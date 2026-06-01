# -*- coding: utf-8 -*-
"""出价完成：快照 C2S_34_game_bid 检测。"""

from bidking.interaction._legacy_bot import (
    _c2s34_bid_match_keys,
    _snapshot_has_game_over_notify,
    _snapshot_has_new_c2s34_for_round,
    _snapshot_round_advanced_past,
)


def _snap(*, skill_logs=None, current_round=2, self_bid_events=None):
    gs = {"current_round": current_round, "self_bid_events": self_bid_events or []}
    return {
        "current_round": current_round,
        "game_state": gs,
        "skill_logs": list(skill_logs or []),
    }


def test_detects_new_c2s34_in_skill_logs() -> None:
    prior = _c2s34_bid_match_keys(_snap(current_round=1))
    snap = _snap(
        current_round=2,
        skill_logs=[
            {
                "event_type": "C2S_34_game_bid",
                "user_bid": {
                    "GameUid": "g1",
                    "BidPrice": 100,
                    "Round": 2,
                    "Token": "t",
                },
            }
        ],
    )
    assert _snapshot_has_new_c2s34_for_round(snap, 2, prior)
    assert not _snapshot_round_advanced_past(snap, 2)


def test_ignores_prior_round_bids() -> None:
    snap = _snap(
        current_round=2,
        skill_logs=[
            {
                "event_type": "C2S_34_game_bid",
                "user_bid": {"GameUid": "g1", "BidPrice": 50, "Round": 1},
            }
        ],
    )
    prior = frozenset()
    assert not _snapshot_has_new_c2s34_for_round(snap, 2, prior)


def test_next_round_without_new_bid() -> None:
    snap = _snap(current_round=3)
    assert _snapshot_round_advanced_past(snap, 2)


def test_self_bid_events_in_game_state() -> None:
    prior = frozenset()
    snap = _snap(
        current_round=1,
        self_bid_events=[{"game_uid": "g1", "bid_price": 888, "round": 1}],
    )
    assert _snapshot_has_new_c2s34_for_round(snap, 1, prior)


def test_game_over_in_skill_logs() -> None:
    snap = _snap(
        current_round=5,
        skill_logs=[{"event_type": "S2C_45_game_over_notify", "game_data": {}}],
    )
    assert _snapshot_has_game_over_notify(snap)
    assert not _snapshot_has_game_over_notify(_snap(current_round=5))
