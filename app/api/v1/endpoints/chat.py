"""对话接口：把用户的问题交给多轮对话 Agent，返回回答 + 引用来源。

提供两个接口：
- POST /chat        一次性返回完整答案(等 Agent 全跑完)。
- POST /chat/stream 流式返回(SSE)，一个字一个字推给前端，做打字机效果。

历史(方案 B：自建会话表为准)的两种来源，由 persist 决定：
- persist=True (默认，网页端)：服务端按 conversation_id 从数据库读历史、答完写回。
  **注意：此模式下请求里的 history 字段被忽略**，历史一律以数据库为准。
- persist=False (桌面端)：用请求里带来的 history，服务端不读不写库。

会话 ID（conversation_id）的约定（"开新对话 vs 接着聊"靠它区分）：
- **不传**：服务端**生成一个新的会话 ID**（= 开一个新对话），并在响应里返回，前端存下来。
- **传上次返回的 ID**：接着那个对话聊（追加到它的历史）。
- 想开新对话：前端别传 ID（或换个新 ID），服务端就给个全新的。
- 不再有共享的 "default" 默认值——避免所有人挤进同一个对话、历史串台。

引用来源：回答用到的文档会在 sources 里给出，含可直接下载原件的 MinIO 链接。
"""

import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.exceptions import BadRequestError
from app.db.session import get_session
from app.services.agent.agent import run_agent, stream_agent
from app.services.agent.context import begin_capture, get_captured
from app.services.chat.history import append_turn, load_history
from app.services.chat.sources import attach_download_urls, dedupe_sources
from app.services.llm.client import DEFAULT_MODEL, available_models

router = APIRouter()


class ChatTurn(BaseModel):
    """一条历史消息。role 标明是用户说的还是助手说的。"""

    role: Literal["user", "assistant"]
    content: str


class SourceOut(BaseModel):
    """回答引用的一个来源文档。"""

    document_id: int
    document_name: str
    download_url: str  # MinIO 预签名链接，点开即可下载原件(限时有效)


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户本轮输入")
    # 不传=开新对话(服务端生成并在响应里返回)；传上次的 ID=接着那个对话聊。
    conversation_id: str | None = Field(
        None, description="会话 ID。不传则新建一个并在响应返回；传上次返回的 ID 则接着聊"
    )
    # persist=True：服务端按 conversation_id 存取历史(网页端)，此时忽略下面的 history。
    # persist=False：用下面的 history，不碰数据库(桌面端)。
    persist: bool = Field(True, description="是否由服务端存取历史(True 时忽略 history 字段)")
    history: list[ChatTurn] = Field(default_factory=list, description="persist=False 时带上的历史")
    model: str | None = Field(None, description="所选模型，不传用默认")


class ChatResponse(BaseModel):
    answer: str
    model: str
    conversation_id: str
    sources: list[SourceOut]  # 本次回答引用到的文档


def _to_messages(turns: list[ChatTurn]) -> list[AnyMessage]:
    """把请求里的 {role, content} 历史，转成 Agent 能用的消息对象。"""
    return [
        HumanMessage(content=t.content)
        if t.role == "user"
        else AIMessage(content=t.content)
        for t in turns
    ]


def _resolve_model(model: str | None) -> str:
    """不传用默认；传了就必须是白名单里的模型，否则返回清晰的 400(而不是把
    无效模型名发给上游导致 500)。"""
    model = model or DEFAULT_MODEL
    if model not in available_models():
        raise BadRequestError(f"不支持的模型 {model!r}，可选：{', '.join(available_models())}")
    return model


def _resolve_conversation_id(req: "ChatRequest") -> str:
    """定下本轮用哪个会话 ID：传了就用传的(接着聊)，没传就新生成一个(开新对话)。

    用 uuid4().hex 生成一个全局唯一的随机串当 ID，绝不会和别的会话撞，
    也就不会再出现以前所有人挤进 "default" 一个会话的串台问题。
    """
    return req.conversation_id or uuid4().hex


async def _resolve_history(
    req: "ChatRequest", conversation_id: str, session: AsyncSession
) -> list[AnyMessage]:
    """按 persist 决定历史从哪来：数据库 或 请求自带。

    persist=True 时按 conversation_id 从库里取(新生成的 ID 自然取到空历史=干净新对话)；
    persist=False 时用请求带来的 history。
    """
    if req.persist:
        return await load_history(session, conversation_id)
    return _to_messages(req.history)


async def _build_sources(session: AsyncSession) -> tuple[list[SourceOut], list[dict]]:
    """把本轮检索记录下的来源，整理成两份：

    - 返回给前端的 SourceOut 列表(带现签下载链接)；
    - 去重后的原始来源 [{document_id, document_name}]，用来存进消息(不含链接，链接会过期)。

    去重 + 加链接的具体逻辑下沉到 services/chat/sources.py，和历史回看共用同一套。
    """
    deduped = dedupe_sources(get_captured())
    rows = await attach_download_urls(session, deduped)
    return [SourceOut(**r) for r in rows], deduped


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """一次性返回：等 Agent 完全跑完，一把返回答案 + 引用来源。"""
    model = _resolve_model(req.model)
    conversation_id = _resolve_conversation_id(req)  # 没传则新建，返回里带回去
    history = await _resolve_history(req, conversation_id, session)

    begin_capture()  # 开一个空篮子，准备收集本轮检索到的来源
    answer = await run_agent(message=req.message, model=model, history=history)
    sources, captured = await _build_sources(session)

    if req.persist:
        await append_turn(
            session,
            conversation_id,
            user_text=req.message,
            assistant_text=answer,
            sources=captured,  # 把本轮来源一起存进助手消息，历史回看时能还原
        )
        await session.commit()
    return ChatResponse(
        answer=answer, model=model, conversation_id=conversation_id, sources=sources
    )


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """流式返回(SSE)：先推一条 meta(会话 ID)，再逐字推答案，然后 sources，最后 done。"""
    model = _resolve_model(req.model)
    conversation_id = _resolve_conversation_id(req)
    history = await _resolve_history(req, conversation_id, session)

    async def event_source():
        # 先告诉前端本轮的会话 ID：新对话时这是服务端新生成的，前端要存下来用于后续追问。
        yield {"event": "meta", "data": json.dumps({"conversation_id": conversation_id})}

        begin_capture()
        pieces: list[str] = []
        async for token in stream_agent(message=req.message, model=model, history=history):
            pieces.append(token)
            yield {"data": token}

        # 答案流完后：推一条 sources 事件(JSON)，再存库，最后 done
        sources, captured = await _build_sources(session)
        yield {
            "event": "sources",
            "data": json.dumps([s.model_dump() for s in sources], ensure_ascii=False),
        }
        if req.persist:
            await append_turn(
                session,
                conversation_id,
                user_text=req.message,
                assistant_text="".join(pieces),
                sources=captured,  # 同 /chat：把本轮来源存进助手消息
            )
            await session.commit()
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_source())
