"""``map_quality_avg_out.csv`` 加载与按地图 quality_group → 单格均价/件均价。"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional, Set, Tuple

_map_quality_cells_cache: Optional[Dict[int, Dict[str, float]]] = None
_map_quality_present_ids_cache: Optional[Set[int]] = None
_map_quality_csv_override: Optional[str] = None
_map_prefix3_to_min_map_id_cache: Optional[Dict[str, int]] = None


def set_map_quality_csv_override(path: Optional[str]) -> None:
    global _map_quality_cells_cache, _map_quality_csv_override
    global _map_prefix3_to_min_map_id_cache, _map_quality_present_ids_cache
    _map_quality_csv_override = path
    _map_quality_cells_cache = None
    _map_prefix3_to_min_map_id_cache = None
    _map_quality_present_ids_cache = None


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
    global _map_quality_cells_cache, _map_quality_present_ids_cache
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
    _map_quality_present_ids_cache = set(tab.keys())
    return tab


def map_ids_in_quality_avg_csv(snapshot_path_hint: Optional[str] = None) -> Set[int]:
    """``map_quality_avg_out.csv`` 中出现过的 ``map_id`` 集合（用于查表回退）。"""
    global _map_quality_present_ids_cache
    if _map_quality_csv_override is None and _map_quality_present_ids_cache is not None:
        return set(_map_quality_present_ids_cache)
    load_map_quality_cells_by_map_id(snapshot_path_hint)
    if _map_quality_present_ids_cache is not None:
        return set(_map_quality_present_ids_cache)
    return set()


def resolve_map_id_for_quality_csv(
    map_id: Optional[int],
    *,
    snapshot_path_hint: Optional[str] = None,
    known_map_ids: Optional[Set[int]] = None,
) -> Optional[int]:
    """
    查 map_quality_* CSV 时使用的 ``map_id``：先 ``normalize_map_id``，无行则对
    25xx/45xx 末两位 21–30 回退到 −20 的基础子图（2501–2510 / 4501–4510 同位）。
    """
    from ..parsing.item_db import normalize_map_id, ship_series_weight_fallback_map_id

    mid = normalize_map_id(map_id)
    if mid is None:
        return None
    present = known_map_ids if known_map_ids is not None else map_ids_in_quality_avg_csv(
        snapshot_path_hint
    )

    def _has_rows(candidate: int) -> bool:
        return candidate in present

    if _has_rows(mid):
        return mid
    fallback = ship_series_weight_fallback_map_id(mid)
    if fallback is not None and _has_rows(fallback):
        return fallback
    return mid


def get_map_quality_cells_for_map(
    map_id: Optional[int],
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, float]:
    """按 ``resolve_map_id_for_quality_csv`` 解析后读取均价 CSV 的 quality_group→格价。"""
    tab = load_map_quality_cells_by_map_id(snapshot_path_hint)
    resolved = resolve_map_id_for_quality_csv(
        map_id,
        snapshot_path_hint=snapshot_path_hint,
        known_map_ids=set(tab.keys()),
    )
    if resolved is None:
        return {}
    return dict(tab.get(resolved, {}))


def map_id_prefix3(map_id: int) -> str:
    """与 :func:`bidking.parsing.item_db.map_bundle_key_for_automation` 一致（历史名保留）。"""
    from ..parsing.item_db import map_bundle_key_for_automation

    return map_bundle_key_for_automation(map_id)


def load_prefix3_to_min_map_id(
    snapshot_path_hint: Optional[str] = None,
) -> Dict[str, int]:
    """
    从 ``map_quality_avg_out.csv`` 的 ``map_id`` 列汇总：同一**档键**
    （:func:`map_id_prefix3`，即前两位末位 0）下取**最小** ``map_id`` 作为该族代表
    （子图共享同一张入场价表时，与 ``runtime.json`` 的 ``maps`` /
    ``map_entry_ticket_by_map_id`` 对齐用）。
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
    返回 ``(代表 map_id, 档键)``；档键与 ``map_bundle_key_for_automation`` 一致。
    CSV 查表经 ``resolve_map_id_for_quality_csv``（活动图 252x→250x，日志 452x 同）。
    """
    mid = int(map_id)
    pfx = map_id_prefix3(mid)
    tab = load_map_quality_cells_by_map_id(snapshot_path_hint)
    known = set(tab.keys())
    resolved = resolve_map_id_for_quality_csv(
        mid,
        snapshot_path_hint=snapshot_path_hint,
        known_map_ids=known,
    )
    if resolved is not None and resolved in known:
        return int(resolved), pfx
    rep = load_prefix3_to_min_map_id(snapshot_path_hint).get(pfx, mid)
    return int(rep), pfx


__all__ = [
    "get_map_quality_cells_for_map",
    "load_map_quality_cells_by_map_id",
    "load_prefix3_to_min_map_id",
    "map_id_prefix3",
    "map_ids_in_quality_avg_csv",
    "map_quality_csv_path_resolved",
    "representative_map_id_for_ticket",
    "resolve_map_id_for_quality_csv",
    "set_map_quality_csv_override",
]
