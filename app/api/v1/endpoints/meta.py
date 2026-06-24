"""元信息：可用模型列表等（供前端对话框模型切换使用）。"""

from fastapi import APIRouter

from app.services.llm.client import DEFAULT_MODEL, available_models

router = APIRouter()


@router.get("/models")
async def models() -> dict:
    return {"default": DEFAULT_MODEL, "models": available_models()}
