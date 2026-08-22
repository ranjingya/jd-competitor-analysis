"""提供后端批处理进程互斥锁。"""

from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


LOGGER = logging.getLogger(__name__)


@contextmanager
def acquire_job_lock(path: Path) -> Iterator[bool]:
    """尝试获取批处理进程锁。

    功能说明：使用非阻塞文件锁防止同一数据目录同时运行两个日分析进程，退出上下文时自动释放。
    参数 path：锁文件路径；应位于与 SQLite 数据库相同的持久化目录。
    返回值：是否成功获得锁的布尔值迭代器。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file: TextIO = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            LOGGER.info("日分析进程锁已获取：%s", path)
        except BlockingIOError:
            LOGGER.warning("已有日分析任务正在运行：%s", path)
        yield acquired
    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            LOGGER.info("日分析进程锁已释放：%s", path)
        lock_file.close()
