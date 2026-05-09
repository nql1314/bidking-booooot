from __future__ import annotations

from typing import Any

from .snapshot_players import (
    board_snapshot_self_identity,
    iter_opponent_round_bids_from_snapshot,
    player_round_price_bid,
    self_round_bid_from_snapshot,
)

_HERO_CID_RED_SCOUT = 110

# 与旧版 aisha_premium 一致：低级图不做空置红推断
_VACANT_RED_INFERENCE_EXCLUDE_MAP_CONFIG_KEYS = frozenset({"1", "2"})


def _count_quality_items_all(board_snapshot: dict[str, Any], quality: int) -> int:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    if not isinstance(raw, dict):
        return 0
    k = 0
    for _uid, it in raw.items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) == quality:
                k += 1
        except (TypeError, ValueError):
            continue
    return k


def _hero_110_red_scout_signal(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    computed_price_floor: float,
) -> tuple[bool, list[dict[str, Any]]]:
    self_uid, name_hint = board_snapshot_self_identity(config, board_snapshot)
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
        pname = str(pdata.get("name") or "")
        if name_hint and name_hint in pname:
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
    red_items_all = _count_quality_items_all(board_snapshot, 6)
    detail["red_quality_item_count_on_board"] = red_items_all
    if red_items_all > 0:
        detail["decision_rule"] = "existing_red_quality_in_items_assume_no_red_in_vacant"
        detail["has_red_inferred"] = False
        return False, detail

    vac = int(vacant_used)
    if vac <= 4:
        detail["decision_rule"] = "vac_le_4_ignore_red"
        return False, detail

    ref_r = 3 if int(current_round) == 4 else 4
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
        "has_red_inferred": has_red,
        "chosen_points": chosen,
        "points_floor": pf_i,
        "points_ceiling": pc_i,
        "before_pick": int(fin),
        "after_pick": chosen,
        "inference": infer_detail,
    }
