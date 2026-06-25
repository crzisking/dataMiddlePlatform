"""检索接口：输入一句话，返回知识库里最相关的若干文本块。

主要用于联调/预览检索效果。P4 做问答时，Agent 的"知识库检索"工具也会调
同一个检索服务。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.rag.retrieval import hybrid_search, keyword_search, search

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., description="要检索的问题或关键词")
    top_k: int = Field(5, ge=1, le=50, description="返回多少个最相关的块")
    doc_type: str | None = Field(None, description="只在某类文档里搜，不传则全部")
    # hybrid=向量+关键词融合(默认，最好)；vector=只按意思；keyword=只按词面
    mode: Literal["hybrid", "vector", "keyword"] = Field("hybrid", description="检索方式")


class SearchHit(BaseModel):
    chunk_id: int
    document_id: int
    document_name: str
    seq: int
    content: str
    score: float  # 相似度，越大越相关
    meta: dict | None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


@router.post("", response_model=SearchResponse)
async def search_chunks(
    req: SearchRequest,
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    finder = {"hybrid": hybrid_search, "vector": search, "keyword": keyword_search}[req.mode]
    hits = await finder(
        session,
        req.query,
        top_k=req.top_k,
        doc_type=req.doc_type,
    )
    return SearchResponse(query=req.query, hits=[SearchHit(**h) for h in hits])
