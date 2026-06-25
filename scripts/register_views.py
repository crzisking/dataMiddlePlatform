"""【预留模板】把整理好的业务视图登记进语义层（schema_docs）。

用法：等 DBA 把一个业务视图（或要文字描述的裸表）整理好后，照下面 EXAMPLE 的样子
填一条（或多条）到 VIEWS 列表里，然后运行：

    uv run python scripts/register_views.py

它会把每条 upsert 进语义层并向量化（向量化只调通义 API，**不碰业务库 SQL Server**）。
重复运行是安全的：按 object_name 覆盖更新。

⚠️ 现在 VIEWS 里只有一条带 PLACEHOLDER 的示例（enabled=False、字段是占位）。
   你把它替换成真实视图、把 PLACEHOLDER 改掉、enabled 改 True，再运行。
   只要还含 "PLACEHOLDER"，脚本会拒绝运行，免得把占位数据灌进去。
"""

import asyncio
import sys

import app.core.eventloop  # noqa: F401  先设置 Windows 事件循环
from app.db.session import async_session_factory
from app.services.texttosql.semantic_layer import upsert_schema_doc, vectorize

# ── 在这里填你的视图 ────────────────────────────────────────────────────────────
# 一条 = 一个视图（source_type="view"）或一组裸表（source_type="table"，要填 relations）。
# 字段说明见 app/models/schema_doc.py。下面是一条占位示例，照它替换成真实内容。
EXAMPLE = {
    "source_type": "view",                         # view（首选）/ table（裸表兜底）
    "object_name": "v_ai_PLACEHOLDER",             # 视图名，如 v_ai_制程不良明细
    "desc": "PLACEHOLDER：一句话说清这个视图是干嘛的",
    "grain": "PLACEHOLDER：一行 = 一个什么（如 一个批次）",
    "columns": [
        # 每个字段：name 精确列名 / type 类型 / desc 中文含义 / unit 单位 / values 取值范围
        {"name": "PLACEHOLDER_col", "type": "varchar", "desc": "占位字段含义"},
    ],
    "relations": None,                             # 视图通常 None；裸表必填 "A.lot_no = B.lot_no"
    "samples": "PLACEHOLDER：1~2 个典型问法 ↔ SQL 样例",
    "aliases": "PLACEHOLDER：业务术语别名，如 不良=次品=NG",
    # —— 大数据量护栏（千万级表必填，详见 TextToSQL.md 7.3.1）——
    "required_filter": "PLACEHOLDER：必带的过滤列，通常是日期",
    "default_window": "近30天",
    "max_window": "1年",
    "isolation": "nolock",                         # 生产库建议 nolock，避免和业务抢锁
    "enabled": False,                              # 整理好后改 True 才会被检索
}

VIEWS: list[dict] = [
    EXAMPLE,
]
# ────────────────────────────────────────────────────────────────────────────────


def _has_placeholder(views: list[dict]) -> bool:
    """粗查有没有没填的占位符，防止把示例数据误灌进库。"""
    import json

    return "PLACEHOLDER" in json.dumps(views, ensure_ascii=False)


async def main() -> int:
    if _has_placeholder(VIEWS):
        print("VIEWS 里还有 PLACEHOLDER 没填，已拒绝运行。请先填好真实视图再试。")
        return 1

    async with async_session_factory() as session:
        for v in VIEWS:
            doc = await upsert_schema_doc(session, **v)
            if doc.enabled:
                await vectorize(session, doc)  # 启用的才向量化
            await session.commit()
            print(f"已登记：{doc.object_name}（enabled={doc.enabled}）")
    print(f"完成，共 {len(VIEWS)} 条。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
