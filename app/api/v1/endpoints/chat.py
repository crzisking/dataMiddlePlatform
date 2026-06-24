"""对话接口：调用多轮工具调用 Agent。

对话记忆采用方案 B（自建会话/消息表为唯一真相，Agent 无状态）：
- 桌面端：直接在 history 里带上本地组装的历史。
- 网页端：传 conversation_id，由服务端从 PG 会话/消息表取历史填充（P4 实现）。
- 流式输出（SSE）留待 P4，这里先做一次性返回。
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
    """一轮历史消息（前端/客户端传入的最简结构）。"""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    # Field(...) 里的 ... 表示必填；description 会自动出现在 /docs 接口文档里。
    message: str = Field(..., description="用户本轮输入")
    # 会话 ID：网页端据此让服务端从 PG 取历史（P4）；也用于日志/追踪。
    conversation_id: str = Field("default", description="会话 ID")
    # 历史消息：桌面端在此带上本地历史；网页端可不传（服务端按 conversation_id 取）。
    history: list[ChatTurn] = Field(default_factory=list, description="本会话历史消息")
    # 模型由用户在对话中自选；不传则后端用默认模型。
    model: str | None = Field(None, description="所选模型，不传用默认")


class ChatResponse(BaseModel):
    answer: str
    model: str
    conversation_id: str


def _to_messages(turns: list[ChatTurn]) -> list[AnyMessage]:
    """把接口的 {role, content} 历史转成 LangChain 消息对象。"""
    return [
        HumanMessage(content=t.content)
        if t.role == "user"
        else AIMessage(content=t.content)
        for t in turns
    ]


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """一次性返回：等 Agent 全部跑完一把返回。供不需要流式的场景（如批处理、桌面端简单调用）。"""
    model = req.model or DEFAULT_MODEL
    # TODO(P4): 网页端在此按 conversation_id 从 PG 会话/消息表加载历史，合并进 history。
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
    """流式返回（SSE）：逐 token 推送最终答案，前端边收边显示。

    事件约定：
    - 多条 `data: <文本增量>`（默认 event，无名）
    - 末尾一条 `event: done`，标志本轮结束
    EventSourceResponse 会在客户端断开时自动停止生成器，避免空跑大模型。
    """
    model = req.model or DEFAULT_MODEL

    async def event_source():
        async for token in stream_agent(
            message=req.message,
            model=model,
            history=_to_messages(req.history),
        ):
            yield {"data": token}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_source())
