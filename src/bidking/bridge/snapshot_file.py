"""可选 JSON 快照文件读写：兼容既有外部看板 / 单独进程消费。

由 ``runtime.board_snapshot.write_mode`` 控制：

- ``"off"``  —— 不写文件，仅进程内总线
- ``"file"`` —— 仅写文件
- ``"both"`` —— 同时进程内 + 写文件（默认）
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


def write_mode_from_runtime(board_snapshot_cfg: Mapping[str, Any]) -> str:
    raw = str(board_snapshot_cfg.get("write_mode", "both")).lower()
    if raw not in {"off", "file", "both"}:
        return "both"
    return raw


class BoardSnapshotFileWriter:
    def __init__(self, path: Path | str, *, mode: str = "both") -> None:
        self.path = Path(path)
        self.mode = mode
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.mode in {"file", "both"}

    def write(self, snapshot: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        with self._lock:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=".board_snapshot.",
                suffix=".tmp",
                delete=False,
            ) as fp:
                fp.write(payload)
                tmp_path = Path(fp.name)
            os.replace(tmp_path, self.path)

    def archive(self, dest_dir: Path | str) -> Optional[Path]:
        """把当前 snapshot 文件另存到 ``dest_dir``（用于开局归档旧局）。"""
        if not self.path.is_file():
            return None
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        archived = dest / f"board_snapshot_{ts}.json"
        try:
            archived.write_bytes(self.path.read_bytes())
        except OSError:
            return None
        return archived


class BoardSnapshotFileReader:
    """供独立看板 / 外部 bot 进程读取最新快照（轮询或一次性）。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> Optional[Dict[str, Any]]:
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except (OSError, ValueError):
            return None

    def mtime(self) -> Optional[float]:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None
