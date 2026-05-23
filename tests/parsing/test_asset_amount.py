# -*- coding: utf-8 -*-

from bidking.parsing.asset_amount import (
    map_entry_money_by_map_key,
    parse_asset_amount_from_bidking_home,
    parse_asset_amount_from_ocr,
    parse_uid_from_home_full_window,
)


def test_parse_asset_plain_commas() -> None:
    assert parse_asset_amount_from_ocr("11,111") == 11_111
    assert parse_asset_amount_from_ocr(" 1,234,567 ") == 1_234_567


def test_parse_asset_k_m_suffix() -> None:
    assert parse_asset_amount_from_ocr("11,111K") == 11_111_000
    assert parse_asset_amount_from_ocr("111M") == 111_000_000
    assert parse_asset_amount_from_ocr("2.5M") == 2_500_000


def test_parse_asset_ocr_space_after_comma() -> None:
    assert parse_asset_amount_from_ocr("9, 665K") == 9_665_000
    assert parse_asset_amount_from_ocr("9,\n665K") == 9_665_000


def test_parse_asset_full_window_snippet() -> None:
    snippet = "BidKing\n9,665K\n650\nNico666"
    assert parse_asset_amount_from_bidking_home(snippet) == 9_665_000
    assert parse_asset_amount_from_ocr(snippet) == 9_665_000


def test_parse_asset_bidking_picks_max_of_two_lines() -> None:
    assert parse_asset_amount_from_bidking_home("BidKing\n9,665K\n650") == 9_665_000
    assert parse_asset_amount_from_bidking_home("BidKing\n650\n9,674K") == 9_674_000


def test_parse_asset_bidking_skips_nickname_line() -> None:
    snippet = "BidKing\n650\n9,674K\nNico666\nUID:358372071974712"
    assert parse_asset_amount_from_bidking_home(snippet) == 9_674_000


def test_parse_asset_bidking_space_after_comma() -> None:
    snippet = "BidKing\n9, 665K"
    assert parse_asset_amount_from_bidking_home(snippet) == 9_665_000


def test_parse_asset_picks_largest_token() -> None:
    assert parse_asset_amount_from_ocr("noise 500 11,111K") == 11_111_000


def test_parse_uid_from_home() -> None:
    snippet = "BidKing\n9,665K\nNico666\nUID:358372071974712"
    assert parse_uid_from_home_full_window(snippet) == "358372071974712"
    assert parse_uid_from_home_full_window("UID：123456789012") == "123456789012"


def test_map_entry_money_lookup() -> None:
    auto = {
        "map_entry_money_by_map_id": {
            "230": 500_000,
            "450": 5_000_000,
        },
    }
    assert map_entry_money_by_map_key(auto, "230") == 500_000
    assert map_entry_money_by_map_key(auto, "450") == 5_000_000
    assert map_entry_money_by_map_key(auto, "999") == 0
    assert map_entry_money_by_map_key({}, "230") == 0
