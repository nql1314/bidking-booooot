# -*- coding: utf-8 -*-
"""从 configs 合并树生成 visual_config_schema.json（含 hide / scope / type）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"


def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def walk_paths(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and v:
                out.extend(walk_paths(v, path))
            else:
                out.append((path, v))
    return out


TYPE_OVERRIDES: dict[str, str] = {
    "automation.bid_cap_price": "int",
    "pricing.fallback_bid_price": "int",
    "automation.bid_cap_skip_when_total_above": "int",
}
for _r in range(1, 6):
    TYPE_OVERRIDES[f"automation.bid_ratio_by_round.{_r}"] = "float"
for _k in ("1", "2", "3", "4", "default"):
    TYPE_OVERRIDES[f"pricing.secret_auction_rank_opponent_multipliers.{_k}"] = "float"

LABEL_OVERRIDES: dict[str, str] = {
    "automation.bid_ratio_by_round.1": "第1回合系数",
    "automation.bid_ratio_by_round.2": "第2回合系数",
    "automation.bid_ratio_by_round.3": "第3回合系数",
    "automation.bid_ratio_by_round.4": "第4回合系数",
    "automation.bid_ratio_by_round.5": "第5回合系数",
    "automation.bid_cap_price": "封顶价",
    "pricing.fallback_bid_price": "兜底价",
    "advisor.role": "顾问角色",
}


def infer_type(value: Any, path: str = "") -> str:
    if path in TYPE_OVERRIDES:
        return TYPE_OVERRIDES[path]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        if value and all(isinstance(x, int) for x in value):
            return "int_list"
        return "json"
    if isinstance(value, dict):
        return "json"
    if path.endswith("_price") or path.endswith("_below") or path.endswith("_bid"):
        return "int"
    if path.endswith("_seconds") or path.endswith("_minutes") or "ratio" in path:
        return "float"
    return "str"


def path_group(path: str) -> str:
    top = path.split(".", 1)[0]
    labels = {
        "pricing": "出价",
        "automation": "自动化",
        "timing": "时序",
        "safety": "安全",
        "window": "窗口",
        "capture": "截图区域",
        "clicks": "点击坐标",
        "board_snapshot": "棋盘快照",
        "grid_view": "画板 UI",
        "debug": "调试",
        "viewer": "启动页",
        "advisor": "顾问",
        "humanize": "拟人化",
        "input": "后台输入",
        "ocr": "OCR",
    }
    return labels.get(top, top)


def default_hide(path: str, typ: str) -> bool:
    """hide=true 表示不在可视化页展示（仍保留在 schema 中）。"""
    if typ == "json":
        return True
    if path.startswith("clicks."):
        return True
    if path.startswith("capture."):
        return True
    if path.startswith("automation.maps."):
        return True
    if path.startswith("automation.warehouse_auto_sort.") and (
        "click" in path or path.endswith("_seconds")
    ):
        return path not in (
            "automation.warehouse_auto_sort.enabled",
            "automation.warehouse_auto_sort.wait_after_warehouse_click_seconds",
            "automation.warehouse_auto_sort.wait_after_auto_sort_click_seconds",
        )
    if path.startswith("safety.stuck_after_handled_round."):
        return path not in (
            "safety.stuck_after_handled_round.enabled",
            "safety.stuck_after_handled_round.consecutive_poll_threshold",
            "safety.stuck_after_handled_round.between_clicks_seconds",
        )
    if path.startswith("window.reference_client_size."):
        return True
    if path == "window.hwnd":
        return True
    if path.startswith("humanize."):
        return path != "humanize.enabled"
    if path.startswith("input."):
        return True
    if path.startswith("ocr."):
        return True
    if path.startswith("automation.map_entry_ticket_by_map_id."):
        return True
    if path in ("board_snapshot.path", "board_snapshot.write_mode", "board_snapshot.schema_version_min"):
        return True
    if path.startswith("debug.") and path != "debug.gui_verbose":
        return True
    visible_prefixes = (
        "pricing.enable_",
        "pricing.late_round",
        "pricing.fallback",
        "pricing.vacant",
        "pricing.infer_",
        "pricing.price_avg",
        "pricing.grid_avg",
        "pricing.secret_auction",
        "automation.bid_",
        "automation.tool_",
        "automation.selected_",
        "automation.run_",
        "automation.cycle_",
        "automation.bot_runner",
        "automation.selected_mode",
        "automation.default_",
        "automation.enable_aisha",
        "automation.aisha_round4",
        "automation.unknown_escape",
        "automation.post_confirm",
        "automation.game_start",
        "automation.map_select",
        "automation.tool_skip",
        "automation.warehouse_auto_sort.enabled",
        "timing.",
        "board_snapshot.enabled",
        "board_snapshot.self_user_uid",
        "grid_view.",
        "advisor.",
        "safety.dry_run",
        "safety.failsafe",
        "safety.bring_window",
        "safety.confirm_after_type",
        "safety.verify_bid",
        "safety.park_mouse",
        "safety.move_pause",
        "viewer.",
    )
    for p in visible_prefixes:
        if path.startswith(p) or path == p.rstrip("."):
            return False
    return True


def resolve_scope(
    path: str,
    config_paths: set[str],
    map_paths: set[str],
) -> str:
    in_cfg = path in config_paths
    in_map = path in map_paths
    if in_cfg and in_map:
        return "both"
    if in_map:
        return "map"
    return "config"


def path_label(path: str) -> str:
    leaf = path.split(".")[-1]
    leaf = re.sub(r"^(\d+)$", r"第\1", leaf)
    return leaf.replace("_", " ")


def main() -> None:
    runtime = load_json(CONFIGS / "runtime.json")
    overlay = load_json(CONFIGS / "config.json")
    merged = deep_merge(runtime, overlay)

    config_paths = {p for p, _ in walk_paths(overlay)}
    map_paths: set[str] = set()
    maps_dir = CONFIGS / "pricing.maps"
    for mp in maps_dir.glob("*.json"):
        doc = load_json(mp)
        map_paths.update(p for p, _ in walk_paths(doc))

    all_paths: dict[str, Any] = {}
    for p, v in walk_paths(merged):
        all_paths[p] = v
    for p in config_paths | map_paths:
        all_paths.setdefault(p, None)

    if maps_dir.is_dir():
        for mp in maps_dir.glob("*.json"):
            for p, v in walk_paths(load_json(mp)):
                if all_paths.get(p) is None:
                    all_paths[p] = v

    # humanize 默认键（runtime 中可能无）
    humanize_defaults = {
        "humanize.enabled": True,
        "humanize.click_jitter_pixels": 3,
        "humanize.move_duration_min": 0.07,
        "humanize.move_duration_max": 0.38,
        "humanize.move_steps_min": 3,
        "humanize.move_steps_max": 10,
        "humanize.arc_strength_min": 0.35,
        "humanize.arc_strength_max": 1.25,
        "humanize.pre_click_delay_min": 0.0,
        "humanize.pre_click_delay_max": 0.07,
        "humanize.price_char_interval_min": 0.038,
        "humanize.price_char_interval_max": 0.11,
        "humanize.price_stutter_probability": 0.11,
        "humanize.price_stutter_extra_min": 0.1,
        "humanize.price_stutter_extra_max": 0.42,
        "humanize.pre_select_all_delay_min": 0.02,
        "humanize.pre_select_all_delay_max": 0.12,
        "humanize.post_select_all_delay_scale_min": 0.85,
        "humanize.post_select_all_delay_scale_max": 1.35,
    }
    for p, v in humanize_defaults.items():
        all_paths.setdefault(p, v)

    extra_scalars = {
        "automation.bid_cap_skip_when_total_above": 0,
        "automation.game_start_timeout_seconds": 60.0,
        "automation.map_select_no_start_esc_after": 3,
        "automation.tool_skip_vacant_threshold": 5,
        "pricing.enable_big_gold_adjustment": False,
        "safety.skip_round_bid_button_ocr_gate": False,
        "timing.round_bid_button_gate_max_seconds": 120.0,
        "timing.round_bid_button_gate_poll_seconds": 0.4,
        "board_snapshot.ahmad_abde_scale": 1.0,
    }
    for p, v in extra_scalars.items():
        all_paths.setdefault(p, v)

    fields: list[dict[str, Any]] = []
    for path in sorted(all_paths.keys()):
        val = all_paths[path]
        typ = infer_type(val, path) if val is not None else infer_type(None, path)
        field: dict[str, Any] = {
            "path": path,
            "type": typ,
            "label": LABEL_OVERRIDES.get(path, path_label(path)),
            "description": path,
            "scope": resolve_scope(path, config_paths, map_paths),
            "group": path_group(path),
            "hide": default_hide(path, typ),
        }
        if path == "pricing.vacant_red_floor_ceiling_pick_mode":
            field["type"] = "enum"
            field["choices"] = ["normal", "aggressive", "conservative"]
            field["hide"] = False
        if path == "grid_view.fraud_empty_cells_algorithm":
            field["type"] = "enum"
            field["choices"] = ["tiling_strict", "tiling", "none"]
            field["hide"] = False
        if path == "board_snapshot.write_mode":
            field["type"] = "enum"
            field["choices"] = ["read", "write", "both"]
        fields.append(field)

    doc = {
        "version": 2,
        "description": (
            "可视化配置字段表。path=JSON 点路径；scope=config|map|both；"
            "hide=true 时不在「可视化配置」页展示（仍可在 JSON 编辑器中改）。"
            "运行 tools/generate_visual_config_schema.py 可从 configs 目录重新生成。"
        ),
        "fields": fields,
    }
    out = CONFIGS / "visual_config_schema.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    visible = sum(1 for f in fields if not f.get("hide"))
    print(f"Wrote {len(fields)} fields ({visible} visible) -> {out}")


if __name__ == "__main__":
    main()
