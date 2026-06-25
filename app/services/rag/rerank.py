"""重排序(rerank)：把检索出来的候选块，用专门的 rerank 模型按"和问题的相关度"重新排个序。

为什么要它：向量/关键词检索是"粗筛"，速度快但不够准。rerank 模型会把
"问题 + 每个候选块"一起细读，给出更准的相关度分，从而把最相关的顶上来。
代价是多一次 API 调用、增加一点延迟，所以做成可配开关(默认关)。

通义的 rerank 是 DashScope 原生接口(不是 OpenAI 兼容那套)，所以这里用 httpx 直接调。
"""

import httpx

from app.core.config import settings


async def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
    """对候选文档重排序。

    入参 documents 是候选块的文本列表。
    返回 [(原始下标, 相关度分), ...]，已按相关度从高到低排好，最多 top_n 个。
    调用方再用"原始下标"回去找对应的块。
    """
    if not documents:
        return []

    headers = {
        "Authorization": f"Bearer {settings.qwen_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        # return_documents=False：只要排序结果和分数，不要把原文回传(省流量)
        "parameters": {"return_documents": False, "top_n": top_n},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(settings.dashscope_rerank_url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # 返回结构：output.results = [{index: 原始下标, relevance_score: 相关度}, ...]
    results = data["output"]["results"]
    return [(r["index"], r["relevance_score"]) for r in results]
