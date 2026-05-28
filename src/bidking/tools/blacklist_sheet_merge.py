"""将腾讯文档「临时表」有效行合并到「汇总表」，并清理已同步的临时行。

读写使用 [腾讯文档 Open API V3 在线表格](https://docs.qq.com/open/document/app/openapi/v3/sheet/overview.html)
（见 ``docs/tencent_sheet_openapi_v3.md``）。未配置 token 时仅能用 ``dop-api`` 粗略预览（常缺 round/bid 列）。
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from dataclasses import dataclass
from typing import Any

from bidking.interaction.public_blacklist_sync import (
    _DEFAULT_SHEET_ID,
    _UID_RE,
    _fetch_sheet_chunk_blob,
    parse_qq_sheet_url,
)
from bidking.tools.tencent_sheet_v3 import TencentSheetV3Client

_DEFAULT_TEMP_TAB = "xz3aq0"
_DEFAULT_SUMMARY_TAB = "BB08J2"
_DEFAULT_ACCESS_TOKEN_ENV = "BIDKING_TENCENT_DOCS_ACCESS_TOKEN"
_DEFAULT_SUMMARY_COUNT_COL = "C"
_DEFAULT_SUMMARY_JOIN_DATE_COL = "D"
_DEFAULT_JOIN_DATE_FORMAT = "%Y-%m-%d"
_DEFAULT_SYNC_ROUND_MARKER = "2101:"
_DEFAULT_SYNC_ROUND_NO = 1
_MAX_ROUND_COLUMN_VALUE = 20
_DEFAULT_MAX_SYNC_BID = 25000
_DEFAULT_TEMP_READ_RANGE = "A4:E500"
_DEFAULT_SUMMARY_READ_RANGE = "A4:D500"
_MAX_REASONABLE_BID = 99_999_999
_SKIP_HINT_RE = re.compile(r"示例|误删|测试|test|demo", re.I)
_GAME_COLON_RE = re.compile(r"^\d{4}:\d+")
# 临时表：第 2 行示例、第 3 行表头；数据自第 4 行起。汇总表仍跳过第 2 行示例。
_SHEET_EXAMPLE_ROW_INDEX = 2
_TEMP_SHEET_HEADER_ROW_INDEX = 3
_TEMP_SHEET_FIRST_DATA_ROW_INDEX = 4


@dataclass(frozen=True)
class TempBlacklistRow:
    """临时表一行（含 1-based 行号，便于 Open API 定位）。"""

    row_index: int
    uid: str
    name: str
    bid: int | None = None
    game_uid: str = ""
    round_no: int | None = None


@dataclass(frozen=True)
class SkippedRow:
    row: TempBlacklistRow
    reason: str


@dataclass(frozen=True)
class SummaryBlacklistRow:
    """汇总表已有行（含行号，便于原地更新）。"""

    row_index: int
    uid: str
    name: str
    count: int = 0


@dataclass(frozen=True)
class MergePlan:
    inserts: tuple[TempBlacklistRow, ...]
    updates: tuple[TempBlacklistRow, ...]
    skipped: tuple[SkippedRow, ...]
    summary_by_uid: dict[str, SummaryBlacklistRow]
    purge_other_rounds: tuple[TempBlacklistRow, ...]


@dataclass(frozen=True)
class MergeApplyResult:
    plan: MergePlan
    synced: tuple[TempBlacklistRow, ...]
    failed_delete_rows: tuple[int, ...]
    note: str


def _col_index(col: str) -> int:
    """Excel 列字母 → 1-based 索引（``A`` → 1）。"""
    n = 0
    for ch in str(col or "").strip().upper():
        if not ("A" <= ch <= "Z"):
            raise ValueError(f"无效列名: {col!r}")
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _col_letter(index: int) -> str:
    """1-based 索引 → Excel 列字母。"""
    if index < 1:
        raise ValueError(f"列索引须 >= 1，收到 {index}")
    letters: list[str] = []
    n = index
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def format_sync_join_date(
    when: date | datetime | None = None,
    *,
    fmt: str | None = None,
) -> str:
    """生成写入汇总表「加入日期」列的字符串。"""
    pattern = (fmt or _DEFAULT_JOIN_DATE_FORMAT).strip() or _DEFAULT_JOIN_DATE_FORMAT
    if when is None:
        when = date.today()
    elif isinstance(when, datetime):
        when = when.date()
    return when.strftime(pattern)


def parse_count_cell(value: str) -> int:
    """解析汇总表「偷快递次数」单元格为整数。"""
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 0


def game_marker_from_parts(parts: list[str]) -> str:
    """取行内 A 列局号标记（``2101:…``）；仅认第一个 ``dddd:`` 字段。"""
    for part in parts:
        raw = str(part or "").strip()
        if _GAME_COLON_RE.match(raw):
            return raw
    return ""


def extract_round_from_row_parts(parts: list[str]) -> int | None:
    """
    从临时表行字段解析回合列（D 列，通常 1–10）。

    A 列为 ``地图ID:局号``（如 ``2107:…``），不能用来判断第几回合。
    """
    for part in parts[1:]:
        raw = str(part or "").strip().replace(",", "")
        if not raw.isdigit():
            continue
        if _UID_RE.fullmatch(raw):
            continue
        n = int(raw)
        if 1 <= n <= _MAX_ROUND_COLUMN_VALUE:
            return n
    return None


def temp_row_is_sync_round(
    parts: list[str],
    *,
    sync_round_no: int = _DEFAULT_SYNC_ROUND_NO,
) -> bool:
    """临时表行是否属于待同步回合（默认第 1 回合，看 D 列数字）。"""
    r = extract_round_from_row_parts(parts)
    if r is None:
        return False
    return r == int(sync_round_no)


def temp_row_has_round_marker(
    parts: list[str],
    *,
    round_marker: str = _DEFAULT_SYNC_ROUND_MARKER,
) -> bool:
    """已废弃：请用 ``temp_row_is_sync_round``（按 D 列回合，非 A 列地图前缀）。"""
    return temp_row_is_sync_round(parts)


def build_summary_row_cells(
    *,
    uid: str,
    name: str,
    count: int,
    join_date: str,
    uid_col: str,
    name_col: str,
    join_date_col: str,
    count_col: str | None,
) -> tuple[str, str, list[str]]:
    """构造汇总表一行单元格（A–D：UID / 昵称 / 次数 / 加入日期）。"""
    cells: dict[str, str] = {
        uid_col: uid,
        name_col: name,
        join_date_col: join_date,
    }
    if count_col:
        cells[count_col] = str(max(0, int(count)))
    ordered_cols = sorted(cells, key=_col_index)
    left, right = ordered_cols[0], ordered_cols[-1]
    values: list[str] = []
    for idx in range(_col_index(left), _col_index(right) + 1):
        letter = _col_letter(idx)
        values.append(cells.get(letter, ""))
    return left, right, values


def _merge_sheet_merge_branch(
    base: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    out = dict(base)
    for key, val in overlay.items():
        if key == "openapi" and isinstance(val, dict):
            prev = out.get("openapi")
            merged_openapi = dict(prev) if isinstance(prev, dict) else {}
            merged_openapi.update(val)
            out["openapi"] = merged_openapi
        else:
            out[key] = val
    return out


def resolve_blacklist_sheet_merge_source(
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    解析合并配置。

    推荐写在 ``configs/runtime.json`` 顶层 ``sheet_merge``（``load_runtime()`` 已合并
    ``config.json``）。亦可使用 ``express_emoji_public_blacklist.sheet_merge``、
    ``blacklist_sheet_merge``；后两者仅补充未在 ``sheet_merge`` 中设置的字段。

    ``openapi`` 放 ``client_id`` / ``open_id``；``access_token`` 从环境变量读取（默认
    ``BIDKING_TENCENT_DOCS_ACCESS_TOKEN``，可用 ``access_token_env`` 改名）。
    """
    branch: dict[str, Any] = {}
    if isinstance(config, dict):
        root = config.get("express_emoji_public_blacklist")
        if isinstance(root, dict):
            raw = root.get("sheet_merge")
            if isinstance(raw, dict):
                branch = dict(raw)
            if not branch.get("sheet_id"):
                branch["sheet_id"] = str(root.get("sheet_id") or "").strip()
            if not branch.get("summary_tab"):
                branch["summary_tab"] = str(root.get("tab") or "").strip()
            if not branch.get("source_url") and not branch.get("url"):
                url = str(root.get("source_url") or root.get("url") or "").strip()
                if url:
                    branch["source_url"] = url
        for key in ("blacklist_sheet_merge", "sheet_merge"):
            alt = config.get(key)
            if isinstance(alt, dict):
                branch = _merge_sheet_merge_branch(branch, alt)
    sheet_id = str(branch.get("sheet_id") or _DEFAULT_SHEET_ID).strip()
    temp_tab = str(branch.get("temp_tab") or _DEFAULT_TEMP_TAB).strip()
    summary_tab = str(branch.get("summary_tab") or _DEFAULT_SUMMARY_TAB).strip()
    url = str(branch.get("source_url") or branch.get("url") or "").strip()
    if url:
        parsed_id, parsed_tab = parse_qq_sheet_url(url)
        sheet_id = sheet_id or parsed_id
        if parsed_tab and not branch.get("summary_tab"):
            summary_tab = parsed_tab
    openapi = branch.get("openapi")
    if not isinstance(openapi, dict):
        openapi = {}
    return {
        "sheet_id": sheet_id,
        "temp_tab": temp_tab,
        "summary_tab": summary_tab,
        "book_id": str(branch.get("book_id") or "").strip(),
        "openapi": openapi,
        "summary_uid_col": str(branch.get("summary_uid_col") or "A").strip().upper(),
        "summary_name_col": str(branch.get("summary_name_col") or "B").strip().upper(),
        "summary_count_col": str(
            branch.get("summary_count_col") or _DEFAULT_SUMMARY_COUNT_COL
        ).strip().upper(),
        "summary_join_date_col": str(
            branch.get("summary_join_date_col") or _DEFAULT_SUMMARY_JOIN_DATE_COL
        ).strip().upper(),
        "join_date_format": str(
            branch.get("join_date_format") or _DEFAULT_JOIN_DATE_FORMAT
        ).strip(),
        "sync_round_marker": str(
            branch.get("sync_round_marker") or _DEFAULT_SYNC_ROUND_MARKER
        ).strip(),
        "sync_round_no": int(branch.get("sync_round_no", _DEFAULT_SYNC_ROUND_NO) or _DEFAULT_SYNC_ROUND_NO),
        "max_sync_bid": int(
            branch.get("max_sync_bid", _DEFAULT_MAX_SYNC_BID) or _DEFAULT_MAX_SYNC_BID
        ),
        "temp_clear_range_cols": str(branch.get("temp_clear_range_cols") or "A:E").strip().upper(),
        "temp_read_range": str(
            branch.get("temp_read_range") or _DEFAULT_TEMP_READ_RANGE
        ).strip().upper(),
        "summary_read_range": str(
            branch.get("summary_read_range") or _DEFAULT_SUMMARY_READ_RANGE
        ).strip().upper(),
    }


def _read_length_prefixed_field(blob: bytes, pos: int) -> tuple[str | None, int]:
    while pos < len(blob) and blob[pos] == 0x0A:
        pos += 1
    if pos + 3 > len(blob) or blob[pos + 1] != 0x0A:
        return None, pos
    length = blob[pos + 2]
    pos += 3
    if pos + length > len(blob):
        return None, pos
    return blob[pos : pos + length].decode("utf-8", errors="replace"), pos + length


def _read_all_length_prefixed_fields(blob: bytes, *, marker: bytes) -> list[str]:
    pos = blob.find(marker)
    if pos < 0:
        return []
    pos += len(marker)
    fields: list[str] = []
    while pos < len(blob) - 3:
        value, pos = _read_length_prefixed_field(blob, pos)
        if value is None:
            break
        fields.append(value)
    return fields


def _extract_name_from_row_parts(parts: list[str]) -> str:
    for part in parts[1:]:
        if (
            not _GAME_COLON_RE.match(part)
            and ":" not in part
            and not _UID_RE.fullmatch(part)
            and not _is_digit_token(part)
        ):
            return part.strip()
    return ""


def _is_digit_token(value: str) -> bool:
    return str(value or "").strip().replace(",", "").isdigit()


def _is_sheet_example_row(row_index: int) -> bool:
    """是否为表格固定示例行（默认第 2 行）。"""
    return int(row_index) == _SHEET_EXAMPLE_ROW_INDEX


def _is_temp_sheet_skipped_row(row_index: int) -> bool:
    """临时表非数据行：第 2 行示例、第 3 行表头。"""
    n = int(row_index)
    return n in (_SHEET_EXAMPLE_ROW_INDEX, _TEMP_SHEET_HEADER_ROW_INDEX)


def extract_bid_from_row_parts(parts: list[str]) -> int | None:
    """
    从临时表行字段解析 ``bid`` 列（纯数字，与 ``emoji_signal_match_blacklist.csv`` 一致）。

    若有多个数字，优先取大于 20 的（排除 ``round`` 列 1–10）；仅小数字时视为无出价。
    """
    numbers: list[int] = []
    for part in parts[1:]:
        raw = str(part or "").strip().replace(",", "")
        if not raw.isdigit():
            continue
        if _UID_RE.fullmatch(raw):
            continue
        n = int(raw)
        if 0 < n <= _MAX_REASONABLE_BID:
            numbers.append(n)
    if not numbers:
        return None
    high = [n for n in numbers if n > 20]
    if high:
        return high[0]
    if all(n <= 20 for n in numbers):
        return None
    return numbers[0]


def _advance_temp_sheet_row_index(row_index: int) -> int:
    row_index += 1
    if row_index == _TEMP_SHEET_HEADER_ROW_INDEX:
        return _TEMP_SHEET_FIRST_DATA_ROW_INDEX
    return row_index


def _iter_temp_sheet_row_parts(fields: list[str]) -> list[tuple[int, list[str]]]:
    """
    按表格行切分字段：A 列 ``2101:局号`` 开启新行，至下一个局号标记前归属同一行。

    无局号标记时回退为「遇新 UID 换行」（兼容旧压缩块顺序）。
    """
    rows: list[tuple[int, list[str]]] = []
    row_index = 2
    parts: list[str] = []

    def flush() -> None:
        nonlocal row_index, parts
        if not parts:
            return
        if (
            len(parts) == 1
            and _GAME_COLON_RE.match(str(parts[0]).strip())
            and rows
            and not game_marker_from_parts(rows[-1][1])
        ):
            prev_index, prev_parts = rows[-1]
            rows[-1] = (prev_index, prev_parts + list(parts))
            parts = []
            return
        if _is_temp_sheet_skipped_row(row_index):
            if game_marker_from_parts(parts):
                while _is_temp_sheet_skipped_row(row_index):
                    row_index = _advance_temp_sheet_row_index(row_index)
            else:
                row_index = _advance_temp_sheet_row_index(row_index)
                parts = []
                return
        rows.append((row_index, list(parts)))
        row_index = _advance_temp_sheet_row_index(row_index)
        parts = []

    for field in fields:
        raw = str(field or "").strip()
        if not raw:
            continue
        if _GAME_COLON_RE.match(raw):
            if parts:
                flush()
            parts = [raw]
            continue
        if _UID_RE.fullmatch(raw):
            if not parts:
                parts = [raw]
                continue
            if any(_UID_RE.fullmatch(str(p).strip()) for p in parts):
                flush()
                parts = [raw]
                continue
        if parts:
            parts.append(raw)
    if parts:
        flush()
    return rows


def _iter_temp_sheet_uid_blocks(blob: bytes) -> list[tuple[int, str, str, list[str]]]:
    """解析临时表每个 UID 数据行，返回 ``(行号, uid, name, 原始字段)``。"""
    fields = _read_all_length_prefixed_fields(blob, marker=b"bid\n")
    if not fields:
        fields = _read_all_length_prefixed_fields(blob, marker=b"uid\n")
    blocks: list[tuple[int, str, str, list[str]]] = []
    for row_index, parts in _iter_temp_sheet_row_parts(fields):
        uid = next((p for p in parts if _UID_RE.fullmatch(str(p).strip())), None)
        if not uid:
            continue
        name = _extract_name_from_row_parts(parts)
        blocks.append((row_index, uid, name, parts))
    return blocks


def _parse_optional_int(value: str) -> int | None:
    raw = str(value or "").strip().replace(",", "")
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def _temp_row_from_parts(
    row_index: int,
    uid: str,
    name: str,
    parts: list[str],
) -> TempBlacklistRow:
    game_uid = game_marker_from_parts(parts)
    if not game_uid:
        head = str(parts[0] if parts else "").strip()
        if _GAME_COLON_RE.match(head):
            game_uid = head
    return TempBlacklistRow(
        row_index=row_index,
        uid=uid,
        name=name,
        bid=extract_bid_from_row_parts(parts),
        game_uid=game_uid,
        round_no=extract_round_from_row_parts(parts),
    )


def parse_temp_rows_from_grid(
    grid_rows: list[list[str]],
    *,
    first_row_index: int = _TEMP_SHEET_FIRST_DATA_ROW_INDEX,
) -> list[TempBlacklistRow]:
    """从 V3 ``get_range`` 返回的网格解析临时表行（列 A–E）。"""
    rows: list[TempBlacklistRow] = []
    for offset, cells in enumerate(grid_rows):
        row_index = int(first_row_index) + offset
        if _is_temp_sheet_skipped_row(row_index):
            continue
        padded = (list(cells) + [""] * 5)[:5]
        game_uid = str(padded[0] or "").strip()
        uid = str(padded[1] or "").strip()
        name = str(padded[2] or "").strip()
        round_raw = str(padded[3] or "").strip()
        bid_raw = str(padded[4] or "").strip()
        if not uid and not game_uid:
            continue
        parts = [p for p in (game_uid, uid, name, round_raw, bid_raw) if p]
        if any(_SKIP_HINT_RE.search(p) for p in parts):
            continue
        if not _UID_RE.fullmatch(uid):
            continue
        if game_uid and not _GAME_COLON_RE.match(game_uid):
            game_uid = game_marker_from_parts(parts)
        round_no = _parse_optional_int(round_raw)
        bid = _parse_optional_int(bid_raw)
        if bid is None and bid_raw:
            bid = extract_bid_from_row_parts(parts)
        if round_no is None and round_raw:
            round_no = extract_round_from_row_parts(parts)
        rows.append(
            TempBlacklistRow(
                row_index=row_index,
                uid=uid,
                name=name,
                bid=bid,
                game_uid=game_uid,
                round_no=round_no,
            )
        )
    return rows


def parse_summary_rows_from_grid(
    grid_rows: list[list[str]],
    *,
    first_row_index: int = _TEMP_SHEET_FIRST_DATA_ROW_INDEX,
) -> list[SummaryBlacklistRow]:
    """从 V3 网格解析汇总表行（A=UID, B=昵称）。"""
    rows: list[SummaryBlacklistRow] = []
    for offset, cells in enumerate(grid_rows):
        row_index = int(first_row_index) + offset
        padded = (list(cells) + [""] * 2)[:2]
        uid = str(padded[0] or "").strip()
        name = str(padded[1] or "").strip()
        if not _UID_RE.fullmatch(uid):
            continue
        if _is_sheet_example_row(row_index):
            continue
        rows.append(
            SummaryBlacklistRow(row_index=row_index, uid=uid, name=name, count=0)
        )
    by_uid: dict[str, SummaryBlacklistRow] = {}
    for row in rows:
        if row.uid not in by_uid:
            by_uid[row.uid] = row
    return list(by_uid.values())


def classify_temp_rows(
    rows: list[TempBlacklistRow],
    *,
    sync_round_no: int = _DEFAULT_SYNC_ROUND_NO,
    max_sync_bid: int = _DEFAULT_MAX_SYNC_BID,
) -> tuple[
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    list[TempBlacklistRow],
]:
    """
    将临时表行分为：待写入汇总 / 待清理 / 无局号忽略 / 其它忽略。

    其它忽略：有局号但无法解析回合（常见于 dop-api 缺 D 列）。
    """
    sync_rows: list[TempBlacklistRow] = []
    purge_rows: list[TempBlacklistRow] = []
    ignored_no_game: list[TempBlacklistRow] = []
    ignored_other: list[TempBlacklistRow] = []
    for row in rows:
        if not row.game_uid:
            ignored_no_game.append(row)
            continue
        round_no = row.round_no
        over_bid = row.bid is not None and row.bid > int(max_sync_bid)
        if round_no is None:
            ignored_other.append(row)
            continue
        if round_no == int(sync_round_no) and not over_bid:
            sync_rows.append(row)
        elif round_no > int(sync_round_no) or over_bid:
            purge_rows.append(row)
        else:
            ignored_other.append(row)
    return sync_rows, purge_rows, ignored_no_game, ignored_other


def classify_temp_sheet_rows(
    blob: bytes,
    *,
    sync_round_no: int = _DEFAULT_SYNC_ROUND_NO,
    max_sync_bid: int = _DEFAULT_MAX_SYNC_BID,
) -> tuple[
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    list[TempBlacklistRow],
]:
    """从 dop-api 压缩块分类（常缺 round/bid，仅作无 token 回退）。"""
    parsed: list[TempBlacklistRow] = []
    for row_index, uid, name, parts in _iter_temp_sheet_uid_blocks(blob):
        if any(_SKIP_HINT_RE.search(p) for p in parts):
            continue
        parsed.append(_temp_row_from_parts(row_index, uid, name, parts))
    sync_rows, purge_rows, ignored_no_game, ignored_other = classify_temp_rows(
        parsed, sync_round_no=sync_round_no, max_sync_bid=max_sync_bid
    )
    return sync_rows, purge_rows, list(ignored_no_game) + list(ignored_other)


def split_temp_rows_by_round(
    blob: bytes,
    *,
    sync_round_no: int = _DEFAULT_SYNC_ROUND_NO,
    max_sync_bid: int = _DEFAULT_MAX_SYNC_BID,
) -> tuple[list[TempBlacklistRow], list[TempBlacklistRow]]:
    """将临时表行分为待同步第一回合与待清理行（见 ``classify_temp_sheet_rows``）。"""
    sync_rows, purge_rows, _ = classify_temp_sheet_rows(
        blob, sync_round_no=sync_round_no, max_sync_bid=max_sync_bid
    )
    return sync_rows, purge_rows


def parse_temp_blacklist_rows_from_sheet_blob(
    blob: bytes,
    *,
    sync_round_no: int = _DEFAULT_SYNC_ROUND_NO,
    max_sync_bid: int = _DEFAULT_MAX_SYNC_BID,
) -> list[TempBlacklistRow]:
    """从临时表压缩块解析待同步的第一回合行。"""
    sync_rows, _, _ = classify_temp_sheet_rows(
        blob, sync_round_no=sync_round_no, max_sync_bid=max_sync_bid
    )
    return sync_rows


def parse_summary_blacklist_rows_from_sheet_blob(
    blob: bytes,
) -> list[SummaryBlacklistRow]:
    """从汇总表压缩块解析已有行（含行号；次数列公开读取常为空，写入前再拉取）。"""
    marker = "加入日期\n".encode("utf-8")
    fields = _read_all_length_prefixed_fields(blob, marker=marker)
    if not fields:
        fields = _read_all_length_prefixed_fields(blob, marker=b"UID\n")
    rows: list[SummaryBlacklistRow] = []
    row_index = 2
    i = 0
    while i < len(fields):
        field = fields[i]
        if not _UID_RE.fullmatch(field):
            i += 1
            continue
        uid = field
        parts = [uid]
        j = i + 1
        while j < len(fields) and not _UID_RE.fullmatch(fields[j]):
            parts.append(fields[j])
            j += 1
        name = _extract_name_from_row_parts(parts)
        if not _is_sheet_example_row(row_index):
            rows.append(
                SummaryBlacklistRow(row_index=row_index, uid=uid, name=name, count=0)
            )
        row_index += 1
        i = j if j > i + 1 else i + 1
    by_uid: dict[str, SummaryBlacklistRow] = {}
    for row in rows:
        if row.uid not in by_uid:
            by_uid[row.uid] = row
    return list(by_uid.values())


def validate_temp_row(
    row: TempBlacklistRow,
    *,
    seen_temp_uids: set[str],
) -> str | None:
    """校验待写入汇总的临时行；通过返回 ``None``，否则返回跳过原因。"""
    uid = row.uid.strip()
    if not _UID_RE.fullmatch(uid):
        return "UID 格式无效"
    if uid in seen_temp_uids:
        return "临时表内重复 UID"
    if _SKIP_HINT_RE.search(f"{row.name}"):
        return "示例/测试行"
    return None


def build_merge_plan(
    temp_rows: list[TempBlacklistRow],
    summary_rows: list[SummaryBlacklistRow],
) -> MergePlan:
    summary_by_uid = {r.uid: r for r in summary_rows if r.uid}
    inserts: list[TempBlacklistRow] = []
    updates: list[TempBlacklistRow] = []
    skipped: list[SkippedRow] = []
    seen: set[str] = set()
    for row in temp_rows:
        reason = validate_temp_row(row, seen_temp_uids=seen)
        if reason:
            skipped.append(SkippedRow(row=row, reason=reason))
            continue
        seen.add(row.uid)
        if row.uid in summary_by_uid:
            updates.append(row)
        else:
            inserts.append(row)
    return MergePlan(
        inserts=tuple(inserts),
        updates=tuple(updates),
        skipped=tuple(skipped),
        summary_by_uid=summary_by_uid,
        purge_other_rounds=(),
    )


def _write_summary_row(
    client: TencentSheetV3Client,
    *,
    sheet_id: str,
    row_index: int,
    uid_col: str,
    name_col: str,
    join_date_col: str,
    count_col: str | None,
    uid: str,
    name: str,
    count: int,
    join_date: str,
) -> None:
    left, right, cells = build_summary_row_cells(
        uid=uid,
        name=name,
        count=count,
        join_date=join_date,
        uid_col=uid_col,
        name_col=name_col,
        join_date_col=join_date_col,
        count_col=count_col,
    )
    client.update_values(sheet_id, f"{left}{row_index}:{right}{row_index}", [cells])


def _append_summary_rows(
    client: TencentSheetV3Client,
    *,
    sheet_id: str,
    start_row: int,
    uid_col: str,
    name_col: str,
    join_date_col: str,
    join_date: str,
    count_col: str | None,
    rows: list[TempBlacklistRow],
) -> None:
    if not rows:
        return
    end_row = start_row + len(rows) - 1
    sample_left, sample_right, _ = build_summary_row_cells(
        uid=rows[0].uid,
        name=rows[0].name,
        count=1,
        join_date=join_date,
        uid_col=uid_col,
        name_col=name_col,
        join_date_col=join_date_col,
        count_col=count_col,
    )
    values: list[list[str]] = []
    for row in rows:
        _, _, cells = build_summary_row_cells(
            uid=row.uid,
            name=row.name,
            count=1,
            join_date=join_date,
            uid_col=uid_col,
            name_col=name_col,
            join_date_col=join_date_col,
            count_col=count_col,
        )
        values.append(cells)
    client.update_values(
        sheet_id, f"{sample_left}{start_row}:{sample_right}{end_row}", values
    )


def _load_temp_classification(
    client: TencentSheetV3Client | None,
    *,
    temp_tab: str,
    temp_read_range: str,
    temp_blob: bytes | None,
    sync_round_no: int,
    max_sync_bid: int,
    timeout: float,
) -> tuple[
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    list[TempBlacklistRow],
    str,
]:
    """返回 (sync, purge, ignored_no_game, ignored_other, data_source)。"""
    if client is not None:
        try:
            first_row, _, grid = client.get_range_grid(temp_tab, temp_read_range)
            parsed = parse_temp_rows_from_grid(grid, first_row_index=first_row)
            sync_rows, purge_rows, no_game, other = classify_temp_rows(
                parsed,
                sync_round_no=sync_round_no,
                max_sync_bid=max_sync_bid,
            )
            return sync_rows, purge_rows, no_game, other, "openapi-v3"
        except Exception as exc:
            raise RuntimeError(f"V3 读取临时表失败: {exc}") from exc
    if temp_blob is None:
        raise RuntimeError("未配置 Open API 且未提供 dop-api 数据块")
    sync_rows, purge_rows, ignored = classify_temp_sheet_rows(
        temp_blob, sync_round_no=sync_round_no, max_sync_bid=max_sync_bid
    )
    return sync_rows, purge_rows, [], ignored, "dop-api"


def _load_summary_rows(
    client: TencentSheetV3Client | None,
    *,
    summary_tab: str,
    summary_read_range: str,
    summary_blob: bytes | None,
) -> list[SummaryBlacklistRow]:
    if client is not None:
        first_row, _, grid = client.get_range_grid(summary_tab, summary_read_range)
        return parse_summary_rows_from_grid(grid, first_row_index=first_row)
    if summary_blob is None:
        return []
    return parse_summary_blacklist_rows_from_sheet_blob(summary_blob)


# 兼容旧名称
TencentSheetOpenClient = TencentSheetV3Client


def _clear_temp_rows_on_sheet(
    client: TencentSheetV3Client,
    *,
    sheet_id: str,
    row_indices: list[int],
    col_range: str,
    delete_mode: str,
) -> list[int]:
    """清空或删除临时表指定行；返回失败行号。"""
    if not row_indices:
        return []
    if delete_mode == "delete":
        failed = client.delete_rows(sheet_id=sheet_id, row_indices=row_indices)
        if failed:
            client.clear_temp_rows(
                sheet_id=sheet_id,
                row_indices=failed,
                col_range=col_range,
            )
        return failed
    return client.clear_temp_rows(
        sheet_id=sheet_id,
        row_indices=row_indices,
        col_range=col_range,
    )


def resolve_openapi_access_token(
    api: dict[str, Any] | None,
    *,
    environ: dict[str, str] | None = None,
) -> str:
    """
    从环境变量解析 Open API ``access_token``（不读取 config 明文）。

    变量名：``openapi.access_token_env``，默认 ``BIDKING_TENCENT_DOCS_ACCESS_TOKEN``。
    """
    env = os.environ if environ is None else environ
    branch = api if isinstance(api, dict) else {}
    var_name = str(
        branch.get("access_token_env") or _DEFAULT_ACCESS_TOKEN_ENV
    ).strip()
    if not var_name:
        return ""
    return str(env.get(var_name) or "").strip()


def _open_client_from_config(
    cfg: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> TencentSheetV3Client | None:
    file_id = str(cfg.get("book_id") or "").strip()
    api = cfg.get("openapi")
    if not isinstance(api, dict):
        return None
    client_id = str(api.get("client_id") or "").strip()
    open_id = str(api.get("open_id") or "").strip()
    access_token = resolve_openapi_access_token(api)
    if not all((file_id, client_id, open_id, access_token)):
        return None
    return TencentSheetV3Client(
        file_id=file_id,
        client_id=client_id,
        open_id=open_id,
        access_token=access_token,
        timeout=timeout,
    )


def sync_temp_blacklist_to_summary_sheet(
    config: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
    timeout: float = 25.0,
    delete_mode: str = "clear",
    sync_on: date | datetime | None = None,
) -> tuple[bool, str, MergePlan | None]:
    """
    拉取临时表第一回合（有局号、出价未超阈值）→ 合并汇总表 → 清理临时表。

    仅 D 列回合为 ``sync_round_no``（默认 1）且 A 列含 ``地图ID:局号`` 的行写入汇总。
    回合 > 1 或出价超 ``max_sync_bid`` 且有局号的行只删临时表、不写汇总。
    无局号行不汇总也不删。新 UID 次数 ``1``；已有 UID 次数 ``+1``。
    ``delete_mode``: ``clear``（默认）或 ``delete``。须配置 Open API V3 凭证；无 token 时仅用 dop-api 预览。
    """
    cfg = resolve_blacklist_sheet_merge_source(config)
    sheet_id = cfg["sheet_id"]
    temp_tab = cfg["temp_tab"]
    summary_tab = cfg["summary_tab"]
    col_range = cfg["temp_clear_range_cols"]
    temp_read_range = str(cfg.get("temp_read_range") or _DEFAULT_TEMP_READ_RANGE)
    summary_read_range = str(
        cfg.get("summary_read_range") or _DEFAULT_SUMMARY_READ_RANGE
    )
    join_date = format_sync_join_date(
        sync_on, fmt=str(cfg.get("join_date_format") or _DEFAULT_JOIN_DATE_FORMAT)
    )
    client = _open_client_from_config(cfg, timeout=timeout)
    sync_round_no = int(cfg.get("sync_round_no") or _DEFAULT_SYNC_ROUND_NO)
    max_sync_bid = int(cfg.get("max_sync_bid") or _DEFAULT_MAX_SYNC_BID)
    temp_blob: bytes | None = None
    summary_blob: bytes | None = None
    if client is None:
        try:
            temp_blob = _fetch_sheet_chunk_blob(
                sheet_id=sheet_id, tab=temp_tab, timeout=timeout
            )
            summary_blob = _fetch_sheet_chunk_blob(
                sheet_id=sheet_id, tab=summary_tab, timeout=timeout
            )
        except Exception as exc:
            return False, f"拉取腾讯文档失败: {exc}", None
    try:
        temp_rows, purge_temp_rows, ignored_no_game, ignored_other, data_source = (
            _load_temp_classification(
                client,
                temp_tab=temp_tab,
                temp_read_range=temp_read_range,
                temp_blob=temp_blob,
                sync_round_no=sync_round_no,
                max_sync_bid=max_sync_bid,
                timeout=timeout,
            )
        )
        summary_rows = _load_summary_rows(
            client,
            summary_tab=summary_tab,
            summary_read_range=summary_read_range,
            summary_blob=summary_blob,
        )
    except Exception as exc:
        return False, str(exc), None
    plan = build_merge_plan(temp_rows, summary_rows)
    plan = MergePlan(
        inserts=plan.inserts,
        updates=plan.updates,
        skipped=plan.skipped,
        summary_by_uid=plan.summary_by_uid,
        purge_other_rounds=tuple(purge_temp_rows),
    )
    synced_temp = list(plan.inserts) + list(plan.updates)
    purge_rows = list(plan.purge_other_rounds)

    if dry_run or client is None:
        source_note = (
            "Open API V3"
            if data_source == "openapi-v3"
            else "dop-api（缺 round/bid 时无法准确分类，请配置 token）"
        )
        lines = [
            f"[预览/{source_note}] 第一回合：新增 {len(plan.inserts)}，"
            f"更新 {len(plan.updates)}，跳过 {len(plan.skipped)}；"
            f"将清理临时表 {len(purge_rows)} 行（非第一回合或出价>{max_sync_bid}）",
        ]
        if ignored_no_game:
            lines.append(f"；无局号忽略 {len(ignored_no_game)} 行")
        if ignored_other:
            lines.append(f"；其它忽略 {len(ignored_other)} 行（多为缺回合列）")
        for row in purge_rows[:8]:
            bid_note = f" 出价={row.bid}" if row.bid is not None else ""
            lines.append(
                f"  [删] 行{row.row_index}: {row.game_uid} {row.uid} {row.name}{bid_note}"
            )
        if len(purge_rows) > 8:
            lines.append(f"  … 另有 {len(purge_rows) - 8} 行待清理")
        for row in plan.inserts[:12]:
            bid_note = f" 出价={row.bid}" if row.bid is not None else ""
            lines.append(
                f"  [新] 行{row.row_index}: {row.uid} {row.name}{bid_note} "
                f"次数=1 加入日期={join_date}"
            )
        for row in plan.updates[:12]:
            prev = plan.summary_by_uid.get(row.uid)
            prev_n = prev.count if prev else 0
            bid_note = f" 出价={row.bid}" if row.bid is not None else ""
            lines.append(
                f"  [更] 行{row.row_index}: {row.uid} {row.name}{bid_note} "
                f"次数={prev_n + 1} 加入日期={join_date}"
            )
        if len(synced_temp) > 24:
            lines.append(f"  … 另有 {len(synced_temp) - 24} 行")
        if client is None:
            env_name = _DEFAULT_ACCESS_TOKEN_ENV
            api = cfg.get("openapi")
            if isinstance(api, dict) and api.get("access_token_env"):
                env_name = str(api["access_token_env"]).strip()
            lines.append(
                "未配置 Open API V3（book_id、openapi.client_id/open_id、"
                f"环境变量 {env_name}），未写入文档。"
                "说明见 docs/tencent_sheet_openapi_v3.md"
            )
        if not synced_temp and not purge_rows:
            if ignored_no_game or ignored_other:
                parts = ["无待同步/清理行"]
                if ignored_no_game:
                    parts.append(f"无局号 {len(ignored_no_game)} 行")
                if ignored_other:
                    parts.append(f"其它 {len(ignored_other)} 行")
                return True, "；".join(parts), plan
            return True, "无待同步行且无需清理的临时数据", plan
        return True, "\n".join(lines), plan

    count_col = str(cfg.get("summary_count_col") or "").strip().upper() or None
    uid_col = cfg["summary_uid_col"]
    name_col = cfg["summary_name_col"]
    join_date_col = cfg["summary_join_date_col"]
    max_summary_row = max(
        (r.row_index for r in plan.summary_by_uid.values()),
        default=1,
    )
    start_row = max_summary_row + 1
    failed: list[int] = []
    purge_failed: list[int] = []
    try:
        if purge_rows:
            purge_failed = _clear_temp_rows_on_sheet(
                client,
                sheet_id=temp_tab,
                row_indices=[r.row_index for r in purge_rows],
                col_range=col_range,
                delete_mode=delete_mode,
            )
        for row in plan.updates:
            prev = plan.summary_by_uid[row.uid]
            name = row.name.strip() or prev.name
            current = client.read_count_at_row(
                sheet_id=summary_tab,
                row_index=prev.row_index,
                count_col=count_col or _DEFAULT_SUMMARY_COUNT_COL,
                fallback=prev.count,
                parse_count=parse_count_cell,
            )
            _write_summary_row(
                client,
                sheet_id=summary_tab,
                row_index=prev.row_index,
                uid_col=uid_col,
                name_col=name_col,
                join_date_col=join_date_col,
                count_col=count_col,
                uid=row.uid,
                name=name,
                count=current + 1,
                join_date=join_date,
            )
        if plan.inserts:
            _append_summary_rows(
                client,
                sheet_id=summary_tab,
                start_row=start_row,
                uid_col=uid_col,
                name_col=name_col,
                join_date_col=join_date_col,
                join_date=join_date,
                count_col=count_col,
                rows=list(plan.inserts),
            )
        if synced_temp:
            failed = _clear_temp_rows_on_sheet(
                client,
                sheet_id=temp_tab,
                row_indices=[r.row_index for r in synced_temp],
                col_range=col_range,
                delete_mode=delete_mode,
            )
    except Exception as exc:
        return False, f"写入腾讯文档失败: {exc}", plan

    parts: list[str] = []
    if synced_temp:
        parts.append(
            f"已同步第一回合 {len(synced_temp)} 行（新增 {len(plan.inserts)}，"
            f"更新 {len(plan.updates)}，加入日期 {join_date}），"
            f"跳过 {len(plan.skipped)} 行"
        )
        if failed:
            parts.append(
                f"；已同步行清理失败 {len(failed)} 行: {failed}"
            )
        else:
            parts.append(f"；已清理已同步临时行 {len(synced_temp)} 行")
    elif plan.skipped or purge_rows:
        parts.append(
            f"无第一回合可同步（跳过 {len(plan.skipped)}）"
        )
    if ignored_no_game:
        parts.append(f"；无局号忽略 {len(ignored_no_game)} 行")
    if ignored_other:
        parts.append(f"；其它忽略 {len(ignored_other)} 行")
    if purge_rows:
        n_purged = len(purge_rows) - len(purge_failed)
        parts.append(
            f"；已清理临时表 {n_purged} 行（非第一回合或出价>{max_sync_bid}）"
        )
        if purge_failed:
            parts.append(f"（失败 {len(purge_failed)} 行: {purge_failed}）")
    note = "".join(parts) if parts else "无操作"
    return True, note, plan
