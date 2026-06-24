"""入库编排（P2-4）：worker 取到任务后真正执行的流程。

从 MinIO 取原件 → 解析 → 切割 → 通义 embedding → 写 document_chunks → 更新状态。
全程更新 documents.status，失败则记 error，供前端回查。
"""

import asyncio

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.document import DocStatus, Document, DocumentChunk
from app.services.rag.chunking import chunk_text
from app.services.rag.embedding import embed_texts
from app.services.rag.parsing import extract_text
from app.services.storage.minio_client import get_minio

logger = get_logger(__name__)


def _download(object_key: str) -> bytes:
    resp = get_minio().get_object(settings.minio_bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


async def ingest(document_id: int) -> None:
    """执行一篇文档的入库。异常被捕获并落到 status=failed。"""
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            logger.warning("入库任务：文档不存在 id=%s", document_id)
            return

        try:
            doc.status = DocStatus.parsing
            await session.commit()

            # 取原件 + 解析（IO/CPU 密集，丢线程池避免阻塞事件循环）
            data = await run_in_threadpool(_download, doc.object_key)
            text = await asyncio.to_thread(extract_text, doc.file_ext, data)

            chunks = chunk_text(text)
            if not chunks:
                doc.status = DocStatus.done
                doc.chunk_count = 0
                await session.commit()
                logger.warning("入库完成但无可切分文本 id=%s（可能是扫描件，待 OCR）", doc.id)
                return

            doc.status = DocStatus.embedding
            await session.commit()
            vectors = await embed_texts(chunks)

            # 每块带元数据：类型 + 业务标签，供检索时过滤
            base_meta = {"doc_type": doc.doc_type, **(doc.biz_tags or {})}
            session.add_all(
                [
                    DocumentChunk(
                        document_id=doc.id,
                        seq=i,
                        content=c,
                        embedding=v,
                        meta=base_meta,
                    )
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ]
            )
            doc.status = DocStatus.done
            doc.chunk_count = len(chunks)
            await session.commit()
            logger.info("入库完成 id=%s chunks=%s", doc.id, len(chunks))

        except Exception as e:  # noqa: BLE001  统一兜底，落 failed 状态
            await session.rollback()
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocStatus.failed
                doc.error = str(e)[:500]
                await session.commit()
            logger.exception("入库失败 id=%s", document_id)
