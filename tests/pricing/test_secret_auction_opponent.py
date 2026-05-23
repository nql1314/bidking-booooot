# -*- coding: utf-8 -*-
from __future__ import annotations

from bidking.pricing.opponent_adjust import (
    apply_opponent_bid_adjustment,
    apply_secret_auction_rank_opponent_adjustment,
    board_map_bundle_key,
    board_snapshot_is_secret_auction,
    opponent_bid_adjustment_enabled,
    resolve_secret_auction_rank_opponent_multipliers,
)
from bidking.pricing.self_bid_cache import SELF_BID_HISTORY_SNAPSHOT_KEY


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
    return {"board_snapshot": {"self_user_uid": self_uid}}


def test_secret_rank_multipliers_configurable() -> None:
    cfg = {
        **_minimal_config("941456831344888"),
        "pricing": {
            "secret_auction_rank_opponent_multipliers": {
                "2": 1.25,
                "default": 1.5,
            }
        },
    }
    resolved = resolve_secret_auction_rank_opponent_multipliers(cfg, {})
    assert resolved["by_rank"][2] == 1.25
    assert resolved["fallback"] == 1.5
    snap = {
        "game_state": {
            "map_id": 4402,
            "players": {
                "941456831344888": {"name": "self", "prices": {"0": 2, "1": 2}},
                "111": {"name": "a", "prices": {"0": 3, "1": 1}},
            },
        },
        SELF_BID_HISTORY_SNAPSHOT_KEY: {"2": 400_000},
    }
    _out, _tag, detail = apply_secret_auction_rank_opponent_adjustment(
        cfg, 100_000, 3, board_snapshot=snap, price_config={}
    )
    assert detail.get("o_estimated_raw") == 400_000 * 1.25


def test_secret_opponent_skips_without_cached_bid_pre() -> None:
    """无 ``self_bid_history`` 时不应把 prices 名次误当金币出价。"""
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
        cfg, 100_000, 3, board_snapshot=snap, price_config={}
    )
    assert tag is None
    assert out == 100_000
    assert detail.get("skip") == "no_self_bid_prev"


def test_secret_opponent_uses_ordinal_rank_for_multiplier() -> None:
    cfg = _minimal_config("941456831344888")
    snap = {
        "game_state": {
            "map_id": 4402,
            "players": {
                "941456831344888": {"name": "self", "prices": {"0": 2, "1": 2}},
                "111": {"name": "a", "prices": {"0": 3, "1": 1}},
            },
        },
        SELF_BID_HISTORY_SNAPSHOT_KEY: {"2": 400_000},
    }
    out, tag, detail = apply_secret_auction_rank_opponent_adjustment(
        cfg, 100_000, 3, board_snapshot=snap, price_config={}
    )
    assert detail.get("my_rank_ordinal") == 2
    assert detail.get("bid_pre") == 400_000
    assert detail.get("o_estimated_raw") == 400_000 * 1.1
    assert tag is not None
    assert out == int(round((100_000 + 400_000 * 1.1) / 2))


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
        "board_snapshot": {"self_user_uid": "1"},
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
        },
        SELF_BID_HISTORY_SNAPSHOT_KEY: {"2": 300_000},
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
    assert ob["tag"] is not None
    assert ob["detail"]["bid_pre"] == 300_000
    assert fin != before
