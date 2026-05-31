# -*- coding: utf-8 -*-
"""C2S_34 用户出价解析与 skill_logs 条目。"""

import io

from bidking.parsing.handlers import handle_c2s34, parse_game_bid
from bidking.parsing.log_source import extract_event, game_bid_log_entry
from bidking.parsing.state import GameState


_SAMPLE_LINE = (
    '[Network] Send C2S34GameBid : (C2S_34_game_bid){ '
    '"Token": "1246296431397667", '
    '"GameUid": "4407:1295018589673368", '
    '"BidPrice": 408888 }'
)


def test_extract_event_parses_c2s34() -> None:
    got = extract_event(_SAMPLE_LINE)
    assert got is not None
    event_type, data = got
    assert event_type == "C2S_34_game_bid"
    assert data["GameUid"] == "4407:1295018589673368"
    assert data["BidPrice"] == 408888
    assert data["Token"] == "1246296431397667"


def test_parse_game_bid_records_on_state() -> None:
    st = GameState()
    st.uid = "4407:1295018589673368"
    st.current_round = 3
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    ev = parse_game_bid(data, st)
    assert ev.bid_price == 408888
    assert ev.game_uid == "4407:1295018589673368"
    assert len(st.self_bid_events) == 1
    row = st.self_bid_events[0]
    assert row["bid_price"] == 408888
    assert row["round"] == 3


def test_handle_c2s34_prints_bid_line() -> None:
    st = GameState()
    st.uid = "4407:1295018589673368"
    st.current_round = 2
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    buf = io.StringIO()
    handle_c2s34(data, st, {}, [], buf)
    text = buf.getvalue()
    assert "[用户出价]" in text
    assert "408,888" in text
    assert "第2回合" in text


def test_game_bid_log_entry_shape() -> None:
    _, data = extract_event(_SAMPLE_LINE)  # type: ignore[misc]
    entry = game_bid_log_entry(
        "C2S_34_game_bid",
        data,
        round_no=4,
        received_at_unix=1.0,
    )
    assert entry["event_type"] == "C2S_34_game_bid"
    assert entry["received_at_unix"] == 1.0
    assert entry["user_bid"]["BidPrice"] == 408888
    assert entry["user_bid"]["Round"] == 4
    assert "game_data" not in entry
