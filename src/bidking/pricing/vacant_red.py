from __future__ import annotations

from typing import Any

from .opponent_adjust import board_map_bundle_key, board_snapshot_is_secret_auction
from .snapshot_players import (
    board_snapshot_self_identity,
    iter_opponent_round_bids_from_snapshot,
    player_round_price_bid,
    self_round_bid_from_snapshot,
)

_VACANT_RED_PICK_MODE_NORMAL = "normal"
_VACANT_RED_PICK_MODE_AGGRESSIVE = "aggressive"

# 暗图（440/450 隐秘拍卖档）：积极模式不比较对手价，规则 7 之后统一均价
_AGGRESSIVE_DARK_MAP_BUNDLE_KEYS = frozenset({"440", "450"})

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


def _infer_secret_auction_red_by_rank(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    ref_round: int,
    vac: int,
    current_round: int,
) -> tuple[bool, dict[str, Any]]:
    """隐秘拍卖专用：prices 为排名（1=最好，4=最差），用相对排名判断是否有空置红。

    策略：
    - 只针对第4、5回合生效，其他回合直接返回无红
    - 若我方排名 >= 3（第3或第4名），认为对手抢得凶，推断有红。
    - 或有 2 个以上对手排名比我方靠前（数值更小），也认为有红。
    - 如果第4回合判断有红，第5回合直接沿用该结果
    """
    detail: dict[str, Any] = {
        "mode": "secret_auction_rank",
        "reference_round": ref_round,
        "current_round": current_round,
    }

    # 只针对第4、5回合生效
    if int(current_round) not in (4, 5):
        detail["decision_rule"] = "only_round_4_5_effective"
        return False, detail

    # 第5回合：检查第4回合是否已判断有红
    if int(current_round) == 5:
        round_4_red = board_snapshot.get("vacant_red_round4_inferred")
        if round_4_red is True:
            detail["decision_rule"] = "round4_had_red_inherit"
            detail["round4_red_inferred"] = True
            return True, detail

    our_rank = self_round_bid_from_snapshot(config, board_snapshot, ref_round)
    detail["our_rank"] = our_rank

    op_ranks = list(iter_opponent_round_bids_from_snapshot(config, board_snapshot, ref_round))
    detail["opponent_ranks"] = op_ranks

    if our_rank is None:
        detail["decision_rule"] = "no_self_rank_assume_red"
        has_red = True
        # 第4回合记录结果供第5回合使用
        if int(current_round) == 4:
            board_snapshot["vacant_red_round4_inferred"] = has_red
        return has_red, detail

    our_r = int(our_rank)
    ahead_count = sum(1 for r in op_ranks if r is not None and int(r) < our_r)
    detail["opponents_ahead_count"] = ahead_count

    # 排名 >=3（第3或第4名）或至少有2个对手排名更好，则认为有红
    has_red = our_r >= 3 or ahead_count >= 2
    detail["decision_rule"] = "rank_based"
    detail["rank_threshold"] = {"ours": our_r, "has_red": has_red}

    # 第4回合记录结果供第5回合使用
    if int(current_round) == 4:
        board_snapshot["vacant_red_round4_inferred"] = has_red

    return has_red, detail


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

    # 隐秘拍卖：prices 是排名而非金币，使用排名判断逻辑
    if board_snapshot_is_secret_auction(board_snapshot):
        detail["reference_price_round"] = ref_r
        has_red, sub_detail = _infer_secret_auction_red_by_rank(
            config, board_snapshot, ref_r, vac, current_round
        )
        detail["secret_auction_inference"] = sub_detail
        detail["has_red_inferred"] = has_red
        detail["decision_rule"] = "secret_auction_rank_based"
        # 继续向下检查 vac > 12 的保底规则（197-201行）
        if has_red:
            return has_red, detail
        # has_red 为 False 时，继续检查 vac > 16
        if current_round == 4 and vac >= 20:
            detail["decision_rule"] = "secret_auction_vac_gt_12_assume_red"
            return True, detail
        return has_red, detail
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
    """``pricing.vacant_red_floor_ceiling_pick_mode``：``normal``（默认）或 ``aggressive``。"""
    raw = (config.get("pricing") or {}).get("vacant_red_floor_ceiling_pick_mode")
    mode = str(raw or _VACANT_RED_PICK_MODE_NORMAL).strip().lower()
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
    return 3 if int(current_round) == 4 else 4


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
            return pf_i, "aggressive_floor_gt_opp_x1_2", detail
        if fl > mo:
            return avg_i, "aggressive_floor_gt_max_opp_avg", detail
        if mo >= 1.2 * fl:
            return red_i, "aggressive_opp_ge_floor_x1_2_red", detail
        if mo >= float(red_i):
            return red_i, "aggressive_opp_ge_red", detail

    if 5 <= vac_i <= 12:
        return avg_i, "aggressive_vac_5_12_avg", detail

    if vac_i >= 12:
        if dark_map:
            return avg_i, "aggressive_dark_map_avg", detail
        return red_i, "aggressive_vac_ge_12_red", detail

    if dark_map:
        return avg_i, "aggressive_dark_map_avg", detail

    return red_i, "aggressive_vac_ge_12_red", detail


def apply_vacant_red_floor_ceiling_pick(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    pricing: dict[str, Any],
    round_no: int,
    fin: int,
) -> tuple[int, dict[str, Any]]:
    """第 4–5 回合：若 ``points_floor`` ≠ ``points_ceiling``，在倍数前先择优锚定价。"""
    if int(round_no) not in (4, 5):
        return int(fin), {"applied": False, "reason": "not_round_4_or_5"}
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
