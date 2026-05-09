"""轻量性能日志：带日期时间戳与毫秒级耗时。

与 app_log 共用文件 sink。
"""

from __future__ import annotations

import time

from .app_log import append_app_log, log_timestamp


def perf_log(message: str) -> None:
    line = f"[{log_timestamp()}] [perf] {message}"
    print(line, flush=True)
    append_app_log(line)


def perf_log_elapsed(label: str, t0: float) -> None:
    ms = (time.perf_counter() - t0) * 1000.0
    perf_log(f"{label} {ms:.1f}ms")
