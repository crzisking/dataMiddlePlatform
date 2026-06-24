"""统一异常与错误处理。

目标：所有报错都走一个出口，前端永远拿到规整的 `{code, message, detail?}`，
完整堆栈只记日志、不外泄（避免泄露表名/SQL/路径等内部信息）。

用法：
- 业务里主动抛：`raise LLMError("模型超时")`，会被转成对应状态码 + 错误码。
- 未预期的异常：自动兜底为 500 INTERNAL_ERROR。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """业务异常基类。子类只需覆盖 code / status_code / 默认 message。"""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    message: str = "服务异常，请稍后重试"

    def __init__(self, message: str | None = None, *, detail: object = None):
        # message 可在抛出时覆盖；detail 放结构化补充信息（可选，给前端/排查用）。
        self.message = message or self.message
        self.detail = detail
        super().__init__(self.message)


# —— 常用分类（按需扩展）——
class BadRequestError(AppError):
    code, status_code, message = "BAD_REQUEST", 400, "请求参数有误"


class NotFoundError(AppError):
    code, status_code, message = "NOT_FOUND", 404, "资源不存在"


class LLMError(AppError):
    # 502：本服务正常，是上游(通义/DeepSeek)出错，语义比 500 更准。
    code, status_code, message = "LLM_ERROR", 502, "模型调用失败，请稍后重试"


class DatabaseError(AppError):
    code, status_code, message = "DB_ERROR", 500, "数据访问异常"


class ExternalServiceError(AppError):
    # MinIO 等外部依赖出错。
    code, status_code, message = "EXTERNAL_ERROR", 502, "外部服务异常"


def _error(status_code: int, code: str, message: str, detail: object = None) -> JSONResponse:
    """统一构造错误响应体。"""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 app 上注册全部异常处理器（main.py 启动时调用）。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 业务异常：信息是我们可控的，可直接返回；记 warning 便于观察。
        logger.warning("业务异常 %s: %s", exc.code, exc.message)
        return _error(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI 参数校验失败：统一成我们的格式（默认它返回的结构和我们不一致）。
        return _error(422, "VALIDATION_ERROR", "请求参数校验失败", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 404/405 等框架级 HTTP 异常，也归一到统一格式。
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 兜底：未预期的异常。完整堆栈进日志，对外只给笼统提示，不泄露内部信息。
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return _error(500, "INTERNAL_ERROR", "服务异常，请稍后重试")
