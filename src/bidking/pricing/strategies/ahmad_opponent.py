"""Ahmad 角色：对手出价调整（当前与艾莎同逻辑，便于后续分叉）。"""

from __future__ import annotations

import random
from typing import Any

from .._multipliers import resolve_round_multiplier
from ..opponent_adjust import evaluate_opponent_bid_possibilities


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
    if int(round_no) <= 1 or o_prev is None:
        return int(bid), None, None

    o_poss = evaluate_opponent_bid_possibilities(
        config, board_snapshot, None, int(round_no), int(o_prev)
    )
    mult = resolve_round_multiplier(round_no, price_config)
    adj = o_poss * mult + 1000
    bid_i = int(bid)
    r_no = int(round_no)

    if r_no >= 5:
        out = int(
            max(
                (bid_i + o_poss) / 2.0 + random.randint(1000, 1500),
                float(o_poss) + random.randint(1000, 1500),
            )
        )
        return out, "opp_final", None
    if bid_i > adj:
        return int(round((bid_i + adj) / 2)), "opp_low", None

    if bid_i > o_poss:
        return int(o_poss), "opp_poss", None

    if bid_i > int(o_prev):
        return int(min(o_poss, (bid_i + int(o_prev)) / 2)), "opp_pre", None

    return (bid_i + o_poss) / 2, "opp_sticky", None
