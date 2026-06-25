"""把"这一轮检索到哪些文档"从工具里带回接口，用于回答的"引用来源"。

难点：Agent 的工具只能返回字符串给模型，没法直接把结构化的来源传回接口。
办法：用 ContextVar 当"每次请求专属的小篮子"——检索工具把来源放进篮子，
接口在 Agent 跑完后从篮子里取。

为什么按请求隔离：ContextVar 在每个异步任务里互不干扰，而每个 HTTP 请求是
独立任务，所以并发请求各放各的篮子，不会串。
"""

from contextvars import ContextVar

# 篮子：存本次请求检索到的来源 [{document_id, document_name}, ...]
_sources: ContextVar[list[dict] | None] = ContextVar("rag_sources", default=None)


def begin_capture() -> None:
    """请求开始时放一个空篮子。"""
    _sources.set([])


def record_sources(items: list[dict]) -> None:
    """检索工具调用：把这次检索到的来源放进篮子(没篮子就忽略)。"""
    bucket = _sources.get()
    if bucket is not None:
        bucket.extend(items)


def get_captured() -> list[dict]:
    """接口读取：取出本次请求记录的所有来源。"""
    return _sources.get() or []
