"""异步任务定义（procrastinate）。

任务在此登记，worker 通过 queue.py 的 import_paths 发现它们。
"""

from app.services.rag.ingest import ingest
from app.workers.queue import app


@app.task(name="ingest_document", queue="ingest")
async def ingest_document(document_id: int) -> None:
    """文档入库：解析 → 切割 → 向量化 → 写 chunks → 更新状态。"""
    await ingest(document_id)
