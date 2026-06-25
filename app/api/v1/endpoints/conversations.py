"""会话历史接口：列出会话、查看某会话的全部消息(供前端历史回看)。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.chat.history import get_messages, list_conversations

router = APIRouter()


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    created_at: datetime


@router.get("", response_model=list[ConversationOut])
async def list_convs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    """列出会话(最近更新的在前)。"""
    rows = await list_conversations(session, limit=limit, offset=offset)
    return [ConversationOut.model_validate(r) for r in rows]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_conv_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    """查看某会话的全部消息(按对话顺序)。"""
    rows = await get_messages(session, conversation_id)
    return [MessageOut.model_validate(r) for r in rows]
