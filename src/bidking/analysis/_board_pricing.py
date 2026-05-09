# -*- coding: utf-8 -*-
"""
画板快照定价：地图质量 CSV、空置三档（全金/金红/全红）、地图技能约束与艾莎 bid 元数据。

原逻辑与 ``bidking-bot/aisha_premium.compute_aisha_snapshot_bid_points`` 对齐，供 ``grid_view`` 写入
``board_snapshot.json`` 的 ``pricing`` 与 ``pricing["aisha_bid"]``；bot 侧仅消费快照字段。
"""

from __future__ import annotations

import csv
import math
import os
import re
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Set, Tuple

from ..parsing import item_db
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
    MAP_SKILL_TOTAL_HIDDEN_CELLS,
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

_DEFAULT_UNIT_Q234 = 874.5672
_DEFAULT_UNIT_Q34 = 1275.0056
_DEFAULT_UNIT_Q4 = 2444.4747
_DEFAULT_UNIT_Q5_Q6 = 10916.9326
_DEFAULT_UNIT_Q5 = 9587.4375
_DEFAULT_UNIT_Q6 = 64551.3821

# 地图 CSV 缺行时按品质的格均价回退（与 map_quality_avg_out 典型量级一致）
_DEFAULT_AVG_CELL_Q1 = 118.4634
_DEFAULT_AVG_CELL_Q2 = 291.5937
_DEFAULT_AVG_CELL_Q3 = 917.4746

ITEM_PRICES_CSV_RELPATHS = (
    ("..", "..", "..", "data", "item_prices.csv"),
    ("..", "..", "data", "item_prices.csv"),
)

_item_prices_cache: Optional[Tuple[Dict[int, Any], List[Any]]] = None

VACANT_UNIT_ALL_ORANGE = 10_000
VACANT_UNIT_GOLD_RED = 17_000
VACANT_UNIT_ALL_RED = 56_000

_map_quality_cells_cache: Optional[Dict[int, Dict[str, float]]] = None
_map_quality_blends_cache: Optional[Dict[int, Dict[str, float]]] = None
_map_quality_csv_override: Optional[str] = None


def set_map_quality_csv_override(path: Optional[str]) -> None:
    """测试或自定义报表路径时调用；``None`` 恢复默认候选解析。"""
    global _map_quality_cells_cache, _map_quality_blends_cache, _map_quality_csv_override
    _map_quality_csv_override = path
    _map_quality_cells_cache = None
    _map_quality_blends_cache = None


def _map_quality_csv_candidates(snapshot_path_hint: Optional[str] = None) -> List[str]:
    out: List[str] = []
    if _map_quality_csv_override and os.path.isfile(_map_quality_csv_override):
        return [_map_quality_csv_override]
    snap = (snapshot_path_hint or "").strip()
    if snap:
        out.append(
            os.path.normpath(
                os.path.join(os.path.dirname(snap), "data", "map_quality_avg_out.csv")
            )
        )
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out.append(
            os.path.normpath(
                os.path.join(here, "..", "..", "..", "data", "map_quality_avg_out.csv")
            )
        )
    except Exception:
        pass
    return out


def map_quality_csv_path_resolved(snapshot_path_hint: Optional[str] = None) -> str:
    for p in _map_quality_csv_candidates(snapshot_path_hint):
        if p and os.path.isfile(p):
            return p
    cands = _map_quality_csv_candidates(snapshot_path_hint)
    return cands[0] if cands else ""


def load_map_quality_cells_by_map_id(snapshot_path_hint: Optional[str] = None) -> Dict[int, Dict[str, float]]:
    global _map_quality_cells_cache
    if _map_quality_csv_override is None and _map_quality_cells_cache is not None:
        return _map_quality_cells_cache
    tab: Dict[int, Dict[str, float]] = {}
    path = map_quality_csv_path_resolved(snapshot_path_hint)
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    try:
                        mid = int(row["map_id"])
                        qg = str(row["quality_group"]).strip()
                        cell = float(row["avg_price_per_cell"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    tab.setdefault(mid, {})[qg] = cell
        except OSError:
            tab = {}
    if _map_quality_csv_override is None:
        _map_quality_cells_cache = tab
    return tab


def load_map_quality_blends_by_map_id(snapshot_path_hint: Optional[str] = None) -> Dict[int, Dict[str, float]]:
    global _map_quality_blends_cache
    if _map_quality_csv_override is None and _map_quality_blends_cache is not None:
        return _map_quality_blends_cache
    groups: Dict[Tuple[int, str, str], List[Tuple[str, float, float, float]]] = defaultdict(list)
    path = map_quality_csv_path_resolved(snapshot_path_hint)
    if not path or not os.path.isfile(path):
        out: Dict[int, Dict[str, float]] = {}
        if _map_quality_csv_override is None:
            _map_quality_blends_cache = out
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                mid = int(row["map_id"])
                qg = str(row["quality_group"]).strip()
                cell = float(row["avg_price_per_cell"])
                pit = float(row["avg_price_per_item"])
                prob = float(row["prob_in_group"])
            except (KeyError, TypeError, ValueError):
                continue
            tier = str(row.get("tier") or "")
            nest = str(row.get("nest_drop_id") or "")
            groups[(mid, tier, nest)].append((qg, cell, pit, prob))

    out: Dict[int, Dict[str, float]] = {}
    for mid in {k[0] for k in groups}:
        best: Optional[Tuple[int, Dict[str, float]]] = None
        for key, lst in groups.items():
            if key[0] != mid:
                continue
            by_qg: Dict[str, Tuple[float, float, float]] = {}
            for qg, cell, pit, prob in lst:
                by_qg[qg] = (cell, pit, prob)
            if "q2" not in by_qg or "q3" not in by_qg:
                continue
            q2c, _, q2p = by_qg["q2"]
            q3c, q3i, q3p = by_qg["q3"]
            denom = q2p + q3p
            q23_cell = (q2p * q2c + q3p * q3c) / denom if denom > 0 else (q2c + q3c) / 2
            q5_item = by_qg["q5"][1] if "q5" in by_qg else 0.0
            q6_item = by_qg["q6"][1] if "q6" in by_qg else 0.0
            score = 2 if "q4" in by_qg else (1 if "q5" in by_qg else 0)
            chunk = {
                "q2+q3_cell": float(q23_cell),
                "q3_cell": float(q3c),
                "q5_item": float(q5_item),
                "q6_item": float(q6_item),
            }
            if best is None or score > best[0]:
                best = (score, chunk)
        if best is not None:
            out[mid] = best[1]
    if _map_quality_csv_override is None:
        _map_quality_blends_cache = out
    return out


def vacant_unit_prices_for_map_id(
    map_id: int, snapshot_path_hint: Optional[str] = None
) -> Tuple[int, int, int, bool]:
    tab = load_map_quality_cells_by_map_id(snapshot_path_hint)
    if map_id <= 0:
        return VACANT_UNIT_ALL_ORANGE, VACANT_UNIT_GOLD_RED, VACANT_UNIT_ALL_RED, False
    mid_csv = item_db.normalize_map_id(map_id)
    cells = tab.get(mid_csv) if mid_csv is not None else None
    if not cells:
        return VACANT_UNIT_ALL_ORANGE, VACANT_UNIT_GOLD_RED, VACANT_UNIT_ALL_RED, False

    def pick(qg: str, default: int) -> int:
        v = cells.get(qg)
        if v is None:
            return default
        return int(round(float(v)))

    return (
        pick("q5", VACANT_UNIT_ALL_ORANGE),
        pick("q5+q6", VACANT_UNIT_GOLD_RED),
        pick("q6", VACANT_UNIT_ALL_RED),
        True,
    )


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
    """
    地图技能 200009「所有藏品格数」：取各 SkillCid 最新一条的占用格总数。
    与 ``grid_view`` 空置区、``pricing.vacant`` 一致；无有效数据时返回 ``None``。

    有有效总数时，空置格可取 **收藏总格数 − 画板已有物品占位格数**（见
    ``vacant_cells_from_map_skill_total_hidden``）。
    """
    ent = _merge_latest_map_skill_entries(skill_logs or []).get(MAP_SKILL_TOTAL_HIDDEN_CELLS)
    if not ent:
        return None
    v = _ms_int_field(ent, "TotalHitBoxIndex", "HitItemIndex")
    return v if v is not None and v > 0 else None


def vacant_cells_from_map_skill_total_hidden(
    skill_logs: List[dict],
    *,
    occupied_cell_count: int,
) -> Optional[int]:
    """
    地图技能 200009 已揭示时：空置格 = 收藏总格数 − 画板已有物品占位格数。

    无 200009 或总数无效时返回 ``None``（调用方继续用几何空置区 / 诈骗格等路径）。
    """
    total_h = map_skill_total_hidden_cells_from_logs(skill_logs)
    if total_h is None:
        return None
    try:
        occ = int(occupied_cell_count)
    except (TypeError, ValueError):
        occ = 0
    occ = max(0, occ)
    return max(0, total_h - occ)


def _ms_int_field(entry: dict, *keys: str) -> Optional[int]:
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _ms_float_field(entry: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _min_total_cells_from_avg_per_item_ui(avg: float) -> int:
    if avg <= 0 or avg != avg:
        return 0
    max_cells = GRID_COLS * GRID_ROWS
    try:
        fr = Fraction(Decimal(str(avg))).limit_denominator(512)
    except (ArithmeticError, ValueError, TypeError):
        try:
            fr = Fraction(avg).limit_denominator(512)
        except (ArithmeticError, ValueError, TypeError):
            return max(0, min(int(round(avg)), max_cells))
    return max(0, min(fr.numerator, max_cells))


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


def _confirmed_items_from_snapshot(board_snapshot: Dict[str, Any]) -> List[dict]:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    out: List[dict] = []
    for _uid, it in raw.items():
        if not isinstance(it, dict) or not it.get("box_id_confirmed"):
            continue
        bid = it.get("box_id")
        if bid is None:
            continue
        try:
            int(bid)
        except (TypeError, ValueError):
            continue
        out.append(it)
    return out


def _items_dict_from_snapshot(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    return raw if isinstance(raw, dict) else {}


def _early_round_vacant_metrics(board_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    items = _confirmed_items_from_snapshot(board_snapshot)
    if not items:
        return {
            "max_anchor_box_id": -1,
            "vacant_round_1_2": 0,
            "vacant_round_3": 0,
            "round_3_anchor_floor_exclusive": 0,
            "known_quality_cell_count": 0,
            "all_occupied_cell_count": 0,
        }

    # 与画板占位一致的几何并集；上届仍为已确认物品的最大锚点。
    all_occ = _board_display_occupied_cells_from_snapshot(board_snapshot)
    max_anchor = max(int(it["box_id"]) for it in items)

    known_cells: set = set()
    for it in items:
        cells = _occupied_cells_item_board_display(it, board_snapshot)
        q = it.get("quality")
        if q is None:
            continue
        try:
            int(q)
        except (TypeError, ValueError):
            continue
        known_cells |= cells

    span_hi = min(max_anchor, GRID_MAX_BOX_ID)
    vacant_12 = 0
    if span_hi >= 0:
        for b in range(span_hi + 1):
            r, c = b // GRID_COLS, b % GRID_COLS
            if (r, c) not in all_occ:
                vacant_12 += 1

    r3_cap = (max_anchor // 10) * 10 if max_anchor >= 0 else 0
    vacant_3 = 0
    r3_hi = min(r3_cap, GRID_MAX_BOX_ID + 1)
    for b in range(r3_hi):
        r, c = b // GRID_COLS, b % GRID_COLS
        if (r, c) not in all_occ:
            vacant_3 += 1

    return {
        "max_anchor_box_id": max_anchor,
        "vacant_round_1_2": vacant_12,
        "vacant_round_3": vacant_3,
        "round_3_anchor_floor_exclusive": r3_cap,
        "known_quality_cell_count": len(known_cells),
        "all_occupied_cell_count": len(all_occ),
    }


def _scam_span_vacant_deduction(board_snapshot: Dict[str, Any]) -> int:
    items = _confirmed_items_from_snapshot(board_snapshot)
    if not items:
        return 1
    all_occ = _board_display_occupied_cells_from_snapshot(board_snapshot)
    max_anchor = max(int(it["box_id"]) for it in items)
    if max_anchor < 0:
        return 1
    col = max_anchor % GRID_COLS
    span_lo = max(0, max_anchor - col - GRID_COLS)
    span_hi = min(max_anchor, GRID_MAX_BOX_ID)
    n = 0
    for b in range(span_lo, span_hi + 1):
        r, c = b // GRID_COLS, b % GRID_COLS
        if (r, c) not in all_occ:
            n += 1
    return n


def _sum_quality_footprint_cells(
    board_snapshot: Dict[str, Any],
    quality: int,
    *,
    csv_cells_raw: Optional[Dict[str, float]] = None,
    pricing: Optional[Dict[str, Any]] = None,
    map_id_normalized: Optional[int] = None,
) -> int:
    """
    某品质在地图上的占用格总数：已揭示 ``shape`` → w×h；
    金/红（q5/q6）且无日志形状时，用「权重总价 / 该品质格均价」的等价格数（与空置加权扣减一致）；
    其余未知轮廓按 1 格计。
    """
    n = 0
    use_weighted_gr = (
        quality in (5, 6)
        and csv_cells_raw is not None
        and pricing is not None
    )
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        shape = it.get("shape")
        if shape is not None:
            w, h = _shape_wh_from_snapshot(shape)
            n += w * h
        elif use_weighted_gr:
            w_eq = _weighted_cell_equiv_for_unknown_contour_item(
                it,
                board_snapshot,
                csv_cells_raw,
                pricing,
                map_id_normalized,
            )
            if w_eq is not None:
                n += max(1, int(round(w_eq)))
            else:
                n += 1
        else:
            n += 1
    return n


def _count_quality_items_all(board_snapshot: Dict[str, Any], quality: int) -> int:
    k = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) == quality:
                k += 1
        except (TypeError, ValueError):
            continue
    return k


def _quality_has_unconfirmed_contour(board_snapshot: Dict[str, Any], quality: int) -> bool:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    for _uid, it in raw.items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed"):
            return True
        if it.get("shape") is None:
            return True
    return False


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
    default: float,
) -> int:
    if csv_by_group and quality_group in csv_by_group:
        return int(round(csv_by_group[quality_group]))
    raw = pricing.get(pricing_key)
    if raw is not None:
        return int(round(float(raw)))
    return int(round(default))


def _item_prices_csv_path_resolved() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for parts in ITEM_PRICES_CSV_RELPATHS:
        p = os.path.normpath(os.path.join(here, *parts))
        if os.path.isfile(p):
            return p
    return ""


def _load_item_prices_db() -> Tuple[Dict[int, Any], List[Any]]:
    global _item_prices_cache
    if _item_prices_cache is not None:
        return _item_prices_cache
    path = _item_prices_csv_path_resolved()
    if not path:
        _item_prices_cache = ({}, [])
        return _item_prices_cache
    try:
        _item_prices_cache = item_db.load_csv(path)
    except OSError:
        _item_prices_cache = ({}, [])
    return _item_prices_cache


def _avg_cell_price_for_quality(
    quality: int,
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
) -> float:
    key = f"q{quality}"
    if csv_cells_raw and key in csv_cells_raw:
        return float(csv_cells_raw[key])
    pk = f"vacant_unit_q{quality}"
    raw = pricing.get(pk)
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    defaults = {
        1: _DEFAULT_AVG_CELL_Q1,
        2: _DEFAULT_AVG_CELL_Q2,
        3: _DEFAULT_AVG_CELL_Q3,
        4: _DEFAULT_UNIT_Q4,
        5: _DEFAULT_UNIT_Q5,
        6: _DEFAULT_UNIT_Q6,
    }
    return float(defaults.get(quality, _DEFAULT_UNIT_Q234))


def _int_set_from_snapshot_field(raw: Any) -> Set[int]:
    out: Set[int] = set()
    if not isinstance(raw, list):
        return out
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _weighted_cell_equiv_for_unknown_contour_item(
    it: Dict[str, Any],
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
    map_id_normalized: Optional[int],
) -> Optional[float]:
    """
    无日志 shape、已确认锚点：权重总价（或唯一候选原价）/ 该品质地图格均价 ⇒ 等价格数。
    """
    _ = board_snapshot
    if not it.get("box_id_confirmed") or it.get("shape") is not None:
        return None
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return None
    try:
        q = int(it["quality"])
    except (KeyError, TypeError, ValueError):
        return None
    if q < 1 or q > 6:
        return None
    try:
        cid_raw = it.get("item_cid")
        item_cid_i = int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        item_cid_i = None
    categories = _int_set_from_snapshot_field(it.get("categories"))
    excl_q = _int_set_from_snapshot_field(it.get("excluded_qualities"))
    excl_c = _int_set_from_snapshot_field(it.get("excluded_categories"))

    best, count, unique, est, _ql = item_db.query_item(
        shape=None,
        quality=q,
        categories=categories,
        item_cid=item_cid_i,
        csv_index=csv_index,
        csv_items=csv_items,
        excluded_categories=excl_c if excl_c else None,
        excluded_qualities=excl_q if excl_q else None,
        max_shape_wh=None,
        map_category_weights=None,
        map_id=map_id_normalized,
    )
    if best is None or count == 0:
        return None
    price = float(est) if est is not None else float(best.base_value)
    u_cell = _avg_cell_price_for_quality(q, csv_cells_raw, pricing)
    if u_cell <= 0:
        return None
    return price / u_cell


def _unknown_contour_vacant_weighted_excess(
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
    map_id_normalized: Optional[int],
) -> Tuple[float, Dict[str, Any]]:
    """
    未知轮廓（无日志 shape）物品：权重总价 / 该品质地图格均价 ≈ 等价占位格数 w；
    画板几何仅占锚格 1×1，线性空置中多算的部分为 max(0, w-1)。
    返回所有此类物品的 sum(max(0,w-1))，供从 vac_n 扣除（类金红 vac_n_linear 扣格）。
    """
    csv_index, csv_items = _load_item_prices_db()
    if not csv_items:
        return 0.0, {}

    raw_items = _items_dict_from_snapshot(board_snapshot)
    per_item: List[Dict[str, Any]] = []
    total_excess = 0.0
    n_uc = 0

    for uid, it in raw_items.items():
        if not isinstance(it, dict):
            continue
        if not it.get("box_id_confirmed"):
            continue
        if it.get("shape") is not None:
            continue
        try:
            q = int(it["quality"])
        except (KeyError, TypeError, ValueError):
            continue
        if q < 1 or q > 6:
            continue
        n_uc += 1

        w_cells = _weighted_cell_equiv_for_unknown_contour_item(
            it,
            board_snapshot,
            csv_cells_raw,
            pricing,
            map_id_normalized,
        )
        if w_cells is None:
            continue
        price = w_cells * _avg_cell_price_for_quality(q, csv_cells_raw, pricing)
        ex = max(0.0, w_cells - 1.0)
        total_excess += ex
        if len(per_item) < 48:
            per_item.append(
                {
                    "uid": str(uid),
                    "quality": q,
                    "price_used": round(price, 4),
                    "price_label": "weighted_equiv",
                    "avg_cell_unit": round(_avg_cell_price_for_quality(q, csv_cells_raw, pricing), 4),
                    "weighted_cell_equiv": round(w_cells, 6),
                    "excess_over_one_cell": round(ex, 6),
                }
            )

    if n_uc == 0:
        return 0.0, {}

    return total_excess, {
        "early_unknown_contour_vacant_linear_adjust": True,
        "unknown_contour_items": n_uc,
        "weighted_cell_excess_sum": round(total_excess, 6),
        "detail_per_item": per_item,
    }


def _quality_scan_hit_uids_by_value_from_snapshot(
    board_snapshot: Dict[str, Any],
) -> Dict[int, frozenset[str]]:
    """
    解析 ``game_state.scan_history`` 中 ``scan_type == quality`` 的记录。

    同一 ``value`` 出现多次时取**最后一条**（与对局内追加顺序一致）。未出现过的品质档位不做键，
    表示该档尚未通过「品质扫描」否定任何物品。
    """
    gs = board_snapshot.get("game_state")
    if not isinstance(gs, dict):
        return {}
    rows = gs.get("scan_history") or []
    if not isinstance(rows, list):
        return {}
    last: Dict[int, frozenset[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        st = str(row.get("scan_type") or "").strip().lower()
        if st != "quality":
            continue
        try:
            v = int(row.get("value"))
        except (TypeError, ValueError):
            continue
        if v < 1 or v > 6:
            continue
        hit_uids = row.get("hit_uids") or []
        if not isinstance(hit_uids, list):
            continue
        last[v] = frozenset(str(x) for x in hit_uids)
    return last


def _possible_qualities_from_scan_history(board_snapshot: Dict[str, Any]) -> frozenset[int]:
    """
    仅使用 ``game_state.scan_history`` 中的 ``quality`` 记录推断**空格（空置格）**仍可能的品质集合；
    不读取 ``items`` 等其它对象。

    某档位 ``v`` 一旦出现品质扫描记录（同一 ``value`` 多条时取最后一条，见
    ``_quality_scan_hit_uids_by_value_from_snapshot``），则空格不可能是该档：空 ``hit_uids`` 表示该档在板上
    无对应物件；非空时命中仅含已有 uid，空格无 uid，故不可能等于已用扫描「钉死」过该档的情形。

    从未在 ``scan_history`` 中出现品质扫描的档位仍可能为空格品质。无 ``quality`` 扫描记录时返回全集
    ``{1,…,6}``（对应 CSV 键 ``all``）。
    """
    quality_hits = _quality_scan_hit_uids_by_value_from_snapshot(board_snapshot)
    all_q = frozenset(range(1, 7))
    if not quality_hits:
        return all_q
    scanned_v = frozenset(v for v in quality_hits if 1 <= v <= 6)
    return frozenset(q for q in all_q if q not in scanned_v)


_possible_qualities_from_negative_constraints = _possible_qualities_from_scan_history


def _csv_quality_group_from_possible_set(possible: frozenset[int]) -> Optional[str]:
    """
    将全局仍可能品质集合映射为 ``map_quality_avg_out.csv`` 中的 ``quality_group`` 键。

    仅当 ``possible`` 为全集 ``{1,…,6}`` 时使用 ``all``；否则为按编号排序的 ``q1+q5+…``，须与 CSV 行完全一致。
    """
    if not possible:
        return None
    all_q = frozenset(range(1, 7))
    if not possible <= all_q:
        return None
    if possible == all_q:
        return "all"
    return "+".join(f"q{i}" for i in sorted(possible))


def _vacant_early_unit_from_exclusions(
    *,
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    csv_cells: Optional[Dict[str, float]],
    blends: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
) -> Tuple[int, str, frozenset[int]]:
    """早期回合：由 ``scan_history`` 品质扫描得到全局品质集合，**精确**对应 CSV 行取格均价；无键或缺行则为 0。"""
    _ = blends, pricing
    possible = _possible_qualities_from_scan_history(board_snapshot)
    qg = _csv_quality_group_from_possible_set(possible)
    if qg is None:
        return 0, "", possible
    use_blend = qg in ("q2+q3", "q3") and csv_cells is not None
    src = csv_cells if use_blend else csv_cells_raw
    if not src or qg not in src:
        return 0, qg, possible
    return int(round(float(src[qg]))), qg, possible


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
    s = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed"):
            continue
        if it.get("shape") is None:
            continue
        pr = it.get("price")
        if pr is None:
            continue
        try:
            s += int(round(float(pr)))
        except (TypeError, ValueError):
            continue
    return s


def _count_unconfirmed_contour_quality_items(board_snapshot: Dict[str, Any], quality: int) -> int:
    n = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) != quality:
                continue
        except (TypeError, ValueError):
            continue
        if not it.get("box_id_confirmed") or it.get("shape") is None:
            n += 1
    return n


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
    blends: Optional[Dict[str, float]],
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
        float(blends[key])
        if blends and float(blends.get(key) or 0) > 0
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
    csv_tab = load_map_quality_cells_by_map_id(snapshot_path_hint)
    csv_cells_raw = csv_tab.get(mid_csv) if mid_csv is not None else None
    csv_cells: Optional[Dict[str, float]] = dict(csv_cells_raw) if csv_cells_raw else None
    blends = (
        load_map_quality_blends_by_map_id(snapshot_path_hint).get(mid_csv)
        if mid_csv is not None
        else None
    )
    if csv_cells is not None and blends is not None:
        csv_cells["q2+q3"] = blends["q2+q3_cell"]
        csv_cells["q3"] = blends["q3_cell"]
    csv_hit = bool(csv_cells_raw)

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
            csv_cells=csv_cells,
            blends=blends,
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
            uq5 = _vacant_cell_unit(csv_cells_raw, "q5", pricing, "vacant_unit_q5", _DEFAULT_UNIT_Q5)
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
            float(blends["q5_item"])
            if blends and float(blends.get("q5_item") or 0) > 0
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
                blends=blends,
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
            uq6 = _vacant_cell_unit(csv_cells_raw, "q6", pricing, "vacant_unit_all_red", _DEFAULT_UNIT_Q6)
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
                        float(blends["q6_item"])
                        if blends and float(blends.get("q6_item") or 0) > 0
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
                blends=blends,
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
            "map_quality_avg_csv": map_quality_csv_path_resolved(snapshot_path_hint),
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

    unit_q5 = _vacant_cell_unit(csv_cells_raw, "q5", pricing, "vacant_unit_q5", _DEFAULT_UNIT_Q5)
    unit_q5_q6 = _vacant_cell_unit(
        csv_cells_raw, "q5+q6", pricing, "vacant_unit_q5_q6", _DEFAULT_UNIT_Q5_Q6
    )
    unit_q6 = _vacant_cell_unit(csv_cells_raw, "q6", pricing, "vacant_unit_all_red", _DEFAULT_UNIT_Q6)

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
            blends=blends,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            blends=blends,
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
            blends=blends,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            blends=blends,
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
            blends=blends,
            quality=5,
            default_item_unit=32629.7684,
        )
        lr, nr = _lift_vac_pts_for_avg_price_map_skill(
            map_skill_cid=MAP_SKILL_AVG_RED_PRICE,
            vac_pts_component=red_vac_pts,
            board_snapshot=board_snapshot,
            map_skills=map_skills,
            skip_quality_extras=skip_red_extras,
            blends=blends,
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
            blends=blends,
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
        "map_quality_avg_csv": map_quality_csv_path_resolved(snapshot_path_hint),
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
    *,
    total: float,
    raw_vacant: Optional[int],
    sum_gold_red_min_minus_weighted: float,
    map_id: int,
    current_round: int,
    skill_logs: List[dict],
    game_state_json: Dict[str, Any],
    snapshot_path_hint: Optional[str] = None,
    vacant_occupied_cell_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    组装写入 ``board_snapshot.json`` 的 ``pricing`` 字段（含 ``aisha_bid``、三档仓位总价与 ``known_items_total``）。

    ``vacant_occupied_cell_count``：画板占位格数（含幽灵等）；若省略则从 ``game_state_json`` 单独推导日志物品占位，
    与界面 ``_build_occupied()`` 可能略有差异。
    """
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

    u_orange, u_gr, u_red, csv_hit = vacant_unit_prices_for_map_id(int(map_id or 0), snapshot_path_hint)
    est_orange = total + vacant_num * u_orange
    est_gold_red = total + vacant_num * u_gr
    est_red = total + vacant_num * u_red
    est_floor = total + sum_gold_red_min_minus_weighted + vacant_num * u_orange
    path_used = map_quality_csv_path_resolved(snapshot_path_hint)

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

    board_snap = {
        "game_state": game_state_json,
        "skill_logs": list(skill_logs or []),
        "pricing": pricing,
        "current_round": int(current_round),
        "map_id": int(map_id or 0),
    }
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
