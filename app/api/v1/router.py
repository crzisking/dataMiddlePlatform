"""v1 API 路由汇总。后续各模块（rag / texttosql / chat）在此挂载。"""

from fastapi import APIRouter

from app.api.v1.endpoints import chat, documents, health, meta

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(meta.router, prefix="/meta", tags=["meta"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(documents.router, prefix="/documents", tags=["rag"])
