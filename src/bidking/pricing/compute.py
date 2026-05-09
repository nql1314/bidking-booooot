from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.map_runtime_overlay import merged_runtime_with_map_pricing
from .snapshot_io import current_round_from_snapshot, load_board_snapshot_if_enabled
from ._multipliers import resolve_automation_bid_ratio
from ._numeric import parse_int_config
from .opponent_adjust import apply_opponent_bid_adjustment
from .postprocess import (
    apply_bid_cap,
    apply_ceiling_points,
    apply_early_round_fallback_floor,
    apply_human_like_price_tail,
    apply_safe_guard,
)
from .price_config_load import load_price_config
from .strategies import compute_role_base, resolve_strategy_role


def compute_price(
    config: dict[str, Any],
    *,
    config_path: Path,
    round_no: int,
    board_snapshot: dict[str, Any] | None = None,
    price_config: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    读快照 ``pricing`` → ``compute_role_base``（艾莎在 ``compute_base_bid_points`` 内含空置红择优）→
    回合倍数 → 对手调整 →
    ``points_ceiling`` 锚 → 人性化尾数 → 前两回合兜底 → bid_cap → safe_guard。
    """
    effective_config = merged_runtime_with_map_pricing(config)

    if price_config is None:
        price_config = load_price_config(effective_config, config_path)

    bs = board_snapshot
    if bs is None:
        bs_cfg = effective_config.get("board_snapshot") or {}
        if bool(bs_cfg.get("enabled")):
            bs = load_board_snapshot_if_enabled(effective_config)

    snap_round = current_round_from_snapshot(bs) if isinstance(bs, dict) else None
    effective_round = int(snap_round) if snap_round is not None else int(round_no)

    role = resolve_strategy_role(effective_config, bs)
    fallback = parse_int_config((effective_config.get("pricing") or {}).get("fallback_bid_price"), 22223)

    payload: dict[str, Any] = {
        "fallback": False,
        "reason": "",
        "role": role,
        "effective_round": effective_round,
        "pricing_strategy": "snapshot_v2",
        "source_value": None,
        "board_snapshot_bid": {},
    }

    def _fallback_only(msg: str) -> tuple[int, dict[str, Any]]:
        payload["fallback"] = True
        payload["reason"] = msg
        fin_fb = int(fallback)
        payload["source_value"] = float(fin_fb)
        payload["final_round_used"] = effective_round
        return fin_fb, payload

    if not isinstance(bs, dict):
        return _fallback_only("pricing: 无画板快照或快照未启用")

    pricing = bs.get("pricing")
    if not isinstance(pricing, dict) or pricing.get("total") is None:
        return _fallback_only("pricing: 快照缺少 pricing 或 total")

    pts, meta = compute_role_base(
        role,
        pricing,
        config=effective_config,
        board_snapshot=bs,
        effective_round=effective_round,
    )
    payload["board_snapshot_bid"] = meta

    if pts is None:
        return _fallback_only(str(meta.get("reason") or "pricing: 无法解析基础出价"))

    fin = int(pts)
    payload["source_value"] = float(fin)
    payload["reason"] = meta.get("pricing_reason") or (
        f"{meta.get('bid_points_source')}: base={fin}"
    )

    ratio, ratio_skipped_r5_hero = resolve_automation_bid_ratio(
        effective_config, effective_round, bs
    )
    fin_before_ratio = fin
    fin = int(round(fin * ratio))
    br: dict[str, Any] = {
        "round": effective_round,
        "ratio": ratio,
        "before": fin_before_ratio,
        "after": fin,
    }
    if ratio_skipped_r5_hero:
        br["skipped_multiplier_opponent_hero_103_or_107"] = True
    payload["bid_ratio"] = br

    fin, payload["opponent_bid"], fin_before_opp = apply_opponent_bid_adjustment(
        effective_config,
        fin,
        effective_round,
        price_config,
        board_snapshot=bs,
        pricing=pricing,
    )

    ceiling_pts: int | None = None
    raw_ceil = pricing.get("points_ceiling")
    if raw_ceil is not None:
        try:
            ceiling_pts = int(raw_ceil)
        except (TypeError, ValueError):
            ceiling_pts = None

    fin, payload = apply_ceiling_points(
        fin, fin_before_opp, ceiling_pts, payload, effective_round
    )
    fin, payload = apply_human_like_price_tail(fin, payload)
    fin, payload = apply_early_round_fallback_floor(
        fin, effective_round, int(fallback), payload
    )
    fin, payload = apply_bid_cap(effective_config, fin, payload)
    fin, payload = apply_safe_guard(effective_config, fin, payload)
    payload["final_round_used"] = effective_round
    return int(fin), payload
