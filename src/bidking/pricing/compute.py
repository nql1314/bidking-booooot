from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis._board_pricing import map_id_from_board_snapshot
from ..analysis.strategy.ahmad import (
    map_bundle_is_container_series,
    map_bundle_is_express_station_series,
)
from ..config.map_runtime_overlay import merged_runtime_with_map_pricing
from ..parsing.item_db import map_bundle_key_for_automation
from .snapshot_io import load_board_snapshot_if_enabled, resolve_effective_round
from .snapshot_players import board_snapshot_self_identity
from ._multipliers import resolve_automation_bid_ratio
from ._numeric import parse_int_config
from .opponent_adjust import apply_opponent_bid_adjustment
from .postprocess import (
    apply_bid_cap,
    apply_ceiling_points,
    apply_early_round_fallback_floor,
    apply_human_like_price_tail,
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
    strategy_role: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """
    读快照 ``pricing`` → ``compute_role_base``（艾莎在 ``compute_base_bid_points`` 内含空置红择优）→
    回合倍数 → 对手调整 →
    ``points_ceiling`` 锚（第 4 回合起；若倍数 ``ratio`` > 1 则封顶按 ``points_ceiling * ratio``）→
    人性化尾数 → 前两回合兜底 → bid_cap。

    当传入或从磁盘启用的画板快照中含有效 ``map_id`` 时，``pricing.maps`` 覆盖层按该局地图档键
    加载（与 grid_view / 日志对局一致）；否则仍按 ``automation.selected_map`` 等解析。

    ``strategy_role``：若给出 ``aisha`` / ``ahmad`` / ``universal``，则跳过
    :func:`resolve_strategy_role`（供 grid_view 等按快照内 ``pricing.ahmad_pricing_active``
    与当前局英雄/地图决策，而不依赖 bot 的 ``selected_mode``）。
    """
    bs = board_snapshot
    cfg_for_paths: dict[str, Any] | None = None
    if bs is None:
        cfg_for_paths = merged_runtime_with_map_pricing(config)
        bs_cfg = cfg_for_paths.get("board_snapshot") or {}
        if bool(bs_cfg.get("enabled")):
            bs = load_board_snapshot_if_enabled(cfg_for_paths)

    map_bundle_key: str | None = None
    if isinstance(bs, dict):
        mid_snap = map_id_from_board_snapshot(bs)
        if mid_snap is not None and int(mid_snap) > 0:
            mid_i = int(mid_snap)
            # 使用原始 map_id 计算档键，不做归一化
            map_bundle_key = map_bundle_key_for_automation(mid_i)

    if map_bundle_key is not None:
        effective_config = merged_runtime_with_map_pricing(
            config, map_bundle_key=map_bundle_key
        )
    elif cfg_for_paths is not None:
        effective_config = cfg_for_paths
    else:
        effective_config = merged_runtime_with_map_pricing(config)

    if price_config is None:
        price_config = load_price_config(effective_config, config_path)

    effective_round = resolve_effective_round(int(round_no), bs if isinstance(bs, dict) else None)

    if strategy_role is not None:
        r = str(strategy_role).strip().lower()
        role = r if r in ("aisha", "ahmad", "universal") else resolve_strategy_role(
            effective_config, bs
        )
    else:
        role = resolve_strategy_role(effective_config, bs)
    fallback = parse_int_config((effective_config.get("pricing") or {}).get("fallback_bid_price"), 22223)

    payload: dict[str, Any] = {
        "fallback": False,
        "reason": "",
        "pricing_reason": None,
        "role": role,
        "effective_round": effective_round,
        "pricing_strategy": "snapshot_v2",
        "source_value": None,
        "board_snapshot_bid": {},
    }

    def _fallback_only(msg: str) -> tuple[int, dict[str, Any]]:
        payload["fallback"] = True
        payload["reason"] = msg
        payload["pricing_reason"] = None
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
    payload["board_snapshot_bid"] = meta if isinstance(meta, dict) else {}
    payload["pricing_reason"] = (
        meta.get("pricing_reason") if isinstance(meta, dict) else None
    )

    if pts is None:
        msg = "pricing: 无法解析基础出价"
        if isinstance(meta, dict):
            msg = str(meta.get("reason") or msg)
        return _fallback_only(msg)

    fin = int(pts)
    payload["source_value"] = float(fin)
    payload["reason"] = meta.get("pricing_reason") or (
        f"{meta.get('bid_points_source')}: base={fin}"
    )

    ratio = resolve_automation_bid_ratio(effective_config, effective_round)
    fin_before_ratio = fin
    fin = int(round(fin * ratio))
    payload["bid_ratio"] = {
        "round": effective_round,
        "ratio": ratio,
        "before": fin_before_ratio,
        "after": fin,
    }

    fin, payload["opponent_bid"], fin_before_opp = apply_opponent_bid_adjustment(
        effective_config,
        fin,
        effective_round,
        price_config,
        role=role,
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
        fin,
        fin_before_opp,
        ceiling_pts,
        payload,
        effective_round,
        bid_ratio=ratio,
    )
     # 集装箱地图：非作者账号遇到作者账号时，价格乘以 0.88
    mid_ct = map_id_from_board_snapshot(bs)
    if mid_ct is not None and map_bundle_is_container_series(int(mid_ct)):
        self_uid_ct, _ = board_snapshot_self_identity(effective_config, bs)
        if self_uid_ct:
            players_ct = (bs.get("game_state") or {}).get("players") or {}
            if not isinstance(players_ct, dict):
                players_ct = bs.get("players") if isinstance(bs.get("players"), dict) else {}
            if isinstance(players_ct, dict):
                _author_uid_large = "358372071974712"  # 大号
                _author_uid_small = "941456831344888"  # 小号
                author_uids = {_author_uid_large, _author_uid_small}
                opp_uids_ct = {
                    str(k) for k in players_ct if str(k) != str(self_uid_ct)
                }
                # 当前使用者非作者账号，且对手中包含作者账号
                if self_uid_ct not in author_uids:
                    if author_uids.intersection(opp_uids_ct):
                        fin = int(round(fin * 0.88))
    fin, payload = apply_human_like_price_tail(fin, payload)
    fin, payload = apply_early_round_fallback_floor(
        fin, effective_round, int(fallback), payload
    )
    # 快递站系列地图：与作者（两固定 UID）对局时的约定出价（早于 bid_cap）
    mid_sp = map_id_from_board_snapshot(bs)
    if mid_sp is not None and map_bundle_is_express_station_series(int(mid_sp)):
        self_uid_sp, _ = board_snapshot_self_identity(effective_config, bs)
        if self_uid_sp:
            players_sp = (bs.get("game_state") or {}).get("players") or {}
            if not isinstance(players_sp, dict):
                players_sp = bs.get("players") if isinstance(bs.get("players"), dict) else {}
            if isinstance(players_sp, dict):
                _author_uid_primary = "941456831344888"
                _author_uid_alt = "358372071974712"
                opp_uids = {
                    str(k) for k in players_sp if str(k) != str(self_uid_sp)
                }
                forced: int | None = None
                if self_uid_sp == _author_uid_primary and _author_uid_alt in opp_uids:
                    forced = 250
                elif self_uid_sp == _author_uid_alt and _author_uid_primary in opp_uids:
                    forced = 886
                if forced is not None:
                    fin = int(forced)
    fin, payload = apply_bid_cap(effective_config, fin, payload)
    payload["final_round_used"] = effective_round
    return int(fin), payload
