"""实时日志活动检测：仅查询文件元数据，不读取内容或递归扫描。"""

import fnmatch
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


class LogFileActivity:
    """记录启动前的基线，并在现有运行循环中检测日志文件变化。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._snapshot: dict[Path, tuple[int, int, int]] | None = None
        self._warned = False
        self.poll()

    def _read_snapshot(self) -> dict[Path, tuple[int, int, int]]:
        if any(char in self.path.name for char in "*?["):
            try:
                with os.scandir(self.path.parent) as entries:
                    paths = [
                        Path(entry.path)
                        for entry in entries
                        if fnmatch.fnmatch(entry.name, self.path.name)
                    ]
            except FileNotFoundError:
                return {}  # 日志目录可能在脚本启动后才创建。
        else:
            paths = [self.path]
        snapshot = {}
        for path in paths:
            try:
                info = path.stat()
            except FileNotFoundError:
                continue  # 尚未创建，或恰好在轮转中被移走。
            if stat.S_ISREG(info.st_mode):
                snapshot[path] = (info.st_size, info.st_mtime_ns, info.st_ino)
        return snapshot

    def poll(self) -> bool:
        """新增、改写、截断或替换文件算活动；旧文件不变或仅删除不算。"""
        try:
            current = self._read_snapshot()
        except OSError as error:
            if not self._warned:
                logger.warning(
                    "无法检查日志文件 %s (%s): %s",
                    self.path,
                    type(error).__name__,
                    error,
                )
                self._warned = True
            return False  # 保留基线，避免恢复访问后误把旧日志算作新活动。
        self._warned = False
        changed = self._snapshot is not None and any(
            path not in self._snapshot or signature != self._snapshot[path]
            for path, signature in current.items()
        )
        self._snapshot = current
        return changed
