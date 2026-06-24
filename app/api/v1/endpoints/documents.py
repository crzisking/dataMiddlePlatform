"""文档上传接口（P2 子步骤 3）。

收文件 + 元数据 → 校验 → 存 MinIO → 建文档记录(pending) → 投递异步入库任务。
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.session import get_session
from app.services.rag.documents import create_document_version
from app.workers.tasks import ingest_document

router = APIRouter()


class UploadResponse(BaseModel):
    id: int
    name: str
    doc_type: str
    version: int
    status: str


@router.post("", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(..., description="上传的文档文件"),
    doc_type: str = Form(..., description="文档类型，如 SOP/工艺/质量/设备手册/制度"),
    biz_tags: str | None = Form(None, description="业务标签 JSON，如 {\"部门\":\"装配\"}"),
    session: AsyncSession = Depends(get_session),
) -> UploadResponse:
    if not file.filename:
        raise BadRequestError("缺少文件名")
    data = await file.read()  # 读入内存（100MB 上限）；后续可优化为流式直传 MinIO

    doc = await create_document_version(
        session,
        filename=file.filename,
        data=data,
        doc_type=doc_type,
        biz_tags_raw=biz_tags,
    )
    # 先提交（文档落库），再投递任务：避免任务指向一个未提交的文档
    await session.commit()
    await ingest_document.defer_async(document_id=doc.id)

    return UploadResponse(
        id=doc.id,
        name=doc.name,
        doc_type=doc.doc_type,
        version=doc.version,
        status=doc.status,
    )
