"""艾莎（aisha）角色：对手出价调整核心逻辑。"""

from __future__ import annotations

import random
from typing import Any

from .._multipliers import resolve_round_multiplier
from ..opponent_adjust import (
    blend_bid_with_opponent_reference,
    evaluate_opponent_bid_possibilities,
    _round3_protect_decision,
)


def apply_opponent_bid_adjustment_core(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    o_prev: int | None,
    price_config: dict[str, Any],
    *,
    board_snapshot: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> tuple[int, str | None, dict[str, Any] | None]:
    pricing_d = pricing if isinstance(pricing, dict) else {}
    ceiling_raw = pricing_d.get("points_ceiling")
    ceiling_pts: int | None = None
    if ceiling_raw is not None:
        try:
            ceiling_pts = int(ceiling_raw)
        except (TypeError, ValueError):
            ceiling_pts = None

    if int(round_no) <= 1 or o_prev is None:
        return int(bid), None, None

    if ceiling_pts is not None and int(o_prev) > ceiling_pts and int(round_no) >= 3:
        return int(bid), "opp_high", None

    o_poss = evaluate_opponent_bid_possibilities(
        config, board_snapshot, None, int(round_no), int(o_prev)
    )
    mult = resolve_round_multiplier(round_no, price_config)
    adj = o_poss * mult + 1000
    bid_i = int(bid)
    r_no = int(round_no)

    r3_detail = None
    if r_no >= 5:
        blended = blend_bid_with_opponent_reference(
            bid_i, o_poss, config=config, price_config=price_config
        )
        out = int(
            min(
                blended + random.randint(1000, 1500),
                float(o_poss) + random.randint(1000, 1500),
            )
        )
        return out, "opp_final", None

    if r_no == 3:
        r3_detail = _round3_protect_decision(
            config, board_snapshot, pricing_d, bid_i
        )
        if not bool(r3_detail.get("protect")):
            out = int(round(blend_bid_with_opponent_reference(
                bid_i, int(o_prev), config=config, price_config=price_config
            )))
            return out, "opp_r3_no_protect", r3_detail

    if bid_i > adj:
        if r_no == 3:
            return int(adj), "opp_low", r3_detail
        return int(round(blend_bid_with_opponent_reference(
            bid_i, adj, config=config, price_config=price_config
        ))), "opp_low", r3_detail

    if bid_i > o_poss:
        return int(o_poss), "opp_poss", r3_detail

    if bid_i > int(o_prev):
        blended = blend_bid_with_opponent_reference(
            bid_i, int(o_prev), config=config, price_config=price_config
        )
        return int(min(o_poss, round(blended))), "opp_pre", r3_detail

    return int(round(blend_bid_with_opponent_reference(
        bid_i, o_poss, config=config, price_config=price_config
    ))), "opp_sticky", r3_detail
