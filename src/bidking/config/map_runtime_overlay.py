"""按当前选中地图合并 ``configs/pricing.maps/<map_id>.json`` 到运行时 config。

GUI 将兜底价、封顶、``bid_ratio_by_round`` 等写入地图文件；
:func:`merged_runtime_with_map_pricing` 在出价计算前叠加以便与 bot 主配置一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import pricing_map_overlay_path
from .pricing import deep_merge


def automation_maps_sorted_keys(maps: Mapping[str, Any]) -> list[str]:
    """``automation.maps`` 的顶层键，按数字序（可解析为 int）否则字典序。"""
    if not isinstance(maps, dict) or not maps:
        return []

    def sort_key(k: str) -> tuple:
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)

    out = [str(k) for k in maps.keys() if isinstance(maps.get(k), dict)]
    return sorted(out, key=sort_key)


def resolve_automation_map_config_key(auto_d: Mapping[str, Any]) -> str:
    """
    解析用于 ``automation.maps`` / ``pricing.maps/<id>.json`` 的地图配置键。

    优先 ``selected_map``，否则 ``default_map``；均无效时取 ``maps`` 排序后的第一个；
    无 ``maps`` 时兜底 ``\"210\"``（与 GUI 三位地图 id 约定一致）。
    """
    maps = auto_d.get("maps") if isinstance(auto_d.get("maps"), dict) else {}
    keys = automation_maps_sorted_keys(maps)
    sel = str(auto_d.get("selected_map") or "").strip()
    if sel and sel in maps and isinstance(maps.get(sel), dict):
        return sel
    dm = str(auto_d.get("default_map") or "").strip()
    if dm and dm in maps and isinstance(maps.get(dm), dict):
        return dm
    if keys:
        return keys[0]
    return "210"


def merged_runtime_with_map_pricing(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return dict(config)
    auto = config.get("automation")
    auto_d = auto if isinstance(auto, dict) else {}
    mid = resolve_automation_map_config_key(auto_d)
    p: Path = pricing_map_overlay_path(mid)
    if not p.is_file():
        return dict(config)
    try:
        overlay = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(config)
    if not isinstance(overlay, dict):
        return dict(config)
    return deep_merge(dict(config), overlay)
