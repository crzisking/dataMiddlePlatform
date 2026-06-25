"""对话存储：会话表 + 消息表(网页端多轮对话的"唯一真相"，方案 B)。

- Conversation：一条 = 一个会话(像 ChatGPT 左边的一条对话)。
- Message：一条 = 会话里的一句(用户问 或 AI 答)。
按 conversation_id 把消息归到会话下；每轮对话前读历史、答完写回。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    # 会话 ID 用字符串(由前端生成，比如 uuid)，所以主键是 str 不是自增整数
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")  # 一般取首条提问做标题

    # 一对多：一个会话有多条消息。删会话时消息一起删。
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",  # 按写入顺序排，也就是对话先后顺序
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user"=用户说的，"assistant"=AI 说的
    content: Mapped[str] = mapped_column(Text)
    # 这条回答引用的来源文档，形如 [{"document_id": 1, "document_name": "x.docx"}, ...]。
    # 只存 id + 名字，**不存下载链接**——MinIO 预签名 URL 限时会过期，要用时现签。
    # 只有助手消息、且本轮真的检索了才有值；用户消息恒为空。
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
