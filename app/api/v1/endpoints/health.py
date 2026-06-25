"""健康检查接口：用来快速确认"服务活着没""数据库连得上没"。

常用于部署后探活、或排查"是服务挂了还是数据库挂了"。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.db.session import get_session
from app.services.texttosql.db import ping as mssql_ping

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """只确认进程还在跑，不碰任何外部依赖。"""
    return {"status": "ok"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict:
    """确认能连上 PostgreSQL：跑一句最简单的 SELECT 1，能返回就说明通。"""
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "postgresql"}


@router.get("/health/mssql")
async def health_mssql() -> dict:
    """确认能连上业务库 SQL Server（TextToSQL 用）。

    没配 MSSQL_* 时不报错，只回 skipped（P5 才启用，没配是正常状态）。
    pymssql 是同步驱动，用 run_in_threadpool 丢线程池跑，别堵事件循环。
    """
    if not settings.mssql_configured:
        return {"status": "skipped", "db": "sqlserver", "detail": "未配置 MSSQL_*"}
    await run_in_threadpool(mssql_ping)
    return {"status": "ok", "db": "sqlserver"}
