# -*- coding: utf-8 -*-
"""
画板快照定价：地图质量 CSV、空置三档（全金/金红/全红）、地图技能约束与艾莎 bid 元数据。

原逻辑与 ``bidking-bot/aisha_premium.compute_aisha_snapshot_bid_points`` 对齐，供 ``grid_view`` 写入
``board_snapshot.json`` 的 ``pricing`` 与 ``pricing["aisha_bid"]``；bot 侧仅消费快照字段。
"""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
from . import map_avg_csv as _map_avg_csv
from . import quality_stats as _quality_stats
from . import scan_inference as _scan_inference
from . import unknown_value as _unknown_value
from . import vacant as _vacant
from ..parsing.constants import (
    MAP_SKILL_AVG_GOLD_CELLS,
    MAP_SKILL_AVG_GOLD_PRICE,
    MAP_SKILL_AVG_RED_CELLS,
    MAP_SKILL_AVG_RED_PRICE,
    MAP_SKILL_GOLD_ITEM_COUNT,
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_RANDOM6_AVG_PRICE,
    MAP_SKILL_RANDOM9_AVG_PRICE,
    MAP_SKILL_RED_ITEM_COUNT,
    MAP_SKILL_TOTAL_GOLD_CELLS,
    MAP_SKILL_TOTAL_RED_CELLS,
)
GRID_COLS = 10
GRID_ROWS = 30
GRID_MAX_BOX_ID = GRID_COLS * GRID_ROWS - 1

_MS_RND_AVG = (
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_RANDOM6_AVG_PRICE,
    MAP_SKILL_RANDOM9_AVG_PRICE,
)

ITEM_PRICES_CSV_RELPATHS = (
    ("..", "..", "..", "data", "item_prices.csv"),
    ("..", "..", "data", "item_prices.csv"),
)

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None

def set_map_quality_csv_override(path: Optional[str]) -> None:
    """兼容入口，转发到 ``analysis.map_avg_csv``。"""
    _map_avg_csv.set_map_quality_csv_override(path)


def _merge_latest_map_skill_entries(skill_logs: List[dict]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for entry in gd.get("MapSkillLog") or []:
            if not isinstance(entry, dict):
                continue
            try:
                cid = int(entry.get("SkillCid") or 0)
            except (TypeError, ValueError):
                continue
            if cid:
                out[cid] = entry
    return out


def map_skill_total_hidden_cells_from_logs(skill_logs: List[dict]) -> Optional[int]:
    return _vacant.map_skill_total_hidden_cells_from_logs(skill_logs)


def vacant_cells_from_map_skill_total_hidden(
    skill_logs: List[dict],
    *,
    occupied_cell_count: int,
) -> Optional[int]:
    return _vacant.vacant_cells_from_map_skill_total_hidden(
        skill_logs, occupied_cell_count=occupied_cell_count
    )

def _shape_wh_from_snapshot(shape: Any) -> Tuple[int, int]:
    if shape is None:
        return 1, 1
    s = str(shape)
    if len(s) == 2:
        try:
            return int(s[0]), int(s[1])
        except ValueError:
            return 1, 1
    return 1, 1


def _item_occupied_cells(box_id: int, shape: Any) -> set:
    w, h = _shape_wh_from_snapshot(shape)
    col = box_id % GRID_COLS
    row = box_id // GRID_COLS
    cells: set = set()
    for dr in range(h):
        for dc in range(w):
            cells.add((row + dr, col + dc))
    return cells


def _early_round_vacant_metrics(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return _vacant.early_round_vacant_metrics(board_snapshot)


def _scam_span_vacant_deduction(board_snapshot: Dict[str, Any]) -> int:
    return _vacant.scam_span_vacant_deduction(board_snapshot)


def _sum_quality_footprint_cells(
    board_snapshot: Dict[str, Any],
    quality: int,
    *,
    csv_cells_raw: Optional[Dict[str, float]] = None,
    pricing: Optional[Dict[str, Any]] = None,
    map_id_normalized: Optional[int] = None,
) -> int:
    return _quality_stats.sum_quality_footprint_cells(
        board_snapshot,
        quality,
        csv_cells_raw=csv_cells_raw,
        pricing=pricing,
        map_id_normalized=map_id_normalized,
    )


def _count_quality_items_all(board_snapshot: Dict[str, Any], quality: int) -> int:
    return _quality_stats.count_quality_items_all(board_snapshot, quality)


def _quality_has_unconfirmed_contour(board_snapshot: Dict[str, Any], quality: int) -> bool:
    return _quality_stats.quality_has_unconfirmed_contour(board_snapshot, quality)


def _map_skill_gold_red_suppressed_for_ambiguous_contour(
    board_snapshot: Dict[str, Any],
) -> Tuple[bool, bool]:
    return (
        _quality_has_unconfirmed_contour(board_snapshot, 5),
        _quality_has_unconfirmed_contour(board_snapshot, 6),
    )


def map_skill_hidden_cell_reserve_from_snapshot(board_snapshot: Dict[str, Any]) -> int:
    """地图技能预留几何空置格（当前实现恒为 0）。"""
    _ = board_snapshot
    return 0


def map_id_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    gs = board_snapshot.get("game_state")
    mid = None
    if isinstance(gs, dict):
        mid = gs.get("map_id")
    if mid is None:
        mid = board_snapshot.get("map_id")
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None


def current_round_from_board_snapshot(board_snapshot: Dict[str, Any]) -> Optional[int]:
    r = board_snapshot.get("current_round")
    if r is None:
        r = (board_snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def _occupied_cells_item_board_display(it: Dict[str, Any], board_snapshot: Dict[str, Any]) -> set:
    """
    单件在画板上的占位格（与画板几何一致）：
    - 已知 ``shape``：日志轮廓；
    - 否则：BoxId 锚格 1×1（未知轮廓不再用推断扩充）。
    """
    _ = board_snapshot
    bid_raw = it.get("box_id")
    if bid_raw is None:
        return set()
    try:
        bid = int(bid_raw)
    except (TypeError, ValueError):
        return set()
    if it.get("shape") is not None:
        return _item_occupied_cells(bid, it.get("shape"))
    br = bid // GRID_COLS
    bc = bid % GRID_COLS
    return {(br, bc)}


def _board_display_occupied_cells_from_snapshot(board_snapshot: Dict[str, Any]) -> set:
    """
    与画板橘红空置区一致的占用并集；未确认物品仅合并锚格
    （``grid_view._build_occupied`` + ``_merge_unconfirmed_anchor_cells``）。
    """
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    if not isinstance(raw, dict):
        return set()
    occ: set = set()
    for it in raw.values():
        if not isinstance(it, dict) or it.get("box_id") is None:
            continue
        try:
            int(it["box_id"])
        except (TypeError, ValueError):
            continue
        if it.get("box_id_confirmed"):
            occ |= _occupied_cells_item_board_display(it, board_snapshot)
    for it in raw.values():
        if not isinstance(it, dict) or it.get("box_id") is None:
            continue
        try:
            bid = int(it["box_id"])
        except (TypeError, ValueError):
            continue
        if it.get("box_id_confirmed"):
            continue
        occ.add((bid // GRID_COLS, bid % GRID_COLS))
    return occ


def _vacant_cell_unit(
    csv_by_group: Optional[Dict[str, float]],
    quality_group: str,
    pricing: Dict[str, Any],
    pricing_key: str,
) -> int:
    if csv_by_group and quality_group in csv_by_group:
        return int(round(csv_by_group[quality_group]))
    raw = pricing.get(pricing_key)
    if raw is not None:
        return int(round(float(raw)))
    return 0

def _unknown_contour_vacant_weighted_excess(
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
    map_id_normalized: Optional[int],
) -> Tuple[float, Dict[str, Any]]:
    return _unknown_value.unknown_contour_vacant_weighted_excess(
        board_snapshot, csv_cells_raw, pricing, map_id_normalized
    )


def _possible_qualities_from_scan_history(board_snapshot: Dict[str, Any]) -> frozenset[int]:
    return _scan_inference.possible_qualities_from_scan_history(board_snapshot)


_possible_qualities_from_negative_constraints = _possible_qualities_from_scan_history


def _csv_quality_group_from_possible_set(possible: frozenset[int]) -> Optional[str]:
    return _scan_inference.csv_quality_group_from_possible_set(possible)


def _vacant_early_unit_from_exclusions(
    *,
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
) -> Tuple[int, str, frozenset[int]]:
    return _scan_inference.vacant_early_unit_from_exclusions(
        board_snapshot=board_snapshot,
        csv_cells_raw=csv_cells_raw,
        pricing=pricing,
    )


def _latest_map_skill_entries(board_snapshot: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return dict(_merge_latest_map_skill_entries(list(board_snapshot.get("skill_logs") or [])))


def _safe_int_field(entry: Dict[str, Any], *keys: str) -> Optional[int]:
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _safe_float_field(entry: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _min_total_cells_from_avg_per_item(avg: Any) -> int:
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return 0
    if a <= 0 or a != a:
        return 0
    max_cells = GRID_COLS * GRID_ROWS
    try:
        fr = Fraction(Decimal(str(a))).limit_denominator(512)
    except (ArithmeticError, ValueError, TypeError):
        try:
            fr = Fraction(a).limit_denominator(512)
        except (ArithmeticError, ValueError, TypeError):
            return max(0, min(int(round(a)), max_cells))
    return max(0, min(fr.numerator, max_cells))


def _max_quantity_price_from_avg_item_price(avg: Any) -> Optional[int]:
    try:
        a = float(avg)
    except (TypeError, ValueError):
        return None
    if a <= 0 or a != a:
        return None
    try:
        fr = Fraction(Decimal(str(a))).limit_denominator(512)
    except (ArithmeticError, ValueError, TypeError):
        try:
            fr = Fraction(a).limit_denominator(512)
        except (ArithmeticError, ValueError, TypeError):
            return max(0, int(round(a)))
    fr = fr.limit_denominator(512)
    if fr.numerator <= 0:
        return None
    return int(fr.numerator)


def _sum_confirmed_contour_quality_price(board_snapshot: Dict[str, Any], quality: int) -> int:
    return _quality_stats.sum_confirmed_contour_quality_price(board_snapshot, quality)


def _count_unconfirmed_contour_quality_items(board_snapshot: Dict[str, Any], quality: int) -> int:
    return _quality_stats.count_unconfirmed_contour_quality_items(board_snapshot, quality)


def _vacant_pts_floor_vs_avg_map_price_cap(
    *,
    vac_pts_component: int,
    max_quantity_price: Optional[int],
    confirmed_quality_price: int,
    unconfirmed_contour_items: int,
    unit_item_price: float,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    if max_quantity_price is None:
        return vac_pts_component, None
    try:
        hold = int(round(float(unconfirmed_contour_items) * float(unit_item_price)))
    except (TypeError, ValueError):
        hold = 0
    cap_remain = int(max_quantity_price - int(confirmed_quality_price) - hold)
    lifted = max(int(vac_pts_component), cap_remain)
    note = {
        "max_quantity_price": max_quantity_price,
        "confirmed_contour_quality_price": int(confirmed_quality_price),
        "unconfirmed_contour_items": int(unconfirmed_contour_items),
        "unit_item_price_applied": float(unit_item_price),
        "cap_remain_from_map_avg": cap_remain,
        "vac_pts_component_before": int(vac_pts_component),
        "vac_pts_component_after": int(lifted),
    }
    return lifted, note


def _lift_vac_pts_for_avg_price_map_skill(
    *,
    map_skill_cid: int,
    vac_pts_component: int,
    board_snapshot: Dict[str, Any],
    map_skills: Dict[int, Dict[str, Any]],
    skip_quality_extras: bool,
    csv_items_raw: Optional[Dict[str, float]],
    quality: int,
    default_item_unit: float,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    if skip_quality_extras:
        return int(vac_pts_component), None
    ent = map_skills.get(map_skill_cid)
    if not ent:
        return int(vac_pts_component), None
    ap = _safe_float_field(ent, "AllHitItemAvgPrice")
    mq = _max_quantity_price_from_avg_item_price(ap) if ap is not None else None
    key = "q5_item" if quality == 5 else "q6_item"
    qit = (
        float(csv_items_raw[key])
        if csv_items_raw and float(csv_items_raw.get(key) or 0) > 0
        else float(default_item_unit)
    )
    lifted, note = _vacant_pts_floor_vs_avg_map_price_cap(
        vac_pts_component=int(vac_pts_component),
        max_quantity_price=mq,
        confirmed_quality_price=_sum_confirmed_contour_quality_price(board_snapshot, quality),
        unconfirmed_contour_items=_count_unconfirmed_contour_quality_items(board_snapshot, quality),
        unit_item_price=qit,
    )
    if note is None:
        return int(vac_pts_component), None
    return int(lifted), {"map_skill": map_skill_cid, **note}


def _blend_pts_with_random_avg_map_skills(
    pts: int,
    map_skills: Dict[int, Dict[str, Any]],
) -> Tuple[int, List[Dict[str, Any]]]:
    notes: List[Dict[str, Any]] = []
    weights = {_MS_RND_AVG[0]: 0.9, _MS_RND_AVG[1]: 0.6, _MS_RND_AVG[2]: 0.5}
    default_n = {_MS_RND_AVG[0]: 3, _MS_RND_AVG[1]: 6, _MS_RND_AVG[2]: 9}
    cur = pts
    for cid in _MS_RND_AVG:
        ent = map_skills.get(cid)
        if not ent:
            continue
        ap = ent.get("AllHitItemAvgPrice")
        if ap is None:
            continue
        try:
            avg = float(ap)
        except (TypeError, ValueError):
            continue
        hn = _safe_int_field(ent, "HitItemIndex", "HitItemCount")
        if hn is None:
            hn = default_n[cid]
        skill_pts = int(round(avg * float(hn)))
        w = weights[cid]
        base_w = 1.0 - w
        nxt = int(round(cur * base_w + skill_pts * w))
        if nxt <= cur:
            continue
        notes.append(
            {
                "skill_cid": cid,
                "skill_pts": skill_pts,
                "weight_base_total_vacant": base_w,
                "weight_skill_pts": w,
                "before": cur,
                "after": nxt,
            }
        )
        cur = nxt
    return cur, notes


def compute_aisha_bid_from_board_snapshot(
    board_snapshot: Dict[str, Any],
    *,
    snapshot_path_hint: Optional[str] = None,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """
    与历史 ``aisha_premium.compute_aisha_snapshot_bid_points`` 对齐（无 ``config`` 覆盖单价键时行为一致）。
    返回 ``(points, meta)``；meta 将写入 ``pricing["aisha_bid"]``。
    """
    pricing = board_snapshot.get("pricing")
    if not isinstance(pricing, dict) or pricing.get("total") is None:
        return None, {}

    total_int = int(round(float(pricing["total"])))
    mid = map_id_from_board_snapshot(board_snapshot)
    mid_csv = item_db.normalize_map_id(mid)
    raw_block = board_snapshot.get("raw_pricing") if isinstance(board_snapshot, dict) else None
    raw_csv_cells = raw_block.get("csv_quality_groups_avg_per_cell") if isinstance(raw_block, dict) else None
    raw_csv_items = raw_block.get("csv_quality_groups_avg_per_item") if isinstance(raw_block, dict) else None
    csv_cells_raw = None
    if isinstance(raw_csv_cells, dict) and raw_csv_cells:
        try:
            csv_cells_raw = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_raw = None
    csv_items_raw = None
    if isinstance(raw_csv_items, dict) and raw_csv_items:
        try:
            csv_items_raw = {str(k): float(v) for k, v in raw_csv_items.items()}
        except (TypeError, ValueError):
            csv_items_raw = None
    csv_hit = bool(csv_cells_raw)
    map_quality_avg_csv = str(raw_block.get("map_quality_avg_csv") or "") if isinstance(raw_block, dict) else ""

    map_skills = _latest_map_skill_entries(board_snapshot)
    entry_gold_cells = map_skills.get(MAP_SKILL_TOTAL_GOLD_CELLS)
    entry_red_cells = map_skills.get(MAP_SKILL_TOTAL_RED_CELLS)
    total_gold_map = _safe_int_field(entry_gold_cells or {}, "TotalHitBoxIndex") if entry_gold_cells else None
    total_red_map = _safe_int_field(entry_red_cells or {}, "TotalHitBoxIndex") if entry_red_cells else None
    gold_total_disclosed = total_gold_map
    red_total_disclosed = total_red_map

    gold_cells_from_avg_skill = False
    red_cells_from_avg_skill = False
    if total_gold_map is None:
        ent_avg_g = map_skills.get(MAP_SKILL_AVG_GOLD_CELLS)
        if ent_avg_g:
            avg_g = _safe_float_field(ent_avg_g, "AllHitItemAvgBoxIndex")
            if avg_g is not None:
                total_gold_map = _min_total_cells_from_avg_per_item(avg_g)
                gold_cells_from_avg_skill = True
    if total_red_map is None:
        ent_avg_r = map_skills.get(MAP_SKILL_AVG_RED_CELLS)
        if ent_avg_r:
            avg_r = _safe_float_field(ent_avg_r, "AllHitItemAvgBoxIndex")
            if avg_r is not None:
                total_red_map = _min_total_cells_from_avg_per_item(avg_r)
                red_cells_from_avg_skill = True

    gold_zero_inferred_from_item_count = False
    ent019 = map_skills.get(MAP_SKILL_GOLD_ITEM_COUNT)
    if ent019 is not None:
        d019 = _safe_int_field(ent019, "HitItemIndex", "TotalHitBoxIndex")
        if d019 == 0 and total_gold_map is None:
            total_gold_map = 0
            gold_zero_inferred_from_item_count = True

    red_zero_inferred_from_item_count = False
    ent020 = map_skills.get(MAP_SKILL_RED_ITEM_COUNT)
    if ent020 is not None:
        d020 = _safe_int_field(ent020, "HitItemIndex", "TotalHitBoxIndex")
        if d020 == 0 and total_red_map is None:
            total_red_map = 0
            red_zero_inferred_from_item_count = True

    skip_gold_extras, skip_red_extras = _map_skill_gold_red_suppressed_for_ambiguous_contour(board_snapshot)
    if skip_gold_extras:
        total_gold_map = None
        gold_cells_from_avg_skill = False
        gold_total_disclosed = None
        gold_zero_inferred_from_item_count = False
    if skip_red_extras:
        total_red_map = None
        red_cells_from_avg_skill = False
        red_total_disclosed = None
        red_zero_inferred_from_item_count = False

    gold_cells_items = _sum_quality_footprint_cells(
        board_snapshot,
        5,
        csv_cells_raw=csv_cells_raw,
        pricing=pricing,
        map_id_normalized=mid_csv,
    )
    red_cells_items = _sum_quality_footprint_cells(
        board_snapshot,
        6,
        csv_cells_raw=csv_cells_raw,
        pricing=pricing,
        map_id_normalized=mid_csv,
    )
    gold_item_count_items = _count_quality_items_all(board_snapshot, 5)
    red_item_count_items = _count_quality_items_all(board_snapshot, 6)

    rnd = current_round_from_board_snapshot(board_snapshot)

    if rnd is not None and rnd <= 3:
        detail = _early_round_vacant_metrics(board_snapshot)
        adj_notes: List[Dict[str, Any]] = []

        vac_n = float(detail["vacant_round_1_2"])
        unit, vacant_qg, possible_q = _vacant_early_unit_from_exclusions(
            board_snapshot=board_snapshot,
            csv_cells_raw=csv_cells_raw,
            pricing=pricing,
        )
        adj_notes.append(
            {
                "vacant_tier": vacant_qg,
                "possible_qualities_from_exclusions": sorted(possible_q),
            }
        )

        vac_reserve = map_skill_hidden_cell_reserve_from_snapshot(board_snapshot)
        vac_n_geo = vac_n
        vac_n = max(0.0, vac_n - float(vac_reserve))

        unk_excess, unk_note = _unknown_contour_vacant_weighted_excess(
            board_snapshot,
            csv_cells_raw,
            pricing,
            mid_csv,
        )
        vac_n_before_unknown_adj = vac_n
        sub_unknown = min(float(unk_excess), vac_n)
        vac_n = max(0.0, vac_n - sub_unknown)
        if unk_note:
            unk_note["vacant_cells_subtracted_for_unknown_contour_weight"] = sub_unknown
            unk_note["vac_n_before_unknown_weight_adjust"] = vac_n_before_unknown_adj
            adj_notes.append(unk_note)

        # 地图「多出来的金/红格」已按 q5/q6 格价计入 early extra；若仍属几何空置，不应再按空格混合单价 unit 计价。
        extra_g_early = (
            max(0, int(total_gold_map) - gold_cells_items)
            if total_gold_map is not None
            else 0
        )
        extra_r_early = (
            max(0, int(total_red_map) - red_cells_items)
            if total_red_map is not None
            else 0
        )
        vac_n_subtract_for_gold_map_extra = float(min(extra_g_early, vac_n))
        vac_after_gold = max(0.0, vac_n - vac_n_subtract_for_gold_map_extra)
        vac_n_subtract_for_red_map_extra = float(min(extra_r_early, vac_after_gold))
        vac_n_linear = max(0.0, vac_after_gold - vac_n_subtract_for_red_map_extra)

        vac_n_linear_ceiled = math.ceil(vac_n_linear)
        vac_n_used_ceiled = math.ceil(vac_n)
        pts = int(round(total_int + vac_n_linear_ceiled * unit))

        gold_early_extra_raw = 0
        if extra_g_early > 0:
            uq5 = _vacant_cell_unit(csv_cells_raw, "q5", pricing, "vacant_unit_q5")
            add_g = int(round(extra_g_early * uq5))
            gold_early_extra_raw += add_g
            adj_notes.append(
                {
                    "map_skill": MAP_SKILL_AVG_GOLD_CELLS if gold_cells_from_avg_skill else MAP_SKILL_TOTAL_GOLD_CELLS,
                    "extra_gold_cells": extra_g_early,
                    "add_cells_raw": add_g,
                    "early_vacant_cells_subtracted_for_extra_gold_map": vac_n_subtract_for_gold_map_extra,
                }
            )

        q5_it_early = (
            float(csv_items_raw["q5"])
            if csv_items_raw and float(csv_items_raw.get("q5") or 0) > 0
            else 32629.7684
        )
        if ent019 is not None and not skip_gold_extras:
            declared = _safe_int_field(ent019, "HitItemIndex", "TotalHitBoxIndex")
            if declared is not None:
                extra_items = max(0, declared - gold_item_count_items)
                if extra_items > 0:
                    add_i = int(round(extra_items * q5_it_early))
                    gold_early_extra_raw += add_i
                    adj_notes.append(
                        {"map_skill": MAP_SKILL_GOLD_ITEM_COUNT, "extra_gold_items": extra_items, "add_items_raw": add_i}
                    )

        if gold_early_extra_raw > 0:
            gold_lifted, n37 = _lift_vac_pts_for_avg_price_map_skill(
                map_skill_cid=MAP_SKILL_AVG_GOLD_PRICE,
                vac_pts_component=gold_early_extra_raw,
                board_snapshot=board_snapshot,
                map_skills=map_skills,
                skip_quality_extras=skip_gold_extras,
                csv_items_raw=csv_items_raw,
                quality=5,
                default_item_unit=32629.7684,
            )
            pts += gold_lifted
            if n37:
                adj_notes.append(n37)
            adj_notes.append(
                {
                    "gold_early_map_extras_raw_sum": gold_early_extra_raw,
                    "gold_early_map_extras_applied": gold_lifted,
                }
            )

        red_early_extra_raw = 0
        if extra_r_early > 0:
            uq6 = _vacant_cell_unit(csv_cells_raw, "q6", pricing, "vacant_unit_all_red")
            add_rc = int(round(extra_r_early * uq6))
            red_early_extra_raw += add_rc
            adj_notes.append(
                {
                    "map_skill": MAP_SKILL_AVG_RED_CELLS if red_cells_from_avg_skill else MAP_SKILL_TOTAL_RED_CELLS,
                    "extra_red_cells": extra_r_early,
                    "add_cells_raw": add_rc,
                    "early_vacant_cells_subtracted_for_extra_red_map": vac_n_subtract_for_red_map_extra,
                }
            )

        if ent020 is not None and not skip_red_extras:
            declared_r = _safe_int_field(ent020, "HitItemIndex", "TotalHitBoxIndex")
            if declared_r is not None:
                extra_r_items = max(0, declared_r - red_item_count_items)
                if extra_r_items > 0:
                    q6_it = (
                        float(csv_items_raw["q6"])
                        if csv_items_raw and float(csv_items_raw.get("q6") or 0) > 0
                        else 68072.2211
                    )
                    add_r = int(round(extra_r_items * q6_it))
                    red_early_extra_raw += add_r
                    adj_notes.append(
                        {"map_skill": MAP_SKILL_RED_ITEM_COUNT, "extra_red_items": extra_r_items, "add_items_raw": add_r}
                    )

        if red_early_extra_raw > 0:
            red_lifted, n38 = _lift_vac_pts_for_avg_price_map_skill(
                map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
                vac_pts_component=red_early_extra_raw,
                board_snapshot=board_snapshot,
                map_skills=map_skills,
                skip_quality_extras=skip_red_extras,
                csv_items_raw=csv_items_raw,
                quality=6,
                default_item_unit=68072.2211,
            )
            pts += red_lifted
            if n38:
                adj_notes.append(n38)
            adj_notes.append(
                {
                    "red_early_map_extras_raw_sum": red_early_extra_raw,
                    "red_early_map_extras_applied": red_lifted,
                }
            )

        pts, blend_notes = _blend_pts_with_random_avg_map_skills(pts, map_skills)
        adj_notes.extend(blend_notes)

        meta: Dict[str, Any] = {
            "points": pts,
            "points_floor": pts,
            "points_ceiling": pts,
            "gold_red_vacant_counts_certain": None,
            "early_round_estimated": True,
            "current_round": rnd,
            "vacant_used": vac_n_used_ceiled,
            "early_vacant_cells_for_linear_pricing": vac_n_linear_ceiled,
            "early_vacant_cells_linear_float": vac_n_linear,
            "vacant_geometric_for_pricing": vac_n_geo,
            "vacant_map_skill_hidden_cell_reserve": vac_reserve,
            "vacant_unit_applied": unit,
            "early_round_detail": detail,
            "map_id": mid,
            "map_quality_avg_csv": map_quality_avg_csv,
            "map_quality_avg_hit": csv_hit,
            "map_skill_adjustments": adj_notes,
            "map_skill_gold_red_suppressed_ambiguous_contour": {
                "gold": skip_gold_extras,
                "red": skip_red_extras,
            },
        }
        if pts == 0:
            return None, meta
        return pts, meta

    vacant_raw = pricing.get("vacant")
    vac_geo = pricing.get("vacant_geometric")
    vac_reserve = map_skill_hidden_cell_reserve_from_snapshot(board_snapshot)
    if vac_geo is not None:
        try:
            geo_n = int(vac_geo)
        except (TypeError, ValueError):
            geo_n = None
        if geo_n is not None:
            vac_n = max(0, geo_n - vac_reserve)
        else:
            try:
                vac_n = int(vacant_raw) if vacant_raw is not None else 0
            except (TypeError, ValueError):
                vac_n = 0
    else:
        try:
            base_v = int(vacant_raw or 0)
        except (TypeError, ValueError):
            base_v = 0
        vac_n = max(0, base_v - vac_reserve)

    unit_q5 = _vacant_cell_unit(csv_cells_raw, "q5", pricing, "vacant_unit_q5")
    unit_q5_q6 = _vacant_cell_unit(csv_cells_raw, "q5+q6", pricing, "vacant_unit_q5_q6")
    unit_q6 = _vacant_cell_unit(csv_cells_raw, "q6", pricing, "vacant_unit_all_red")

    vacant_mode = "default"
    adj_late: List[Dict[str, Any]] = []

    gold_split_reliable = total_gold_map is not None and (
        gold_total_disclosed is not None or gold_zero_inferred_from_item_count
    )
    red_split_reliable = total_red_map is not None and (
        red_total_disclosed is not None or red_zero_inferred_from_item_count
    )

    if gold_split_reliable and red_split_reliable:
        G = int(total_gold_map)
        R = int(total_red_map)
        hg = max(0, G - gold_cells_items)
        hr = max(0, R - red_cells_items)
        red_n = min(hr, vac_n)
        gold_n = min(hg, max(0, vac_n - red_n))
        rest = max(0, vac_n - gold_n - red_n)
        if G == 0:
            gold_vac_pts = int(round(gold_n * float(unit_q5)))
            red_vac_pts = int(round((red_n + rest) * float(unit_q6)))
        else:
            gold_vac_pts = int(round((gold_n + rest) * float(unit_q5)))
            red_vac_pts = int(round(red_n * float(unit_q6)))
        lg, ng = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_GOLD_PRICE,
            vac_pts_component=gold_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_gold_extras,
            csv_items_raw=csv_items_raw,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            csv_items_raw=csv_items_raw,
            quality=6,
            default_item_unit=68072.2211,
        )
        if ng:
            adj_late.append(ng)
        if nr:
            adj_late.append(nr)
        pts_one = float(total_int + lg + lr)
        pts_floor = pts_ceiling = int(round(pts_one))
        vacant_mode = "split_both_gold_red_totals_known"
        adj_late.append(
            {
                "hidden_gold_cells": hg,
                "hidden_red_cells": hr,
                "gold_like_cells_est": gold_n,
                "red_cells_est": red_n,
                "other_cells_est": rest,
            }
        )
    elif gold_split_reliable:
        scam_vac = _scam_span_vacant_deduction(board_snapshot)
        G = int(total_gold_map)
        if G == 0:
            gold_n = 0
            red_n = max(0, vac_n - scam_vac)
            rest = max(0, vac_n - gold_n - red_n)
            hidden_gold = 0
            vacant_mode = "split_from_total_gold_cells"
        else:
            hidden_gold = max(0, G - gold_cells_items)
            if gold_cells_from_avg_skill and vac_n < hidden_gold:
                gold_n = hidden_gold
                red_n = 0
                rest = 0
                vacant_mode = "split_from_avg_gold_cells_short_vacant"
            else:
                red_n = max(0, vac_n - hidden_gold - scam_vac)
                gold_n = vac_n - red_n
                rest = 0
                vacant_mode = "split_from_total_gold_cells"
        if G == 0:
            gold_vac_pts = 0
            red_vac_pts = int(round((red_n + rest) * float(unit_q6)))
        else:
            gold_vac_pts = int(round((gold_n + rest) * float(unit_q5)))
            red_vac_pts = int(round(red_n * float(unit_q6)))
        lg, ng = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_GOLD_PRICE,
            vac_pts_component=gold_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_gold_extras,
            csv_items_raw=csv_items_raw,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            csv_items_raw=csv_items_raw,
            quality=6,
            default_item_unit=68072.2211,
        )
        if ng:
            adj_late.append(ng)
        if nr:
            adj_late.append(nr)
        pts_one = float(total_int + lg + lr)
        pts_floor = pts_ceiling = int(round(pts_one))
        adj_late.append(
            {
                "map_skill": MAP_SKILL_AVG_GOLD_CELLS if gold_cells_from_avg_skill else MAP_SKILL_TOTAL_GOLD_CELLS,
                "hidden_gold_cells": hidden_gold,
                "red_cells_est": red_n,
                "gold_like_cells_est": gold_n,
                "other_cells_est": rest,
                "scam_span_vacant_deduction": scam_vac,
            }
        )
    elif red_split_reliable:
        R = int(total_red_map)
        if R == 0:
            gold_n = vac_n
            red_n = 0
            hidden_red = 0
        else:
            hidden_red = max(0, R - red_cells_items)
            red_n = min(hidden_red, vac_n)
            gold_n = vac_n - red_n
        gold_vac_pts = int(round(gold_n * float(unit_q5)))
        red_vac_pts = int(round(red_n * float(unit_q6)))
        lg, ng = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_GOLD_PRICE,
            vac_pts_component=gold_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_gold_extras,
            csv_items_raw=csv_items_raw,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            csv_items_raw=csv_items_raw,
            quality=6,
            default_item_unit=68072.2211,
        )
        if ng:
            adj_late.append(ng)
        if nr:
            adj_late.append(nr)
        pts_one = float(total_int + lg + lr)
        pts_floor = pts_ceiling = int(round(pts_one))
        vacant_mode = "split_from_total_red_cells"
        adj_late.append(
            {
                "map_skill": MAP_SKILL_AVG_RED_CELLS if red_cells_from_avg_skill else MAP_SKILL_TOTAL_RED_CELLS,
                "hidden_red_cells": hidden_red,
                "red_cells_est": red_n,
                "gold_like_cells_est": gold_n,
            }
        )
    else:
        gold_floor_raw = int(round(vac_n * float(unit_q5)))
        lg, ng = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_GOLD_PRICE,
            vac_pts_component=gold_floor_raw,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_gold_extras,
            csv_items_raw=csv_items_raw,
            quality=5,
            default_item_unit=32629.7684,
        )
        if ng:
            adj_late.append(ng)
        pts_floor = int(round(float(total_int) + float(lg)))
        pts_ceiling = int(round(total_int + vac_n * float(unit_q5_q6)))

    bn_f: List[Dict[str, Any]] = []
    bn_c: List[Dict[str, Any]] = []

    pts = pts_floor
    meta = {
        "points": pts,
        "points_floor": pts_floor,
        "points_ceiling": pts_ceiling,
        "gold_red_vacant_counts_certain": vacant_mode != "default",
        "early_round_estimated": False,
        "vacant_used": vac_n,
        "vacant_map_skill_hidden_cell_reserve": vac_reserve,
        "vacant_unit_q5": unit_q5,
        "vacant_unit_q5_q6": unit_q5_q6,
        "vacant_unit_q6": unit_q6,
        "vacant_pricing_mode": vacant_mode,
        "map_id": mid,
        "map_quality_avg_csv": map_quality_avg_csv,
        "map_quality_avg_hit": csv_hit,
        "map_skill_adjustments": adj_late,
        "random_avg_blend_ceiling_notes": bn_c,
        "random_avg_map_skills_round_cap": "only_rounds_1_to_3",
        "map_skill_gold_red_suppressed_ambiguous_contour": {
            "gold": skip_gold_extras,
            "red": skip_red_extras,
        },
    }
    return pts, meta


def build_snapshot_pricing_dict(
    board_snapshot: Optional[Dict[str, Any]] = None,
    *,
    total: Optional[float] = None,
    raw_vacant: Optional[int] = None,
    sum_gold_red_min_minus_weighted: Optional[float] = None,
    map_id: Optional[int] = None,
    current_round: Optional[int] = None,
    skill_logs: Optional[List[dict]] = None,
    game_state_json: Optional[Dict[str, Any]] = None,
    snapshot_path_hint: Optional[str] = None,
    vacant_occupied_cell_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    组装写入 ``board_snapshot.json`` 的 ``pricing`` 字段（含 ``aisha_bid``、三档仓位总价与 ``known_items_total``）。

    ``vacant_occupied_cell_count``：画板占位格数（含幽灵等）；若省略则从 ``game_state_json`` 单独推导日志物品占位，
    与界面 ``_build_occupied()`` 可能略有差异。
    """
    if isinstance(board_snapshot, dict):
        game_state_json = board_snapshot.get("game_state") or {}
        skill_logs = list(board_snapshot.get("skill_logs") or [])
        map_id = int(board_snapshot.get("map_id") or (game_state_json.get("map_id") or 0))
        current_round = int(
            board_snapshot.get("current_round") or (game_state_json.get("current_round") or 1)
        )
        raw = board_snapshot.get("raw_pricing") or {}
        pricing_prev = board_snapshot.get("pricing") or {}
        if total is None:
            total = pricing_prev.get("known_items_total")
        if total is None:
            total = pricing_prev.get("total")
        if raw_vacant is None:
            raw_vacant = pricing_prev.get("vacant_geometric")
        if sum_gold_red_min_minus_weighted is None:
            sum_gold_red_min_minus_weighted = pricing_prev.get("sum_gold_red_min_minus_weighted")
    else:
        game_state_json = game_state_json or {}
        skill_logs = list(skill_logs or [])
        map_id = int(map_id or 0)
        current_round = int(current_round or 1)
        if total is None:
            total = 0.0
        if sum_gold_red_min_minus_weighted is None:
            sum_gold_red_min_minus_weighted = 0.0
        from .raw_pricing import build_raw_pricing_dict

        raw = build_raw_pricing_dict(
            map_id=map_id,
            skill_logs=skill_logs,
            snapshot_path_hint=snapshot_path_hint,
        )

    total = float(total or 0.0)
    sum_gold_red_min_minus_weighted = float(sum_gold_red_min_minus_weighted or 0.0)
    game_state_json = game_state_json or {}
    skill_logs = list(skill_logs or [])
    map_id = int(map_id or 0)
    current_round = int(current_round or 1)

    if vacant_occupied_cell_count is not None:
        try:
            occ_n = max(0, int(vacant_occupied_cell_count))
        except (TypeError, ValueError):
            occ_n = len(_board_display_occupied_cells_from_snapshot({"game_state": game_state_json}))
    else:
        occ_n = len(_board_display_occupied_cells_from_snapshot({"game_state": game_state_json}))
    skill_vacant = vacant_cells_from_map_skill_total_hidden(
        list(skill_logs or []), occupied_cell_count=occ_n
    )
    if skill_vacant is not None:
        raw_vacant = skill_vacant

    vacant_reserve = map_skill_hidden_cell_reserve_from_snapshot(
        {"game_state": game_state_json, "skill_logs": list(skill_logs or [])}
    )
    if raw_vacant is None:
        vacant_num = 0
        vacant_eff: Optional[int] = None
    else:
        vacant_num = max(0, int(raw_vacant) - vacant_reserve)
        vacant_eff = vacant_num

    raw_csv_cells = raw.get("csv_quality_groups_avg_per_cell") if isinstance(raw, dict) else None
    if isinstance(raw_csv_cells, dict):
        try:
            csv_cells_for_est = {str(k): float(v) for k, v in raw_csv_cells.items()}
        except (TypeError, ValueError):
            csv_cells_for_est = {}
    else:
        csv_cells_for_est = {}
    u_orange = int(round(float(csv_cells_for_est.get("q5", 0.0))))
    u_gr = int(round(float(csv_cells_for_est.get("q5+q6", 0.0))))
    u_red = int(round(float(csv_cells_for_est.get("q6", 0.0))))
    csv_hit = bool(csv_cells_for_est)
    est_orange = total + vacant_num * u_orange
    est_gold_red = total + vacant_num * u_gr
    est_red = total + vacant_num * u_red
    est_floor = total + sum_gold_red_min_minus_weighted + vacant_num * u_orange
    path_used = str(raw.get("map_quality_avg_csv") or "") if isinstance(raw, dict) else ""

    pricing: Dict[str, Any] = {
        "total": total,
        "known_items_total": float(total),
        "vacant": vacant_eff if raw_vacant is not None else None,
        "vacant_geometric": raw_vacant,
        "vacant_map_skill_hidden_cell_reserve": vacant_reserve,
        "sum_gold_red_min_minus_weighted": sum_gold_red_min_minus_weighted,
        "est_orange": est_orange,
        "est_gold_red": est_gold_red,
        "est_red": est_red,
        "est_floor": est_floor,
        "position_total_all_gold": est_orange,
        "position_total_gold_red": est_gold_red,
        "position_total_all_red": est_red,
        "vacant_unit_all_orange": u_orange,
        "vacant_unit_gold_red": u_gr,
        "vacant_unit_all_red": u_red,
        "map_quality_avg_hit": csv_hit,
        "map_quality_avg_csv": path_used,
        "vacant_effective_count": vacant_eff,
    }

    board_snap: Dict[str, Any] = {
        "game_state": game_state_json,
        "skill_logs": list(skill_logs or []),
        "pricing": pricing,
        "current_round": int(current_round),
        "map_id": int(map_id or 0),
    }
    if isinstance(board_snapshot, dict):
        raw_block = board_snapshot.get("raw_pricing")
        if isinstance(raw_block, dict):
            board_snap["raw_pricing"] = raw_block
    pts, bid_meta = compute_aisha_bid_from_board_snapshot(board_snap, snapshot_path_hint=snapshot_path_hint)
    pricing["aisha_bid"] = bid_meta
    pricing["aisha_bid_points"] = pts

    # 第 1–3 回合：`_vacant_early_unit_from_exclusions` 的单价与线性参考总价（与 aisha 早期分支一致，供 UI/快照直读）
    if bid_meta.get("early_round_estimated"):
        u_e = bid_meta.get("vacant_unit_applied")
        try:
            u_e_int = int(u_e) if u_e is not None else None
        except (TypeError, ValueError):
            u_e_int = None
        pricing["early_exclusions_vacant_unit"] = u_e_int
        tier: Optional[str] = None
        for note in bid_meta.get("map_skill_adjustments") or []:
            if isinstance(note, dict) and "vacant_tier" in note:
                tier = str(note["vacant_tier"])
                break
        pricing["early_exclusions_quality_group"] = tier
        v_lin = bid_meta.get("early_vacant_cells_for_linear_pricing")
        if v_lin is not None:
            v_used = v_lin
        else:
            v_used = bid_meta.get("vacant_used")
        try:
            v_int = int(v_used) if v_used is not None else 0
        except (TypeError, ValueError):
            v_int = 0
        if u_e_int is not None:
            pricing["early_exclusions_linear_total"] = float(total) + float(v_int) * float(u_e_int)
        else:
            pricing["early_exclusions_linear_total"] = None
    else:
        pricing["early_exclusions_vacant_unit"] = None
        pricing["early_exclusions_quality_group"] = None
        pricing["early_exclusions_linear_total"] = None

    return pricing
