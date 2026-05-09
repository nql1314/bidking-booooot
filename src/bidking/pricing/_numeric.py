from __future__ import annotations

import math
from typing import Any


def parse_int_config(raw: Any, default: int) -> int:
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def parse_float_config(raw: Any, default: float) -> float:
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def safe_floor_positive(x: float) -> int:
    return int(math.floor(max(0.0, float(x))))
