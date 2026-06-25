"""会话历史读写：加载某会话的历史消息、把新一轮存回去、列会话/查消息。

网页端多轮对话靠这里：每轮对话前 load_history 取上文喂给 Agent，
答完 append_turn 把"用户问 + AI 答"写回。
"""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message


async def load_history(session: AsyncSession, conversation_id: str) -> list[AnyMessage]:
    """取某会话已有的历史消息，转成 Agent 能用的消息对象(按时间顺序)。"""
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
    ).scalars().all()
    return [
        HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        for m in rows
    ]


async def append_turn(
    session: AsyncSession,
    conversation_id: str,
    *,
    user_text: str,
    assistant_text: str,
) -> None:
    """把这一轮(用户问 + AI 答)写回数据库。会话不存在则顺便建一条。

    不在这里 commit，由调用方(接口)统一提交。
    """
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        # 首次对话：建会话，标题取首条提问的前 40 字
        conv = Conversation(id=conversation_id, title=user_text[:40] or "新对话")
        session.add(conv)

    session.add(Message(conversation_id=conversation_id, role="user", content=user_text))
    session.add(
        Message(conversation_id=conversation_id, role="assistant", content=assistant_text)
    )


async def list_conversations(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[Conversation]:
    """列出会话(最近更新的在前)，供历史列表。"""
    rows = (
        await session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return list(rows)


async def get_messages(session: AsyncSession, conversation_id: str) -> list[Message]:
    """取某会话的全部消息(按顺序)，供历史回看。"""
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
    ).scalars().all()
    return list(rows)
