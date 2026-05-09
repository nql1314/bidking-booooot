"""扫描历史 / 负向约束 → 空格仍可能的品质（推断）。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def quality_scan_hit_uids_by_value(board_snapshot: Dict[str, Any]) -> Dict[int, frozenset[str]]:
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


def possible_qualities_from_scan_history(board_snapshot: Dict[str, Any]) -> frozenset[int]:
    quality_hits = quality_scan_hit_uids_by_value(board_snapshot)
    all_q = frozenset(range(1, 7))
    if not quality_hits:
        return all_q
    scanned_v = frozenset(v for v in quality_hits if 1 <= v <= 6)
    return frozenset(q for q in all_q if q not in scanned_v)


possible_qualities_from_negative_constraints = possible_qualities_from_scan_history


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

__all__ = [
    "csv_quality_group_from_possible_set",
    "possible_qualities_from_negative_constraints",
    "possible_qualities_from_scan_history",
    "quality_scan_hit_uids_by_value",
    "vacant_early_unit_from_exclusions",
]
