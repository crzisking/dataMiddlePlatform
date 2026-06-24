"""健康检查 / 根路径冒烟测试（不依赖外部服务）。"""


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["version"]


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
