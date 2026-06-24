"""对话接口：把用户的问题交给多轮对话 Agent，返回回答。

提供两个接口：
- POST /chat        一次性返回完整答案(等 Agent 全跑完)。
- POST /chat/stream 流式返回(SSE)，一个字一个字推给前端，做打字机效果。

关于历史(方案 B：自建会话表为准，Agent 无状态)：
- 桌面端：直接把本地的历史放在请求的 history 里带上来。
- 网页端：带上 conversation_id，由服务端从数据库取历史(P4 实现)。
"""

from typing import Literal

from fastapi import APIRouter
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.agent.agent import run_agent, stream_agent
from app.services.llm.client import DEFAULT_MODEL

router = APIRouter()


class ChatTurn(BaseModel):
    """一条历史消息。role 标明是用户说的还是助手说的。"""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    # Field 的第一个参数 ... 表示"必填"；description 会显示在 /docs 接口文档里。
    message: str = Field(..., description="用户本轮输入")
    # 会话 ID：同一个会话用同一个 id。网页端将来靠它从数据库取历史；也方便日志追踪。
    conversation_id: str = Field("default", description="会话 ID")
    # 历史消息：桌面端把本地历史放这；网页端可不传(以后由服务端按 conversation_id 取)。
    history: list[ChatTurn] = Field(default_factory=list, description="本会话历史消息")
    # 用哪个模型由用户选；不传就用默认模型。
    model: str | None = Field(None, description="所选模型，不传用默认")


class ChatResponse(BaseModel):
    answer: str
    model: str
    conversation_id: str


def _to_messages(turns: list[ChatTurn]) -> list[AnyMessage]:
    """把接口收到的 {role, content} 历史，转成 Agent 能用的 LangChain 消息对象。
    用户说的 → HumanMessage，助手说的 → AIMessage。
    """
    return [
        HumanMessage(content=t.content)
        if t.role == "user"
        else AIMessage(content=t.content)
        for t in turns
    ]


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """一次性返回：等 Agent 完全跑完，一把返回答案。适合不需要打字机效果的场景。"""
    model = req.model or DEFAULT_MODEL
    # TODO(P4): 网页端在这里按 conversation_id 从数据库把历史读出来，合并进 history。
    answer = await run_agent(
        message=req.message,
        model=model,
        history=_to_messages(req.history),
    )
    return ChatResponse(
        answer=answer,
        model=model,
        conversation_id=req.conversation_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    """流式返回(SSE)：把答案逐字推给前端，边生成边显示。

    返回的数据格式(SSE 约定)：
    - 多条 `data: <文本片段>`，拼起来就是完整答案；
    - 最后一条 `event: done` 表示这轮结束。
    另外：用户中途关掉页面(连接断开)时，EventSourceResponse 会自动停止下面的
    生成器，避免大模型还在后台空跑、白花钱。
    """
    model = req.model or DEFAULT_MODEL

    async def event_source():
        # 每产出一个文本片段，就作为一条 SSE data 推给前端
        async for token in stream_agent(
            message=req.message,
            model=model,
            history=_to_messages(req.history),
        ):
            yield {"data": token}
        # 结束信号
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_source())
