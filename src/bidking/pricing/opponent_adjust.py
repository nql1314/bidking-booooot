from __future__ import annotations

from typing import Any

from ..analysis._board_pricing import map_id_from_board_snapshot
from ..parsing.item_db import map_bundle_key_for_automation
from .snapshot_players import (
    board_snapshot_self_identity,
    max_other_player_bid_from_snapshot_players,
    player_round_price_bid,
    self_round_bid_from_snapshot,
)

# ``automation.maps`` 档键：幽静别墅 / 沉船密封舱；快照 ``players.*.prices`` 为排名而非金币。
SECRET_AUCTION_MAP_BUNDLE_KEYS: frozenset[str] = frozenset({"440", "450"})

# 隐秘拍卖按「名次差 behind」缩放估价；可被 ``configs/pricing.maps/<档键>.json`` 内
# ``pricing.secret_auction_rank_opponent_multipliers`` 覆盖。
_DEFAULT_SECRET_AUCTION_RANK_MULTIPLIERS: dict[str, float] = {
    "behind_ge_2": 1.08,
    "behind_1": 1.045,
    "behind_0": 1.012,
    "behind_lt_0": 0.994,
    "no_opponent_bid": 1.0,
}


def _secret_auction_rank_multipliers(config: dict[str, Any]) -> dict[str, float]:
    out = dict(_DEFAULT_SECRET_AUCTION_RANK_MULTIPLIERS)
    pr = config.get("pricing") if isinstance(config, dict) else None
    if not isinstance(pr, dict):
        return out
    raw = pr.get("secret_auction_rank_opponent_multipliers")
    if not isinstance(raw, dict):
        return out
    for key in out:
        if key not in raw:
            continue
        try:
            out[key] = float(raw[key])
        except (TypeError, ValueError):
            pass
    return out


def _parse_enable_opponent_bid_adjustment_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def opponent_bid_adjustment_enabled(
    config: dict[str, Any], price_config: dict[str, Any]
) -> bool:
    """
    是否执行对手价调整。读取顺序：``price_config`` → ``config[\"pricing\"]``；
    均未配置时默认 ``True``（保持历史行为）。

    配置键：``enable_opponent_bid_adjustment``（``false`` / ``0`` / ``\"off\"`` 等关闭）。
    """
    if isinstance(price_config, dict) and "enable_opponent_bid_adjustment" in price_config:
        return _parse_enable_opponent_bid_adjustment_flag(
            price_config.get("enable_opponent_bid_adjustment")
        )
    pr = config.get("pricing") if isinstance(config, dict) else None
    if isinstance(pr, dict) and "enable_opponent_bid_adjustment" in pr:
        return _parse_enable_opponent_bid_adjustment_flag(
            pr.get("enable_opponent_bid_adjustment")
        )
    return True


def board_map_bundle_key(board_snapshot: dict[str, Any] | None) -> str | None:
    """
    快照内**原始** ``MapId`` 的档键（如 ``4402`` → ``\"440\"``）。

    注意：不得先做 ``normalize_map_id``；否则 ``4402`` 会归一成 ``2402``，
    档键误为 ``\"240\"``，无法识别幽静别墅/沉船密封舱（隐秘拍卖）族。
    """
    if not isinstance(board_snapshot, dict):
        return None
    mid = map_id_from_board_snapshot(board_snapshot)
    if mid is None or int(mid) <= 0:
        return None
    return map_bundle_key_for_automation(int(mid))


def board_snapshot_is_secret_auction(board_snapshot: dict[str, Any] | None) -> bool:
    k = board_map_bundle_key(board_snapshot)
    return bool(k) and k in SECRET_AUCTION_MAP_BUNDLE_KEYS


def _secret_auction_prev_round_rank_detail(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    round_no: int,
) -> dict[str, Any]:
    """上一拍卖列（与 ``opponent_last_bid_default_from_snapshot`` 的 ``grid_round`` 一致）的排名信号。"""
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict) or not players:
        return {"skip": "no_players"}
    ref_r = max(1, int(round_no) - 1)
    self_uid, name_hint = board_snapshot_self_identity(config, board_snapshot)
    my_rank: int | None = None
    opp_ranks: list[int] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        rk = player_round_price_bid(pdata, ref_r)
        if rk is None:
            continue
        is_self = bool(self_uid and str(p_uid) == self_uid)
        if not is_self and name_hint:
            pname = str(pdata.get("name") or "")
            if name_hint in pname:
                is_self = True
        if is_self:
            my_rank = int(rk)
        else:
            opp_ranks.append(int(rk))
    opp_best: int | None = min(opp_ranks) if opp_ranks else None
    behind: int | None = None
    if my_rank is not None and opp_best is not None:
        behind = int(my_rank) - int(opp_best)
    return {
        "mode": "secret_rank",
        "ref_round_no": ref_r,
        "my_rank_prev": my_rank,
        "opponent_ranks_prev": opp_ranks,
        "opponent_best_rank_prev": opp_best,
        "behind_by": behind,
    }


def apply_secret_auction_rank_opponent_adjustment(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    *,
    board_snapshot: dict[str, Any],
    pricing: dict[str, Any] | None = None,
) -> tuple[int, str | None, dict[str, Any]]:
    """
    隐秘拍卖图：``prices`` 为名次（越小越靠前），缺失表示该轮未出价。
    在无法还原对手金币价时，按「我方相对最优对手名次差」对当前估价做轻量缩放。

    缩放系数来自 ``config[\"pricing\"][\"secret_auction_rank_opponent_multipliers\"]``
    （由 ``configs/pricing.maps/<档键>.json`` 深合并写入）；缺省与历史硬编码一致。
    """
    bid_i = int(bid)
    r_no = int(round_no)
    pricing_d = pricing if isinstance(pricing, dict) else {}
    detail = _secret_auction_prev_round_rank_detail(config, board_snapshot, r_no)

    if r_no <= 1:
        detail["skip"] = "round_lte_1"
        return bid_i, None, detail

    my_rank = detail.get("my_rank_prev")
    if my_rank is None:
        detail["skip"] = "no_self_rank_prev"
        return bid_i, None, detail

    mults = _secret_auction_rank_multipliers(config)
    detail["secret_auction_rank_multipliers"] = dict(mults)

    opp_best = detail.get("opponent_best_rank_prev")
    behind = detail.get("behind_by")
    if opp_best is None:
        fin = int(round(bid_i * mults["no_opponent_bid"]))
        tag = "secret_rank_no_opp_bid"
    elif behind is not None:
        if behind >= 2:
            fin = int(round(bid_i * mults["behind_ge_2"]))
            tag = "secret_rank_behind_far"
        elif behind == 1:
            fin = int(round(bid_i * mults["behind_1"]))
            tag = "secret_rank_behind_1"
        elif behind == 0:
            fin = int(round(bid_i * mults["behind_0"]))
            tag = "secret_rank_tied"
        else:
            fin = int(round(bid_i * mults["behind_lt_0"]))
            tag = "secret_rank_ahead"
    else:
        fin = bid_i
        tag = None

    ceiling_raw = pricing_d.get("points_ceiling")
    if ceiling_raw is not None:
        try:
            ceiling_pts = int(ceiling_raw)
            if ceiling_pts > 0 and fin > ceiling_pts:
                fin = ceiling_pts
                detail["ceiling_clamped"] = ceiling_pts
        except (TypeError, ValueError):
            pass

    fin = max(1, int(fin))
    if fin != bid_i and tag is None:
        tag = "secret_rank"
    return fin, tag, detail


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

    fin_before_opp = int(bid)
    pc = price_config if isinstance(price_config, dict) else {}
    if not opponent_bid_adjustment_enabled(config, pc):
        return fin_before_opp, {
            "applied": False,
            "disabled": True,
            "o_prev": None,
            "detail": {"reason": "enable_opponent_bid_adjustment_false"},
        }, fin_before_opp

    if isinstance(board_snapshot, dict) and board_snapshot_is_secret_auction(board_snapshot):
        fin, opp_tag, opp_detail = apply_secret_auction_rank_opponent_adjustment(
            config,
            fin_before_opp,
            int(round_no),
            board_snapshot=board_snapshot,
            pricing=pricing,
        )
        o_prev: int | None = None
    else:
        o_prev = None
        if isinstance(board_snapshot, dict):
            o_prev = opponent_last_bid_default_from_snapshot(
                config, board_snapshot, round_no=int(round_no)
            )

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
