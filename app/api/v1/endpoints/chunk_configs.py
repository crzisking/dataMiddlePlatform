"""切割配置管理接口：给管理页查看/设置"每类文档怎么切"。

改了配置后，对该类型文档**重新入库**才会按新配置切(已入库的不会自动重切)。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.rag.chunk_config import list_configs, upsert_config

router = APIRouter()


class ChunkConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_type: str
    strategy: str
    chunk_size: int
    overlap: int
    parent_size: int


class ChunkConfigIn(BaseModel):
    strategy: Literal["recursive", "parent_child"] = "recursive"
    chunk_size: int = Field(512, ge=64, le=4096)
    overlap: int = Field(50, ge=0, le=1024)
    parent_size: int = Field(2048, ge=256, le=16384)


@router.get("", response_model=list[ChunkConfigOut])
async def list_chunk_configs(
    session: AsyncSession = Depends(get_session),
) -> list[ChunkConfigOut]:
    """列出所有已配置的文档类型切割参数。没列出的类型 = 用默认(recursive/512/50)。"""
    rows = await list_configs(session)
    return [ChunkConfigOut.model_validate(r) for r in rows]


@router.put("/{doc_type}", response_model=ChunkConfigOut)
async def set_chunk_config(
    doc_type: str,
    body: ChunkConfigIn,
    session: AsyncSession = Depends(get_session),
) -> ChunkConfigOut:
    """新增或更新某类文档的切割配置。"""
    cfg = await upsert_config(
        session,
        doc_type=doc_type,
        strategy=body.strategy,
        chunk_size=body.chunk_size,
        overlap=body.overlap,
        parent_size=body.parent_size,
    )
    await session.commit()
    return ChunkConfigOut.model_validate(cfg)
