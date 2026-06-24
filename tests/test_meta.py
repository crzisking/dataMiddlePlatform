"""模型列表接口冒烟测试。"""


def test_models(client):
    r = client.get("/api/v1/meta/models")
    assert r.status_code == 200
    data = r.json()
    # 默认模型必须在可选列表里，且至少包含已登记的通义模型。
    assert data["default"] in data["models"]
    assert "qwen-plus" in data["models"]
