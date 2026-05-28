# -*- coding: utf-8 -*-
"""临时表 → 汇总表合并计划。"""

from datetime import date

from bidking.tools import blacklist_sheet_merge as merge
from bidking.tools.tencent_sheet_v3 import TencentSheetV3Client


def test_parse_temp_rows_from_sample_blob() -> None:
    blob = (
        b"bid\n"
        b"\x11\n\x0f884144787915084\n"
        b"\x11\n\x0f\xe4\xb8\x80\xe5\x88\x87\xe4\xba\xa6\xe8\x99\x9a\xe5\xb9\xbb\n"
        b"\x0e\n\x0c\xe7\xa4\xba\xe4\xbe\x8b\xe8\xaf\xaf\xe5\x88\xa0\n"
        b"\x17\n\x152101:1178745817265764\n"
        b"\x12\n\x101071817679858757\n"
        b"\x13\n\x11\xe7\xbb\x93\xe5\x9f\x8e\xe6\x98\x8e\xe6\x97\xa5\xe5\xa5\x8811\n"
        b"\x03\n\x011\n"
        b"\x06\n\x041041\n"
    )
    rows = merge.parse_temp_blacklist_rows_from_sheet_blob(blob)
    assert len(rows) == 1
    assert rows[0].uid == "1071817679858757"
    assert rows[0].row_index == 4
    assert rows[0].bid == 1041


def test_temp_row_sync_round_by_d_column() -> None:
    assert merge.temp_row_is_sync_round(
        ["2107:1274127909675670", "913762882518538", "叶子也吃鱼", "1", "8886"]
    )
    assert not merge.temp_row_is_sync_round(
        ["2107:1274127909675670", "913762882518538", "叶子也吃鱼", "2", "8886"]
    )
    assert not merge.temp_row_is_sync_round(["2106:123", "uid", "name"])


def test_split_temp_rows_by_round() -> None:
    blob = (
        b"bid\n"
        b"\x17\n\x152106:1274127905909778\n"
        b"\x12\n\x101193519871950916\n"
        b"\x0b\n\t\xe6\xb3\xbd\xe5\xb8\x83\xe4\xbc\xa6\n"
        b"\x03\n\x022\n"
        b"\x17\n\x152101:1178745817265764\n"
        b"\x12\n\x101071817679858757\n"
        b"\x13\n\x11\xe7\xbb\x93\xe5\x9f\x8e\xe6\x98\x8e\xe6\x97\xa5\xe5\xa5\x8811\n"
        b"\x03\n\x011\n"
        b"\x06\n\x041041\n"
    )
    round_one, other = merge.split_temp_rows_by_round(blob)
    assert len(other) == 1
    assert other[0].uid == "1193519871950916"
    assert len(round_one) == 1
    assert round_one[0].uid == "1071817679858757"


def test_extract_bid_from_row_parts() -> None:
    assert merge.extract_bid_from_row_parts(
        ["884144787915084", "一切亦虚幻", "1", "1041"]
    ) == 1041
    assert merge.extract_bid_from_row_parts(["uid", "name", "1"]) is None
    assert merge.extract_bid_from_row_parts(["uid", "name", "26000"]) == 26000


def test_classify_purges_high_bid_round_one() -> None:
    blob = (
        b"bid\n"
        b"\x11\n\x0f884144787915084\n"
        b"\x11\n\x0f\xe4\xb8\x80\xe5\x88\x87\xe4\xba\xa6\xe8\x99\x9a\xe5\xb9\xbb\n"
        b"\x0e\n\x0c\xe7\xa4\xba\xe4\xbe\x8b\xe8\xaf\xaf\xe5\x88\xa0\n"
        b"\x17\n\x152101:1178745817265764\n"
        b"\x12\n\x101071817679858757\n"
        b"\x13\n\x11\xe7\xbb\x93\xe5\x9f\x8e\xe6\x98\x8e\xe6\x97\xa5\xe5\xa5\x8811\n"
        b"\x03\n\x011\n"
        b"\x06\n\x0526000\n"
    )
    sync_rows, purge_rows, ignored = merge.classify_temp_sheet_rows(
        blob, max_sync_bid=25000
    )
    assert not sync_rows
    assert len(purge_rows) == 1
    assert purge_rows[0].bid == 26000
    assert purge_rows[0].game_uid == "2101:1178745817265764"
    assert not ignored


def test_classify_ignores_rows_without_game_uid() -> None:
    blob = (
        b"bid\n"
        b"\x17\n\x152106:1274127905909778\n"
        b"\x12\n\x101193519871950916\n"
        b"\x0b\n\t\xe6\xb3\xbd\xe5\xb8\x83\xe4\xbc\xa6\n"
        b"\x03\n\x022\n"
        b"\x17\n\x152101:1178745817265764\n"
        b"\x12\n\x101071817679858757\n"
        b"\x13\n\x11\xe7\xbb\x93\xe5\x9f\x8e\xe6\x98\x8e\xe6\x97\xa5\xe5\xa5\x8811\n"
        b"\x03\n\x011\n"
        b"\x06\n\x041041\n"
        b"\x12\n\x101313131313131313\n"
        b"\x0b\n\t\xe5\x90\x8d\xe5\xad\x97\n"
        b"\x03\n\x011\n"
    )
    sync_rows, purge_rows, ignored = merge.classify_temp_sheet_rows(blob)
    assert len(sync_rows) == 1
    assert sync_rows[0].uid == "1071817679858757"
    assert len(purge_rows) == 1
    assert purge_rows[0].uid == "1193519871950916"
    assert len(ignored) == 1
    assert ignored[0].uid == "1313131313131313"
    assert ignored[0].game_uid == ""


def test_build_merge_plan_insert_and_update() -> None:
    temp = [
        merge.TempBlacklistRow(2, "111111111111111", "a"),
        merge.TempBlacklistRow(3, "222222222222222", "b"),
        merge.TempBlacklistRow(4, "111111111111111", "dup"),
    ]
    summary = [
        merge.SummaryBlacklistRow(5, "222222222222222", "old", count=2),
    ]
    plan = merge.build_merge_plan(temp, summary)
    assert len(plan.inserts) == 1
    assert plan.inserts[0].uid == "111111111111111"
    assert len(plan.updates) == 1
    assert plan.updates[0].uid == "222222222222222"
    assert len(plan.skipped) == 1
    assert plan.skipped[0].reason == "临时表内重复 UID"


def test_build_merge_plan_includes_purge_rows() -> None:
    purge = [merge.TempBlacklistRow(6, "333333333333333", "x", game_uid="2101:1")]
    plan = merge.build_merge_plan([], [], purge_rows=purge)
    assert len(plan.purge_other_rounds) == 1


def test_access_token_from_env(monkeypatch) -> None:
    monkeypatch.setenv("BIDKING_TENCENT_DOCS_ACCESS_TOKEN", "secret-token")
    token = merge.resolve_openapi_access_token({"client_id": "c"})
    assert token == "secret-token"


def test_access_token_custom_env_name() -> None:
    token = merge.resolve_openapi_access_token(
        {"access_token_env": "MY_DOCS_TOKEN"},
        environ={"MY_DOCS_TOKEN": "  tok  "},
    )
    assert token == "tok"


def test_open_client_from_config(monkeypatch) -> None:
    monkeypatch.setenv("BIDKING_TENCENT_DOCS_ACCESS_TOKEN", "tok")
    client = merge._open_client_from_config(
        {
            "book_id": "300000000$ABC",
            "openapi": {"client_id": "cid", "open_id": "oid"},
        }
    )
    assert isinstance(client, TencentSheetV3Client)
    assert client.access_token == "tok"


def test_build_summary_row_cells() -> None:
    left, right, cells = merge.build_summary_row_cells(
        uid="884144787915084",
        name="一切亦虚幻",
        count=3,
        join_date="2026-05-28",
        uid_col="A",
        name_col="B",
        join_date_col="D",
        count_col="C",
    )
    assert (left, right) == ("A", "D")
    assert cells == ["884144787915084", "一切亦虚幻", "3", "2026-05-28"]


def test_format_sync_join_date() -> None:
    assert (
        merge.format_sync_join_date(date(2026, 5, 28), fmt="%Y-%m-%d")
        == "2026-05-28"
    )


def test_resolve_sheet_merge_from_runtime_top_level() -> None:
    cfg = {
        "express_emoji_public_blacklist": {
            "sheet_id": "DQ0hQYVVyc1dQbFJH",
            "tab": "BB08J2",
        },
        "sheet_merge": {
            "book_id": "300000000$CHPaUrsWPlRG",
            "openapi": {
                "client_id": "cid",
                "open_id": "oid",
            },
        },
    }
    resolved = merge.resolve_blacklist_sheet_merge_source(cfg)
    assert resolved["book_id"] == "300000000$CHPaUrsWPlRG"
    assert resolved["sheet_id"] == "DQ0hQYVVyc1dQbFJH"
    assert resolved["summary_tab"] == "BB08J2"
    assert resolved["openapi"]["client_id"] == "cid"
    assert resolved["summary_join_date_col"] == "D"
    assert resolved["sync_round_no"] == 1


def test_validate_skips_example_row() -> None:
    row = merge.TempBlacklistRow(2, "333333333333333", "示例勿用")
    reason = merge.validate_temp_row(row, seen_temp_uids=set())
    assert reason == "示例/测试行"


def test_iter_skips_sheet_row_2_even_without_hint() -> None:
    """第 2 行即使有合法 UID 也不参与扫描（与是否含「示例」文案无关）。"""
    blob = (
        b"bid\n"
        b"\x12\n\x101193519871950916\n"
        b"\x0b\n\t\xe6\xb3\xbd\xe5\xb8\x83\xe4\xbc\xa6\n"
        b"\x03\n\x022\n"
        b"\x17\n\x152101:1178745817265764\n"
        b"\x12\n\x101071817679858757\n"
        b"\x13\n\x11\xe7\xbb\x93\xe5\x9f\x8e\xe6\x98\x8e\xe6\x97\xa5\xe5\xa5\x8811\n"
        b"\x03\n\x011\n"
    )
    rows = merge.parse_temp_blacklist_rows_from_sheet_blob(blob)
    assert len(rows) == 1
    assert rows[0].uid == "1071817679858757"
    assert rows[0].row_index == 4


def test_summary_append_start_row_when_sheet_empty() -> None:
    plan = merge.build_merge_plan(
        [merge.TempBlacklistRow(4, "111111111111111", "a", game_uid="2101:1", round_no=1)],
        [],
    )
    max_row = max((r.row_index for r in plan.summary_by_uid.values()), default=3)
    start_row = max(max_row + 1, merge._TEMP_SHEET_FIRST_DATA_ROW_INDEX)
    assert start_row == 4
