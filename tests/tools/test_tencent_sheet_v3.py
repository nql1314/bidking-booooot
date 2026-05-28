# -*- coding: utf-8 -*-
"""腾讯文档 Open API V3 工具函数。"""

from bidking.tools import blacklist_sheet_merge as merge
from bidking.tools.tencent_sheet_v3 import (
    _redact_headers,
    build_sheet_cell,
    cell_value_to_text,
    grid_data_to_rows,
    iter_a1_row_subranges,
    iter_value_row_chunks,
    max_rows_per_update_chunk,
    normalize_a1_range_for_api,
    parse_a1_range,
    range_cell_count,
    summarize_for_request_log,
)


def test_parse_a1_range() -> None:
    assert parse_a1_range("A4:E200") == (4, 1, 200, 5)
    assert parse_a1_range("C10") == (10, 3, 10, 3)
    assert normalize_a1_range_for_api("C6") == "C6:C6"
    assert normalize_a1_range_for_api("A4:E500") == "A4:E500"


def test_request_log_summarize_and_redact() -> None:
    headers = _redact_headers({"Access-Token": "abcdefgh1234", "Client-Id": "x"})
    assert "abcdef…" in headers["Access-Token"]
    assert "1234" not in headers["Access-Token"]
    body = {
        "requests": [
            {
                "updateRangeRequest": {
                    "sheetId": "BB08J2",
                    "gridData": {
                        "startRow": 3,
                        "startColumn": 0,
                        "rows": [{"values": [{"cellValue": {"text": "uid"}}]}],
                    },
                }
            }
        ]
    }
    summary = summarize_for_request_log(body)
    assert summary["requests"][0]["updateRangeRequest"]["rowCount"] == 1


def test_range_limits_and_chunking() -> None:
    assert range_cell_count("A4:E500") == 497 * 5
    assert max_rows_per_update_chunk(ncol=4) == 1000
    assert max_rows_per_update_chunk(ncol=5) == 1000
    assert max_rows_per_update_chunk(ncol=11) == 909

    values = [["a", "b", "c", "d"] for _ in range(2501)]
    chunks = iter_value_row_chunks(values)
    assert len(chunks) == 3
    assert chunks[0][0] == 0 and len(chunks[0][1]) == 1000
    assert chunks[1][0] == 1000 and len(chunks[1][1]) == 1000
    assert chunks[2][0] == 2000 and len(chunks[2][1]) == 501

    subs = iter_a1_row_subranges("A4:E500")
    assert subs == ["A4:E500"]
    subs_large = iter_a1_row_subranges("A4:E1500")
    assert subs_large == ["A4:E1003", "A1004:E1500"]


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


def test_build_sheet_cell_number_and_font() -> None:
    cell = build_sheet_cell(3, as_number=True, font_size=11)
    assert cell["cellValue"] == {"number": 3}
    assert cell["cellFormat"]["textFormat"]["fontSize"] == 11


def test_build_summary_row_cells_count_is_number() -> None:
    _, _, cells = merge.build_summary_row_cells(
        uid="884144787915084",
        name="昵称",
        count=5,
        join_date="2026-05-28",
        uid_col="A",
        name_col="B",
        join_date_col="D",
        count_col="C",
    )
    assert cells[2]["cellValue"] == {"number": 5}
    assert "cellFormat" not in cells[2]


def test_build_summary_row_cells_optional_font_size() -> None:
    _, _, cells = merge.build_summary_row_cells(
        uid="1",
        name="n",
        count=1,
        join_date="2026-01-01",
        uid_col="A",
        name_col="B",
        join_date_col="D",
        count_col="C",
        font_size=11,
    )
    assert cells[0]["cellFormat"]["textFormat"]["fontSize"] == 11


def test_parse_summary_rows_from_grid_reads_count() -> None:
    grid = [
        ["884144787915084", "昵称A", "3", "2026-01-01"],
        ["1071817679858757", "昵称B", "12", "2026-02-01"],
    ]
    rows = merge.parse_summary_rows_from_grid(grid, first_row_index=4)
    assert len(rows) == 2
    by_uid = {r.uid: r for r in rows}
    assert by_uid["884144787915084"].count == 3
    assert by_uid["1071817679858757"].count == 12


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
