#!/usr/bin/env python3
"""艾莎专用自动化：主循环仍用整窗 OCR 识别结束/大厅/主页等；竞拍回合数与对手价来自画板 JSON 快照。

不进行中央区 OCR、不做底价区 OCR；基础出价为快照 ``pricing.total`` 加空余估价（第 1–3 回合用语义估算空余×分档格均价，
优先 ``map_quality_avg_out.csv`` 按 ``map_id`` 取值；第 4 回合起主价为 ``total + vacant×`` q5 格均价下限，元信息中带 q5+q6 上限），
再仅经过 ``apply_opponent_bid_adjustment``、bid_cap、safe_guard，**不使用** value-anchor ceiling。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import math
from pathlib import Path
from typing import Any

import pyautogui

ROOT = Path(__file__).resolve().parent

from ..pricing._aisha_legacy import (  # noqa: E402
    _board_snapshot_self_identity,
    _count_quality_items_all,
    _player_round_price_log_bid,
    apply_aisha_vacant_red_floor_ceiling_pick,
    clear_board_snapshot_file,
    compute_aisha_snapshot_bid_points,
    current_round_from_snapshot,
    load_board_snapshot_for_aisha_bot,
    max_other_player_bid_from_snapshot_players,
    self_round_bid_from_snapshot,
    snapshot_bid_source_reason,
)
from . import _legacy_bot as fb  # noqa: E402

_ROUND5_SKIP_RATIO_OPPONENT_HERO_CIDS = frozenset({103, 107})


def _opponents_have_hero_cids(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    hero_cids: frozenset[int],
) -> bool:
    """除己方外的玩家（与快照对手价相同的 uid / name 排除规则）是否存在给定 hero_cid。"""
    bs_cfg = config.get("board_snapshot") or {}
    self_uid = str(bs_cfg.get("self_user_uid") or "").strip()
    name_hint = str(bs_cfg.get("self_name_substring") or "").strip()
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return False
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
        if hc in hero_cids:
            return True
    return False


def _resolve_aisha_bid_ratio(
    config: dict[str, Any],
    round_no: int,
    board_snapshot: dict[str, Any] | None = None,
) -> tuple[float, bool]:
    """``automation.bid_ratio_by_round``：按回合倍数，缺省用 ``default``，再无则 1.0。

    第 5 回合且任一对手 ``hero_cid`` 为 103、107 时不套用倍数，返回 ``(1.0, True)``。
    否则返回 ``(ratio, False)``。
    """
    if int(round_no) >= 4 and board_snapshot is not None:
        if _opponents_have_hero_cids(
            board_snapshot, config, _ROUND5_SKIP_RATIO_OPPONENT_HERO_CIDS
        ):
            return 1.0, True
    auto = config.get("automation") or {}
    raw = auto.get("bid_ratio_by_round")
    if raw is None:
        raw = config.get("bid_ratio_by_round")
    if not isinstance(raw, dict):
        return 1.0, False
    key = str(int(round_no))
    v = raw.get(key)
    if v is None:
        v = raw.get("default")
    if v is None:
        return 1.0, False
    try:
        r = float(v)
    except (TypeError, ValueError):
        return 1.0, False
    return (r if r > 0 else 1.0), False


def _aisha_log_json_snippet(obj: Any, max_len: int = 900) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        s = repr(obj)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _format_aisha_computed_price_log(
    final_price: int,
    details: dict[str, Any],
    config: dict[str, Any],
) -> str:
    """单行日志：最终价、快照基础与 meta、后处理链（金红 floor/ceiling 择优、倍数、对手、封顶、尾数、caps/guard）。"""
    _ = config
    reason = str(details.get("reason") or "").strip()
    head = f"price computed: {final_price}"
    line = f"{head}; {reason}" if reason else head
    src_bits: list[str] = []
    sv = details.get("source_value")
    if sv is not None:
        try:
            src_bits.append(f"source_value={int(round(float(sv)))}")
        except (TypeError, ValueError):
            src_bits.append(f"source_value={sv!r}")
    if details.get("fallback"):
        src_bits.append("fallback=1")
    if src_bits:
        line += " | src[" + ", ".join(src_bits) + "]"

    meta = details.get("board_snapshot_bid")
    if not isinstance(meta, dict) or not meta:
        line = _format_aisha_post_processing_log_line(line, details)
        return line

    m_bits: list[str] = []
    if meta.get("map_id") is not None:
        m_bits.append(f"map_id={meta['map_id']}")
    m_bits.append(f"map_csv_hit={bool(meta.get('map_quality_avg_hit'))}")
    cr = meta.get("current_round")
    if cr is not None:
        m_bits.append(f"snapshot_round={cr}")
    m_bits.append(f"early_estimated_vacant={bool(meta.get('early_round_estimated'))}")
    bps = meta.get("bid_points_source")
    if bps:
        m_bits.append(f"bid_points_source={bps}")
    grc = meta.get("gold_red_vacant_counts_certain")
    if grc is not None:
        m_bits.append(f"gold_red_vacant_certain={grc}")
    vmode = meta.get("vacant_pricing_mode")
    if vmode is not None and str(vmode).strip() != "":
        m_bits.append(f"vacant_pricing_mode={vmode}")
    line += " | meta[" + ", ".join(m_bits) + "]"

    snap_ex: list[str] = []
    if meta.get("early_round_estimated"):
        for k, lbl in (
            ("early_vacant_cells_for_linear_pricing", "vac_linear_cells"),
            ("early_vacant_cells_linear_float", "vac_linear_f"),
            ("vacant_geometric_for_pricing", "vac_geo"),
            ("vacant_map_skill_hidden_cell_reserve", "vac_reserve"),
        ):
            if meta.get(k) is not None:
                snap_ex.append(f"{lbl}={meta[k]}")
    else:
        for k, lbl in (
            ("vacant_unit_q5", "u_q5"),
            ("vacant_unit_q6", "u_q6"),
            ("vacant_unit_q5_q6", "u_q56"),
        ):
            if meta.get(k) is not None:
                snap_ex.append(f"{lbl}={meta[k]}")
    if meta.get("q6prob_in_group") is not None:
        snap_ex.append(f"q6prob_in_group={meta.get('q6prob_in_group')}")
    sup = meta.get("map_skill_gold_red_suppressed_ambiguous_contour")
    if isinstance(sup, dict) and sup:
        snap_ex.append(
            "contour_suppress[g="
            + str(sup.get("gold"))
            + ",r="
            + str(sup.get("red"))
            + "]"
        )
    pf_m = meta.get("points_floor")
    pc_m = meta.get("points_ceiling")
    pts_m = meta.get("points")
    if pts_m is not None:
        snap_ex.append(f"pts={pts_m}")
    if pf_m is not None and pf_m != pts_m:
        snap_ex.append(f"pts_floor={pf_m}")
    if pc_m is not None and pc_m != pts_m and pc_m != pf_m:
        snap_ex.append(f"pts_ceil={pc_m}")
    if snap_ex:
        line += " | snap[" + ", ".join(snap_ex) + "]"

    adj = meta.get("map_skill_adjustments")
    if isinstance(adj, list) and adj:
        line += " | map_skill_adj=" + _aisha_log_json_snippet(adj, 950)

    pricing = meta.get("pricing")
    total_int: int | None = None
    if isinstance(pricing, dict) and pricing.get("total") is not None:
        try:
            total_int = int(round(float(pricing["total"])))
        except (TypeError, ValueError):
            total_int = None

    b_bits: list[str] = []
    if total_int is not None:
        b_bits.append(f"pricing.total={total_int}")

    if meta.get("early_round_estimated"):
        vac = meta.get("vacant_used")
        unit = meta.get("vacant_unit_applied")
        pts = meta.get("points")
        cr_i = int(cr) if cr is not None else None
        tier = {1: "q2+q3+q4", 2: "q3+q4", 3: "q4"}.get(cr_i, "tier?")
        if (
            total_int is not None
            and vac is not None
            and unit is not None
            and pts is not None
        ):
            core = int(round(total_int + float(vac) * float(unit)))
            b_bits.append(
                f"snapshot_pts={pts} | vacant_formula={total_int}+{vac}*{unit}({tier})={core}"
                + (
                    " | formula_matches_pts"
                    if core == int(pts)
                    else " | note=pts_includes_map_skill_extras"
                )
            )
        det = meta.get("early_round_detail")
        if isinstance(det, dict):
            keys = (
                "max_anchor_box_id",
                "vacant_round_1_2",
                "vacant_round_3",
                "round_3_anchor_floor_exclusive",
                "known_quality_cell_count",
                "all_occupied_cell_count",
            )
            d_bits = [f"{k}={det[k]}" for k in keys if k in det]
            if d_bits:
                b_bits.append("vacancy[" + ", ".join(d_bits) + "]")
    else:
        vac = meta.get("vacant_used")
        u5 = meta.get("vacant_unit_q5")
        u56 = meta.get("vacant_unit_q5_q6")
        u6 = meta.get("vacant_unit_q6")
        pf = meta.get("points_floor")
        pc = meta.get("points_ceiling")
        pts = meta.get("points")
        mode = str(meta.get("vacant_pricing_mode") or "")
        split_like = mode.startswith("split")
        # round4+ 仅在「金/红总数均未知」的 default 分支才是 total+vac*q5 / total+vac*q5+q6；
        # gold/red 分拆、地图技能抬价等都会使「total+vac*单价」与 points_floor/ceiling 不一致。
        if (
            total_int is not None
            and vac is not None
            and u5 is not None
            and pf is not None
        ):
            naive_f = int(round(float(total_int) + float(vac) * float(u5)))
            if not split_like and naive_f == int(pf):
                b_bits.append(f"floor={total_int}+{vac}*{u5}={pf}")
            else:
                tail = f"naive_total+{vac}*q5={naive_f}, mode={mode or '?'}"
                adj = meta.get("map_skill_adjustments") or []
                split = (
                    adj[-1]
                    if isinstance(adj, list) and adj and isinstance(adj[-1], dict)
                    else {}
                )
                if split_like and split:
                    gn = split.get("gold_like_cells_est")
                    rn = split.get("red_cells_est")
                    if (
                        gn is not None
                        and rn is not None
                        and u6 is not None
                        and int(gn) + int(rn) == int(vac)
                    ):
                        gv = int(round(float(gn) * float(u5)))
                        rv = int(round(float(rn) * float(u6)))
                        tail = f"split vacant: {gn}*q5+{rn}*q6 => +{gv}+{rv}; {tail}"
                b_bits.append(f"floor={pf} ({tail})")
        if (
            total_int is not None
            and vac is not None
            and u56 is not None
            and pc is not None
        ):
            naive_c = int(round(float(total_int) + float(vac) * float(u56)))
            if not split_like and naive_c == int(pc):
                b_bits.append(f"ceiling={total_int}+{vac}*{u56}={pc}")
            else:
                b_bits.append(
                    f"ceiling={pc} (naive_total+{vac}*q5+q6={naive_c}, mode={mode or '?'})"
                )
        snap_v = pricing.get("vacant") if isinstance(pricing, dict) else None
        if snap_v is not None:
            b_bits.append(f"pricing.vacant={snap_v}")
        if (
            snap_v is not None
            and vac is not None
            and str(snap_v).strip() != ""
            and int(round(float(snap_v))) != int(vac)
        ):
            b_bits.append(
                "note=pricing.vacant_vs_meta.vacant_used_mismatch_check_reserve"
            )

    if not meta.get("early_round_estimated"):
        pf = meta.get("points_floor")
        pts = meta.get("points")
        if pf is not None and pts is not None:
            b_bits.append(f"snapshot_points_floor={pts}")

    if b_bits:
        line += " | " + " | ".join(b_bits)
    return _format_aisha_post_processing_log_line(line, details)


def _format_aisha_post_processing_log_line(
    line: str, details: dict[str, Any]
) -> str:
    """``apply_aisha_price_post_processing`` 写入 ``details`` 的各步因子（与 meta 无关时也可单独调用）。"""
    post: list[str] = []

    vr = details.get("vacant_red_floor_ceiling_pick")
    if isinstance(vr, dict):
        if vr.get("applied"):
            post.append(
                "vac_red_pick["
                + ",".join(
                    f"{k}={vr.get(k)}"
                    for k in (
                        "has_red_inferred",
                        "chosen_points",
                        "before_pick",
                        "after_pick",
                        "points_floor",
                        "points_ceiling",
                    )
                    if vr.get(k) is not None
                )
                + "]"
            )
            inf = vr.get("inference")
            if isinstance(inf, dict) and inf:
                infer_keys = (
                    "decision_rule",
                    "vacant_used",
                    "current_round",
                    "points_floor_ref",
                    "red_quality_item_count_on_board",
                    "reference_price_round",
                    "our_bid_same_round",
                    "opponent_count_ge_two_rule",
                    "opponent_count_ge_one_rule",
                    "opponent_history_suggests_red",
                    "hero_110_red_signal",
                    "has_red_inferred",
                )
                post.append(
                    "vac_infer["
                    + ",".join(f"{k}={inf.get(k)}" for k in infer_keys if k in inf)
                    + "]"
                )
        else:
            rr = vr.get("reason")
            if rr:
                extra = ""
                ck = vr.get("config_map_key")
                if ck is not None:
                    extra = f",config_map_key={ck}"
                post.append(f"vac_red_pick[applied=0,reason={rr}{extra}]")

    br = details.get("bid_ratio") if isinstance(details.get("bid_ratio"), dict) else {}
    if br.get("ratio") is not None:
        chunk = f"bid_ratio[r={br.get('round')}]={br['ratio']}"
        if br.get("before") is not None and br.get("after") is not None:
            chunk += f": {br['before']}→{br['after']}"
        if br.get("skipped_multiplier_opponent_hero_103_or_107"):
            chunk += ",skip_hero103_107=1"
        post.append(chunk)

    ob = details.get("opponent_bid")
    if isinstance(ob, dict):
        parts: list[str] = [f"applied={bool(ob.get('applied'))}"]
        if ob.get("tag") is not None:
            parts.append(f"tag={ob.get('tag')}")
        if ob.get("o_prev") is not None:
            parts.append(f"o_prev={ob.get('o_prev')}")
        if ob.get("before") is not None and ob.get("after") is not None:
            parts.append(f"{ob['before']}→{ob['after']}")
        od = ob.get("detail")
        if isinstance(od, dict):
            if "protect" in od:
                parts.append(f"r3_protect={od.get('protect')}")
            if od.get("score") is not None:
                parts.append(f"r3_score={od.get('score')}")
            rs = od.get("reasons")
            if isinstance(rs, list) and rs:
                parts.append("r3_rules=" + _aisha_log_json_snippet(rs, 320))
        post.append("opp[" + ",".join(parts) + "]")

    cp = details.get("ceiling_points")
    if isinstance(cp, dict) and cp.get("applied"):
        post.append(
            "ceil_pts["
            + ",".join(
                f"{k}={cp.get(k)}"
                for k in ("q5_q6_ceiling", "before", "after")
                if cp.get(k) is not None
            )
            + "]"
        )

    ht = details.get("human_price_tail")
    if isinstance(ht, dict) and ht.get("after") is not None:
        post.append(
            "human_tail["
            + ",".join(
                f"{k}={ht.get(k)}"
                for k in ("before", "after", "pattern")
                if ht.get(k) is not None
            )
            + "]"
        )

    erf = details.get("early_round_fallback_floor")
    if isinstance(erf, dict) and erf.get("applied"):
        post.append(
            "early_fallback["
            + ",".join(
                f"{k}={erf.get(k)}"
                for k in ("fallback", "before", "after", "round")
                if erf.get(k) is not None
            )
            + "]"
        )

    cap = details.get("bid_cap")
    if isinstance(cap, dict) and cap.get("enabled"):
        post.append(
            "bid_cap["
            + ",".join(
                f"{k}={cap.get(k)}"
                for k in ("cap_price", "applied", "original_price")
                if k in cap and cap.get(k) is not None
            )
            + "]"
        )

    sg = details.get("safe_guard")
    if isinstance(sg, dict) and sg.get("enabled"):
        post.append(
            "safe_guard["
            + ",".join(
                f"{k}={sg.get(k)}"
                for k in (
                    "triggered",
                    "previous_price",
                    "limit_price",
                    "safe_limit_ratio",
                )
                if k in sg and sg.get(k) is not None
            )
            + "]"
        )

    if post:
        line += " | post[" + " | ".join(post) + "]"
    return line


def _board_snapshot_file_missing(config: dict[str, Any]) -> bool:
    """``board_snapshot`` 已启用且配置了 path，但磁盘上尚无该文件（常见于先启 bot、后点开局）。"""
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return False
    raw_path = str(bs.get("path") or "").strip()
    if not raw_path:
        return True
    try:
        return not Path(raw_path).is_file()
    except OSError:
        return True


def _game_uid_from_snapshot(data: dict[str, Any] | None) -> str | None:
    """根级 ``game_uid`` 或 ``game_state.uid``；用于判断是否进入新的一局。"""
    if not data:
        return None
    uid = data.get("game_uid")
    if uid is not None:
        s = str(uid).strip()
        if s:
            return s
    gs = data.get("game_state")
    if isinstance(gs, dict):
        u = gs.get("uid")
        if u is not None:
            s = str(u).strip()
            if s:
                return s
    return None


def _aisha_game_started(bs_data: dict[str, Any] | None, observation: Any) -> bool:
    """快照回合或整窗 OCR 回合任一表明已进入竞拍。"""
    if bs_data:
        sr = current_round_from_snapshot(bs_data)
        if sr is not None and int(sr) >= 1:
            return True
    rn = observation.round_no
    return rn is not None and int(rn) >= 1


def apply_early_round_fallback_floor(
    fin: int,
    round_no: int,
    fallback_floor: int,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """仅第 1、2 回合：出价低于 ``fallback_bid_price`` 时使用 fallback 价。"""
    fin = int(fin)
    fb_floor = int(fallback_floor)
    r = int(round_no)
    if r not in (1, 2):
        payload["early_round_fallback_floor"] = {
            "applied": False,
            "reason": "not_round_1_or_2",
        }
        return fin, payload
    if fin >= fb_floor:
        payload["early_round_fallback_floor"] = {
            "applied": False,
            "reason": "already_ge_fallback",
            "fallback": fb_floor,
            "round": r,
        }
        return fin, payload
    before = fin
    fin = fb_floor
    payload["early_round_fallback_floor"] = {
        "applied": True,
        "fallback": fb_floor,
        "before": before,
        "after": fin,
        "round": r,
    }
    return fin, payload


def _round3_max_box_id(
    meta: dict[str, Any], board_snapshot: dict[str, Any] | None
) -> int | None:
    candidates: list[Any] = [meta.get("max_anchor_box_id")]
    early = meta.get("early_round_detail")
    if isinstance(early, dict):
        candidates.append(early.get("max_anchor_box_id"))
    if isinstance(board_snapshot, dict):
        pricing = board_snapshot.get("pricing")
        if isinstance(pricing, dict):
            candidates.append(pricing.get("max_anchor_box_id"))
            aisha_bid = pricing.get("aisha_bid")
            if isinstance(aisha_bid, dict):
                candidates.append(aisha_bid.get("max_anchor_box_id"))
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
    meta: dict[str, Any] | None,
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
    meta_map = meta if isinstance(meta, dict) else {}
    self_uid, self_name = _board_snapshot_self_identity(config, board_snapshot)
    round2_prices: list[int] = []
    my_round2_price: int | None = None
    low_bids = 0
    abandon_threshold = max(1.0, float(estimated_price) / 4.0)
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        p2 = _player_round_price_log_bid(pdata, 2)
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
        my_rank = sorted_prices.index(my_round2_price) + 1
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

    max_box_id = _round3_max_box_id(meta_map, board_snapshot)
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


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(float(v) for v in values)
    n = len(s)
    m = n // 2
    if n % 2 == 1:
        return s[m]
    return 0.5 * (s[m - 1] + s[m])


def apply_aisha_red_cells_increment_price(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    meta: dict[str, Any],
    round_no: int,
    fin: int,
) -> tuple[int, dict[str, Any]]:
    detail: dict[str, Any] = {"applied": False, "round": int(round_no)}
    if int(round_no) < 4:
        detail["reason"] = "round_lt_4"
        return int(fin), detail
    pf = meta.get("points_floor")
    if pf is None:
        detail["reason"] = "missing_points_floor"
        return int(fin), detail
    u5 = meta.get("vacant_unit_q5")
    u6 = meta.get("vacant_unit_q6")
    try:
        floor_pts = int(pf)
        cell_delta = int(round(float(u6) - float(u5)))
    except (TypeError, ValueError):
        detail["reason"] = "invalid_q5_q6_unit_price"
        return int(fin), detail
    if cell_delta <= 0:
        detail["reason"] = "non_positive_cell_delta"
        detail["cell_delta"] = cell_delta
        return int(fin), detail

    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    items = (board_snapshot.get("game_state") or {}).get("items") or {}
    if not isinstance(players, dict):
        detail["reason"] = "missing_players"
        return int(fin), detail
    occupied = len(items) if isinstance(items, dict) else 0
    know_red = _count_quality_items_all(board_snapshot, 6)
    q6prob = meta.get("q6prob_in_group")
    factor_total: float | None = None
    if q6prob is not None:
        try:
            q6p = float(q6prob)
            if q6p > 0:
                factor_total = max(0.0, float(occupied) * q6p - float(know_red))
        except (TypeError, ValueError):
            factor_total = None
    detail["factor_total_by_occupied"] = factor_total
    detail["occupied_cells"] = occupied
    detail["know_red"] = know_red
    detail["q6prob_in_group"] = q6prob

    self_uid, self_name = _board_snapshot_self_identity(config, board_snapshot)
    opp_samples: list[float] = []
    hero119_samples: list[float] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        pname = str(pdata.get("name") or "")
        if self_name and self_name in pname:
            continue
        r3 = _player_round_price_log_bid(pdata, 3)
        r4 = _player_round_price_log_bid(pdata, 4)
        for bid in (r3, r4):
            if bid is None:
                continue
            opp_samples.append((float(bid) - float(floor_pts)) / float(cell_delta))
        try:
            hc = int(pdata.get("hero_cid") or 0)
        except (TypeError, ValueError):
            hc = 0
        if hc == 119:
            vals = [b for b in (r3, r4) if b is not None]
            if vals:
                avg_bid = float(sum(vals)) / float(len(vals))
                hero119_samples.append((avg_bid - float(floor_pts)) / float(cell_delta))

    factor_opp = _median(opp_samples)
    factor_hero119 = _median(hero119_samples)
    detail["factor_from_opponents"] = factor_opp
    detail["factor_from_hero_119"] = factor_hero119
    detail["opponent_sample_count"] = len(opp_samples)
    detail["hero_119_sample_count"] = len(hero119_samples)

    factors = [f for f in (factor_total, factor_opp, factor_hero119) if f is not None]
    if not factors:
        detail["reason"] = "no_available_factors"
        return int(fin), detail
    avg_factor = float(sum(factors)) / float(len(factors))
    n = int(math.floor(avg_factor))
    detail["factor_avg"] = avg_factor
    detail["red_cells_floor_n"] = n
    detail["cell_delta"] = cell_delta
    detail["points_floor"] = floor_pts
    if n <= 0:
        detail["reason"] = "n_le_0"
        return int(fin), detail
    new_fin = int(floor_pts + n * cell_delta)
    detail["applied"] = True
    detail["reason"] = "floor_plus_red_cells_increment"
    detail["before"] = int(fin)
    detail["after"] = new_fin
    return new_fin, detail


def apply_aisha_price_post_processing(
    config: dict[str, Any],
    round_no: int,
    opponent_last_bid: int | None,
    price_config: dict[str, Any],
    final_price: int,
    payload: dict[str, Any],
    meta: dict[str, Any],
    *,
    fallback_floor: int,
    board_snapshot: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """金红未定 floor/ceiling 择优 → 出价系数（按回合）→ 对手价调整 → ceil pts → bid_cap + safe_guard。"""
    fin = int(final_price)
    if board_snapshot:
        fin, vac_red_pick = apply_aisha_vacant_red_floor_ceiling_pick(
            config, board_snapshot, meta, int(round_no), fin
        )
        if vac_red_pick.get("applied"):
            payload["vacant_red_floor_ceiling_pick"] = vac_red_pick
        # fin, red_inc = apply_aisha_red_cells_increment_price(
        #     config, board_snapshot, meta, int(round_no), fin
        # )
        # payload["vacant_red_cells_increment"] = red_inc
    ratio, ratio_skipped_r5_hero = _resolve_aisha_bid_ratio(
        config, int(round_no), board_snapshot
    )
    fin_before_ratio = fin
    fin = int(round(fin * ratio))
    br: dict[str, Any] = {
        "round": int(round_no),
        "ratio": ratio,
        "before": fin_before_ratio,
        "after": fin,
    }
    if ratio_skipped_r5_hero:
        br["skipped_multiplier_opponent_hero_103_or_107"] = True
    payload["bid_ratio"] = br
    fin_before_opp = fin
    fin, opp_tag, opp_detail = apply_opponent_bid_adjustment(
        config,
        fin,
        int(round_no),
        opponent_last_bid,
        price_config,
        board_snapshot=board_snapshot,
        meta=meta,
    )
    if opp_tag:
        payload["opponent_bid"] = {
            "applied": True,
            "tag": opp_tag,
            "before": fin_before_opp,
            "after": fin,
            "o_prev": opponent_last_bid,
            "value_anchor_ceiling": "skipped",
            "detail": opp_detail or {},
        }
    else:
        payload["opponent_bid"] = {
            "applied": False,
            "o_prev": opponent_last_bid,
            "value_anchor_ceiling": "skipped",
            "detail": opp_detail or {},
        }
    ceiling_pts = meta.get("points_ceiling")
    if ceiling_pts is None:
        ceiling_pts = meta.get("q5_q6_ceiling")
    fin, payload = apply_ceiling_points(
        fin, fin_before_opp, ceiling_pts, payload, int(round_no)
    )
    fin, payload = apply_human_like_price_tail(fin, payload)
    fin, payload = apply_early_round_fallback_floor(
        fin, int(round_no), int(fallback_floor), payload
    )
    fin, payload = fb.apply_bid_cap(config, fin, payload)
    fin, payload = fb.apply_safe_guard(config, fin, payload)
    return fin, payload


def evaluate_opponent_bid_possibilities(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
    _meta: dict[str, Any] | None,
    round_no: int,
    o_prev: int,
) -> float:
    """根据上一回合己方出价 ``s_prev`` 与对手最高价 ``o_prev`` 估算本回合对手可能抬到的量级。

    ``o_prev`` 与 ``handle_aisha_round`` 中 ``opponent_bid_grid_round = max(1, round_no - 1)``
    列一致；``s_prev`` 取同一 PriceLog 列上己方出价。

    - ``s_prev < o_prev``：我方落后，认为全场最高价不会大幅跃升 → ``1.1 * o_prev``。
    - ``s_prev > o_prev``：我方领先，对手可能追赶 → ``1.1 * s_prev``。
    - ``s_prev`` 缺失或与 ``o_prev`` 相等：保守按 ``1.1 * o_prev``。
    """
    prev_col_round = max(1, int(round_no) - 1)
    s_prev: int | None = None
    if board_snapshot:
        s_prev = self_round_bid_from_snapshot(config, board_snapshot, prev_col_round)
    if s_prev is None or s_prev <= int(o_prev):
        return 1.05 * float(o_prev)
    return 1.05 * float(s_prev)


def apply_opponent_bid_adjustment(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    o_prev: int | None,
    price_config: dict[str, Any],
    board_snapshot: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[int, str | None, dict[str, Any] | None]:
    if int(round_no) <= 2 or o_prev is None:
        return int(bid), None, None
    if o_prev > meta.get("points_ceiling"):
        return int(bid), "opp_high", None
    o_poss = evaluate_opponent_bid_possibilities(
        config, board_snapshot, meta, int(round_no), int(o_prev)
    )
    mult = fb.resolve_round_multiplier(round_no, price_config)
    adj = o_poss * mult + 1000
    if round_no >= 5:
        return (
            int(
                max(
                    (bid + o_poss * 1.05) / 2.0 + random.randint(1000, 1500),
                    float(o_poss * 1.05) + random.randint(1000, 1500),
                )
            ),
            "opp_final",
            None,
        )
    if round_no == 3:
        r3_detail = _round3_protect_decision(config, board_snapshot, meta, int(bid))
        if not bool(r3_detail.get("protect")):
            return (bid + o_prev) / 2, "opp_r3_no_protect", r3_detail
    if bid > adj:
        if round_no == 3:
            return adj, "opp_low", None
        return (bid + adj)/2, "opp_low", None
    if bid > o_poss:
        return o_poss, "opp_poss", None
    if bid > o_prev:
        return min(o_poss, (bid + o_prev) / 2), "opp_pre", None
    return bid, "opp_sticky", None


def apply_ceiling_points(
    fin: int,
    fin_before_opp: int,
    ceiling_pts: int | None,
    payload: dict[str, Any],
    round_no: int,
) -> tuple[int, dict[str, Any]]:
    if ceiling_pts is None:
        return int(fin), payload
    if round_no <= 3:
        return fin, payload
    if fin <= ceiling_pts:
        payload["ceiling_points"] = {
            "applied": True,
            "q5_q6_ceiling": ceiling_pts,
            "before": fin_before_opp,
            "after": fin,
        }
        return int(fin), payload
    else:
        return min(ceiling_pts, int(fin_before_opp)), payload


def _default_aisha_warehouse_auto_sort_settings() -> dict[str, Any]:
    """1920×1080 参考分辨率下的仓库入口与自动排序按钮区域（随 ``window.reference_client_size`` 缩放）。"""
    return {
        "enabled": True,
        "wait_after_warehouse_click_seconds": 5.0,
        "wait_after_auto_sort_click_seconds": 5.0,
        "warehouse_button_region": {"left": 71, "top": 992, "width": 111, "height": 53},
        "auto_sort_region": {"left": 1436, "top": 1010, "width": 155, "height": 34},
    }


def _merge_aisha_warehouse_auto_sort_settings(config: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_aisha_warehouse_auto_sort_settings()
    raw = (config.get("automation") or {}).get("aisha_warehouse_auto_sort")
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for key, val in raw.items():
        if key in ("warehouse_button_region", "auto_sort_region") and isinstance(
            val, dict
        ):
            base = dict(defaults[key]) if isinstance(defaults.get(key), dict) else {}
            base.update(val)
            out[key] = base
        else:
            out[key] = val
    return out


def _click_client_region_center(
    config: dict[str, Any], region: dict[str, Any], label: str
) -> None:
    fb.ensure_not_stopped()
    fb.bring_window_to_front(config)
    frame, _info = fb.capture_window_frame(config)
    left, top, right, bottom = fb.scaled_region_box(
        region, config, frame.width, frame.height
    )
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    sx, sy = fb.client_to_screen(config, {"x": cx, "y": cy})
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    pause = float(config.get("timing", {}).get("click_pause_seconds", 0.12))
    fb.log(
        f"aisha warehouse: click {label} client_center=({cx},{cy}) -> screen=({sx},{sy})",
        gui_verbose_only=True,
    )
    if not dry_run:
        pyautogui.click(sx, sy)
    fb.sleep_interruptible(pause)
    if bool(config.get("safety", {}).get("park_mouse_after_clicks", True)):
        fb.park_mouse_if_configured(config)


def run_aisha_warehouse_auto_sort(config: dict[str, Any]) -> None:
    """主页上：点仓库 → 等待 → 自动排序 → 等待 → ESC 回主界面。"""
    wc = _merge_aisha_warehouse_auto_sort_settings(config)
    if not bool(wc.get("enabled", True)):
        return
    wh_region = wc.get("warehouse_button_region")
    sort_region = wc.get("auto_sort_region")
    if not isinstance(wh_region, dict) or not isinstance(sort_region, dict):
        fb.log("aisha warehouse: 区域配置无效，跳过")
        return
    w1 = max(0.0, float(wc.get("wait_after_warehouse_click_seconds", 5.0) or 0.0))
    w2 = max(0.0, float(wc.get("wait_after_auto_sort_click_seconds", 5.0) or 0.0))
    fb.log("aisha warehouse: 进入仓库并自动排序", gui_verbose_only=True)
    _click_client_region_center(config, wh_region, "warehouse_entry")
    if w1 > 0:
        fb.sleep_interruptible(w1)
    _click_client_region_center(config, sort_region, "auto_sort")
    if w2 > 0:
        fb.sleep_interruptible(w2)
    fb.press_escape(config)
    fb.log("aisha warehouse: 已 ESC 返回主界面", gui_verbose_only=True)


def apply_human_like_price_tail(
    fin: int, payload: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """千分位以下随机向上对齐到 333 / 666 / 888；若抽到 000 则千位加一并尾数 000。"""
    fin = int(fin)
    before = fin
    high, _low = divmod(fin, 1000)
    # None 表示尾数 000 且千位 +1
    pattern = random.choice((333, 666, 888, None))
    if pattern is None:
        fin = (high + 1) * 1000
        tag = "000_carry"
    else:
        cand = high * 1000 + pattern
        fin = cand if cand >= fin else (high + 1) * 1000 + pattern
        tag = str(pattern)
    payload["human_price_tail"] = {"before": before, "after": fin, "pattern": tag}
    return fin, payload


def compute_aisha_round_price(
    config: dict[str, Any],
    round_no: int,
    price_config: dict[str, Any],
    opponent_last_bid: int | None,
    board_snapshot: dict[str, Any],
    advisor_input: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    pricing_cfg = config.get("pricing", {})
    fallback = fb.parse_int_config(pricing_cfg.get("fallback_bid_price"), 22223)
    pts, meta = compute_aisha_snapshot_bid_points(config, board_snapshot)
    payload: dict[str, Any] = {
        "fallback": False,
        "reason": "",
        "facts": 0,
        "parsed": {"parsed_facts": []},
        "advisor_input": advisor_input,
        "result": {},
        "source_value": None,
        "board_snapshot_bid": meta,
        "aisha_snapshot_bot": True,
    }
    if pts is None:
        payload["fallback"] = True
        if meta.get("early_round_estimated") and int(meta.get("points") or 0) == 0:
            payload["reason"] = "aisha bot: 前三回合快照点数为 0（可能未扫到物品）"
        else:
            payload["reason"] = "aisha bot: 快照 pricing 不完整"
        fin = fallback
        payload["source_value"] = float(fin)
    else:
        payload["source_value"] = float(pts)
        payload["reason"] = f"{snapshot_bid_source_reason()}: base={pts}"
        fin = pts
    fin, payload = apply_aisha_price_post_processing(
        config,
        round_no,
        opponent_last_bid,
        price_config,
        fin,
        payload,
        meta,
        fallback_floor=fallback,
        board_snapshot=board_snapshot,
    )
    return fin, payload


def observe_aisha_round_light(
    config: dict[str, Any],
    config_path: Path,
    label: str,
    *,
    round_no: int,
    opponent_last_bid: int | None,
    scan_session: dict[str, Any] | None,
) -> tuple[fb.Observation, int | None]:
    """仅保留回合前等待与可选截图：无中央区 OCR、无底价 OCR、无对手网格 OCR。"""
    t_obs = time.perf_counter()
    fb.bring_window_to_front(config)
    fb.park_mouse_if_configured(config)
    frame, _info = fb.capture_window_frame(config)
    runs_dir = fb.ensure_output_dir(config, config_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    image_path: Path | None = None
    if bool(config.get("debug", {}).get("save_crops", True)):
        image_path = runs_dir / f"{timestamp}_{label}_full_window.png"
        frame.save(image_path)

    timing_cfg = config.get("timing", {}) or {}
    target_pre_central = max(
        0.0,
        float(timing_cfg.get("round_detect_wait_seconds", 0.0) or 0.0)
        + (
            float(timing_cfg.get("round1_extra_wait_seconds", 0.0) or 0.0)
            if int(round_no) == 1
            else 0.0
        ),
    )
    t_pre = time.perf_counter()
    elapsed = time.perf_counter() - t_pre
    remaining = max(0.0, target_pre_central - elapsed)
    if remaining > 0:
        fb.sleep_interruptible(remaining)
    frame, _info = fb.capture_window_frame(config)
    if bool(config.get("debug", {}).get("save_crops", True)):
        frame.save(runs_dir / f"{timestamp}_{label}_after_wait_full_window.png")

    capture = fb.CaptureResult(
        text="",
        image_path=image_path,
        parsed={"parsed_facts": []},
    )
    observation = fb.Observation(
        capture=capture,
        end_text="",
        round_no=int(round_no),
        end_prompt=False,
        reward_continue=False,
        failed_auction_settlement=False,
        auction_lobby=False,
        home_bid_button=False,
        has_any_signal=False,
    )
    fb.perf_log_elapsed(f"observe_aisha[{label}] 总计", t_obs)
    return observation, opponent_last_bid


def handle_aisha_round(
    config: dict[str, Any],
    config_path: Path,
    price_config: dict[str, Any],
    round_no: int,
    knowledge_patch: dict[str, Any] | None,
    scan_session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    fb.ensure_not_stopped()
    fb.click_loot_overlay_dismiss_if_enabled(config)
    tool_rounds = {
        int(item) for item in config.get("automation", {}).get("tool_rounds", [1, 2])
    }
    ran_tool_this_round = int(round_no) in tool_rounds
    seconds = float(config.get("timing", {}).get("tool_after_wait_seconds", 5.0))
    if ran_tool_this_round:
        fb.run_tool_sequence(config)
        fb.log(f"after tool: wait {seconds:g}s", gui_verbose_only=True)
        if seconds > 0:
            fb.sleep_interruptible(seconds)
    else:
        fb.log(f"round {round_no}: tool skipped by config", gui_verbose_only=True)

    bs_cfg = config.get("board_snapshot") or {}
    timing_cfg = config.get("timing") or {}
    wait_interval = max(
        0.05,
        float(
            bs_cfg.get("wait_poll_seconds")
            or timing_cfg.get("poll_seconds", 1.0)
            or 1.0
        ),
    )
    timeout_raw = bs_cfg.get("wait_timeout_seconds")
    wait_deadline: float | None = None
    if timeout_raw is not None:
        try:
            wait_deadline = time.monotonic() + max(0.0, float(timeout_raw))
        except (TypeError, ValueError):
            wait_deadline = None

    board_snapshot = load_board_snapshot_for_aisha_bot(config)
    wait_started = time.monotonic()
    last_wait_log = wait_started
    wait_intro_logged = False
    while not board_snapshot:
        fb.ensure_not_stopped()
        if wait_deadline is not None and time.monotonic() >= wait_deadline:
            fb.log("aisha bot: 等待 board_snapshot 超时，跳过出价")
            return knowledge_patch
        if not wait_intro_logged:
            fb.log(f"aisha bot: 无有效快照，每 {wait_interval:g}s 重试直到可用")
            wait_intro_logged = True
        now = time.monotonic()
        if now - last_wait_log >= 10.0:
            fb.log(f"aisha bot: 仍在等待快照 ({now - wait_started:.0f}s)")
            last_wait_log = now
        fb.sleep_interruptible(wait_interval)
        board_snapshot = load_board_snapshot_for_aisha_bot(config)

    snap_round = current_round_from_snapshot(board_snapshot)
    if snap_round is None:
        fb.log("aisha bot: 快照缺少 current_round")
        return knowledge_patch
    if int(snap_round) != int(round_no):
        fb.log(
            f"aisha bot: 调度回合 {round_no} 与快照回合 {snap_round} 不一致，以快照为准执行"
        )
        round_no = int(snap_round)

    opponent_bid_grid_round = max(1, int(round_no) - 1)
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    opponent_last_bid = max_other_player_bid_from_snapshot_players(
        players,
        opponent_bid_grid_round,
        self_user_uid=str(bs_cfg.get("self_user_uid") or ""),
        self_name_substring=str(bs_cfg.get("self_name_substring") or ""),
        board_snapshot=board_snapshot,
    )
    if opponent_last_bid is not None:
        fb.log(
            f"aisha bot: 对手价来自快照 col={opponent_bid_grid_round} -> {opponent_last_bid}"
        )
    else:
        fb.log("aisha bot: 快照无对手上一列出价，对手调整按空")

    observation, opp_bid = observe_aisha_round_light(
        config,
        config_path,
        f"round{round_no}_after_tool",
        round_no=round_no,
        opponent_last_bid=opponent_last_bid,
        scan_session=scan_session,
    )
    knowledge_patch = fb.apply_observation_memory(observation, knowledge_patch)
    effective_patch = knowledge_patch or observation.capture.parsed
    advisor_input = fb.build_advisor_input_from_patch(
        config, effective_patch, round_no, price_config
    )
    price, details = compute_aisha_round_price(
        config,
        round_no,
        price_config,
        opp_bid,
        board_snapshot,
        advisor_input,
    )
    if details.get("fallback"):
        fb.log(f"price fallback: {price}; reason={details.get('reason')}")
    else:
        fb.log(_format_aisha_computed_price_log(price, details, config))
    fb.log(
        "opponent_bid: "
        + json.dumps({"opponent_bid": details.get("opponent_bid")}, ensure_ascii=False)
    )
    fb.save_round_debug_bundle(
        config,
        config_path,
        round_no=round_no,
        raw_text="",
        knowledge_patch=effective_patch,
        advisor_input=advisor_input,
        details=details,
        final_price=price,
    )
    if details.get("skip_submit"):
        fb.log(f"bid skipped: {details.get('reason')}")
        return knowledge_patch
    bid_outcome = fb.input_bid(config, price, config_path=config_path)
    if bid_outcome == "verify_timeout":
        fb.exit_round_after_bid_confirm_verify_timeout(config)
        return knowledge_patch
    fb.persist_last_submitted_price(config_path, price, config)
    return knowledge_patch


def run_aisha_loop(config_path: Path) -> None:
    fb.set_app_log_file(Path.cwd() / "fresh_aisha_bot.log")
    config = fb.load_json(config_path)
    fb.set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
    clear_board_snapshot_file(config)
    config.setdefault("automation", {})
    config["automation"]["selected_mode"] = "aisha_premium"
    fb.persist_last_submitted_price(config_path, None, config)

    fb.apply_pyautogui_from_config(config)
    lv0 = fb.refresh_poll_loop_locals(config)
    selected_map = lv0["selected_map"]
    max_runs = lv0["max_runs"]
    fb.prepare_target_window(config, center=True)

    fb.log(
        "fresh_aisha_bot started (snapshot round / opponent; no central or min-price OCR)；按 F9 停止"
    )
    handled_rounds: set[int] = set()
    cached_game_uid: str | None = None
    knowledge_patch: dict[str, Any] | None = None
    scan_session: dict[str, Any] = {
        "min_price_cached_points": None,
        "min_price_central_trigger_count_prev": 0,
        "opp_lobby_key": None,
        "opp_self_slot": None,
    }
    if _board_snapshot_file_missing(config):
        fb.log(
            "启动时未发现 board_snapshot 文件：按新一局处理；请先在游戏内开局，"
            "画板监听日志写入快照后即可出价。"
        )
        handled_rounds.clear()
        cached_game_uid = None
        knowledge_patch = None
        fb.reset_capture_scan_session(scan_session)
        fb.persist_last_submitted_price(config_path, None, config)

    completed_runs = 0
    startup_warehouse_sort_done = False
    warehouse_sort_milestones_done: set[int] = set()
    last_end_at = 0.0
    last_lobby_at = 0.0
    last_home_bid_at = 0.0
    last_reward_continue_at = 0.0
    last_failed_auction_at = 0.0
    last_unknown_escape_at = 0.0
    last_post_continue_confirm_at = 0.0
    poll_seconds = lv0["poll_seconds"]
    transition_debounce = lv0["transition_debounce"]
    reward_continue_debounce = lv0["reward_continue_debounce"]
    unknown_escape_cooldown = lv0["unknown_escape_cooldown"]
    post_confirm_escape_block_seconds = lv0["post_confirm_escape_block_seconds"]
    stuck_handled_enabled = lv0["stuck_handled_enabled"]
    stuck_handled_threshold = lv0["stuck_handled_threshold"]
    stuck_already_handled_polls = 0
    loop_index = 0
    last_loot_poll_overlay_dismiss_at = 0.0
    # 下一局进地图页前先 ESC 回主页；选图后若在超时内未检测到开局则 ESC 再重试。
    preflight_esc_before_next_map_select = True
    await_non_lobby_after_preflight_esc = False
    pending_game_start_deadline: float | None = None
    game_start_timeout_seconds = lv0["game_start_timeout_seconds"]

    while True:
        loop_index += 1
        try:
            fb.ensure_not_stopped()
            config = fb.load_json(config_path)
            fb.set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
            config.setdefault("automation", {})
            config["automation"]["selected_mode"] = "aisha_premium"
            fb.apply_pyautogui_from_config(config)
            lv = fb.refresh_poll_loop_locals(config)
            poll_seconds = lv["poll_seconds"]
            transition_debounce = lv["transition_debounce"]
            reward_continue_debounce = lv["reward_continue_debounce"]
            unknown_escape_cooldown = lv["unknown_escape_cooldown"]
            post_confirm_escape_block_seconds = lv["post_confirm_escape_block_seconds"]
            stuck_handled_enabled = lv["stuck_handled_enabled"]
            stuck_handled_threshold = lv["stuck_handled_threshold"]
            selected_map = lv["selected_map"]
            max_runs = lv["max_runs"]
            game_start_timeout_seconds = lv["game_start_timeout_seconds"]
            price_config = fb.load_price_config(config, config_path)
            observation = fb.observe_state_poll(config, config_path, "poll")
            knowledge_patch = fb.apply_observation_memory(observation, knowledge_patch)

            if await_non_lobby_after_preflight_esc and not observation.auction_lobby:
                await_non_lobby_after_preflight_esc = False

            bs_data = load_board_snapshot_for_aisha_bot(config)
            snap_round = current_round_from_snapshot(bs_data) if bs_data else None
            round_no = snap_round if snap_round is not None else observation.round_no

            if pending_game_start_deadline is not None:
                if _aisha_game_started(bs_data, observation):
                    pending_game_start_deadline = None
                elif time.monotonic() >= pending_game_start_deadline:
                    fb.log(
                        f"loop {loop_index}: 选图后 {game_start_timeout_seconds:.0f}s 内未检测到开局，"
                        "ESC 回主页后重试"
                    )
                    fb.press_escape(config)
                    # 本次 ESC 已回主页；勿再重复「开局前 ESC」，但仍需离开大厅 OCR 后再选图。
                    preflight_esc_before_next_map_select = False
                    await_non_lobby_after_preflight_esc = True
                    pending_game_start_deadline = None
                    last_lobby_at = 0.0
                    fb.sleep_interruptible(poll_seconds)
                    continue

            game_uid = _game_uid_from_snapshot(bs_data)
            if (
                game_uid is not None
                and cached_game_uid is not None
                and game_uid != cached_game_uid
            ):
                fb.log(
                    f"loop {loop_index}: 新局 game_uid {cached_game_uid!r} -> {game_uid!r}；重置回合状态"
                )
                handled_rounds.clear()
                knowledge_patch = fb.apply_observation_memory(observation, None)
                fb.reset_capture_scan_session(scan_session)
                fb.persist_last_submitted_price(config_path, None, config)
            if game_uid is not None:
                cached_game_uid = game_uid

            fb.log(
                f"loop {loop_index}: snap_round={snap_round} poll_round={observation.round_no} "
                f"effective_round={round_no} end={observation.end_prompt} lobby={observation.auction_lobby} "
                f"reward_continue={observation.reward_continue} "
                f"failed_auction={observation.failed_auction_settlement} "
                f"home_bid={observation.home_bid_button} any={observation.has_any_signal}",
                gui_verbose_only=True,
            )

            loot_poll = config.get("safety", {}).get("loot_overlay_dismiss", {}) or {}
            loot_round = snap_round if snap_round is not None else observation.round_no
            if (
                bool(loot_poll.get("enabled", False))
                and bool(loot_poll.get("poll_dismiss_enabled", True))
                and fb.loot_overlay_in_bidding_poll_snapshot(observation, loot_round)
            ):
                poll_min = max(
                    0.0, float(loot_poll.get("poll_dismiss_min_seconds", 2.5))
                )
                if time.monotonic() - last_loot_poll_overlay_dismiss_at >= poll_min:
                    fb.click_loot_overlay_dismiss_if_enabled(config)
                    last_loot_poll_overlay_dismiss_at = time.monotonic()

            if not observation.has_any_signal:
                since_post_confirm = time.monotonic() - last_post_continue_confirm_at
                if since_post_confirm < post_confirm_escape_block_seconds:
                    fb.log(
                        f"loop {loop_index}: no signal, esc blocked after post_continue_confirm "
                        f"({since_post_confirm:.1f}/{post_confirm_escape_block_seconds:.1f}s)",
                        gui_verbose_only=True,
                    )
                elif (
                    time.monotonic() - last_unknown_escape_at >= unknown_escape_cooldown
                ):
                    fb.press_escape(config)
                    last_unknown_escape_at = time.monotonic()
                else:
                    fb.log(f"loop {loop_index}: no signal, esc on cooldown", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            if observation.end_prompt:
                pending_game_start_deadline = None
                last_end_at, confirm_at = fb.handle_end_transition(
                    config,
                    handled_rounds,
                    last_end_at,
                    transition_debounce,
                    f"loop {loop_index}",
                )
                if confirm_at:
                    last_post_continue_confirm_at = confirm_at
                completed_runs += 1
                preflight_esc_before_next_map_select = True
                knowledge_patch = None
                fb.reset_capture_scan_session(scan_session)
                fb.persist_last_submitted_price(config_path, None, config)
                fb.log(f"completed runs: {completed_runs}/{max_runs}")
                if completed_runs >= max_runs:
                    fb.log("target runs reached; exit")
                    return
                fb.sleep_interruptible(poll_seconds)
                continue

            if observation.reward_continue:
                pending_game_start_deadline = None
                if (
                    time.monotonic() - last_reward_continue_at
                    >= reward_continue_debounce
                ):
                    fb.run_reward_continue_transition(config)
                    knowledge_patch = None
                    fb.reset_capture_scan_session(scan_session)
                    last_reward_continue_at = time.monotonic()
                else:
                    fb.log(f"loop {loop_index}: reward continue ignored by debounce", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            if observation.failed_auction_settlement:
                pending_game_start_deadline = None
                if time.monotonic() - last_failed_auction_at >= transition_debounce:
                    fb.run_failed_auction_settlement_transition(config)
                    preflight_esc_before_next_map_select = True
                    knowledge_patch = None
                    fb.reset_capture_scan_session(scan_session)
                    handled_rounds.clear()
                    fb.persist_last_submitted_price(config_path, None, config)
                    last_failed_auction_at = time.monotonic()
                else:
                    fb.log(
                        f"loop {loop_index}: failed auction settlement ignored by debounce",
                        gui_verbose_only=True,
                    )
                fb.sleep_interruptible(poll_seconds)
                continue

            if observation.auction_lobby:
                if time.monotonic() - last_lobby_at >= transition_debounce:
                    if preflight_esc_before_next_map_select:
                        fb.log(
                            f"loop {loop_index}: auction lobby: 开局前先 ESC 回主界面，"
                            "再由主页进入选图",
                            gui_verbose_only=True,
                        )
                        fb.press_escape(config)
                        preflight_esc_before_next_map_select = False
                        await_non_lobby_after_preflight_esc = True
                        last_lobby_at = time.monotonic()
                    elif await_non_lobby_after_preflight_esc:
                        fb.log(
                            f"loop {loop_index}: auction lobby: 已 ESC，等待退出大厅界面后再从主页进入选图",
                            gui_verbose_only=True,
                        )
                        fb.sleep_interruptible(poll_seconds)
                        continue
                    else:
                        confirm_at = fb.run_map_selection_transition(
                            config, selected_map
                        )
                        if confirm_at:
                            last_post_continue_confirm_at = confirm_at
                            pending_game_start_deadline = (
                                time.monotonic() + game_start_timeout_seconds
                            )
                        handled_rounds.clear()
                        knowledge_patch = None
                        fb.reset_capture_scan_session(scan_session)
                        fb.persist_last_submitted_price(config_path, None, config)
                        last_lobby_at = time.monotonic()
                else:
                    fb.log(f"loop {loop_index}: auction lobby ignored by debounce", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            if observation.home_bid_button:
                if time.monotonic() - last_home_bid_at >= transition_debounce:
                    wc = _merge_aisha_warehouse_auto_sort_settings(config)
                    if bool(wc.get("enabled", True)):
                        need_wh_sort = False
                        reason = ""
                        if not startup_warehouse_sort_done:
                            need_wh_sort = True
                            reason = "开局首次回到主页"
                        elif (
                            completed_runs > 0
                            and completed_runs % 5 == 0
                            and completed_runs not in warehouse_sort_milestones_done
                        ):
                            need_wh_sort = True
                            reason = f"已完成 {completed_runs} 局（每 5 局整理）"
                        if need_wh_sort:
                            fb.log(f"aisha warehouse: 触发整理 ({reason})", gui_verbose_only=True)
                            run_aisha_warehouse_auto_sort(config)
                            startup_warehouse_sort_done = True
                            if completed_runs > 0 and completed_runs % 5 == 0:
                                warehouse_sort_milestones_done.add(int(completed_runs))
                    fb.run_home_bid_button_transition(config)
                    knowledge_patch = None
                    fb.reset_capture_scan_session(scan_session)
                    fb.persist_last_submitted_price(config_path, None, config)
                    last_home_bid_at = time.monotonic()
                else:
                    fb.log(f"loop {loop_index}: home bid button ignored by debounce", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            if round_no is None:
                if not bs_data:
                    fb.log(
                        f"loop {loop_index}: 尚无有效 board_snapshot 且无 OCR 回合；"
                        "可先开局，等待画板生成快照",
                        gui_verbose_only=True,
                    )
                else:
                    fb.log(f"loop {loop_index}: 无快照回合且 OCR 未识别回合；等待", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            if round_no == 1 and any(value > 1 for value in handled_rounds):
                fb.log("new auction inferred from round 1; reset handled rounds")
                handled_rounds.clear()
                knowledge_patch = fb.apply_observation_memory(observation, None)
                fb.reset_capture_scan_session(scan_session)
                fb.persist_last_submitted_price(config_path, None, config)

            if round_no not in handled_rounds:
                stuck_already_handled_polls = 0

            if round_no in handled_rounds:
                stuck_already_handled_polls += 1
                if (
                    stuck_handled_enabled
                    and stuck_already_handled_polls >= stuck_handled_threshold
                ):
                    fb.log(
                        f"stuck after handled round: {stuck_already_handled_polls} consecutive polls "
                        f"(threshold={stuck_handled_threshold}); running screen recovery"
                    )
                    fb.run_stuck_after_handled_recovery(config)
                    stuck_already_handled_polls = 0
                    handled_rounds.clear()
                    knowledge_patch = None
                    fb.reset_capture_scan_session(scan_session)
                    fb.persist_last_submitted_price(config_path, None, config)
                    fb.sleep_interruptible(poll_seconds)
                    continue
                fb.log(f"loop {loop_index}: round {round_no} already handled; waiting", gui_verbose_only=True)
                fb.sleep_interruptible(poll_seconds)
                continue

            fb.log(f"loop {loop_index}: round {round_no} (snapshot-driven) -> handle", gui_verbose_only=True)
            knowledge_patch = handle_aisha_round(
                config,
                config_path,
                price_config,
                round_no,
                knowledge_patch,
                scan_session,
            )
            handled_rounds.add(round_no)

            if round_no >= 5:
                fb.log("round 5 handled; waiting for end prompt or next state", gui_verbose_only=True)

            fb.sleep_interruptible(poll_seconds)
        except KeyboardInterrupt:
            fb.log("stopped by Ctrl+C")
            return
        except fb.StopRequested:
            fb.log("stopped by GUI")
            return
        except fb.EndPromptDetected as exc:
            pending_game_start_deadline = None
            last_end_at, confirm_at = fb.handle_end_transition(
                config,
                handled_rounds,
                last_end_at,
                transition_debounce,
                f"active handling ({exc.source})",
            )
            if confirm_at:
                last_post_continue_confirm_at = confirm_at
            completed_runs += 1
            preflight_esc_before_next_map_select = True
            knowledge_patch = None
            fb.reset_capture_scan_session(scan_session)
            fb.persist_last_submitted_price(config_path, None, config)
            fb.log(f"completed runs: {completed_runs}/{max_runs}")
            if completed_runs >= max_runs:
                fb.log("target runs reached; exit")
                return
            fb.sleep_interruptible(poll_seconds)
        except Exception as exc:
            fb.log(f"error: {type(exc).__name__}: {exc}")
            fb.sleep_interruptible(max(1.0, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BidKing 艾莎快照专用 bot（fresh_aisha_bot）。"
    )
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = fb.load_json(config_path)
    maps = config.get("automation", {}).get("maps", {})
    default_map = str(config.get("automation", {}).get("default_map", "4"))
    default_runs = int(config.get("automation", {}).get("default_runs", 1))
    print("fresh_aisha_bot — 请选择地图：")
    for key in ("1", "2", "3", "4", "5", "6", "7"):
        item = maps.get(key, {})
        print(f"{key}. {item.get('name', key)}")
    map_input = input(f"地图编号 [默认 {default_map}]: ").strip() or default_map
    runs_input = input(f"刷取次数 [默认 {default_runs}]: ").strip() or str(default_runs)
    selected_runs = (
        int(runs_input)
        if runs_input.isdigit() and int(runs_input) > 0
        else default_runs
    )
    config.setdefault("automation", {})
    config["automation"]["selected_map"] = map_input
    config["automation"]["selected_runs"] = selected_runs
    config["automation"]["selected_mode"] = "aisha_premium"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fb.reset_stop()
    run_aisha_loop(config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
