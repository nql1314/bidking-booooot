"""画板 JSON 快照的读写（仅用于交互层同步回合 / 对局 id，不含任何出价策略逻辑）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config.paths import resolve_board_snapshot_path


def board_snapshot_file_path(config: dict[str, Any]) -> Path | None:
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return None
    raw_path = str(bs.get("path") or "").strip()
    return resolve_board_snapshot_path(raw_path)


def board_snapshot_file_age_seconds(config: dict[str, Any]) -> float | None:
    """快照文件距上次修改的秒数；不存在时返回 ``None``。"""
    path = board_snapshot_file_path(config)
    if path is None or not path.is_file():
        return None
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def board_snapshot_max_stale_seconds(config: dict[str, Any]) -> float:
    bs = config.get("board_snapshot") or {}
    try:
        return max(0.0, float(bs.get("max_stale_seconds", 120.0)))
    except (TypeError, ValueError):
        return 120.0


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


class BoardSnapshotGameMismatch(RuntimeError):
    """画板快照与当前对局不一致（如画板卡死残留上一局数据）。"""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


def ensure_board_snapshot_matches_current_game(
    config: dict[str, Any],
    *,
    expected_game_uid: str | None,
    round_no: int,
    ocr_round: int | None = None,
    context: str = "",
) -> tuple[dict[str, Any] | None, str | None]:
    """读最新快照并校验属于当前对局；返回 ``(snapshot, resolved_game_uid)``。"""
    bs_cfg = config.get("board_snapshot") or {}
    if not bs_cfg.get("enabled"):
        return None, expected_game_uid

    snap = load_board_snapshot_for_loop(config)
    prefix = f"{context}: " if context else ""
    if snap is None:
        raise BoardSnapshotGameMismatch(
            f"{prefix}board_snapshot 已启用但文件不存在或无效",
            expected_game_uid=expected_game_uid,
            round_no=int(round_no),
            ocr_round=ocr_round,
        )

    snap_uid = game_uid_from_snapshot(snap)
    snap_round = current_round_from_snapshot(snap)
    rn = int(round_no)
    ocr_r = int(ocr_round) if ocr_round is not None else None

    if ocr_r is not None and snap_round is not None:
        if int(snap_round) > ocr_r + 1:
            raise BoardSnapshotGameMismatch(
                f"{prefix}画板快照回合 {snap_round} 领先 OCR 回合 {ocr_r}，疑似上一局残留",
                expected_game_uid=expected_game_uid,
                snapshot_game_uid=snap_uid,
                snapshot_round=snap_round,
                round_no=rn,
                ocr_round=ocr_r,
            )

    resolved_uid = str(expected_game_uid).strip() if expected_game_uid else None
    if not resolved_uid and snap_uid:
        resolved_uid = snap_uid
    elif resolved_uid and snap_uid and snap_uid != resolved_uid:
        raise BoardSnapshotGameMismatch(
            f"{prefix}画板快照 game_uid={snap_uid!r} 与当前对局 {resolved_uid!r} 不一致",
            expected_game_uid=resolved_uid,
            snapshot_game_uid=snap_uid,
            snapshot_round=snap_round,
            round_no=rn,
            ocr_round=ocr_r,
        )

    if snap_round is not None and abs(int(snap_round) - rn) > 2:
        raise BoardSnapshotGameMismatch(
            f"{prefix}画板快照回合 {snap_round} 与出价回合 {rn} 偏差过大",
            expected_game_uid=resolved_uid,
            snapshot_game_uid=snap_uid,
            snapshot_round=snap_round,
            round_no=rn,
            ocr_round=ocr_r,
        )

    max_stale = board_snapshot_max_stale_seconds(config)
    if max_stale > 0:
        age = board_snapshot_file_age_seconds(config)
        if age is not None and age > max_stale:
            raise BoardSnapshotGameMismatch(
                f"{prefix}画板快照已超过 {max_stale:.0f}s 未更新（约 {age:.0f}s），"
                "画板可能已关闭或卡死",
                expected_game_uid=resolved_uid,
                snapshot_game_uid=snap_uid,
                snapshot_round=snap_round,
                round_no=rn,
                ocr_round=ocr_r,
                stale_seconds=age,
                max_stale_seconds=max_stale,
            )

    return snap, resolved_uid or None


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
