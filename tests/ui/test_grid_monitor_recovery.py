# -*- coding: utf-8 -*-
"""画板 log tail：漏 S2C_33 时按事件 Uid 恢复新局。"""

from __future__ import annotations

from bidking.ui.grid._grid_view import (
    event_game_uid_from_network_data,
    should_recover_missed_new_game,
)


def test_event_game_uid_from_root_and_game_data() -> None:
    assert event_game_uid_from_network_data({"GameUid": "2107:g1"}) == "2107:g1"
    assert (
        event_game_uid_from_network_data(
            {"GameData": {"Uid": "2107:g2", "Round": 1}}
        )
        == "2107:g2"
    )
    assert event_game_uid_from_network_data({}) == ""


def test_should_recover_after_game_over_on_new_uid() -> None:
    assert should_recover_missed_new_game(
        live_active=False,
        state_uid="2107:old",
        event_uid="2107:new",
    )
    assert not should_recover_missed_new_game(
        live_active=False,
        state_uid="2107:old",
        event_uid="2107:old",
    )


def test_should_recover_mid_game_uid_switch() -> None:
    assert should_recover_missed_new_game(
        live_active=True,
        state_uid="2107:old",
        event_uid="2107:new",
    )
    assert not should_recover_missed_new_game(
        live_active=True,
        state_uid="2107:same",
        event_uid="2107:same",
    )


def test_should_not_recover_without_event_uid() -> None:
    assert not should_recover_missed_new_game(
        live_active=False,
        state_uid="2107:old",
        event_uid="",
    )
