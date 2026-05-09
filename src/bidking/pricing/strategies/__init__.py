from __future__ import annotations

from typing import Any, Callable

from . import aisha_base, ahmad_base

RoleBaseFn = Callable[..., tuple[int | None, dict[str, Any]]]

_REGISTRY: dict[str, RoleBaseFn] = {
    "aisha": aisha_base.compute_base_bid_points,
    "ahmad": ahmad_base.compute_base_bid_points,
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
