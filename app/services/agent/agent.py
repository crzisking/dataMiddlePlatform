"""多轮对话 Agent：整个问答的"大脑"。

它是一个"工具调用 Agent"——不是我们写死"先查这、再查那"，而是把能力做成
一个个工具(见 tools.py)，由大模型自己看用户问题，决定调哪个工具、调几次、
怎么综合，直到能回答(这套循环由 LangGraph 框架负责)。

关于"记忆"(已定方案 B)：
  Agent 本身不记任何东西(无状态)。每次请求都把"这个会话之前的消息 + 本轮新消息"
  作为一个完整列表喂进来，模型就有了上下文。历史从哪来分两端：
  网页端由服务端从数据库取(P4 做)，桌面端由客户端本地带上来。
  好处：会话历史完全由我们自己的表掌控，不依赖框架内部那套记忆。
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, AnyMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from app.services.agent.tools import TOOLS
from app.services.llm.client import DEFAULT_MODEL, get_chat_model

# 给模型的"岗位说明"：告诉它有哪些工具、什么场景该用哪个。模型据此自己决定怎么调。
SYSTEM_PROMPT = (
    "你是制造业数据中台的智能助手。\n"
    "你可以调用工具来回答用户问题：\n"
    "- 文档 / 规范 / 流程 / 标准等知识类问题 → 用知识库检索工具；\n"
    "- 订单 / 产量 / 库存 / 质量等数据统计类问题 → 用业务数据库查询工具；\n"
    "- 复杂问题可多次、组合调用工具，并综合结果作答。\n"
    # 关键：知识类问题每一轮都要重新检索，不能凭对话历史/记忆直接作答。
    # 原因有二：① 只有本轮真的检索了，回答才会带上「引用来源 + 下载链接」(来源是检索时旁路采集的)；
    # ② 重新检索能拿到最准的依据，避免吃过时的历史上下文、避免"加戏"编造。
    "重要：只要是知识类问题，即使对话历史里看起来已经有答案，你也必须重新调用知识库检索工具，"
    "依据本轮检索结果作答，不要仅凭历史或记忆回答。\n"
    "若工具无法给出答案，如实说明，不要编造。请用中文回答。"
)


# 把构建好的 Agent 缓存起来，每个模型只构建一次。
# 为什么：构建 Agent 要编译一张 LangGraph 流程图，有开销；而 Agent 本身无状态，
# 同一个模型的 Agent 可以被所有请求安全复用(各请求的历史是各自传进去的，不会串)。
@lru_cache(maxsize=8)
def get_agent(model: str = DEFAULT_MODEL) -> CompiledStateGraph:
    """按所选模型构建(并缓存)一个工具调用 Agent。"""
    llm = get_chat_model(model)
    return create_agent(
        llm,
        tools=TOOLS,  # 它能调用的工具清单；调哪个由模型自己决定
        system_prompt=SYSTEM_PROMPT,  # 上面那段岗位说明
    )


async def run_agent(
    message: str,
    model: str | None = None,
    history: list[AnyMessage] | None = None,
) -> str:
    """跑一轮对话，一次性返回最终答案文本。

    history 是本会话之前的消息(调用方从数据库或客户端取来)。多轮上下文全靠它传入。
    """
    agent = get_agent(model or DEFAULT_MODEL)
    result = await agent.ainvoke({"messages": _build_messages(message, history)})
    # result["messages"] 是这一轮的"完整过程"(包含模型调工具、工具返回等中间消息)，
    # 最后一条才是给用户看的最终回答。
    return result["messages"][-1].content


async def stream_agent(
    message: str,
    model: str | None = None,
    history: list[AnyMessage] | None = None,
) -> AsyncGenerator[str, None]:
    """跑一轮对话，但把最终答案"一个字一个字"地吐出来(给前端做打字机效果/SSE)。

    一期只流式输出"最终答案"：模型在调工具那几步产生的 content 基本是空的，
    会被下面的判断自然跳过。把"正在查询数据库…"这类工具进度也推给前端，是后续增强。
    """
    agent = get_agent(model or DEFAULT_MODEL)
    # stream_mode="messages"：让框架按"模型生成的 token"逐个吐出来，而不是等整段算完
    async for chunk, _meta in agent.astream(
        {"messages": _build_messages(message, history)},
        stream_mode="messages",
    ):
        # 只取"模型回答的文本片段"。工具相关的消息、以及 content 为空的片段都跳过。
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content:
            yield chunk.content


def _build_messages(message: str, history: list[AnyMessage] | None) -> list[AnyMessage]:
    """把"历史消息 + 本轮新消息"拼成一个完整列表，喂给 Agent。"""
    messages: list[AnyMessage] = list(history or [])
    messages.append(HumanMessage(content=message))
    return messages
