"""连接 PostgreSQL 的"基础管道"：连接池 + 会话工厂 + 获取会话的方法。

三个概念别混(常见误区)：
- engine = 连接池，管理一批到数据库的真实连接，全项目建一个、共享。
- session = 一次操作的"工作台/购物车"，临时从池子借一条连接来用，用完还回去。
- async_session_factory = "发会话的窗口"，要操作数据库就找它领一个 session。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 连接池。全局只建这一个，整个应用共用——千万不要每次请求都新建(建连接很贵)。
engine = create_async_engine(
    settings.pg_dsn,
    # echo=True 时会把执行的 SQL 打到日志，方便开发调试；生产关掉以免日志太吵
    echo=settings.app_debug,
    # 取连接前先 ping 一下，自动剔除已经被数据库/网络断开的"死连接"，避免偶发报错
    pool_pre_ping=True,
    # 连接池大小(P8 C2)：高并发下请求大多在等 LLM、用 DB 很短，池子够借用即可。
    # pool_size 常驻连接数，max_overflow 池满后可临时多开的数；超出才排队等(pool_timeout)。
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=30,
    # 给每条连接设单条 SQL 超时(毫秒)：防一条慢查询长时间挂住连接、拖垮并发。
    # 这是 PostgreSQL 的 statement_timeout，由连接参数 -c 传入(psycopg 支持)。
    connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
)

# 会话工厂：调用它(async_session_factory())就产出一个新的 session。
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # expire_on_commit=False：提交(commit)之后，已经查出来的对象仍然能直接读属性。
    # 否则一提交对象就"过期"，再读属性会触发额外查询，异步场景下还可能在返回响应时报错。
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """给 FastAPI 接口用的"依赖"：每个请求自动领一个独立会话，
    请求处理完(退出 async with)自动关闭、把连接还回池子。

    接口里这样用：session: AsyncSession = Depends(get_session)
    """
    async with async_session_factory() as session:
        yield session
