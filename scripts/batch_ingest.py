"""批量入库脚本：把一个文件夹里的文档逐个灌进 RAG 知识库。

用法：
    uv run python scripts/batch_ingest.py <文件夹> --doc-type <类型>
例：
    uv run python scripts/batch_ingest.py C:\\Users\\Admin\\Desktop\\ragUse_docx --doc-type 通用

做的事：扫描文件夹 → 按白名单过滤 → 逐个 校验/存MinIO/建记录/解析切割向量化入库。
直接调入库流程(不经队列)，所以不需要单独开 worker。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# eventloop 必须在 app.db.session(会建异步引擎)之前设置好 Windows 事件循环策略。
# plain `import` 会被排在所有 `from app...` 之前，顺序天然满足，无需手动调位置。
import app.core.eventloop  # noqa: F401
from app.core.config import settings
from app.db.session import async_session_factory
from app.models.document import Document
from app.services.rag.documents import create_document_version
from app.services.rag.ingest import ingest


async def ingest_one(path: Path, doc_type: str) -> tuple[str, str]:
    """灌一个文件，返回 (文件名, 结果状态/错误)。"""
    data = path.read_bytes()
    async with async_session_factory() as session:
        doc = await create_document_version(
            session, filename=path.name, data=data, doc_type=doc_type
        )
        await session.commit()
        doc_id = doc.id
    await ingest(doc_id)  # 解析→切割→embedding→写chunks→更新状态
    async with async_session_factory() as session:
        d = await session.get(Document, doc_id)
        result = f"{d.status} (chunks={d.chunk_count})"
        if d.error:
            result += f" err={d.error}"
        return path.name, result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="要批量上传的文件夹")
    parser.add_argument("--doc-type", default="通用", help="文档类型(默认 通用)")
    args = parser.parse_args()

    folder = Path(args.folder)
    allowed = settings.allowed_exts

    def _ext_ok(p: Path) -> bool:
        return p.is_file() and p.suffix.lstrip(".").lower() in allowed

    files = [p for p in sorted(folder.iterdir()) if _ext_ok(p)]
    skipped = [p.name for p in folder.iterdir() if p.is_file() and not _ext_ok(p)]

    print(f"待入库: {len(files)} 个；跳过(格式不支持): {len(skipped)} 个")
    ok = 0
    failed = 0
    for i, path in enumerate(files, 1):
        try:
            name, result = await ingest_one(path, args.doc_type)
            status_ok = result.startswith("done")
            ok += status_ok
            failed += not status_ok
            print(f"[{i}/{len(files)}] {name} -> {result}", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[{i}/{len(files)}] {path.name} -> 异常: {e}", flush=True)

    print(f"\n完成：成功 {ok} / 失败 {failed} / 跳过 {len(skipped)}")
    if skipped:
        print("跳过的文件:", skipped)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
