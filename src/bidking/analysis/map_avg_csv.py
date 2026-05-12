"""``map_quality_avg_out.csv`` 加载与按地图 quality_group → 单格均价/件均价。"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional, Tuple

_map_quality_cells_cache: Optional[Dict[int, Dict[str, float]]] = None
_map_quality_csv_override: Optional[str] = None
_map_prefix3_to_min_map_id_cache: Optional[Dict[str, int]] = None


def set_map_quality_csv_override(path: Optional[str]) -> None:
    global _map_quality_cells_cache, _map_quality_csv_override
    global _map_prefix3_to_min_map_id_cache
    _map_quality_csv_override = path
    _map_quality_cells_cache = None
    _map_prefix3_to_min_map_id_cache = None


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
    try:
        from bidking.config.paths import data_dir

        out.append(str(data_dir() / "map_quality_avg_out.csv"))
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


def map_id_prefix3(map_id: int) -> str:
    """``map_id`` 的前三位十进制数字（子图族键）；如 ``2306`` → ``\"230\"``。"""
    s = str(int(map_id))
    if len(s) >= 3:
        return s[:3]
    return s.zfill(3)


def load_prefix3_to_min_map_id(
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, int]:
    """
    从 ``map_quality_avg_out.csv`` 的 ``map_id`` 列汇总：同一前三位前缀下取**最小**
    ``map_id`` 作为该族代表（子图共享同一张入场价表时，与 ``runtime.json`` 的
    ``maps`` / ``map_entry_ticket_by_map_id`` 对齐用）。
    """
    global _map_prefix3_to_min_map_id_cache
    if _map_quality_csv_override is None and _map_prefix3_to_min_map_id_cache is not None:
        return _map_prefix3_to_min_map_id_cache
    by_p: Dict[str, List[int]] = {}
    path = map_quality_csv_path_resolved(snapshot_path_hint)
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    try:
                        mid = int(row["map_id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if mid <= 0:
                        continue
                    pfx = map_id_prefix3(mid)
                    by_p.setdefault(pfx, []).append(mid)
        except OSError:
            by_p = {}
    out = {p: min(ids) for p, ids in by_p.items() if ids}
    if _map_quality_csv_override is None:
        _map_prefix3_to_min_map_id_cache = out
    return out


def representative_map_id_for_ticket(
    map_id: int, snapshot_path_hint: Optional[str] = None
) -> Tuple[int, str]:
    """
    返回 ``(代表 map_id, 前三位前缀)``；若 CSV 中无此前缀则代表为自身 ``map_id``。
    """
    mid = int(map_id)
    pfx = map_id_prefix3(mid)
    rep = load_prefix3_to_min_map_id(snapshot_path_hint).get(pfx, mid)
    return int(rep), pfx


__all__ = [
    "load_map_quality_cells_by_map_id",
    "load_prefix3_to_min_map_id",
    "map_id_prefix3",
    "map_quality_csv_path_resolved",
    "representative_map_id_for_ticket",
    "set_map_quality_csv_override",
]
