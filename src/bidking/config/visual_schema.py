"""可视化配置 schema 加载与 JSON 点路径读写。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .paths import configs_dir

FieldScope = Literal["config", "map", "both"]
FieldType = Literal["bool", "int", "float", "str", "enum", "int_list", "json"]


def field_is_hidden(field: dict[str, Any]) -> bool:
    """``hide: true`` 的字段不在可视化页展示。"""
    return bool(field.get("hide", False))


def visual_config_schema_path() -> Path:
    return configs_dir() / "visual_config_schema.json"


def load_visual_config_schema(path: Path | None = None) -> dict[str, Any]:
    p = path or visual_config_schema_path()
    if not p.is_file():
        return {"version": 1, "fields": []}
    return json.loads(p.read_text(encoding="utf-8-sig"))


def field_matches_map_bundle(
    field: dict[str, Any],
    map_bundle_key: str | None,
) -> bool:
    """
    若字段含 ``map_bundle_keys`` 列表，则仅当当前地图档键命中时才展示；
    未配置该键时对所有地图可见。
    """
    keys = field.get("map_bundle_keys")
    if not keys:
        return True
    if not isinstance(keys, list):
        return True
    mk = str(map_bundle_key or "").strip()
    allowed = {str(k).strip() for k in keys if str(k).strip()}
    if not allowed:
        return True
    return mk in allowed


def schema_fields_for_scope(
    schema: dict[str, Any],
    scope: FieldScope,
    *,
    map_bundle_key: str | None = None,
) -> list[dict[str, Any]]:
    """返回适用于某编辑区的字段（config 区含 scope=config/both；map 区含 map/both）。"""
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return []
    out: list[dict[str, Any]] = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        if field_is_hidden(item):
            continue
        if scope == "map" and not field_matches_map_bundle(item, map_bundle_key):
            continue
        fs = str(item.get("scope") or "config").strip().lower()
        if scope == "config" and fs in ("config", "both"):
            out.append(item)
        elif scope == "map" and fs in ("map", "both"):
            out.append(item)
    return out


def get_by_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_by_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def coerce_field_value(field: dict[str, Any], raw: str) -> Any:
    ftype = str(field.get("type") or "str").strip().lower()
    raw = raw.strip()
    if ftype == "bool":
        return raw.lower() in ("1", "true", "yes", "on", "是")
    if ftype == "int":
        return int(raw) if raw else 0
    if ftype == "float":
        return float(raw) if raw else 0.0
    if ftype == "int_list":
        if not raw:
            return []
        parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
        return [int(p) for p in parts]
    if ftype == "json":
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, (dict, list)):
            raise ValueError("json 类型须为对象或数组")
        return parsed
    return raw


def format_field_value(value: Any, field: dict[str, Any]) -> str:
    ftype = str(field.get("type") or "str").strip().lower()
    if value is None:
        return ""
    if ftype == "bool":
        return "1" if bool(value) else "0"
    if ftype == "int_list":
        if isinstance(value, list):
            return ", ".join(str(int(x)) for x in value)
        return str(value)
    if ftype == "json":
        if value is None:
            return "{}"
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


__all__ = [
    "visual_config_schema_path",
    "load_visual_config_schema",
    "schema_fields_for_scope",
    "field_matches_map_bundle",
    "field_is_hidden",
    "get_by_path",
    "set_by_path",
    "coerce_field_value",
    "format_field_value",
]
