"""OCR 详细日志（识别耗时 / 文本片段 / 结果命中等）。

由全局开关 ``set_ocr_log_enabled(True)`` 控制，对应 runtime.debug.print_ocr_snippet
等开关；默认关闭，避免主日志噪音。
"""

from __future__ import annotations

from .app_log import append_app_log, log_timestamp

_OCR_LOG_ENABLED = False


def set_ocr_log_enabled(enabled: bool) -> None:
    global _OCR_LOG_ENABLED
    _OCR_LOG_ENABLED = bool(enabled)


def ocr_log_enabled() -> bool:
    return _OCR_LOG_ENABLED


def ocr_log(message: str) -> None:
    if not _OCR_LOG_ENABLED:
        return
    line = f"[{log_timestamp()}] [ocr] {message}"
    print(line, flush=True)
    append_app_log(line)
