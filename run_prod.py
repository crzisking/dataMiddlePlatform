"""生产启动入口（Windows 专用）：强制用 SelectorEventLoop 跑 uvicorn。

为什么需要它：直接 `uvicorn app.main:app`（无 --reload）启动时，uvicorn 会在
`uvicorn.run()` 内部自行设置事件循环，Windows 上会用成默认的 ProactorEventLoop——
而 psycopg(异步) 不兼容 Proactor，导致连不上 PG（日志狂刷
"Psycopg cannot use the 'ProactorEventLoop'"）。仅靠 app/core/eventloop.py 设策略也不够，
会被 uvicorn 覆盖。

这里的做法：**自己建一个 SelectorEventLoop 并直接驱动 uvicorn 的 server.serve()**，
不走 `uvicorn.run()`（那个会重置循环），从而确保用的是 SelectorEventLoop。

用法（生产，不带 --reload）：
    .venv\\Scripts\\python run_prod.py
"""

import asyncio

import uvicorn

from app.core.config import settings


def main() -> None:
    # 显式建 SelectorEventLoop 并设为当前循环（绕开 uvicorn 自己的循环设置）
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config("app.main:app", host=settings.app_host, port=settings.app_port)
    server = uvicorn.Server(config)
    # 直接驱动 serve()（不调 server.run()，那个会重置成 Proactor）
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
