"""FastAPI 应用入口。

本地启动：
    uv run uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.core.eventloop  # noqa: F401  必须最先 import：设置 Windows 事件循环策略
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.workers.queue import app as task_app

setup_logging()
logger = get_logger(__name__)


# lifespan：yield 之前 = 启动时执行，yield 之后 = 关闭时执行。
# 后续把「建连接池预热、初始化任务队列、加载模型」等启动/收尾逻辑放这里。
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("启动 %s (env=%s)", settings.app_name, settings.app_env)
    # 打开 procrastinate 连接，使接口能投递异步任务（defer）；关闭时释放。
    async with task_app.open_async():
        yield
    logger.info("关闭 %s", settings.app_name)


app = FastAPI(
    title="制造业数据中台",
    version="0.1.0",
    description="RAG + TextToSQL 后端服务",
    lifespan=lifespan,
)

# CORS：允许浏览器跨域调本接口（前端与后端不同源时必需）。
# 一期不鉴权，先全放开；上线前(P8)应把 allow_origins 收敛为前端实际域名。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 所有业务接口统一挂在 /api/v1 前缀下：版本化，将来出 v2 不影响老接口。

# 统一错误处理：所有异常归一到 {code, message, detail} 格式，堆栈只进日志。
register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    return {"app": settings.app_name, "version": "0.1.0"}
