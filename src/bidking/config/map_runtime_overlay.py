"""合并 ``configs/pricing.maps/<档键>.json`` 到运行时 config。

Bot 策略面板所选地图（``automation.selected_map``）与对局快照中的 ``map_id``（经
:func:`bidking.parsing.item_db.map_bundle_key_for_automation` 得到档键）均可作为覆盖层键；
:func:`merged_runtime_with_map_pricing` 在出价计算前叠加以便与主配置一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import configs_dir, pricing_map_overlay_path
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


def _map_keys_from_pricing_maps_dir(pricing_maps_dir: Path) -> list[str]:
    from ..parsing.item_db import map_bundle_key_for_automation

    if not pricing_maps_dir.is_dir():
        return []
    out: list[str] = []
    for p in pricing_maps_dir.glob("*.json"):
        stem = p.stem.strip()
        if not stem or stem.upper() == "README":
            continue
        if stem.isdigit():
            out.append(map_bundle_key_for_automation(int(stem)))
        else:
            out.append(stem)
    return out


def _map_keys_from_item_db_tiers() -> list[str]:
    """从物品权重表 ``MAP_TO_TIER_NEST`` 推导档键（210、220…260，与 automation 对齐）。"""
    from ..parsing.item_db import MAP_TO_TIER_NEST, map_bundle_key_for_automation

    seen: set[str] = set()
    for mid in MAP_TO_TIER_NEST:
        seen.add(map_bundle_key_for_automation(int(mid)))
    return sorted(seen, key=lambda k: (0, int(k)) if k.isdigit() else (1, k))


def all_strategy_map_editor_keys(
    config: Mapping[str, Any],
    *,
    configs_root: Path | None = None,
) -> list[str]:
    """
    「策略配置」编辑地图下拉的**全集候选**：automation.maps 顶层键、
    ``map_entry_ticket_by_map_id`` 键、``configs/pricing.maps/*.json`` 文件名、
    以及 ``item_db.MAP_TO_TIER_NEST`` 推导的档 id；去重后按数字序排序。
    """
    root = configs_root if configs_root is not None else configs_dir()
    keys: set[str] = set()
    auto = config.get("automation") if isinstance(config.get("automation"), dict) else {}
    maps = auto.get("maps") if isinstance(auto.get("maps"), dict) else {}
    keys.update(automation_maps_sorted_keys(maps))
    tix = auto.get("map_entry_ticket_by_map_id")
    if isinstance(tix, dict):
        from ..parsing.item_db import map_bundle_key_for_automation

        for k in tix:
            ks = str(k).strip()
            if not ks:
                continue
            keys.add(map_bundle_key_for_automation(int(ks)) if ks.isdigit() else ks)
    keys.update(_map_keys_from_pricing_maps_dir(root / "pricing.maps"))
    keys.update(_map_keys_from_item_db_tiers())

    def sort_key(k: str) -> tuple:
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)

    return sorted(keys, key=sort_key)


def strategy_map_combo_entries(
    config: Mapping[str, Any],
    *,
    configs_root: Path | None = None,
) -> list[str]:
    """``\"<id>. <名称或提示>\"`` 列表，供 BotConfigPanel / 下拉里展示。"""
    keys = all_strategy_map_editor_keys(config, configs_root=configs_root)
    auto = config.get("automation") if isinstance(config.get("automation"), dict) else {}
    maps = auto.get("maps") if isinstance(auto.get("maps"), dict) else {}

    def label_for(map_key: str) -> str:
        ent = maps.get(map_key)
        if isinstance(ent, dict):
            name = ent.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        if map_key in maps:
            return map_key
        return f"{map_key}（未在 automation.maps 配置入口，可写 pricing.maps）"

    return [f"{k}. {label_for(k)}" for k in keys]


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


def merged_runtime_with_map_pricing(
    config: Mapping[str, Any],
    *,
    map_bundle_key: str | None = None,
) -> dict[str, Any]:
    """
    深合并 ``configs/pricing.maps/<id>.json``。

    若传入 ``map_bundle_key``（与 :func:`bidking.parsing.item_db.map_bundle_key_for_automation`
    一致，如 ``\"230\"``），优先按该键加载覆盖层；否则按 ``automation.selected_map`` /
    ``default_map`` 解析（与 Bot 策略面板所选地图一致）。
    """
    if not isinstance(config, dict):
        return dict(config)
    auto = config.get("automation")
    auto_d = auto if isinstance(auto, dict) else {}
    kb = str(map_bundle_key or "").strip()
    mid = kb if kb else resolve_automation_map_config_key(auto_d)
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
