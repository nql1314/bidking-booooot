"""从画板 JSON 快照构造与「中央区 OCR」等价的 ``parsed_patch``，供 ahmad_premium 使用。

快照内 ``raw_pricing.event_stats`` 与 ``skill_logs`` 由 analysis 层写入；
本模块只做字段映射，不包含任何加价策略逻辑。
"""

from __future__ import annotations

from typing import Any

from ..analysis.raw_pricing import _merge_latest_skill_entries, _safe_float_field
from ..analysis.quality_stats import count_quality_items_all, sum_quality_footprint_cells
from ..parsing.constants import (
    MAP_SKILL_RANDOM3_AVG_PRICE,
    MAP_SKILL_RANDOM6_AVG_PRICE,
    MAP_SKILL_RANDOM9_AVG_PRICE,
)


def _empty_constraints() -> dict[str, dict[str, Any]]:
    """pricing 层使用的约束占位结构（与历史中央区解析字段对齐，供快照补丁使用）。"""
    return {
        "wg": {"avg": None, "count": None, "grid": None, "min_count": None},
        "blue": {"avg": None, "count": None, "grid": None, "min_count": None},
        "purple": {"avg": None, "count": None, "grid": None, "min_count": None},
        "gold": {"avg": None, "count": None, "grid": None, "min_count": None},
        "red": {"avg": None, "count": None, "grid": None, "min_count": None},
    }


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _append_fact(out: dict[str, Any], field: str, value: Any, line: str) -> None:
    out.setdefault("parsed_facts", []).append({"field": field, "value": value, "line": line})


def random_pick_from_snapshot(snapshot: dict[str, Any]) -> tuple[int | None, float | None]:
    """从最新地图技能日志解析「随机 n 件均价」；n 由技能 CID 固定为 3/6/9。"""
    logs = snapshot.get("skill_logs") or []
    ent = _merge_latest_skill_entries(list(logs))
    for cid, n in (
        (MAP_SKILL_RANDOM3_AVG_PRICE, 3),
        (MAP_SKILL_RANDOM6_AVG_PRICE, 6),
        (MAP_SKILL_RANDOM9_AVG_PRICE, 9),
    ):
        e = ent.get(cid)
        if not isinstance(e, dict):
            continue
        avg = _safe_float_field(e, "AllHitItemAvgPrice")
        if avg is not None and avg > 0:
            return n, float(avg)
    return None, None


def min_price_points_from_snapshot(snapshot: dict[str, Any]) -> int | None:
    """替代底价区 OCR：优先 ``event_stats.total_price_min``（与 raw_pricing 构建一致）。"""
    raw = snapshot.get("raw_pricing") or {}
    es = raw.get("event_stats") or {}
    v = es.get("total_price_min")
    if v is None:
        return None
    return _as_int(v)


def build_central_parsed_patch_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """由画板快照生成中央区风格的补丁 dict（供 pricing / 分析层消费）。"""
    raw = snapshot.get("raw_pricing") or {}
    es = dict(raw.get("event_stats") or {})

    q1 = _as_int(es.get("q1_count"))
    q2 = _as_int(es.get("q2_count"))
    if q1 is None:
        q1 = count_quality_items_all(snapshot, 1)
    if q2 is None:
        q2 = count_quality_items_all(snapshot, 2)

    q12 = _as_int(es.get("q12_count"))
    if q12 is None and q1 is not None and q2 is not None:
        q12 = int(q1) + int(q2)

    total_all = _as_int(es.get("total_count"))
    if total_all is None:
        total_all = sum(count_quality_items_all(snapshot, q) for q in range(1, 7))

    total_grid = _as_int(es.get("total_grid_count"))
    if total_grid is None:
        total_grid = sum(sum_quality_footprint_cells(snapshot, q) for q in range(1, 7))

    avg_grid = _as_float(es.get("total_grid_avg"))
    if (
        avg_grid is None
        and total_all is not None
        and total_all > 0
        and total_grid is not None
        and total_grid > 0
    ):
        avg_grid = round(float(total_grid) / float(total_all), 6)

    constraints = _empty_constraints()

    def fill_color(color: str, q: int) -> None:
        c = _as_int(es.get(f"q{q}_count"))
        if c is None and q >= 3:
            c = count_quality_items_all(snapshot, q)
        g = _as_int(es.get(f"q{q}_grid_count"))
        if g is None and q >= 3:
            g = sum_quality_footprint_cells(snapshot, q)
        ag = _as_float(es.get(f"q{q}_grid_avg"))
        if ag is None and c is not None and g is not None and c > 0:
            ag = round(float(g) / float(c), 6)
        mnc = _as_int(es.get(f"q{q}_count_min")) if q >= 4 else None
        co = constraints[color]
        if c is not None:
            co["count"] = c
        if g is not None:
            co["grid"] = g
        if ag is not None:
            co["avg"] = ag
        if mnc is not None and co.get("count") is None:
            co["min_count"] = mnc

    fill_color("blue", 3)
    fill_color("purple", 4)
    fill_color("gold", 5)
    fill_color("red", 6)

    snap_round = snapshot.get("current_round")
    if snap_round is None:
        snap_round = (snapshot.get("game_state") or {}).get("current_round")
    round_v = _as_int(snap_round)

    out: dict[str, Any] = {
        "constraints": constraints,
        "parsed_facts": [],
        "unparsed_lines": [],
    }
    if round_v is not None:
        out["round"] = round_v
        _append_fact(out, "round", round_v, "snapshot:current_round")

    if total_all is not None:
        out["total_all"] = int(total_all)
        _append_fact(out, "total_all", int(total_all), "snapshot:event_stats.total_count")
    if total_grid is not None:
        out["total_grid_all"] = int(total_grid)
        _append_fact(out, "total_grid_all", int(total_grid), "snapshot:event_stats.total_grid_count")
    if avg_grid is not None:
        out["avg_grid_all"] = float(avg_grid)
        _append_fact(out, "avg_grid_all", float(avg_grid), "snapshot:event_stats.total_grid_avg")
    if q1 is not None:
        out["count_white"] = int(q1)
        _append_fact(out, "count_white", int(q1), "snapshot:q1_count")
    if q2 is not None:
        out["count_green"] = int(q2)
        _append_fact(out, "count_green", int(q2), "snapshot:q2_count")
    if q12 is not None:
        out["wg_total"] = int(q12)
        _append_fact(out, "wg_total", int(q12), "snapshot:q12_count")

    ap4 = _as_float(es.get("q4_price_avg"))
    if ap4 is not None:
        out["avg_price_purple"] = float(ap4)
        _append_fact(out, "avg_price_purple", float(ap4), "snapshot:q4_price_avg")
    tt4 = _as_int(es.get("q4_price_total"))
    if tt4 is not None:
        out["total_price_purple"] = float(tt4)
        _append_fact(out, "total_price_purple", float(tt4), "snapshot:q4_price_total")

    ap5 = _as_float(es.get("q5_price_avg"))
    if ap5 is not None:
        out["avg_price_gold"] = float(ap5)
        _append_fact(out, "avg_price_gold", float(ap5), "snapshot:q5_price_avg")
    tt5 = _as_int(es.get("q5_price_total"))
    if tt5 is not None:
        out["total_price_gold"] = float(tt5)
        _append_fact(out, "total_price_gold", float(tt5), "snapshot:q5_price_total")

    ap6 = _as_float(es.get("q6_price_avg"))
    if ap6 is not None:
        out["avg_price_red"] = float(ap6)
        _append_fact(out, "avg_price_red", float(ap6), "snapshot:q6_price_avg")
    tt6 = _as_int(es.get("q6_price_total"))
    if tt6 is not None:
        out["total_price_red"] = float(tt6)
        _append_fact(out, "total_price_red", float(tt6), "snapshot:q6_price_total")

    tmin = _as_int(es.get("total_price_min"))
    if tmin is not None:
        out["observed_low_price"] = float(tmin)
        _append_fact(out, "observed_low_price", float(tmin), "snapshot:total_price_min")

    pick_n, pick_avg = random_pick_from_snapshot(snapshot)
    if pick_n is not None and pick_avg is not None:
        out["random_pick_count"] = int(pick_n)
        out["random_pick_avg_price"] = float(pick_avg)
        _append_fact(out, "random_pick_count", int(pick_n), "snapshot:MapSkillLog random")
        _append_fact(out, "random_pick_avg_price", float(pick_avg), "snapshot:MapSkillLog random")

    return out


__all__ = [
    "build_central_parsed_patch_from_snapshot",
    "min_price_points_from_snapshot",
    "random_pick_from_snapshot",
]
