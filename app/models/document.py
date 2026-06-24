"""文档相关的数据库表定义(ORM 模型)。

ORM 模型 = 用一个 Python 类来描述一张数据库表：类对应表，类里每个字段对应表里
一列。这样我们用 Python 对象就能读写数据库，不用手写 SQL。

这里有两张表：
- Document：每行是"一个上传的文档版本"，存的是档案信息(名字、类型、状态、
  文件在 MinIO 的位置等)，不存文件本身——文件本体在 MinIO。
- DocumentChunk：每行是"文档切碎后的一个文本块 + 它的向量"。
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin

# 向量的维度，跟配置走(通义 text-embedding-v3 是 1024)。
# 注意：这个数定了表里向量列的宽度，以后要改维度得配套做数据库迁移。
EMBEDDING_DIM = settings.embedding_dim


class DocStatus(StrEnum):
    """文档入库的几种状态。上传后由后台任务一步步往后推，前端靠它显示进度。"""

    pending = "pending"  # 刚登记，还没开始处理
    parsing = "parsing"  # 正在解析(抽文字)
    embedding = "embedding"  # 正在向量化
    done = "done"  # 处理完成，可被检索
    failed = "failed"  # 失败了(具体原因看 error 字段)


class Document(Base, TimestampMixin):
    # __tablename__ 指定这个类对应数据库里哪张表
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)  # 主键，自增
    name: Mapped[str] = mapped_column(String(512))  # 文件名
    doc_type: Mapped[str] = mapped_column(String(64))  # 文档类型，同时也是检索时的过滤标签
    # 业务标签(部门/产线/设备型号等)，用 JSONB 存任意键值。一期可空，主要为将来权限过滤预留
    biz_tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # —— 版本相关 ——
    # 规则：文件名+类型相同就算同一篇文档。重传时版本号 +1，旧版本的 is_active 置 False
    # (旧版不删除，保留以便追溯，只是检索时不再用它)。
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 是不是当前有效版本

    file_ext: Mapped[str] = mapped_column(String(16))  # 扩展名
    file_size: Mapped[int] = mapped_column(BigInteger)  # 文件大小(字节)
    content_hash: Mapped[str] = mapped_column(String(64))  # 内容的 SHA256 指纹，备用去重
    object_key: Mapped[str] = mapped_column(String(1024))  # 文件在 MinIO 里的存放路径

    status: Mapped[str] = mapped_column(String(16), default=DocStatus.pending.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败时记录原因
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # 切了多少块

    # 一对多关系：一篇文档对应多个 chunk。cascade=delete-orphan 表示
    # 删除文档时，它的 chunk 也自动一起删。
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_name_type", "name", "doc_type"),  # 判版本时按"名字+类型"查
        Index("ix_documents_active", "is_active"),  # 检索时只取有效版本
        # 唯一约束：同一篇文档(名字+类型)的同一个版本号只能有一条。
        # 作用是兜底防并发：两个相同文件同时上传、算出同一个版本号时，
        # 数据库会拒绝第二条，避免出现重复/脏数据。
        UniqueConstraint("name", "doc_type", "version", name="uq_documents_name_type_version"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 外键：指向它属于哪篇文档。ondelete=CASCADE：文档被删时，数据库自动删掉它的 chunk
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # 这块在文档里的顺序号(第几块)
    content: Mapped[str] = mapped_column(Text)  # 块的文本内容
    # jieba 分词结果，给中文关键词检索(BM25)用。P3 才会启用，这里先把列留好
    content_tokens: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))  # 这块的向量
    # 块的元数据(文档类型、部门标签等)，检索时可按这些字段先过滤
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        # 向量检索专用索引：HNSW 算法 + 余弦距离。
        # 必须和检索时用的距离一致(检索用 <=> 余弦距离)，否则索引用不上、检索会很慢。
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
