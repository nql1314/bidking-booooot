from __future__ import annotations

from typing import Any

from .snapshot_players import (
    board_snapshot_self_identity,
    max_other_player_bid_from_snapshot_players,
    player_round_price_bid,
    self_round_bid_from_snapshot,
)


def opponent_last_bid_default_from_snapshot(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    *,
    round_no: int,
) -> int | None:
    """列口径：``max(1, round_no - 1)``，与 ``fresh_aisha_bot`` 一致。"""
    bs_cfg = config.get("board_snapshot") or {}
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return None
    grid_round = max(1, int(round_no) - 1)
    return max_other_player_bid_from_snapshot_players(
        players,
        grid_round,
        self_user_uid=str(bs_cfg.get("self_user_uid") or ""),
        self_name_substring=str(bs_cfg.get("self_name_substring") or ""),
        board_snapshot=board_snapshot,
    )


def evaluate_opponent_bid_possibilities(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
    _meta: dict[str, Any] | None,
    round_no: int,
    o_prev: int,
) -> float:
    prev_col_round = max(1, int(round_no) - 1)
    s_prev: int | None = None
    if board_snapshot:
        s_prev = self_round_bid_from_snapshot(config, board_snapshot, prev_col_round)
    if s_prev is None or s_prev <= int(o_prev):
        return 1.05 * float(o_prev)
    return 1.05 * float(s_prev)


def _round3_max_box_id(pricing: dict[str, Any], board_snapshot: dict[str, Any] | None) -> int | None:
    candidates: list[Any] = []
    if isinstance(pricing, dict):
        candidates.append(pricing.get("max_anchor_box_id"))
    if isinstance(board_snapshot, dict):
        p2 = board_snapshot.get("pricing")
        if isinstance(p2, dict):
            candidates.append(p2.get("max_anchor_box_id"))
    for raw in candidates:
        if raw is None:
            continue
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if v >= 0:
            return v
    return None


def _round3_protect_decision(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
    pricing: dict[str, Any],
    estimated_price: int,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"score": 0, "protect": False, "reasons": []}
    if not isinstance(board_snapshot, dict):
        detail["reasons"].append("missing_board_snapshot")
        return detail
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict) or not players:
        detail["reasons"].append("missing_players")
        return detail
    self_uid, self_name = board_snapshot_self_identity(config, board_snapshot)
    round2_prices: list[int] = []
    my_round2_price: int | None = None
    low_bids = 0
    abandon_threshold = max(1.0, float(estimated_price) / 4.0)
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        p2 = player_round_price_bid(pdata, 2)
        if p2 is None:
            continue
        p2i = int(p2)
        round2_prices.append(p2i)
        if float(p2i) < abandon_threshold:
            low_bids += 1
        is_self = False
        if self_uid and str(p_uid) == self_uid:
            is_self = True
        else:
            pname = str(pdata.get("name") or "")
            if self_name and self_name in pname:
                is_self = True
        if is_self:
            my_round2_price = p2i

    score = 0
    reasons: list[dict[str, Any]] = []
    sorted_prices = sorted(round2_prices, reverse=True)
    if my_round2_price is not None and sorted_prices:
        try:
            my_rank = sorted_prices.index(my_round2_price) + 1
        except ValueError:
            my_rank = len(sorted_prices) + 1
        if my_rank == 1:
            rank_delta = -1
        elif my_rank == 2:
            rank_delta = 0
        elif my_rank == 3:
            rank_delta = 1
        else:
            rank_delta = 2
        score += rank_delta
        reasons.append(
            {
                "rule": "round2_self_rank",
                "my_round2_price": my_round2_price,
                "my_rank": my_rank,
                "delta": rank_delta,
            }
        )
    else:
        reasons.append(
            {"rule": "round2_self_rank", "delta": 0, "skip": "missing_self_round2_bid"}
        )

    if len(sorted_prices) >= 2:
        top1 = float(sorted_prices[0])
        top2 = max(1.0, float(sorted_prices[1]))
        ratio = top1 / top2
        ratio_delta = 0
        if ratio > 1.3:
            ratio_delta -= 1
        if ratio > 1.5:
            ratio_delta -= 1
        score += ratio_delta
        reasons.append(
            {
                "rule": "round2_top_ratio",
                "top1": int(top1),
                "top2": int(top2),
                "ratio": ratio,
                "delta": ratio_delta,
            }
        )

    if low_bids > 0:
        low_delta = -int(low_bids)
        score += low_delta
        reasons.append(
            {
                "rule": "round2_abandon_like_bid_count",
                "estimate_price": int(estimated_price),
                "threshold_lt_estimate_div_4": abandon_threshold,
                "count": int(low_bids),
                "delta": low_delta,
            }
        )

    max_box_id = _round3_max_box_id(pricing, board_snapshot)
    if max_box_id is not None:
        if max_box_id <= 30:
            pos_delta = -2
        elif max_box_id < 45:
            pos_delta = -1
        elif max_box_id > 80:
            pos_delta = 3
        elif max_box_id > 60:
            pos_delta = 2
        else:
            pos_delta = 1
        score += pos_delta
        reasons.append(
            {
                "rule": "current_max_box_id",
                "max_box_id": int(max_box_id),
                "delta": pos_delta,
            }
        )
    else:
        reasons.append(
            {"rule": "current_max_box_id", "delta": 0, "skip": "missing_max_box_id"}
        )

    detail["score"] = int(score)
    detail["protect"] = bool(score > 0)
    detail["reasons"] = reasons
    return detail


def apply_opponent_bid_adjustment(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    price_config: dict[str, Any],
    *,
    role: str,
    board_snapshot: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], int]:
    """快照口径对手价：按 ``role`` 选策略，解析 ``o_prev``、调价，并产出 ``opponent_bid`` 片段。"""
    from .strategies import apply_opponent_bid_adjustment_core_for_role

    o_prev: int | None = None
    if isinstance(board_snapshot, dict):
        o_prev = opponent_last_bid_default_from_snapshot(
            config, board_snapshot, round_no=int(round_no)
        )

    fin_before_opp = int(bid)
    fin, opp_tag, opp_detail = apply_opponent_bid_adjustment_core_for_role(
        str(role).strip().lower() or "aisha",
        config,
        fin_before_opp,
        int(round_no),
        o_prev,
        price_config,
        board_snapshot=board_snapshot,
        pricing=pricing,
    )

    if opp_tag:
        opponent_bid: dict[str, Any] = {
            "applied": True,
            "tag": opp_tag,
            "before": fin_before_opp,
            "after": fin,
            "o_prev": o_prev,
            "detail": opp_detail or {},
        }
    else:
        opponent_bid = {
            "applied": False,
            "o_prev": o_prev,
            "detail": opp_detail or {},
        }

    return int(fin), opponent_bid, fin_before_opp
