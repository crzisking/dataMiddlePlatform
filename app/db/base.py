"""所有数据库表模型的"共同基类"。

Base 是 SQLAlchemy 要求的基类，所有表模型(如 Document)都要继承它，
SQLAlchemy 才知道"这些类是数据库表"。

提醒：新建了模型文件后，要在 app/models/__init__.py 里 import 一下，
Alembic(迁移工具)才能扫描到它、生成建表脚本。
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """一个"可复用的时间戳零件"：哪张表想要创建/更新时间，就
    `class 某表(Base, TimestampMixin)` 一起继承，自动获得下面两个字段。
    """

    # created_at：记录创建时间。
    # server_default=func.now()：默认值由"数据库"在插入时生成(而不是 Python 端)，
    #   这样不管哪台机器写入，时间都以数据库为准、保持一致。
    # timezone=True：存带时区的时间，避免跨时区时间对不上。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # updated_at：记录最后修改时间。
    # onupdate=func.now()：每次这行被 UPDATE 时，数据库自动把它刷成当前时间。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
