"""异步任务队列(用 procrastinate 库，队列直接存在 PostgreSQL 里，不需要 Redis)。

什么是任务队列：像文档解析、向量化这种耗时的活，不能让用户上传时干等。
做法是：上传时只往队列里"投"一条待办，立刻返回；后台一个常驻的 worker
进程不断从队列里"捞"待办来执行。这里就是定义这个队列(App)的地方。

首次要先把队列用的表建到 PostgreSQL(只做一次)：
    uv run procrastinate --app=app.workers.queue.app schema --apply

启动后台 worker(它来真正执行任务)：
    uv run procrastinate --app=app.workers.queue.app worker
"""

from procrastinate import App, PsycopgConnector

import app.core.eventloop  # noqa: F401  worker 进程也要先设置 Windows 事件循环策略
from app.core.config import settings

# App 是整个队列的入口。
# - connector：告诉它队列存在哪个 PostgreSQL(用原生连接串)。
# - import_paths：worker 启动时会 import 这些模块，从而"发现"里面用 @app.task
#   定义的任务。我们的任务都写在 app.workers.tasks 里，所以登记它。
app = App(
    connector=PsycopgConnector(conninfo=settings.pg_conninfo),
    import_paths=["app.workers.tasks"],
)


@app.task(name="ping")
def ping() -> str:
    """一个用来自检"队列通不通"的小任务。"""
    return "pong"
