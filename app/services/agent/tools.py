"""Agent 能调用的"工具"清单（也叫 skill）。

每个工具就是一个加了 @tool 的函数。关键点：函数的 docstring(三引号说明)
会被当成"工具说明书"原样喂给大模型——模型就是靠读这段说明，来判断
"用户这个问题该不该用这个工具、要传什么参数"。所以 docstring 要写清楚
"这个工具干嘛的、什么时候用、参数是什么"。

加一个新能力 = 在这里写一个新函数 + 登记到底部的 TOOLS 列表，主流程不用改。

- search_knowledge_base  → 已接入 RAG 混合检索(P4)
- query_business_database → 已接入 TextToSQL 链路(P5)；语义层无视图时安全短路、不碰生产库
"""

from langchain_core.tools import tool

from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.agent.context import record_sources
from app.services.rag.retrieval import hybrid_search
from app.services.texttosql.query import answer_business_question

logger = get_logger(__name__)


@tool
async def search_knowledge_base(query: str) -> str:
    """检索企业知识库，回答"文档/规范/流程/标准/代码含义"类问题。

    什么时候用：用户问某项作业怎么做、某流程/规范是什么、某代码代表什么、某制度如何规定——
    答案在文档里（SOP、工艺文件、质量手册、设备手册、操作说明、ERP 代码表等）。
    不要用在"查实际数据/统计数字"上（那是 query_business_database）。

    参数 query：要检索的自然语言问题或关键词，尽量带上关键术语/编号（如"I2Q8 计价工时"）。
    """
    # 工具在 worker/接口之外被 Agent 调用，没有现成的 session，自己开一个。
    # 兜底：检索若因 embedding/DB 临时异常抛错，返回可读提示而不是让整轮对话 500——
    # 让模型能如实告知用户"查询失败"，而不是崩在半路。
    try:
        async with async_session_factory() as session:
            hits = await hybrid_search(session, query, top_k=5)
    except Exception:
        logger.exception("知识库检索失败 query=%s", query)
        return "知识库检索暂时失败，请稍后重试。"

    if not hits:
        return "知识库中没有找到相关内容。"
    # 记录来源(文档 id/名字)，供接口生成"引用来源 + 下载链接"
    record_sources(
        [{"document_id": h["document_id"], "document_name": h["document_name"]} for h in hits]
    )
    # 把检索到的片段拼成带来源的文本，交给模型据此作答。
    # 标上来源，模型回答时可以说明依据，也便于核对。
    parts = [
        f"[资料{i}] 来源：{h['document_name']}\n{h['content']}"
        for i, h in enumerate(hits, 1)
    ]
    return "\n\n".join(parts)


@tool
async def query_business_database(question: str) -> str:
    """查询业务数据库，回答"实际数据/统计数字"类问题（订单/产量/库存/不良/工时等）。

    什么时候用：用户问"多少、几件、合计、平均、排名、某时间段的实际数值"等需要从业务库算出来的数据。
    不要用在"文档/规范/流程"类问题上（那是 search_knowledge_base）。

    参数 question：自然语言描述的数据问题，如"上月各产线不良数"。内部会转成只读 SQL 查询。
    """
    # 走 TextToSQL 完整链路：检索相关视图 → 生成 SQL → 安全护栏 → 只读执行 → 返回结果文本。
    # 语义层还没登记任何视图时，链路会在第一步短路、返回"未配置"，不会去碰业务生产库。
    return await answer_business_question(question)


# 工具注册表：构建 Agent 时会把这一份列表交给它。新增工具记得加到这里。
TOOLS = [
    search_knowledge_base,
    query_business_database,
]
