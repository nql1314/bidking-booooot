"""扫描历史 / 负向约束 → 空格仍可能的品质（推断）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

from ..parsing.state import ItemKnowledge


def _quality_scan_last_hits_from_game_state(gs: Dict[str, Any]) -> Dict[int, frozenset[str]]:
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


def census_absent_qualities_from_board_snapshot(board_snapshot: Dict[str, Any]) -> frozenset[int]:
    """来自 ``raw_pricing.census_absent_qualities``：分档零一致性后 ``qK_count==0`` 的品质档。"""
    rp = board_snapshot.get("raw_pricing")
    if not isinstance(rp, dict):
        return frozenset()
    xs = rp.get("census_absent_qualities")
    if not isinstance(xs, (list, tuple)):
        return frozenset()
    out: Set[int] = set()
    for x in xs:
        try:
            qi = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= qi <= 6:
            out.add(qi)
    return frozenset(out)


def quality_scan_hit_uids_by_value(board_snapshot: Dict[str, Any]) -> Dict[int, frozenset[str]]:
    """合并 ``game_state.scan_history`` 与 ``raw_pricing.census_absent_qualities``（等价于空 hit 的全图品质负向）。"""
    gs = board_snapshot.get("game_state")
    if isinstance(gs, dict):
        last: Dict[int, frozenset[str]] = dict(_quality_scan_last_hits_from_game_state(gs))
    else:
        last = {}
    for q in census_absent_qualities_from_board_snapshot(board_snapshot):
        if q not in last:
            last[q] = frozenset()
    return last


def possible_qualities_from_scan_history(board_snapshot: Dict[str, Any]) -> frozenset[int]:
    quality_hits = quality_scan_hit_uids_by_value(board_snapshot)
    all_q = frozenset(range(1, 7))
    if not quality_hits:
        return all_q
    scanned_v = frozenset(v for v in quality_hits if 1 <= v <= 6)
    return frozenset(q for q in all_q if q not in scanned_v)


def csv_quality_group_from_possible_set(possible: frozenset[int]) -> Optional[str]:
    if not possible:
        return None
    all_q = frozenset(range(1, 7))
    if not possible <= all_q:
        return None
    if possible == all_q:
        return "all"
    return "+".join(f"q{i}" for i in sorted(possible))


def vacant_early_unit_from_exclusions(
    *,
    board_snapshot: Dict[str, Any],
    csv_cells_raw: Optional[Dict[str, float]],
    pricing: Dict[str, Any],
) -> Tuple[int, str, frozenset[int]]:
    _ = pricing
    possible = possible_qualities_from_scan_history(board_snapshot)
    qg = csv_quality_group_from_possible_set(possible)
    if qg is None:
        return 0, "", possible
    if not csv_cells_raw or qg not in csv_cells_raw:
        return 0, qg, possible
    return int(round(float(csv_cells_raw[qg]))), qg, possible


def apply_census_absent_qualities_from_raw_pricing(
    state_items: Dict[str, ItemKnowledge],
    phantom_items: Dict[str, ItemKnowledge],
    raw_pricing: Optional[Dict[str, Any]],
) -> None:
    """将 ``raw_pricing.census_absent_qualities`` 并入负向：幽灵全量；日志物品仅未知品质。"""
    if not isinstance(raw_pricing, dict):
        return
    xs = raw_pricing.get("census_absent_qualities")
    if not isinstance(xs, (list, tuple)):
        return
    qualities: Set[int] = set()
    for x in xs:
        try:
            qi = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= qi <= 6:
            qualities.add(qi)
    if not qualities:
        return
    for _phid, pk in phantom_items.items():
        for qi in qualities:
            pk.excluded_qualities.add(qi)
    for _uid, k in state_items.items():
        if k.quality is not None:
            continue
        for qi in qualities:
            k.excluded_qualities.add(qi)


__all__ = [
    "apply_census_absent_qualities_from_raw_pricing",
    "census_absent_qualities_from_board_snapshot",
    "csv_quality_group_from_possible_set",
    "possible_qualities_from_scan_history",
    "quality_scan_hit_uids_by_value",
    "vacant_early_unit_from_exclusions",
]
