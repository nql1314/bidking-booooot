"""出价后处理：cap / safe_guard / 对手价上限 / 价值锚 ceiling。

从历史 ``fresh_bidking_bot.apply_price_post_processing`` 与
``fresh_aisha_bot.apply_aisha_price_post_processing`` 拆出的纯函数。
为避免在迁移期把 ~2k 行的循环主体拆碎，这里仅提供**最小可用的纯函数**集合，
策略层调用它们；旧 runner 内联版本在迁移完成前继续保留。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PostProcessConfig:
    burst_limit: float = 1.3
    bid_cap_price: Optional[int] = None
    safe_guard_enabled: bool = False
    safe_guard_max_increase_ratio: float = 0.5
    last_submitted_price: Optional[int] = None
    opponent_bid_k_increment: float = 1.01
    opponent_bid_defensive_bump: int = 300
    opponent_bid_min: int = 0
    opponent_bid_max: Optional[int] = None


def cap_with_burst_limit(price: float, base: float, burst_limit: float) -> float:
    if base <= 0 or burst_limit <= 0:
        return price
    ceiling = base * burst_limit
    return min(price, ceiling)


def apply_bid_cap(price: float, cap: Optional[int]) -> float:
    if cap is None or cap <= 0:
        return price
    return min(price, float(cap))


def apply_safe_guard(price: float, cfg: PostProcessConfig) -> float:
    if not cfg.safe_guard_enabled:
        return price
    last = cfg.last_submitted_price or 0
    if last <= 0:
        return price
    ratio = max(0.0, float(cfg.safe_guard_max_increase_ratio))
    ceiling = last * (1.0 + ratio)
    return min(price, ceiling)


def apply_opponent_floor(price: float, opponent_bid: Optional[int], cfg: PostProcessConfig) -> float:
    """若已知对手最高价，则 ``max(price, opp * k + bump)``，并夹到 [min, max]。"""
    if opponent_bid is None or opponent_bid <= 0:
        return price
    k = max(1.0, float(cfg.opponent_bid_k_increment))
    raised = opponent_bid * k + max(0, int(cfg.opponent_bid_defensive_bump))
    out = max(price, raised)
    if cfg.opponent_bid_min:
        out = max(out, float(cfg.opponent_bid_min))
    if cfg.opponent_bid_max:
        out = min(out, float(cfg.opponent_bid_max))
    return out


def apply_value_anchor_ceiling(price: float, anchor_ceiling: Optional[float]) -> float:
    if anchor_ceiling is None or anchor_ceiling <= 0:
        return price
    return min(price, float(anchor_ceiling))


def post_process(
    raw_price: float,
    *,
    base: Optional[float],
    cfg: PostProcessConfig,
    opponent_bid: Optional[int] = None,
    value_anchor_ceiling: Optional[float] = None,
) -> int:
    """统一后处理入口；返回整数出价（向下取整）。"""
    p = float(raw_price)
    if base is not None:
        p = cap_with_burst_limit(p, float(base), cfg.burst_limit)
    p = apply_bid_cap(p, cfg.bid_cap_price)
    p = apply_safe_guard(p, cfg)
    p = apply_opponent_floor(p, opponent_bid, cfg)
    p = apply_value_anchor_ceiling(p, value_anchor_ceiling)
    return max(0, int(p))


__all__ = [
    "PostProcessConfig",
    "apply_bid_cap",
    "apply_opponent_floor",
    "apply_safe_guard",
    "apply_value_anchor_ceiling",
    "cap_with_burst_limit",
    "post_process",
]
