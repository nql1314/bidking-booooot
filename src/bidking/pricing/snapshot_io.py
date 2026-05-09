"""pricing 层读取 ``board_snapshot.path``（与 interaction.board_snapshot_util 字段约定一致）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_board_snapshot_if_enabled(config: dict[str, Any]) -> dict[str, Any] | None:
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return None
    raw_path = str(bs.get("path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    min_sv = int(bs.get("schema_version_min", 1))
    if int(data.get("schema_version", 0)) < min_sv:
        return None
    return data


def current_round_from_snapshot(snapshot: dict[str, Any]) -> int | None:
    r = snapshot.get("current_round")
    if r is None:
        r = (snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None
