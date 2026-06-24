"""PostgreSQL 异步会话（psycopg3 + SQLAlchemy 2.0）。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# engine 全局只建一个：内部维护连接池，整个应用共享，切勿每次请求新建。
engine = create_async_engine(
    settings.pg_dsn,
    echo=settings.app_debug,  # 开发时打印 SQL 便于调试；生产(debug=False)关闭以免日志噪音
    pool_pre_ping=True,  # 取连接前先 ping，自动剔除被 DB/网络断掉的死连接，避免偶发报错
)

# 会话工厂：每次请求用它产出一个独立 session。
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # 提交后不过期对象：否则访问已提交对象的属性会触发额外查询，异步下还可能在响应阶段报错。
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求注入一个独立会话，请求结束(async with 退出)自动关闭归还连接池。"""
    async with async_session_factory() as session:
        yield session
