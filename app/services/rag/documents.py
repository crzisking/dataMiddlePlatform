"""文档入库编排（P2 子步骤 3）：校验 → 版本判定 → 存 MinIO → 建文档记录。

真正的解析/切割/向量化在异步任务里做（P2 子步骤 4），这里只负责"登记 + 落原件"。
"""

import io
import json
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import BadRequestError
from app.models.document import Document
from app.services.rag.upload import sha256_of, validate_upload
from app.services.storage.minio_client import ensure_bucket, get_minio


def _parse_biz_tags(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BadRequestError("biz_tags 不是合法 JSON") from e
    if not isinstance(v, dict):
        raise BadRequestError("biz_tags 必须是 JSON 对象")
    return v


async def _store_to_minio(object_key: str, data: bytes) -> None:
    # MinIO 客户端是同步的：丢到线程池执行，避免阻塞异步事件循环。
    bucket = await run_in_threadpool(ensure_bucket)
    await run_in_threadpool(
        get_minio().put_object,
        bucket,
        object_key,
        io.BytesIO(data),
        len(data),
    )


async def create_document_version(
    session: AsyncSession,
    *,
    filename: str,
    data: bytes,
    doc_type: str,
    biz_tags_raw: str | None = None,
) -> Document:
    """创建一个文档版本记录（status=pending），原件存 MinIO。不提交，由调用方 commit。"""
    ext = validate_upload(filename, data)  # 校验不过会抛 BadRequestError
    content_hash = sha256_of(data)
    biz_tags = _parse_biz_tags(biz_tags_raw)

    # 版本：同 (name, doc_type) 视为同一文档，重传则版本递增、旧版置 is_active=False
    max_v = (
        await session.execute(
            select(func.max(Document.version)).where(
                Document.name == filename, Document.doc_type == doc_type
            )
        )
    ).scalar()
    version = (max_v or 0) + 1
    if max_v:
        await session.execute(
            update(Document)
            .where(
                Document.name == filename,
                Document.doc_type == doc_type,
                Document.is_active.is_(True),
            )
            .values(is_active=False)
        )

    # 原件存 MinIO：key 用 uuid 防重名/防覆盖
    object_key = f"{doc_type}/{uuid4().hex}/{filename}"
    await _store_to_minio(object_key, data)

    doc = Document(
        name=filename,
        doc_type=doc_type,
        biz_tags=biz_tags,
        version=version,
        is_active=True,
        file_ext=ext,
        file_size=len(data),
        content_hash=content_hash,
        object_key=object_key,
    )
    session.add(doc)
    await session.flush()  # 拿到自增 id
    return doc
