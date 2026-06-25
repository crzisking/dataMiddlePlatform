"""SQL Server 连通自检（独立小工具，不用先启 API）。

填好 .env 的 MSSQL_* 后，直接跑这个验证能不能连上业务库：
    uv run python scripts/check_mssql.py

成功打印连接信息和版本号；失败打印原因（连不上/账号错/库名错等）。
pymssql 是同步库，这里是纯同步脚本，不涉及事件循环。
"""

import sys

from app.core.config import settings
from app.services.texttosql.db import _connect


def main() -> int:
    if not settings.mssql_configured:
        print("未配置 MSSQL_*：请先在 .env 填 MSSQL_HOST / MSSQL_DATABASE 等再试。")
        return 1

    print(f"尝试连接 {settings.mssql_host}:{settings.mssql_port}/{settings.mssql_database} ...")
    conn = _connect()
    try:
        cursor = conn.cursor()
        # @@VERSION 返回 SQL Server 的版本字符串，顺便确认连的是哪台/哪个版本
        cursor.execute("SELECT @@VERSION AS version")
        row = cursor.fetchone()
        print("连接成功 ✅")
        print(row["version"])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
