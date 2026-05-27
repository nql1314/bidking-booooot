# -*- coding: utf-8 -*-
"""快递站表情暗号黑名单（CSV）。"""

from pathlib import Path

import pytest

from bidking.interaction import emoji_signal_blacklist as bl


def _snap(
    *,
    players: dict,
    self_uid: str = "uid_a",
    game_uid: str = "2107:g1",
) -> dict:
    return {
        "game_uid": game_uid,
        "game_state": {"uid": game_uid, "players": players},
        "self_user_uid": self_uid,
    }


def _cfg() -> dict:
    return {"board_snapshot": {"self_user_uid": "uid_a"}}


@pytest.fixture
def blacklist_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pub = tmp_path / "emoji_signal_public_blacklist.csv"
    match = tmp_path / "emoji_signal_match_blacklist.csv"
    pub.write_text("uid,name\nbad_uid,坏人\n", encoding="utf-8-sig")
    match.write_text("game_uid,uid,name,round,bid\n", encoding="utf-8-sig")
    monkeypatch.setattr(bl, "_public_path", lambda: pub)
    monkeypatch.setattr(bl, "_match_path", lambda: match)
    return tmp_path


def test_public_blacklist_blocks_by_uid(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "bad_uid": {"name": "坏人", "prices": {"0": 50}},
        }
    )
    blocked, reason = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap)
    assert blocked is True
    assert reason == "public"


def test_self_on_public_blacklist(blacklist_files: Path) -> None:
    pub = blacklist_files / "emoji_signal_public_blacklist.csv"
    pub.write_text("uid,name\nuid_a,我\n", encoding="utf-8-sig")
    snap = _snap(players={"uid_a": {"name": "我"}, "uid_b": {"name": "对手"}})
    assert bl.is_self_on_public_blacklist(_cfg(), snap) is True


def test_public_blacklist_blocks_by_name(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_x": {"name": "坏人", "prices": {"0": 50}},
        }
    )
    blocked, reason = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap)
    assert blocked is True
    assert reason == "public"


def test_steal_express_appends_bid_row(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 1500}},
        }
    )
    assert bl.record_steal_express_on_match_blacklist(_cfg(), snap) is True
    blocked, reason = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap)
    assert blocked is True
    assert reason == "match"
    bids = bl.load_match_blacklist_bids("2107:g1", uid="uid_b")
    assert len(bids) == 1
    assert bids[0]["round"] == 1
    assert bids[0]["bid"] == 1500
    entry = bl.match_blacklist_opponent_entry(game_uid="2107:g1", uid="uid_b")
    assert entry is not None
    assert entry["abnormal_signal_bid_count"] == 1
    assert bl.record_steal_express_on_match_blacklist(_cfg(), snap) is False
    assert len(bl.load_match_blacklist_bids("2107:g1", uid="uid_b")) == 1


def test_multiple_bid_rows_per_opponent(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 1500, "1": 2200}},
        }
    )
    bl.maybe_update_steal_express_blacklist(_cfg(), snap)
    bids = bl.load_match_blacklist_bids("2107:g1", uid="uid_b")
    assert len(bids) == 2
    assert {b["round"]: b["bid"] for b in bids} == {1: 1500, 2: 2200}


def test_steal_express_ignores_bid_at_most_1000(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "正常", "prices": {"0": 1000}},
        }
    )
    assert bl.record_steal_express_on_match_blacklist(_cfg(), snap) is False
    blocked, _ = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap)
    assert blocked is False


def test_player_express_blacklist_reason_public_and_match(
    blacklist_files: Path,
) -> None:
    snap_public = _snap(
        players={
            "uid_a": {"name": "我"},
            "bad_uid": {"name": "坏人"},
        }
    )
    assert bl.player_express_blacklist_reason(
        uid="bad_uid", name="坏人", game_uid="2107:g1"
    ) == "public"
    snap_match = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 1500}},
        }
    )
    bl.record_steal_express_on_match_blacklist(_cfg(), snap_match)
    assert bl.player_express_blacklist_reason(
        uid="uid_b", name="偷子", game_uid="2107:g1"
    ) == "match"
    assert bl.player_express_blacklist_reason(
        uid="uid_x", name="路人", game_uid="2107:g1"
    ) == ""


def test_remove_player_from_match_blacklist(blacklist_files: Path) -> None:
    bl.append_match_blacklist_bid(
        game_uid="2107:g9", uid="uid_z", name="手动", round_no=1, bid=1500
    )
    bl.append_match_blacklist_bid(
        game_uid="2107:g9", uid="uid_z", name="手动", round_no=2, bid=1600
    )
    removed, note = bl.remove_player_from_match_blacklist(
        game_uid="2107:g9", uid="uid_z", name="手动"
    )
    assert removed is True
    assert "移出" in note
    assert bl.load_match_blacklist_bids("2107:g9", uid="uid_z") == []
    again, note2 = bl.remove_player_from_match_blacklist(
        game_uid="2107:g9", uid="uid_z", name="手动"
    )
    assert again is False
    assert "未在" in note2


def test_add_player_to_match_blacklist_manual(blacklist_files: Path) -> None:
    added, note = bl.add_player_to_match_blacklist(
        game_uid="2107:g9",
        uid="uid_z",
        name="手动",
        round_no=1,
        bid=None,
    )
    assert added is True
    assert "已加入" in note
    again, note2 = bl.add_player_to_match_blacklist(
        game_uid="2107:g9",
        uid="uid_z",
        name="手动",
        round_no=1,
    )
    assert again is False
    assert "已在" in note2


def test_opponent_express_blacklist_banner_public(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "bad_uid": {"name": "坏人", "prices": {"0": 50}},
        }
    )
    banner = bl.opponent_express_blacklist_banner(_cfg(), snap)
    assert banner == ("坏人", "公共")


def test_opponent_express_blacklist_banner_match(blacklist_files: Path) -> None:
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 1500}},
        }
    )
    bl.record_steal_express_on_match_blacklist(_cfg(), snap)
    banner = bl.opponent_express_blacklist_banner(_cfg(), snap)
    assert banner == ("偷子", "对局")


def test_steal_express_skipped_when_self_on_public_blacklist(
    blacklist_files: Path,
) -> None:
    pub = blacklist_files / "emoji_signal_public_blacklist.csv"
    pub.write_text("uid,name\nuid_a,我\n", encoding="utf-8-sig")
    snap = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 1500}},
        }
    )
    bl.maybe_update_steal_express_blacklist(_cfg(), snap)
    assert bl.load_match_blacklist_bids("2107:g1", uid="uid_b") == []


def test_match_blacklist_kept_across_different_game_uid(blacklist_files: Path) -> None:
    snap_g1 = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_b": {"name": "偷子", "prices": {"0": 2000}},
        },
        game_uid="2107:g1",
    )
    bl.record_steal_express_on_match_blacklist(_cfg(), snap_g1)
    snap_g2 = _snap(
        players={
            "uid_a": {"name": "我"},
            "uid_c": {"name": "另一人", "prices": {"0": 3000}},
        },
        game_uid="2107:g2",
    )
    bl.record_steal_express_on_match_blacklist(_cfg(), snap_g2)
    assert len(bl.load_match_blacklist_bids("2107:g1", uid="uid_b")) == 1
    assert len(bl.load_match_blacklist_bids("2107:g2", uid="uid_c")) == 1
    blocked_g1, _ = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap_g1)
    assert blocked_g1 is True
    snap_g2_only_opp = _snap(
        players={"uid_a": {"name": "我"}, "uid_d": {"name": "新人"}},
        game_uid="2107:g2",
    )
    blocked, _ = bl.opponent_blocks_express_emoji_signal_price(_cfg(), snap_g2_only_opp)
    assert blocked is False
