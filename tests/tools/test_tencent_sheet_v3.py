# -*- coding: utf-8 -*-
"""腾讯文档 Open API V3 工具函数。"""

from bidking.tools import blacklist_sheet_merge as merge
from bidking.tools.tencent_sheet_v3 import (
    cell_value_to_text,
    grid_data_to_rows,
    parse_a1_range,
)


def test_parse_a1_range() -> None:
    assert parse_a1_range("A4:E200") == (4, 1, 200, 5)
    assert parse_a1_range("C10") == (10, 3, 10, 3)


def test_grid_data_to_rows() -> None:
    grid = {
        "startRow": 3,
        "startColumn": 0,
        "rows": [
            {
                "values": [
                    {"cellValue": {"text": "2101:117"}},
                    {"cellValue": {"text": "1071817679858757"}},
                    {"cellValue": {"text": "name"}},
                    {"cellValue": {"number": 1}},
                    {"cellValue": {"text": "1041"}},
                ]
            }
        ],
    }
    first_row, first_col, lines = grid_data_to_rows(grid)
    assert first_row == 4
    assert first_col == 1
    assert lines[0][3] == "1"
    assert lines[0][4] == "1041"


def test_parse_temp_rows_from_grid() -> None:
    grid = [
        ["2101:1178745817265764", "1071817679858757", "结城明日奈11", "1", "1041"],
        ["", "", "", "", ""],
        ["2104:1178745824104353", "434925569544468", "一嘻", "2", "23333"],
    ]
    rows = merge.parse_temp_rows_from_grid(grid, first_row_index=4)
    assert len(rows) == 2
    assert rows[0].round_no == 1
    assert rows[0].bid == 1041
    assert rows[1].round_no == 2


def test_classify_temp_rows_from_grid() -> None:
    rows = merge.parse_temp_rows_from_grid(
        [
            ["2101:1", "111111111111111", "a", "1", "1000"],
            ["2101:2", "222222222222222", "b", "2", "1000"],
            ["2101:3", "333333333333333", "c", "1", "30000"],
            ["", "444444444444444", "d", "1", "100"],
        ],
        first_row_index=4,
    )
    sync, purge, no_game, other = merge.classify_temp_rows(
        rows, max_sync_bid=25000
    )
    assert len(sync) == 1
    assert sync[0].uid == "111111111111111"
    assert len(purge) == 2
    assert {r.uid for r in purge} == {"222222222222222", "333333333333333"}
    assert len(no_game) == 1
    assert no_game[0].uid == "444444444444444"
