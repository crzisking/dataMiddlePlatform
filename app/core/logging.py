"""日志配置：统一日志的格式和输出位置（控制台 + 文件）。

日志同时打到：
- 控制台(stdout)：开发时实时看
- 文件 logs/<name>.log：持久化、可回溯。带轮转(单文件最大 10MB、留 5 个旧文件)，不会无限长大。

为什么按 name 分文件：API 和 Worker 是两个进程，各写各的(api.log / worker.log)，
避免两个进程抢同一个文件、轮转打架。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

# 日志目录(项目根下 logs/)，不存在就建。logs/ 已在 .gitignore 里，不会进 git。
_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


def setup_logging(name: str = "app") -> None:
    """配置全局日志。API 启动时 setup_logging('api')，Worker 进程 setup_logging('worker')。"""
    level = logging.DEBUG if settings.app_debug else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    # 文件(轮转)：logs/<name>.log，单个最大 10MB，保留 5 个历史
    _LOG_DIR.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        _LOG_DIR / f"{name}.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",  # 中文日志不乱码
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()  # 清掉旧处理器，避免重复配置导致日志打多遍
    root.addHandler(console)
    root.addHandler(file_handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """取一个带名字的日志器。各文件用 get_logger(__name__)，
    日志里就能显示是哪个模块打的，方便定位。
    """
    return logging.getLogger(name)
