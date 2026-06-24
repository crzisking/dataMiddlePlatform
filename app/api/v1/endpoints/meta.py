"""元信息接口：提供一些"配置类"数据给前端，目前是可选模型列表。"""

from fastapi import APIRouter

from app.services.llm.client import DEFAULT_MODEL, available_models

router = APIRouter()


@router.get("/models")
async def models() -> dict:
    """返回可选模型列表和默认模型，给前端的"模型切换下拉框"用。

    这样前端不用把模型名写死——后端加/减模型，前端自动跟着变。
    """
    return {"default": DEFAULT_MODEL, "models": available_models()}
