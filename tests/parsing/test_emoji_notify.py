# -*- coding: utf-8 -*-
"""S2C_265 表情信号解析与 skill_logs 条目。"""

import io

from bidking.parsing.handlers import handle_s2c265, parse_game_use_emoji_notify
from bidking.parsing.log_source import emoji_signal_log_entry, extract_event
from bidking.parsing.state import GameState


_SAMPLE_LINE = (
    '[Network] OnHanderNotify S2C265GameUseEmojiNotify : '
    '(S2C_265_game_use_emoji_notify){ "GameUid": "2107:1178745704676264", '
    '"UserUid": "358372071974712", "EmojiCid": 105 }'
)


def test_extract_event_parses_s2c265() -> None:
    got = extract_event(_SAMPLE_LINE)
    assert got is not None
    event_type, data = got
    assert event_type == "S2C_265_game_use_emoji_notify"
    assert data["GameUid"] == "2107:1178745704676264"
    assert data["UserUid"] == "358372071974712"
    assert data["EmojiCid"] == 105


def test_parse_game_use_emoji_records_on_state() -> None:
    st = GameState()
    st.current_round = 2
    st.players["358372071974712"] = {
        "name": "测试玩家",
        "hero_cid": 103,
        "prices": {},
        "items_used": {},
    }
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    ev = parse_game_use_emoji_notify(data, st)
    assert ev.emoji_cid == 105
    assert ev.player_name == "测试玩家"
    assert len(st.emoji_events) == 1
    row = st.emoji_events[0]
    assert row["emoji_cid"] == 105
    assert row["round"] == 2
    assert row["user_uid"] == "358372071974712"


def test_handle_s2c265_prints_signal_line() -> None:
    st = GameState()
    st.current_round = 1
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    buf = io.StringIO()
    handle_s2c265(data, st, {}, [], buf)
    text = buf.getvalue()
    assert "[表情信号]" in text
    assert "遗憾" in text
    assert "EmojiCid=105" in text


def test_emoji_signal_log_entry_shape() -> None:
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    entry = emoji_signal_log_entry("S2C_265_game_use_emoji_notify", data, received_at_unix=1.0)
    assert entry["event_type"] == "S2C_265_game_use_emoji_notify"
    assert entry["received_at_unix"] == 1.0
    assert entry["emoji_signal"]["EmojiCid"] == 105
    assert "game_data" not in entry
