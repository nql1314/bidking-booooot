# -*- coding: utf-8 -*-
"""技能日志 → ``event_stats`` 标量与轮廓补全（非守恒推理）。

本模块负责：

- **合并** ``HeroSkillLog`` / ``MapSkillLog`` / ``ItemSkillLog`` 为 ``skill_entries``（含英雄并入地图键、道具并入规范 SkillCid）。
- **属性 ↔ 技能溯源**（:data:`EVENT_STATS_ATTRIBUTE_SOURCES`）：说明每个 ``event_stats`` 键可由哪些
  ``SkillCid`` / ``ItemCid`` 与日志字段提供；同一键可对应**多条**来源（多技能或地图+英雄+道具先后覆盖同一合并键）。
- **解析**：从合并后的 ``skill_entries`` 直读整数字段、浮点字段、地图价绑定，以及从轮廓类技能的 ``HitBoxList`` 汇总件数/占格。

守恒推算、分档零一致性、CSV 组合下界等**推理**仍在 :mod:`bidking.analysis.raw_pricing`。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..parsing.skill_bindings import (
    HERO_SKILL_CID_MERGE_INTO_MAP,
    ITEM_SKILL_CANONICAL_SKILL_CID,
    OUTLINE_SKILL_QUALITY,
    RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS,
    RAW_PRICING_DIRECT_ITEM_INT_BINDINGS,
    RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS,
    RAW_PRICING_DIRECT_SKILL_INT_BINDINGS,
)


def _collect_attribute_sources() -> Dict[str, Tuple[str, ...]]:
    """由绑定表与合并规则生成「属性 → 人类可读来源列表」。"""
    src: Dict[str, List[str]] = {}

    def add(attr: str, note: str) -> None:
        src.setdefault(attr, []).append(note)

    for key, cid, field in RAW_PRICING_DIRECT_SKILL_INT_BINDINGS:
        add(key, f"SkillCid={cid} {field} (Map/Hero 合并键)")
    for key, cid, field in RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS:
        add(key, f"SkillCid={cid} {field} (Map/Hero 合并键)")
    for key, cid, field in RAW_PRICING_DIRECT_ITEM_INT_BINDINGS:
        add(key, f"ItemSkillLog ItemCid={cid} {field}")
    for key, cid, field in RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS:
        add(key, f"ItemSkillLog ItemCid={cid} {field}")
    for hero_cid, canon in HERO_SKILL_CID_MERGE_INTO_MAP.items():
        for key, cid, _f in RAW_PRICING_DIRECT_SKILL_INT_BINDINGS + RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS:
            if cid == canon:
                add(key, f"HeroSkillLog {hero_cid} 并入规范键 {canon}")
    for item_cid, canon in ITEM_SKILL_CANONICAL_SKILL_CID.items():
        for key, c2, _f in RAW_PRICING_DIRECT_SKILL_INT_BINDINGS + RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS:
            if c2 == canon:
                add(key, f"ItemSkillLog ItemCid={item_cid} 并入规范键 {canon}")
    for q in range(1, 7):
        note = f"轮廓 HitBoxList（OUTLINE_SKILL_QUALITY 品质{q}）"
        add(f"q{q}_count", note)
        add(f"q{q}_grid_count", note)
        add(f"q{q}_grid_avg", note)

    return {k: tuple(v) for k, v in src.items()}


#: ``event_stats`` 键 → 可能提供该值的日志/技能来源说明（多源并存）
EVENT_STATS_ATTRIBUTE_SOURCES: Dict[str, Tuple[str, ...]] = _collect_attribute_sources()


def merge_latest_skill_entries(skill_logs: List[dict]) -> Dict[int, dict]:
    """将多段 ``skill_logs`` 合并为 ``SkillCid`` / ``ItemCid`` → 最新一条日志条目。"""
    out: Dict[int, dict] = {}
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for key in ("HeroSkillLog", "MapSkillLog", "ItemSkillLog"):
            for entry in gd.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                try:
                    cid = int(entry.get("SkillCid") or 0)
                except (TypeError, ValueError):
                    continue
                if cid > 0:
                    out[cid] = entry
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for key in ("HeroSkillLog", "MapSkillLog", "ItemSkillLog"):
            for entry in gd.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                try:
                    cid = int(entry.get("SkillCid") or 0)
                except (TypeError, ValueError):
                    continue
                if cid <= 0:
                    continue
                canon = HERO_SKILL_CID_MERGE_INTO_MAP.get(cid)
                if canon and canon not in out:
                    out[canon] = entry
    for block in skill_logs or []:
        if not isinstance(block, dict):
            continue
        gd = block.get("game_data") or {}
        if not isinstance(gd, dict):
            continue
        for entry in gd.get("ItemSkillLog") or []:
            if not isinstance(entry, dict):
                continue
            try:
                item_cid = int(entry.get("ItemCid") or 0)
            except (TypeError, ValueError):
                continue
            canon = ITEM_SKILL_CANONICAL_SKILL_CID.get(item_cid)
            if canon:
                out[canon] = entry
            if item_cid > 0:
                out[item_cid] = entry
    return out


def safe_int_field(entry: Optional[dict], *keys: str) -> Optional[int]:
    if not isinstance(entry, dict):
        return None
    for k in keys:
        v = entry.get(k)
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def safe_float_field(entry: Optional[dict], *keys: str) -> Optional[float]:
    if not isinstance(entry, dict):
        return None
    for k in keys:
        v = entry.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def item_skill_int_if_logged(
    skill_entries: Dict[int, dict], item_cid: int, log_field: str
) -> Optional[int]:
    ent = skill_entries.get(int(item_cid))
    if not isinstance(ent, dict):
        return None
    return safe_int_field(ent, log_field)


def item_skill_float_if_logged(
    skill_entries: Dict[int, dict], item_cid: int, log_field: str
) -> Optional[float]:
    ent = skill_entries.get(int(item_cid))
    if not isinstance(ent, dict):
        return None
    v = safe_float_field(ent, log_field)
    if v is None or v != v:
        return 0.0
    return float(v)


def _shape_cell_count(slot_type: Any) -> int:
    if slot_type is None:
        return 0
    try:
        s = str(int(slot_type))
    except (TypeError, ValueError):
        return 0
    if len(s) == 2:
        return max(0, int(s[0]) * int(s[1]))
    return max(0, int(s))


def _aggregate_hitbox_list(boxes: List[dict]) -> Dict[str, Any]:
    count = 0
    total_cells = 0
    for box in boxes or []:
        if not isinstance(box, dict):
            continue
        if not box.get("ItemUid"):
            continue
        count += 1
        total_cells += _shape_cell_count(box.get("ItemSlotType"))
    avg_cells = (total_cells / count) if count else None
    return {
        "count": count,
        "total_cells": total_cells,
        "avg_cells": avg_cells,
    }


def _best_outline_aggregate_for_quality(
    skill_entries: Dict[int, dict], quality: int
) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_n = -1
    for cid, q in OUTLINE_SKILL_QUALITY.items():
        if q != quality:
            continue
        entry = skill_entries.get(cid)
        if not isinstance(entry, dict):
            continue
        boxes = entry.get("HitBoxList") or []
        if not isinstance(boxes, list):
            continue
        agg = _aggregate_hitbox_list(boxes)
        if agg["count"] > best_n:
            best_n = agg["count"]
            best = agg
    return best


def apply_outline_hitbox_to_event_stats(
    skill_entries: Dict[int, dict], direct: Dict[str, Any]
) -> None:
    """用轮廓类技能的 ``HitBoxList`` 补 ``q1``–``q6`` 件数/占格/均格（不推导价格）。"""
    for q in (1, 2, 3, 4, 5, 6):
        agg = _best_outline_aggregate_for_quality(skill_entries, q)
        if agg is None or agg["count"] <= 0:
            continue
        if q == 1:
            if direct["q1_count"] in (None, 0):
                direct["q1_count"] = int(agg["count"])
            if not direct["q1_grid_count"] and agg["total_cells"]:
                direct["q1_grid_count"] = int(agg["total_cells"])
        if q == 2:
            if direct["q2_count"] in (None, 0):
                direct["q2_count"] = int(agg["count"])
            if not direct["q2_grid_count"] and agg["total_cells"]:
                direct["q2_grid_count"] = int(agg["total_cells"])
        if q == 3:
            if direct["q3_count"] in (None, 0):
                direct["q3_count"] = int(agg["count"])
            if not direct["q3_grid_count"] and agg["total_cells"]:
                direct["q3_grid_count"] = int(agg["total_cells"])
        if q == 4:
            if direct["q4_count"] in (None, 0):
                direct["q4_count"] = int(agg["count"])
            if not direct["q4_grid_count"] and agg["total_cells"]:
                direct["q4_grid_count"] = int(agg["total_cells"])
            if direct["q4_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q4_grid_avg"] = float(agg["avg_cells"])
        if q == 5:
            if direct["q5_count"] in (None, 0):
                direct["q5_count"] = int(agg["count"])
            if not direct["q5_grid_count"] and agg["total_cells"]:
                direct["q5_grid_count"] = int(agg["total_cells"])
            if direct["q5_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q5_grid_avg"] = float(agg["avg_cells"])
        if q == 6:
            if direct["q6_count"] in (None, 0):
                direct["q6_count"] = int(agg["count"])
            if not direct["q6_grid_count"] and agg["total_cells"]:
                direct["q6_grid_count"] = int(agg["total_cells"])
            if direct["q6_grid_avg"] is None and agg["avg_cells"] is not None:
                direct["q6_grid_avg"] = float(agg["avg_cells"])


def _write_skill_int_fields_from_logs(
    skill_entries: Dict[int, dict], direct: Dict[str, Any]
) -> None:
    """地图/英雄/道具技能行合并键上的整型直读（绑表见 ``RAW_PRICING_DIRECT_SKILL_INT_BINDINGS``）。"""
    for key, cid, field in RAW_PRICING_DIRECT_SKILL_INT_BINDINGS:
        direct[key] = safe_int_field(skill_entries.get(cid), field)


def _write_skill_float_fields_from_logs(
    skill_entries: Dict[int, dict], direct: Dict[str, Any]
) -> None:
    """同上，浮点直读（``RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS``）。"""
    for key, cid, field in RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS:
        direct[key] = safe_float_field(skill_entries.get(cid), field)


def _write_item_int_fields_from_logs(
    skill_entries: Dict[int, dict], direct: Dict[str, Any]
) -> None:
    """``ItemSkillLog`` 整型直读（``RAW_PRICING_DIRECT_ITEM_INT_BINDINGS``）。"""
    for key, cid, field in RAW_PRICING_DIRECT_ITEM_INT_BINDINGS:
        v = item_skill_int_if_logged(skill_entries, cid, field)
        if v is not None:
            direct[key] = v


def _write_item_float_fields_from_logs(
    skill_entries: Dict[int, dict], direct: Dict[str, Any]
) -> None:
    """``ItemSkillLog`` 浮点直读（``RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS``）。"""
    for key, cid, field in RAW_PRICING_DIRECT_ITEM_FLOAT_BINDINGS:
        direct[key] = item_skill_float_if_logged(skill_entries, cid, field)


def parse_skill_entries_to_event_stats_direct(
    skill_entries: Dict[int, dict],
) -> Dict[str, Any]:
    """从合并日志解析标量 ``event_stats`` 并应用轮廓补全。

    不含 ``random_avg_price_min``（由 :mod:`bidking.analysis.raw_pricing` 推理写入）。
    """
    direct: Dict[str, Any] = {
        "total_count": None,
        "total_grid_count": None,
        "total_grid_avg": None,
        "random_avg_price_min": None,
        "q1_count": None,
        "q1_grid_count": None,
        "q1_price_total": None,
        "q2_count": None,
        "q2_grid_count": None,
        "q2_price_total": None,
        "q12_count": None,
        "q12_grid_count": None,
        "q12_grid_avg": None,
        "q12_price_total": None,
        "q3_count": None,
        "q3_grid_count": None,
        "q3_grid_avg": None,
        "q3_price_total": None,
        "q4_count": None,
        "q4_grid_count": None,
        "q4_grid_avg": None,
        "q4_count_min": None,
        "q4_grid_min": None,
        "q4_price_avg": None,
        "q4_price_total": None,
        "q5_count": None,
        "q5_count_min": None,
        "q5_grid_count": None,
        "q5_grid_avg": None,
        "q5_grid_min": None,
        "q5_price_avg": None,
        "q5_price_total": None,
        "q6_count": None,
        "q6_count_min": None,
        "q6_grid_count": None,
        "q6_grid_avg": None,
        "q6_grid_min": None,
        "q6_price_avg": None,
        "q6_price_total": None,
    }

    _write_skill_int_fields_from_logs(skill_entries, direct)
    _write_skill_float_fields_from_logs(skill_entries, direct)
    _write_item_int_fields_from_logs(skill_entries, direct)
    _write_item_float_fields_from_logs(skill_entries, direct)

    apply_outline_hitbox_to_event_stats(skill_entries, direct)
    return direct


def parse_skill_logs_to_event_stats_direct(skill_logs: List[dict]) -> Dict[str, Any]:
    """``skill_logs`` → 合并 → 标量 + 轮廓 ``event_stats``（不含随机均价推理）。"""
    return parse_skill_entries_to_event_stats_direct(merge_latest_skill_entries(list(skill_logs or [])))
