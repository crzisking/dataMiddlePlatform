"""TextToSQL 主链路：把"自然语言问题"变成"业务库查询结果文本"。

串起四步（详见 TextToSQL.md 第七节）：
  ① 检索相关视图/表（schema-RAG，B4）
  ② 让模型据此生成 SQL（C1）
  ③ 安全护栏校验+加固（D1）
  ④ 只读执行 + 整理成文本（D2）

被 Agent 的 query_business_database 工具调用（E1）。**语义层为空时第①步就返回空，
直接提示"未配置"，根本不会去碰业务生产库**——这也是开发期的天然保护。
"""

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.texttosql.db import run_query
from app.services.texttosql.generate import generate_sql
from app.services.texttosql.semantic_layer import render_ddl_card, retrieve_schemas
from app.services.texttosql.validate import validate

logger = get_logger(__name__)

_MAX_ROWS = 1000  # 单次查询返回行数上限（护栏）


def _format_rows(rows: list[dict]) -> str:
    """把查询结果行整理成给模型/用户看的紧凑文本。空结果明确说明。"""
    if not rows:
        return "查询成功，但没有符合条件的数据。"
    headers = list(rows[0].keys())
    lines = [" | ".join(headers)]
    for r in rows:
        lines.append(" | ".join("" if r[h] is None else str(r[h]) for h in headers))
    note = f"（共 {len(rows)} 行" + ("，已达上限" if len(rows) >= _MAX_ROWS else "") + "）"
    return "\n".join(lines) + "\n" + note


async def answer_business_question(question: str, model: str | None = None) -> str:
    """跑完整 TextToSQL 链路，返回结果文本（或可读的失败说明）。"""
    if not settings.mssql_configured:
        return "业务数据库（SQL Server）未配置，无法查询业务数据。"

    # ① 检索相关视图/表
    async with async_session_factory() as session:
        schemas = await retrieve_schemas(session, question, top_k=3)
    if not schemas:
        # 语义层还没登记任何视图（或都没向量化）→ 不去碰业务库，直接说明
        return "尚未配置业务数据视图（语义层为空），暂时无法查询业务数据。"

    # ② 生成 SQL（只喂检索命中的视图说明）
    cards = [render_ddl_card(d) for d in schemas]
    sql = await generate_sql(question, cards, model=model)

    # ③ 安全护栏：白名单 = 命中的视图；必带过滤取排名最高那条视图的要求
    allowed = {d.object_name for d in schemas}
    required_filter = schemas[0].required_filter
    try:
        safe_sql = validate(
            sql, allowed_views=allowed, required_filter=required_filter, max_rows=_MAX_ROWS
        )
    except ValueError as e:
        # 生成的 SQL 没过关。记日志（含原始 SQL 便于排查），对外只给可读提示，不暴露 SQL 细节。
        logger.warning("TextToSQL 生成的 SQL 未通过校验：%s | sql=%s", e, sql)
        return f"未能生成安全的查询（{e}）。请把问题问得更具体些。"

    # ④ 只读执行（同步驱动丢线程池），整理结果
    try:
        rows = await run_in_threadpool(run_query, safe_sql, max_rows=_MAX_ROWS)
    except Exception:
        logger.exception("TextToSQL 执行失败 | sql=%s", safe_sql)
        return "业务数据库查询执行失败，请稍后重试或换个问法。"
    return _format_rows(rows)
