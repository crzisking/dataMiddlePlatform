"""统一错误响应格式测试。"""

from app.core.exceptions import LLMError, NotFoundError


def _is_unified(body: dict) -> bool:
    return {"code", "message", "detail"}.issubset(body)


def test_validation_error_format(client):
    # 缺必填 message → 422，且归一成统一格式。
    r = client.post("/api/v1/chat", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert _is_unified(body)


def test_not_found_format(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "HTTP_ERROR"


def test_app_error_attrs():
    # 业务异常携带正确的状态码 / 错误码 / 可覆盖 message。
    assert LLMError().status_code == 502
    assert LLMError().code == "LLM_ERROR"
    assert NotFoundError("文档不存在").message == "文档不存在"
