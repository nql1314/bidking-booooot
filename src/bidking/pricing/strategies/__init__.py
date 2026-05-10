from __future__ import annotations

from typing import Any, Callable

from . import ahmad_base, ahmad_opponent, aisha_base, aisha_opponent

RoleBaseFn = Callable[..., tuple[int | None, dict[str, Any]]]

_REGISTRY: dict[str, RoleBaseFn] = {
    "aisha": aisha_base.compute_base_bid_points,
    "ahmad": ahmad_base.compute_base_bid_points,
}

OpponentAdjustCoreFn = Callable[
    ...,
    tuple[int, str | None, dict[str, Any] | None],
]

_OPPONENT_ADJUST_REGISTRY: dict[str, OpponentAdjustCoreFn] = {
    "aisha": aisha_opponent.apply_opponent_bid_adjustment_core,
    "ahmad": ahmad_opponent.apply_opponent_bid_adjustment_core,
}


def resolve_strategy_role(config: dict[str, Any], board_snapshot: dict[str, Any] | None) -> str:
    mode = str((config.get("automation") or {}).get("selected_mode", "")).strip().lower()
    if mode == "aisha_premium":
        return "aisha"
    if mode == "ahmad_premium" or mode in ("normal", "express"):
        return "ahmad"
    return "ahmad"


def compute_role_base(
    role: str,
    pricing: dict[str, Any],
    *,
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    effective_round: int,
) -> tuple[int | None, dict[str, Any]]:
    fn = _REGISTRY.get(role) or _REGISTRY["ahmad"]
    return fn(
        pricing,
        config=config,
        board_snapshot=board_snapshot,
        round_no=int(effective_round),
    )


def apply_opponent_bid_adjustment_core_for_role(
    role: str,
    config: dict[str, Any],
    bid: int,
    round_no: int,
    o_prev: int | None,
    price_config: dict[str, Any],
    *,
    board_snapshot: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> tuple[int, str | None, dict[str, Any] | None]:
    fn = _OPPONENT_ADJUST_REGISTRY.get(role) or _OPPONENT_ADJUST_REGISTRY["ahmad"]
    return fn(
        config,
        bid,
        round_no,
        o_prev,
        price_config,
        board_snapshot=board_snapshot,
        pricing=pricing,
    )
