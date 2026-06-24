"""Agent 可调用的工具（skill）注册表。

每个工具是一个带 @tool 的函数，函数的 docstring 会作为「工具说明」喂给模型，
模型据此自主决定何时调用、传什么参数。**新增一个能力 = 在这里加一个工具并登记到 TOOLS。**

当前为骨架：工具内部是占位，待对应阶段接入真实实现：
- search_knowledge_base  → P4 接入 RAG 检索
- query_business_database → P5 接入 TextToSQL
"""

from langchain_core.tools import tool


@tool
async def search_knowledge_base(query: str) -> str:
    """检索企业知识库，回答文档/规范/流程类问题。

    适用：SOP、工艺文件、质量手册、设备手册、制度等**非结构化文档**里的知识。
    参数 query 为要检索的自然语言问题或关键词。
    """
    # TODO(P4): 接入 RAG 检索（向量召回 + rerank + 拼接）
    return "（知识库检索尚未实现：P4 接入 RAG）"


@tool
async def query_business_database(question: str) -> str:
    """查询业务数据库，回答订单/产量/库存/质量等**结构化数据**统计问题。

    数据全部在 SQL Server。参数 question 为自然语言描述的数据问题，
    例如「上个月华东区订单量」。内部会生成并执行只读 SQL。
    """
    # TODO(P5): 接入 TextToSQL（schema 检索 → 生成 SQL → 校验 → 执行）
    return "（业务数据查询尚未实现：P5 接入 TextToSQL）"


# 工具注册表：Agent 启动时拿到这一份列表。新增 skill 在此追加。
TOOLS = [
    search_knowledge_base,
    query_business_database,
]
