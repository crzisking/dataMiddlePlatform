"""入库：后台 worker 取到任务后，真正把一篇文档"变成可检索知识"的流程。

完整步骤：
    从 MinIO 取回原件 → 解析出文字 → 切成小块 → 每块转成向量(通义)
    → 写进 document_chunks 表 → 把文档状态改成 done。
中途每一步都会更新 documents.status，方便前端看进度；任何一步出错就记到
failed，并把错误原因存进 error 字段。
"""

import asyncio

from sqlalchemy import delete
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.document import DocStatus, Document, DocumentChunk
from app.services.rag.chunk_config import get_settings_for
from app.services.rag.chunking import chunk_documents
from app.services.rag.embedding import embed_texts
from app.services.rag.parsing import extract_text
from app.services.rag.tokenize import tokenize
from app.services.storage.minio_client import get_minio

logger = get_logger(__name__)


def _download(object_key: str) -> bytes:
    """从 MinIO 把原件读成字节。读完务必关闭连接，否则连接会泄漏。"""
    resp = get_minio().get_object(settings.minio_bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


async def ingest(document_id: int) -> None:
    """处理一篇文档的入库。整段用 try 包住：任何异常都落到 status=failed，
    而不是让 worker 崩掉。
    """
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            # 文档可能已被删除，任务就没必要继续了
            logger.warning("入库任务：文档不存在 id=%s", document_id)
            return

        try:
            # 标记"解析中"，前端能看到进度
            doc.status = DocStatus.parsing
            await session.commit()

            # 取原件 + 解析。这两步是同步阻塞的(网络IO/CPU)，丢线程池跑，
            # 不阻塞 worker 的事件循环。
            data = await run_in_threadpool(_download, doc.object_key)
            text = await asyncio.to_thread(extract_text, doc.file_ext, data)

            # 按这篇文档的类型读取切割配置(没配过用默认)，再按配置切割。
            # pairs 是一串 (小块, 父块)；普通策略父块为 None。
            cfg = await get_settings_for(session, doc.doc_type)
            pairs = chunk_documents(
                text,
                strategy=cfg.strategy,
                chunk_size=cfg.chunk_size,
                overlap=cfg.overlap,
                parent_size=cfg.parent_size,
            )
            if not pairs:
                # 没切出任何文字（比如扫描件没有文字层），算完成但 0 块，
                # 等以后接 OCR 再处理这类文件。
                doc.status = DocStatus.done
                doc.chunk_count = 0
                await session.commit()
                logger.warning("入库完成但无可切分文本 id=%s（可能是扫描件，待 OCR）", doc.id)
                return

            # 向量化用"小块"文本(pairs 里每对的第 0 个)。
            contents = [c for c, _parent in pairs]
            doc.status = DocStatus.embedding
            await session.commit()
            vectors = await embed_texts(contents)

            # 可重入保护：如果这篇文档之前已经入过库（比如失败后重试），
            # 先删掉它旧的所有 chunks，避免这次写入造成重复。
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            )

            # 每块都带上元数据：文档类型 + 业务标签(部门等)。
            # 检索时可以用这些字段先过滤(比如"只搜装配部门的 SOP")。
            # 每块用独立的 dict（dict(meta)），不要让所有块共享同一个字典对象。
            meta = {"doc_type": doc.doc_type, **(doc.biz_tags or {})}
            session.add_all(
                [
                    DocumentChunk(
                        document_id=doc.id,
                        seq=i,  # 块在文档里的顺序号
                        content=content,
                        content_tokens=tokenize(content),  # jieba 分词，供关键词检索
                        embedding=vector,
                        parent_content=parent,  # 父子切割时是父块文本，否则为 None
                        meta=dict(meta),
                    )
                    # zip(..., strict=True)：要求三者一一对应、长度相等，否则报错
                    for i, ((content, parent), vector) in enumerate(
                        zip(pairs, vectors, strict=True)
                    )
                ]
            )
            # 全部写好，标记完成并记下切了多少块
            doc.status = DocStatus.done
            doc.chunk_count = len(pairs)
            await session.commit()
            logger.info("入库完成 id=%s chunks=%s strategy=%s", doc.id, len(pairs), cfg.strategy)

        except Exception as e:  # noqa: BLE001  这里就是要兜住所有异常，落 failed
            # 出错时：先回滚没提交的改动，再把文档标成 failed 并记下错误原因。
            # 重新 get 一次 doc，是因为上面回滚后原对象可能已失效。
            await session.rollback()
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocStatus.failed
                doc.error = str(e)[:500]  # 错误信息可能很长，截断存
                await session.commit()
            logger.exception("入库失败 id=%s", document_id)
