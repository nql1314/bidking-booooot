"""快递站表情暗号：公共黑名单与对局黑名单（含偷快递检测）。数据文件为 CSV。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ..config.paths import data_dir
from .board_snapshot_util import game_uid_from_snapshot
from ..pricing.snapshot_players import (
    board_snapshot_self_identity,
    player_round_price_bid,
)

_PUBLIC_FILENAME = "emoji_signal_public_blacklist.csv"
_MATCH_FILENAME = "emoji_signal_match_blacklist.csv"
_STEAL_EXPRESS_ROUND1_BID_MIN = 1001  # 首回合出价 > 1000

_PUBLIC_FIELDS = ("uid", "name")
_MATCH_FIELDS = ("game_uid", "uid", "name", "round", "bid")


def _public_path() -> Path:
    return (data_dir() / _PUBLIC_FILENAME).resolve()


def _match_path() -> Path:
    return (data_dir() / _MATCH_FILENAME).resolve()


def _norm_uid(uid: str) -> str:
    return str(uid or "").strip()


def _norm_name(name: str) -> str:
    return str(name or "").strip()


def _read_csv_table(path: Path, fieldnames: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return []
            rows: list[dict[str, str]] = []
            for raw in reader:
                if not isinstance(raw, dict):
                    continue
                row = {k: str(raw.get(k) or "").strip() for k in fieldnames}
                if any(row.values()):
                    rows.append(row)
            return rows
    except Exception:
        return []


def _write_csv_table(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    tmp.replace(path)


def opponent_identity_from_snapshot(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
) -> tuple[str, str] | None:
    """本局对手 ``(uid, name)``；多人局取第一个非己方玩家。"""
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return None
    for p_uid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        uid = _norm_uid(str(p_uid))
        if self_uid and uid == _norm_uid(self_uid):
            continue
        name = _norm_name(str(pdata.get("name") or ""))
        return uid, name
    return None


def _opponent_player_data(
    config: dict[str, Any], board_snapshot: dict[str, Any]
) -> tuple[str, str, dict[str, Any]] | None:
    opp = opponent_identity_from_snapshot(config, board_snapshot)
    if opp is None:
        return None
    uid, name = opp
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    pdata = players.get(uid) if isinstance(players, dict) else None
    if not isinstance(pdata, dict):
        return None
    return uid, name, pdata


def _opponent_round_bid(
    config: dict[str, Any], board_snapshot: dict[str, Any], round_no: int
) -> int | None:
    row = _opponent_player_data(config, board_snapshot)
    if row is None:
        return None
    _, _, pdata = row
    return player_round_price_bid(pdata, int(round_no))


def _opponent_round1_bid(
    config: dict[str, Any], board_snapshot: dict[str, Any]
) -> int | None:
    return _opponent_round_bid(config, board_snapshot, 1)


def _entry_matches(entry: dict[str, Any], *, uid: str, name: str) -> bool:
    """黑名单命中须 ``uid`` 与 ``name`` 同时与条目一致（缺一不匹配）。"""
    e_uid = _norm_uid(str(entry.get("uid") or ""))
    e_name = _norm_name(str(entry.get("name") or ""))
    u = _norm_uid(uid)
    n = _norm_name(name)
    if not e_uid or not e_name or not u or not n:
        return False
    return u == e_uid and n == e_name


def load_public_blacklist() -> list[dict[str, Any]]:
    return [
        {"uid": r.get("uid", ""), "name": r.get("name", "")}
        for r in _read_csv_table(_public_path(), _PUBLIC_FIELDS)
    ]


def replace_public_blacklist_csv(entries: list[dict[str, str]]) -> int:
    """用远程同步结果覆盖本地公共黑名单 CSV；返回写入条数。"""
    rows: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        uid = _norm_uid(str(entry.get("uid") or ""))
        name = _norm_name(str(entry.get("name") or ""))
        if uid and name:
            rows.append({"uid": uid, "name": name})
    _write_csv_table(_public_path(), _PUBLIC_FIELDS, rows)
    return len(rows)


def is_on_public_blacklist(*, uid: str, name: str) -> bool:
    for entry in load_public_blacklist():
        if _entry_matches(entry, uid=uid, name=name):
            return True
    return False


def self_identity_from_snapshot(
    config: dict[str, Any], board_snapshot: dict[str, Any]
) -> tuple[str, str]:
    """己方 ``(uid, name)``。"""
    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    uid = _norm_uid(self_uid)
    name = ""
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if uid and isinstance(players, dict):
        pdata = players.get(uid)
        if isinstance(pdata, dict):
            name = _norm_name(str(pdata.get("name") or ""))
    return uid, name


def is_self_on_public_blacklist(
    config: dict[str, Any], board_snapshot: dict[str, Any]
) -> bool:
    """当前用户（己方）是否在公共黑名单中。"""
    uid, name = self_identity_from_snapshot(config, board_snapshot)
    if not uid and not name:
        return False
    return is_on_public_blacklist(uid=uid, name=name)


SELF_PUBLIC_BLACKLIST_FORCE_BID = 1


def _parse_bid_row(row: dict[str, str]) -> dict[str, Any] | None:
    uid = _norm_uid(row.get("uid", ""))
    if not uid:
        return None
    try:
        round_no = int(row.get("round") or 0)
    except ValueError:
        round_no = 0
    try:
        bid = int(row.get("bid") or 0)
    except ValueError:
        bid = 0
    return {
        "game_uid": _norm_uid(row.get("game_uid", "")),
        "uid": uid,
        "name": _norm_name(row.get("name", "")),
        "round": round_no,
        "bid": bid,
    }


def load_match_blacklist_bids(
    game_uid: str, *, uid: str | None = None
) -> list[dict[str, Any]]:
    """本局对局黑名单出价记录（可按对手 ``uid`` 过滤）。"""
    g = _norm_uid(game_uid)
    if not g:
        return []
    out: list[dict[str, Any]] = []
    for row in _read_csv_table(_match_path(), _MATCH_FIELDS):
        if _norm_uid(row.get("game_uid", "")) != g:
            continue
        parsed = _parse_bid_row(row)
        if parsed is None:
            continue
        if uid and parsed["uid"] != _norm_uid(uid):
            continue
        out.append(parsed)
    return out


def _bid_row_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        _norm_uid(row.get("game_uid", "")),
        _norm_uid(row.get("uid", "")),
        str(row.get("round") or "").strip(),
        str(row.get("bid") or "").strip(),
        _norm_name(row.get("name", "")),
    )


def append_match_blacklist_bid(
    *,
    game_uid: str,
    uid: str,
    name: str,
    round_no: int,
    bid: int,
) -> bool:
    """
    追加一条对手出价记录。相同 ``game_uid`` + ``uid`` + ``round`` + ``bid`` 不重复写入。

    返回是否新增了记录。
    """
    g = _norm_uid(game_uid)
    u = _norm_uid(uid)
    if not g or not u or int(bid) <= 0 or int(round_no) <= 0:
        return False
    new_row = {
        "game_uid": g,
        "uid": u,
        "name": _norm_name(name),
        "round": str(int(round_no)),
        "bid": str(int(bid)),
    }
    rows = _read_csv_table(_match_path(), _MATCH_FIELDS)
    key = _bid_row_key(new_row)
    if any(_bid_row_key(r) == key for r in rows):
        return False
    rows.append(new_row)
    _write_csv_table(_match_path(), _MATCH_FIELDS, rows)
    return True


def match_blacklist_opponent_entry(
    *, game_uid: str, uid: str
) -> dict[str, Any] | None:
    bids = load_match_blacklist_bids(game_uid, uid=uid)
    if not bids:
        return None
    name = next((str(b.get("name") or "") for b in bids if b.get("name")), "")
    return {
        "uid": _norm_uid(uid),
        "name": name,
        "bids": bids,
        "abnormal_signal_bid_count": len(bids),
    }


def is_on_match_blacklist(*, game_uid: str, uid: str, name: str) -> bool:
    g = _norm_uid(game_uid)
    if not g:
        return False
    for row in load_match_blacklist_bids(g):
        if _entry_matches(row, uid=uid, name=name):
            return True
    return False


def add_player_to_match_blacklist(
    *,
    game_uid: str,
    uid: str,
    name: str,
    round_no: int,
    bid: int | None = None,
) -> tuple[bool, str]:
    """
    画板手动将玩家记入对局黑名单（写入 CSV 出价行）。

    返回 ``(是否新增, 说明文案)``。已在名单中时 ``(False, ...)``。
    """
    g = _norm_uid(game_uid)
    u = _norm_uid(uid)
    if not g or not u:
        return False, "缺少对局 UID，无法加入"
    if is_on_match_blacklist(game_uid=g, uid=u, name=name):
        return False, "已在对局黑名单"
    rnd = max(1, int(round_no))
    amount = bid
    if amount is None or int(amount) <= 0:
        amount = _STEAL_EXPRESS_ROUND1_BID_MIN
    elif int(amount) < _STEAL_EXPRESS_ROUND1_BID_MIN:
        amount = _STEAL_EXPRESS_ROUND1_BID_MIN
    added = append_match_blacklist_bid(
        game_uid=g,
        uid=u,
        name=name,
        round_no=rnd,
        bid=int(amount),
    )
    if added:
        return True, "已加入对局黑名单"
    return False, "写入失败"


def remove_player_from_match_blacklist(
    *, game_uid: str, uid: str, name: str
) -> tuple[bool, str]:
    """
    从对局黑名单 CSV 移除该玩家在本局 ``game_uid`` 下的全部出价记录。

    返回 ``(是否移除, 说明文案)``。
    """
    g = _norm_uid(game_uid)
    if not g:
        return False, "缺少对局 UID，无法移除"
    rows = _read_csv_table(_match_path(), _MATCH_FIELDS)
    kept: list[dict[str, str]] = []
    removed = 0
    for row in rows:
        parsed = _parse_bid_row(row)
        if (
            parsed is not None
            and _norm_uid(str(parsed.get("game_uid") or "")) == g
            and _entry_matches(parsed, uid=uid, name=name)
        ):
            removed += 1
            continue
        kept.append(row)
    if removed <= 0:
        return False, "未在对局黑名单"
    _write_csv_table(_match_path(), _MATCH_FIELDS, kept)
    return True, "已移出对局黑名单"


def record_steal_express_on_match_blacklist(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    *,
    round_no: int = 1,
    bid: int | None = None,
) -> bool:
    """
    暗号已对上且对手指定回合出价 > 1000：向对局黑名单追加一条出价记录。

    返回是否新增了记录。
    """
    row = _opponent_player_data(config, board_snapshot)
    if row is None:
        return False
    uid, name, _ = row
    if not _player_identity_complete(uid, name):
        return False

    amount = bid
    if amount is None:
        amount = _opponent_round_bid(config, board_snapshot, int(round_no))
    if amount is None or int(amount) < _STEAL_EXPRESS_ROUND1_BID_MIN:
        return False

    g_uid = _norm_uid(str(game_uid_from_snapshot(board_snapshot) or ""))
    if not g_uid:
        return False

    return append_match_blacklist_bid(
        game_uid=g_uid,
        uid=uid,
        name=name,
        round_no=int(round_no),
        bid=int(amount),
    )


def player_express_blacklist_reason(
    *, uid: str, name: str, game_uid: str
) -> str:
    """
    指定玩家是否在表情暗号黑名单中。

    返回 ``public`` / ``match`` / ``""``。
    """
    if is_on_public_blacklist(uid=uid, name=name):
        return "public"
    g = _norm_uid(game_uid)
    if g and is_on_match_blacklist(game_uid=g, uid=uid, name=name):
        return "match"
    return ""


def opponent_express_blacklist_banner(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
) -> tuple[str, str] | None:
    """
    快递站画板顶栏：对手若在黑名单则返回 ``(显示名, 黑名单类型文案)``。

    类型文案为「公共」或「对局」。
    """
    blocked, reason = opponent_blocks_express_emoji_signal_price(
        config, board_snapshot
    )
    if not blocked or not reason:
        return None
    opp = opponent_identity_from_snapshot(config, board_snapshot)
    if opp is None:
        return None
    uid, name = opp
    display = _norm_name(name) or _norm_uid(uid) or "对手"
    kind = "公共" if reason == "public" else "对局"
    return display, kind


def opponent_blocks_express_emoji_signal_price(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
) -> tuple[bool, str]:
    """
    是否因黑名单跳过暗号价。

    返回 ``(blocked, reason)``，``reason`` 为 ``public`` / ``match`` / ``""``。
    """
    opp = opponent_identity_from_snapshot(config, board_snapshot)
    if opp is None:
        return False, ""
    uid, name = opp
    if is_on_public_blacklist(uid=uid, name=name):
        return True, "public"
    g_uid = _norm_uid(str(game_uid_from_snapshot(board_snapshot) or ""))
    if g_uid and is_on_match_blacklist(game_uid=g_uid, uid=uid, name=name):
        return True, "match"
    return False, ""


def record_opponent_steal_express_bids_from_snapshot(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
) -> int:
    """
    将快照中对手各回合出价 > 1000 的条目写入对局黑名单 CSV。

    不因对手已在公共/对局黑名单而跳过；仅要求 ``uid``、``name`` 完整可写。
    返回本次尝试写入的条数（去重后实际新增数）。
    """
    row = _opponent_player_data(config, board_snapshot)
    if row is None:
        return 0
    uid, name, pdata = row
    if not _player_identity_complete(uid, name):
        return 0
    g_uid = _norm_uid(str(game_uid_from_snapshot(board_snapshot) or ""))
    if not g_uid:
        return 0

    appended = 0
    prices = pdata.get("prices") or {}
    if isinstance(prices, dict):
        for key in prices:
            try:
                round_no = int(key) + 1
            except (TypeError, ValueError):
                continue
            bid = player_round_price_bid(pdata, round_no)
            if bid is not None and int(bid) >= _STEAL_EXPRESS_ROUND1_BID_MIN:
                if append_match_blacklist_bid(
                    game_uid=g_uid,
                    uid=uid,
                    name=name,
                    round_no=round_no,
                    bid=int(bid),
                ):
                    appended += 1
    return appended


def _player_identity_complete(uid: str, name: str) -> bool:
    """``uid``、``name`` 均非空方可记入对局黑名单。"""
    return bool(_norm_uid(uid) and _norm_name(name))


def maybe_update_steal_express_blacklist(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
) -> int | None:
    """
    暗号对上时：将对手各回合已出现且 > 1000 的出价写入对局黑名单；返回首回合出价。

    己方在公共黑名单时不记对局黑名单：此时己方强制出 1，对手未按暗号座次价配合时
    的高价不应视为偷快递。对手已在公共/对局黑名单时仍继续追记异常出价。
    """
    if is_self_on_public_blacklist(config, board_snapshot):
        return _opponent_round1_bid(config, board_snapshot)

    record_opponent_steal_express_bids_from_snapshot(config, board_snapshot)
    return _opponent_round1_bid(config, board_snapshot)
