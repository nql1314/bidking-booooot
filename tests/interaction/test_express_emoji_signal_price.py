# -*- coding: utf-8 -*-
"""快递站表情暗号价：第 1 席 OCR 判席与对手相同表情检测。"""

from unittest.mock import MagicMock, patch

from bidking.interaction._legacy_bot import (
    _ocr_identity_matches_self,
    _opponent_matched_emoji_signal,
    _player_seat_index_from_slot1_ocr,
    try_resolve_express_emoji_signal_price,
    wait_after_express_station_round1_emoji,
)


def _base_config(*, emoji: str = "问候") -> dict:
    return {
        "board_snapshot": {"enabled": True, "self_user_uid": "uid_a"},
        "window": {"reference_client_size": {"width": 1920, "height": 1080}},
        "capture": {
            "seat_1_identity": {
                "character_name": {"left": 1, "top": 1, "width": 10, "height": 10},
                "character_titles": {"left": 2, "top": 2, "width": 10, "height": 10},
            }
        },
        "advisor": {"role": "ahmad"},
        "automation": {
            "selected_map": "210",
            "express_station_round1_emoji": {
                "enabled": True,
                "emoji": emoji,
                "character_name": "艾哈迈德",
                "character_title": "狂热博士",
                "seat_1_price": 250,
                "seat_2_price": 886,
            },
        },
    }


def _express_snapshot(
    *,
    players_order: list[str],
    self_uid: str,
    opp_emoji_cid: int | None = None,
) -> dict:
    players = {
        uid: {"name": uid, "hero_cid": 103, "prices": {}, "items_used": {}}
        for uid in players_order
    }
    emoji_events = []
    if opp_emoji_cid is not None and opp_emoji_cid > 0:
        opp = next(u for u in players_order if u != self_uid)
        emoji_events.append(
            {
                "game_uid": "2107:x",
                "user_uid": opp,
                "emoji_cid": int(opp_emoji_cid),
                "round": 1,
            }
        )
    return {
        "map_id": 2107,
        "current_round": 1,
        "game_state": {
            "uid": "2107:x",
            "map_id": 2107,
            "current_round": 1,
            "players": players,
            "emoji_events": emoji_events,
        },
        "self_user_uid": self_uid,
        "pricing": {"total": 999999},
    }


def test_ocr_identity_matches_self_requires_name_and_title() -> None:
    assert _ocr_identity_matches_self(
        "艾哈迈德",
        "狂热博士",
        my_character_name="艾哈迈德",
        my_character_title="狂热博士",
    )
    assert not _ocr_identity_matches_self(
        "对手名",
        "狂热博士",
        my_character_name="艾哈迈德",
        my_character_title="狂热博士",
    )


def test_player_seat_index_slot1_match_is_seat_1() -> None:
    cfg = _base_config()
    frame = MagicMock()
    frame.width = 1920
    frame.height = 1080
    frame.crop.return_value = MagicMock()
    with patch(
        "bidking.interaction._legacy_bot._ocr_region_text_from_frame",
        side_effect=["艾哈迈德", "狂热博士"],
    ):
        assert _player_seat_index_from_slot1_ocr(cfg, frame=frame) == 1


def test_player_seat_index_slot1_no_match_is_seat_2() -> None:
    cfg = _base_config()
    frame = MagicMock()
    frame.width = 1920
    frame.height = 1080
    with patch(
        "bidking.interaction._legacy_bot._ocr_region_text_from_frame",
        side_effect=["对手", "别的称号"],
    ):
        assert _player_seat_index_from_slot1_ocr(cfg, frame=frame) == 2


def test_opponent_same_emoji_matches() -> None:
    cfg = _base_config(emoji="问候")
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=101
    )
    assert _opponent_matched_emoji_signal(snap, cfg, expected_emoji_cid=101) is True


def test_opponent_different_emoji_not_matched() -> None:
    cfg = _base_config(emoji="问候")
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=103
    )
    assert _opponent_matched_emoji_signal(snap, cfg, expected_emoji_cid=101) is False


def test_signal_price_seat_2_without_backend_pricing(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_b", "uid_a"], self_uid="uid_a", opp_emoji_cid=101
    )
    cfg = _base_config(emoji="问候")

    def _fail_compute(*_a, **_k):
        raise AssertionError("不应调用 pricing.compute_price")

    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._player_seat_index_from_slot1_ocr",
        lambda _cfg, frame=None, board_snapshot=None: 2,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot.pricing_compute_price",
        _fail_compute,
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=1)
    assert price is not None
    assert price == 886
    assert details.get("pricing_strategy") == "express_emoji_seat_signal"
    assert details["express_emoji_signal"]["seat"] == 2
    assert details["express_emoji_signal"]["self_emoji_cid"] == 101


def test_signal_price_skipped_when_emoji_mismatch(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=105
    )
    cfg = _base_config(emoji="问候")
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    assert try_resolve_express_emoji_signal_price(cfg, snap, round_no=1) is None


def test_wait_returns_early_when_opponent_same_emoji() -> None:
    snap_no_opp = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a"
    )
    snap_with_opp = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=101
    )
    cfg = _base_config()
    cfg["automation"]["express_station_round1_emoji"]["wait_after_send_seconds"] = 5.0
    calls = {"n": 0}

    def fake_load(_cfg):
        calls["n"] += 1
        return snap_with_opp if calls["n"] >= 2 else snap_no_opp

    with patch(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda c, _bs=None: c.get("automation") or {},
    ), patch(
        "bidking.interaction._legacy_bot.load_board_snapshot_for_loop",
        fake_load,
    ), patch(
        "bidking.interaction._legacy_bot.sleep_interruptible",
        lambda _s: None,
    ):
        out = wait_after_express_station_round1_emoji(cfg, snap_no_opp)
    assert out is not None
    assert _opponent_matched_emoji_signal(out, cfg, expected_emoji_cid=101)
