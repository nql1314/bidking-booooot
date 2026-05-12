# -*- coding: utf-8 -*-

import csv
from pathlib import Path

import pytest

from bidking.parsing import game_report_csv as grc
from bidking.parsing.game_report_csv import (
    OVERBID_REBATE_PER_PLAYER_RATE,
    OVERBID_SURPLUS_THRESHOLD,
    append_game_over_report_csv,
)
from bidking.config.runtime import load_runtime
from bidking.parsing.state import CsvItem, GameState


def test_append_game_over_report_csv_userlog_and_stock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "rep.csv"
    monkeypatch.setenv("BIDKING_GAME_REPORT_CSV", str(csv_path))

    st = GameState()
    st.uid = "2306:testgame"

    data = {
        "WinUserUid": "u1",
        "GameData": {
            "Uid": "2306:testgame",
            "UserLog": [
                {
                    "UserUid": "u1",
                    "Name": "玩家甲",
                    "HeroCid": 103,
                    "PriceLog": [
                        {"Round": 0, "ItemCidOrPrice": 1000},
                        {"Round": 1, "ItemCidOrPrice": 2000},
                    ],
                    "Profit": 42,
                },
                {
                    "UserUid": "u2",
                    "Name": "玩家乙",
                    "HeroCid": 101,
                    "PriceLog": [{"Round": 0, "ItemCidOrPrice": 500}],
                },
            ],
            "StockContainer": {
                "StockBoxes": [
                    {
                        "UserUid": "u1",
                        "HitBoxList": [
                            {"ItemPrice": 100, "ItemUid": "1"},
                            {"ItemPrice": 200, "ItemUid": "2"},
                        ],
                    },
                    {
                        "UserUid": "u2",
                        "HitBoxList": [{"ItemPrice": 50, "ItemUid": "3"}],
                    },
                ]
            },
        },
    }

    append_game_over_report_csv(data, st, {})

    rows = list(csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == [
        "对局UID",
        "对局开始时间",
        "对局结束时间",
        "角色名称",
        "角色英雄",
        "每轮出价",
        "最终藏品价值",
        "最终收益",
    ]
    assert rows[1][0] == "2306:testgame"
    assert rows[1][1] == ""
    assert rows[1][2] == ""
    assert rows[1][3] == "玩家甲"
    assert "103" in rows[1][4]
    assert rows[1][5] == "R1:1000;R2:2000"
    assert rows[1][6] == "300"
    assert rows[1][7] == "42"

    assert rows[2][3] == "玩家乙"
    assert rows[2][6] == "0"
    assert rows[2][7] == "0"


def test_fallback_from_state_players(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "rep2.csv"
    monkeypatch.setenv("BIDKING_GAME_REPORT_CSV", str(csv_path))

    st = GameState()
    st.uid = "g2"
    st.players["p9"] = {
        "name": "solo",
        "hero_cid": 204,
        "prices": {0: 10, 1: 20},
        "items_used": {},
    }

    data = {
        "WinUserUid": "p9",
        "GameData": {
            "Uid": "g2",
            "MapId": 2301,
            "UserLog": [],
            "StockContainer": {
                "StockBoxes": [{"BoxId": 1, "Item": {"Cid": 9999001, "Count": 1}}]
            },
        },
    }
    csv_index = {
        9999001: CsvItem(
            item_id=9999001,
            name="t",
            category_tags=[],
            shape=11,
            quality=1,
            base_value=1000,
        )
    }

    append_game_over_report_csv(data, st, csv_index)

    text = csv_path.read_text(encoding="utf-8-sig")
    assert "solo" in text
    assert "R1:10;R2:20" in text
    assert "1000" in text
    rows = list(csv.reader(text.splitlines()))
    ticket = grc._map_entry_ticket(load_runtime().raw.get("automation") or {}, 2301)
    assert int(rows[1][7]) == 1000 - 20 - ticket


def test_overbid_rebate_per_player(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """差价=最后一轮出价−盘面价；差价>10000 时每人 (差价−10000)×10%。"""
    csv_path = tmp_path / "rebate.csv"
    monkeypatch.setenv("BIDKING_GAME_REPORT_CSV", str(csv_path))

    st = GameState()
    st.uid = "ov:1"
    cid = 8888001
    csv_index = {
        cid: CsvItem(
            item_id=cid,
            name="x",
            category_tags=[],
            shape=11,
            quality=1,
            base_value=100_000,
        )
    }
    data = {
        "WinUserUid": "w1",
        "GameData": {
            "Uid": "ov:1",
            "MapId": 2306,
            "UserLog": [
                {
                    "UserUid": "w1",
                    "Name": "胜者",
                    "HeroCid": 103,
                    "PriceLog": [
                        {"ItemCidOrPrice": 50_000},
                        {"Round": 1, "ItemCidOrPrice": 120_000},
                    ],
                },
                {
                    "UserUid": "l2",
                    "Name": "败者",
                    "HeroCid": 104,
                    "PriceLog": [{"ItemCidOrPrice": 500}],
                },
            ],
            "StockContainer": {
                "StockBoxes": [{"BoxId": 0, "Item": {"Cid": cid, "Count": 1}}]
            },
        },
    }

    append_game_over_report_csv(data, st, csv_index)

    price_diff = 120_000 - 100_000
    assert price_diff > OVERBID_SURPLUS_THRESHOLD
    rebate = int(round((price_diff - OVERBID_SURPLUS_THRESHOLD) * OVERBID_REBATE_PER_PLAYER_RATE))

    rows = list(csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[1][3] == "胜者"
    ticket = grc._map_entry_ticket(load_runtime().raw.get("automation") or {}, 2306)
    assert int(rows[1][7]) == 100_000 - 120_000 + rebate - ticket
    assert rows[2][3] == "败者"
    assert int(rows[2][7]) == 0 + rebate - ticket


def test_map_entry_ticket_lookup() -> None:
    auto = {
        "map_entry_ticket_by_map_id": {
            "230": 100,
            "240": 777,
        },
    }
    assert grc._map_entry_ticket(auto, 2301) == 100
    assert grc._map_entry_ticket(auto, 2306) == 100
    assert grc._map_entry_ticket(auto, 2310) == 100
    assert grc._map_entry_ticket(auto, 2401) == 777
    auto_int_key = {"map_entry_ticket_by_map_id": {230: 333}}
    assert grc._map_entry_ticket(auto_int_key, 2308) == 333
    assert grc._map_entry_ticket({"maps": {"1": {"ticket": 1}}}, 2301) == 0
