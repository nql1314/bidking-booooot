"""空置金/金红档溢价：按格数幂律衰减 ``u × n^α``（α 可配置，默认 1 即线性）。

红档 ``q6`` 不参与衰减，恒为线性 ``u × n``。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

_VACANT_TIER_EXPONENT_MIN = 0.5
_VACANT_TIER_EXPONENT_MAX = 1.0
# 仅金 / 金红空置溢价可配置 α；红档恒为 1.0。
_DECAY_QUALITY_GROUPS = frozenset({"q5", "q5+q6"})


def _clamp_exponent(alpha: float) -> float:
    if not math.isfinite(alpha):
        return 1.0
    return max(_VACANT_TIER_EXPONENT_MIN, min(_VACANT_TIER_EXPONENT_MAX, float(alpha)))


def resolve_vacant_tier_exponent(
    pricing_config: Optional[Mapping[str, Any]],
    quality_group: str,
) -> float:
    """从 ``pricing.vacant_tier_cell_exponents`` 读取品质组 ``α``；缺省为 ``1.0``。

    ``q6``（红档）恒返回 ``1.0``，配置中的 ``q6`` 项会被忽略。
    """
    key = str(quality_group).strip()
    if key == "q6":
        return 1.0
    if key not in _DECAY_QUALITY_GROUPS:
        return 1.0
    if not isinstance(pricing_config, Mapping):
        return 1.0
    raw = pricing_config.get("vacant_tier_cell_exponents")
    if not isinstance(raw, Mapping):
        return 1.0
    val = raw.get(key)
    if val is None:
        return 1.0
    try:
        return _clamp_exponent(float(val))
    except (TypeError, ValueError):
        return 1.0


def vacant_tier_scaled_cells(n: int, alpha: float) -> float:
    """``max(0, n)^α``；``α >= 1`` 时等价于 ``float(n)``。"""
    if n <= 0:
        return 0.0
    a = _clamp_exponent(alpha)
    if a >= 1.0 - 1e-12:
        return float(n)
    return float(n) ** a


def vacant_tier_premium(unit: float, n: int, alpha: float) -> float:
    """空置溢价：``unit × n^α``。"""
    if n <= 0 or unit <= 0:
        return 0.0
    return float(unit) * vacant_tier_scaled_cells(n, alpha)


def resolve_all_vacant_tier_exponents(
    pricing_config: Optional[Mapping[str, Any]],
) -> dict[str, float]:
    return {
        "q5": resolve_vacant_tier_exponent(pricing_config, "q5"),
        "q5+q6": resolve_vacant_tier_exponent(pricing_config, "q5+q6"),
        "q6": 1.0,
    }


__all__ = [
    "resolve_all_vacant_tier_exponents",
    "resolve_vacant_tier_exponent",
    "vacant_tier_premium",
    "vacant_tier_scaled_cells",
]
