from __future__ import annotations

from typing import Any

from ._self_uid_inference import (
    apply_self_uid_inference_to_board_snapshot,
    resolve_effective_self_user_uid,
)


def _self_identity_from_board_snapshot(board_snapshot: dict[str, Any] | None) -> tuple[str, str]:
    """快照根级 ``self_user_uid``（``self_name_substring`` 已废弃，恒为空）。"""
    if not board_snapshot:
        return "", ""
    return (
        str(board_snapshot.get("self_user_uid") or "").strip(),
        "",
    )


def effective_self_user_uid_on_snapshot(
    board_snapshot: dict[str, Any] | None, *, fallback_uid: str = ""
) -> str:
    """显式 UID（快照根或 ``fallback_uid``，须在本局 ``players`` 内）→ 推断 ``inferred_self_user_uid``。"""
    if not board_snapshot or not isinstance(board_snapshot, dict):
        return (fallback_uid or "").strip()
    fb = (fallback_uid or "").strip()
    apply_self_uid_inference_to_board_snapshot(
        board_snapshot, config_self_user_uid=fb
    )
    return resolve_effective_self_user_uid(
        board_snapshot, config_self_user_uid=fb
    )


def board_snapshot_self_identity(
    config: dict[str, Any], board_snapshot: dict[str, Any] | None = None
) -> tuple[str, str]:
    """解析己方玩家 UID：见 :func:`resolve_effective_self_user_uid` 的优先级说明。

    返回 ``(self_user_uid, "")``；第二项保留为兼容旧调用方，恒为空字符串。
    """
    bs_cfg = config.get("board_snapshot") or {}
    cfg_uid = str(bs_cfg.get("self_user_uid") or "").strip()
    if board_snapshot and isinstance(board_snapshot, dict):
        apply_self_uid_inference_to_board_snapshot(
            board_snapshot, config_self_user_uid=cfg_uid
        )
        return (
            resolve_effective_self_user_uid(
                board_snapshot, config_self_user_uid=cfg_uid
            ),
            "",
        )
    return cfg_uid, ""


def player_round_price_bid(pdata: dict[str, Any], round_no: int) -> int | None:
    """``prices`` 键为 ``str(round_no - 1)``（与快照 ``players.*.prices`` 一致）。"""
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


def max_other_player_bid_from_snapshot_players(
    players: dict[str, Any],
    bid_round: int,
    *,
    self_user_uid: str,
    self_name_substring: str = "",
    board_snapshot: dict[str, Any] | None = None,
) -> int | None:
    del self_name_substring  # 已废弃，仅保留参数以兼容旧调用
    self_uid = effective_self_user_uid_on_snapshot(
        board_snapshot, fallback_uid=self_user_uid
    )
    key_int = int(bid_round - 1)
    key_str = str(key_int)
    best: int | None = None
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
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


def self_round_bid_from_snapshot(
    config: dict[str, Any], board_snapshot: dict[str, Any], round_no: int
) -> int | None:
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    if not self_uid:
        return None
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return None
    pdata = players.get(self_uid)
    if not isinstance(pdata, dict):
        return None
    return player_round_price_bid(pdata, round_no)


def iter_opponent_round_bids_from_snapshot(
    config: dict[str, Any], board_snapshot: dict[str, Any], round_no: int
) -> list[int]:
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return []
    out: list[int] = []
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        if self_uid and str(p_uid) == self_uid:
            continue
        b = player_round_price_bid(pdata, round_no)
        if b is not None:
            out.append(b)
    return out
