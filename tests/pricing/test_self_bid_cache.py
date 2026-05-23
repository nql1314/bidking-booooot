# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from bidking.pricing.opponent_adjust import apply_secret_auction_rank_opponent_adjustment
from bidking.pricing.self_bid_cache import (
    SELF_BID_HISTORY_SNAPSHOT_KEY,
    get_self_gold_bid,
    record_self_gold_bid,
)


def _minimal_config(self_uid: str) -> dict:
    return {"board_snapshot": {"self_user_uid": self_uid}}


def test_get_self_gold_bid_from_snapshot_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "bidking.pricing.self_bid_cache._cache_file_path",
        lambda: tmp_path / "cache.json",
    )
    cfg = _minimal_config("u1")
    snap = {
        "game_uid": "g1",
        "game_state": {"map_id": 4501, "players": {}},
        SELF_BID_HISTORY_SNAPSHOT_KEY: {"2": 799_333},
    }
    assert get_self_gold_bid(cfg, snap, 2) == 799_333
    assert get_self_gold_bid(cfg, snap, 1) is None


def test_record_self_gold_bid_persists(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(
        "bidking.pricing.self_bid_cache._cache_file_path",
        lambda: cache_path,
    )
    cfg = _minimal_config("u1")
    snap = {"game_uid": "g1", "game_state": {"map_id": 4501, "players": {}}}
    record_self_gold_bid(cfg, round_no=2, bid_amount=846_666, board_snapshot=snap, game_uid="g1")
    assert snap[SELF_BID_HISTORY_SNAPSHOT_KEY]["2"] == 846_666
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["games"]["g1"]["by_round"]["2"] == 846_666


def test_secret_opponent_uses_cached_bid_pre_not_rank_signal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "bidking.pricing.self_bid_cache._cache_file_path",
        lambda: tmp_path / "cache.json",
    )
    cfg = _minimal_config("941456831344888")
    snap = {
        "game_uid": "g1",
        "game_state": {
            "map_id": 4501,
            "players": {
                "941456831344888": {"name": "self", "prices": {"0": 2, "1": 3}},
                "111": {"name": "a", "prices": {"0": 3, "1": 1}},
            },
        },
        SELF_BID_HISTORY_SNAPSHOT_KEY: {"2": 500_000},
    }
    out, tag, detail = apply_secret_auction_rank_opponent_adjustment(
        cfg, 800_000, 3, board_snapshot=snap, price_config={}
    )
    assert detail.get("bid_pre") == 500_000
    assert detail.get("my_rank_ordinal") == 2
    assert detail.get("o_estimated_raw") == 500_000 * 1.1
    assert tag in ("secret_opp_sticky", "secret_opp_low", "secret_opp_est")
    assert out > 0
