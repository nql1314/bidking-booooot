# -*- coding: utf-8 -*-
"""出价前画板快照与当前对局一致性校验。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from bidking.interaction.board_snapshot_util import (
    BoardSnapshotGameMismatch,
    board_snapshot_stop_bot_on_game_mismatch,
    ensure_board_snapshot_matches_current_game,
)


def _write_snapshot(path: Path, *, game_uid: str, current_round: int) -> None:
    payload = {
        "schema_version": 1,
        "game_uid": game_uid,
        "current_round": current_round,
        "game_state": {"uid": game_uid, "current_round": current_round},
        "skill_logs": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_accepts_matching_game_uid(tmp_path: Path) -> None:
    snap_path = tmp_path / "board_snapshot.json"
    _write_snapshot(snap_path, game_uid="2107:g1", current_round=2)
    config = {
        "board_snapshot": {"enabled": True, "path": str(snap_path), "schema_version_min": 1},
    }
    snap, uid = ensure_board_snapshot_matches_current_game(
        config,
        expected_game_uid="2107:g1",
        round_no=2,
        ocr_round=2,
        context="test",
    )
    assert snap is not None
    assert uid == "2107:g1"


def test_binds_game_uid_when_unset(tmp_path: Path) -> None:
    snap_path = tmp_path / "board_snapshot.json"
    _write_snapshot(snap_path, game_uid="2107:g2", current_round=1)
    config = {
        "board_snapshot": {"enabled": True, "path": str(snap_path), "schema_version_min": 1},
    }
    _, uid = ensure_board_snapshot_matches_current_game(
        config,
        expected_game_uid=None,
        round_no=1,
        ocr_round=1,
    )
    assert uid == "2107:g2"


def test_rejects_mismatched_game_uid(tmp_path: Path) -> None:
    snap_path = tmp_path / "board_snapshot.json"
    _write_snapshot(snap_path, game_uid="2107:old", current_round=2)
    config = {
        "board_snapshot": {"enabled": True, "path": str(snap_path), "schema_version_min": 1},
    }
    with pytest.raises(BoardSnapshotGameMismatch, match="不一致"):
        ensure_board_snapshot_matches_current_game(
            config,
            expected_game_uid="2107:new",
            round_no=2,
            ocr_round=2,
        )


def test_rejects_stale_snapshot_round_ahead_of_ocr(tmp_path: Path) -> None:
    snap_path = tmp_path / "board_snapshot.json"
    _write_snapshot(snap_path, game_uid="2107:g1", current_round=5)
    config = {
        "board_snapshot": {"enabled": True, "path": str(snap_path), "schema_version_min": 1},
    }
    with pytest.raises(BoardSnapshotGameMismatch, match="上一局残留"):
        ensure_board_snapshot_matches_current_game(
            config,
            expected_game_uid="2107:g1",
            round_no=5,
            ocr_round=1,
        )


def test_rejects_stale_snapshot_file_mtime(tmp_path: Path) -> None:
    snap_path = tmp_path / "board_snapshot.json"
    _write_snapshot(snap_path, game_uid="2107:g1", current_round=2)
    old = time.time() - 300.0
    os.utime(snap_path, (old, old))
    config = {
        "board_snapshot": {
            "enabled": True,
            "path": str(snap_path),
            "schema_version_min": 1,
            "max_stale_seconds": 120,
        },
    }
    with pytest.raises(BoardSnapshotGameMismatch, match="未更新"):
        ensure_board_snapshot_matches_current_game(
            config,
            expected_game_uid="2107:g1",
            round_no=2,
            ocr_round=2,
        )


def test_stop_bot_on_game_mismatch_config() -> None:
    assert board_snapshot_stop_bot_on_game_mismatch({}) is True
    assert board_snapshot_stop_bot_on_game_mismatch({"board_snapshot": {}}) is True
    assert (
        board_snapshot_stop_bot_on_game_mismatch(
            {"board_snapshot": {"stop_bot_on_game_mismatch": False}}
        )
        is False
    )
    assert (
        board_snapshot_stop_bot_on_game_mismatch(
            {"board_snapshot": {"stop_bot_on_game_mismatch": "off"}}
        )
        is False
    )


def test_skips_when_board_snapshot_disabled() -> None:
    snap, uid = ensure_board_snapshot_matches_current_game(
        {"board_snapshot": {"enabled": False}},
        expected_game_uid="2107:g1",
        round_no=1,
    )
    assert snap is None
    assert uid == "2107:g1"
