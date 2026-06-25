"""语义层表（schema_docs）：TextToSQL 的"业务数据字典"。

这张表存的是**对业务库（SQL Server）里视图/表的中文描述**——表/视图是干嘛的、
每个字段什么意思、表怎么关联、典型查法等。TextToSQL 提问时先按问题向量检索出相关的
几条，再据此让大模型写 SQL。**它不存业务数据本身**，只存"怎么读懂业务库"的元信息。

一条记录 = 业务库的一个视图（首选）或一组裸表（兜底），用 source_type 区分：
- view：DBA 整理好的 `v_ai_` 宽视图（已 JOIN、已翻译），模型不用自己 JOIN，准确率高。
- table：建不了视图的裸表（如按日期分片的表），靠文字描述 + 显式关系，模型自己 JOIN。

详细设计见 项目选型/TextToSQL.md 第七节。
"""

from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base, TimestampMixin

# 向量维度跟全局配置走（通义 text-embedding-v3 是 1024），和 RAG 那边一致。
EMBEDDING_DIM = settings.embedding_dim


class SourceType(StrEnum):
    """数据源的两类（详见 TextToSQL.md 7.3.2）。"""

    view = "view"  # 整理好的业务视图（首选）
    table = "table"  # 只能文字描述的裸表（兜底）


class SchemaDoc(Base, TimestampMixin):
    __tablename__ = "schema_docs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # —— 基本身份 ——
    source_type: Mapped[str] = mapped_column(String(16), default=SourceType.view.value)
    # 视图名/表名，如 v_ai_制程不良明细。唯一：一个对象一条语义记录。
    object_name: Mapped[str] = mapped_column(String(256), unique=True)
    # 中文用途，一句话说清这个视图/表是干嘛的（检索 + 喂模型都用它）
    desc: Mapped[str] = mapped_column(Text)
    # 粒度，如"一行 = 一个批次"。防模型聚合时重复计数；可空（填了更稳）
    grain: Mapped[str | None] = mapped_column(Text, nullable=True)

    # —— 字段与关系 ——
    # 字段清单，JSON：[{"name","type","desc","unit","values"}, ...]。渲染给模型的 DDL 名片用。
    columns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 表关系（谁的哪个键 = 谁的哪个键）。视图通常为空（已 JOIN 好）；裸表必填，否则模型会乱 JOIN。
    relations: Mapped[str | None] = mapped_column(Text, nullable=True)
    # few-shot：典型问法 ↔ SQL 样例。提升准确率最有效的一项，尤其裸表路径。
    samples: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 业务术语别名，如"不良=次品=NG"。一起参与 embedding，提升检索召回。
    aliases: Mapped[str | None] = mapped_column(Text, nullable=True)

    # —— 大数据量护栏元数据（详见 TextToSQL.md 7.3.1）——
    # 必填过滤列（通常是日期）：模型没带它，校验器自动注入默认时间窗，防裸跑全表。
    required_filter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 默认时间窗 / 最大可查范围，如 "近30天" / "1年"。
    default_window: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_window: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 读隔离级别，如 "nolock"。查生产库时用，避免和业务抢锁。
    isolation: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # —— 检索用 ——
    # 描述文本的向量。可空：先建好"架子"（占位行）、内容填好后再向量化回填。
    # 没向量的行不会被检索命中（schema-RAG 只在有向量的行里找）。
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # 是否启用：占位/未整理好的行设 False，不参与检索；整理好再开 True。
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        # 向量检索索引：HNSW + 余弦距离，和 document_chunks 一致（检索时用 <=> 余弦距离才用得上）
        Index(
            "ix_schema_docs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
