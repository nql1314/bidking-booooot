"""runner 公共工具：加载 runtime + pricing、配置日志开关、初始化 snapshot bridge。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from ..bridge import (
    BoardSnapshotFileWriter,
    get_default_store,
    write_mode_from_runtime,
)
from ..config import RuntimeConfig, load_pricing, load_runtime
from ..config.paths import resolve_board_snapshot_path
from ..logsys import (
    set_app_log_file,
    set_mouse_log_enabled,
    set_ocr_log_enabled,
)


def load_all() -> Tuple[RuntimeConfig, Dict[str, Any]]:
    runtime = load_runtime()
    pricing = load_pricing()
    return runtime, pricing


def configure_logging(runtime: RuntimeConfig, *, app_log_path: Path | None) -> None:
    debug = runtime.debug
    set_app_log_file(app_log_path)
    set_ocr_log_enabled(bool(debug.get("print_ocr_snippet", False) or debug.get("save_ocr_text", False)))
    set_mouse_log_enabled(bool(debug.get("print_round_debug", False)))


def make_snapshot_writer(runtime: RuntimeConfig) -> BoardSnapshotFileWriter | None:
    bs = runtime.board_snapshot
    if not bs.get("enabled"):
        return None
    raw_path = str(bs.get("path") or "").strip()
    mode = write_mode_from_runtime(bs)
    return BoardSnapshotFileWriter(resolve_board_snapshot_path(raw_path), mode=mode)


def install_snapshot_file_writer(runtime: RuntimeConfig) -> BoardSnapshotFileWriter | None:
    """订阅 :mod:`bidking.bridge.snapshot_store`，把每次 publish 的 dict 写到磁盘。"""
    writer = make_snapshot_writer(runtime)
    if writer is None or not writer.enabled:
        return writer
    store = get_default_store()
    store.subscribe(writer.write)
    return writer


__all__ = [
    "load_all",
    "configure_logging",
    "make_snapshot_writer",
    "install_snapshot_file_writer",
]
