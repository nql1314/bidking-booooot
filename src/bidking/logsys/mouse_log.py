"""鼠标 / 键盘动作详细日志。

由 ``set_mouse_log_enabled(True)`` 控制；默认关闭。
"""

from __future__ import annotations

from .app_log import append_app_log, log_timestamp

_MOUSE_LOG_ENABLED = False


def set_mouse_log_enabled(enabled: bool) -> None:
    global _MOUSE_LOG_ENABLED
    _MOUSE_LOG_ENABLED = bool(enabled)


def mouse_log_enabled() -> bool:
    return _MOUSE_LOG_ENABLED


def mouse_log(message: str) -> None:
    if not _MOUSE_LOG_ENABLED:
        return
    line = f"[{log_timestamp()}] [mouse] {message}"
    print(line, flush=True)
    append_app_log(line)
