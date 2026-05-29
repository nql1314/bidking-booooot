# -*- coding: utf-8 -*-
"""艾莎第 4 回合道具空置门控。"""

from __future__ import annotations

from bidking.analysis.grid_overlay_infer_vacant_rects import (
    auto_vacant_rect_phantom_cell_count_from_snapshot,
)
from bidking.interaction._legacy_bot import should_skip_tool_for_aisha_vacant_gate


def _base_config(*, min_vacant: int = 35) -> dict:
    return {
        "board_snapshot": {"self_user_uid": "self"},
        "automation": {
            "enable_aisha_round4_tool_vacant_gate": True,
            "aisha_round4_tool_min_vacant": min_vacant,
            "tool_rounds": [4],
        },
    }


def _aisha_round4_snapshot(
    *,
    vacant: int,
    auto_phantom_wh: list[tuple[int, int]] | None = None,
) -> dict:
    manual_shapes: dict[str, list[int]] = {}
    phantom_items: dict[str, dict] = {}
    for i, (w, h) in enumerate(auto_phantom_wh or []):
        uid = f"phantom_vac_{i}"
        phantom_items[uid] = {"quality": None}
        manual_shapes[uid] = [w, h, 0, 0]
    return {
        "current_round": 4,
        "pricing": {"vacant": vacant},
        "raw_pricing": {"event_stats": {}},
        "grid_overlay": {
            "phantom_items": phantom_items,
            "manual_shapes": manual_shapes,
        },
        "game_state": {
            "map_id": 240,
            "players": {"self": {"hero_cid": 103}},
        },
    }


def test_auto_phantom_cell_count_from_snapshot() -> None:
    snap = _aisha_round4_snapshot(vacant=10, auto_phantom_wh=[(3, 4), (2, 2)])
    assert auto_vacant_rect_phantom_cell_count_from_snapshot(snap) == 16


def test_gate_uses_vacant_plus_auto_phantom() -> None:
    snap = _aisha_round4_snapshot(vacant=20, auto_phantom_wh=[(3, 5)])
    skip, reason = should_skip_tool_for_aisha_vacant_gate(
        config=_base_config(min_vacant=35),
        round_no=4,
        tool_rounds={4},
        board_snapshot=snap,
    )
    assert skip is False
    assert reason == ""


def test_gate_skips_when_vacant_plus_auto_phantom_below_threshold() -> None:
    snap = _aisha_round4_snapshot(vacant=20, auto_phantom_wh=[(3, 4)])
    skip, reason = should_skip_tool_for_aisha_vacant_gate(
        config=_base_config(min_vacant=35),
        round_no=4,
        tool_rounds={4},
        board_snapshot=snap,
    )
    assert skip is True
    assert "vacant=20+auto_phantom=12=32" in reason
    assert "< 35" in reason


def test_gate_ignores_manual_phantom_in_auto_count() -> None:
    snap = _aisha_round4_snapshot(vacant=30, auto_phantom_wh=[(2, 2)])
    snap["grid_overlay"]["phantom_items"]["phantom_manual"] = {"quality": None}
    snap["grid_overlay"]["manual_shapes"]["phantom_manual"] = [5, 5, 0, 0]
    skip, _ = should_skip_tool_for_aisha_vacant_gate(
        config=_base_config(min_vacant=35),
        round_no=4,
        tool_rounds={4},
        board_snapshot=snap,
    )
    assert skip is True
