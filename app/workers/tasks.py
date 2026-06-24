"""异步任务的定义处。

每个用 @app.task 装饰的函数就是一个"可被投递、由 worker 执行"的任务。
worker 启动时通过 queue.py 里的 import_paths 把本模块导入，从而发现这些任务。

真正的处理逻辑写在 app/services/rag/ 里，这里只做一层很薄的"任务入口"。
"""

from app.services.rag.ingest import ingest
from app.workers.queue import app


@app.task(name="ingest_document", queue="ingest")
async def ingest_document(document_id: int) -> None:
    """文档入库任务：解析 → 切割 → 向量化 → 写 chunks → 更新状态。

    具体流程都在 ingest() 里，这里只是把任务和它接起来。
    上传接口用 ingest_document.defer_async(document_id=...) 投递它。
    """
    await ingest(document_id)
