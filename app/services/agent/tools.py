"""Agent 能调用的"工具"清单（也叫 skill）。

每个工具就是一个加了 @tool 的函数。关键点：函数的 docstring(三引号说明)
会被当成"工具说明书"原样喂给大模型——模型就是靠读这段说明，来判断
"用户这个问题该不该用这个工具、要传什么参数"。所以 docstring 要写清楚
"这个工具干嘛的、什么时候用、参数是什么"。

加一个新能力 = 在这里写一个新函数 + 登记到底部的 TOOLS 列表，主流程不用改。

当前是骨架：工具内部还是占位，等对应阶段接真实实现：
- search_knowledge_base  → P4 接入 RAG 检索
- query_business_database → P5 接入 TextToSQL
"""

from langchain_core.tools import tool


@tool
async def search_knowledge_base(query: str) -> str:
    """检索企业知识库，回答文档/规范/流程类问题。

    适用：SOP、工艺文件、质量手册、设备手册、制度等"文档里写的知识"。
    参数 query 是要检索的自然语言问题或关键词。
    """
    # TODO(P4): 接入真正的 RAG 检索(向量召回 + 重排 + 拼接上下文)
    return "（知识库检索尚未实现：P4 接入 RAG）"


@tool
async def query_business_database(question: str) -> str:
    """查询业务数据库，回答订单/产量/库存/质量等"数据统计"类问题。

    数据都在 SQL Server。参数 question 是自然语言描述的数据问题，
    比如"上个月华东区订单量"。内部会把它转成只读 SQL 去查。
    """
    # TODO(P5): 接入 TextToSQL(找相关表 → 生成 SQL → 校验 → 执行)
    return "（业务数据查询尚未实现：P5 接入 TextToSQL）"


# 工具注册表：构建 Agent 时会把这一份列表交给它。新增工具记得加到这里。
TOOLS = [
    search_knowledge_base,
    query_business_database,
]
