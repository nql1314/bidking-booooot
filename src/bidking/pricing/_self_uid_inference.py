# -*- coding: utf-8 -*-
"""跨对局推断己方玩家 ``UserUid``（仅 UID，不用显示名）。

规则（进程内模块级状态）：

- 若快照根级或配置里的 ``self_user_uid`` **出现在本局** ``players`` 键中：视为可信，
  **不进行**候选交集/唯一解推断，直接采用该 UID；并将进程内候选收窄为 ``{该 UID}``。
- 否则：维护候选集合 ``_self_uid_candidates``，在新对局（``game_state.uid`` 与上一局不同）
  时与当前局玩家求交；交为空则重置为当前局全部玩家 UID；唯一候选时写入
  ``inferred_self_user_uid``，并可写回 ``configs/config.json`` 的 ``board_snapshot.self_user_uid``
  （见 :func:`_maybe_persist_inferred_self_user_uid`；单测可设环境变量
  ``BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST=1`` 关闭写盘）。
- 本局仅一名玩家时，该 UID 即己方。

显式 ``self_user_uid``（快照根或配置）在局内有效时优先于 ``inferred_self_user_uid``。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_lock = threading.Lock()
_last_game_uid: str | None = None
_self_uid_candidates: set[str] = set()
_persist_file_lock = threading.Lock()
_last_persisted_uid: str | None = None


def reset_self_uid_inference_state() -> None:
    """供测试重置进程内缓存。"""
    global _last_game_uid, _self_uid_candidates, _last_persisted_uid
    with _lock:
        _last_game_uid = None
        _self_uid_candidates = set()
    with _persist_file_lock:
        _last_persisted_uid = None


def _game_state_slice(board_snapshot: dict[str, Any]) -> dict[str, Any]:
    gs = board_snapshot.get("game_state")
    if isinstance(gs, dict) and isinstance(gs.get("players"), dict):
        return gs
    if isinstance(board_snapshot.get("players"), dict):
        return board_snapshot
    return {}


def _current_player_uids(game_state: dict[str, Any]) -> set[str]:
    players = game_state.get("players") or {}
    if not isinstance(players, dict) or not players:
        return set()
    out: set[str] = set()
    for k in players.keys():
        s = str(k).strip()
        if s:
            out.add(s)
    return out


def current_round_player_uids(board_snapshot: dict[str, Any]) -> set[str]:
    """本局 ``players`` 的 UID 集合（规范化字符串）。"""
    return _current_player_uids(_game_state_slice(board_snapshot))


def resolve_effective_self_user_uid(
    board_snapshot: dict[str, Any], *, config_self_user_uid: str = ""
) -> str:
    """在已调用 :func:`apply_self_uid_inference_to_board_snapshot` 之后，解析有效己方 UID。

    顺序：快照根 ``self_user_uid``（须在本局玩家内）→ 配置 ``self_user_uid``（须在本局玩家内）
    → ``inferred_self_user_uid``。
    """
    uids = current_round_player_uids(board_snapshot)
    for cand in (
        str(board_snapshot.get("self_user_uid") or "").strip(),
        str(config_self_user_uid or "").strip(),
    ):
        if cand and cand in uids:
            return cand
    return str(board_snapshot.get("inferred_self_user_uid") or "").strip()


def _game_transition_update_candidates_in_lock(
    eff_game_uid: str,
    current_uids: set[str],
) -> None:
    global _last_game_uid, _self_uid_candidates
    if not eff_game_uid:
        return
    if _last_game_uid is not None and eff_game_uid != _last_game_uid:
        _self_uid_candidates &= current_uids
        if not _self_uid_candidates:
            _self_uid_candidates = set(current_uids)
    elif _last_game_uid is None and not _self_uid_candidates:
        _self_uid_candidates = set(current_uids)
    _last_game_uid = eff_game_uid


def _persist_disabled() -> bool:
    v = os.environ.get("BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST", "")
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _maybe_persist_inferred_self_user_uid(inferred_uid: str) -> bool:
    """将唯一推断 UID 写入 ``configs/config.json`` 的 ``board_snapshot.self_user_uid``。"""
    global _last_persisted_uid
    if not inferred_uid or "BIDKING_SELF_USER_UID" in os.environ or _persist_disabled():
        return False
    from ..config.paths import config_overlay_path

    path = config_overlay_path()
    with _persist_file_lock:
        if _last_persisted_uid == inferred_uid:
            return False
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
            else:
                raw = {}
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        bs = raw.get("board_snapshot")
        if not isinstance(bs, dict):
            bs = {}
            raw["board_snapshot"] = bs
        cur = str(bs.get("self_user_uid") or "").strip()
        if cur == inferred_uid:
            _last_persisted_uid = inferred_uid
            return False
        bs["self_user_uid"] = inferred_uid
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return False
        _last_persisted_uid = inferred_uid
        return True


def apply_self_uid_inference_to_board_snapshot(
    board_snapshot: dict[str, Any],
    *,
    config_self_user_uid: str = "",
) -> dict[str, Any]:
    """就地更新 ``inferred_self_*`` / 必要时写回配置；返回供写入 ``pricing`` 的摘要 dict。"""
    global _last_game_uid, _self_uid_candidates
    empty_detail: dict[str, Any] = {"skipped": True}
    if not isinstance(board_snapshot, dict):
        return empty_detail

    gs = _game_state_slice(board_snapshot)
    current_uids = _current_player_uids(gs)
    if not current_uids:
        board_snapshot.pop("inferred_self_user_uid", None)
        board_snapshot.pop("inferred_self_name", None)
        return {**empty_detail, "reason": "no_players"}

    game_uid = str(gs.get("uid") or "").strip()
    root_game_uid = str(board_snapshot.get("game_uid") or "").strip()
    eff_game_uid = game_uid or root_game_uid

    players = gs.get("players") if isinstance(gs.get("players"), dict) else {}

    u_explicit = ""
    for cand in (
        str(board_snapshot.get("self_user_uid") or "").strip(),
        str(config_self_user_uid or "").strip(),
    ):
        if cand and cand in current_uids:
            u_explicit = cand
            break
    if u_explicit:
        with _lock:
            _game_transition_update_candidates_in_lock(eff_game_uid, current_uids)
            _self_uid_candidates = {u_explicit}
            cand_after = sorted(_self_uid_candidates)
        board_snapshot.pop("inferred_self_user_uid", None)
        board_snapshot.pop("inferred_self_name", None)
        return {
            "skipped": False,
            "identity_mode": "configured_in_players",
            "game_uid": eff_game_uid,
            "current_player_uids": sorted(current_uids),
            "resolved_self_user_uid": u_explicit,
            "candidates_after": cand_after,
        }

    inferred_uid: str | None = None
    inference_mode: str | None = None
    cand_before: set[str]
    cand_after: set[str]

    with _lock:
        cand_before = set(_self_uid_candidates)
        _game_transition_update_candidates_in_lock(eff_game_uid, current_uids)
        cand_after = set(_self_uid_candidates)

        if len(current_uids) == 1:
            inferred_uid = next(iter(current_uids))
            inference_mode = "single_player_in_round"
        elif len(_self_uid_candidates) == 1:
            only = next(iter(_self_uid_candidates))
            if only in current_uids:
                inferred_uid = only
                inference_mode = "unique_candidate_across_games"

    detail: dict[str, Any] = {
        "skipped": False,
        "identity_mode": inference_mode or "ambiguous",
        "game_uid": eff_game_uid,
        "current_player_uids": sorted(current_uids),
        "candidates_before": sorted(cand_before),
        "candidates_after": sorted(cand_after),
    }

    persisted = False
    if inferred_uid:
        pdata = players.get(inferred_uid) if isinstance(players, dict) else None
        name = ""
        if isinstance(pdata, dict):
            name = str(pdata.get("name") or "").strip()
        board_snapshot["inferred_self_user_uid"] = inferred_uid
        if name:
            board_snapshot["inferred_self_name"] = name
        else:
            board_snapshot.pop("inferred_self_name", None)
        detail["inferred_self_user_uid"] = inferred_uid
        if name:
            detail["inferred_self_name"] = name
        persisted = _maybe_persist_inferred_self_user_uid(inferred_uid)
        detail["config_self_user_uid_persisted"] = bool(persisted)
        if persisted:
            board_snapshot["self_user_uid"] = inferred_uid
            board_snapshot.pop("inferred_self_user_uid", None)
            board_snapshot.pop("inferred_self_name", None)
    else:
        board_snapshot.pop("inferred_self_user_uid", None)
        board_snapshot.pop("inferred_self_name", None)
        detail["config_self_user_uid_persisted"] = False

    return detail


def persist_self_user_uid_to_config(inferred_uid: str) -> bool:
    """将己方 UID 写入 ``configs/config.json`` 的 ``board_snapshot.self_user_uid``（有变化时）。"""
    return _maybe_persist_inferred_self_user_uid(inferred_uid)
