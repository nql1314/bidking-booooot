# -*- coding: utf-8 -*-
"""对局结束统计：将每局每名玩家一行追加到 CSV。"""

from __future__ import annotations

import csv
import datetime
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .constants import HERO_ID
from .state import CsvItem, GameState

_LINE_TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})"
)

# 超价分配（每人）：差价 = 获胜者最后一轮出价 − 藏品总价；仅当差价 > 阈值时生效，
# 每人加计 ``(差价 − 阈值) × 比例``（先减 10000，再乘 10%）。
OVERBID_SURPLUS_THRESHOLD = 10000
OVERBID_REBATE_PER_PLAYER_RATE = 0.10

# 默认报表文件名时间戳（``game_match_reports_<stamp>.csv``）；见 ``init_game_report_csv_session``。
_SESSION_STAMP: Optional[str] = None


def init_game_report_csv_session() -> None:
    """固定本次进程默认对局报表路径的时间戳。

    在 GUI / 看板 ``main()`` 入口调用一次，文件名即**程序启动时刻**。
    若未调用，则在首次 ``resolve_game_report_csv_path()``（且未设置
    ``BIDKING_GAME_REPORT_CSV``）时再生成时间戳。
    """
    global _SESSION_STAMP
    if _SESSION_STAMP is None:
        _SESSION_STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _stock_container(data: Mapping[str, Any]) -> Optional[dict]:
    gd = data.get("GameData")
    if isinstance(gd, dict):
        sc = gd.get("StockContainer")
        if isinstance(sc, dict):
            return sc
    sc = data.get("StockContainer")
    return sc if isinstance(sc, dict) else None


def _sum_hit_prices(hit_list: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for box in hit_list:
        if not isinstance(box, dict):
            continue
        p = _safe_int(box.get("ItemPrice"))
        if p is not None:
            total += p
    return total


def _sum_stock_boxes_item_cid(
    sc: Mapping[str, Any], csv_index: Mapping[int, CsvItem]
) -> int:
    """
    真实客户端 ``StockContainer.StockBoxes``：每项为
    ``{ "BoxId", "Position", "Item": { "Cid": item_id, "Count": n } | {} }``，
    价格表用 ``item_prices.csv`` 的 ``base_value``。
    """
    rows = sc.get("StockBoxes")
    if not isinstance(rows, list):
        return 0
    total = 0
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        item = entry.get("Item")
        if not isinstance(item, dict) or not item:
            continue
        cid = _safe_int(item.get("Cid") or item.get("ItemCid"))
        if cid is None:
            continue
        cnt = _safe_int(item.get("Count"))
        if cnt is None or cnt < 1:
            cnt = 1
        row = csv_index.get(cid)
        if row is not None:
            total += int(row.base_value) * cnt
    return total


def _stock_value_by_user_hitbox_style(data: Mapping[str, Any]) -> Dict[str, int]:
    """旧版/测试数据：按 ``UserUid`` + ``HitBoxList`` 的 ``ItemPrice`` 汇总。"""
    sc = _stock_container(data)
    if not sc:
        return {}

    out: Dict[str, int] = {}

    for key in ("UserStockList", "StockUserList", "PlayerStockList"):
        rows = sc.get(key)
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                uid = str(row.get("UserUid") or row.get("Uid") or "").strip()
                if not uid:
                    continue
                for hk in ("HitBoxList", "StockBoxList", "StockBoxes", "Items", "ItemList"):
                    hits = row.get(hk)
                    if isinstance(hits, list) and hits and isinstance(hits[0], dict):
                        if "ItemPrice" in hits[0] or "ItemUid" in hits[0]:
                            out[uid] = out.get(uid, 0) + _sum_hit_prices(hits)
                            break
            if out:
                return out

    rows = sc.get("StockBoxes")
    if not isinstance(rows, list) or not rows:
        return out

    first = rows[0]
    if isinstance(first, dict) and (
        "ItemPrice" in first or "ItemUid" in first or "ItemCid" in first
    ):
        win = str(data.get("WinUserUid") or "").strip()
        total = _sum_hit_prices(rows)
        if win and total:
            return {win: total}
        return {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("UserUid") or row.get("Uid") or "").strip()
        if not uid:
            continue
        for hk in ("HitBoxList", "StockBoxList", "Items", "ItemList"):
            hits = row.get(hk)
            if isinstance(hits, list):
                out[uid] = out.get(uid, 0) + _sum_hit_prices(hits)
                break
    return out


def _build_stock_by_user(
    data: Mapping[str, Any], csv_index: Optional[Mapping[int, CsvItem]]
) -> Dict[str, int]:
    """
    优先：整盘 ``StockBoxes`` + ``Item.Cid`` → 仅计入 ``WinUserUid``（竞拍整板归胜者）。
    否则：回退 ``HitBoxList`` / ``ItemPrice`` 等旧结构。
    """
    sc = _stock_container(data)
    winner = str(data.get("WinUserUid") or "").strip()
    if csv_index and sc:
        t = _sum_stock_boxes_item_cid(sc, csv_index)
        if t > 0 and winner:
            return {winner: t}
    return _stock_value_by_user_hitbox_style(data)


def _first_int(d: Mapping[str, Any], keys: Tuple[str, ...]) -> Optional[int]:
    for k in keys:
        if k in d:
            v = _safe_int(d.get(k))
            if v is not None:
                return v
    return None


def _user_explicit_stock_profit(u: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    explicit_stock = _first_int(
        u,
        (
            "StockTotalPrice",
            "TotalStockPrice",
            "StockPrice",
            "ItemTotalPrice",
            "TotalItemPrice",
            "BoardTotalPrice",
            "FinalStockPrice",
        ),
    )
    explicit_profit = _first_int(
        u,
        (
            "Profit",
            "GameProfit",
            "NetProfit",
            "SettlementProfit",
            "Earn",
            "TotalEarn",
            "EarnGold",
            "UserProfit",
            "ScoreChange",
            "ChangeScore",
        ),
    )
    return explicit_stock, explicit_profit


def _player_assigned_stock(
    puid: str,
    winner_uid: str,
    stock_by_user: Dict[str, int],
    explicit_stock: Optional[int],
) -> Optional[int]:
    if explicit_stock is not None:
        return explicit_stock
    if not stock_by_user:
        return None
    if len(stock_by_user) == 1:
        only = next(iter(stock_by_user.items()))
        wk, wv = only
        if winner_uid and puid == winner_uid and wk == winner_uid:
            return wv
        if winner_uid and puid != winner_uid:
            return 0
        return stock_by_user.get(puid)
    return stock_by_user.get(puid)


def _bid_round_csv_label(protocol_round: Optional[int]) -> int:
    """协议 ``Round`` / ``state.prices`` 键为 0 起（缺省视为 0）；CSV 从 R1 起算（首轮=R1.. 一般到 R5 对应协议 0..4）。"""
    r = _safe_int(protocol_round)
    if r is None:
        r = 0
    return int(r) + 1


def _format_round_bids(price_log: List[Mapping[str, Any]]) -> str:
    pairs: List[Tuple[int, Any]] = []
    for pl in price_log or []:
        if not isinstance(pl, dict):
            continue
        r = _safe_int(pl.get("Round"))
        if r is None:
            r = 0
        pairs.append((r, pl.get("ItemCidOrPrice", "")))
    pairs.sort(key=lambda x: x[0])
    return ";".join(
        f"R{_bid_round_csv_label(t[0])}:{t[1]}" for t in pairs
    )


def _sum_round_bids(price_log: List[Mapping[str, Any]]) -> int:
    s = 0
    for pl in price_log or []:
        if not isinstance(pl, dict):
            continue
        v = _safe_int(pl.get("ItemCidOrPrice"))
        if v is not None:
            s += v
    return s


def _last_round_bid_sum(price_log: List[Mapping[str, Any]]) -> int:
    """同一协议轮次内多条则相加；取最大 ``Round``（缺省 0）的那一轮为「最后一轮」。"""
    by_r: Dict[int, int] = {}
    for pl in price_log or []:
        if not isinstance(pl, dict):
            continue
        r = _safe_int(pl.get("Round"))
        if r is None:
            r = 0
        v = _safe_int(pl.get("ItemCidOrPrice"))
        if v is None:
            continue
        by_r[int(r)] = by_r.get(int(r), 0) + int(v)
    if not by_r:
        return 0
    return int(by_r[max(by_r.keys())])


def _last_state_round_bid(prices: Mapping[Any, Any]) -> int:
    """``state.players[*].prices`` 键为协议轮次 0 起；取最大键的一轮出价。"""
    by_r: Dict[int, int] = {}
    for rk, pv in (prices or {}).items():
        r = _safe_int(rk)
        if r is None:
            continue
        v = _safe_int(pv)
        if v is None:
            continue
        by_r[int(r)] = by_r.get(int(r), 0) + int(v)
    if not by_r:
        return 0
    return int(by_r[max(by_r.keys())])


def _format_bids_from_state_prices(prices: Mapping[Any, Any]) -> str:
    pairs: List[Tuple[int, Any]] = []
    for rk, pv in (prices or {}).items():
        r = _safe_int(rk)
        if r is None:
            continue
        pairs.append((r, pv))
    pairs.sort(key=lambda x: x[0])
    return ";".join(
        f"R{_bid_round_csv_label(t[0])}:{t[1]}" for t in pairs
    )


def _map_entry_ticket(
    automation: Mapping[str, Any],
    map_id: int,
    _snapshot_path_hint: Optional[str] = None,
) -> int:
    """
    仅从 ``automation.map_entry_ticket_by_map_id`` 读取门票：键为地图 ``MapId`` 的
    **档键**（与 :func:`bidking.parsing.item_db.map_bundle_key_for_automation` 一致，
    如 ``2301`` / ``2310`` / ``2306`` → 键 ``\"230\"``）。

    第三参保留为兼容旧调用，已忽略。
    """
    if map_id <= 0:
        return 0
    from .item_db import map_bundle_key_for_automation

    key = map_bundle_key_for_automation(map_id)
    by_id = automation.get("map_entry_ticket_by_map_id")
    if not isinstance(by_id, dict):
        return 0
    raw = by_id.get(key)
    if raw is None and key.isdigit():
        raw = by_id.get(int(key))
    v = _safe_int(raw)
    if v is not None and v > 0:
        return int(v)
    return 0


def _compute_overbid_rebate_per_player(
    winner_uid: str,
    board_total: int,
    winner_last_round_bid: int,
) -> int:
    """
    差价 = 获胜者最后一轮出价 − 藏品总价。若差价 > ``OVERBID_SURPLUS_THRESHOLD``（10000），
    则每人超价分配为 ``round((差价 − 10000) × OVERBID_REBATE_PER_PLAYER_RATE)``（先减阈值再乘 10%），
    加计到「最终收益」估算（所有 ``UserLog`` 玩家同额）。

    若 ``UserLog`` 自带 ``Profit`` 等协议字段，上层不调用本估算（保持原值）。
    """
    if not winner_uid or board_total <= 0:
        return 0
    wb = int(winner_last_round_bid)
    price_diff = wb - int(board_total)
    if price_diff <= OVERBID_SURPLUS_THRESHOLD:
        return 0
    after_cut = price_diff - OVERBID_SURPLUS_THRESHOLD
    return int(round(max(0, after_cut) * OVERBID_REBATE_PER_PLAYER_RATE))


def _hero_label(hero_cid: Any) -> str:
    try:
        cid = int(hero_cid)
    except (TypeError, ValueError):
        return str(hero_cid)
    tag = HERO_ID.get(cid)
    if tag:
        return f"{cid}:{tag}"
    return str(cid)


def resolve_game_report_csv_path() -> Path:
    """路径：环境变量 ``BIDKING_GAME_REPORT_CSV``；否则 ``<data>/game_match_reports_<启动时间>.csv``。"""
    env = os.environ.get("BIDKING_GAME_REPORT_CSV", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    init_game_report_csv_session()
    stamp = _SESSION_STAMP or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from bidking.config.paths import data_dir

        return (data_dir() / f"game_match_reports_{stamp}.csv").resolve()
    except Exception:
        return (Path.cwd() / f"game_match_reports_{stamp}.csv").resolve()


def resolve_game_report_history_csv_path() -> Path:
    """
    历史补录文件路径：环境变量 ``BIDKING_GAME_REPORT_HISTORY_CSV``；否则
    ``<data>/game_match_reports_history_<启动时间>.csv``，与同次启动的 live CSV
    共享时间戳，方便成对查看。
    """
    env = os.environ.get("BIDKING_GAME_REPORT_HISTORY_CSV", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    init_game_report_csv_session()
    stamp = _SESSION_STAMP or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        from bidking.config.paths import data_dir

        return (data_dir() / f"game_match_reports_history_{stamp}.csv").resolve()
    except Exception:
        return (Path.cwd() / f"game_match_reports_history_{stamp}.csv").resolve()


def _extract_log_line_timestamp(line: str) -> str:
    """从 Player.log 行前缀提取 ``YYYY-MM-DD HH:MM:SS``；找不到返回空串。"""
    m = _LINE_TIMESTAMP_RE.search(line)
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)}"


def backfill_history_game_reports_csv(
    log_path: str,
    csv_path: str,
    *,
    target_path: Optional[Path] = None,
    overwrite: bool = False,
) -> Optional[Tuple[Path, int]]:
    """
    扫描历史日志，将所有已结束（含 ``S2C_45``）的对局**单独**写入历史 CSV。

    - 不影响 live 报表：写入的是 ``resolve_game_report_history_csv_path()``
      （或显式 ``target_path``）这条独立路径。
    - 幂等：本次启动若历史文件已存在则直接返回，不重复生成。
      用 ``overwrite=True`` 可强制覆盖重写。
    - 行内对局开始 / 结束时间：若日志行前缀有 ``YYYY-MM-DD HH:MM:SS`` 则用之；
      否则**留空**（避免误导成"补录时刻"）。Unity 默认 Player.log 不带时间戳。
    - 若 ``BIDKING_DISABLE_GAME_REPORT`` 为真则跳过（与 live 行为一致）。

    Returns:
        ``(写出文件路径, 新写入对局行数)``；被跳过或没有任何已结束对局可写时
        返回 ``None``。若历史文件本次启动已存在且未要求覆盖，返回 ``(path, 0)``。
    """
    if os.environ.get("BIDKING_DISABLE_GAME_REPORT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return None

    target = target_path or resolve_game_report_history_csv_path()
    if target.exists() and not overwrite:
        return (target, 0)
    if target.exists() and overwrite:
        try:
            target.unlink()
        except OSError:
            return None

    if not log_path or not os.path.exists(log_path):
        return None

    from .handlers import handle_s2c33, handle_s2c37, handle_s2c39, handle_s2c45
    from .item_db import load_csv
    from .log_source import extract_event, iter_log_lines

    try:
        csv_index, csv_items = load_csv(csv_path)
    except (OSError, ValueError):
        return None

    silent = io.StringIO()
    state = GameState()
    game_active = False
    pending_start_ts = ""
    wrote_count = 0

    for line in iter_log_lines(log_path, tail=False):
        if line is None:
            break
        ts = _extract_log_line_timestamp(line)
        result = extract_event(line)
        if not result:
            continue
        event_type, data = result

        if event_type == "S2C_33_game_start_notify":
            state = GameState()
            game_active = True
            handle_s2c33(data, state, csv_index, csv_items, silent)
            state.match_started_at = ts
            pending_start_ts = ts
        elif event_type == "S2C_37_game_next_round_notify" and game_active:
            handle_s2c37(data, state, csv_index, csv_items, silent)
        elif event_type == "S2C_39_game_use_item" and game_active:
            handle_s2c39(data, state, csv_index, csv_items, silent)
        elif event_type == "S2C_45_game_over_notify" and game_active:
            handle_s2c45(
                data, state, csv_index, csv_items, silent,
                write_game_report_csv=False,
            )
            state.match_started_at = pending_start_ts
            state.match_ended_at = ts
            try:
                append_game_over_report_csv(
                    data, state, csv_index, target_path=target,
                )
                wrote_count += 1
            except OSError:
                pass
            game_active = False
            pending_start_ts = ""

    if wrote_count == 0 and not target.exists():
        return None
    return (target, wrote_count)


def append_game_over_report_csv(
    data: Mapping[str, Any],
    state: GameState,
    csv_index: Optional[Mapping[int, CsvItem]] = None,
    *,
    target_path: Optional[Path] = None,
) -> None:
    """
    在收到 ``S2C_45`` 且 ``state`` 已 ``update_players`` 后调用：
    每个 ``UserLog`` 玩家追加一行。

    列：对局UID, 对局开始时间, 对局结束时间, 角色名称, 角色英雄, 每轮出价,
    最终藏品价值, 最终收益

    「每轮出价」格式 ``R1:价;R2:价;…``：从 R1 起算（日志 ``Round`` 缺省或 0 为第一轮，
    R5 对应 ``Round`` 4）；超过五轮仍继续 R6…

    ``StockContainer`` 若为客户端真实结构（``Item.Cid``），需传入 ``csv_index``
    用 ``base_value`` 求和；整盘价值记在 ``WinUserUid``，其余玩家藏品价值为 0。

    收益（无协议 ``Profit`` 等字段时估算）：

    - **获胜者**：基础 = ``总藏品价值 − 本人最后一轮出价``（同轮多条则加总后再取最大轮次）；
      再 ``+`` 超价分配、``−`` 门票。
    - **未获胜**（无论是否出过价）：出价不在此列扣减；基础 = ``0``；再 ``+`` 超价分配、``−`` 门票。

    超价分配：差价 = 最后一轮出价 − 藏品总价；差价 > 10000 时每人
    ``(差价 − 10000) × 10%``（先减 10000 再乘 10%）。若 ``UserLog`` 自带 ``Profit`` 等，整列保持原值
    （不再叠门票/返利，避免与服务器重复）。

    ``target_path``：显式指定输出文件；缺省则走 ``resolve_game_report_csv_path()``。
    用于历史补录（``backfill_history_game_reports_csv``）写入独立的历史 CSV。
    """
    if os.environ.get("BIDKING_DISABLE_GAME_REPORT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return

    gd = data.get("GameData")
    if not isinstance(gd, dict):
        return

    game_uid = str(state.uid or gd.get("Uid") or "").strip()
    if not game_uid:
        return

    winner_uid = str(data.get("WinUserUid") or "").strip()
    stock_by_user = _build_stock_by_user(data, csv_index)

    try:
        from bidking.config.runtime import load_runtime

        automation: Mapping[str, Any] = load_runtime().raw.get("automation") or {}
    except Exception:
        automation = {}
    map_id_int = int(_safe_int(gd.get("MapId")) or _safe_int(state.map_id) or 0)
    entry_ticket = _map_entry_ticket(automation, map_id_int)

    user_logs: List[dict] = [
        u for u in (gd.get("UserLog") or []) if isinstance(u, dict)
    ]
    winner_last_bid = 0
    for u in user_logs:
        if str(u.get("UserUid") or "").strip() != winner_uid:
            continue
        winner_last_bid = _last_round_bid_sum(list(u.get("PriceLog") or []))
        break
    board_total_winner = int(stock_by_user.get(winner_uid, 0) or 0)
    rebate_per = _compute_overbid_rebate_per_player(
        winner_uid,
        board_total_winner,
        winner_last_bid,
    )

    path = target_path or resolve_game_report_csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    new_file = not path.exists() or path.stat().st_size == 0
    encoding = "utf-8-sig" if new_file else "utf-8"
    t_start = str(getattr(state, "match_started_at", "") or "")
    t_end = str(getattr(state, "match_ended_at", "") or "")
    header = [
        "对局UID",
        "对局开始时间",
        "对局结束时间",
        "角色名称",
        "角色英雄",
        "每轮出价",
        "最终藏品价值",
        "最终收益",
    ]

    rows_out: List[List[str]] = []

    def append_row(
        name: str,
        hero_cid: Any,
        bids: str,
        price_log: List[Mapping[str, Any]],
        u: Mapping[str, Any],
    ) -> None:
        puid = str(u.get("UserUid") or "").strip()
        ex_stock, profit_v = _user_explicit_stock_profit(u)
        stock_v = _player_assigned_stock(puid, winner_uid, stock_by_user, ex_stock)
        if stock_v is None and ex_stock is None:
            stock_v = stock_by_user.get(puid)
        last_bid = _last_round_bid_sum(price_log)
        if profit_v is None:
            is_winner = bool(winner_uid and puid == winner_uid)
            if is_winner:
                col = int(stock_v) if stock_v is not None else board_total_winner
                base_profit = int(col) - int(last_bid)
            else:
                base_profit = 0
            profit_v = int(base_profit)
            if rebate_per:
                profit_v += int(rebate_per)
            if entry_ticket:
                profit_v -= int(entry_ticket)
        if winner_uid and puid != winner_uid:
            stock_display: Optional[int] = 0
        else:
            stock_display = stock_v
        rows_out.append(
            [
                game_uid,
                t_start,
                t_end,
                name,
                _hero_label(hero_cid),
                bids,
                "" if stock_display is None else str(stock_display),
                "" if profit_v is None else str(profit_v),
            ]
        )

    for u in user_logs:
        name = str(u.get("Name") or "").strip()
        plog = list(u.get("PriceLog") or [])
        append_row(
            name,
            u.get("HeroCid"),
            _format_round_bids(plog),
            plog,
            u,
        )

    if not rows_out and state.players:
        fb_winner_last = 0
        wp = state.players.get(winner_uid)
        if isinstance(wp, dict):
            fb_winner_last = _last_state_round_bid(wp.get("prices") or {})
        fb_board = int(stock_by_user.get(winner_uid, 0) or 0)
        fb_rebate = _compute_overbid_rebate_per_player(
            winner_uid, fb_board, fb_winner_last
        )
        for p_uid, p in state.players.items():
            prices = p.get("prices") or {}
            bids = _format_bids_from_state_prices(prices)
            ex_stock, _ = _user_explicit_stock_profit({})
            stock_v = _player_assigned_stock(
                p_uid, winner_uid, stock_by_user, ex_stock
            )
            if stock_v is None:
                stock_v = stock_by_user.get(p_uid)
            last_b = _last_state_round_bid(prices)
            is_w = bool(winner_uid and p_uid == winner_uid)
            if is_w:
                col = int(stock_v) if stock_v is not None else fb_board
                base_p = int(col) - int(last_b)
            else:
                base_p = 0
            profit_v = int(base_p)
            if fb_rebate:
                profit_v += int(fb_rebate)
            if entry_ticket:
                profit_v -= int(entry_ticket)
            if winner_uid and p_uid != winner_uid:
                sd: Optional[int] = 0
            else:
                sd = stock_v
            rows_out.append(
                [
                    game_uid,
                    t_start,
                    t_end,
                    str(p.get("name") or ""),
                    _hero_label(p.get("hero_cid")),
                    bids,
                    "" if sd is None else str(sd),
                    "" if profit_v is None else str(profit_v),
                ]
            )

    if not rows_out:
        return

    with open(path, "a", encoding=encoding, newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerows(rows_out)


__all__ = [
    "append_game_over_report_csv",
    "backfill_history_game_reports_csv",
    "init_game_report_csv_session",
    "resolve_game_report_csv_path",
    "resolve_game_report_history_csv_path",
]
