"""模型列表接口冒烟测试。"""


def test_models(client):
    r = client.get("/api/v1/meta/models")
    assert r.status_code == 200
    data = r.json()
    # 模型清单来自 .env 配置（QWEN_MODELS/DEEPSEEK_MODELS），不写死具体名字，
    # 这里只校验结构：有非空列表，且默认模型在列表里。
    assert isinstance(data["models"], list) and data["models"]
    assert data["default"] in data["models"]
