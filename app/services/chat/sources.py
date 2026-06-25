"""把检索旁路采集到的来源，整理成可下载的来源列表（含 MinIO 下载链接）。

两处复用：
- 问答接口：返回本轮答案引用的来源。
- 历史回看：把每条助手消息当初存的来源还原出来（重新签下载链接）。

为什么单独成一个服务：上面两处都要做"去重 + 拿文档名 + 现签下载链接"这同一套活，
抽出来避免两边各写一遍、还能保证行为一致。

关于下载链接：MinIO 预签名 URL 限时 1 小时会过期，**绝不存库**，所以每次都用文档的
object_key 现签（见 storage/minio_client.presigned_get_url）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.storage.minio_client import presigned_get_url


def dedupe_sources(items: list[dict]) -> list[dict]:
    """按 document_id 去重，保留首次出现的顺序。

    入参 items 形如 [{"document_id": 1, "document_name": "x"}, ...]（检索旁路采集的原始来源，
    同一篇文档常被多个 chunk 命中而重复）。返回去重后的同结构列表，用于存库 / 再加链接。
    """
    seen: set[int] = set()
    out: list[dict] = []
    for s in items:
        did = s["document_id"]
        if did not in seen:
            seen.add(did)
            out.append({"document_id": did, "document_name": s.get("document_name")})
    return out


async def attach_download_urls(session: AsyncSession, items: list[dict]) -> list[dict]:
    """给来源列表补上现签的 MinIO 下载链接。

    入参 items 是 [{"document_id", "document_name"}]（已去重）。按 id 批量查文档拿到
    object_key 现签下载链接；文档已删除则跳过。返回 [{document_id, document_name, download_url}]。
    """
    ids = [s["document_id"] for s in items]
    if not ids:
        return []
    docs = (await session.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
    by_id = {d.id: d for d in docs}
    out: list[dict] = []
    for s in items:
        doc = by_id.get(s["document_id"])
        if doc is not None:  # 文档还在才给链接；已删除的就不返回了
            out.append(
                {
                    "document_id": doc.id,
                    "document_name": doc.name,
                    "download_url": presigned_get_url(doc.object_key),
                }
            )
    return out
