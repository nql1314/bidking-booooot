"""主应用日志：UI 关键决策行 / 对局信息（面向用户）。

stdout + 可选复制到文件 ``set_app_log_file(path)``；线程安全。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_APP_LOG_FILE: Optional[Path] = None
_APP_LOG_LOCK = threading.Lock()


def set_app_log_file(path: Optional[Path | str]) -> None:
    global _APP_LOG_FILE
    _APP_LOG_FILE = Path(path).resolve() if path is not None else None


def append_app_log(line: str) -> None:
    path = _APP_LOG_FILE
    if path is None:
        return
    try:
        with _APP_LOG_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except OSError:
        pass


def log_timestamp() -> str:
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"


def log_info(message: str, *, tag: str = "info") -> None:
    line = f"[{log_timestamp()}] [{tag}] {message}"
    print(line, flush=True)
    append_app_log(line)
