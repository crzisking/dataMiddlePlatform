"""SQL 安全护栏：执行大模型生成的 SQL 前先把关，挡住危险/失控的语句。

业务库是**只读生产库**，模型生成的 SQL 绝不能写、不能跨表乱查、不能全表扫。这里在执行前
逐条校验并加固（D1）。即使只读账号已兜底，这一层也必不可少（纵深防御）。

把的几道关：
- 只允许单条 SELECT（禁多语句、禁 `;` 拼接、禁任何写/DDL/EXEC）。
- 只能查白名单视图/表（语义层登记过的那些），碰别的一律拒。
- 强制行数上限（注入 TOP n），防一次拉回海量数据。
- 必带过滤列在的检查（大表必须按日期等过滤，否则拒绝让模型重写）。

校验不通过抛 ValueError，调用方（query.py）据此让模型重试或返回可读提示。
"""

import re

# 一旦出现这些关键词就直接拒（写操作、DDL、执行存储过程、权限变更等）。
# 用单词边界匹配，避免误伤列名里含这些子串的情况。
_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "merge", "exec", "execute", "grant", "revoke", "into", "sp_", "xp_",
)


def _strip_comments(sql: str) -> str:
    """去掉 SQL 注释（-- 行注释 和 /* */ 块注释），避免有人把危险语句藏在注释后绕过检查。"""
    sql = re.sub(r"--[^\n]*", " ", sql)  # 行注释
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)  # 块注释
    return sql


def _normalize(name: str) -> str:
    """把表/视图标识符规整成可比较的形式：去掉中括号、库/schema 前缀，转小写。

    例：`[dbo].[v_ai_x]` → `v_ai_x`。这样和语义层里登记的 object_name 比对才对得上。
    """
    name = name.replace("[", "").replace("]", "").strip().lower()
    return name.split(".")[-1]  # 取最后一段（去掉 dbo. / 库名. 前缀）


def _extract_sources(sql: str) -> set[str]:
    """抽出 SQL 里所有 FROM / JOIN 后面的表/视图名（规整后）。

    用来核对"只查了白名单对象"。不是完整 SQL 解析，但配合只读账号 + SELECT-only 足够兜底。
    """
    found = re.findall(r"\b(?:from|join)\s+([A-Za-z_\[][\w\.\[\]]*)", sql, flags=re.IGNORECASE)
    return {_normalize(f) for f in found}


def ensure_row_limit(sql: str, max_rows: int) -> str:
    """保证有行数上限：没写 TOP 就在 SELECT 后注入 `TOP {max_rows}`。

    SQL Server 用 `SELECT TOP n ...` 限制返回行数。已经有 TOP 的就不动。
    注意 DISTINCT 要排在 TOP 前面（`SELECT DISTINCT TOP n` 是错的，得 `SELECT TOP n DISTINCT`...
    实际 SQL Server 写法是 `SELECT DISTINCT TOP n`），这里按 `SELECT [DISTINCT] TOP n` 注入。
    """
    if re.match(r"^\s*select\s+(distinct\s+)?top\b", sql, flags=re.IGNORECASE):
        return sql  # 已有 TOP
    # 在开头的 SELECT（及可选 DISTINCT）后面插入 TOP n
    return re.sub(
        r"^(\s*select\s+)(distinct\s+)?",
        lambda m: f"{m.group(1)}{m.group(2) or ''}TOP {max_rows} ",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def validate(
    sql: str,
    *,
    allowed_views: set[str],
    required_filter: str | None = None,
    max_rows: int = 1000,
) -> str:
    """校验并加固一条生成的 SQL，返回可安全执行的 SQL；不通过抛 ValueError。

    allowed_views：本次允许查询的视图/表名集合（来自语义层检索结果）。
    required_filter：必带的过滤列（大表防全表扫）；SQL 里没出现这一列就拒绝。
    max_rows：行数上限，会注入成 TOP。
    """
    raw = _strip_comments(sql).strip().rstrip(";").strip()
    if not raw:
        raise ValueError("生成的 SQL 为空")

    low = raw.lower()

    # 关 1：只允许单条语句。去掉结尾分号后，中间不应再有分号。
    if ";" in raw:
        raise ValueError("只允许单条 SQL，不能包含多条语句")

    # 关 2：必须以 SELECT 开头（一期不支持 WITH/CTE，单视图查询用不到，简单更安全）
    if not low.startswith("select"):
        raise ValueError("只允许 SELECT 查询")

    # 关 3：不得出现任何写操作/DDL/执行类关键词
    for kw in _FORBIDDEN:
        if re.search(rf"\b{re.escape(kw)}", low):
            raise ValueError(f"SQL 含禁止的关键词：{kw}")

    # 关 4：只能查白名单对象
    allowed = {_normalize(v) for v in allowed_views}
    sources = _extract_sources(raw)
    if not sources:
        raise ValueError("未识别到查询的表/视图")
    illegal = sources - allowed
    if illegal:
        raise ValueError(f"查询了未授权的表/视图：{', '.join(sorted(illegal))}")

    # 关 5：大表必带过滤列（防全表扫）。这里只校验"出现了该列"，
    # 具体范围由模型按提示词带（默认时间窗）。没带就拒绝，让上层让模型重写。
    if required_filter and required_filter.lower() not in low:
        raise ValueError(f"查询必须带过滤列【{required_filter}】（防止全表扫描）")

    # 加固：注入行数上限
    return ensure_row_limit(raw, max_rows)
