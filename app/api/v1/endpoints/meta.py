"""元信息接口：提供一些"配置类"数据给前端（可选模型列表、文档类型词表等）。"""

from fastapi import APIRouter

from app.core.config import settings
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


@router.get("/doc-types")
async def doc_types() -> dict:
    """返回文档类型受控词表，给前端上传/筛选的"文档类型下拉框"用。

    清单来自 .env 的 `DOC_TYPES`（运维可改），前端不写死、后端加减类型前端自动跟着变。
    """
    return {"doc_types": settings.doc_type_list}
