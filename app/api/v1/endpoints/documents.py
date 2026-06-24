"""文档相关接口：上传、列表、查详情/状态。

上传只负责"快"的部分：校验 → 存 MinIO → 在表里登记(状态 pending) → 往队列投递
一个入库任务，然后立刻返回。真正的解析/切割/向量化由后台 worker 异步做。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.session import get_session
from app.services.rag.documents import (
    create_document_version,
    get_document,
    list_documents,
)
from app.workers.tasks import ingest_document

router = APIRouter()


class UploadResponse(BaseModel):
    """上传成功后返回给前端的内容。"""

    id: int
    name: str
    doc_type: str
    version: int
    status: str


class DocumentOut(BaseModel):
    # from_attributes=True：允许直接拿数据库 ORM 对象来构造这个响应模型，
    # 即 DocumentOut.model_validate(文档对象)，省去手动一个个字段抄。
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    doc_type: str
    biz_tags: dict | None
    version: int
    is_active: bool
    status: str
    chunk_count: int
    error: str | None
    file_ext: str
    file_size: int
    created_at: datetime
    updated_at: datetime


class DocumentListOut(BaseModel):
    """列表接口的返回：当前页数据 + 分页信息(总数/页码/每页大小)。"""

    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


@router.post("", response_model=UploadResponse)
async def upload_document(
    # File(...)：这是上传的文件本体；Form(...)：这些是和文件一起提交的表单字段
    file: UploadFile = File(..., description="上传的文档文件"),
    doc_type: str = Form(..., description="文档类型，如 SOP/工艺/质量/设备手册/制度"),
    biz_tags: str | None = Form(None, description="业务标签 JSON，如 {\"部门\":\"装配\"}"),
    session: AsyncSession = Depends(get_session),
) -> UploadResponse:
    """上传一篇文档。"""
    if not file.filename:
        raise BadRequestError("缺少文件名")
    # 把文件整个读进内存(受 100MB 上限保护)。后续可优化成边读边传给 MinIO 的流式方式。
    data = await file.read()

    # 校验 + 存 MinIO + 在表里建记录(此时还没 commit)
    doc = await create_document_version(
        session,
        filename=file.filename,
        data=data,
        doc_type=doc_type,
        biz_tags_raw=biz_tags,
    )
    # 顺序很重要：先 commit 让文档真正落库，再投递任务。
    # 否则任务可能比"文档落库"先被 worker 捞到，找不到这条文档。
    await session.commit()
    await ingest_document.defer_async(document_id=doc.id)

    return UploadResponse(
        id=doc.id,
        name=doc.name,
        doc_type=doc.doc_type,
        version=doc.version,
        status=doc.status,
    )


@router.get("", response_model=DocumentListOut)
async def list_docs(
    doc_type: str | None = Query(None, description="按文档类型过滤"),
    status: str | None = Query(None, description="按状态过滤(pending/done/failed 等)"),
    only_active: bool = Query(True, description="仅看当前有效版本"),
    page: int = Query(1, ge=1),  # ge=1：页码至少为 1
    page_size: int = Query(20, ge=1, le=100),  # 每页 1~100 条
    session: AsyncSession = Depends(get_session),
) -> DocumentListOut:
    """分页列出文档(给管理页用)。"""
    rows, total = await list_documents(
        session,
        doc_type=doc_type,
        status=status,
        only_active=only_active,
        limit=page_size,
        # 第 page 页要跳过前面 (page-1)*page_size 条
        offset=(page - 1) * page_size,
    )
    return DocumentListOut(
        items=[DocumentOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_doc(
    doc_id: int,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """查单篇文档的详情/状态。前端上传后可以定时调它，轮询处理进度。"""
    doc = await get_document(session, doc_id)
    if doc is None:
        raise NotFoundError(f"文档不存在 id={doc_id}")
    return DocumentOut.model_validate(doc)
