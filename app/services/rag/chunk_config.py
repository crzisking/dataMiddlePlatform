"""切割配置的读写：入库时按文档类型取配置；管理页增改配置。

某类文档没单独配过时，用下面的默认配置(recursive / 512 / 50)。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk_config import ChunkConfig


@dataclass
class ChunkSettings:
    """一份切割配置的取值(从表里读出，或用默认)。"""

    strategy: str = "recursive"
    chunk_size: int = 512
    overlap: int = 50
    parent_size: int = 2048


DEFAULT = ChunkSettings()


async def get_settings_for(session: AsyncSession, doc_type: str) -> ChunkSettings:
    """取某文档类型的切割配置；没配过就返回默认。"""
    cfg = (
        await session.execute(select(ChunkConfig).where(ChunkConfig.doc_type == doc_type))
    ).scalar_one_or_none()
    if cfg is None:
        return DEFAULT
    return ChunkSettings(
        strategy=cfg.strategy,
        chunk_size=cfg.chunk_size,
        overlap=cfg.overlap,
        parent_size=cfg.parent_size,
    )


async def list_configs(session: AsyncSession) -> list[ChunkConfig]:
    """列出所有已配置的类型(给管理页)。"""
    rows = (await session.execute(select(ChunkConfig).order_by(ChunkConfig.doc_type))).scalars()
    return list(rows)


async def upsert_config(
    session: AsyncSession,
    *,
    doc_type: str,
    strategy: str,
    chunk_size: int,
    overlap: int,
    parent_size: int,
) -> ChunkConfig:
    """新增或更新某类型的切割配置(有则改、无则建)。调用方负责 commit。"""
    cfg = (
        await session.execute(select(ChunkConfig).where(ChunkConfig.doc_type == doc_type))
    ).scalar_one_or_none()
    if cfg is None:
        cfg = ChunkConfig(doc_type=doc_type)
        session.add(cfg)
    cfg.strategy = strategy
    cfg.chunk_size = chunk_size
    cfg.overlap = overlap
    cfg.parent_size = parent_size
    await session.flush()
    return cfg
