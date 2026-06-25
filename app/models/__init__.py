"""ORM 模型集中导入处。

Alembic 通过 import 此模块的 Base.metadata 识别所有表。
新增模型务必在此导入，否则迁移检测不到。
"""

from app.db.base import Base
from app.models.chunk_config import ChunkConfig
from app.models.conversation import Conversation, Message
from app.models.document import DocStatus, Document, DocumentChunk

__all__ = [
    "Base",
    "Document",
    "DocumentChunk",
    "DocStatus",
    "ChunkConfig",
    "Conversation",
    "Message",
]
