"""检索：给一句话，从知识库里找出最相关的若干文本块(chunk)。

这是 RAG 回答问题的第一步——先把相关资料找出来，后面(P4)再交给大模型据此作答。
提供三种检索：
- search()         向量检索：按"意思相近"找(余弦距离)。
- keyword_search() 关键词检索：按"词面匹配"找(PG 全文检索)，擅长精确词。
- hybrid_search()  混合检索：上面两路融合 + 可选 rerank 精排(默认入口)。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk
from app.services.rag.embedding import embed_texts
from app.services.rag.rerank import rerank
from app.services.rag.tokenize import to_tsquery_or

logger = get_logger(__name__)


async def search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
) -> list[dict]:
    """向量检索：返回与 query 最相关的 top_k 个文本块。

    doc_type：可选，只在某类文档里搜(比如只搜 SOP)。
    只搜"当前有效版本"的文档(is_active=True)，旧版本不参与。
    """
    # 1. 把查询转成向量(embed_texts 收的是列表，取第 0 个结果)
    query_vec = (await embed_texts([query]))[0]

    # 2. 组装过滤条件：只搜有效版本；如果指定了类型再加一条
    conditions = [Document.is_active.is_(True)]
    if doc_type:
        conditions.append(Document.doc_type == doc_type)

    # 3. 按"余弦距离"排序取最近的 top_k 块。
    #    cosine_distance 越小越相近(0=一模一样)；它会用到我们建的 HNSW 向量索引。
    distance = DocumentChunk.embedding.cosine_distance(query_vec)
    stmt = (
        select(DocumentChunk, Document.name, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*conditions)
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    # 4. 整理成好用的字典列表。score 用 (1 - 余弦距离) 表示相似度，越大越相关。
    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_name": name,
            "seq": chunk.seq,
            # 父子切割时返回父块(上下文更全)；普通切割 parent_content 为空就返回本块
            "content": chunk.parent_content or chunk.content,
            "score": round(1 - float(dist), 4),
            "meta": chunk.meta,
        }
        for chunk, name, dist in rows
    ]


async def keyword_search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
) -> list[dict]:
    """关键词检索(BM25 风格)：靠 PG 全文检索按词匹配，擅长"型号/代码/术语"这类精确词。

    向量检索靠"意思相近"，对精确词(如 E01、qwen-plus)反而弱；这个按词面匹配来补。
    """
    # 把查询切词、拼成 PG 全文检索表达式；切不出有效词就直接返回空
    tsq_str = to_tsquery_or(query)
    if not tsq_str:
        return []
    tsquery = func.to_tsquery("simple", tsq_str)

    conditions = [Document.is_active.is_(True)]
    if doc_type:
        conditions.append(Document.doc_type == doc_type)

    # ts_rank 是匹配程度的打分，越大越相关；用 @@ 判断 ts 是否匹配 tsquery
    rank = func.ts_rank(DocumentChunk.ts, tsquery)
    stmt = (
        select(DocumentChunk, Document.name, rank.label("rank"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*conditions, DocumentChunk.ts.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "document_name": name,
            "seq": chunk.seq,
            # 父子切割时返回父块(上下文更全)；普通切割 parent_content 为空就返回本块
            "content": chunk.parent_content or chunk.content,
            "score": round(float(score), 4),
            "meta": chunk.meta,
        }
        for chunk, name, score in rows
    ]


def _rrf_fuse(result_lists: list[list[dict]], rrf_k: int = 60) -> list[dict]:
    """RRF(Reciprocal Rank Fusion，倒数排名融合)：把多路检索结果合并成一个排序。

    做法：某个块在某一路里排第 rank 名(从 0 算)，就得 1/(rrf_k + rank + 1) 分；
    把它在各路里的得分加起来。在多路都靠前的块，总分自然更高，排到最前。
    好处：不用纠结"向量分"和"关键词分"量纲不同，只看排名，简单又稳。
    """
    scores: dict[int, float] = {}
    hit_by_id: dict[int, dict] = {}
    for results in result_lists:
        for rank, hit in enumerate(results):
            cid = hit["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
            hit_by_id.setdefault(cid, hit)  # 留一份该块的数据(内容/来源等)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    fused = []
    for cid, score in ordered:
        hit = dict(hit_by_id[cid])
        hit["score"] = round(score, 6)  # 这里的 score 是 RRF 融合分
        fused.append(hit)
    return fused


def _dedupe_by_content(hits: list[dict]) -> list[dict]:
    """按返回内容去重，保留排名靠前的那条。

    主要为父子切割：同一个父块常被多个小块命中，不去重的话结果里会重复出现
    同一段父块，白占名额。这里把内容相同的只留第一条(也就是排名最高的那条)。
    """
    seen: set[str] = set()
    out = []
    for hit in hits:
        if hit["content"] in seen:
            continue
        seen.add(hit["content"])
        out.append(hit)
    return out


async def hybrid_search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
    use_rerank: bool | None = None,
) -> list[dict]:
    """混合检索：同时跑向量 + 关键词，融合两路结果；可选再用 rerank 精排。

    向量擅长"意思相近"、关键词擅长"精确词"，融合后取长补短，召回更全更准。
    use_rerank 不传时用配置里的开关(settings.rerank_enabled)。
    """
    if use_rerank is None:
        use_rerank = settings.rerank_enabled

    # 每路多取一些候选(融合/精排才有得挑)，最后再截到 top_k
    candidate_k = max(top_k, 20)
    vector_hits = await search(session, query, top_k=candidate_k, doc_type=doc_type)
    keyword_hits = await keyword_search(session, query, top_k=candidate_k, doc_type=doc_type)

    # 融合两路，并去掉重复(主要是父子切割时同一父块被多个小块命中的情况)
    fused = _dedupe_by_content(_rrf_fuse([vector_hits, keyword_hits]))
    if not fused:
        return []

    if not use_rerank:
        return fused[:top_k]

    # 开了 rerank：把融合后的候选交给 rerank 模型精排，再取 top_k。
    # rerank 是可选增强，万一调用失败(超时/限流等)，回退到融合结果，别让整个检索挂掉。
    candidates = fused[:candidate_k]
    try:
        order = await rerank(query, [h["content"] for h in candidates], top_n=top_k)
    except Exception:
        logger.warning("rerank 调用失败，回退到融合结果", exc_info=True)
        return fused[:top_k]

    reranked = []
    for original_index, score in order:
        hit = dict(candidates[original_index])
        hit["score"] = round(float(score), 4)  # 这里的 score 是 rerank 相关度分
        reranked.append(hit)
    return reranked
