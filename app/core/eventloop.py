"""Windows 事件循环修复（import 即生效）。

psycopg(异步) 与 procrastinate 在 Windows 上不支持默认的 ProactorEventLoop，
必须用 SelectorEventLoop。须在任何事件循环创建之前设置，故由各入口最先 import 本模块。

注意：SelectorEventLoop 在 Windows 有 ~512 套接字上限（Windows 阶段约束，迁 Linux 后无此限）。
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
