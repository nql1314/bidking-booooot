from __future__ import annotations

from typing import Any


def _self_identity_from_board_snapshot(board_snapshot: dict[str, Any] | None) -> tuple[str, str]:
    """快照根级 ``self_user_uid`` / ``self_name_substring``。"""
    if not board_snapshot:
        return "", ""
    return (
        str(board_snapshot.get("self_user_uid") or "").strip(),
        str(board_snapshot.get("self_name_substring") or "").strip(),
    )


def board_snapshot_self_identity(
    config: dict[str, Any], board_snapshot: dict[str, Any] | None = None
) -> tuple[str, str]:
    if board_snapshot:
        u, h = _self_identity_from_board_snapshot(board_snapshot)
        if u or h:
            return u, h
    bs = config.get("board_snapshot") or {}
    return str(bs.get("self_user_uid") or "").strip(), str(bs.get("self_name_substring") or "").strip()


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
    u, h = _self_identity_from_board_snapshot(board_snapshot)
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
    self_uid, name_hint = board_snapshot_self_identity(config, board_snapshot)
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
        b = player_round_price_bid(pdata, round_no)
        if b is not None:
            out.append(b)
    return out
