"""UI 内的关键决策 / 对局信息流（替换原 ``GuiLogger`` 的部分功能）。

最小封装：一个线程安全的环形缓冲 + 订阅回调；UI 控件可在 ``mainloop`` 中
通过 ``after`` 拉取 / 渲染。详细 OCR / 鼠标日志走文件，不进 UI。
"""

from __future__ import annotations

import collections
import threading
from typing import Callable, Deque, List, Optional

from ..logsys.app_log import log_timestamp


class UiLogView:
    def __init__(self, max_lines: int = 1000) -> None:
        self._lock = threading.Lock()
        self._buf: Deque[str] = collections.deque(maxlen=max_lines)
        self._listeners: List[Callable[[str], None]] = []

    def write(self, line: str, *, tag: str = "ui") -> None:
        ts = log_timestamp()
        formatted = f"[{ts}] [{tag}] {line}"
        with self._lock:
            self._buf.append(formatted)
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(formatted)
            except Exception:
                pass

    def snapshot(self) -> List[str]:
        with self._lock:
            return list(self._buf)

    def subscribe(self, cb: Callable[[str], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(cb)

        def _unsub() -> None:
            with self._lock:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass

        return _unsub


_DEFAULT: Optional[UiLogView] = None


def default_view() -> UiLogView:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = UiLogView()
    return _DEFAULT


__all__ = ["UiLogView", "default_view"]
