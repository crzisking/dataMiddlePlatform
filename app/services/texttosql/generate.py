"""SQL 生成（C1）：把"用户问题 + 检索到的视图说明"交给大模型，产出一条 SQL Server 查询。

只把检索命中的几张视图/表的 DDL 名片喂给模型（绝不喂整库），并注入"今天的日期"好让模型
正确换算"上月/本季"这类相对时间。生成的 SQL 还要再过安全护栏（validate.py）才会执行。
"""

from datetime import datetime

from app.services.llm.client import DEFAULT_MODEL, get_client

# 给模型的指令：约束它只用给定视图、只写只读 SELECT、按要求带过滤、用 SQL Server 语法。
_SYSTEM = (
    "你是 SQL Server 查询生成助手。根据用户问题和下面给出的视图/表说明，生成"
    "**一条** SQL Server 的只读 SELECT 查询。严格遵守：\n"
    "- 只能用下面给出的视图/表和字段，不要臆造表名/列名；\n"
    "- 只写 SELECT，禁止任何写操作、DDL、多条语句、分号拼接；\n"
    "- 用 SQL Server 语法（如限制行数用 `SELECT TOP n`，不是 LIMIT）；\n"
    "- 若说明里标了「必须按某列过滤」，务必在 WHERE 带上该过滤（相对时间按给的今天日期换算）；\n"
    "- 只输出 SQL 本身，不要解释、不要 markdown 代码块。"
)


def _extract_sql(text: str) -> str:
    """从模型输出里抽出纯 SQL：去掉可能的 ```sql ``` 代码块围栏和首尾空白。"""
    t = text.strip()
    if t.startswith("```"):
        # 去掉第一行的 ```sql / ``` 和结尾的 ```
        t = t.split("\n", 1)[-1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


async def generate_sql(question: str, schema_cards: list[str], model: str | None = None) -> str:
    """根据问题 + 视图 DDL 名片，让模型生成一条 SQL。

    schema_cards：检索命中的视图/表，渲染好的 DDL 名片（见 semantic_layer.render_ddl_card）。
    返回纯 SQL 文本（未校验，调用方还要过 validate）。
    """
    today = datetime.now().strftime("%Y-%m-%d")  # 注入今天日期，供模型换算"上月/本季"等相对时间
    user = (
        f"今天是 {today}。\n\n"
        f"可用的视图/表说明：\n" + "\n\n".join(schema_cards) + f"\n\n用户问题：{question}\n\n"
        "请生成对应的 SQL Server 只读 SELECT 查询："
    )
    client = get_client(model or DEFAULT_MODEL)
    resp = await client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        temperature=0,  # 要稳定可复现，关掉随机性
    )
    return _extract_sql(resp.choices[0].message.content or "")
