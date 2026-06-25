"""连接业务库 SQL Server（TextToSQL 用，只读）。

为什么单独一个模块：业务数据全在 SQL Server，和 RAG 用的 PostgreSQL 是两套库、
两套驱动。这里只管"怎么连上 SQL Server、怎么安全地跑一条只读查询"，不掺别的。

驱动用 pymssql（基于 FreeTDS）：装起来不依赖系统 ODBC 驱动，离线 Windows 省事，
且能兼容较老的 SQL Server（这里业务库是 2008）。

注意：pymssql 是**同步阻塞**的库（和 MinIO 一样）。在异步接口里调用时，必须用
run_in_threadpool 丢到线程池跑，否则会卡住整个事件循环。本模块只提供同步函数，
"挪线程池"由调用方负责（见 endpoints 里的用法）。
"""

import pymssql

from app.core.config import settings
from app.core.exceptions import ExternalServiceError


def _connect() -> "pymssql.Connection":
    """建一条到 SQL Server 的连接。调用方用完务必关闭（用 try/finally 或 with）。

    login_timeout：连接握手的超时（连不上时别干等）。
    timeout：单条查询的执行超时，是 TextToSQL 的护栏之一，防慢查询拖垮连接。
    as_dict=True：查询结果每行返回成 {列名: 值} 的字典，比按下标取值可读、不易错位。
    """
    if not settings.mssql_configured:
        # 没配连接信息就别尝试连接，直接给一句清楚的提示
        raise ExternalServiceError("SQL Server 未配置（请在 .env 填 MSSQL_* 后重试）")
    try:
        return pymssql.connect(
            server=settings.mssql_host,
            port=str(settings.mssql_port),
            user=settings.mssql_user,
            password=settings.mssql_password,
            database=settings.mssql_database,
            login_timeout=10,
            timeout=settings.mssql_timeout,
            as_dict=True,
            # 必须显式指定，否则默认会用新版协议跟 SQL Server 2008 做 TLS 握手而失败。
            # 详见 config.py 的 mssql_tds_version 说明。
            tds_version=settings.mssql_tds_version,
        )
    except Exception as e:
        # 把底层驱动的报错包装成统一的外部服务异常（502），并记下原因
        raise ExternalServiceError(f"SQL Server 连接失败：{e}") from e


def ping() -> bool:
    """连通自检：连上 SQL Server 跑一句 SELECT 1，能返回就说明通。

    同步函数。给健康检查/自检脚本用；异步接口里要用 run_in_threadpool 包起来调。
    """
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 AS ok")
        row = cursor.fetchone()
        return bool(row and row.get("ok") == 1)
    finally:
        conn.close()
