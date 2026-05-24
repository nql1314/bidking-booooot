"""隐秘拍卖图（440/450）：缓存己方各回合实际金币出价。

``game_state.players.*.prices`` 在该类地图仅为名次信号，不能作为 ``bid_pre``。
Bot 出价确认后写入；Grid 写快照时合并进 ``board_snapshot.self_bid_history``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..analysis._board_pricing import map_id_from_board_snapshot
from ..config.paths import data_dir
from ..parsing.item_db import map_bundle_key_for_automation
from .snapshot_players import board_snapshot_self_identity, self_round_bid_from_snapshot


def _game_uid_from_snapshot(board_snapshot: dict[str, Any]) -> str | None:
    u = str(board_snapshot.get("game_uid") or "").strip()
    if u:
        return u
    u = str((board_snapshot.get("game_state") or {}).get("uid") or "").strip()
    return u or None

_SECRET_MAP_KEYS = frozenset({"440", "450"})


def _board_snapshot_is_secret_auction(board_snapshot: dict[str, Any]) -> bool:
    mid = map_id_from_board_snapshot(board_snapshot)
    if mid is None or int(mid) <= 0:
        return False
    key = map_bundle_key_for_automation(int(mid))
    return bool(key) and key in _SECRET_MAP_KEYS

SELF_BID_HISTORY_SNAPSHOT_KEY = "self_bid_history"
_CACHE_FILENAME = "self_bid_cache.json"


def _cache_file_path() -> Path:
    return (data_dir() / _CACHE_FILENAME).resolve()


def _load_disk_cache() -> dict[str, Any]:
    path = _cache_file_path()
    if not path.is_file():
        return {"games": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"games": {}}
    if not isinstance(data, dict):
        return {"games": {}}
    games = data.get("games")
    if not isinstance(games, dict):
        data["games"] = {}
    return data


def _save_disk_cache(data: dict[str, Any]) -> None:
    path = _cache_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clear_self_bid_disk_cache(*, reason: str = "") -> None:
    """新对局开始时清空整盘 ``games``（对局结束、结算流程不调用）。"""
    _ = reason  # 供调用方在日志中说明触发源
    _save_disk_cache({"games": {}})


def _history_on_snapshot(board_snapshot: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(board_snapshot, dict):
        return {}
    raw = board_snapshot.get(SELF_BID_HISTORY_SNAPSHOT_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv > 0:
            out[str(k)] = iv
    return out


def _disk_history_for_game(game_uid: str) -> dict[str, int]:
    data = _load_disk_cache()
    games = data.get("games") or {}
    entry = games.get(game_uid) if isinstance(games, dict) else None
    if not isinstance(entry, dict):
        return {}
    raw = entry.get("by_round")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv > 0:
            out[str(k)] = iv
    return out


def get_self_gold_bid(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
    round_no: int,
) -> int | None:
    """隐秘图读缓存/快照 ``self_bid_history``；其它地图仍读 ``players.*.prices``。"""
    if not isinstance(board_snapshot, dict):
        return None
    if not _board_snapshot_is_secret_auction(board_snapshot):
        return self_round_bid_from_snapshot(config, board_snapshot, round_no)

    key = str(int(round_no))
    hist = _history_on_snapshot(board_snapshot)
    if key in hist:
        return hist[key]

    game_uid = _game_uid_from_snapshot(board_snapshot)
    if game_uid:
        disk = _disk_history_for_game(game_uid)
        if key in disk:
            return disk[key]
    return None


def resolve_self_bid_cache_amount(
    final_price: int,
    pricing_details: dict[str, Any] | None = None,
) -> int:
    """
    写入 ``self_bid_history`` 的金币数额。

    部分后处理仅改变实际输入价（如超回合低价放弃出 886），
    ``pricing_details["self_bid_cache_amount"]`` 保留策略原始出价。
    """
    if isinstance(pricing_details, dict):
        raw = pricing_details.get("self_bid_cache_amount")
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        lrs = pricing_details.get("late_round_low_bid_surrender")
        if isinstance(lrs, dict) and lrs.get("applied"):
            try:
                return int(lrs["before"])
            except (KeyError, TypeError, ValueError):
                pass
    return int(final_price)


def record_self_gold_bid(
    config: dict[str, Any],
    *,
    round_no: int,
    bid_amount: int,
    board_snapshot: dict[str, Any] | None = None,
    game_uid: str | None = None,
) -> None:
    """Bot/手动确认出价后调用，持久化到磁盘并在内存快照上打补丁。"""
    try:
        amount = int(bid_amount)
    except (TypeError, ValueError):
        return
    if amount <= 0:
        return

    r_key = str(int(round_no))
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)

    if game_uid is None and isinstance(board_snapshot, dict):
        game_uid = _game_uid_from_snapshot(board_snapshot)
    if not game_uid:
        return

    data = _load_disk_cache()
    games = data.setdefault("games", {})
    if not isinstance(games, dict):
        games = {}
        data["games"] = games
    entry = games.get(game_uid)
    if not isinstance(entry, dict):
        entry = {}
        games[game_uid] = entry
    if self_uid:
        entry["self_uid"] = str(self_uid)
    by_round = entry.get("by_round")
    if not isinstance(by_round, dict):
        by_round = {}
        entry["by_round"] = by_round
    by_round[r_key] = amount
    _save_disk_cache(data)

    if isinstance(board_snapshot, dict):
        hist = board_snapshot.get(SELF_BID_HISTORY_SNAPSHOT_KEY)
        if not isinstance(hist, dict):
            hist = {}
            board_snapshot[SELF_BID_HISTORY_SNAPSHOT_KEY] = hist
        hist[r_key] = amount


def merge_self_bid_history_for_snapshot(
    payload: dict[str, Any],
    *,
    game_uid: str | None,
) -> None:
    """Grid 写 ``board_snapshot.json`` 前：把磁盘缓存合并进 outgoing payload。"""
    uid = str(game_uid or "").strip()
    if not uid:
        return
    disk = _disk_history_for_game(uid)
    if not disk:
        return
    existing = payload.get(SELF_BID_HISTORY_SNAPSHOT_KEY)
    merged: dict[str, int] = {}
    if isinstance(existing, dict):
        merged.update(_history_on_snapshot({"self_bid_history": existing}))
    merged.update(disk)
    payload[SELF_BID_HISTORY_SNAPSHOT_KEY] = {str(k): int(v) for k, v in merged.items()}
