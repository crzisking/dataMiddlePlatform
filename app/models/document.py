"""RAG 文档与切块的 ORM 模型（数据底座，建在 PostgreSQL）。

- Document：每行 = 一个上传的文档版本（档案信息，不存文件本体；文件在 MinIO）。
- DocumentChunk：每行 = 文档切碎后的一个文本块 + 向量。
"""

from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin

# 向量维度跟随配置（通义 text-embedding-v3 = 1024）。改维度需配套迁移。
EMBEDDING_DIM = settings.embedding_dim


class DocStatus(StrEnum):
    """入库状态机：上传后异步流转，供前端回查进度。"""

    pending = "pending"  # 已入库登记，待处理
    parsing = "parsing"  # 解析中
    embedding = "embedding"  # 向量化中
    done = "done"  # 完成，可检索
    failed = "failed"  # 失败（见 error 字段）


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(512))  # 文件名
    doc_type: Mapped[str] = mapped_column(String(64))  # 文档类型，也是检索过滤标签
    # 部门/产线/设备型号等业务标签；预留权限过滤用，一期可空
    biz_tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 版本：同 (name, doc_type) 视为同一文档，重传则版本递增、旧版置 is_active=False（保留可追溯）
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    file_ext: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column(BigInteger)  # 字节
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256，备用去重/跳过重复 embedding
    object_key: Mapped[str] = mapped_column(String(1024))  # MinIO 对象 key

    status: Mapped[str] = mapped_column(String(16), default=DocStatus.pending.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # 按 (名称+类型) 查现有文档以判定新版本
        Index("ix_documents_name_type", "name", "doc_type"),
        # 检索时只取有效版本
        Index("ix_documents_active", "is_active"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 属于哪个文档版本；文档删除时级联删除其 chunk
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # 块在文档内的顺序
    content: Mapped[str] = mapped_column(Text)  # 块文本
    # jieba 分词结果，供中文 BM25 混合检索（P3 启用），先留列
    content_tokens: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))  # 向量
    # 标题路径 / 页码 / 类型 / 部门标签等，检索时元数据过滤
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        # 向量近邻检索索引：HNSW + 余弦距离（与检索时用的 <=> 一致）
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
