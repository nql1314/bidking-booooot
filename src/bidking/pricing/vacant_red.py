from __future__ import annotations

from typing import Any

from ..analysis.raw_pricing import event_stats_q12_q3_q4_grids_all_known
from .opponent_adjust import board_map_bundle_key, board_snapshot_is_secret_auction
from .snapshot_players import (
    board_snapshot_self_identity,
    iter_opponent_round_bids_from_snapshot,
    player_round_price_bid,
    self_round_bid_from_snapshot,
)

_VACANT_RED_PICK_MODE_NORMAL = "normal"
_VACANT_RED_PICK_MODE_AGGRESSIVE = "aggressive"
_VACANT_RED_PICK_MODE_FORCE_GOLD_RED = "force_gold_red"

# 暗图（440/450 隐秘拍卖档）：积极模式不比较对手价，规则 7 之后统一均价
_AGGRESSIVE_DARK_MAP_BUNDLE_KEYS = frozenset({"440", "450", "560"})

_HERO_CID_RED_SCOUT = 110

# 与旧版 aisha_premium 一致：低级图不做空置红推断
_VACANT_RED_INFERENCE_EXCLUDE_MAP_CONFIG_KEYS = frozenset({"1", "2"})


def _hero_110_red_scout_signal(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    computed_price_floor: float,
) -> tuple[bool, list[dict[str, Any]]]:
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return False, []
    cp = float(computed_price_floor)
    if cp <= 0:
        return False, []
    thr_hi = 1.1 * cp
    thr_abandon = 0.7 * cp
    hits: list[dict[str, Any]] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        try:
            hc = int(pdata.get("hero_cid") or 0)
        except (TypeError, ValueError):
            continue
        if hc != _HERO_CID_RED_SCOUT:
            continue
        for r in (3, 4):
            b = player_round_price_bid(pdata, r)
            if b is None:
                continue
            bf = float(b)
            if bf < thr_abandon:
                continue
            if bf > thr_hi:
                hits.append(
                    {
                        "hero_cid": hc,
                        "round": r,
                        "bid": b,
                        "threshold_high": thr_hi,
                        "abandon_below": thr_abandon,
                    }
                )
    return bool(hits), hits


def infer_vacant_has_red_from_opponent_history(
    *,
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    vacant_used: int,
    current_round: int,
    points_floor: int,
) -> tuple[bool, dict[str, Any]]:
    cp = float(points_floor)
    detail: dict[str, Any] = {
        "vacant_used": int(vacant_used),
        "current_round": int(current_round),
        "points_floor_ref": int(points_floor),
    }
    vac = int(vacant_used)
    if vac <= 4:
        detail["decision_rule"] = "vac_le_4_ignore_red"
        return False, detail

    ref_r = 3 if int(current_round) == 4 else 4

    # 隐秘拍卖：``prices`` 为名次而非金币，不做按排名金红推断；仅保留空置格保底。
    if board_snapshot_is_secret_auction(board_snapshot):
        detail["reference_price_round"] = ref_r
        detail["has_red_inferred"] = False
        detail["decision_rule"] = "secret_auction_no_rank_red_inference"
        if int(current_round) == 4 and vac >= 12:
            detail["decision_rule"] = "secret_auction_vac_ge_12_assume_red"
            detail["has_red_inferred"] = True
            return True, detail
        return False, detail

    detail["reference_price_round"] = ref_r
    our_b = self_round_bid_from_snapshot(config, board_snapshot, ref_r)
    detail["our_bid_same_round"] = our_b
    our_f = float(our_b) if our_b is not None else None

    op_bids = iter_opponent_round_bids_from_snapshot(config, board_snapshot, ref_r)
    detail["opponent_bids"] = list(op_bids)

    if int(current_round) == 4:

        def hit_two_opp(b: float) -> bool:
            if our_f is not None and b >= 1.2 * our_f:
                return True
            return b > 1.1 * cp

        def hit_one_opp(b: float) -> bool:
            if our_f is not None and b >= 1.3 * our_f:
                return True
            return b > 1.1 * cp

    else:

        def hit_two_opp(b: float) -> bool:
            if our_f is not None and b >= 1.1 * our_f:
                return True
            return b > cp

        def hit_one_opp(b: float) -> bool:
            if our_f is not None and b >= 1.2 * our_f:
                return True
            return b > 1.1 * cp

    n_two = sum(1 for b in op_bids if hit_two_opp(float(b)))
    n_one = sum(1 for b in op_bids if hit_one_opp(float(b)))
    detail["opponent_count_ge_two_rule"] = n_two
    detail["opponent_count_ge_one_rule"] = n_one
    opp_red = n_two >= 2 or n_one >= 1
    detail["opponent_history_suggests_red"] = opp_red

    hero_red, hero_hits = _hero_110_red_scout_signal(board_snapshot, config, cp)
    detail["hero_110_red_signal"] = hero_red
    detail["hero_110_hits"] = hero_hits

    has_red = opp_red or hero_red
    detail["has_red_inferred"] = has_red
    detail["decision_rule"] = "vac_6_to_12_opponent_and_hero_110"
    if not has_red:
        if current_round == 4 and vac > 12:
            detail["decision_rule"] = "vac_gt_12_assume_red"
            return True, detail

    return has_red, detail


def _automation_selected_map_config_key(config: dict[str, Any]) -> str:
    auto = config.get("automation") or {}
    return str(auto.get("selected_map") or auto.get("default_map") or "").strip()


def resolve_vacant_red_floor_ceiling_pick_mode(config: dict[str, Any]) -> str:
    """``pricing.vacant_red_floor_ceiling_pick_mode``：``normal``（默认）、``aggressive`` 或 ``force_gold_red``。"""
    raw = (config.get("pricing") or {}).get("vacant_red_floor_ceiling_pick_mode")
    mode = str(raw or _VACANT_RED_PICK_MODE_NORMAL).strip().lower()
    if mode in (
        _VACANT_RED_PICK_MODE_FORCE_GOLD_RED,
        "force_gold_red",
        "强制金红",
        "强制",
    ):
        return _VACANT_RED_PICK_MODE_FORCE_GOLD_RED
    if mode in (_VACANT_RED_PICK_MODE_AGGRESSIVE, "激进", "积极"):
        return _VACANT_RED_PICK_MODE_AGGRESSIVE
    return _VACANT_RED_PICK_MODE_NORMAL


def board_snapshot_aggressive_dark_map(
    board_snapshot: dict[str, Any] | None,
) -> bool:
    """暗图档（440/450）：``prices`` 为名次，不宜按金币比较对手价。"""
    k = board_map_bundle_key(board_snapshot)
    return bool(k) and k in _AGGRESSIVE_DARK_MAP_BUNDLE_KEYS


def _reference_round_for_vacant_red_pick(current_round: int) -> int:
    """返回用于参考对手出价的回合号。

    - 第3回合参考第2回合
    - 第4回合参考第3回合
    - 第5回合参考第4回合
    """
    r = int(current_round)
    if r == 3:
        return 2
    if r == 4:
        return 3
    return 4  # 第5回合及以后参考第4回合


def _max_opponent_bid_for_vacant_red_pick(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    current_round: int,
) -> int | None:
    ref_r = _reference_round_for_vacant_red_pick(current_round)
    op_bids = iter_opponent_round_bids_from_snapshot(config, board_snapshot, ref_r)
    if not op_bids:
        return None
    return int(max(op_bids))


def _aggressive_floor_ceiling_choice(
    *,
    points_floor: int,
    points_ceiling: int,
    vacant_used: int,
    max_opponent_bid: int | None,
    dark_map: bool = False,
) -> tuple[int, str, dict[str, Any]]:
    """积极模式：默认金红价（``points_ceiling``），按序命中则退回全橙或均价。"""
    pf_i = int(points_floor)
    red_i = int(points_ceiling)
    avg_i = int(round((pf_i + red_i) / 2))
    vac_i = int(vacant_used)
    detail: dict[str, Any] = {
        "points_floor": pf_i,
        "points_ceiling_red": red_i,
        "avg_points": avg_i,
        "vacant_used": vac_i,
        "max_opponent_bid": max_opponent_bid,
        "dark_map": bool(dark_map),
    }

    if vac_i <= 4:
        return pf_i, "aggressive_vac_le_4_floor", detail

    if not dark_map and max_opponent_bid is not None:
        mo = float(max_opponent_bid)
        fl = float(pf_i)
        if fl > mo * 1.2:
            return avg_i, "aggressive_floor_gt_opp_x1_2", detail
        if fl > mo:
            return avg_i, "aggressive_floor_gt_max_opp_avg", detail
        if mo >= 1.2 * fl:
            return red_i, "aggressive_opp_ge_floor_x1_2_red", detail
        if mo >= float(red_i):
            return red_i, "aggressive_opp_ge_red", detail

    if 5 <= vac_i <= 15:
        return avg_i, "aggressive_vac_5_12_avg", detail
    return red_i, "aggressive_vac_ge_12_red", detail


def apply_early_auto_fill_ceiling_anchor(
    config: dict[str, Any],
    pricing: dict[str, Any],
    round_no: int,
    fin: int,
) -> tuple[int, dict[str, Any]]:
    """各回合：自动填充已开、未启用空置红格价格选取时，锚定价用 ``points_ceiling``。"""
    from ..config.runtime import infer_vacant_rect_phantoms_enabled

    r = int(round_no)
    if config.get("pricing", {}).get("enable_vacant_red_floor_ceiling_pick", True):
        return int(fin), {"applied": False, "reason": "vacant_red_floor_ceiling_pick_enabled"}
    if not infer_vacant_rect_phantoms_enabled(config, current_round=None):
        return int(fin), {"applied": False, "reason": "auto_fill_disabled"}
    pf = pricing.get("points_floor")
    pc = pricing.get("points_ceiling")
    if pf is None or pc is None:
        return int(fin), {"applied": False, "reason": "missing_floor_ceiling"}
    try:
        pf_i, pc_i = int(pf), int(pc)
    except (TypeError, ValueError):
        return int(fin), {"applied": False, "reason": "invalid_floor_ceiling"}
    if pf_i == pc_i:
        return int(fin), {"applied": False, "reason": "floor_equals_ceiling"}
    return pc_i, {
        "applied": True,
        "decision_rule": "early_auto_fill_points_ceiling",
        "chosen_points": pc_i,
        "points_floor": pf_i,
        "points_ceiling": pc_i,
        "before_pick": int(fin),
        "after_pick": pc_i,
        "round": r,
    }


def apply_vacant_red_floor_ceiling_pick(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    pricing: dict[str, Any],
    round_no: int,
    fin: int,
) -> tuple[int, dict[str, Any]]:
    """第 3–5 回合：若 ``points_floor`` ≠ ``points_ceiling``，在倍数前先择优锚定价。

    第3回合仅在低档总格已划定 (q14_grid_known) 且启用激进模式时生效。
    """
    r = int(round_no)
    if r not in (3, 4, 5):
        return int(fin), {"applied": False, "reason": "not_round_3_4_or_5"}

    # 第3回合：仅在低档总格已划定且激进/强制金红模式下启用
    if r == 3:
        pick_mode = resolve_vacant_red_floor_ceiling_pick_mode(config)
        if pick_mode not in (
            _VACANT_RED_PICK_MODE_AGGRESSIVE,
            _VACANT_RED_PICK_MODE_FORCE_GOLD_RED,
        ):
            return int(fin), {"applied": False, "reason": "round_3_requires_aggressive_mode"}
        # 检查低档总格是否已划定 (q12+q3+q4)
        raw = board_snapshot.get("raw_pricing") if isinstance(board_snapshot, dict) else None
        q14_known = event_stats_q12_q3_q4_grids_all_known(raw)
        if not q14_known:
            return int(fin), {"applied": False, "reason": "round_3_requires_q14_grid_known"}
    if not config.get("pricing", {}).get("enable_vacant_red_floor_ceiling_pick", True):
        return int(fin), {"applied": False, "reason": "vacant_red_floor_ceiling_pick_disabled"}
    cfg_map_key = _automation_selected_map_config_key(config)
    if cfg_map_key in _VACANT_RED_INFERENCE_EXCLUDE_MAP_CONFIG_KEYS:
        return int(fin), {
            "applied": False,
            "reason": "vacant_red_inference_disabled_low_tier_config_map",
            "config_map_key": cfg_map_key,
        }
    pf = pricing.get("points_floor")
    pc = pricing.get("points_ceiling")
    if pf is None or pc is None:
        return int(fin), {"applied": False, "reason": "missing_floor_ceiling"}
    pf_i, pc_i = int(pf), int(pc)
    if pf_i == pc_i:
        return int(fin), {"applied": False, "reason": "floor_equals_ceiling"}

    vac_m = pricing.get("vacant")
    if vac_m is None:
        return int(fin), {"applied": False, "reason": "missing_vacant"}
    vac_i = int(vac_m)
    pick_mode = resolve_vacant_red_floor_ceiling_pick_mode(config)

    if pick_mode == _VACANT_RED_PICK_MODE_FORCE_GOLD_RED:
        return pc_i, {
            "applied": True,
            "pick_mode": _VACANT_RED_PICK_MODE_FORCE_GOLD_RED,
            "decision_rule": "force_gold_red_ceiling",
            "chosen_points": pc_i,
            "points_floor": pf_i,
            "points_ceiling": pc_i,
            "before_pick": int(fin),
            "after_pick": pc_i,
        }

    if pick_mode == _VACANT_RED_PICK_MODE_AGGRESSIVE:
        dark_map = board_snapshot_aggressive_dark_map(board_snapshot)
        max_opp = None
        if not dark_map:
            max_opp = _max_opponent_bid_for_vacant_red_pick(
                config, board_snapshot, int(round_no)
            )
        chosen, rule, agg_detail = _aggressive_floor_ceiling_choice(
            points_floor=pf_i,
            points_ceiling=pc_i,
            vacant_used=vac_i,
            max_opponent_bid=max_opp,
            dark_map=dark_map,
        )
        return chosen, {
            "applied": True,
            "pick_mode": _VACANT_RED_PICK_MODE_AGGRESSIVE,
            "decision_rule": rule,
            "chosen_points": chosen,
            "points_floor": pf_i,
            "points_ceiling": pc_i,
            "before_pick": int(fin),
            "after_pick": chosen,
            "aggressive_detail": agg_detail,
        }

    has_red, infer_detail = infer_vacant_has_red_from_opponent_history(
        config=config,
        board_snapshot=board_snapshot,
        vacant_used=vac_i,
        current_round=int(round_no),
        points_floor=pf_i,
    )
    chosen = pc_i if has_red else pf_i
    return chosen, {
        "applied": True,
        "pick_mode": _VACANT_RED_PICK_MODE_NORMAL,
        "has_red_inferred": has_red,
        "chosen_points": chosen,
        "points_floor": pf_i,
        "points_ceiling": pc_i,
        "before_pick": int(fin),
        "after_pick": chosen,
        "inference": infer_detail,
    }
