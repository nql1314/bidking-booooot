# -*- coding: utf-8 -*-
"""快递站表情暗号价：随机座次与对手相同表情检测。"""

from unittest.mock import patch

from bidking.interaction._legacy_bot import (
    _express_random_seat_for_signal,
    _opponent_matched_emoji_signal,
    try_resolve_express_emoji_signal_price,
    wait_after_express_station_round1_emoji,
)


def _base_config(*, emoji: str = "问候") -> dict:
    return {
        "board_snapshot": {"enabled": True, "self_user_uid": "uid_a"},
        "window": {"reference_client_size": {"width": 1920, "height": 1080}},
        "advisor": {"role": "ahmad"},
        "automation": {
            "selected_map": "210",
            "express_station_round1_emoji": {
                "enabled": True,
                "emoji": emoji,
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
    current_round: int = 1,
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
        "current_round": current_round,
        "game_state": {
            "uid": "2107:x",
            "map_id": 2107,
            "current_round": current_round,
            "players": players,
            "emoji_events": emoji_events,
        },
        "self_user_uid": self_uid,
        "pricing": {"total": 999999},
    }


def test_express_random_seat_is_one_or_two() -> None:
    seen = {_express_random_seat_for_signal() for _ in range(40)}
    assert seen <= {1, 2}
    assert seen == {1, 2}


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
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (False, ""),
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_random_seat_for_signal",
        lambda: 2,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot.pricing_compute_price",
        _fail_compute,
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=1)
    assert price is not None
    assert price == 886
    assert details.get("pricing_strategy") == "express_emoji_seat_signal"
    sig = details["express_emoji_signal"]
    assert sig["seat"] == 2
    assert sig.get("seat_random_pick") is True
    assert sig["self_emoji_cid"] == 101


def test_signal_price_seat_1_when_random_picks_one(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=101
    )
    cfg = _base_config(emoji="问候")
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (False, ""),
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_random_seat_for_signal",
        lambda: 1,
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=1)
    assert price == 250
    assert details["express_emoji_signal"]["seat"] == 1


def test_signal_price_round2_after_seat1_bid_uses_1_to_seat2(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_b", "uid_a"],
        self_uid="uid_a",
        opp_emoji_cid=101,
        current_round=2,
    )
    cfg = _base_config(emoji="问候")
    rand_args: list[tuple[int, int]] = []

    def _fail_seat_pick(*_a, **_k):
        raise AssertionError("第2回合不应随机座次")

    def _capture_randint(a: int, b: int) -> int:
        rand_args.append((int(a), int(b)))
        return 77

    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (False, ""),
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_random_seat_for_signal",
        _fail_seat_pick,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_round1_signal_bid_for_followup",
        lambda _c, _s, _p: 250,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot.random.randint",
        _capture_randint,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot.pricing_compute_price",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("不应调用 pricing.compute_price")
        ),
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=2)
    assert price == 77
    assert rand_args == [(1, 886)]
    sig = details["express_emoji_signal"]
    assert sig["random_lo"] == 1
    assert sig["random_hi"] == 886
    assert sig["round1_signal_bid"] == 250


def test_signal_price_round2_after_seat2_bid_uses_seat1_to_888(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_b", "uid_a"],
        self_uid="uid_a",
        opp_emoji_cid=101,
        current_round=2,
    )
    cfg = _base_config(emoji="问候")
    cfg["automation"]["express_station_round1_emoji"]["round2_plus_high_random_max"] = 888
    rand_args: list[tuple[int, int]] = []

    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (False, ""),
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_round1_signal_bid_for_followup",
        lambda _c, _s, _p: 886,
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot.random.randint",
        lambda a, b: rand_args.append((int(a), int(b))) or 600,
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=2)
    assert price == 600
    assert rand_args == [(250, 888)]
    sig = details["express_emoji_signal"]
    assert sig["round1_signal_bid"] == 886


def test_signal_price_force_one_when_self_on_public_blacklist(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=101
    )
    cfg = _base_config(emoji="问候")
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.is_self_on_public_blacklist",
        lambda _c, _s: True,
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (False, ""),
    )
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._express_random_seat_for_signal",
        lambda: (_ for _ in ()).throw(AssertionError("公共黑名单不应随机座次")),
    )
    price, details = try_resolve_express_emoji_signal_price(cfg, snap, round_no=1)
    assert price == 1
    assert details.get("pricing_strategy") == "express_emoji_public_blacklist_force"
    assert details["express_emoji_signal"]["price_mode"] == "public_blacklist_force"


def test_signal_price_skipped_when_opponent_blacklisted(monkeypatch) -> None:
    snap = _express_snapshot(
        players_order=["uid_a", "uid_b"], self_uid="uid_a", opp_emoji_cid=101
    )
    cfg = _base_config(emoji="问候")
    monkeypatch.setattr(
        "bidking.interaction._legacy_bot._automation_with_map_overlay",
        lambda cfg, _bs=None: cfg.get("automation") or {},
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.opponent_blocks_express_emoji_signal_price",
        lambda _c, _s: (True, "public"),
    )
    monkeypatch.setattr(
        "bidking.interaction.emoji_signal_blacklist.maybe_update_steal_express_blacklist",
        lambda _c, _s: None,
    )
    assert try_resolve_express_emoji_signal_price(cfg, snap, round_no=1) is None


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
