"""HTTP 中间件：上线硬化用（P8）。

- ConcurrencyLimitMiddleware：限制"同时在处理的请求数"，超过就直接 503，
  保护本机和上游 LLM 不被突发流量打爆（B1）。
- RequestLoggingMiddleware：每条请求记一行日志（方法/路径/状态/耗时），
  排障和成本观测用（D1）。

为什么用计数器而不用锁：FastAPI 跑在单线程事件循环里，`self._active += 1` 这种
不会有多线程竞态，简单计数即可准确。
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger

logger = get_logger("app.request")


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """同时处理的请求数超过上限就拒（503），不让请求无限堆积压垮服务/上游。"""

    def __init__(self, app, limit: int):
        super().__init__(app)
        self.limit = limit
        self._active = 0  # 当前在处理中的请求数

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._active >= self.limit:
            # 满了直接挡掉，返回统一错误结构（和全局异常处理器同形状），让前端可识别。
            logger.warning("并发已达上限 %s，拒绝请求 %s", self.limit, request.url.path)
            return JSONResponse(
                status_code=503,
                content={
                    "code": "BUSY",
                    "message": "服务繁忙，请稍后重试",
                    "detail": None,
                },
            )
        self._active += 1
        try:
            return await call_next(request)
        finally:
            self._active -= 1


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """每条请求记一行：方法 路径 -> 状态码 (耗时ms)。用于排障和粗粒度成本/流量观测。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # perf_counter 是单调时钟，专门用来测时间差（不受系统时间调整影响）
        start = time.perf_counter()
        response = await call_next(request)
        cost_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            cost_ms,
        )
        return response
