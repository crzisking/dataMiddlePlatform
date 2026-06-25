"""把各个功能模块的接口"汇总"成一个总路由。

每个端点文件(health/meta/chat/documents)各自有一个小路由，这里用
include_router 把它们收进来，并给每个加上各自的路径前缀(prefix)。
最终路径 = /api/v1(在 main.py 加) + 这里的 prefix + 端点函数里写的路径。
比如 documents 的上传接口最终是 /api/v1/documents。
"""

from fastapi import APIRouter

from app.api.v1.endpoints import chat, chunk_configs, documents, health, meta, search

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])  # 健康检查，不加前缀
api_router.include_router(meta.router, prefix="/meta", tags=["meta"])  # 元信息(模型列表等)
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])  # 对话
api_router.include_router(documents.router, prefix="/documents", tags=["rag"])  # 文档上传/查询
api_router.include_router(search.router, prefix="/search", tags=["rag"])  # 知识库检索
api_router.include_router(
    chunk_configs.router, prefix="/chunk-configs", tags=["rag"]
)  # 切割配置管理
