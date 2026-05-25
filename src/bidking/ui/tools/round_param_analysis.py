# -*- coding: utf-8 -*-
"""回合参数分析助手（原 ``tools/gui8.py``）：对局报表 CSV + R1~R5 系数模拟。"""

from __future__ import annotations

import csv
import io
import json
import os
import tkinter as tk
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from ...config.map_runtime_overlay import (
    merged_runtime_with_map_pricing,
    resolve_automation_map_config_key,
)
from ...config.paths import config_overlay_path, pricing_map_overlay_path, runtime_path
from ...config.pricing import deep_merge
from .._bot_config_panel import DEFAULT_BID_RATIO_BY_ROUND

MULTIPLIERS = [2.0, 1.6, 1.3, 1.1]  # R1~R4 秒杀倍数
PREMIUM_MIN = 10000

COEF_MIN = 0.50
COEF_MAX = 1.20
COEF_STEP = 0.01
RECO_COEF_HALF_WINDOW = 0.15  # 推荐系数在原系数 ± 此范围内搜索
# 目标玩家下拉：报表内出现次数须大于该值（>5 即至少 6 条玩家行）
TARGET_PLAYER_MIN_ROWS = 5

_SHELL_ATTR = "_bidking_round_param_shell"

# 对局报表在 Windows/Excel 下常为 GBK；配置 JSON 一般为 UTF-8
_READ_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936")


def _normalize_player_name(name: str) -> str:
    return (name or "").replace("\r", "").replace("\n", "").strip()


def _decode_text_bytes(raw: bytes) -> str:
    for enc in _READ_TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _load_json_file(path: Path) -> dict:
    return json.loads(_decode_text_bytes(path.read_bytes()))


def _merged_config_from_disk() -> dict:
    rp = runtime_path()
    runtime_base = _load_json_file(rp) if rp.is_file() else {}
    op = config_overlay_path()
    overlay = _load_json_file(op) if op.is_file() else {}
    return deep_merge(runtime_base, overlay)


def _bid_ratio_strings_from_map(
    map_key: str,
    config: dict,
) -> list[str]:
    mp = pricing_map_overlay_path(map_key)
    if mp.is_file():
        data = _load_json_file(mp)
        au = data.get("automation") if isinstance(data.get("automation"), dict) else {}
    else:
        merged = merged_runtime_with_map_pricing(config, map_bundle_key=map_key)
        au = merged.get("automation") if isinstance(merged.get("automation"), dict) else {}
    br_src = au.get("bid_ratio_by_round") if isinstance(au.get("bid_ratio_by_round"), dict) else {}
    out: list[str] = []
    for round_no in range(1, 6):
        key = str(round_no)
        if key in br_src:
            try:
                out.append(f"{float(br_src[key]):.2f}")
            except (TypeError, ValueError):
                out.append(f"{DEFAULT_BID_RATIO_BY_ROUND[key]:.2f}")
        else:
            out.append(f"{DEFAULT_BID_RATIO_BY_ROUND[key]:.2f}")
    return out


def resolve_orig_coef_strings_for_map(map_bundle: str | None) -> tuple[list[str], str]:
    """从磁盘 ``configs/pricing.maps/<档键>`` 或合并配置读取 ``bid_ratio_by_round``。"""
    config = _merged_config_from_disk()
    key = (map_bundle or "").strip()
    if key and key != "全部":
        return _bid_ratio_strings_from_map(key, config), f"地图 {key}"
    auto = config.get("automation") if isinstance(config.get("automation"), dict) else {}
    fallback = resolve_automation_map_config_key(auto)
    return _bid_ratio_strings_from_map(fallback, config), f"默认地图 {fallback}"


def parse_map_from_uid(uid: str) -> tuple[int | None, str]:
    """从 ``MapId:对局id`` 解析地图 ID 与门票档键（230/240 等）。"""
    if ":" not in uid:
        return None, ""
    head = uid.split(":", 1)[0].strip()
    try:
        from ...parsing.item_db import map_bundle_key_for_automation, normalize_map_id

        mid = int(head)
        norm = normalize_map_id(mid)
        bundle = map_bundle_key_for_automation(int(norm) if norm is not None else mid)
        return mid, bundle
    except (TypeError, ValueError):
        return None, ""


def ticket_for_map_bundle(bundle_key: str) -> int | None:
    """``automation.map_entry_ticket_by_map_id`` 中该地图档的门票。"""
    if not bundle_key:
        return None
    config = _merged_config_from_disk()
    auto = config.get("automation") if isinstance(config.get("automation"), dict) else {}
    by_id = auto.get("map_entry_ticket_by_map_id")
    if not isinstance(by_id, dict):
        return None
    raw = by_id.get(bundle_key)
    if raw is None and bundle_key.isdigit():
        raw = by_id.get(int(bundle_key))
    try:
        v = int(raw)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def format_bids_short(bids: list[int | None]) -> str:
    parts: list[str] = []
    for i, b in enumerate(bids):
        if b is not None and b > 0:
            parts.append(f"R{i + 1}:{b}")
    return ";".join(parts) if parts else "—"


def parse_bids(bid_str: str) -> list[int | None]:
    result: list[int | None] = [None] * 5
    if not bid_str or not bid_str.strip():
        return result
    for part in bid_str.split(";"):
        part = part.strip()
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        if k.startswith("R") and k[1:].isdigit():
            idx = int(k[1:]) - 1
            if 0 <= idx < 5:
                try:
                    result[idx] = int(v)
                except ValueError:
                    pass
    return result


def load_games(filepath: str | os.PathLike[str]) -> tuple[list[dict], str]:
    text = _decode_text_bytes(Path(filepath).read_bytes())
    rows = list(csv.reader(io.StringIO(text)))

    games_dict: dict[str, dict] = {}
    name_counts: Counter[str] = Counter()

    for row in rows[1:]:
        if len(row) < 8:
            continue
        uid = row[0].strip()
        name = _normalize_player_name(row[3])
        bids = parse_bids(row[5])
        try:
            item_value = int(row[6])
        except ValueError:
            item_value = 0
        try:
            csv_profit = int(row[7])
        except ValueError:
            csv_profit = 0

        name_counts[name] += 1

        if uid not in games_dict:
            map_id, map_bundle = parse_map_from_uid(uid)
            games_dict[uid] = {
                "uid": uid,
                "map_id": map_id,
                "map_bundle": map_bundle,
                "players": [],
                "prize_pool": 0,
            }
        games_dict[uid]["players"].append(
            {
                "name": name,
                "bids": bids,
                "item_value": item_value,
                "csv_profit": csv_profit,
            }
        )
        if item_value > games_dict[uid]["prize_pool"]:
            games_dict[uid]["prize_pool"] = item_value

    games = list(games_dict.values())
    games.sort(key=lambda g: g["uid"])
    top_name = name_counts.most_common(1)[0][0] if name_counts else ""
    return games, top_name


def _player_row_counts(games: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for g in games:
        for p in g.get("players") or []:
            n = _normalize_player_name(str(p.get("name") or ""))
            if n:
                counts[n] += 1
    return counts


def _selectable_target_options(
    games: list[dict],
    *,
    min_rows: int = TARGET_PLAYER_MIN_ROWS,
) -> list[tuple[str, str]]:
    """
    报表内出现次数 > ``min_rows`` 的玩家，按出现次数降序。
    返回 ``(下拉显示 \"名称 (次数)\", 纯名称)``。
    """
    counts = _player_row_counts(games)
    out: list[tuple[str, str]] = []
    for name, cnt in counts.most_common():
        if cnt > min_rows:
            out.append((f"{name} ({cnt})", name))
    return out


def _parse_target_combo_value(raw: str) -> str:
    """从 ``名称 (次数)`` 或手输名称解析目标玩家名。"""
    s = _normalize_player_name(raw)
    if not s:
        return ""
    if s.endswith(")") and " (" in s:
        head, tail = s.rsplit(" (", 1)
        if tail.rstrip(")").isdigit():
            return head.strip()
    return s


def _default_target_name(games: list[dict]) -> str:
    """出现次数 >5 的玩家中，取报表内出现最多者。"""
    opts = _selectable_target_options(games)
    return opts[0][1] if opts else ""


def simulate_auction(players: list[dict]) -> tuple[str | None, int, int]:
    for rnd in range(5):
        entries: list[tuple[str, int]] = []
        for p in players:
            b = p["bids"][rnd]
            if b is not None and b > 0:
                entries.append((p["name"], b))
        if not entries:
            continue
        entries.sort(key=lambda x: x[1], reverse=True)

        if rnd == 4:
            return entries[0][0], entries[0][1], 5
        if len(entries) == 1:
            return entries[0][0], entries[0][1], rnd + 1

        highest, second = entries[0][1], entries[1][1]
        if highest >= second * MULTIPLIERS[rnd]:
            return entries[0][0], highest, rnd + 1
    return None, 0, 0


def calc_target_profit(
    winner_name: str | None,
    winner_round_bid: int,
    prize_pool: int,
    target_name: str,
    target_round_bid: int,
    ticket: int,
) -> int:
    if winner_name is None:
        return -ticket
    if winner_name == target_name:
        return prize_pool - target_round_bid - ticket
    premium = winner_round_bid - prize_pool
    if premium > PREMIUM_MIN:
        return round(premium * 0.1) - ticket
    return -ticket


def safe_round(orig_val: int | None, orig_coef: float, new_coef: float) -> int | None:
    if orig_val is None or orig_val <= 0 or orig_coef == 0:
        return orig_val
    d_val = Decimal(str(orig_val))
    d_orig = Decimal(str(orig_coef))
    d_new = Decimal(str(new_coef))
    est = d_val / d_orig
    return int((est * d_new).to_integral_value(ROUND_HALF_UP))


def simulate_raw(game: dict, target_name: str, ticket: int) -> dict:
    players = [{"name": p["name"], "bids": p["bids"].copy()} for p in game["players"]]
    winner, w_bid, rnd = simulate_auction(players)

    t_bid = 0
    if winner == target_name:
        for p in players:
            if p["name"] == target_name:
                t_bid = p["bids"][rnd - 1] or 0
                break

    profit = calc_target_profit(winner, w_bid, game["prize_pool"], target_name, t_bid, ticket)
    return {
        "winner": winner or "无人",
        "round": rnd,
        "winner_bid": w_bid,
        "target_profit": profit,
        "target_rbid": t_bid,
    }


def simulate_adjusted(
    game: dict,
    target_name: str,
    orig_coefs: list[float],
    new_coefs: list[float],
    ticket: int,
) -> dict | None:
    target_bids = None
    target_csv_profit = None
    target_name = _normalize_player_name(target_name)
    for p in game["players"]:
        if _normalize_player_name(p.get("name", "")) == target_name:
            target_bids = p["bids"].copy()
            target_csv_profit = p["csv_profit"]
            break

    if target_bids is None:
        return None

    ests: list[float | None] = [None] * 5
    new_bids = target_bids.copy()
    for i in range(5):
        ov = target_bids[i]
        oc = orig_coefs[i]
        nc = new_coefs[i]
        if ov is not None and ov > 0 and oc and oc != 0:
            ests[i] = ov / oc
            new_bids[i] = safe_round(ov, oc, nc)

    players = []
    for p in game["players"]:
        bids = new_bids if p["name"] == target_name else p["bids"].copy()
        players.append({"name": p["name"], "bids": bids})

    winner, w_bid, rnd = simulate_auction(players)

    t_bid = 0
    if winner == target_name:
        for p in players:
            if p["name"] == target_name:
                t_bid = p["bids"][rnd - 1] or 0
                break

    profit = calc_target_profit(winner, w_bid, game["prize_pool"], target_name, t_bid, ticket)
    return {
        "winner": winner or "无人",
        "round": rnd,
        "winner_bid": w_bid,
        "target_profit": profit,
        "target_rbid": t_bid,
        "ests": ests,
        "orig_bids": target_bids,
        "new_bids": new_bids,
        "csv_profit": target_csv_profit,
    }


def _reco_coef_range(center: float) -> list[float]:
    """原系数 ± ``RECO_COEF_HALF_WINDOW``，步长 ``COEF_STEP``，并夹在 [COEF_MIN, COEF_MAX]。"""
    lo = max(COEF_MIN, center - RECO_COEF_HALF_WINDOW)
    hi = min(COEF_MAX, center + RECO_COEF_HALF_WINDOW)
    if hi < lo:
        return [round(max(COEF_MIN, min(COEF_MAX, center)), 2)]
    n = int(round((hi - lo) / COEF_STEP)) + 1
    return [round(lo + i * COEF_STEP, 2) for i in range(n)]


def total_sim_profit(
    games: list[dict],
    target_name: str,
    orig_coefs: list[float],
    new_coefs: list[float],
    ticket: int,
) -> int:
    total = 0
    for g in games:
        sr = simulate_adjusted(g, target_name, orig_coefs, new_coefs, ticket)
        if sr is not None:
            total += sr["target_profit"]
    return total


def infer_best_coef_for_round(
    round_idx: int,
    games: list[dict],
    target_name: str,
    ticket: int,
    orig_coefs: list[float],
    new_coefs: list[float],
) -> float | None:
    """单回合推荐系数：在原系数 ±0.15 内枚举，取总模拟收益最高者。"""
    if not games or not target_name:
        return None

    center = orig_coefs[round_idx]
    if center <= 0:
        return None

    base = list(new_coefs)
    profits: dict[float, int] = {}
    for c in _reco_coef_range(center):
        trial = base.copy()
        trial[round_idx] = c
        profits[c] = total_sim_profit(games, target_name, orig_coefs, trial, ticket)

    if not profits:
        return None

    max_profit = max(profits.values())
    tied = [c for c, p in profits.items() if p == max_profit]
    return min(tied, key=lambda c: abs(c - center))


def infer_best_coefs(
    games: list[dict],
    target_name: str,
    ticket: int,
    orig_coefs: list[float],
    new_coefs: list[float],
) -> list[float | None]:
    return [
        infer_best_coef_for_round(i, games, target_name, ticket, orig_coefs, new_coefs)
        for i in range(5)
    ]


def _default_report_csv_path() -> Path | None:
    """全局对局总表 ``game_match_reports.csv``（不合并带时间戳的会话分表）。"""
    try:
        from ...parsing.game_report_csv import resolve_game_report_csv_path

        p = resolve_game_report_csv_path()
        return p if p.is_file() else None
    except Exception:
        return None


class _HoverTooltip:
    """Treeview 行悬浮提示。"""

    def __init__(self, widget: tk.Misc) -> None:
        self._widget = widget
        self._tip: tk.Toplevel | None = None
        self._label: tk.Label | None = None

    def show(self, x: int, y: int, text: str) -> None:
        if not text.strip():
            self.hide()
            return
        if self._tip is None:
            self._tip = tk.Toplevel(self._widget)
            self._tip.wm_overrideredirect(True)
            self._tip.attributes("-topmost", True)
            self._label = tk.Label(
                self._tip,
                text=text,
                justify=tk.LEFT,
                background="#ffffe0",
                relief=tk.SOLID,
                borderwidth=1,
                font=("Consolas", 9),
                padx=6,
                pady=4,
            )
            self._label.pack()
        else:
            assert self._label is not None
            self._label.configure(text=text)
        self._tip.wm_geometry(f"+{x + 14}+{y + 18}")

    def hide(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
            self._label = None


class RoundParamAnalysisApp:
    """回合参数分析：加载 ``game_match_reports`` CSV，调节 R1~R5 系数并模拟利润。"""

    def __init__(self, root: tk.Misc, *, shell_root: tk.Misc | None = None) -> None:
        self.root = root
        self._shell_root = shell_root if shell_root is not None else root
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.title("回合参数分析助手")
            root.geometry("1480x780")
            root.resizable(True, True)

        self.games: list[dict] = []
        self.top_name = ""
        self.baseline: dict[str, dict] = {}
        self.sim_results: dict[str, dict | None] = {}
        self._sel_uid: str | None = None
        self._hover_uid: str | None = None
        self._sort_col: str = "uid"
        self._sort_reverse: bool = False
        self._load_summary: str = ""

        self.orig_entries: list[ttk.Entry] = []
        self.new_spins: list[tk.Spinbox] = []
        self.new_vars: list[tk.StringVar] = []
        self.reco_vars: list[tk.StringVar] = []
        self._reco_coefs: list[float | None] = [None] * 5

        self._build_ui()
        self._auto_load()

    def _build_ui(self) -> None:
        f1 = ttk.Frame(self.root, padding=5)
        f1.pack(fill=tk.X)
        ttk.Label(f1, text="CSV:").pack(side=tk.LEFT)
        self.file_var = tk.StringVar()
        ttk.Entry(f1, textvariable=self.file_var, width=80).pack(side=tk.LEFT, padx=5)
        ttk.Button(f1, text="浏览", command=self._browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(f1, text="加载", command=self._do_load).pack(side=tk.LEFT, padx=2)

        ttk.Separator(f1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        ttk.Label(f1, text="目标玩家:").pack(side=tk.LEFT)
        self.target_var = tk.StringVar(value="")
        self.target_combo = ttk.Combobox(
            f1,
            textvariable=self.target_var,
            width=20,
            state="readonly",
        )
        self.target_combo.pack(side=tk.LEFT, padx=3)
        self.target_combo.bind("<<ComboboxSelected>>", lambda _e: self._sim_all())
        self.target_combo.bind("<Return>", lambda _e: self._sim_all())

        ttk.Label(f1, text="门票:").pack(side=tk.LEFT, padx=(8, 0))
        self.ticket_var = tk.StringVar(value="5000")
        ttk.Entry(f1, textvariable=self.ticket_var, width=7).pack(side=tk.LEFT, padx=2)

        ttk.Button(f1, text="▶ 全部模拟", command=self._sim_all).pack(side=tk.LEFT, padx=10)

        grp_coef = ttk.LabelFrame(
            self.root,
            text="系数设置（原系数用于反推估价，新系数用于生成出价）",
            padding=10,
        )
        grp_coef.pack(fill=tk.X, padx=10, pady=(8, 0))

        coef_hdr = ttk.Frame(grp_coef)
        coef_hdr.grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 4))
        self.orig_source_var = tk.StringVar(value="")
        ttk.Label(
            coef_hdr,
            textvariable=self.orig_source_var,
            foreground="#5a6a7a",
        ).pack(side=tk.LEFT)
        ttk.Button(
            coef_hdr,
            text="↻ 读所选地图系数",
            command=lambda: self._apply_orig_coefs_for_map_filter(interactive=True),
            width=14,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(
            coef_hdr,
            text="填入推荐系数",
            command=self._apply_recommended_coefs,
            width=12,
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(grp_coef, text="", width=4).grid(row=1, column=0)
        ttk.Label(grp_coef, text="原系数", width=8).grid(row=1, column=1)
        ttk.Label(grp_coef, text="新系数", width=8).grid(row=1, column=2)
        ttk.Label(grp_coef, text="推荐", width=8).grid(row=1, column=3)
        ttk.Label(grp_coef, text="", width=2).grid(row=1, column=4)

        defaults_orig, _ = resolve_orig_coef_strings_for_map(None)
        defaults_new = list(defaults_orig)

        for i in range(5):
            row = i + 2
            ttk.Label(grp_coef, text=f"R{i + 1}", width=4, font=("", 9, "bold")).grid(
                row=row, column=0, pady=2, sticky=tk.E
            )

            ev = tk.StringVar(value=defaults_orig[i])
            e = ttk.Entry(grp_coef, textvariable=ev, width=7)
            e.grid(row=row, column=1, padx=4, pady=1)
            self.orig_entries.append(e)

            sv = tk.StringVar(value=defaults_new[i])
            sp = tk.Spinbox(
                grp_coef,
                textvariable=sv,
                from_=COEF_MIN,
                to=COEF_MAX,
                increment=0.01,
                width=7,
                format="%.2f",
                command=self._sim_all,
            )
            sp.grid(row=row, column=2, padx=4, pady=1)
            sp.bind("<Return>", lambda _e: self._sim_all())
            self.new_spins.append(sp)
            self.new_vars.append(sv)

            rv = tk.StringVar(value="—")
            ttk.Label(
                grp_coef,
                textvariable=rv,
                width=8,
                foreground="#0066cc",
                font=("", 9, "bold"),
            ).grid(row=row, column=3, padx=4, pady=1)
            self.reco_vars.append(rv)

        ttk.Button(grp_coef, text="导出CSV", command=self._export).grid(
            row=2, column=4, rowspan=2, padx=20, sticky="ns"
        )

        self._apply_orig_coefs_for_map_filter()

        f_filter = ttk.Frame(self.root, padding=(8, 4, 8, 0))
        f_filter.pack(fill=tk.X)
        ttk.Label(f_filter, text="地图筛选:").pack(side=tk.LEFT)
        self.map_filter_var = tk.StringVar(value="全部")
        self.map_filter_combo = ttk.Combobox(
            f_filter,
            textvariable=self.map_filter_var,
            values=("全部",),
            width=8,
            state="readonly",
        )
        self.map_filter_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.map_filter_combo.bind("<<ComboboxSelected>>", self._on_map_filter_changed)
        ttk.Label(
            f_filter,
            text="（按地图档 230/240 等筛选；切换时同步该档门票）",
            foreground="#5a6a7a",
        ).pack(side=tk.LEFT)

        f_table = ttk.Frame(self.root, padding=5)
        f_table.pack(fill=tk.BOTH, expand=True, padx=5)

        cols = (
            "uid",
            "map",
            "prize",
            "win_bid",
            "csv_profit",
            "orig_r1",
            "orig_r2",
            "orig_r3",
            "orig_r4",
            "orig_r5",
            "new_r1",
            "new_r2",
            "new_r3",
            "new_r4",
            "new_r5",
            "base",
            "sim",
            "delta",
        )
        self.tree = ttk.Treeview(f_table, columns=cols, show="headings")

        cfg = [
            ("uid", "对局UID", 175),
            ("map", "地图", 48),
            ("prize", "当局藏品价值", 88),
            ("win_bid", "赢家出价", 88),
            ("csv_profit", "玩家收益", 72),
            ("orig_r1", "原R1", 58),
            ("orig_r2", "原R2", 58),
            ("orig_r3", "原R3", 58),
            ("orig_r4", "原R4", 58),
            ("orig_r5", "原R5", 58),
            ("new_r1", "新R1", 58),
            ("new_r2", "新R2", 58),
            ("new_r3", "新R3", 58),
            ("new_r4", "新R4", 58),
            ("new_r5", "新R5", 58),
            ("base", "基准利润", 76),
            ("sim", "模拟利润", 76),
            ("delta", "变化", 62),
        ]
        for c, label, w in cfg:
            self.tree.heading(
                c,
                text=label,
                command=lambda col=c: self._sort_by_column(col),
            )
            anchor = tk.W if c == "uid" else tk.CENTER
            self.tree.column(c, width=w, anchor=anchor)

        sb = ttk.Scrollbar(f_table, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self._row_tooltip = _HoverTooltip(self.tree)

        f_detail = ttk.Frame(self.root, padding=5)
        f_detail.pack(fill=tk.X)
        self.detail_var = tk.StringVar(value="—")
        ttk.Label(
            f_detail, textvariable=self.detail_var, relief=tk.SUNKEN, anchor=tk.W, padding=4
        ).pack(fill=tk.X)

        f_status = ttk.Frame(self.root)
        f_status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="就绪 — 请加载 CSV")
        ttk.Label(
            f_status, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=4
        ).pack(fill=tk.X)
        self.analysis_var = tk.StringVar(value="")
        ttk.Label(
            f_status,
            textvariable=self.analysis_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=4,
            foreground="#0066cc",
        ).pack(fill=tk.X)

    def _auto_load(self) -> None:
        path = _default_report_csv_path()
        if path is None:
            self.status_var.set("未找到总表 data/game_match_reports.csv")
            return
        try:
            self.games, _ = load_games(path)
        except Exception as e:
            messagebox.showerror("自动加载失败", str(e))
            return
        self._load_summary = f"总表 {path.name} → {len(self.games)} 局"
        self.file_var.set(str(path))
        self._after_games_loaded()
        self._populate_map_filter_options()
        self._apply_orig_coefs_for_map_filter()
        self._sim_all()

    def _after_games_loaded(self) -> None:
        options = _selectable_target_options(self.games)
        self.target_combo["values"] = [disp for disp, _ in options]
        self.top_name = options[0][1] if options else ""
        if options:
            self.target_var.set(options[0][0])
        else:
            self.target_var.set("")
            messagebox.showwarning(
                "目标玩家",
                f"报表中没有出现次数大于 {TARGET_PLAYER_MIN_ROWS} 次的角色名，"
                "请检查总表 CSV 或换一份报表加载。",
            )

    def _populate_map_filter_options(self) -> None:
        bundles = sorted(
            {str(g.get("map_bundle") or "") for g in self.games if g.get("map_bundle")}
        )
        self.map_filter_combo.unbind("<<ComboboxSelected>>")
        self.map_filter_combo["values"] = ("全部",) + tuple(bundles)
        self.map_filter_var.set("全部")
        self.map_filter_combo.bind("<<ComboboxSelected>>", self._on_map_filter_changed)

    def _filtered_games(self) -> list[dict]:
        sel = self.map_filter_var.get().strip()
        if not sel or sel == "全部":
            return self.games
        return [g for g in self.games if str(g.get("map_bundle") or "") == sel]

    def _on_map_filter_changed(self, *_args: object) -> None:
        bundle = self.map_filter_var.get().strip()
        if bundle and bundle != "全部":
            ticket = ticket_for_map_bundle(bundle)
            if ticket is not None:
                self.ticket_var.set(str(ticket))
            self._apply_orig_coefs_for_map_filter()
        if self.games:
            self._sim_all()

    def _apply_orig_coefs_for_map_filter(self, *, interactive: bool = False) -> None:
        bundle = ""
        if hasattr(self, "map_filter_var"):
            bundle = self.map_filter_var.get().strip()
        if interactive and (not bundle or bundle == "全部"):
            messagebox.showinfo(
                "提示",
                "请先在「地图筛选」中选择具体地图档（如 230、240），再读取对应系数。",
            )
            return
        map_key = bundle if bundle and bundle != "全部" else None
        coef_strs, source = resolve_orig_coef_strings_for_map(map_key)
        for i, s in enumerate(coef_strs):
            entry = self.orig_entries[i]
            entry.delete(0, tk.END)
            entry.insert(0, s)
        self.orig_source_var.set(f"原系数来源：{source}（automation.bid_ratio_by_round）")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("所有", "*.*")])
        if path:
            self.file_var.set(path)

    def _do_load(self) -> None:
        path = self.file_var.get().strip()
        if not path:
            return
        try:
            self.games, self.top_name = load_games(path)
            self._load_summary = f"{Path(path).name} → {len(self.games)} 局"
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return

        self._after_games_loaded()
        self._populate_map_filter_options()
        self._apply_orig_coefs_for_map_filter()
        self._sim_all()

    def _read_params(self) -> tuple[str, int, list[float], list[float]]:
        target = _parse_target_combo_value(self.target_var.get())
        try:
            ticket = int(self.ticket_var.get().strip())
        except ValueError:
            ticket = 5000

        orig_coefs: list[float] = []
        new_coefs: list[float] = []
        for i in range(5):
            try:
                orig_coefs.append(float(self.orig_entries[i].get().strip()))
            except ValueError:
                orig_coefs.append(0.0)
            try:
                new_coefs.append(float(self.new_vars[i].get().strip()))
            except ValueError:
                new_coefs.append(0.0)

        return target, ticket, orig_coefs, new_coefs

    def _sim_all(self, *args: object) -> None:
        if not self.games:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        if not target:
            return

        self.baseline.clear()
        self.sim_results.clear()
        for g in self.games:
            self.baseline[g["uid"]] = simulate_raw(g, target, ticket)
            sr = simulate_adjusted(g, target, orig_coefs, new_coefs, ticket)
            self.sim_results[g["uid"]] = sr

        self._refresh_tree()
        self._update_recommendations(target, ticket, orig_coefs, new_coefs)
        self._warn_if_target_missing(target)

    def _warn_if_target_missing(self, target: str) -> None:
        if not target or not self.games:
            return
        n = sum(
            1
            for g in self.games
            if any(_normalize_player_name(p.get("name", "")) == target for p in g["players"])
        )
        if n == 0:
            sample = ", ".join(name for _, name in _selectable_target_options(self.games)[:8])
            messagebox.showwarning(
                "目标玩家未匹配",
                f"当前目标「{target}」在已加载报表的 {len(self.games)} 局中均未出现。\n\n"
                f"请从「目标玩家」下拉框选择（仅含出现>{TARGET_PLAYER_MIN_ROWS}次的角色）。\n"
                f"可选示例：{sample or '（无）'}",
            )

    def _eligible_games(self, target: str) -> list[dict]:
        target = _normalize_player_name(target)
        return [
            g
            for g in self._filtered_games()
            if any(_normalize_player_name(p.get("name", "")) == target for p in g["players"])
        ]

    def _update_recommendations(
        self,
        target: str,
        ticket: int,
        orig_coefs: list[float],
        new_coefs: list[float],
    ) -> None:
        eligible = self._eligible_games(target)
        if not eligible or not target:
            self._reco_coefs = [None] * 5
            for rv in self.reco_vars:
                rv.set("—")
            return

        self.status_var.set(self.status_var.get() + " | 推理推荐系数中…")
        self.root.update_idletasks()

        recos = infer_best_coefs(eligible, target, ticket, orig_coefs, new_coefs)
        self._reco_coefs = list(recos)
        for i, rv in enumerate(self.reco_vars):
            c = recos[i]
            if c is None:
                rv.set("—")
                continue
            cur = new_coefs[i]
            if abs(c - cur) < 1e-6:
                rv.set(f"{c:.2f}")
            elif c > cur:
                rv.set(f"{c:.2f} ↑")
            else:
                rv.set(f"{c:.2f} ↓")

        status = self.status_var.get().replace(" | 推理推荐系数中…", "")
        self.status_var.set(status)

    def _apply_recommended_coefs(self) -> None:
        """将推荐列数值写入新系数并重新模拟。"""
        filled = 0
        for i, c in enumerate(self._reco_coefs):
            if c is None:
                continue
            self.new_vars[i].set(f"{float(c):.2f}")
            filled += 1
        if filled == 0:
            messagebox.showinfo(
                "提示",
                "暂无推荐系数。请先加载报表并点击「▶ 全部模拟」。",
            )
            return
        self._sim_all()

    def _target_csv_profit(self, g: dict, target: str) -> int:
        """目标玩家报表中的最终收益。"""
        target = _normalize_player_name(target)
        for p in g.get("players") or []:
            if _normalize_player_name(p.get("name", "")) == target:
                return int(p.get("csv_profit") or 0)
        return 0

    def _baseline_winner_bid_text(self, uid: str) -> str:
        bl = self.baseline.get(uid)
        if not bl:
            return "—"
        return str(int(bl.get("winner_bid") or 0))

    def _tree_row_values(self, g: dict, target: str) -> tuple[Any, ...]:
        uid = g["uid"]
        bl = self.baseline.get(uid, {})
        sr = self.sim_results.get(uid)
        map_b = str(g.get("map_bundle") or "—")
        prize = int(g.get("prize_pool") or 0)
        win_bid = self._baseline_winner_bid_text(uid)
        csv_p = self._target_csv_profit(g, target)

        if sr is None:
            return (
                uid,
                map_b,
                str(prize),
                win_bid,
                str(csv_p),
                *(["—"] * 10),
                "—",
                "—",
                "—",
            )

        bp = int(bl.get("target_profit", 0))
        sp = int(sr.get("target_profit", 0))
        delta = sp - bp
        delta_s = f"+{delta}" if delta > 0 else str(delta)
        orig = sr["orig_bids"]
        newb = sr["new_bids"]
        return (
            uid,
            map_b,
            str(prize),
            win_bid,
            str(csv_p),
            _b(orig[0]),
            _b(orig[1]),
            _b(orig[2]),
            _b(orig[3]),
            _b(orig[4]),
            _b(newb[0]),
            _b(newb[1]),
            _b(newb[2]),
            _b(newb[3]),
            _b(newb[4]),
            str(bp),
            str(sp),
            delta_s,
        )

    def _sort_key_for_column(self, col: str, values: tuple[Any, ...]) -> Any:
        idx_map = {
            "uid": 0,
            "map": 1,
            "prize": 2,
            "win_bid": 3,
            "csv_profit": 4,
            "orig_r1": 5,
            "orig_r2": 6,
            "orig_r3": 7,
            "orig_r4": 8,
            "orig_r5": 9,
            "new_r1": 10,
            "new_r2": 11,
            "new_r3": 12,
            "new_r4": 13,
            "new_r5": 14,
            "base": 15,
            "sim": 16,
            "delta": 17,
        }
        i = idx_map.get(col, 0)
        raw = values[i] if i < len(values) else ""
        if col in ("prize", "win_bid", "csv_profit", "base", "sim", "delta"):
            s = str(raw).lstrip("+").replace(",", "")
            try:
                return int(s)
            except ValueError:
                return -10**18
        if col.startswith("orig_") or col.startswith("new_"):
            s = str(raw)
            if s in ("", "—"):
                return -1
            try:
                return int(s)
            except ValueError:
                return -1
        return str(raw)

    def _sort_by_column(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        target = _parse_target_combo_value(self.target_var.get())
        rows: list[tuple[tuple[Any, ...], dict]] = []
        for g in self._filtered_games():
            vals = self._tree_row_values(g, target)
            rows.append((vals, g))

        rows.sort(
            key=lambda item: self._sort_key_for_column(self._sort_col, item[0]),
            reverse=self._sort_reverse,
        )

        for vals, _g in rows:
            self.tree.insert("", tk.END, values=vals)

        self._update_status()

    def _update_status(self) -> None:
        if not self.sim_results:
            return

        visible = self._filtered_games()
        valid_srs: list[dict] = []
        for g in visible:
            sr = self.sim_results.get(g["uid"])
            if sr is not None:
                valid_srs.append(sr)
        if not valid_srs:
            return

        target, ticket, orig_coefs, new_coefs = self._read_params()
        map_sel = self.map_filter_var.get().strip()

        csv_sum = sum(sr["csv_profit"] for sr in valid_srs)
        base_sum = sum(
            self.baseline[g["uid"]]["target_profit"]
            for g in visible
            if self.sim_results.get(g["uid"]) is not None
        )
        sim_sum = sum(sr["target_profit"] for sr in valid_srs)
        d = sim_sum - base_sum

        mismatch = 0
        for sr in valid_srs:
            for i in range(5):
                if sr["orig_bids"][i] is not None and sr["new_bids"][i] is not None:
                    if sr["orig_bids"][i] != sr["new_bids"][i]:
                        mismatch += 1
                        break

        map_part = f" | 地图={map_sel}" if map_sel and map_sel != "全部" else ""
        load_part = f"{self._load_summary} | " if self._load_summary else ""
        self.status_var.set(
            load_part
            + f"显示 {len(valid_srs)}/{len(self.games)} 局{map_part} | 目标: {target} | "
            f"CSV原始: {csv_sum:,} | 门票={ticket} | "
            f"原系数 {_fmt5(orig_coefs)} → 新系数 {_fmt5(new_coefs)} | "
            f"基准: {base_sum:,} | 模拟: {sim_sum:,} | 变化: {d:+,}"
            + (f" | ⚠出价不一致:{mismatch}局" if mismatch else "")
        )

        blocked: list[tuple[str, str, int, int]] = []
        for g in visible:
            sr = self.sim_results.get(g["uid"])
            if sr is None:
                continue
            bl = self.baseline.get(g["uid"])
            if bl is None:
                continue

            orig_winner = bl.get("winner", "无人")
            if orig_winner == target or orig_winner == "无人":
                continue

            sim_winner = sr.get("winner", "无人")
            if sim_winner != orig_winner:
                prize_pool = g["prize_pool"]
                orig_w_profit = prize_pool - bl["winner_bid"] - ticket
                new_w_profit = -ticket
                blocked.append((g["uid"], orig_winner, orig_w_profit, new_w_profit))

        if blocked:
            total_change = sum(owp - nwp for _, _, owp, nwp in blocked)
            blocked.sort(key=lambda x: abs(x[2] - x[3]), reverse=True)
            top3 = blocked[:3]
            top_strs = []
            for uid, name, owp, nwp in top3:
                short_uid = uid[-20:] if len(uid) > 20 else uid
                top_strs.append(f"{short_uid}/{name}:{owp:+,}→{nwp:+,}")

            self.analysis_var.set(
                f"阻止 {len(blocked)} 人拍下仓 | 他们利润变化合计: {total_change:+,} | "
                + "Top: "
                + "  ".join(top_strs)
            )
        else:
            self.analysis_var.set("阻止 0 人（无人被阻止）")

    def _on_select(self, event: object) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        self._sel_uid = self.tree.item(sel[0], "values")[0]
        self._show_detail(self._sel_uid)

    def _on_tree_motion(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self._hover_uid = None
            self._row_tooltip.hide()
            return
        vals = self.tree.item(row_id, "values")
        if not vals:
            return
        uid = str(vals[0])
        if uid == self._hover_uid:
            return
        self._hover_uid = uid
        g = next((x for x in self.games if x["uid"] == uid), None)
        if not g:
            self._row_tooltip.hide()
            return
        target = _parse_target_combo_value(self.target_var.get())
        lines: list[str] = []
        for p in g.get("players") or []:
            name = _normalize_player_name(str(p.get("name") or ""))
            if name == target:
                continue
            lines.append(f"{name}: {format_bids_short(p.get('bids') or [])}")
        if not lines:
            lines.append("（无其他玩家）")
        self._row_tooltip.show(event.x_root, event.y_root, "\n".join(lines))

    def _on_tree_leave(self, _event: object) -> None:
        self._hover_uid = None
        self._row_tooltip.hide()

    def _show_detail(self, uid: str) -> None:
        g = next((g for g in self.games if g["uid"] == uid), None)
        if not g:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        bl = self.baseline.get(uid, {})
        sr = self.sim_results.get(uid)

        if sr is None:
            self.detail_var.set(f"[{uid}] 目标玩家「{target}」不在本局")
            return

        ests = sr["ests"]
        orig = sr["orig_bids"]
        newb = sr["new_bids"]

        parts = []
        for i in range(5):
            e = _i(ests[i])
            o = _b(orig[i])
            n = _b(newb[i])
            ok = "✓" if (orig[i] == newb[i]) else "✗"
            parts.append(
                f"R{i + 1}:估价={e}(÷{orig_coefs[i]}) 原={o}→×{new_coefs[i]}→新={n}[{ok}]"
            )

        blocked_info = ""
        orig_winner = bl.get("winner", "无人")
        sim_winner = sr.get("winner", "无人")
        if orig_winner != target and orig_winner != "无人" and sim_winner != orig_winner:
            prize_pool = g["prize_pool"]
            owp = prize_pool - bl["winner_bid"] - ticket
            nwp = -ticket
            blocked_info = f" | ⛔阻止了{orig_winner} 利润{owp:+,}→{nwp:+,}"

        csv_p = self._target_csv_profit(g, target)
        w_bid = int(bl.get("winner_bid") or 0)
        opp_parts: list[str] = []
        for p in g.get("players") or []:
            nm = str(p.get("name") or "")
            if nm == target:
                continue
            opp_parts.append(f"{nm}={format_bids_short(p.get('bids') or [])}")

        self.detail_var.set(
            f"[{uid}] 地图={g.get('map_bundle') or '—'} | "
            f"藏品={g['prize_pool']:,} | 赢家出价={w_bid:,}({bl.get('winner', '—')}) | 玩家收益={csv_p:,} | "
            + " | ".join(parts)
            + " | 对手: "
            + ("; ".join(opp_parts) if opp_parts else "—")
            + " | "
            f"基准: {bl.get('winner', '—')}(R{bl.get('round', '—')}) "
            f"利润={bl.get('target_profit', '—')} | "
            f"模拟: {sr.get('winner', '—')}(R{sr.get('round', '—')}) "
            f"利润={sr.get('target_profit', '—')}"
            + blocked_info
        )

    def _export(self) -> None:
        if not self.games or not self.sim_results:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "对局UID",
                    "地图档",
                    "当局藏品价值",
                    "赢家出价",
                    "玩家收益",
                    "估价1",
                    "估价2",
                    "估价3",
                    "估价4",
                    "估价5",
                    "原R1",
                    "原R2",
                    "原R3",
                    "原R4",
                    "原R5",
                    "新R1",
                    "新R2",
                    "新R3",
                    "新R4",
                    "新R5",
                    "基准利润",
                    "模拟利润",
                    "利润变化",
                    "原始赢家",
                    "模拟赢家",
                    "是否被阻止",
                ]
            )
            for g in self._filtered_games():
                sr = self.sim_results.get(g["uid"])
                if sr is None:
                    continue
                bl = self.baseline.get(g["uid"], {})
                ests = sr["ests"]
                orig = sr["orig_bids"]
                newb = sr["new_bids"]
                bp = bl.get("target_profit", 0)
                sp = sr.get("target_profit", 0)
                csv_p = self._target_csv_profit(g, target)

                orig_w = bl.get("winner", "无人")
                sim_w = sr.get("winner", "无人")
                was_blocked = (
                    orig_w != target and orig_w != "无人" and sim_w != orig_w
                )

                w.writerow(
                    [
                        g["uid"],
                        g.get("map_bundle") or "",
                        g.get("prize_pool") or 0,
                        int(bl.get("winner_bid") or 0),
                        csv_p,
                        *[round(e) if e else "" for e in ests],
                        *[_b(orig[i]) for i in range(5)],
                        *[_b(newb[i]) for i in range(5)],
                        bp,
                        sp,
                        sp - bp,
                        orig_w,
                        sim_w,
                        "是" if was_blocked else "",
                    ]
                )
        messagebox.showinfo("导出成功", f"已保存到:\n{path}")


def _fmt5(coefs: list[float]) -> str:
    return "×".join(f"{c:.2f}" for c in coefs)


def _b(v: object) -> str:
    if v is None or v == "":
        return "—"
    return str(v)


def _i(v: float | None) -> str:
    if v is None:
        return "—"
    return str(round(v))


def launch_round_param_analysis(start_root: tk.Misc) -> None:
    """在独立 ``Toplevel`` 中打开回合参数分析助手（单例，已打开则置顶）。"""
    existing = getattr(start_root, _SHELL_ATTR, None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except tk.TclError:
            setattr(start_root, _SHELL_ATTR, None)

    top = tk.Toplevel(start_root)
    setattr(start_root, _SHELL_ATTR, top)

    def _on_destroy(event: tk.Event) -> None:
        if event.widget is top:
            try:
                delattr(start_root, _SHELL_ATTR)
            except AttributeError:
                pass

    top.bind("<Destroy>", _on_destroy)
    RoundParamAnalysisApp(top, shell_root=start_root)


def main() -> None:
    root = tk.Tk()
    RoundParamAnalysisApp(root, shell_root=root)
    root.mainloop()


# 兼容旧脚本 ``from gui8 import App``
App = RoundParamAnalysisApp
