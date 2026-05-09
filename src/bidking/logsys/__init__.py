"""第 6 层 · 日志：app / perf / ocr / mouse / debug-dump。"""

from .app_log import (
    append_app_log,
    log_timestamp,
    set_app_log_file,
    log_info,
)
from .perf_log import perf_log, perf_log_elapsed
from .ocr_log import ocr_log, ocr_log_enabled, set_ocr_log_enabled
from .mouse_log import mouse_log, mouse_log_enabled, set_mouse_log_enabled
from .debug_dump import save_round_debug_bundle

__all__ = [
    "append_app_log",
    "log_timestamp",
    "set_app_log_file",
    "log_info",
    "perf_log",
    "perf_log_elapsed",
    "ocr_log",
    "ocr_log_enabled",
    "set_ocr_log_enabled",
    "mouse_log",
    "mouse_log_enabled",
    "set_mouse_log_enabled",
    "save_round_debug_bundle",
]
