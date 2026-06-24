"""向量化：把一段段文本转成"向量"（一串数字），供后续按相似度检索。

向量是什么：模型把一段文字映射成一串浮点数（这里是 1024 个）。两段意思
相近的文字，它们的向量在空间里也"挨得近"。检索时就是比"谁的向量离问题最近"。

这里调通义的 text-embedding-v3 模型来生成向量。
"""

from app.core.config import settings
from app.services.llm.client import embedding_client

# 一次最多送几段文字给通义。通义兼容接口对单次条数有上限，
# 这里保守取 10，送太多可能被接口拒绝。
_BATCH = 10


def _batches(items: list[str], size: int):
    """把一个大列表切成每 size 个一组，逐组产出（避免一次送太多）。"""
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """把多段文本批量转成向量。

    返回的向量列表和输入 texts 一一对应、顺序相同
    （第 0 段文本 → 第 0 个向量，以此类推）。
    """
    client = embedding_client()
    vectors: list[list[float]] = []
    # 分批送：每次最多 _BATCH 段
    for batch in _batches(texts, _BATCH):
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            # 指定向量维度 1024，必须和数据库 chunk 表的 vector(1024) 一致，否则存不进去
            dimensions=settings.embedding_dim,
        )
        # 通义返回的 resp.data 顺序和我们送进去的 batch 顺序一致，直接按序取出
        vectors.extend(d.embedding for d in resp.data)
    return vectors
