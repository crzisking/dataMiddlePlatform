"""SQLAlchemy 声明基类。所有 ORM 模型继承 Base。

新增模型后，在 app/models/__init__.py 中导入，Alembic 才能自动识别。
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """通用创建/更新时间戳。需要的表 `class X(Base, TimestampMixin)` 即可复用。"""

    # server_default=func.now()：默认值由数据库生成（而非 Python），多端写入时间一致。
    # timezone=True：存带时区的时间，避免跨时区歧义。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # onupdate：每次 UPDATE 自动刷新为当前时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
