"""TextToSQL SQL 安全护栏（validate.py）的单测。

护栏是只读生产库前的最后一道防线，必须覆盖到：放行正常 SELECT、注入行数上限、
挡住写操作/多语句/越权表/缺过滤。纯逻辑、不连任何数据库。
"""

import pytest

from app.services.texttosql.validate import ensure_row_limit, validate

ALLOWED = {"v_ai_defect"}


def test_normal_select_passes_and_gets_top():
    sql = "SELECT line, defect_qty FROM v_ai_defect WHERE close_date >= '2024-01-01'"
    out = validate(sql, allowed_views=ALLOWED, required_filter="close_date", max_rows=500)
    assert "TOP 500" in out
    assert "v_ai_defect" in out


def test_existing_top_not_doubled():
    sql = "SELECT TOP 10 line FROM v_ai_defect WHERE close_date >= '2024-01-01'"
    out = validate(sql, allowed_views=ALLOWED, required_filter="close_date")
    assert out.lower().count("top") == 1


def test_distinct_keeps_order():
    out = ensure_row_limit("SELECT DISTINCT line FROM v_ai_defect", 100)
    assert out.lower().startswith("select distinct top 100")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE v_ai_defect SET x=1",
        "SELECT * FROM v_ai_defect; DROP TABLE v_ai_defect",
        "SELECT * FROM v_ai_defect WHERE 1=1; SELECT 1",
        "DELETE FROM v_ai_defect",
        "SELECT * INTO bak FROM v_ai_defect",
        "EXEC sp_who",
    ],
)
def test_dangerous_sql_rejected(sql):
    with pytest.raises(ValueError):
        validate(sql, allowed_views=ALLOWED, required_filter=None)


def test_unauthorized_table_rejected():
    sql = "SELECT * FROM secret_table WHERE close_date >= '2024-01-01'"
    with pytest.raises(ValueError, match="未授权"):
        validate(sql, allowed_views=ALLOWED, required_filter="close_date")


def test_missing_required_filter_rejected():
    sql = "SELECT line, defect_qty FROM v_ai_defect"
    with pytest.raises(ValueError, match="过滤列"):
        validate(sql, allowed_views=ALLOWED, required_filter="close_date")


def test_non_select_rejected():
    with pytest.raises(ValueError):
        validate("WITH x AS (SELECT 1) SELECT * FROM x", allowed_views=ALLOWED)
