"""文档"档案"管理：上传时建记录、查询时取记录。

这里负责的是文档的"档案信息"（documents 表）和原始文件（MinIO），
不负责把文件内容变成可检索的知识——那是 ingest.py 在后台异步做的。

上传时的职责：校验文件 → 判断版本 → 把原件存进 MinIO → 在 documents 表
建一条 status=pending 的记录。建完就交给异步任务去解析。
"""

import io
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import BadRequestError
from app.models.document import Document
from app.services.rag.upload import sha256_of, validate_upload
from app.services.storage.minio_client import ensure_bucket, get_minio


def _parse_biz_tags(raw: str | None) -> dict | None:
    """把前端传来的业务标签字符串(JSON)解析成字典。没传就返回 None。"""
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
    """把文件原件存进 MinIO。"""
    # MinIO 这个库是"同步"的（会阻塞），而我们在异步接口里。
    # 直接调用会卡住整个事件循环，所以丢到线程池里跑，不挡别的请求。
    bucket = await run_in_threadpool(ensure_bucket)
    await run_in_threadpool(
        get_minio().put_object,
        bucket,
        object_key,
        io.BytesIO(data),  # put_object 要一个"文件流"，把字节包成内存流
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
    """新建一个文档版本记录（status=pending），原件存 MinIO。

    注意：这里只 flush 拿到 id，不 commit。要不要真正提交由调用方决定，
    这样接口层能把"建记录"和"投递任务"放在一起控制提交时机。
    """
    ext = validate_upload(filename, data)  # 校验不过会直接抛 BadRequestError
    content_hash = sha256_of(data)
    biz_tags = _parse_biz_tags(biz_tags_raw)

    # —— 判断版本 ——
    # 规则：文件名 + 文档类型 相同，就算"同一篇文档的新版本"。
    # 先查这篇文档目前最大的版本号。
    max_v = (
        await session.execute(
            select(func.max(Document.version)).where(
                Document.name == filename, Document.doc_type == doc_type
            )
        )
    ).scalar()
    version = (max_v or 0) + 1  # 没查到(第一次传)就是 1，否则在最大版本上 +1
    if max_v:
        # 已有旧版本：把旧的"当前有效"版本标记为失效(is_active=False)。
        # 旧记录不删除，仍保留以便追溯，只是检索时不再用它。
        await session.execute(
            update(Document)
            .where(
                Document.name == filename,
                Document.doc_type == doc_type,
                Document.is_active.is_(True),
            )
            .values(is_active=False)
        )

    # —— 存原件到 MinIO ——
    # key 里加一段 uuid（随机串），保证不同文件/不同版本不会同名互相覆盖
    object_key = f"{doc_type}/{uuid4().hex}/{filename}"
    await _store_to_minio(object_key, data)

    # —— 在 documents 表建记录 ——
    doc = Document(
        name=filename,
        doc_type=doc_type,
        biz_tags=biz_tags,
        version=version,
        is_active=True,  # 新版本是当前有效版本
        file_ext=ext,
        file_size=len(data),
        content_hash=content_hash,
        object_key=object_key,
    )
    session.add(doc)
    await session.flush()  # flush：把 insert 发给数据库以拿到自增 id（但还没 commit）
    return doc


async def get_document(session: AsyncSession, doc_id: int) -> Document | None:
    """按 id 取单篇文档；查不到返回 None。供前端轮询上传/处理状态。"""
    return await session.get(Document, doc_id)


async def list_documents(
    session: AsyncSession,
    *,
    doc_type: str | None = None,
    status: str | None = None,
    only_active: bool = True,
    name: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Document], int]:
    """分页列出文档，返回 (当前页的记录列表, 满足条件的总条数)。

    总条数单独查，是为了让前端能算总页数（光有当前页算不出来）。
    name：按文件名模糊匹配（不区分大小写）。created_from/created_to：按创建时间范围过滤（含端点）。
    """
    # 把过滤条件收集到一个列表，下面查总数和查数据都复用同一组条件
    conditions = []
    if doc_type:
        conditions.append(Document.doc_type == doc_type)
    if status:
        conditions.append(Document.status == status)
    if only_active:
        conditions.append(Document.is_active.is_(True))  # 默认只看当前有效版本
    if name:
        # ilike：不区分大小写的模糊匹配；两边加 % 表示文件名里包含这段就算命中
        conditions.append(Document.name.ilike(f"%{name}%"))
    if created_from:
        conditions.append(Document.created_at >= created_from)
    if created_to:
        conditions.append(Document.created_at <= created_to)

    # 先查满足条件的总条数
    total = await session.scalar(
        select(func.count()).select_from(Document).where(*conditions)
    )
    # 再查当前页：按 id 倒序(最新的在前)，跳过前 offset 条，取 limit 条
    rows = (
        await session.execute(
            select(Document)
            .where(*conditions)
            .order_by(Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return list(rows), int(total or 0)
