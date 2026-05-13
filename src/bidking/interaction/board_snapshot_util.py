"""画板 JSON 快照的读写（仅用于交互层同步回合 / 对局 id，不含任何出价策略逻辑）。"""

from __future__ import annotations

import json
from typing import Any

from ..config.paths import resolve_board_snapshot_path


def _read_board_snapshot_if_enabled(config: dict[str, Any]) -> dict[str, Any] | None:
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return None
    raw_path = str(bs.get("path") or "").strip()
    path = resolve_board_snapshot_path(raw_path)
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


def load_board_snapshot_for_loop(config: dict[str, Any]) -> dict[str, Any] | None:
    """``board_snapshot.enabled`` 时读取快照文件（不检查 ``selected_mode``）。"""
    return _read_board_snapshot_if_enabled(config)


def current_round_from_snapshot(snapshot: dict[str, Any]) -> int | None:
    r = snapshot.get("current_round")
    if r is None:
        r = (snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def game_uid_from_snapshot(board_snapshot: dict[str, Any] | None) -> str | None:
    if not board_snapshot:
        return None
    u = str(board_snapshot.get("game_uid") or "").strip()
    if u:
        return u
    u = str((board_snapshot.get("game_state") or {}).get("uid") or "").strip()
    return u or None


def clear_board_snapshot_file(config: dict[str, Any]) -> bool:
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return False
    raw_path = str(bs.get("path") or "").strip()
    path = resolve_board_snapshot_path(raw_path)
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False
