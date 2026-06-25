"""切割配置表：每种文档类型用什么切割策略和参数，存在这里，可由管理页改。

为什么要单独一张表：不同文档(SOP vs 工艺表格)适合不同的切法。把切法做成
"可配置"，管理员就能不改代码地为每类文档调参数。入库时按文档类型读这里的配置。
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChunkConfig(Base, TimestampMixin):
    __tablename__ = "chunk_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 文档类型，唯一(每种类型一条配置)。入库时按文档的 doc_type 来这查配置。
    doc_type: Mapped[str] = mapped_column(String(64), unique=True)

    # 切割策略：
    #   recursive    —— 普通递归切(默认)
    #   parent_child —— 父子切(小块用于检索、命中后返回所在的大块给模型，上下文更全)
    strategy: Mapped[str] = mapped_column(String(32), default="recursive")

    chunk_size: Mapped[int] = mapped_column(Integer, default=512)  # 小块目标大小(字符)
    overlap: Mapped[int] = mapped_column(Integer, default=50)  # 相邻块重叠
    # 父块大小，仅 parent_child 策略用：先切成这么大的"父块"，再把父块切成小块
    parent_size: Mapped[int] = mapped_column(Integer, default=2048)
