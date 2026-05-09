"""pricing.json 加载与按地图深合并覆盖。

Schema 见 ``configs/pricing.json``：``ahmad_premium`` / ``grid_prices`` /
``burst_limit`` / ``avg_tolerance`` / ``round_rules`` / ``category_weights``。

地图覆盖：``configs/pricing.maps/<map_id>.json`` —— 同 schema，对全局做
**深合并**（dict 递归，list 整体替换）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .paths import pricing_map_override_path, pricing_path


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    """递归合并 override 到 base 的副本，dict 按 key 合并，其它类型整体替换。"""
    out: Dict[str, Any] = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], Mapping) and isinstance(v, Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_pricing(path: Optional[Path | str] = None) -> Dict[str, Any]:
    p = Path(path) if path else pricing_path()
    with p.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def resolve_for(map_id: int | str, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """读取全局 pricing 并按 map_id 深合并 override。"""
    if base is None:
        base = load_pricing()
    if map_id is None:
        return dict(base)
    override_path = pricing_map_override_path(map_id)
    if not override_path:
        return dict(base)
    with override_path.open("r", encoding="utf-8") as fp:
        override = json.load(fp)
    return deep_merge(base, override)
