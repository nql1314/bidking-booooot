# -*- coding: utf-8 -*-
"""定价流水线上下文调试落盘。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from ...config.paths import project_root
from .context import SnapshotPricingContext


def _json_safe(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def pricing_context_to_dict(ctx: SnapshotPricingContext) -> Dict[str, Any]:
    """将 ``SnapshotPricingContext`` 转为可 ``json.dumps`` 的字典。"""
    return _json_safe(asdict(ctx))


def _resolve_dump_path(raw: Optional[str]) -> Path:
    s = (raw or "").strip() or "data/pricing_context.json"
    p = Path(s).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (project_root() / s).resolve()


def maybe_write_pricing_context_json(ctx: SnapshotPricingContext) -> Optional[Path]:
    """若 ``debug.save_pricing_context_json`` 为真，将 ``ctx`` 写入 JSON 文件。"""
    try:
        from ...config.runtime import load_runtime

        debug = load_runtime().debug
    except Exception:
        return None
    if not bool(debug.get("save_pricing_context_json", False)):
        return None
    path = _resolve_dump_path(debug.get("pricing_context_json_path"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = pricing_context_to_dict(ctx)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return None
    return path
