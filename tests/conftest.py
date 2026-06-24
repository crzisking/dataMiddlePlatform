"""pytest 公共夹具。"""

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False：让 500 走我们的异常处理器返回 JSON，而非在测试里抛出。
    return TestClient(app, raise_server_exceptions=False)
