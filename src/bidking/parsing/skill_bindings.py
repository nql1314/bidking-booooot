# -*- coding: utf-8 -*-
"""技能表导出的绑定：日志 SkillCid / ItemCid → ``event_stats`` 与 UI 用映射。

由 :data:`SKILL_EXPORT_BY_ID` 与少量固定 ID 规则派生；行分组与
:mod:`bidking.parsing.skill_export_generated` 中「地图竞拍 / 英雄 / 道具效果」子表一致。
更新 ``Skill_export.csv`` 后请运行 ``python build/generate_skill_export_table.py`` 并保证本模块逻辑仍覆盖新行。
"""

from __future__ import annotations

import ast
import csv
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .skill_export_generated import SKILL_EXPORT_BY_ID, SkillExportRow

# 与 :data:`bidking.parsing.constants.ITEM_TOOLS` 首元一致（避免 constants ↔ skill_bindings 循环导入）
_ITEM_SKILL_CANONICAL_SKILL_CID: Dict[int, int] = {
    100151: 2001,
    100152: 2002,
    100153: 2003,
    100154: 2004,
    100155: 2005,
    100156: 2006,
    100157: 2007,
    100158: 2008,
    100159: 2009,
    100160: 2010,
}

Tuple3I = Tuple[str, int, str]
Tuple3F = Tuple[str, int, str]
Tuple3P = Tuple[int, str, str]


def _parse_list(s: str) -> Any:
    t = (s or "").strip()
    if not t:
        return []
    try:
        return ast.literal_eval(t)
    except (SyntaxError, ValueError):
        return []


def _codes(row: SkillExportRow) -> Set[int]:
    v = _parse_list(row.param_16)
    if isinstance(v, list):
        return {int(x) for x in v if isinstance(x, (int, float))}
    return set()


def _qualities(row: SkillExportRow) -> Tuple[int, ...]:
    v = _parse_list(row.param_09)
    if not isinstance(v, list):
        return ()
    out: List[int] = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _skill_int_field(row: SkillExportRow) -> int:
    try:
        return int(row.skill_id)
    except (TypeError, ValueError):
        return 0


def _item_cid_from_item_name_key(key: str) -> Optional[int]:
    m = re.match(r"itemName_(\d+)$", (key or "").strip())
    if not m:
        return None
    return int(m.group(1))


def _is_map_auction_board_row(row: SkillExportRow) -> bool:
    """地图竞拍信息行（与 :func:`bidking.parsing.skill_export_generated._skill_export_part_map_auction_board` 一致）。

    具体 skill_id：200001–200052（连续 52 条）；本谓词仅用 ``param_07==1`` 判定。
    """
    return (row.param_07 or "").strip() == "1"


def _is_hero_equipped_skill_row(row: SkillExportRow) -> bool:
    """英雄携带技能行（与 ``_skill_export_part_hero_skills`` 并集一致）。

    具体 skill_id（共 63 条）：100101, 1001011, 1001012, 1001013, 1001014, 100102,
    1001031, 1001032, 1001033, 1001034, 1001041, 1001042, 1001043, 1001044, 1001045,
    100105, 100106, 1001061, 100107, 1001071, 1001072, 1001073, 1001074, 100108,
    10010801, 100109, 1001091, 1001092, 1001093, 1001094, 100110, 1001101, 100201,
    100202, 1002021, 1002022, 1002023, 1002024, 100203, 10002031, 100204, 1002041,
    1002042, 1002043, 1002044, 100205, 100206, 1002061, 1002062, 1002063, 1002064,
    1002065, 100207, 10002071, 10002072, 10002073, 1002081, 1002082, 1002083,
    1002084, 1002085, 100209, 100301。
    本谓词用 ``param_07==0`` 且 ``item_name_key`` 前缀 ``hero_skill_`` 判定。
    """
    return (row.param_07 or "").strip() == "0" and (row.item_name_key or "").startswith("hero_skill_")


def _is_item_tool_skill_row(row: SkillExportRow) -> bool:
    """道具工具行且带 ``itemName_<ItemCid>``（与各 ``_skill_export_part_item_*`` 并集一致）。

    具体 skill_id（共 65 条，道具表内 ``param_07=2`` 且 ``itemName_*`` 技能）：
    100, 103, 106, 200, 201, 202, 203, 204, 205, 300, 301, 302, 303, 304, 305, 400,
    401, 402, 403, 404, 405, 500, 501, 502, 503, 504, 505, 600, 601, 602, 603, 604,
    605, 606, 700, 701, 702, 703, 704, 705, 706, 801, 2001, 2002, 2003, 2004, 2005,
    2006, 2007, 2008, 2009, 2010, 10000, 10001, 10002, 10003, 10010, 10011, 10012,
    10013, 10014, 10015, 10016, 10017, 10018。
    """
    if (row.param_07 or "").strip() != "2":
        return False
    return _item_cid_from_item_name_key(row.item_name_key) is not None


def _iter_map_auction_board_rows() -> Iterable[SkillExportRow]:
    """产出全部地图竞拍行（skill_id 与上表 ``_is_map_auction_board_row`` 一致）。"""
    for row in SKILL_EXPORT_BY_ID.values():
        if _is_map_auction_board_row(row):
            yield row


def _iter_hero_skill_rows() -> Iterable[SkillExportRow]:
    """产出全部英雄技能行（skill_id 与上表 ``_is_hero_equipped_skill_row`` 一致）。"""
    for row in SKILL_EXPORT_BY_ID.values():
        if _is_hero_equipped_skill_row(row):
            yield row


def _iter_item_tool_skill_rows() -> Iterable[SkillExportRow]:
    """产出全部道具工具 ``itemName_*`` 技能行（skill_id 与上表 ``_is_item_tool_skill_row`` 一致）。"""
    for row in SKILL_EXPORT_BY_ID.values():
        if _is_item_tool_skill_row(row):
            yield row


def _iter_other_skill_direct_rows() -> Iterable[SkillExportRow]:
    """param_07 为 0/1/2 且可走 ``_scan_row_skill_direct_pricing``、但不属于地图/英雄/道具工具行时的兜底。

    当前 Skill_export 并集下通常为空；若 CSV 新增 ``param_07`` 为 0、1 或 2 且不符合上述三类的行，由此迭代器纳入直读绑定扫描。
    """
    for row in SKILL_EXPORT_BY_ID.values():
        if _scan_row_skill_direct_pricing(row) is None:
            continue
        if _is_map_auction_board_row(row) or _is_hero_equipped_skill_row(row) or _is_item_tool_skill_row(row):
            continue
        yield row


def _event_key_from_qualities_grid_series(
    qs: Tuple[int, ...], *, tail: str
) -> Optional[str]:
    """``param_09`` 品质列表 → 与格子相关的统计键（``total_*`` / ``q12_*`` / ``q{n}_*``）。

    ``tail`` 为 ``\"grid_count\"`` 或 ``\"grid_avg\"`` 等同构后缀；格数与均价共用同一套分档规则。
    """
    if not qs or qs == (0,):
        return f"total_{tail}"
    if set(qs) <= {1, 2} and len(qs) >= 1:
        return f"q12_{tail}"
    if len(qs) == 1 and 1 <= qs[0] <= 6:
        return f"q{qs[0]}_{tail}"
    return None


def _event_key_from_qualities_hit_item_count(qs: Tuple[int, ...]) -> Optional[str]:
    """``param_09`` → 命中件数类 ``*_count``（q12 需至少两档以区分于单档）。"""
    if not qs or qs == (0,):
        return "total_count"
    if set(qs) <= {1, 2} and len(qs) >= 2:
        return "q12_count"
    if len(qs) == 1 and 1 <= qs[0] <= 6:
        return f"q{qs[0]}_count"
    return None


def _event_key_from_qualities_item_price_total(qs: Tuple[int, ...]) -> Optional[str]:
    """``param_09`` → 道具总价 ``*_price_total``（空档不汇总到 total）。"""
    if not qs or qs == (0,):
        return None
    if set(qs) <= {1, 2} and len(qs) >= 1:
        return "q12_price_total"
    if len(qs) == 1 and 3 <= qs[0] <= 6:
        return f"q{qs[0]}_price_total"
    return None


def _scan_row_skill_direct_pricing(
    row: SkillExportRow,
) -> Optional[Tuple[int, Set[int], Tuple[int, ...]]]:
    """地图/通用技能直读行：``param_07`` 为 0/1/2 且 ``skill_id`` 有效。返回 ``(sid, codes, qs)``。"""
    p7 = (row.param_07 or "").strip()
    if p7 not in {"0", "1", "2"}:
        return None
    sid = _skill_int_field(row)
    if sid <= 0:
        return None
    return sid, _codes(row), _qualities(row)


def _scan_row_item_tool_pricing(
    row: SkillExportRow,
) -> Optional[Tuple[int, Set[int], Tuple[int, ...]]]:
    """道具技能行：``param_07==2`` 且能解析出道具 ``ItemCid``。返回 ``(iid, codes, qs)``。"""
    if (row.param_07 or "").strip() != "2":
        return None
    iid = _item_cid_from_item_name_key(row.item_name_key)
    if iid is None:
        return None
    return iid, _codes(row), _qualities(row)


def _binding_skill_int_hidden_cell_grid_count(row: SkillExportRow) -> Optional[Tuple3I]:
    """事件：未揭示格数（``2000`` 且非总价/随机价等）→ ``TotalHitBoxIndex``。"""
    scanned = _scan_row_skill_direct_pricing(row)
    if scanned is None:
        return None
    sid, codes, qs = scanned
    if not (2000 in codes and 10000 not in codes and 8000 not in codes and 9000 not in codes):
        return None
    key = _event_key_from_qualities_grid_series(qs, tail="grid_count")
    if not key:
        return None
    return key, sid, "TotalHitBoxIndex"


def _binding_skill_int_hit_item_count(row: SkillExportRow) -> Optional[Tuple3I]:
    """事件：命中件数（``4000``）→ ``HitItemIndex``。"""
    scanned = _scan_row_skill_direct_pricing(row)
    if scanned is None:
        return None
    sid, codes, qs = scanned
    if 4000 not in codes:
        return None
    key = _event_key_from_qualities_hit_item_count(qs)
    if not key:
        return None
    return key, sid, "HitItemIndex"


def _binding_skill_float_grid_cell_avg_index(row: SkillExportRow) -> Optional[Tuple3F]:
    """事件：格子均价索引（``3000``）→ ``AllHitItemAvgBoxIndex``。"""
    scanned = _scan_row_skill_direct_pricing(row)
    if scanned is None:
        return None
    sid, codes, qs = scanned
    if 3000 not in codes:
        return None
    key = _event_key_from_qualities_grid_series(qs, tail="grid_avg")
    if not key:
        return None
    return key, sid, "AllHitItemAvgBoxIndex"


def _binding_item_int_hidden_cell_grid_count(row: SkillExportRow) -> Optional[Tuple3I]:
    """道具事件：未揭示格数（无 ``10000``/``8000`` 干扰）。"""
    scanned = _scan_row_item_tool_pricing(row)
    if scanned is None:
        return None
    iid, codes, qs = scanned
    if not (2000 in codes and 10000 not in codes and 8000 not in codes):
        return None
    key = _event_key_from_qualities_grid_series(qs, tail="grid_count")
    if not key:
        return None
    return key, iid, "TotalHitBoxIndex"


def _binding_item_int_hit_item_count(row: SkillExportRow) -> Optional[Tuple3I]:
    """道具事件：命中件数。"""
    scanned = _scan_row_item_tool_pricing(row)
    if scanned is None:
        return None
    iid, codes, qs = scanned
    if 4000 not in codes:
        return None
    key = _event_key_from_qualities_hit_item_count(qs)
    if not key:
        return None
    return key, iid, "HitItemIndex"


def _binding_item_int_hit_item_price_total(row: SkillExportRow) -> Optional[Tuple3I]:
    """道具事件：命中总价（``10000``）。"""
    scanned = _scan_row_item_tool_pricing(row)
    if scanned is None:
        return None
    iid, codes, qs = scanned
    if 10000 not in codes:
        return None
    key = _event_key_from_qualities_item_price_total(qs)
    if not key:
        return None
    return key, iid, "HitItemTotalPrice"


def _item_tool_event_stat_keys_for_row(row: SkillExportRow) -> List[str]:
    """道具技能行在 ``event_stats`` 中出现的键（与直读整型绑定一致，仅收集键名）。"""
    keys: List[str] = []
    for fn in (
        _binding_item_int_hidden_cell_grid_count,
        _binding_item_int_hit_item_count,
        _binding_item_int_hit_item_price_total,
    ):
        t = fn(row)
        if t is not None:
            keys.append(t[0])
    return keys


def _prefer_row_for_event_key(
    existing: SkillExportRow | None, candidate: SkillExportRow
) -> SkillExportRow:
    """同一 ``event_stats`` 键多条技能时：优先 ``param_07=1`` 竞拍信息，其次更高 ``skill_id``。"""
    if existing is None:
        return candidate
    e1 = (existing.param_07 or "").strip() == "1"
    c1 = (candidate.param_07 or "").strip() == "1"
    if c1 and not e1:
        return candidate
    if e1 and not c1:
        return existing
    try:
        return candidate if int(candidate.skill_id) > int(existing.skill_id) else existing
    except (TypeError, ValueError):
        return candidate


def _dedupe_int_bindings(rows: List[Tuple3I], sid_to_row: Dict[int, SkillExportRow]) -> List[Tuple3I]:
    best_row: Dict[str, SkillExportRow] = {}
    best_t: Dict[str, Tuple3I] = {}
    for t in rows:
        ev, sid, field = t
        row = sid_to_row.get(sid)
        if row is None:
            continue
        if ev not in best_row:
            best_row[ev] = row
            best_t[ev] = t
            continue
        chosen = _prefer_row_for_event_key(best_row[ev], row)
        if chosen is row:
            best_row[ev] = row
            best_t[ev] = t
    return [best_t[k] for k in sorted(best_t.keys())]


def _dedupe_float_bindings(rows: List[Tuple3F], sid_to_row: Dict[int, SkillExportRow]) -> List[Tuple3F]:
    best_row: Dict[str, SkillExportRow] = {}
    best_t: Dict[str, Tuple3F] = {}
    for t in rows:
        ev, sid, field = t
        row = sid_to_row.get(sid)
        if row is None:
            continue
        if ev not in best_row:
            best_row[ev] = row
            best_t[ev] = t
            continue
        chosen = _prefer_row_for_event_key(best_row[ev], row)
        if chosen is row:
            best_row[ev] = row
            best_t[ev] = t
    return [best_t[k] for k in sorted(best_t.keys())]


def _collect_skill_int_bindings_from_rows(
    rows: Iterable[SkillExportRow], seen: Set[Tuple[str, int, str]], out: List[Tuple3I]
) -> None:
    """底层：对给定行集合尝试「未揭示格数 / 命中件数」整型直读事件。"""
    for row in rows:
        for t in (
            _binding_skill_int_hidden_cell_grid_count(row),
            _binding_skill_int_hit_item_count(row),
        ):
            if t is None or t in seen:
                continue
            seen.add(t)
            out.append(t)


def _collect_skill_float_bindings_from_rows(
    rows: Iterable[SkillExportRow], seen: Set[Tuple[str, int, str]], out: List[Tuple3F]
) -> None:
    """底层：对给定行集合尝试「格子均价索引」浮点直读事件。"""
    for row in rows:
        t = _binding_skill_float_grid_cell_avg_index(row)
        if t is None or t in seen:
            continue
        seen.add(t)
        out.append(t)


def _build_direct_skill_int_from_map_auction_board() -> List[Tuple3I]:
    """地图竞拍信息：整型直读（未揭示格数、命中件数）。

    扫描 skill_id：200001–200052（与 ``_iter_map_auction_board_rows`` 一致）。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_int_bindings_from_rows(_iter_map_auction_board_rows(), seen, out)
    return out


def _build_direct_skill_int_from_hero_skills() -> List[Tuple3I]:
    """英雄技能：整型直读（格数、件数等，与地图共用绑定规则）。

    扫描 skill_id：与 ``_iter_hero_skill_rows`` / ``_is_hero_equipped_skill_row`` 所列 63 条一致。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_int_bindings_from_rows(_iter_hero_skill_rows(), seen, out)
    return out


def _build_direct_skill_int_from_item_tool_skill_rows() -> List[Tuple3I]:
    """道具工具（param_07=2 且 itemName_*）：以 ``SkillCid`` 暴露的整型直读（若表中有）。

    扫描 skill_id：与 ``_iter_item_tool_skill_rows`` 所列 65 条一致。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_int_bindings_from_rows(_iter_item_tool_skill_rows(), seen, out)
    return out


def _build_direct_skill_int_from_other_skill_rows() -> List[Tuple3I]:
    """兜底：其余可走直读扫描的技能行。"""
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_int_bindings_from_rows(_iter_other_skill_direct_rows(), seen, out)
    return out


def _merge_skill_int_binding_lists(parts: List[List[Tuple3I]]) -> List[Tuple3I]:
    """合并多段绑定列表并按键去重（保留首次出现顺序）。"""
    seen: Set[Tuple[str, int, str]] = set()
    out: List[Tuple3I] = []
    for part in parts:
        for t in part:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def _build_direct_skill_int() -> List[Tuple3I]:
    """整型直读：按「地图竞拍 / 英雄 / 道具技能行 / 兜底」依次收集后，再按 ``event_stats`` 键做技能级去重。"""
    combined = _merge_skill_int_binding_lists(
        [
            _build_direct_skill_int_from_map_auction_board(),
            _build_direct_skill_int_from_hero_skills(),
            _build_direct_skill_int_from_item_tool_skill_rows(),
            _build_direct_skill_int_from_other_skill_rows(),
        ]
    )
    sid_to_row = {int(r.skill_id): r for r in SKILL_EXPORT_BY_ID.values()}
    return _dedupe_int_bindings(combined, sid_to_row)


def _build_direct_skill_float_from_map_auction_board() -> List[Tuple3F]:
    """地图竞拍信息：浮点直读（格子均价索引）。

    扫描 skill_id：200001–200052。
    """
    out: List[Tuple3F] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_float_bindings_from_rows(_iter_map_auction_board_rows(), seen, out)
    return out


def _build_direct_skill_float_from_hero_skills() -> List[Tuple3F]:
    """英雄技能：浮点直读（均格索引）。

    扫描 skill_id：与英雄 63 条一致（见 ``_is_hero_equipped_skill_row`` 文档）。
    """
    out: List[Tuple3F] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_float_bindings_from_rows(_iter_hero_skill_rows(), seen, out)
    return out


def _build_direct_skill_float_from_item_tool_skill_rows() -> List[Tuple3F]:
    """道具工具技能行：浮点直读（若有）。

    扫描 skill_id：与道具 ``itemName_*`` 65 条一致。
    """
    out: List[Tuple3F] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_float_bindings_from_rows(_iter_item_tool_skill_rows(), seen, out)
    return out


def _build_direct_skill_float_from_other_skill_rows() -> List[Tuple3F]:
    """兜底：其余技能行的浮点直读。"""
    out: List[Tuple3F] = []
    seen: Set[Tuple[str, int, str]] = set()
    _collect_skill_float_bindings_from_rows(_iter_other_skill_direct_rows(), seen, out)
    return out


def _merge_skill_float_binding_lists(parts: List[List[Tuple3F]]) -> List[Tuple3F]:
    seen: Set[Tuple[str, int, str]] = set()
    out: List[Tuple3F] = []
    for part in parts:
        for t in part:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def _build_direct_skill_float() -> List[Tuple3F]:
    """浮点直读：地图 / 英雄 / 道具技能行 / 兜底 合并后按事件键去重。"""
    combined = _merge_skill_float_binding_lists(
        [
            _build_direct_skill_float_from_map_auction_board(),
            _build_direct_skill_float_from_hero_skills(),
            _build_direct_skill_float_from_item_tool_skill_rows(),
            _build_direct_skill_float_from_other_skill_rows(),
        ]
    )
    sid_to_row = {int(r.skill_id): r for r in SKILL_EXPORT_BY_ID.values()}
    return _dedupe_float_bindings(combined, sid_to_row)


def _build_direct_item_int_from_hidden_cell_scan() -> List[Tuple3I]:
    """道具工具 · 仓储格数扫描：``TotalHitBoxIndex`` → ``*_grid_count``。

    产生绑定的 skill_id（与 generated 子组一致）：200, 201, 202, 203, 204, 205。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    for row in SKILL_EXPORT_BY_ID.values():
        t = _binding_item_int_hidden_cell_grid_count(row)
        if t is None or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _build_direct_item_int_from_hit_count_scan() -> List[Tuple3I]:
    """道具工具 · 件数清点：``HitItemIndex`` → ``*_count``。

    产生绑定的 skill_id：400, 401, 402, 403, 404, 405。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    for row in SKILL_EXPORT_BY_ID.values():
        t = _binding_item_int_hit_item_count(row)
        if t is None or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _build_direct_item_int_from_price_total_scan() -> List[Tuple3I]:
    """道具工具 · 分档总价：``HitItemTotalPrice`` → ``*_price_total``。

    产生绑定的 skill_id：500, 501, 502, 503, 504, 505。
    """
    out: List[Tuple3I] = []
    seen: Set[Tuple[str, int, str]] = set()
    for row in SKILL_EXPORT_BY_ID.values():
        t = _binding_item_int_hit_item_price_total(row)
        if t is None or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _build_direct_item_int() -> List[Tuple3I]:
    """道具直读整型：格数扫描 / 件数 / 总价 三类效果合并。"""
    return _merge_skill_int_binding_lists(
        [
            _build_direct_item_int_from_hidden_cell_scan(),
            _build_direct_item_int_from_hit_count_scan(),
            _build_direct_item_int_from_price_total_scan(),
        ]
    )


def _build_direct_item_float() -> List[Tuple3F]:
    return []


def _build_skill_log_price_avg() -> List[Tuple3P]:
    """日志侧固定映射：地图竞拍紫/金/红均价（``AllHitItemAvgPrice``）。

    具体 skill_id：200036（紫）、200037（金）、200038（红）。
    """
    return [
        (200036, "AllHitItemAvgPrice", "q4_price_avg"),
        (200037, "AllHitItemAvgPrice", "q5_price_avg"),
        (200038, "AllHitItemAvgPrice", "q6_price_avg"),
    ]


def _build_skill_log_price_total() -> List[Tuple3P]:
    """日志侧固定映射：道具优品/极品/珍品估价总价行（``HitItemTotalPrice``）。

    具体 skill_id（道具表）：503, 504, 505。
    """
    return [
        (503, "HitItemTotalPrice", "q4_price_total"),
        (504, "HitItemTotalPrice", "q5_price_total"),
        (505, "HitItemTotalPrice", "q6_price_total"),
    ]


def _build_hero_skill_quality() -> Dict[int, int]:
    """英雄全图品质扫描：``param_09`` 为单一品质档位 1–6 的艾莎四形态。

    具体 skill_id：1001031, 1001032, 1001033, 1001034。
    """
    m: Dict[int, int] = {}
    for sid in (1001031, 1001032, 1001033, 1001034):
        r = SKILL_EXPORT_BY_ID.get(sid)
        if not r:
            continue
        qs = _qualities(r)
        if len(qs) == 1 and 1 <= qs[0] <= 6:
            m[sid] = int(qs[0])
    return m


def _build_map_skill_force_quality() -> Dict[int, int]:
    """竞拍信息中「轮廓+品质」且限定 ``SkillCid`` 的强制品质档（紫/金/红展示线）。

    具体 skill_id（仅当 ``param_16`` 解析为恰含 1000 与 7000、且 ``param_09`` 单档 1–6）：200001, 200002, 200003。
    """
    m: Dict[int, int] = {}
    for row in _iter_map_auction_board_rows():
        codes = _codes(row)
        if codes != {1000, 7000}:
            continue
        qs = _qualities(row)
        if len(qs) != 1 or not (1 <= qs[0] <= 6):
            continue
        sid = _skill_int_field(row)
        if sid in {200001, 200002, 200003}:
            m[sid] = int(qs[0])
    return m


def _build_outline_skill_quality() -> Dict[int, int]:
    """轮廓技能 ``SkillCid`` → 汇总到的品质档 ``1..6``（供 ``HitBoxList`` 写入对应 ``q*``）。

    仅当 ``param_16`` 解析结果**包含**轮廓标记 ``1000``、且 ``param_09`` 为**单一整数档位** ``1..6`` 时收录。
    ``param_09`` 为 ``[0]``、多元素、类别 tag 等行不会进入本表；若需轮廓分档统计请在 ``Skill_export.csv`` 中把 ``param_09`` 写成单档品质（如 ``[5]`` 代替 ``[0]`` + 旧 ``param_17``）。

    当前 Skill_export 并集下命中的 skill_id：200001, 200002, 200003, 1001031, 1001032, 1001033, 1001034（共 7 条；随 CSV 变化）。
    """
    m: Dict[int, int] = {}
    for row in SKILL_EXPORT_BY_ID.values():
        codes = _codes(row)
        if 1000 not in codes:
            continue
        if (row.param_08 or "").strip() == "1":
            continue
        qs = _qualities(row)
        if len(qs) != 1:
            continue
        q = int(qs[0])
        if not (1 <= q <= 6):
            continue
        sid = _skill_int_field(row)
        if sid:
            m[sid] = q
    return m


def _build_hero_merge_into_map() -> Dict[int, int]:
    """英雄 SkillCid → 与地图统计同构的规范 SkillCid（缺省为空，由日志自行带地图键）。"""
    return {}


def _build_map_skill_desc() -> Dict[int, str]:
    return {sid: row.name_zh for sid, row in SKILL_EXPORT_BY_ID.items()}


def _build_item_skill_desc() -> Dict[int, str]:
    d: Dict[int, str] = {}
    for row in SKILL_EXPORT_BY_ID.values():
        iid = _item_cid_from_item_name_key(row.item_name_key)
        if iid is None:
            continue
        if (row.param_07 or "").strip() != "2":
            continue
        d[iid] = row.name_zh
    return d


def _build_item_skill_event_stats() -> Dict[int, Tuple[str, ...]]:
    d: Dict[int, Tuple[str, ...]] = {}
    for row in SKILL_EXPORT_BY_ID.values():
        scanned = _scan_row_item_tool_pricing(row)
        if scanned is None:
            continue
        iid, _, _ = scanned
        keys = _item_tool_event_stat_keys_for_row(row)
        if keys:
            d[iid] = tuple(sorted(set(keys)))
    for iid in _build_item_skill_desc():
        d.setdefault(iid, ())
    return d


RAW_PRICING_DIRECT_SKILL_INT_BINDINGS: Tuple[Tuple3I, ...] = tuple(_build_direct_skill_int())
RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS: Tuple[Tuple3F, ...] = tuple(_build_direct_skill_float())
RAW_PRICING_DIRECT_ITEM_INT_BINDINGS: Tuple[Tuple3I, ...] = tuple(_build_direct_item_int())
RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS: Tuple[Tuple3F, ...] = tuple(_build_direct_item_float())
SKILL_LOG_PRICE_AVG_BINDINGS: Tuple[Tuple3P, ...] = tuple(_build_skill_log_price_avg())
SKILL_LOG_PRICE_TOTAL_BINDINGS: Tuple[Tuple3P, ...] = tuple(_build_skill_log_price_total())
HERO_SKILL_QUALITY: Dict[int, int] = _build_hero_skill_quality()
MAP_SKILL_FORCE_QUALITY: Dict[int, int] = _build_map_skill_force_quality()
OUTLINE_SKILL_QUALITY: Dict[int, int] = _build_outline_skill_quality()
HERO_SKILL_CID_MERGE_INTO_MAP: Dict[int, int] = _build_hero_merge_into_map()
ITEM_SKILL_CANONICAL_SKILL_CID: Dict[int, int] = dict(_ITEM_SKILL_CANONICAL_SKILL_CID)
MAP_SKILL_DESC: Dict[int, str] = _build_map_skill_desc()
ITEM_SKILL_DESC: Dict[int, str] = _build_item_skill_desc()
ITEM_SKILL_EVENT_STATS: Dict[int, Tuple[str, ...]] = _build_item_skill_event_stats()


def _skill_cid_for_int_stat(stat_key: str) -> int:
    """整型直读绑定中去重后的 ``SkillCid``（与 ``RAW_PRICING_DIRECT_SKILL_INT_BINDINGS`` 一致）。"""
    for key, sid, _ in RAW_PRICING_DIRECT_SKILL_INT_BINDINGS:
        if key == stat_key:
            return sid
    raise KeyError(f"RAW_PRICING_DIRECT_SKILL_INT_BINDINGS 无键 {stat_key!r}")


def _map_announce_random_avg_price_skill_by_hit_count() -> Dict[int, int]:
    """竞拍信息：``param_16`` 含 8000、``param_15`` 为默认命中件数的随机均价技能 ID。

    与 :data:`MAP_SKILL_RANDOM3_AVG_PRICE` 等一一对应（3/6/9/12）；同件数多行时取较大 ``skill_id``。

    当前表在地图竞拍行中命中的 skill_id：200031（param_15=3）、200032（6）、200033（9）、200034（12）。
    """
    d: Dict[int, int] = {}
    for row in _iter_map_auction_board_rows():
        if 8000 not in _codes(row):
            continue
        p15 = (row.param_15 or "").strip()
        if not p15.isdigit():
            continue
        n = int(p15)
        if n not in (3, 6, 9, 12):
            continue
        try:
            sid = int(row.skill_id)
        except (TypeError, ValueError):
            continue
        prev = d.get(n)
        if prev is None or sid > prev:
            d[n] = sid
    for n in (3, 6, 9, 12):
        if n not in d:
            raise RuntimeError(
                f"Skill_export 缺少竞拍信息(param_07=1)且 param_16 含 8000、param_15={n} 的随机均价技能"
            )
    return d


_rnd_avg_by_hit = _map_announce_random_avg_price_skill_by_hit_count()
MAP_SKILL_RANDOM3_AVG_PRICE: int = _rnd_avg_by_hit[3]
MAP_SKILL_RANDOM6_AVG_PRICE: int = _rnd_avg_by_hit[6]
MAP_SKILL_RANDOM9_AVG_PRICE: int = _rnd_avg_by_hit[9]
MAP_SKILL_RANDOM12_AVG_PRICE: int = _rnd_avg_by_hit[12]
MAP_SKILL_TOTAL_HIDDEN_CELLS: int = _skill_cid_for_int_stat("total_grid_count")
MAP_SKILL_TOTAL_GOLD_COUNT: int = _skill_cid_for_int_stat("q5_count")


def validate_skill_registry_vs_csv(csv_path: str) -> List[str]:
    """校验 CSV 与 :mod:`skill_export_generated` 中 ``param_16`` 等列一致。"""
    errs: List[str] = []
    path = csv_path
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("skill_id") or "").strip()
            if not sid or not sid.isdigit():
                continue
            exp16 = (row.get("param_16") or "").strip()
            got = SKILL_EXPORT_BY_ID.get(int(sid))
            if got is None:
                errs.append(f"skill_id={sid}: CSV 有行但 skill_export_generated 缺失")
                continue
            if (got.param_16 or "").strip() != exp16:
                errs.append(
                    f"skill_id={sid}: param_16 不一致 CSV={exp16!r} generated={(got.param_16 or '').strip()!r}"
                )
    return errs
