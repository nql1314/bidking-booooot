# -*- coding: utf-8 -*-
from __future__ import annotations

from bidking.pricing.opponent_adjust import (
    apply_opponent_bid_adjustment,
    apply_secret_auction_rank_opponent_adjustment,
    board_map_bundle_key,
    board_snapshot_is_secret_auction,
    opponent_bid_adjustment_enabled,
)


def test_board_map_bundle_key_4402_is_440() -> None:
    snap = {"game_state": {"map_id": 4402, "players": {}}}
    assert board_map_bundle_key(snap) == "440"
    assert board_snapshot_is_secret_auction(snap) is True


def test_board_map_bundle_key_4503_is_450() -> None:
    snap = {"game_state": {"map_id": 4503, "players": {}}}
    assert board_map_bundle_key(snap) == "450"
    assert board_snapshot_is_secret_auction(snap) is True


def test_board_map_bundle_key_2306_not_secret() -> None:
    snap = {"game_state": {"map_id": 2306, "players": {}}}
    assert board_map_bundle_key(snap) == "230"
    assert board_snapshot_is_secret_auction(snap) is False


def _minimal_config(self_uid: str) -> dict:
    return {"board_snapshot": {"self_user_uid": self_uid, "self_name_substring": ""}}


def test_secret_rank_behind_1_scales_bid() -> None:
    """上一轮名次：我方 2、最优对手 1 → behind_by=1 → 约 +4.5%。"""
    cfg = _minimal_config("941456831344888")
    snap = {
        "game_state": {
            "map_id": 4402,
            "players": {
                "941456831344888": {"name": "self", "prices": {"0": 2, "1": 2}},
                "111": {"name": "a", "prices": {"0": 3, "1": 1}},
            },
        }
    }
    out, tag, detail = apply_secret_auction_rank_opponent_adjustment(
        cfg, 100_000, 3, board_snapshot=snap, pricing={}
    )
    assert detail.get("behind_by") == 1
    assert tag == "secret_rank_behind_1"
    assert out == int(round(100_000 * 1.045))


def test_opponent_bid_adjustment_disabled_skips_all() -> None:
    cfg = _minimal_config("941456831344888")
    snap = {
        "game_state": {
            "map_id": 4402,
            "players": {
                "941456831344888": {"name": "AIR", "prices": {"1": 1}},
                "882289365978943": {"name": "opp", "prices": {"1": 3}},
            },
        }
    }
    fin, ob, before = apply_opponent_bid_adjustment(
        cfg,
        200_000,
        3,
        {"enable_opponent_bid_adjustment": False},
        role="aisha",
        board_snapshot=snap,
        pricing={},
    )
    assert fin == before == 200_000
    assert ob["applied"] is False
    assert ob.get("disabled") is True
    assert ob["detail"].get("reason") == "enable_opponent_bid_adjustment_false"


def test_opponent_bid_adjustment_enabled_from_config_pricing() -> None:
    cfg = {
        "board_snapshot": {"self_user_uid": "1", "self_name_substring": ""},
        "pricing": {"enable_opponent_bid_adjustment": False},
    }
    assert opponent_bid_adjustment_enabled(cfg, {}) is False
    assert opponent_bid_adjustment_enabled(cfg, {"enable_opponent_bid_adjustment": True}) is True


def test_apply_opponent_bid_adjustment_secret_branch() -> None:
    cfg = _minimal_config("941456831344888")
    snap = {
        "game_state": {
            "map_id": 4402,
            "players": {
                "941456831344888": {"name": "AIR", "prices": {"0": 2, "1": 1}},
                "882289365978943": {"name": "opp", "prices": {"0": 3, "1": 3}},
            },
        }
    }
    fin, ob, before = apply_opponent_bid_adjustment(
        cfg,
        200_000,
        3,
        {},
        role="aisha",
        board_snapshot=snap,
        pricing={"points_ceiling": 500_000},
    )
    assert before == 200_000
    assert ob["o_prev"] is None
    assert ob["applied"] is True
    assert ob["tag"] == "secret_rank_ahead"
    assert fin == int(round(200_000 * 0.994))
