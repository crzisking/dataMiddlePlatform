"""元信息接口：提供一些"配置类"数据给前端，目前是可选模型列表。"""

from fastapi import APIRouter

from app.services.llm.client import DEFAULT_MODEL, available_models

router = APIRouter()


@router.get("/models")
async def models() -> dict:
    """返回可选模型列表和默认模型，给前端的"模型切换下拉框"用。

    模型清单来自 .env 的 `QWEN_MODELS` / `DEEPSEEK_MODELS` 配置（运维从厂商官网查到后挑选填入），
    前端不写死、后端改 .env 即生效。不直接暴露厂商 /models 全量：那会返回上百个混杂模型(图像/
    语音/第三方等)，没法直接做下拉框。
    """
    return {"default": DEFAULT_MODEL, "models": available_models()}
