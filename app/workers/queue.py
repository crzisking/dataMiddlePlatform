"""异步任务队列（procrastinate，PostgreSQL 后端，无需 Redis）。

任务用于文档解析 / 向量化入库等耗时操作（P2 起使用）。

初始化队列表（首次，需 PG 可连）：
    uv run procrastinate --app=app.workers.queue.app schema --apply

启动 worker：
    uv run procrastinate --app=app.workers.queue.app worker
"""

from procrastinate import App, PsycopgConnector

import app.core.eventloop  # noqa: F401  worker 进程也需先设置 Windows 事件循环策略
from app.core.config import settings

# import_paths：worker 启动时导入这些模块以发现其中定义的任务。
app = App(
    connector=PsycopgConnector(conninfo=settings.pg_conninfo),
    import_paths=["app.workers.tasks"],
)


@app.task(name="ping")
def ping() -> str:
    """连通性自检任务。"""
    return "pong"
