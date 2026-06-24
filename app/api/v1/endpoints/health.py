"""健康检查接口：用来快速确认"服务活着没""数据库连得上没"。

常用于部署后探活、或排查"是服务挂了还是数据库挂了"。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

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
