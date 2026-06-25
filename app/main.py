"""整个后端服务的入口：在这里创建 FastAPI 应用、挂上各种接口和中间件。

本地启动：
    uv run uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 导入这一行会顺便设置 Windows 的事件循环策略(切成 SelectorEventLoop，否则 psycopg
# 异步会报错)。只要在程序真正跑起来之前完成即可，所以放在 import 区就行。
import app.core.eventloop  # noqa: F401
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.workers.queue import app as task_app

setup_logging("api")  # API 进程日志 → logs/api.log
logger = get_logger(__name__)


# lifespan = 应用的"生命周期钩子"：yield 之前的代码在"启动时"跑一次，
# yield 之后的代码在"关闭时"跑一次。以后要做"预热、初始化、收尾"都放这里。
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动 %s (env=%s)", settings.app_name, settings.app_env)
    # 尝试打开任务队列连接(接口投递任务要用到它)。
    # 这里做了容错：即使打开失败(比如 PG 临时连不上)，也不让整个服务起不来——
    # 服务照常启动，健康检查、查询等不依赖队列的接口仍可用，只是"上传后投递异步
    # 任务"会暂时失败。等 PG 恢复后重启即可。
    queue_ok = False
    try:
        await task_app.open_async()
        queue_ok = True
    except Exception:
        logger.exception("任务队列连接失败：异步入库暂不可用，其余功能正常")
    try:
        yield
    finally:
        # 只有成功打开过才需要关闭
        if queue_ok:
            await task_app.close_async()
        logger.info("关闭 %s", settings.app_name)


app = FastAPI(
    title="制造业数据中台",
    version="0.1.0",
    description="RAG + TextToSQL 后端服务",
    lifespan=lifespan,
)

# CORS：浏览器有"跨域"限制——前端和后端域名/端口不同时，默认不让前端调后端。
# 这个中间件放开跨域。一期不鉴权先全放开(*)；上线前(P8)要改成只允许前端的真实域名。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册统一错误处理：让所有报错都返回统一的 {code, message, detail} 格式。
register_exception_handlers(app)

# 把所有业务接口挂到 /api/v1 前缀下。
# 加版本号前缀的好处：将来要做不兼容的改动时可以出 /api/v2，不影响老接口。
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    """根路径，用来快速确认服务活着。"""
    return {"app": settings.app_name, "version": "0.1.0"}
