#!/usr/bin/env python3
"""艾莎（aisha）策略：基于画板 JSON 快照的估价与对手价读取，与 ahmad_premium 互不耦合。"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

_WIN_FILENAME_FORBIDDEN = set('<>:"/\\|?*')

# 可开局感知红格信息的英雄（画板 hero_cid）
_HERO_CID_RED_SCOUT = 110

# ``automation.maps`` 的键：低级图不使用「空置金红对手价推断 / floor–ceiling 择优」
_AISHA_VACANT_RED_INFERENCE_EXCLUDE_MAP_CONFIG_KEYS = frozenset({"1", "2"})


def _aisha_automation_selected_map_config_key(config: dict[str, Any]) -> str:
    """与大厅选图一致：``automation.selected_map``，缺省 ``default_map``。"""
    auto = config.get("automation") or {}
    return str(auto.get("selected_map") or auto.get("default_map") or "").strip()


def is_aisha_premium_mode(config: dict[str, Any]) -> bool:
    mode = str(config.get("automation", {}).get("selected_mode", "")).strip().lower()
    return mode == "aisha_premium"


def _read_board_snapshot_if_enabled(config: dict[str, Any]) -> dict[str, Any] | None:
    """``board_snapshot.enabled`` 且文件有效时返回解析后的 dict。"""
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return None
    raw_path = str(bs.get("path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    min_sv = int(bs.get("schema_version_min", 1))
    if int(data.get("schema_version", 0)) < min_sv:
        return None
    return data


def _snapshot_player_names_for_archive(board_snapshot: dict[str, Any]) -> list[str]:
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return []
    names: list[str] = []
    for pdata in players.values():
        if isinstance(pdata, dict):
            n = str(pdata.get("name") or "").strip()
            if n:
                names.append(n)
    return sorted(names)


def _safe_log_stem_from_player_names(names: list[str]) -> str:
    if not names:
        return "board_snapshot_no_players"
    parts: list[str] = []
    for n in names:
        cleaned = "".join(
            c if c not in _WIN_FILENAME_FORBIDDEN and ord(c) >= 32 else "_"
            for c in n
        )
        cleaned = cleaned.strip(" .")
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return "board_snapshot_no_players"
    stem = "_".join(parts)
    if len(stem) > 200:
        stem = stem[:200]
    return stem


def _archive_board_snapshot_to_run_dir(path: Path) -> None:
    """将即将删除的快照复制到当前工作目录 ``run/``，文件名为对局玩家 ``name`` 组合加 ``.log``。"""
    data: dict[str, Any] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    stem = _safe_log_stem_from_player_names(_snapshot_player_names_for_archive(data))
    run_dir = Path.cwd() / "run"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    dest = run_dir / f"{stem}.log"
    if dest.exists():
        dest = run_dir / f"{stem}_{int(time.time())}.log"
    try:
        shutil.copy2(path, dest)
    except OSError:
        pass


def clear_board_snapshot_file(config: dict[str, Any]) -> bool:
    """删除 ``board_snapshot.path`` 对应文件（启用且路径有效时）。用于新局开始前丢弃上一局 JSON，避免在无 ``max_age`` 校验时误读旧盘面。"""
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return False
    raw_path = str(bs.get("path") or "").strip()
    if not raw_path:
        return False
    path = Path(raw_path)
    try:
        if path.is_file():
            _archive_board_snapshot_to_run_dir(path)
            path.unlink()
            return True
    except OSError:
        pass
    return False


def load_board_snapshot_file(config: dict[str, Any]) -> dict[str, Any] | None:
    """读取画板快照；仅在 ``aisha_premium`` 模式且启用快照时生效（供通用脚本兼容）。"""
    if not is_aisha_premium_mode(config):
        return None
    return _read_board_snapshot_if_enabled(config)


def load_board_snapshot_for_aisha_bot(config: dict[str, Any]) -> dict[str, Any] | None:
    """``fresh_aisha_bot`` 专用：不检查 ``selected_mode``，只要 ``board_snapshot.enabled``。"""
    return _read_board_snapshot_if_enabled(config)


def current_round_from_snapshot(snapshot: dict[str, Any]) -> int | None:
    """根级或 ``game_state.current_round``，有效范围 ≥1。"""
    r = snapshot.get("current_round")
    if r is None:
        r = (snapshot.get("game_state") or {}).get("current_round")
    try:
        v = int(r)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def max_other_player_bid_from_snapshot_players(
    players: dict[str, Any],
    bid_round: int,
    *,
    self_user_uid: str,
    self_name_substring: str = "",
    board_snapshot: dict[str, Any] | None = None,
) -> int | None:
    """从 ``game_state.players`` 取除己方外、给定 ``PriceLog`` 回合列上的最高出价。"""
    ac = (board_snapshot or {}).get("aisha_client") or {}
    if isinstance(ac, dict):
        u = str(ac.get("self_user_uid") or "").strip()
        h = str(ac.get("self_name_substring") or "").strip()
        if u:
            self_user_uid = u
        if h:
            self_name_substring = h
    key_int = int(bid_round - 1)
    key_str = str(key_int)
    self_uid = (self_user_uid or "").strip()
    name_hint = (self_name_substring or "").strip()
    best: int | None = None
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        pname = str(pdata.get("name") or "")
        if name_hint and name_hint in pname:
            continue
        prices = pdata.get("prices") or {}
        raw = prices.get(key_str)
        if raw is None:
            raw = prices.get(key_int)
        if raw is None:
            continue
        try:
            iv = int(raw)
        except (TypeError, ValueError):
            continue
        if iv <= 0:
            continue
        if best is None or iv > best:
            best = iv
    return best


def _board_snapshot_self_identity(
    config: dict[str, Any], board_snapshot: dict[str, Any] | None = None
) -> tuple[str, str]:
    if board_snapshot:
        ac = board_snapshot.get("aisha_client") or {}
        if isinstance(ac, dict):
            u = str(ac.get("self_user_uid") or "").strip()
            h = str(ac.get("self_name_substring") or "").strip()
            if u or h:
                return u, h
    bs = config.get("board_snapshot") or {}
    return str(bs.get("self_user_uid") or "").strip(), str(bs.get("self_name_substring") or "").strip()


def _player_round_price_log_bid(pdata: dict[str, Any], round_no: int) -> int | None:
    """``prices`` 键为 ``str(round_no - 1)``，与 ``max_other_player_bid_from_snapshot_players`` 一致。"""
    prices = pdata.get("prices") or {}
    if not isinstance(prices, dict):
        return None
    key_int = int(round_no) - 1
    raw = prices.get(str(key_int))
    if raw is None:
        raw = prices.get(key_int)
    if raw is None:
        return None
    try:
        iv = int(raw)
    except (TypeError, ValueError):
        return None
    return iv if iv > 0 else None


def self_round_bid_from_snapshot(
    config: dict[str, Any], board_snapshot: dict[str, Any], round_no: int
) -> int | None:
    """己方在指定竞拍回合 ``PriceLog`` 列上的出价；需配置 ``board_snapshot.self_user_uid``。"""
    self_uid, _ = _board_snapshot_self_identity(config, board_snapshot)
    if not self_uid:
        return None
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return None
    pdata = players.get(self_uid)
    if not isinstance(pdata, dict):
        return None
    return _player_round_price_log_bid(pdata, round_no)


def iter_opponent_round_bids_from_snapshot(
    config: dict[str, Any], board_snapshot: dict[str, Any], round_no: int
) -> list[int]:
    """除己方外各对手在指定回合的有效出价（仅数值列表，用于条数统计）。"""
    self_uid, name_hint = _board_snapshot_self_identity(config, board_snapshot)
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return []
    out: list[int] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        pname = str(pdata.get("name") or "")
        if name_hint and name_hint in pname:
            continue
        b = _player_round_price_log_bid(pdata, round_no)
        if b is not None:
            out.append(b)
    return out


def _hero_110_red_scout_signal(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    computed_price_floor: float,
) -> tuple[bool, list[dict[str, Any]]]:
    """hero_cid 110：第三或第四回合出价高于估价下限 1.1 倍则视为有红信号。

    若同回合出价低于估价下限 0.7 倍则视为已放弃跟价，该回合不作为「有红」依据。
    """
    self_uid, name_hint = _board_snapshot_self_identity(config, board_snapshot)
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
            b = _player_round_price_log_bid(pdata, r)
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
    """仅用于金红空置分拆未定、第 4–5 回合：据空位数与对手历史价推断是否按「有红」出价。

    - 场上 ``items`` 已存在红品质（6）时（轮廓是否确认均计）：认为空置格再出第二个红的预期极低，**一律按空置无红**。
    - ``vac<=4``：不认为有红。
    - ``vac>12``：认为有红（但若已有红品物则见上条）。
    - ``vac`` 在 6–12：对比参考回合对手价与己方同回合价及 ``points_floor``（当前计算下限）。
    """
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
        detail["decision_rule"] = "vac_le_5_ignore_red"
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


def _coerce_aisha_bid_points(raw: Any, *, round_float: bool) -> int | None:
    try:
        return int(round(float(raw))) if round_float else int(raw)
    except (TypeError, ValueError):
        return None


def apply_aisha_vacant_red_floor_ceiling_pick(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    meta: dict[str, Any],
    round_no: int,
    fin: int,
) -> tuple[int, dict[str, Any]]:
    """第 4–5 回合且金红空置格数未定时：在对手价调整前先选 ``points_floor`` 或 ``points_ceiling``。"""
    if int(round_no) not in (4, 5):
        return int(fin), {"applied": False, "reason": "not_round_4_or_5"}
    cfg_map_key = _aisha_automation_selected_map_config_key(config)
    if cfg_map_key in _AISHA_VACANT_RED_INFERENCE_EXCLUDE_MAP_CONFIG_KEYS:
        return int(fin), {
            "applied": False,
            "reason": "vacant_red_inference_disabled_low_tier_config_map",
            "config_map_key": cfg_map_key,
        }
    if meta.get("early_round_estimated"):
        return int(fin), {"applied": False, "reason": "early_round_estimated"}
    certain = meta.get("gold_red_vacant_counts_certain")
    if certain is None:
        certain = str(meta.get("vacant_pricing_mode") or "") != "default"
    if certain:
        return int(fin), {"applied": False, "reason": "gold_red_vacant_counts_certain"}
    pf = meta.get("points_floor")
    pc = meta.get("points_ceiling")
    if pf is None or pc is None:
        return int(fin), {"applied": False, "reason": "missing_floor_ceiling"}
    pf_i, pc_i = int(pf), int(pc)
    if pf_i == pc_i:
        return int(fin), {"applied": False, "reason": "floor_equals_ceiling"}
    vac_m = meta.get("vacant_used")
    if vac_m is None:
        return int(fin), {"applied": False, "reason": "missing_vacant_used"}
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


def compute_aisha_snapshot_bid_points(
    config: dict[str, Any], board_snapshot: dict[str, Any]
) -> tuple[int | None, dict[str, Any]]:
    """从 ``pricing.points`` 读主估价（兼容旧 ``aisha_bid`` / ``aisha_bid_points`` 键）。"""
    _ = config
    pricing = board_snapshot.get("pricing")
    if not isinstance(pricing, dict) or pricing.get("total") is None:
        return None, {"reason": "missing_or_invalid_pricing_total"}

    p_top = _coerce_aisha_bid_points(pricing.get("points"), round_float=True)
    if p_top is not None:
        meta: dict[str, Any] = {
            "points": p_top,
            "points_floor": pricing.get("points_floor"),
            "points_ceiling": pricing.get("points_ceiling"),
            "bid_points_source": "getlog_snapshot_pricing_points",
        }
        if p_top == 0:
            return None, meta
        return p_top, meta

    ab = pricing.get("aisha_bid")
    if isinstance(ab, dict) and ab.get("points") is not None:
        p = _coerce_aisha_bid_points(ab["points"], round_float=False)
        if p is None:
            return None, {"reason": "aisha_bid_points_not_int"}
        meta = dict(ab)
        meta["bid_points_source"] = "getlog_snapshot_pricing_aisha_bid"
        if p == 0 and meta.get("early_round_estimated"):
            return None, meta
        return p, meta

    p = _coerce_aisha_bid_points(pricing.get("aisha_bid_points"), round_float=True)
    if p is None:
        return None, {
            "reason": "missing_pricing_points",
            "hint": "需 pricing.points（或兼容字段 aisha_bid / aisha_bid_points）",
        }
    meta = {
        "points": p,
        "bid_points_source": "getlog_snapshot_pricing_aisha_bid_points_only",
    }
    if p == 0:
        return None, meta
    return p, meta


def snapshot_bid_source_reason() -> str:
    return "getlog board_snapshot pricing（points）"


def _items_dict_from_snapshot(board_snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = (board_snapshot.get("game_state") or {}).get("items") or {}
    return raw if isinstance(raw, dict) else {}


def _count_quality_items_all(board_snapshot: dict[str, Any], quality: int) -> int:
    """场上该品质物品件数（含轮廓未确认），用于件数类地图技能对比。"""
    k = 0
    for _uid, it in _items_dict_from_snapshot(board_snapshot).items():
        if not isinstance(it, dict):
            continue
        q = it.get("quality")
        try:
            if int(q) == quality:
                k += 1
        except (TypeError, ValueError):
            continue
    return k


