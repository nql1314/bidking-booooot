from __future__ import annotations

import json
from typing import Any

from ..analysis._board_pricing import map_id_from_board_snapshot
from ..parsing.item_db import map_bundle_key_for_automation
from .self_bid_cache import get_self_gold_bid
from .snapshot_players import (
    board_snapshot_self_identity,
    max_other_player_bid_from_snapshot_players,
    player_round_price_bid,
    player_round_rank_signal,
    self_round_bid_from_snapshot,
)
from ._multipliers import resolve_round_multiplier

# ``automation.maps`` 档键：幽静别墅 / 沉船密封舱；快照 ``players.*.prices`` 为排名而非金币。
SECRET_AUCTION_MAP_BUNDLE_KEYS: frozenset[str] = frozenset({"440", "450"})

# 隐秘图：上回合己方排位 → 对手预估出价 = bid_pre * 系数（可被配置覆盖）
DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULTIPLIERS: dict[int, float] = {
    1: 1.0,
    2: 1.1,
    3: 1.2,
}
DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULT_FALLBACK: float = 1.3

# 隐秘图 ``players.*.prices`` 在有效对局中为名次 1–4（1 最好），与 ``self_bid_cache`` 回合键一致。
_SECRET_RANK_MIN = 1
_SECRET_RANK_MAX = 4


def _parse_rank_multiplier_value(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def resolve_secret_auction_rank_opponent_multipliers(
    config: dict[str, Any],
    price_config: dict[str, Any],
) -> dict[str, Any]:
    """
    解析 ``secret_auction_rank_opponent_multipliers``。

    读取顺序：``price_config`` → ``config["pricing"]`` → 内置默认。
    键支持 ``"1"``…``"4"``、``rank_1``…``rank_4``；``"default"`` / ``rank_default`` / ``"4+"`` 为第 4 名及以后。
    """
    raw: Any = None
    if isinstance(price_config, dict) and "secret_auction_rank_opponent_multipliers" in price_config:
        raw = price_config.get("secret_auction_rank_opponent_multipliers")
    pr = config.get("pricing") if isinstance(config, dict) else None
    if raw is None and isinstance(pr, dict) and "secret_auction_rank_opponent_multipliers" in pr:
        raw = pr.get("secret_auction_rank_opponent_multipliers")

    by_rank: dict[int, float] = dict(DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULTIPLIERS)
    fallback = DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULT_FALLBACK

    if isinstance(raw, dict):
        alias_to_rank = (
            ("1", 1),
            ("rank_1", 1),
            ("2", 2),
            ("rank_2", 2),
            ("3", 3),
            ("rank_3", 3),
            ("4", 4),
            ("rank_4", 4),
            ("4+", 4),
            ("default", 0),
            ("rank_default", 0),
        )
        for key, rank_slot in alias_to_rank:
            if key not in raw:
                continue
            parsed = _parse_rank_multiplier_value(raw.get(key))
            if parsed is None:
                continue
            if rank_slot == 0:
                fallback = parsed
            else:
                by_rank[rank_slot] = parsed

    return {"by_rank": by_rank, "fallback": fallback}


# 己方估价与对手/参考价折中时的默认权重（算术平均）
DEFAULT_OPPONENT_BID_BLEND_WEIGHT_BID: float = 0.5
DEFAULT_OPPONENT_BID_BLEND_WEIGHT_OPPONENT: float = 0.5


def _parse_blend_weight(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def resolve_opponent_bid_blend_weights(
    config: dict[str, Any],
    price_config: dict[str, Any],
) -> tuple[float, float]:
    """
    解析 ``opponent_bid_blend_weights``：己方 ``bid`` 与对手/参考价 ``opponent`` 的折中权重。

    读取顺序：``price_config`` → ``config["pricing"]`` → 内置默认（各 0.5）。
    """
    raw: Any = None
    if isinstance(price_config, dict) and "opponent_bid_blend_weights" in price_config:
        raw = price_config.get("opponent_bid_blend_weights")
    pr = config.get("pricing") if isinstance(config, dict) else None
    if raw is None and isinstance(pr, dict) and "opponent_bid_blend_weights" in pr:
        raw = pr.get("opponent_bid_blend_weights")

    w_bid = DEFAULT_OPPONENT_BID_BLEND_WEIGHT_BID
    w_opp = DEFAULT_OPPONENT_BID_BLEND_WEIGHT_OPPONENT

    if isinstance(raw, dict):
        alias_to_slot = (
            ("bid", "bid"),
            ("self", "bid"),
            ("opponent", "opp"),
            ("opp", "opp"),
            ("other", "opp"),
            ("reference", "opp"),
        )
        for key, slot in alias_to_slot:
            if key not in raw:
                continue
            parsed = _parse_blend_weight(raw.get(key))
            if parsed is None:
                continue
            if slot == "bid":
                w_bid = parsed
            else:
                w_opp = parsed

    for src in (price_config, pr):
        if not isinstance(src, dict):
            continue
        flat_bid = _parse_blend_weight(src.get("opponent_bid_blend_weight_bid"))
        flat_opp = _parse_blend_weight(src.get("opponent_bid_blend_weight_opponent"))
        if flat_bid is not None:
            w_bid = flat_bid
        if flat_opp is not None:
            w_opp = flat_opp

    return w_bid, w_opp


def blend_bid_with_opponent_reference(
    bid_i: int | float,
    reference: int | float,
    *,
    config: dict[str, Any],
    price_config: dict[str, Any],
) -> float:
    """加权折中：``(bid_i * w_bid + reference * w_opp) / (w_bid + w_opp)``。"""
    w_bid, w_opp = resolve_opponent_bid_blend_weights(config, price_config)
    total = w_bid + w_opp
    if total <= 0:
        return (float(bid_i) + float(reference)) / 2.0
    return (float(bid_i) * w_bid + float(reference) * w_opp) / total


def _is_secret_rank_signal(value: int) -> bool:
    return _SECRET_RANK_MIN <= int(value) <= _SECRET_RANK_MAX


def _secret_rank_slot(my_rank_signal: int | None) -> int | None:
    """隐秘图 ``prices`` 已是名次 1–4（1 最好），直接用作乘数档位。"""
    if my_rank_signal is not None and _is_secret_rank_signal(my_rank_signal):
        return int(my_rank_signal)
    return None


def _estimate_opponent_bid_by_rank(
    bid_pre: int,
    rank_slot: int,
    *,
    rank_multipliers: dict[str, Any] | None = None,
) -> float:
    """基于上回合己方名次（1–4）预估对手本回合出价：``bid_pre * mult``。"""
    cfg = rank_multipliers or {}
    by_rank: dict[int, float] = cfg.get("by_rank") or DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULTIPLIERS
    fallback = float(
        cfg.get("fallback")
        if cfg.get("fallback") is not None
        else DEFAULT_SECRET_AUCTION_RANK_OPPONENT_MULT_FALLBACK
    )
    r = int(rank_slot)
    if r >= 1:
        mult = float(by_rank.get(r, fallback))
    else:
        mult = fallback
    return float(bid_pre) * mult


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
    是否执行对手价调整。读取顺序：``price_config`` → ``config["pricing"]``；
    均未配置时默认 ``True``（保持历史行为）。

    配置键：``enable_opponent_bid_adjustment``（``false`` / ``0`` / ``"off"`` 等关闭）。
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
    快照内**原始** ``MapId`` 的档键（如 ``4402`` → ``"440"``）。

    注意：不得先做 ``normalize_map_id``；否则 ``4402`` 会归一成 ``2402``，
    档键误为 ``"240"``，无法识别幽静别墅/沉船密封舱（隐秘拍卖）族。
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
    """上一拍卖列排名信号。

    ``ref_round_no``：与 ``self_bid_history`` / ``get_self_gold_bid`` 一致的 1-based 回合（``round_no - 1``）。
    ``rank_signal_round``：PriceLog ``Round`` 键（0 起）；第 N 回合出价前仅 0..N-2 已写入，故用 ``ref_round_no - 1``。
    """
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict) or not players:
        return {"skip": "no_players"}
    ref_r = max(1, int(round_no) - 1)
    rank_signal_round = max(0, ref_r - 1)
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    my_rank: int | None = None
    opp_ranks: list[int] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        rk = player_round_rank_signal(pdata, rank_signal_round)
        if rk is None:
            continue
        is_self = bool(self_uid and str(p_uid) == self_uid)
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
        "rank_signal_round": rank_signal_round,
        "my_rank_prev": my_rank,
        "opponent_ranks_prev": opp_ranks,
        "opponent_best_rank_prev": opp_best,
        "behind_by": behind,
    }


def _log_secret_auction_opponent_debug(
    *,
    round_no: int,
    bid_i: int,
    detail: dict[str, Any],
    bid_pre: int | None = None,
    rank_mult_cfg: dict[str, Any] | None = None,
    o_estimated: float | None = None,
    tag: str | None = None,
    out: int | None = None,
) -> None:
    """隐秘对手调整：将 bid_pre / 乘数配置 / o_estimated / detail 打到控制台。"""
    from ..logsys.app_log import log_info

    parts: list[str] = [f"round={round_no}", f"bid_i={bid_i}"]
    if bid_pre is not None:
        parts.append(f"bid_pre={bid_pre}")
    if o_estimated is not None:
        parts.append(f"o_estimated={int(round(o_estimated))}")
    if rank_mult_cfg is not None:
        parts.append(
            "rank_mult_cfg="
            + json.dumps(rank_mult_cfg, ensure_ascii=False, separators=(",", ":"))
        )
    if tag:
        parts.append(f"tag={tag}")
    if out is not None:
        parts.append(f"out={out}")
    parts.append(
        "detail=" + json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    )
    log_info(" ".join(parts), tag="secret_opp")


def apply_secret_auction_rank_opponent_adjustment(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    *,
    board_snapshot: dict[str, Any],
    price_config: dict[str, Any],
) -> tuple[int, str | None, dict[str, Any]]:
    """
    隐秘拍卖图：``prices`` 为名次 1–4（1 最好），缺失表示该轮未出价。

    基于上回合自己的出价 (bid_pre) 与 ``prices`` 内名次预估对手出价：
    ``bid_pre * secret_auction_rank_opponent_multipliers[rank]``（默认 1→1.0, 2→1.1, 3→1.2, 4+→1.3；
    见 ``pricing.secret_auction_rank_opponent_multipliers``）。

    出价策略（类似aisha逻辑，无r3_protect）：
    - r5+: 取max((bid+o_est)/2*1.05, o_est*1.05) + 1000
    - bid > o_est * 1.05 + 1000: 出 blend(bid, adj)
    - bid > o_est: 出 o_est
    - bid > bid_pre: 出 min(o_est, blend(bid, bid_pre))
    - 其他: 出 blend(bid, o_est)
    """
    bid_i = int(bid)
    r_no = int(round_no)
    detail = _secret_auction_prev_round_rank_detail(config, board_snapshot, r_no)

    if r_no <= 2:
        detail["skip"] = "round_lte_1"
        _log_secret_auction_opponent_debug(
            round_no=r_no, bid_i=bid_i, detail=detail, tag=None, out=bid_i
        )
        return bid_i, None, detail

    my_rank_signal = detail.get("my_rank_prev")
    if my_rank_signal is None:
        detail["skip"] = "no_self_rank_prev"
        _log_secret_auction_opponent_debug(
            round_no=r_no, bid_i=bid_i, detail=detail, tag=None, out=bid_i
        )
        return bid_i, None, detail

    rank_slot = _secret_rank_slot(detail.get("my_rank_prev"))
    if rank_slot is None:
        detail["skip"] = "invalid_self_rank_prev"
        _log_secret_auction_opponent_debug(
            round_no=r_no, bid_i=bid_i, detail=detail, tag=None, out=bid_i
        )
        return bid_i, None, detail

    # 获取上回合自己的金币出价（隐秘图读缓存，不读 players.prices）
    ref_r = max(1, r_no - 1)
    bid_pre = get_self_gold_bid(config, board_snapshot, ref_r)
    if bid_pre is None or bid_pre <= 0:
        detail["skip"] = "no_self_bid_prev"
        detail["bid_pre_source"] = "self_bid_history"
        _log_secret_auction_opponent_debug(
            round_no=r_no, bid_i=bid_i, detail=detail, bid_pre=bid_pre, tag=None, out=bid_i
        )
        return bid_i, None, detail

    rank_mult_cfg = resolve_secret_auction_rank_opponent_multipliers(config, price_config)
    # 基于上回合名次（1–4）预估对手出价；``bid_pre`` 来自 ``self_bid_cache[ref_r]``
    o_estimated = _estimate_opponent_bid_by_rank(
        bid_pre, int(rank_slot), rank_multipliers=rank_mult_cfg
    )
    detail["rank_slot_for_multiplier"] = int(rank_slot)
    detail["bid_pre"] = bid_pre
    detail["bid_pre_source"] = "self_bid_history"
    detail["my_rank_prev"] = my_rank_signal
    detail["secret_auction_rank_multipliers"] = rank_mult_cfg
    detail["o_estimated_raw"] = o_estimated

    def _finish(tag: str, out: int) -> tuple[int, str, dict[str, Any]]:
        _log_secret_auction_opponent_debug(
            round_no=r_no,
            bid_i=bid_i,
            bid_pre=int(bid_pre),
            rank_mult_cfg=rank_mult_cfg,
            o_estimated=o_estimated,
            detail=detail,
            tag=tag,
            out=out,
        )
        return out, tag, detail

    # r5+ 特殊处理：最终轮激进出价
    if r_no >= 5:
        out = int(blend_bid_with_opponent_reference(
            bid_i, o_estimated, config=config, price_config=price_config
        ) + 1000)
        detail["final_round"] = True
        return _finish("secret_opp_final", out)
    mult = resolve_round_multiplier(round_no, price_config)
    # 调价阈值（类似aisha的adj）
    adj = o_estimated * mult + 1000
    detail["adj_threshold"] = adj

    # 出价决策逻辑（类似aisha，但用bid_pre替代o_prev）
    if bid_i > adj:
        # 当前估价远高于预估对手价+缓冲，折中出价
        out = int(round(blend_bid_with_opponent_reference(
            bid_i, adj, config=config, price_config=price_config
        )))
        return _finish("secret_opp_low", out)

    if bid_i > o_estimated:
        # 当前估价高于预估对手价，压低到预估价附近
        out = int(o_estimated)
        return _finish("secret_opp_est", out)

    if bid_i > bid_pre:
        # 当前估价高于上回合自己出价，折中但不超过预估对手价
        out = int(min(
            o_estimated,
            round(blend_bid_with_opponent_reference(
                bid_i, bid_pre, config=config, price_config=price_config
            )),
        ))
        return _finish("secret_opp_pre", out)

    # 其他情况：保守跟进，取当前估价与预估对手价的加权折中
    out = int(round(blend_bid_with_opponent_reference(
        bid_i, o_estimated, config=config, price_config=price_config
    )))
    return _finish("secret_opp_sticky", out)


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
        if board_snapshot_is_secret_auction(board_snapshot):
            s_prev = get_self_gold_bid(config, board_snapshot, prev_col_round)
        else:
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
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
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
        is_self = bool(self_uid and str(p_uid) == self_uid)
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
            price_config=price_config,
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
