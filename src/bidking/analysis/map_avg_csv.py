"""``map_quality_avg_out.csv`` 加载与按地图 quality_group → 单格均价/件均价。"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

_map_quality_cells_cache: Optional[Dict[int, Dict[str, float]]] = None
_map_quality_csv_override: Optional[str] = None


def set_map_quality_csv_override(path: Optional[str]) -> None:
    global _map_quality_cells_cache, _map_quality_csv_override
    _map_quality_csv_override = path
    _map_quality_cells_cache = None


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


__all__ = [
    "load_map_quality_cells_by_map_id",
    "map_quality_csv_path_resolved",
    "set_map_quality_csv_override",
]
