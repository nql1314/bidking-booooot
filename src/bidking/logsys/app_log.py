"""主应用日志：UI 关键决策行 / 对局信息（面向用户）。

``set_app_log_file(path)`` 后：经 ``log_info`` / ``print`` 等到 stdout、stderr 的内容
会同步写入该文件；``append_app_log`` 仍可单独写文件（如仅落盘、不打控制台）。
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

_APP_LOG_FILE: Optional[Path] = None
_APP_LOG_LOCK = threading.Lock()

_ORIGINAL_STDOUT: TextIO | None = None
_ORIGINAL_STDERR: TextIO | None = None
_TEE_STDOUT: "_TeeTextIO | None" = None
_TEE_STDERR: "_TeeTextIO | None" = None


def set_app_log_file(path: Optional[Path | str]) -> None:
    global _APP_LOG_FILE
    _APP_LOG_FILE = Path(path).resolve() if path is not None else None
    _sync_console_tee()


def append_app_log(line: str) -> None:
    _write_log_line(line)


def log_timestamp() -> str:
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"


def log_info(message: str, *, tag: str = "info") -> None:
    line = f"[{log_timestamp()}] [{tag}] {message}"
    print(line, flush=True)


def _write_log_line(line: str) -> None:
    path = _APP_LOG_FILE
    if path is None:
        return
    try:
        with _APP_LOG_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except OSError:
        pass


def _write_log_raw(text: str) -> None:
    path = _APP_LOG_FILE
    if not text or path is None:
        return
    try:
        with _APP_LOG_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(text)
    except OSError:
        pass


class _NullTextIO:
    """无控制台进程（pythonw / GUI 子线程）中 sys.stdout 或 sys.stderr 可能为 None。"""

    def write(self, data: str) -> int:
        return len(data) if data else 0

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def _as_text_stream(stream: TextIO | None) -> TextIO:
    return stream if stream is not None else _NullTextIO()  # type: ignore[return-value]


class _TeeTextIO:
    """将写入原流的文本按行复制到应用日志文件。"""

    def __init__(self, stream: TextIO | None) -> None:
        self._stream = _as_text_stream(stream)
        self._buf = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._stream.write(data)
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _write_log_raw(line.rstrip("\r") + "\n")
        return len(data)

    def flush(self) -> None:
        self._stream.flush()
        if self._buf:
            tail = self._buf.rstrip("\r")
            self._buf = ""
            if tail:
                _write_log_raw(tail + "\n")

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def _sync_console_tee() -> None:
    global _ORIGINAL_STDOUT, _ORIGINAL_STDERR, _TEE_STDOUT, _TEE_STDERR
    if _APP_LOG_FILE is not None:
        if _ORIGINAL_STDOUT is None:
            _ORIGINAL_STDOUT = sys.stdout
            _ORIGINAL_STDERR = sys.stderr
        if _TEE_STDOUT is None:
            _TEE_STDOUT = _TeeTextIO(_ORIGINAL_STDOUT)
            _TEE_STDERR = _TeeTextIO(_ORIGINAL_STDERR)
        sys.stdout = _TEE_STDOUT
        sys.stderr = _TEE_STDERR
        return
    if _ORIGINAL_STDOUT is not None:
        sys.stdout = _ORIGINAL_STDOUT
        sys.stderr = _ORIGINAL_STDERR
    _TEE_STDOUT = None
    _TEE_STDERR = None
