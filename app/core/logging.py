"""日志配置：统一日志的格式和输出位置。

现在只做最基础的"打到控制台"。等 P8(上线前硬化)再接告警、集中采集等。
"""

import logging
import sys

from app.core.config import settings


def setup_logging() -> None:
    """配置全局日志。在 main.py 启动时调用一次。"""
    # 开发时打 DEBUG(信息多、好排查)，生产打 INFO(少一些噪音)
    level = logging.DEBUG if settings.app_debug else logging.INFO

    # 把日志输出到标准输出(控制台)
    handler = logging.StreamHandler(sys.stdout)
    # 日志格式：时间 | 级别 | 是哪个模块打的 | 内容
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # root 是"根日志器"，所有日志最终都汇到它。先清掉已有处理器(避免重复配置导致日志打两遍)，
    # 再装上我们的处理器和级别。
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """取一个带名字的日志器。各文件用 get_logger(__name__)，
    日志里就能显示是哪个模块打的，方便定位。
    """
    return logging.getLogger(name)
