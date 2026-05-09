"""策略路由：根据 ``runtime.automation.selected_mode`` 选 ahmad / aisha。

``compute_bid(snapshot, pricing_cfg, opponent_price=None)`` 是新代码统一入口，
只读 :mod:`bidking.analysis` 出来的快照，不直接读 ``GameState``；后处理走
:mod:`.post_process`。

明确**不实现拉文（Raven）**分支：仅在 :data:`Mode` 中保留枚举位，调用时报错。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class Mode(str, Enum):
    AHMAD = "ahmad_premium"
    AISHA = "aisha_premium"
    RAVEN = "raven"  # 保留枚举位，未实现


@dataclass
class BidDecision:
    price: int
    mode: Mode
    detail: Dict[str, Any]


def normalize_mode(raw: Any) -> Mode:
    s = str(raw or "").strip().lower()
    if s in ("ahmad", "ahmad_premium"):
        return Mode.AHMAD
    if s in ("aisha", "aisha_premium"):
        return Mode.AISHA
    if s in ("raven",):
        return Mode.RAVEN
    return Mode.AHMAD


def compute_bid(
    snapshot: Dict[str, Any],
    pricing_cfg: Dict[str, Any],
    *,
    mode: Mode | str = Mode.AHMAD,
    opponent_price: Optional[int] = None,
    round_no: Optional[int] = None,
) -> BidDecision:
    """统一出价入口。

    - ``snapshot``: 来自 :mod:`bidking.analysis.snapshot.build_board_snapshot`。
    - ``pricing_cfg``: 来自 :func:`bidking.config.pricing.resolve_for`。
    """
    m = normalize_mode(mode)

    if m is Mode.AISHA:
        from .aisha import compute_bid_from_snapshot

        result = compute_bid_from_snapshot(snapshot, pricing_config=pricing_cfg)
        price = int(result.get("aisha_bid") or 0)
        return BidDecision(price=price, mode=m, detail=dict(result))

    if m is Mode.AHMAD:
        from .ahmad import compute_ahmad_premium_w  # imported lazily to avoid cycles

        bucket = round_no if round_no is not None else int(snapshot.get("current_round", 1) or 1)
        try:
            res = compute_ahmad_premium_w(
                pricing_cfg, round_no=int(bucket), map_key=str(snapshot.get("map_id", "") or ""),
            )
        except TypeError:
            res = compute_ahmad_premium_w(pricing_cfg)
        price_w = float(res.get("price_w", 0.0)) if isinstance(res, dict) else 0.0
        price = int(price_w * 10000)
        return BidDecision(price=price, mode=m, detail={"ahmad": res} if isinstance(res, dict) else {})

    raise NotImplementedError("拉文（Raven）策略尚未实现")


__all__ = [
    "Mode",
    "BidDecision",
    "compute_bid",
    "normalize_mode",
]
