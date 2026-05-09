from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def resolve_advisor_path(config_path: Path, raw: Any, default_name: str) -> Path:
    if raw is None or str(raw).strip() == "":
        return config_path.parent / default_name
    p = Path(str(raw))
    if not p.is_absolute():
        return (config_path.parent / p).resolve()
    return p


def load_price_config(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    price_path = resolve_advisor_path(
        config_path,
        (config.get("advisor") or {}).get("price_config_path"),
        "price_config.json",
    )
    if not price_path.is_file():
        return {}
    try:
        return json.loads(price_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
