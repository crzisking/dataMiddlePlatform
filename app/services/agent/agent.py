"""多轮对话 Agent（基于 LangGraph 的工具调用 Agent）。

不写死流程：由模型根据用户问题，**自主决定调用哪个工具（见 tools.py）**、
可多步循环（调用→看结果→再调用），直到给出答案。

多轮记忆（方案 B，已定）：
- **以自建的会话表/消息表为唯一真相**，Agent 本身**无状态**——每次把"历史消息 + 本轮"
  作为一个完整列表喂进来，不依赖 LangGraph checkpointer 做持久化。
- 历史从哪来分两端：网页端由服务端从 PG 取（P4 实现）、桌面端由客户端本地组装后随请求带上。
  两端最终都归一成"准备好一个消息列表 → 喂给 Agent"。
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, AnyMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from app.services.agent.tools import TOOLS
from app.services.llm.client import DEFAULT_MODEL, get_chat_model

SYSTEM_PROMPT = (
    "你是制造业数据中台的智能助手。\n"
    "你可以调用工具来回答用户问题：\n"
    "- 文档 / 规范 / 流程 / 标准等知识类问题 → 用知识库检索工具；\n"
    "- 订单 / 产量 / 库存 / 质量等数据统计类问题 → 用业务数据库查询工具；\n"
    "- 复杂问题可多次、组合调用工具，并综合结果作答。\n"
    "若工具无法给出答案，如实说明，不要编造。请用中文回答。"
)


# lru_cache：每个模型的 Agent 只构建一次后复用（构建会编译 LangGraph 图，有开销）。
# 无 checkpointer：Agent 无状态，历史由调用方（消息列表）提供，故可安全跨请求复用。
@lru_cache(maxsize=8)
def get_agent(model: str = DEFAULT_MODEL) -> CompiledStateGraph:
    """按所选模型构建（并缓存）一个工具调用 Agent。"""
    llm = get_chat_model(model)
    return create_agent(
        llm,
        tools=TOOLS,  # 可调用的工具/skill 列表；模型自主决定调哪个
        system_prompt=SYSTEM_PROMPT,  # 告诉模型何时调哪个工具的「岗位说明」
    )


async def run_agent(
    message: str,
    model: str | None = None,
    history: list[AnyMessage] | None = None,
) -> str:
    """跑一轮对话。

    history：本会话此前的消息（由调用方从 PG / 客户端取来）。Agent 无状态，
    多轮上下文完全靠这里传入，而非框架内部记忆。
    """
    agent = get_agent(model or DEFAULT_MODEL)
    result = await agent.ainvoke({"messages": _build_messages(message, history)})
    # 返回的 messages 是「本轮完整轨迹」（含工具调用过程），最后一条才是给用户的最终答复。
    return result["messages"][-1].content


async def stream_agent(
    message: str,
    model: str | None = None,
    history: list[AnyMessage] | None = None,
) -> AsyncGenerator[str, None]:
    """流式跑一轮对话，逐 token 产出最终答案文本（供 SSE 推给前端）。

    一期只流「最终答案」：工具调用阶段模型输出的 content 基本为空，自然被跳过；
    工具进度提示（如"正在查询数据库…"）作为 P4/P6 增强。
    """
    agent = get_agent(model or DEFAULT_MODEL)
    # stream_mode="messages"：按 LLM 生成的 token 流式产出（而非按节点）。
    async for chunk, _meta in agent.astream(
        {"messages": _build_messages(message, history)},
        stream_mode="messages",
    ):
        # 只取模型回答的文本增量；工具消息 / 空 content 跳过。
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content:
            yield chunk.content


def _build_messages(message: str, history: list[AnyMessage] | None) -> list[AnyMessage]:
    """历史 + 本轮新消息，拼成喂给 Agent 的完整列表。"""
    messages: list[AnyMessage] = list(history or [])
    messages.append(HumanMessage(content=message))
    return messages
