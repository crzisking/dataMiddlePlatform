"""统一的错误处理：让全项目所有报错都长一个样、走一个出口。

为什么需要：如果不管，程序任何地方报错，前端收到的格式五花八门，还可能
把内部信息（表名、SQL、文件路径、堆栈）暴露出去。这里做两件事：
  1. 所有错误都转成统一结构 {code, message, detail?}，前端好统一处理；
  2. 真正的报错细节（堆栈）只写进服务器日志，绝不返回给前端。

用法：
- 业务代码里主动抛，比如 raise LLMError("模型超时")，会被转成对应状态码+错误码；
- 没接住的意外异常，会被最后的兜底处理器转成 500，对外只给一句笼统提示。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """所有"业务异常"的基类。

    子类只要改三个类属性即可：
      code        —— 给前端识别的错误码字符串
      status_code —— HTTP 状态码
      message     —— 默认提示语（抛出时也可以临时换一句）
    """

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    message: str = "服务异常，请稍后重试"

    def __init__(self, message: str | None = None, *, detail: object = None):
        # 抛出时如果传了 message，就用传的那句覆盖默认的；
        # detail 是可选的补充信息（比如校验失败的具体字段），会一起返回给前端。
        self.message = message or self.message
        self.detail = detail
        super().__init__(self.message)


# —— 下面是几类常用的业务异常，按需要继续加 ——
class BadRequestError(AppError):
    code, status_code, message = "BAD_REQUEST", 400, "请求参数有误"


class NotFoundError(AppError):
    code, status_code, message = "NOT_FOUND", 404, "资源不存在"


class LLMError(AppError):
    # 用 502 而不是 500：表示"我们服务没问题，是上游(通义/DeepSeek)出错了"，语义更准
    code, status_code, message = "LLM_ERROR", 502, "模型调用失败，请稍后重试"


class DatabaseError(AppError):
    code, status_code, message = "DB_ERROR", 500, "数据访问异常"


class ExternalServiceError(AppError):
    # 比如 MinIO 等外部依赖出错
    code, status_code, message = "EXTERNAL_ERROR", 502, "外部服务异常"


def _error(status_code: int, code: str, message: str, detail: object = None) -> JSONResponse:
    """统一拼出错误响应体，保证所有错误返回的结构都一样。"""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """把下面这几个错误处理器挂到 app 上。在 main.py 启动时调用一次。

    FastAPI 的机制：用 @app.exception_handler(某种异常) 注册后，只要请求处理
    过程中抛出那种异常，FastAPI 就会自动调用对应的处理器来生成响应。
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 业务异常：提示语是我们自己写的、可控的，直接返回。记 warning 方便排查。
        logger.warning("业务异常 %s: %s", exc.code, exc.message)
        return _error(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 请求参数没通过校验(比如少了必填字段)。FastAPI 自带的返回结构和我们不一样，
        # 这里转成统一格式；exc.errors() 是具体哪些字段错了，放进 detail。
        return _error(422, "VALIDATION_ERROR", "请求参数校验失败", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 框架级的 HTTP 错误，比如访问了不存在的网址(404)、方法不对(405)，也归一成统一格式。
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 最后的兜底：上面没接住的任何意外异常都会到这里。
        # 完整堆栈用 logger.exception 写进日志(给我们排查)，对外只回一句笼统提示，
        # 不把异常内容暴露出去(可能含表名/SQL 等内部信息)。
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return _error(500, "INTERNAL_ERROR", "服务异常，请稍后重试")
