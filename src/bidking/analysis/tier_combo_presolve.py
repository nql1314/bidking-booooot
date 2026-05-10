# -*- coding: utf-8 -*-
"""紫/金/红（Q4–Q6）小件数组合预计算表：无重复子集、``n``≤3。

键 ``"{n},{price_total}"``，值 ``{"price_total": T, "grid_sums": [...]}``（总价与可达总格一并存储）。
"""

from __future__ import annotations

import json
import os
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, TypedDict, cast

from ..parsing.constants import CSV_PATH, resource_path
from ..parsing.state import CsvItem

PRESOLVE_FILENAME = "tier_combo_presolve_q456.json"
PRESOLVE_MAX_N = 3
_QUALITIES = (4, 5, 6)

_JSON_VERSION = 2


class PresolveEntry(TypedDict):
    price_total: int
    grid_sums: List[int]


_cache: Optional[Dict[str, Dict[str, PresolveEntry]]] = None


def _shape_cells(item: CsvItem) -> int:
    try:
        s = str(int(item.shape))
    except (TypeError, ValueError):
        return 0
    if len(s) == 2:
        return max(0, int(s[0]) * int(s[1]))
    return max(0, int(s))


def build_presolve_blob(items: Sequence[CsvItem]) -> Dict[str, Any]:
    qualities: Dict[str, Dict[str, PresolveEntry]] = {}
    for q in _QUALITIES:
        pool = [it for it in items if it.quality == q]
        acc: Dict[str, set[int]] = {}
        for n in range(1, PRESOLVE_MAX_N + 1):
            for combo in combinations(pool, n):
                T = sum(int(x.base_value) for x in combo)
                G = sum(_shape_cells(x) for x in combo)
                key = f"{n},{T}"
                acc.setdefault(key, set()).add(int(G))
        qualities[str(q)] = {
            k: PresolveEntry(price_total=int(k.split(",", 1)[1]), grid_sums=sorted(v))
            for k, v in acc.items()
        }
    return {"version": _JSON_VERSION, "qualities": qualities}


def write_presolve_file(path: str, items: Sequence[CsvItem]) -> None:
    blob = build_presolve_blob(items)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, separators=(",", ":"))


def presolve_json_path() -> str:
    return resource_path(PRESOLVE_FILENAME)


def _parse_row_key(key: str) -> Optional[int]:
    parts = str(key).split(",", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except (TypeError, ValueError):
        return None


def load_presolve_table() -> Dict[str, Dict[str, PresolveEntry]]:
    global _cache
    if _cache is not None:
        return _cache
    path = presolve_json_path()
    if not os.path.isfile(path):
        _cache = {}
        return _cache
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _cache = {}
        return _cache
    inner = blob.get("qualities") or {}
    out: Dict[str, Dict[str, PresolveEntry]] = {}
    for qk, qv in inner.items():
        if not isinstance(qv, dict):
            continue
        row: Dict[str, PresolveEntry] = {}
        for k, v in qv.items():
            sk = str(k)
            if isinstance(v, dict):
                try:
                    pt = int(v["price_total"])
                    gs = [int(x) for x in v["grid_sums"]]
                    row[sk] = PresolveEntry(price_total=pt, grid_sums=sorted(set(gs)))
                except (KeyError, TypeError, ValueError):
                    continue
            elif isinstance(v, list):
                T_guess = _parse_row_key(sk)
                if T_guess is None:
                    continue
                try:
                    gs = sorted({int(x) for x in v})
                except (TypeError, ValueError):
                    continue
                row[sk] = PresolveEntry(price_total=T_guess, grid_sums=gs)
        out[str(qk)] = row
    _cache = out
    return _cache


def presolve_is_ready() -> bool:
    t = load_presolve_table()
    return bool(t) and any(bool(v) for v in t.values())


def presolve_entry(quality: int, n: int, T: int) -> Optional[PresolveEntry]:
    tab = load_presolve_table()
    inner = tab.get(str(int(quality)))
    if not inner:
        return None
    ent = inner.get(f"{int(n)},{int(T)}")
    return cast(Optional[PresolveEntry], ent)


def presolve_grid_sums(quality: int, n: int, T: int) -> Optional[List[int]]:
    """该 ``(品质, n, 总价)`` 下所有可达总格；无表项时 ``None``。"""
    ent = presolve_entry(quality, n, T)
    if ent is None:
        return None
    return list(ent["grid_sums"])


def clear_presolve_cache() -> None:
    global _cache
    _cache = None


if __name__ == "__main__":
    from ..parsing import item_db

    _, items = item_db.load_csv(CSV_PATH)
    out = presolve_json_path()
    write_presolve_file(out, items)
    blob = build_presolve_blob(items)
    nkeys = sum(len(cast(Dict[str, Any], v)) for v in blob["qualities"].values())
    print("wrote", out, "entries", nkeys)
