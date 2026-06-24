"""向量化：调通义 text-embedding-v3，把文本块批量转成向量（P2-4）。"""

from app.core.config import settings
from app.services.llm.client import embedding_client

# 通义兼容接口单次 batch 上限保守取 10，过大可能被拒。
_BATCH = 10


def _batches(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化，返回与输入等长、同序的向量列表。"""
    client = embedding_client()
    vectors: list[list[float]] = []
    for batch in _batches(texts, _BATCH):
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dim,  # 指定维度，与 chunk 表 vector(1024) 一致
        )
        # resp.data 顺序与 input 一致
        vectors.extend(d.embedding for d in resp.data)
    return vectors
