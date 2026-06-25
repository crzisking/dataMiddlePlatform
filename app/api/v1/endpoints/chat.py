"""对话接口：把用户的问题交给多轮对话 Agent，返回回答 + 引用来源。

提供两个接口：
- POST /chat        一次性返回完整答案(等 Agent 全跑完)。
- POST /chat/stream 流式返回(SSE)，一个字一个字推给前端，做打字机效果。

历史(方案 B：自建会话表为准)的两种来源，由 persist 决定：
- persist=True (默认，网页端)：服务端按 conversation_id 从数据库读历史、答完写回。
- persist=False (桌面端)：用请求里带来的 history，服务端不读不写库。

引用来源：回答用到的文档会在 sources 里给出，含可直接下载原件的 MinIO 链接。
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.exceptions import BadRequestError
from app.db.session import get_session
from app.models.document import Document
from app.services.agent.agent import run_agent, stream_agent
from app.services.agent.context import begin_capture, get_captured
from app.services.chat.history import append_turn, load_history
from app.services.llm.client import DEFAULT_MODEL, available_models
from app.services.storage.minio_client import presigned_get_url

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
    conversation_id: str = Field("default", description="会话 ID")
    # persist=True：服务端按 conversation_id 存取历史(网页端)。
    # persist=False：用下面的 history，不碰数据库(桌面端)。
    persist: bool = Field(True, description="是否由服务端存取历史")
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


async def _resolve_history(req: "ChatRequest", session: AsyncSession) -> list[AnyMessage]:
    """按 persist 决定历史从哪来：数据库 或 请求自带。"""
    if req.persist:
        return await load_history(session, req.conversation_id)
    return _to_messages(req.history)


async def _build_sources(session: AsyncSession) -> list[SourceOut]:
    """把本轮检索记录下的来源，整理成带下载链接的列表(按文档去重)。"""
    captured = get_captured()
    # 按 document_id 去重，保留首次出现的顺序
    seen: set[int] = set()
    ids: list[int] = []
    for s in captured:
        did = s["document_id"]
        if did not in seen:
            seen.add(did)
            ids.append(did)
    if not ids:
        return []

    docs = (await session.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
    by_id = {d.id: d for d in docs}
    sources = []
    for did in ids:
        doc = by_id.get(did)
        if doc is not None:
            sources.append(
                SourceOut(
                    document_id=doc.id,
                    document_name=doc.name,
                    download_url=presigned_get_url(doc.object_key),
                )
            )
    return sources


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    """一次性返回：等 Agent 完全跑完，一把返回答案 + 引用来源。"""
    model = _resolve_model(req.model)
    history = await _resolve_history(req, session)

    begin_capture()  # 开一个空篮子，准备收集本轮检索到的来源
    answer = await run_agent(message=req.message, model=model, history=history)
    sources = await _build_sources(session)

    if req.persist:
        await append_turn(
            session, req.conversation_id, user_text=req.message, assistant_text=answer
        )
        await session.commit()
    return ChatResponse(
        answer=answer, model=model, conversation_id=req.conversation_id, sources=sources
    )


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    """流式返回(SSE)：逐字推送答案，末尾再推一条 sources(引用来源)，最后 done。"""
    model = _resolve_model(req.model)
    history = await _resolve_history(req, session)

    async def event_source():
        begin_capture()
        pieces: list[str] = []
        async for token in stream_agent(message=req.message, model=model, history=history):
            pieces.append(token)
            yield {"data": token}

        # 答案流完后：推一条 sources 事件(JSON)，再存库，最后 done
        sources = await _build_sources(session)
        yield {
            "event": "sources",
            "data": json.dumps([s.model_dump() for s in sources], ensure_ascii=False),
        }
        if req.persist:
            await append_turn(
                session,
                req.conversation_id,
                user_text=req.message,
                assistant_text="".join(pieces),
            )
            await session.commit()
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_source())
