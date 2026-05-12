# -*- coding: utf-8 -*-
"""
网格可视化窗口

用 tkinter 将当前对局物品按 BoxId / 形状渲染为 10×30 格子地图，
支持鼠标点击弹窗查看该物品的所有候选列表。

手动画框、幽灵品质偏好、手动确认 id 等写入快照的 ``grid_overlay``；
与日志 ``game_state.items`` 的合并与定价投影由 ``analysis._board_pricing`` 在计算时完成。
覆盖层与日志的同步（清轮廓、删重叠幽灵、扫描负向约束）在 ``_overlay_reconcile``；
``grid_overlay`` JSON 组装在 ``_grid_overlay_payload``。

布局规则（来自游戏协议）：
  - 网格：10 列 × 最多 30 行
  - BoxId = 行 × 10 + 列（行列均从 0 开始）
  - ItemSlotType XY → X 列宽 × Y 行高
  - 只有品质无大小时默认按 1×1 显示

实时监听模式（log_path 非 None 时激活）：
  - 后台线程从文件当前 EOF 开始 tail，解析新增事件并更新 GameState
  - 通过 queue.SimpleQueue 传信号给 UI 主线程
  - UI 主线程每 300ms 通过 root.after() 轮询队列，按需重绘
  - 新对局开始（S2C_33）时：若配置了快照路径则先备份至该路径同级 ``run/`` 再删除旧快照文件（``run/`` 内 ``*.json`` 超过 100 个时按修改时间删最早的），随后清空并重置界面并写入新快照
  - 日志监听与写快照均在 threading.RLock 保护下进行；``_refresh`` 结束时会写出 ``snapshot_path``
   （含 ``grid_overlay`` 手画幽灵/轮廓/空置剔除等），手动画框与拖调轮廓也会触发刷新从而落盘

看板角色（board_mode）：
  - elsa / raven：空置候选区（橘红）与顶部空置估价均由 ``grid_overlay`` 统一计算，无「第几回合起才显示」门槛。
  - raven：状态栏附带铺板顺序提示。
  - 地图技能 200009（所有藏品格数）：在已知区内已占位格数未达到该总数前，空置计数与橘红层**忽略诈骗格过滤**；吃满后且扫描上仅剩金红候选时，才对几何空置应用诈骗格剔除。
  - 诈骗格规则**仅用于**上述自动空置区（计数与初始橘红），**不限制**右键手动剔除/恢复空置标记。
  - 空置候选格：普通右键可手动剔除该格（不计空置、不铺橘红），再右键同一格可恢复。
"""

import io
import json
import os
import queue
import sys
import shutil
import statistics
import threading
import time
from datetime import datetime
import tkinter as tk
from pathlib import Path
from copy import deepcopy
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from ... import __version__
from ...parsing.constants import (
    CATEGORY_NAMES,
    fmt_shape,
)
from ...parsing.handlers import handle_s2c33, handle_s2c37, handle_s2c39, handle_s2c45
from ...parsing.item_db import (
    candidate_probabilities,
    map_category_ratios,
    probability_source_label,
    query_item,
)
from ...parsing.log_source import extract_event
from ...parsing.state import CsvItem, GameState, ItemKnowledge
from ...analysis._board_pricing import (
    build_snapshot_pricing_dict,
    estimate_snapshot_item_price_for_uid,
)
from ...analysis import grid_overlay as _grid_overlay
from ...analysis.raw_pricing import build_raw_pricing_dict
from ...analysis.snapshot import game_state_to_json, item_knowledge_to_json
from ...config.runtime import load_runtime
from ...pricing.compute import compute_price
from ._grid_overlay_payload import (
    build_grid_overlay_export_dict,
    max_anchor_box_id_from_overlay_ui,
)
from ._overlay_reconcile import (
    apply_scan_history_to_phantom_items,
    reconcile_overlay_after_refresh,
)

# ─── 布局常量 ──────────────────────────────────────────────────────────────

GRID_COLS = 10  # 游戏地图固定宽度
GRID_ROWS = 30  # 游戏地图最大高度
VISIBLE_ROWS = 10  # 默认视口显示行数
CELL_SIZE = 56  # 每格像素边长
CELL_W = CELL_SIZE
CELL_H = CELL_SIZE
CANVAS_MAX_W = GRID_COLS * CELL_W + 1
CANVAS_MAX_H = VISIBLE_ROWS * CELL_H + 1

# ─── 品质颜色方案 ──────────────────────────────────────────────────────────

# 背景色（按品质 1-6）
QUALITY_BG: Dict[int, str] = {
    1: "#7a7a8a",  # 灰
    2: "#3a8a4a",  # 绿
    3: "#2060c0",  # 蓝
    4: "#8030b0",  # 紫
    5: "#c07010",  # 橙
    6: "#c02020",  # 红
}
# 文字色（所有品质都用白）
QUALITY_FG: Dict[int, str] = {k: "#ffffff" for k in range(1, 7)}
UNKNOWN_BG = "#fbd99a"  # 未知品质，与空格子和已知品质都有明显区分
UNKNOWN_FG = "#ffffff"
EMPTY_BG = "#2a2a3a"
GRID_LINE = "#505060"

# 空缺区域橘红覆盖层与空置计数：由 ``grid_overlay.compute_overlay_vacant_dict`` 统一计算；
# 诈骗格剔除仅在扫描推断仅剩金红候选且 200009 吃满后生效（见 ``fraud_zone_cell_exclusion_enabled``）。
EMPTY_ZONE_COLOR = "#cc4400"  # 橘红
EMPTY_ZONE_STIPPLE = "gray25"  # 约 25% 覆盖度，模拟半透明

# 看板角色：界面文案（拉文铺板提示）
BOARD_MODE_ELSA = "elsa"
BOARD_MODE_RAVEN = "raven"

# 未知品质物品的手动缩放把手（边条宽度 + 四角命中半径；四角缩放用 Ctrl+左键）
RESIZE_HANDLE_W = 8  # 四边把手条宽度（像素），提高横向拖动命中率
RESIZE_CORNER_HIT = 12  # 角落命中：以角点为心 ± 该值（像素），Ctrl+左键对角缩放
RESIZE_HANDLE_COLOR = "#ffffff"

# 手动画框的"幽灵"物品
PHANTOM_BG = "#0d3a4a"  # 深青蓝：原推断 / 非金非红显式 Q 等
PHANTOM_BORDER = "#00cccc"  # 青色边框
# 左笔金默认 / Q5：淡黄底；右笔红 / Q6：粉格
PHANTOM_GOLD_BG = "#cda48a"
PHANTOM_GOLD_BORDER = "#c18d6d"
PHANTOM_GOLD_FG = "#2a2410"
PHANTOM_PINK_BG = "#d67c8f"
PHANTOM_PINK_BORDER = "#a63cd9"
PHANTOM_PINK_FG = "#3a1525"

# 与 bidking_fresh_bot ``price_config.json`` 的 ``round_rules.multiplier`` 默认一致（第 1–4 回合为「第二价秒杀」倍数）。
_DEFAULT_ROUND_INSTANT_WIN_MULT: Dict[int, float] = {
    1: 2.0,
    2: 1.6,
    3: 1.3,
    4: 1.1,
    5: 1.0,
}


def _instant_win_multiplier_for_round(round_no: Optional[int]) -> float:
    r = max(1, min(5, int(round_no or 1)))
    return float(_DEFAULT_ROUND_INSTANT_WIN_MULT.get(r, 1.0))


def _lines_from_ahmad_points_detail(detail: Any) -> List[str]:
    """将 ``pricing.ahmad_points_detail`` 格式化为悬浮说明行。"""
    if not isinstance(detail, dict):
        return []
    out: List[str] = []
    winner = detail.get("winner")
    if winner:
        out.append(f"Ahmad 多候选取 max，采纳 id = {winner!s}")
    for c in detail.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        lbl = str(c.get("label") or "").strip()
        try:
            pv = int(c.get("points") or 0)
            pts_s = f"{pv:,}"
        except (TypeError, ValueError):
            pts_s = str(c.get("points"))
        suffix = "  ← max" if winner and cid == str(winner) else ""
        out.append(f"  • [{cid}] {lbl} → {pts_s}{suffix}")
    return out


# 写入 board_snapshot.json 的 schema 版本（与 bot 侧校验一致）
BOARD_SNAPSHOT_SCHEMA_VERSION = 2

# ``run/`` 下历史快照 JSON 上限；超出则按修改时间删最早的归档。
BOARD_SNAPSHOT_RUN_ARCHIVE_MAX = 100

# 供 fresh_aisha_bot 等读取的 JSON 快照输出路径；空字符串表示不写快照。
# 构造 ``GridWindow(snapshot_path=...)`` 时若传入非空字符串则覆盖本常量。
DEFAULT_BOARD_SNAPSHOT_PATH = r"C:\bidking\board_snapshot.json"

_WIN_FILENAME_FORBIDDEN = set('<>:"/\\|?*')


def _snapshot_player_names_for_board_archive(board_snapshot: dict) -> List[str]:
    players = (board_snapshot.get("game_state") or {}).get("players") or {}
    if not isinstance(players, dict):
        return []
    names: List[str] = []
    for pdata in players.values():
        if isinstance(pdata, dict):
            n = str(pdata.get("name") or "").strip()
            if n:
                names.append(n)
    return sorted(names)


def _safe_archive_stem_from_player_names(names: List[str]) -> str:
    if not names:
        return "board_snapshot_no_players"
    parts: List[str] = []
    for n in names:
        cleaned = "".join(
            c if c not in _WIN_FILENAME_FORBIDDEN and ord(c) >= 32 else "_" for c in n
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


def _archive_board_snapshot_then_unlink(snapshot_path: str) -> None:
    """新局开始前：将现有快照备份到快照所在目录下的 ``run/``，再删除文件（与 bot 侧原逻辑一致）。"""
    path = Path(snapshot_path)
    try:
        if not path.is_file():
            return
    except OSError:
        return
    data: dict = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    stem = _safe_archive_stem_from_player_names(
        _snapshot_player_names_for_board_archive(data)
    )
    run_dir = path.resolve().parent / "run"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    dest = run_dir / f"{stem}.json"
    if dest.exists():
        dest = run_dir / f"{stem}_{int(time.time())}.json"
    try:
        shutil.copy2(path, dest)
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass

    _prune_board_snapshot_run_archives(run_dir)


def _prune_board_snapshot_run_archives(
    run_dir: Path, max_files: int = BOARD_SNAPSHOT_RUN_ARCHIVE_MAX
) -> None:
    """保留 ``run_dir`` 内至多 ``max_files`` 个 ``*.json``，按 mtime 删最早的。"""
    try:
        files = [
            p
            for p in run_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".json"
        ]
    except OSError:
        return
    excess = len(files) - max_files
    if excess <= 0:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for p in files[:excess]:
        try:
            p.unlink()
        except OSError:
            pass


# 地图质量 CSV、快照定价与 bid 元数据见 ``board_pricing`` 模块。

HIGH_VALUE_THRESHOLD = 100_000

# 幽灵物品品质偏好：dict 中无记录 = 金默认（按 Q5 筛选）；该值 = 不限品质原推断（含金/红等）
PHANTOM_Q_INFER = "_phantom_q_infer"

# ─── 类别缩写（两字显示） ─────────────────────────────────────────────────

_CAT_SHORT: Dict[int, str] = {
    101: "家具",
    102: "医药",
    103: "时尚",
    104: "兵装",
    105: "珠宝",
    106: "文物",
    107: "数码",
    108: "能源",
    109: "食饮",
    110: "书画",
}


# ─── 悬浮提示（估价公式）──────────────────────────────────────────────────


class _PricingHoverTip:
    """在 widget 上悬浮片刻后显示动态文本（用于估价公式说明）。"""

    def __init__(self, widget: tk.Widget, get_text: Callable[[], str]) -> None:
        self.widget = widget
        self.get_text = get_text
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _cancel_sched(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _schedule(self, _event: object = None) -> None:
        self._cancel_sched()
        self._after_id = self.widget.after(380, self._show)

    def _hide(self, _event: object = None) -> None:
        self._cancel_sched()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self) -> None:
        self._after_id = None
        try:
            text = (self.get_text() or "").strip()
        except Exception:
            text = ""
        if not text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:
            pass
        tw.geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=text,
            justify="left",
            bg="#fffacd",
            fg="#1a1a2e",
            relief="solid",
            borderwidth=1,
            font=("微软雅黑", 9),
            wraplength=560,
            padx=10,
            pady=8,
        ).pack()
        self._tip = tw


# ─── 主窗口 ────────────────────────────────────────────────────────────────


class GridWindow:
    """
    BidKing 物品格局可视化窗口。

    Args:
        state       : 解析后的 GameState（含物品知识）
        csv_index   : item_id → CsvItem
        csv_items   : 全量 CsvItem 列表
        board_mode  : ``elsa``（默认）或 ``raven``（仅文案与铺板提示差异）。
        snapshot_path : 若传入非空字符串则用作快照路径；若省略则用模块常量 ``DEFAULT_BOARD_SNAPSHOT_PATH``（空字符串表示不写）。
        snapshot_export_overlay : 是否在快照中包含幽灵物品与手动轮廓（grid_overlay）。
        snapshots : 回放模式下的 ``[(标签, GameState, skill_logs), ...]``；``skill_logs`` 与实时监听累积形状一致，
            供定价/raw_pricing。兼容仅 ``(标签, state)`` 的旧列表（无技能日志时 Ahmad 等会为 0）。
        home_shell : 若传入 grid_view 启动主页 ``tk.Tk``，画板关闭或点「返回主页」时会 ``deiconify`` 该窗口；
            ``None`` 时（命令行直接进画板）行为与原先一致。
    """

    def __init__(
        self,
        state: GameState,
        csv_index: Dict[int, CsvItem],
        csv_items: List[CsvItem],
        log_path: Optional[str] = None,
        snapshots: Optional[List[Tuple[str, GameState, List[dict]]]] = None,
        map_category_weights: Optional[Dict[int, float]] = None,
        board_mode: str = BOARD_MODE_ELSA,
        snapshot_path: Optional[str] = None,
        snapshot_export_overlay: bool = True,
        home_shell: Optional[tk.Tk] = None,
    ) -> None:
        self.state = state
        self.csv_index = csv_index
        self.csv_items = csv_items
        self._log_path = log_path
        bm = (board_mode or BOARD_MODE_ELSA).strip().lower()
        self._board_mode = (
            bm if bm in (BOARD_MODE_ELSA, BOARD_MODE_RAVEN) else BOARD_MODE_ELSA
        )
        if snapshot_path is None:
            sp = (DEFAULT_BOARD_SNAPSHOT_PATH or "").strip() or None
        elif isinstance(snapshot_path, str):
            sp = snapshot_path.strip() or None
        else:
            sp = None
        self._snapshot_path = sp
        if self._snapshot_path:
            snap_parent = Path(self._snapshot_path).expanduser().parent
            try:
                snap_parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                print(
                    f"[bidking] 无法创建棋盘快照所在目录（请检查路径与权限）: {snap_parent}\n"
                    f"  原因: {exc}",
                    file=sys.stderr,
                )
        self._snapshot_export_overlay = bool(snapshot_export_overlay)
        self._skill_logs: List[dict] = []
        self._last_raw_pricing: Optional[Dict[str, Any]] = None
        # 与顶栏「全红/全橙/金红/最低」悬浮提示同步的最近一次 pricing 字典
        self._last_pricing_for_tooltips: Optional[Dict[str, Any]] = None
        # 顶栏「推荐出价」：与 ``pricing.compute_price`` 最近一次结果同步
        self._last_compute_price: Optional[int] = None
        self._last_compute_payload: Optional[Dict[str, Any]] = None
        self._header_compute_sig: Optional[Tuple[Any, ...]] = None
        # 地图类别权重入口：category tag -> multiplier，默认由 item_db 使用 1.0。
        self._map_category_weights = map_category_weights
        self._home_shell: Optional[tk.Tk] = home_shell

        # 实时 tail：关闭画板或返回主页时置位，供后台线程退出
        self._monitor_stop = threading.Event()

        # 快照回放模式（静态逐回合浏览）；每项第三段为截至该点的 skill_logs（与实时 tail 同源）
        self._snapshots: Optional[List[Tuple[str, GameState, List[dict]]]] = None
        self._snap_idx: int = 0
        if snapshots:
            norm: List[Tuple[str, GameState, List[dict]]] = []
            for row in snapshots:
                if isinstance(row, tuple) and len(row) == 3:
                    lab, st, logs = row  # type: ignore[misc]
                    norm.append((lab, st, list(logs) if isinstance(logs, list) else []))
                elif isinstance(row, tuple) and len(row) == 2:
                    lab, st = row  # type: ignore[misc]
                    norm.append((lab, st, []))
                else:
                    continue
            self._snapshots = norm
            self.state = norm[0][1]
            self._skill_logs = list(norm[0][2])

        # 手动尺寸覆盖：uid → (w, h, display_col, display_row)
        # display_col/row 是用户设定的显示左上角；BoxId 必须在矩形内
        # log 确认形状后自动清除；phantom 项也放在这里
        self._manual_shapes: Dict[str, Tuple[int, int, int, int]] = {}
        # 推算轮廓（与快照 grid_overlay.infer_shapes 同源）；手动画框优先覆盖
        self._infer_shapes: Dict[str, Tuple[int, int, int, int]] = {}
        # 最近一次点击「扩展日志物品」之前的 _manual_shapes 快照（用于一键还原）
        self._manual_shapes_restore_backup: Optional[
            Dict[str, Tuple[int, int, int, int]]
        ] = None
        # 缩放把手拖动状态
        self._drag_state: Optional[dict] = None
        # _draw() 期间的占位格缓存（单次绘制内复用，避免重复构建）
        self._occupied_for_draw: Optional[set] = None
        # _compute_max_size 重入栈：打破「effective_shape → 手动确认候选 → max_size → build_occupied」互递归
        self._compute_max_size_stack: List[str] = []
        # 用户右键手动剔除的空置候选格 (row,col)，不计入空置数、不画橘红（与扩展剩余格一致）
        self._vacant_manual_suppress: Set[Tuple[int, int]] = set()
        # 疑似诈骗格集合缓存：(limit, id(occupied)) → 避免同一 occupied 对象上重复全表扫描
        self._empty_zone_fraud_memo: Optional[Tuple[int, int]] = None
        self._empty_zone_fraud_cells: Set[Tuple[int, int]] = set()

        # 手动画框的幽灵物品：uid(phantom_N) → ItemKnowledge
        self._phantom_items: Dict[str, ItemKnowledge] = {}
        # 幽灵品质偏好：无键=金默认（Q5）；PHANTOM_Q_INFER=原推断；否则为显式 Q1–Q6
        self._phantom_quality_pref: Dict[str, Union[int, str]] = {}
        # 日志物品品质未知（非幽灵）：手选 Q1–Q6 筛选候选；无键=不限品质
        self._unknown_cell_quality_pref: Dict[str, int] = {}
        self._phantom_counter: int = 0
        # 当前正在拖拽画框的状态：
        #   start_row/col, cur_row/col, button(1|3), default_quality(None=金默认Q5, 6=红)
        #   phantom_infer: 左键空格=普通(推断)；Ctrl+左键空格=金；Ctrl+右键空格=红（button 3）
        self._phantom_draw_state: Optional[dict] = None
        self._topmost_pinned: bool = False
        self._topmost_pin_photo: Optional[Any] = None

        # 线程安全：后台线程写 state，主线程读 state；用 RLock 以便在持锁的 poll 路径内可再入 _refresh→写快照
        self._lock: threading.RLock = threading.RLock()
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        # 'update' = 普通刷新, 'new_game' = 新对局（需重置整个界面）
        self._live_game_active: bool = bool(state.uid)

        self._recalc_vis_rows()
        self._build_window()

        if log_path and not snapshots:
            self._start_live_monitor()
            self.root.after(300, self._poll_updates)

    # ── 行数计算 ──────────────────────────────────────────────────────────

    def _recalc_vis_rows(self) -> None:
        """网格固定为 10x30；Canvas 视口只显示前 10 行，通过滚动查看其余行。"""
        self.vis_rows = GRID_ROWS

    def _board_mode_title_suffix(self) -> str:
        return " [拉文看板]" if self._board_mode == BOARD_MODE_RAVEN else ""

    def _board_mode_info_suffix(self) -> str:
        """状态栏补充：拉文铺板顺序提示。"""
        if self._board_mode != BOARD_MODE_RAVEN:
            return ""
        return (
            "   [拉文] 铺板建议：左键/Ctrl 幽灵操作见图例；"
            "「扩展日志物品」顺序：绿蓝→金→灰紫/未知→红，同增益按形状边际概率优先"
        )

    def _vacant_scan_context_snapshot(self) -> dict:
        """供空置/诈骗格判断：含 ``scan_history`` 与 ``raw_pricing``（200009 总格数仅来自后者）。"""
        rp = self._last_raw_pricing
        if rp is None:
            rp = build_raw_pricing_dict(
                map_id=int(self.state.map_id or 0),
                skill_logs=list(self._skill_logs),
                snapshot_path_hint=self._snapshot_path,
            )
        return {
            "game_state": game_state_to_json(self.state),
            "raw_pricing": rp,
        }

    # ── 形状解析 ──────────────────────────────────────────────────────────

    @staticmethod
    def _shape_wh(shape: Optional[int]) -> Tuple[int, int]:
        """ItemSlotType → (列宽 w, 行高 h)，无形状信息默认 1×1。"""
        if shape is None:
            return 1, 1
        s = str(shape)
        if len(s) == 2:
            return int(s[0]), int(s[1])
        return 1, 1

    # ── 尺寸推断辅助 ──────────────────────────────────────────────────────

    def _effective_shape_wh(
        self,
        uid: str,
        k: ItemKnowledge,
        *,
        with_infer: bool = True,
    ) -> Tuple[int, int]:
        """返回物品的有效 (w, h)：log 形状 → 手动画框 → 推算框 → 手动确认候选 → 默认 1×1。"""
        if k.shape is not None:
            return self._shape_wh(k.shape)
        if uid in self._manual_shapes:
            w, h, _, _ = self._manual_shapes[uid]
            return w, h
        if with_infer and uid in self._infer_shapes:
            w, h, _, _ = self._infer_shapes[uid]
            return w, h
        manual_item = self._valid_manual_confirm_item(uid, k)
        if manual_item is not None:
            return self._shape_wh(manual_item.shape)
        return (1, 1)

    def _effective_display_origin(
        self,
        uid: str,
        k: ItemKnowledge,
        *,
        with_infer: bool = True,
    ) -> Tuple[int, int]:
        """
        返回物品在网格上显示的左上角 (col, row)。
        有手动覆盖时使用手动值；否则推算框；否则以 BoxId 为 1×1 左上角。
        """
        if uid in self._manual_shapes:
            _, _, dc, dr = self._manual_shapes[uid]
            return dc, dr
        if with_infer and uid in self._infer_shapes:
            _, _, dc, dr = self._infer_shapes[uid]
            return dc, dr
        if k.box_id is None:
            return 0, 0
        return k.box_id % GRID_COLS, k.box_id // GRID_COLS

    def _manual_shapes_merged_for_occupied(
        self,
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """占位用：推算与手动画框合并，手动画框覆盖同 uid 的推算。"""
        out = dict(self._infer_shapes)
        out.update(self._manual_shapes)
        return out

    def _occupied_cells_for_overlay_infer(self) -> Set[Tuple[int, int]]:
        """
        计算 ``infer_shapes`` 时用的占位图：不含推算矩形（避免互依赖），
        仅用户手动画框 + 日志/幽灵真实占位。
        """
        return _grid_overlay.build_occupied_cells(
            items=self.state.items,
            phantom_items=self._phantom_items,
            manual_shapes=self._manual_shapes,
            exclude_uid="",
            item_shape_wh=lambda u, kk: self._effective_shape_wh(
                u, kk, with_infer=False
            ),
            item_origin=lambda u, kk: self._effective_display_origin(
                u, kk, with_infer=False
            ),
        )

    def _sync_infer_shapes_from_analysis(self) -> None:
        """按当前局面刷新 ``_infer_shapes``（与 ``build_grid_overlay_export_dict`` 中 infer 一致）。"""
        rp = build_raw_pricing_dict(
            map_id=int(self.state.map_id or 0),
            skill_logs=list(self._skill_logs),
            snapshot_path_hint=self._snapshot_path,
        )
        self._last_raw_pricing = rp
        occ = self._occupied_cells_for_overlay_infer()
        raw = _grid_overlay.compute_grid_overlay_infer_shapes(
            game_state=self.state,
            manual_shapes=self._manual_shapes,
            occupied_cells=set(occ),
            vacant_manual_suppress=set(self._vacant_manual_suppress),
            max_box_id=max_anchor_box_id_from_overlay_ui(
                self.state.items, self._phantom_items
            ),
            raw_pricing=rp,
        )
        self._infer_shapes = {
            str(uid): (int(t[0]), int(t[1]), int(t[2]), int(t[3]))
            for uid, t in raw.items()
            if len(t) >= 4
        }

    def _build_occupied(self, exclude_uid: str = "") -> set:
        """
        返回所有已确认/手动定位/幽灵物品所占据的格子 (row, col) 集合。
        逻辑在 :func:`grid_overlay.build_occupied_cells`。
        """
        return _grid_overlay.build_occupied_cells(
            items=self.state.items,
            phantom_items=self._phantom_items,
            manual_shapes=self._manual_shapes_merged_for_occupied(),
            exclude_uid=exclude_uid,
            item_shape_wh=lambda u, kk: self._effective_shape_wh(
                u, kk, with_infer=True
            ),
            item_origin=lambda u, kk: self._effective_display_origin(
                u, kk, with_infer=True
            ),
        )

    def _phantom_effective_quality(self, uid: str) -> Optional[int]:
        """幽灵用于筛选的品质：原推断为 None；显式 int；缺省为金 Q5（若扫描已排除 Q5 则不再强套金）。"""
        if uid not in self._phantom_items:
            return None
        k = self._phantom_items[uid]
        ex = k.excluded_qualities or set()
        p = self._phantom_quality_pref.get(uid)
        if p == PHANTOM_Q_INFER:
            return None
        if isinstance(p, int) and 1 <= p <= 6:
            if p in ex:
                return None
            return p
        if 5 in ex:
            return None
        return 5

    def _phantom_pen_theme(self, uid: str) -> str:
        """手画幽灵底色：金笔（缺省/Q5）淡黄，红笔（Q6）粉，其余保持深青。"""
        if uid not in self._phantom_items:
            return "neutral"
        p = self._phantom_quality_pref.get(uid)
        if p == 6:
            return "red"
        if p == PHANTOM_Q_INFER:
            return "neutral"
        if isinstance(p, int) and 1 <= p <= 4:
            return "neutral"
        pk = self._phantom_items[uid]
        if 5 in (pk.excluded_qualities or set()) and p is None:
            return "neutral"
        return "gold"

    def _csv_locked_item_cid(self, k: ItemKnowledge) -> Optional[int]:
        """
        仅当日志已给出精确价（如鉴价/揭晓）时，才把 ItemCid 视为锁定 CSV 唯一行。

        若 HitBox 里常带占位 ItemCid 却无 ItemPrice，仍按「未精确揭示」处理，
        以免封杀多候选与弹窗内手选品质/双击确认。
        """
        cid = k.item_cid
        if cid is None or cid not in self.csv_index:
            return None
        if k.price is None:
            return None
        return cid

    def _unknown_quality_pref_eligible(self, uid: str, k: ItemKnowledge) -> bool:
        """日志物品品质未知时可在候选弹窗手选品质（已精确价锁定 CID 时不适用）。"""
        return (
            k.quality is None
            and uid not in self._phantom_items
            and self._csv_locked_item_cid(k) is None
        )

    @staticmethod
    def _hand_pickable_qualities(k: ItemKnowledge) -> Tuple[int, ...]:
        """弹窗「候选品质」可选 Q1–Q6：须与日志扫描给出的 excluded_qualities 一致。"""
        ex = k.excluded_qualities or set()
        return tuple(q for q in range(1, 7) if q not in ex)

    def _sanitize_unknown_quality_prefs(self) -> None:
        """
        全量品质扫描等会追加 excluded_qualities；若仍保留与排除矛盾的手选品质，
        则候选恒为空。刷新时清掉无效项，避免「选完品质后回放/切回合仍空白」。
        """
        for uid, q in list(self._unknown_cell_quality_pref.items()):
            k = self.state.items.get(uid)
            if not k or not self._unknown_quality_pref_eligible(uid, k):
                self._unknown_cell_quality_pref.pop(uid, None)
                continue
            if not isinstance(q, int) or not (1 <= q <= 6):
                self._unknown_cell_quality_pref.pop(uid, None)
                continue
            if q in (k.excluded_qualities or set()):
                self._unknown_cell_quality_pref.pop(uid, None)

    def _sanitize_phantom_quality_prefs(self) -> None:
        """全量扫描写入 phantoms 的 excluded_qualities 后，清掉与之矛盾的手选品质。"""
        for uid, p in list(self._phantom_quality_pref.items()):
            if p == PHANTOM_Q_INFER:
                continue
            if not isinstance(p, int) or not (1 <= p <= 6):
                self._phantom_quality_pref.pop(uid, None)
                continue
            k = self._phantom_items.get(uid)
            if not k or p in (k.excluded_qualities or set()):
                self._phantom_quality_pref.pop(uid, None)

    def _effective_quality_for_query(self, uid: str, k: ItemKnowledge) -> Optional[int]:
        """候选筛选 / query_item 用品质：日志已知品质优先，其次幽灵金默认/手选。"""
        if k.quality is not None:
            return k.quality
        if uid in self._phantom_items:
            return self._phantom_effective_quality(uid)
        if self._unknown_quality_pref_eligible(uid, k):
            q = self._unknown_cell_quality_pref.get(uid)
            if isinstance(q, int) and 1 <= q <= 6:
                if q in (k.excluded_qualities or set()):
                    return None
                return q
        return None

    @staticmethod
    def _rect_cells(row: int, col: int, w: int, h: int) -> set:
        """返回矩形覆盖的所有格子坐标 (row, col)。"""
        return {(row + ddr, col + ddc) for ddr in range(h) for ddc in range(w)}

    def _rect_overlaps_occupied(
        self,
        row: int,
        col: int,
        w: int,
        h: int,
        exclude_uid: str = "",
    ) -> bool:
        """检查指定矩形是否覆盖已有可靠物品或幽灵物品。"""
        if row < 0 or col < 0 or w <= 0 or h <= 0:
            return True
        if col + w > GRID_COLS or row + h > GRID_ROWS:
            return True
        occupied = self._build_occupied(exclude_uid=exclude_uid)
        return any(cell in occupied for cell in self._rect_cells(row, col, w, h))

    def _query_item_for_grid(
        self,
        uid: str,
        k: ItemKnowledge,
    ) -> Tuple[Optional[CsvItem], int, bool, Optional[float], str]:
        """按当前网格显示约束查询候选，包含手动尺寸、幽灵框和最大尺寸推断。"""
        manual_item = self._valid_manual_confirm_item(uid, k)
        if manual_item is not None:
            return manual_item, 1, True, float(manual_item.base_value), "手动确认"

        effective_shape = k.shape
        max_shape: Optional[Tuple[int, int]] = None

        if k.shape is None:
            if uid in self._manual_shapes:
                mw, mh, _, _ = self._manual_shapes[uid]
                effective_shape = mw * 10 + mh
            elif uid in self._infer_shapes:
                iw, ih, _, _ = self._infer_shapes[uid]
                effective_shape = iw * 10 + ih
            elif k.box_id is not None:
                max_w, max_h = self._compute_max_size(uid, k)
                if max_w < GRID_COLS or max_h < GRID_ROWS:
                    max_shape = (max_w, max_h)

        return query_item(
            effective_shape,
            self._effective_quality_for_query(uid, k),
            k.categories,
            self._csv_locked_item_cid(k),
            self.csv_index,
            self.csv_items,
            k.excluded_categories,
            k.excluded_qualities,
            max_shape_wh=max_shape,
            map_category_weights=self._map_category_weights,
            map_id=self.state.map_id,
        )

    def _valid_manual_confirm_item(
        self, uid: str, k: ItemKnowledge
    ) -> Optional[CsvItem]:
        """
        返回当前仍然有效的手动确认候选；若已与新约束冲突会自动撤销。
        冲突判定基于当前网格约束筛出的候选集合。
        """
        cid = k.manual_confirm_item_id
        if not cid:
            return None
        item = self.csv_index.get(cid)
        if item is None:
            k.manual_confirm_item_id = None
            return None
        candidates = self._candidate_items_for_grid(uid, k)
        if any(c.item_id == cid for c in candidates):
            return item
        k.manual_confirm_item_id = None
        return None

    def _candidate_items_for_grid(self, uid: str, k: ItemKnowledge) -> List[CsvItem]:
        """返回与当前网格约束一致的候选物品列表。"""
        locked = self._csv_locked_item_cid(k)
        if locked is not None:
            return [self.csv_index[locked]]

        candidates = list(self.csv_items)
        if k.shape is not None:
            candidates = [i for i in candidates if i.shape == k.shape]
        elif uid in self._manual_shapes:
            mw, mh, _, _ = self._manual_shapes[uid]
            virtual_shape = mw * 10 + mh
            candidates = [i for i in candidates if i.shape == virtual_shape]
        elif uid in self._infer_shapes:
            iw, ih, _, _ = self._infer_shapes[uid]
            virtual_shape = iw * 10 + ih
            candidates = [i for i in candidates if i.shape == virtual_shape]
        elif k.box_id is not None:
            max_w, max_h = self._compute_max_size(uid, k)
            if max_w < GRID_COLS or max_h < GRID_ROWS:

                def _shape_fits(shape: int) -> bool:
                    ss = str(shape)
                    if len(ss) == 2:
                        return int(ss[0]) <= max_w and int(ss[1]) <= max_h
                    return False

                candidates = [i for i in candidates if _shape_fits(i.shape)]

        eq = self._effective_quality_for_query(uid, k)
        if eq is not None:
            candidates = [i for i in candidates if i.quality == eq]
        if k.excluded_qualities:
            candidates = [
                i for i in candidates if i.quality not in k.excluded_qualities
            ]
        if k.categories:
            with_cat = [
                i for i in candidates if all(c in i.category_tags for c in k.categories)
            ]
            if with_cat:
                candidates = with_cat
        if k.excluded_categories:
            candidates = [
                i
                for i in candidates
                if not any(c in k.excluded_categories for c in i.category_tags)
            ]
        return candidates

    def _candidate_items_without_manual_shape_lock(
        self, uid: str, k: ItemKnowledge
    ) -> List[CsvItem]:
        """
        与 _candidate_items_for_grid 相同的品质/类别/排除约束，
        但不按当前手动矩形过滤 shape；仅用日志形状或 BoxId 推断的最大外形包络。
        用于拉文扩展时按「候选中形状的边际概率」比较不同矩形。
        """
        locked = self._csv_locked_item_cid(k)
        if locked is not None:
            return [self.csv_index[locked]]

        candidates = list(self.csv_items)
        if k.shape is not None:
            candidates = [i for i in candidates if i.shape == k.shape]
        elif k.box_id is not None:
            max_w, max_h = self._compute_max_size(uid, k)
            if max_w < GRID_COLS or max_h < GRID_ROWS:

                def _shape_fits(shape: int) -> bool:
                    ss = str(shape)
                    if len(ss) == 2:
                        return int(ss[0]) <= max_w and int(ss[1]) <= max_h
                    return False

                candidates = [i for i in candidates if _shape_fits(i.shape)]

        eq = self._effective_quality_for_query(uid, k)
        if eq is not None:
            candidates = [i for i in candidates if i.quality == eq]
        if k.excluded_qualities:
            candidates = [
                i for i in candidates if i.quality not in k.excluded_qualities
            ]
        if k.categories:
            with_cat = [
                i for i in candidates if all(c in i.category_tags for c in k.categories)
            ]
            if with_cat:
                candidates = with_cat
        if k.excluded_categories:
            candidates = [
                i
                for i in candidates
                if not any(c in k.excluded_categories for c in i.category_tags)
            ]
        return candidates

    def _marginal_shape_probability_mass(
        self,
        uid: str,
        k: ItemKnowledge,
        w: int,
        h: int,
    ) -> float:
        """候选（未锁手动外形）中 ItemSlotType=w×h 的归一化概率质量之和。"""
        if not (1 <= w <= 9 and 1 <= h <= 9):
            return 0.0
        vs = w * 10 + h
        loose = self._candidate_items_without_manual_shape_lock(uid, k)
        if not loose:
            return 0.0
        probs = candidate_probabilities(
            loose,
            self._map_category_weights,
            self.state.map_id,
        )
        return sum(probs.get(c.item_id, 0.0) for c in loose if c.shape == vs)

    def _display_quality(self, uid: str, k: ItemKnowledge) -> Optional[int]:
        """返回用于显示的品质；候选品质唯一时也补齐显示颜色。"""
        manual_item = self._valid_manual_confirm_item(uid, k)
        if manual_item is not None:
            return manual_item.quality
        if k.quality is not None:
            return k.quality
        if uid in self._phantom_items:
            p = self._phantom_quality_pref.get(uid)
            if p == PHANTOM_Q_INFER:
                pass
            elif isinstance(p, int) and 1 <= p <= 6:
                return p
            else:
                return 5
        if self._unknown_quality_pref_eligible(uid, k):
            uq = self._unknown_cell_quality_pref.get(uid)
            if isinstance(uq, int) and 1 <= uq <= 6:
                return uq
        candidates = self._candidate_items_for_grid(uid, k)
        qualities = {item.quality for item in candidates}
        if len(qualities) == 1:
            return next(iter(qualities))
        best, _count, unique, _est, _label = self._query_item_for_grid(uid, k)
        if unique and best is not None:
            return best.quality
        return None

    def _display_price_value(self, uid: str, k: ItemKnowledge) -> Optional[float]:
        """返回当前格子的精确价或期望价（与合并 ``items`` + ``grid_overlay`` 后的定价一致）。"""
        return estimate_snapshot_item_price_for_uid(self._make_board_snapshot(), uid)

    def _info_summary_text(self) -> str:
        """顶部状态栏：物品总格数、画版总格数（含空置）、均格；橙/红（含手画）。"""
        total_cells = 0
        item_count = 0
        q5_count = 0
        q6_count = 0
        q5_cells = 0
        q6_cells = 0
        unknown_cells = 0

        def _accum_orange_red(uid: str, k: ItemKnowledge, q: Optional[int]) -> None:
            nonlocal total_cells, item_count, q5_count, q6_count, q5_cells, q6_cells, unknown_cells
            if k.box_id is None:
                return
            w, h = self._effective_shape_wh(uid, k)
            cells = w * h
            total_cells += cells
            item_count += 1
            if q == 5:
                q5_count += 1
                q5_cells += cells
            elif q == 6:
                q6_count += 1
                q6_cells += cells
            elif q is None:
                unknown_cells += cells

        for uid, k in self.state.items.items():
            _accum_orange_red(uid, k, self._display_quality(uid, k))

        for uid, k in self._phantom_items.items():
            q_stat: Optional[int]
            manual_item = self._valid_manual_confirm_item(uid, k)
            if manual_item is not None:
                q_stat = manual_item.quality
            elif k.quality is not None:
                q_stat = k.quality
            else:
                p = self._phantom_quality_pref.get(uid)
                if p == PHANTOM_Q_INFER:
                    q_stat = self._display_quality(uid, k)
                elif isinstance(p, int) and 1 <= p <= 6:
                    q_stat = p
                else:
                    q_stat = 5
            _accum_orange_red(uid, k, q_stat)

        avg_cells = total_cells / item_count if item_count else 0.0
        empty_zone = self._compute_empty_zone_count()
        vacant_slots = empty_zone if empty_zone is not None else 0
        board_cells = total_cells + vacant_slots
        top_cats = ""
        category_ratios = map_category_ratios(self.state.map_id)
        if not category_ratios and self._map_category_weights:
            # 回退：若没有地图根图数据，则使用传入的类别倍率入口。
            total_weight = sum(w for w in self._map_category_weights.values() if w > 0)
            if total_weight > 0:
                category_ratios = {
                    cid: w / total_weight
                    for cid, w in self._map_category_weights.items()
                    if w > 0
                }
        if category_ratios:
            ranked = sorted(
                category_ratios.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            top_parts: List[str] = []
            for cid, ratio in ranked[:3]:
                pct = ratio * 100.0
                cat_short = _CAT_SHORT.get(cid, CATEGORY_NAMES.get(cid, str(cid))[:2])
                top_parts.append(f"{cat_short}{pct:.0f}%")
            top_cats = "   类别TOP3: " + " / ".join(top_parts)
        return (
            f"地图: {self.state.map_id}   第 {self.state.current_round} 回合   "
            f"已知物品: {len(self.state.items)} 件   "
            f"当前物品总格数: {total_cells}   "
            f"当前画版格数: {board_cells}   "
            f"平均格数: {avg_cells:.2f}   "
            f"橙（含手画）: {q5_count} 件 {q5_cells}格   "
            f"红（含手画）: {q6_count} 件 {q6_cells}格   "
            f"未知: {unknown_cells}格"
            f"{top_cats}"
            f"{self._board_mode_info_suffix()}"
        )

    def _exclude_from_empty_zone_estimate(
        self,
        row: int,
        col: int,
        occupied: set,
        max_box_id: int,
        *,
        apply_fraud_filter: bool = True,
    ) -> bool:
        """
        疑似诈骗空格：仅在 ``apply_fraud_filter`` 为真时生效；用于自动空置计数与橘红层。
        手动右键剔除/恢复空置**不**调用本过滤（见 ``_cell_is_vacant_manual_suppress_eligible``）。
        """
        if not apply_fraud_filter:
            return False
        if (row, col) in occupied:
            return False
        limit = min(max_box_id, GRID_COLS * GRID_ROWS - 1)
        bid = row * GRID_COLS + col
        if bid > limit:
            return False
        memo_key = (limit, id(occupied))
        if self._empty_zone_fraud_memo != memo_key:
            self._empty_zone_fraud_memo = memo_key
            self._empty_zone_fraud_cells = (
                _grid_overlay.fraud_empty_cells_in_zone_prefix(occupied, limit)
            )
        return (row, col) in self._empty_zone_fraud_cells

    def _cell_is_vacant_manual_suppress_eligible(self, row: int, col: int) -> bool:
        """是否为「空置候选」格：可右键手动剔除/恢复；不受诈骗格规则限制。"""
        max_box_id = self._empty_zone_max_box_id()
        if max_box_id < 0:
            return False
        limit = min(max_box_id, GRID_COLS * GRID_ROWS - 1)
        if row * GRID_COLS + col > limit:
            return False
        occupied = self._build_occupied()
        if (row, col) in occupied:
            return False
        return True

    def _toggle_vacant_manual_suppress(self, row: int, col: int) -> None:
        """空格普通右键：切换「手动剔除空置」；已剔除则恢复。"""
        key = (row, col)
        if key in self._vacant_manual_suppress:
            self._vacant_manual_suppress.discard(key)
            self._refresh()
            return
        if self._cell_is_vacant_manual_suppress_eligible(row, col):
            self._vacant_manual_suppress.add(key)
            self._refresh()

    def _compute_empty_zone_count(self) -> Optional[int]:
        """空置有效格数：算法在 ``analysis.grid_overlay``，此处仅聚合 UI 状态并触发计算。"""
        occupied = (
            self._occupied_for_draw
            if self._occupied_for_draw is not None
            else self._build_occupied()
        )
        d = _grid_overlay.compute_overlay_vacant_dict(
            occupied=occupied,
            max_box_id=self._empty_zone_max_box_id(),
            vacant_manual_suppress=set(self._vacant_manual_suppress),
            board_snapshot=self._vacant_scan_context_snapshot(),
        )
        return d.get("effective_count")

    def _create_phantom(
        self,
        row: int,
        col: int,
        w: int,
        h: int,
        default_phantom_quality: Optional[int] = None,
        use_infer_quality: bool = False,
    ) -> bool:
        """在 (row, col) 以 (w, h) 大小创建一个幽灵物品，并应用当前扫描历史约束。"""
        if self._rect_overlaps_occupied(row, col, w, h):
            return False
        phid = f"phantom_{self._phantom_counter}"
        self._phantom_counter += 1
        pk = ItemKnowledge(uid=phid)
        pk.box_id = row * GRID_COLS + col
        pk.box_id_confirmed = True  # 用户明确指定了位置
        self._phantom_items[phid] = pk
        self._manual_shapes[phid] = (w, h, col, row)
        if use_infer_quality:
            self._phantom_quality_pref[phid] = PHANTOM_Q_INFER
        elif default_phantom_quality == 6:
            self._phantom_quality_pref[phid] = 6
        elif default_phantom_quality is not None and 1 <= default_phantom_quality <= 5:
            self._phantom_quality_pref[phid] = default_phantom_quality
        apply_scan_history_to_phantom_items(self._phantom_items, self.state)
        return True

    def _vacant_remaining_for_expand(self) -> Tuple[Optional[set], str]:
        """
        与橘红空置区一致：从 BoxId=0 到「最大锚格 BoxId」之间的未占位格（含未确认日志锚格；无锚时默认 30）。
        """
        max_box_id = self._empty_zone_max_box_id()
        if max_box_id < 0:
            return None, "无法划定空置区域上界。"
        occupied = self._build_occupied()
        limit = min(max_box_id, GRID_COLS * GRID_ROWS - 1)
        apply_fraud = _grid_overlay.fraud_zone_cell_exclusion_enabled(
            self._vacant_scan_context_snapshot(),
            occupied,
            limit,
        )
        remaining: set = set()
        for bid in range(limit + 1):
            r, c = bid // GRID_COLS, bid % GRID_COLS
            if (r, c) not in occupied:
                if (r, c) in self._vacant_manual_suppress:
                    continue
                if self._exclude_from_empty_zone_estimate(
                    r,
                    c,
                    occupied,
                    limit,
                    apply_fraud_filter=apply_fraud,
                ):
                    continue
                remaining.add((r, c))
        return remaining, ""

    def _expand_rect_collides_others(
        self,
        dr: int,
        dc: int,
        w: int,
        h: int,
        exclude_uid: str,
    ) -> bool:
        occ = self._build_occupied(exclude_uid=exclude_uid)
        return any(cell in occ for cell in self._rect_cells(dr, dc, w, h))

    def _current_item_manual_rect(
        self, uid: str, k: ItemKnowledge
    ) -> Tuple[int, int, int, int]:
        """当前显示用的 (w,h,dc,dr)；手动画框 → 推算框 → 否则按 BoxId 作 1×1 左上角。"""
        if uid in self._manual_shapes:
            return self._manual_shapes[uid]
        if uid in self._infer_shapes:
            return self._infer_shapes[uid]
        bc = k.box_id % GRID_COLS
        br = k.box_id // GRID_COLS
        return (1, 1, bc, br)

    def _probe_log_item_manual_shape(
        self,
        uid: str,
        k: ItemKnowledge,
        dc: int,
        dr: int,
        w: int,
        h: int,
    ) -> int:
        """临时写入手动矩形并测候选数，调用前后恢复原状。"""
        prev = self._manual_shapes.get(uid)
        self._manual_shapes[uid] = (w, h, dc, dr)
        try:
            return len(self._candidate_items_for_grid(uid, k))
        finally:
            if prev is None:
                self._manual_shapes.pop(uid, None)
            else:
                self._manual_shapes[uid] = prev

    def _expandable_log_items_by_phase(
        self,
    ) -> Tuple[
        List[Tuple[str, ItemKnowledge]],
        List[Tuple[str, ItemKnowledge]],
        List[Tuple[str, ItemKnowledge]],
    ]:
        """
        仅日志物品、且轮廓未由日志锁死 (shape is None) 的可调项。
        艾莎看板：非金红（含未知）→ 金 → 红；不创建新 UID。
        """
        p1: List[Tuple[str, ItemKnowledge]] = []
        p2: List[Tuple[str, ItemKnowledge]] = []
        p3: List[Tuple[str, ItemKnowledge]] = []
        for uid, k in self.state.items.items():
            if uid in self._phantom_items:
                continue
            if k.shape is not None:
                continue
            if k.box_id is None:
                continue
            if k.manual_confirm_item_id:
                continue
            q = k.quality
            if q in (1, 2, 3, 4) or q is None:
                p1.append((uid, k))
            elif q == 5:
                p2.append((uid, k))
            elif q == 6:
                p3.append((uid, k))
        return p1, p2, p3

    def _expandable_log_items_by_phase_raven(
        self,
    ) -> Tuple[
        List[Tuple[str, ItemKnowledge]],
        List[Tuple[str, ItemKnowledge]],
        List[Tuple[str, ItemKnowledge]],
        List[Tuple[str, ItemKnowledge]],
    ]:
        """
        拉文「扩展日志物品」专用阶段：绿/蓝 → 金 → 普通（灰、紫、品质未知）→ 红。
        """
        p_gb: List[Tuple[str, ItemKnowledge]] = []
        p_gold: List[Tuple[str, ItemKnowledge]] = []
        p_norm: List[Tuple[str, ItemKnowledge]] = []
        p_red: List[Tuple[str, ItemKnowledge]] = []
        for uid, k in self.state.items.items():
            if uid in self._phantom_items:
                continue
            if k.shape is not None:
                continue
            if k.box_id is None:
                continue
            if k.manual_confirm_item_id:
                continue
            q = k.quality
            if q in (2, 3):
                p_gb.append((uid, k))
            elif q == 5:
                p_gold.append((uid, k))
            elif q in (1, 4) or q is None:
                p_norm.append((uid, k))
            elif q == 6:
                p_red.append((uid, k))
        return p_gb, p_gold, p_norm, p_red

    def _pick_best_log_expansion(
        self,
        phase: List[Tuple[str, ItemKnowledge]],
        remaining: set,
        use_shape_probability: bool = False,
    ) -> Optional[Tuple[str, ItemKnowledge, int, int, int, int, set]]:
        """
        本阶段内选一物品与其新矩形：新增格尽量多且候选非空。
        拉文看板在同增益下优先候选中形状的边际概率（candidate_probabilities），再大者优先面积。
        返回 (uid, k, dc, dr, w, h, extra_cells)。
        """
        best_key: Optional[Tuple[float, ...]] = None
        best_payload: Optional[Tuple[str, ItemKnowledge, int, int, int, int, set]] = (
            None
        )
        for uid, k in phase:
            ow, oh, odc, odr = self._current_item_manual_rect(uid, k)
            old_cells = self._rect_cells(odr, odc, ow, oh)
            brow, bcol = k.box_id // GRID_COLS, k.box_id % GRID_COLS
            for ndr in range(odr + 1):
                for ndc in range(odc + 1):
                    min_w = odc + ow - ndc
                    min_h = odr + oh - ndr
                    if min_w < 1 or min_h < 1:
                        continue
                    max_nw = min(GRID_COLS - ndc, 9)
                    max_nh = min(GRID_ROWS - ndr, 9)
                    for nw in range(min_w, max_nw + 1):
                        for nh in range(min_h, max_nh + 1):
                            if not (ndr <= brow < ndr + nh and ndc <= bcol < ndc + nw):
                                continue
                            ncells = self._rect_cells(ndr, ndc, nw, nh)
                            if not old_cells <= ncells:
                                continue
                            extra = ncells - old_cells
                            if not extra or not extra <= remaining:
                                continue
                            if self._expand_rect_collides_others(
                                ndr, ndc, nw, nh, exclude_uid=uid
                            ):
                                continue
                            if (
                                self._probe_log_item_manual_shape(
                                    uid, k, ndc, ndr, nw, nh
                                )
                                <= 0
                            ):
                                continue
                            gain = len(extra)
                            area = nw * nh
                            shape_mass = (
                                self._marginal_shape_probability_mass(uid, k, nw, nh)
                                if use_shape_probability
                                else 0.0
                            )
                            key: Tuple[float, ...] = (
                                (float(gain), shape_mass, float(area))
                                if use_shape_probability
                                else (float(gain), float(area))
                            )
                            if best_key is None or key > best_key:
                                best_key = key
                                best_payload = (uid, k, ndc, ndr, nw, nh, extra)
        if best_payload is None:
            return None
        uid, k, dc, dr, w, h, extra = best_payload
        return (uid, k, dc, dr, w, h, extra)

    def _expand_log_items_into_vacant(self) -> Tuple[int, int]:
        """
        仅用已有日志物品的「手动轮廓」向空置区扩展，不新增幽灵、不新增物品。
        艾莎：非金红（含未知）→ 金 → 红。
        拉文：绿/蓝 → 金 → 普通（灰、紫、未知）→ 红；同增益按候选形状边际概率优先。
        返回 (成功扩展步数, 仍空余格数)。
        """
        self._manual_shapes_restore_backup = dict(self._manual_shapes)
        remaining, err = self._vacant_remaining_for_expand()
        if remaining is None:
            messagebox.showinfo("扩展日志物品", err)
            return 0, 0
        if not remaining:
            messagebox.showinfo("扩展日志物品", "空置区域内已无空格。")
            return 0, 0

        use_sp = self._board_mode == BOARD_MODE_RAVEN
        if use_sp:
            phases = self._expandable_log_items_by_phase_raven()
            has_any = any(phases)
        else:
            p1, p2, p3 = self._expandable_log_items_by_phase()
            phases = (p1, p2, p3)
            has_any = bool(p1 or p2 or p3)

        if not has_any:
            messagebox.showinfo(
                "扩展日志物品",
                "没有可调物品：需要日志中轮廓未锁定（无 ItemSlotType）且未手动确认唯一候选的物品。",
            )
            return 0, len(remaining)

        steps = 0
        for phase in phases:
            if not phase:
                continue
            guard = 0
            while remaining and guard < 800:
                guard += 1
                picked = self._pick_best_log_expansion(
                    phase,
                    remaining,
                    use_shape_probability=use_sp,
                )
                if picked is None:
                    break
                uid, _k, dc, dr, w, h, extra = picked
                self._manual_shapes[uid] = (w, h, dc, dr)
                remaining -= extra
                steps += 1

        leftover = len(remaining)
        if steps == 0 and leftover > 0:
            messagebox.showinfo(
                "扩展日志物品",
                f"未能扩展任何物品（候选为空或与占位冲突）。仍剩 {leftover} 格。",
            )
        elif leftover > 0:
            messagebox.showinfo(
                "扩展日志物品",
                f"已扩展 {steps} 步；仍有 {leftover} 格空置（可调物品无法再合法变大）。",
            )
        else:
            messagebox.showinfo(
                "扩展日志物品",
                f"已扩展 {steps} 步，空置区域已由日志物品轮廓铺满。",
            )
        return steps, leftover

    def _on_expand_log_items_into_vacant(self) -> None:
        self._expand_log_items_into_vacant()
        self._refresh()

    def _on_restore_manual_shapes(self) -> None:
        """恢复到最近一次点击「扩展日志物品」之前保存的手动轮廓（含幽灵画框尺寸）。"""
        bak = self._manual_shapes_restore_backup
        if bak is None:
            messagebox.showinfo(
                "还原轮廓",
                "尚无备份：请先点击一次「扩展日志物品」（会在执行前自动保存当前轮廓）。",
            )
            return
        self._manual_shapes = dict(bak)
        self._refresh()

    def _compute_max_size(self, uid: str, k: ItemKnowledge) -> Tuple[int, int]:
        """
        推断物品最大可能尺寸 (w, h)，以 BoxId 所在格为锚点，
        向四个方向扫描空闲格子后取上界（不考虑矩形性约束，为保守上界）。
        """
        if k.box_id is None:
            return GRID_COLS, GRID_ROWS
        # 已在栈中说明存在 A↔B 互递归；返回满格尺寸使下游「按 max 筛形状」分支关闭，避免无限递归。
        if uid in self._compute_max_size_stack:
            return GRID_COLS, GRID_ROWS
        self._compute_max_size_stack.append(uid)
        try:
            return self._compute_max_size_impl(uid, k)
        finally:
            if self._compute_max_size_stack and self._compute_max_size_stack[-1] == uid:
                self._compute_max_size_stack.pop()

    def _compute_max_size_impl(self, uid: str, k: ItemKnowledge) -> Tuple[int, int]:
        brow = k.box_id // GRID_COLS
        bcol = k.box_id % GRID_COLS

        # 复用或重建占位图（排除自身）
        if self._occupied_for_draw is not None:
            dc0, dr0 = self._effective_display_origin(uid, k)
            w0, h0 = self._effective_shape_wh(uid, k)
            own = frozenset(
                (dr0 + ddr, dc0 + ddc) for ddr in range(h0) for ddc in range(w0)
            )
            occupied = self._occupied_for_draw - own
        else:
            occupied = self._build_occupied(exclude_uid=uid)

        # 四方向独立扫描（以 BoxId 为锚点）
        def _scan_right() -> int:
            n = 0
            for c in range(bcol, GRID_COLS):
                if (brow, c) in occupied:
                    break
                n += 1
            return n - 1  # 不含 bcol 自身

        def _scan_left() -> int:
            n = 0
            for c in range(bcol, -1, -1):
                if (brow, c) in occupied:
                    break
                n += 1
            return n - 1

        def _scan_down() -> int:
            n = 0
            for r in range(brow, GRID_ROWS):
                if (r, bcol) in occupied:
                    break
                n += 1
            return n - 1

        def _scan_up() -> int:
            n = 0
            for r in range(brow, -1, -1):
                if (r, bcol) in occupied:
                    break
                n += 1
            return n - 1

        right_ext = _scan_right()
        left_ext = _scan_left()
        down_ext = _scan_down()
        up_ext = _scan_up()

        max_w = max(1, left_ext + 1 + right_ext)
        max_h = max(1, up_ext + 1 + down_ext)
        return max_w, max_h

    def _empty_zone_max_box_id(self) -> int:
        """橘红空置层与 ``grid_overlay.vacant`` 共用：最大锚格（含未确认日志/幽灵），无锚时默认 30。"""
        return max_anchor_box_id_from_overlay_ui(self.state.items, self._phantom_items)

    # ── Bot 快照 JSON ───────────────────────────────────────────────────────

    def _skill_log_game_data_subset(self, data: dict) -> dict:
        gd = data.get("GameData")
        if not isinstance(gd, dict):
            return {}
        keys = (
            "HeroSkillLog",
            "MapSkillLog",
            "ItemSkillLog",
            "UserLog",
            "Round",
            "Uid",
            "MapId",
        )
        out: dict = {}
        for k in keys:
            if k not in gd:
                continue
            v = gd[k]
            try:
                out[k] = deepcopy(v)
            except Exception:
                out[k] = v
        return out

    def _append_skill_log_entry(self, event_type: str, data: dict) -> None:
        self._skill_logs.append(
            {
                "event_type": event_type,
                "game_data": self._skill_log_game_data_subset(data),
                "received_at_unix": time.time(),
            }
        )

    def _make_board_snapshot(self) -> dict:
        """不含 ``pricing`` 的画板快照：供定价、单件估价与写盘复用。"""
        gs = game_state_to_json(self.state)
        raw_pricing = build_raw_pricing_dict(
            map_id=int(self.state.map_id or 0),
            skill_logs=list(self._skill_logs),
            snapshot_path_hint=self._snapshot_path,
        )
        self._last_raw_pricing = raw_pricing
        occ_infer = self._occupied_cells_for_overlay_infer()
        return {
            "game_state": gs,
            "skill_logs": list(self._skill_logs),
            "current_round": int(self.state.current_round or 1),
            "map_id": int(self.state.map_id or 0),
            "raw_pricing": raw_pricing,
            "grid_overlay": self._grid_overlay_to_json(
                raw_pricing, occupied_cells=occ_infer
            ),
        }

    def _build_pricing_snapshot_dict(self) -> dict:
        return build_snapshot_pricing_dict(
            self._make_board_snapshot(),
            snapshot_path_hint=self._snapshot_path,
        )

    def _grid_overlay_to_json(
        self,
        raw_pricing: Dict[str, Any],
        *,
        occupied_cells: Optional[set] = None,
    ) -> dict:
        if occupied_cells is None:
            occ_for_infer = self._occupied_cells_for_overlay_infer()
        else:
            occ_for_infer = set(occupied_cells)
        export = build_grid_overlay_export_dict(
            game_state=self.state,
            raw_pricing=raw_pricing,
            phantom_items=self._phantom_items,
            manual_shapes=self._manual_shapes,
            phantom_quality_pref=self._phantom_quality_pref,
            unknown_cell_quality_pref=self._unknown_cell_quality_pref,
            vacant_manual_suppress=self._vacant_manual_suppress,
            occupied_cells=occ_for_infer,
            max_box_id=max_anchor_box_id_from_overlay_ui(
                self.state.items, self._phantom_items
            ),
        )
        inf = export.get("infer_shapes") or {}
        self._infer_shapes = {
            str(uid): (int(v[0]), int(v[1]), int(v[2]), int(v[3]))
            for uid, v in inf.items()
            if isinstance(v, (list, tuple)) and len(v) >= 4
        }
        occ_full = self._build_occupied()
        export[_grid_overlay.OCCUPIED_CELL_BIDS] = sorted(
            r * GRID_COLS + c for r, c in occ_full
        )
        vacant_ctx = {
            "game_state": game_state_to_json(self.state),
            "raw_pricing": raw_pricing,
        }
        export["vacant"] = _grid_overlay.compute_overlay_vacant_dict(
            occupied=set(occ_full),
            max_box_id=int(
                max_anchor_box_id_from_overlay_ui(self.state.items, self._phantom_items)
            ),
            vacant_manual_suppress=set(self._vacant_manual_suppress),
            board_snapshot=vacant_ctx,
        )
        return export

    def _emit_board_snapshot_unlocked(self) -> None:
        """调用方须已持有 ``self._lock``（``RLock``，同线程可重入）。"""
        path = self._snapshot_path
        if not path:
            return
        base = self._make_board_snapshot()
        gs = base["game_state"]
        payload = {
            "schema_version": BOARD_SNAPSHOT_SCHEMA_VERSION,
            "written_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "board_mode": self._board_mode,
            "game_uid": gs["uid"],
            "current_round": gs["current_round"],
            "game_state": gs,
            "skill_logs": list(self._skill_logs),
            "raw_pricing": base["raw_pricing"],
            "pricing": build_snapshot_pricing_dict(
                base,
                snapshot_path_hint=self._snapshot_path,
            ),
        }
        go = base.get("grid_overlay") or {}
        if self._snapshot_export_overlay:
            payload["grid_overlay"] = go
        else:
            v = go.get("vacant")
            if v is not None:
                payload["grid_overlay"] = {"vacant": v}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        tmp_path = path + ".tmp"
        try:
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as wf:
                wf.write(text)
            os.replace(tmp_path, path)
        except OSError:
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # ── 实时监听 ──────────────────────────────────────────────────────────

    def _start_live_monitor(self) -> None:
        """启动后台 daemon 线程，从日志文件当前末尾开始 tail。"""
        t = threading.Thread(target=self._monitor_thread, daemon=True, name="log-tail")
        t.start()

    def _monitor_thread(self) -> None:
        """
        后台线程：从文件 EOF 开始监听新增行，解析事件并更新 self.state。
        状态修改均在 self._lock 保护下进行；事件信号写入 self._queue。
        """
        silent = io.StringIO()
        with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # 直接跳到文件末尾，只处理新增内容
            while True:
                if self._monitor_stop.is_set():
                    return
                line = f.readline()
                if not line:
                    time.sleep(0.3)
                    continue
                result = extract_event(line)
                if not result:
                    continue
                event_type, data = result

                with self._lock:
                    if event_type == "S2C_33_game_start_notify":
                        self.state = GameState()
                        self._live_game_active = True
                        self._skill_logs.clear()
                        self._last_raw_pricing = None
                        handle_s2c33(
                            data, self.state, self.csv_index, self.csv_items, silent
                        )
                        self._append_skill_log_entry(event_type, data)
                        self._queue.put("new_game")

                    elif (
                        event_type == "S2C_37_game_next_round_notify"
                        and self._live_game_active
                    ):
                        handle_s2c37(
                            data, self.state, self.csv_index, self.csv_items, silent
                        )
                        self._append_skill_log_entry(event_type, data)
                        self._queue.put("update")

                    elif (
                        event_type == "S2C_39_game_use_item" and self._live_game_active
                    ):
                        handle_s2c39(
                            data, self.state, self.csv_index, self.csv_items, silent
                        )
                        self._append_skill_log_entry(event_type, data)
                        self._queue.put("update")

                    elif (
                        event_type == "S2C_45_game_over_notify"
                        and self._live_game_active
                    ):
                        handle_s2c45(
                            data,
                            self.state,
                            self.csv_index,
                            self.csv_items,
                            silent,
                            write_game_report_csv=True,
                        )
                        self._append_skill_log_entry(event_type, data)
                        self._live_game_active = False
                        self._queue.put("update")

    def _poll_updates(self) -> None:
        """
        主线程定时任务（每 300ms）：消费队列中的信号并按需刷新 UI。
        多个信号合并为一次绘制，避免短时间内多次重绘。
        """
        if self._monitor_stop.is_set():
            return
        needs_redraw = False
        is_new_game = False
        try:
            while True:
                msg = self._queue.get_nowait()
                needs_redraw = True
                if msg == "new_game":
                    is_new_game = True
        except queue.Empty:
            pass

        if needs_redraw:
            with self._lock:
                self._recalc_vis_rows()
                if is_new_game:
                    sp = self._snapshot_path
                    if sp:
                        _archive_board_snapshot_then_unlink(sp)
                    self._reset_for_new_game()
                else:
                    self._refresh()

        # 继续调度下一次轮询
        if not self._monitor_stop.is_set():
            try:
                self.root.after(300, self._poll_updates)
            except tk.TclError:
                pass

    def _reset_for_new_game(self) -> None:
        """新对局开始：清空幽灵、更新标题、重建 Canvas。"""
        # 新对局：清空所有手动注释
        self._phantom_items.clear()
        self._phantom_draw_state = None
        self._manual_shapes.clear()
        self._infer_shapes.clear()
        self._phantom_quality_pref.clear()
        self._unknown_cell_quality_pref.clear()
        self._manual_shapes_restore_backup = None
        self._vacant_manual_suppress.clear()

        self.root.title(
            f"BidKing 可视化鉴影 v{__version__} "
            f"第 {self.state.current_round} 回合  ● LIVE"
            f"{self._board_mode_title_suffix()}"
        )
        self._info_text.set(self._info_summary_text())
        cw = GRID_COLS * CELL_W + 1
        ch = GRID_ROWS * CELL_H + 1
        self.canvas.config(
            scrollregion=(0, 0, cw, ch),
            width=min(cw, CANVAS_MAX_W),
            height=min(ch, CANVAS_MAX_H),
        )
        self._refresh()

    def _refresh(self) -> None:
        """普通刷新：更新信息栏、总价标签、重绘 Canvas。"""
        reconcile_overlay_after_refresh(
            self.state,
            self._manual_shapes,
            self._phantom_items,
            self._phantom_quality_pref,
        )
        self._sanitize_unknown_quality_prefs()
        self._sanitize_phantom_quality_prefs()
        self._validate_manual_confirmations()

        self._info_text.set(self._info_summary_text())
        self._draw()
        if self._snapshot_path:
            with self._lock:
                self._emit_board_snapshot_unlocked()

    def _validate_manual_confirmations(self) -> None:
        """校验所有物品的手动候选确认，冲突时自动清除。"""
        item_sources = (self.state.items, self._phantom_items)
        for items in item_sources:
            for uid, k in items.items():
                if k.manual_confirm_item_id is not None:
                    self._valid_manual_confirm_item(uid, k)

    def _tooltip_text_grid_total(self) -> str:
        """图例栏「估算总价」：与 ``pricing.total``（board_pricing 汇总）一致。"""
        p = self._last_pricing_for_tooltips
        if not isinstance(p, dict) or p.get("total") is None:
            p = self._build_pricing_snapshot_dict()
        total = float(p.get("total") or 0)
        n_empty = self._compute_empty_zone_count()
        lines = [
            "估算总价 T（物品）",
            "由 ``board_pricing`` 根据快照 items 汇总："
            "已确认价 → 日志价；未知轮廓 → 权重等价占位与期望价；未知品质 → 权重期望价。",
            f"数字：T = ¥{total:,.0f}（与写入快照的 pricing.total 一致）",
        ]
        if n_empty is not None:
            lines.append(
                f"提示：状态栏「空置 {n_empty} 格」与 ``grid_overlay.vacant`` 一致；"
                "定价 ``pricing.vacant`` 优先与 ``grid_overlay.vacant`` 一致（快照已写出时直接读取），否则与 ``vacant_dict_from_board_snapshot`` 计算结果一致。"
            )
        else:
            lines.append(
                "提示：空置计数暂不可用（例如 ``compute_overlay_vacant_dict`` 未返回 effective_count）。"
            )
        return "\n".join(lines)

    def _tooltip_text_position_estimate(self, key: str) -> str:
        """顶栏仓位总价：est_* / 仓位估价区间，与 ``build_snapshot_pricing_dict`` 一致。"""
        p = self._last_pricing_for_tooltips
        if not isinstance(p, dict) or not p:
            return "（估价尚未计算，请稍候刷新）"
        t_raw = p.get("total")
        try:
            t_val = float(t_raw or 0)
        except (TypeError, ValueError):
            t_val = 0.0
        try:
            u_o = float(p.get("vacant_unit_all_orange") or 0)
            u_gr = float(p.get("vacant_unit_gold_red") or 0)
            u_r = float(p.get("vacant_unit_all_red") or 0)
        except (TypeError, ValueError):
            u_o = u_gr = u_r = 0.0

        v_raw = p.get("vacant_geometric")
        try:
            v_g = int(v_raw) if v_raw is not None else None
        except (TypeError, ValueError):
            v_g = None
        v_eff_raw = p.get("vacant")
        try:
            v_eff = int(v_eff_raw) if v_eff_raw is not None else 0
        except (TypeError, ValueError):
            v_eff = 0
        src = "地图品质均价 CSV" if p.get("map_quality_avg_hit") else "内置缺省单价"

        head: List[str] = [
            f"定价用空置 V = {v_eff}（见 pricing.vacant；vacant_source = {p.get('vacant_source', '—')!s}）",
        ]
        if v_g is not None:
            head.append(f"后备/几何相关 vacant_geometric = {v_g}")
        head.append(f"空置单价来源：{src}")
        head.append("")

        if key == "orange":
            title = "全橙估价 est_orange"
            formula = "T + V × U_全橙"
            u = u_o
            result = p.get("est_orange")
            num = f"{t_val:,.0f} + {v_eff} × {u_o:,.0f} = {float(result or 0):,.0f}"
        elif key == "gold_red":
            title = "金红估价 est_gold_red"
            formula = "T + V × U_金红"
            u = u_gr
            result = p.get("est_gold_red")
            num = f"{t_val:,.0f} + {v_eff} × {u_gr:,.0f} = {float(result or 0):,.0f}"
        elif key == "red":
            title = "全红估价 est_red"
            formula = "T + V × U_全红"
            u = u_r
            result = p.get("est_red")
            num = f"{t_val:,.0f} + {v_eff} × {u_r:,.0f} = {float(result or 0):,.0f}"
        elif key == "floor":
            title = "仓位估价区间 points_floor / points_ceiling"
            pf = p.get("points_floor")
            pc = p.get("points_ceiling")
            ahmad_active = bool(p.get("ahmad_pricing_active"))
            base_lines = [
                title,
                f"第 4 回合起：下限 ≈ T + V×U_全橙 = {pf!s}；上限 ≈ T + V×U_全红 = {pc!s}。",
                f"第 1–3 回合：floor/ceiling 与仓位估价 points 相同（扫描推断单价）。",
                f"当前 points = {p.get('points')!s}。",
            ]
            if ahmad_active:
                gpf, gpc = p.get("generic_points_floor"), p.get(
                    "generic_points_ceiling"
                )
                base_lines.insert(
                    1,
                    "己方英雄为 Ahmad（204）：points/floor/ceiling 均为 event_stats 多候选 Ahmad 仓位估价；"
                    f"通用画板对照 generic_floor/ceiling = {gpf!s} / {gpc!s}。",
                )
            return "\n".join(base_lines)
        else:
            return ""

        lines = [
            title,
            *head,
            f"公式：{formula}",
            f"其中 U = ¥{u:,.0f}",
            f"数字：{num}",
        ]
        if key in ("red", "orange", "gold_red"):
            lines.append("说明：适用于金红总格明确的情况下。")
        return "\n".join(lines)

    def _tooltip_text_early_exclusions(self) -> str:
        """扫描推断的早期空置格均价 U（写入 pricing.early_vacant_unit_from_scan）。"""
        p = self._last_pricing_for_tooltips
        if not isinstance(p, dict) or not p:
            return "（估价尚未计算）"
        eu = p.get("early_vacant_unit_from_scan")
        try:
            u_int = int(eu) if eu is not None else 0
        except (TypeError, ValueError):
            u_int = 0
        t_val = float(p.get("total") or 0)
        v_eff = int(p.get("vacant") or 0)
        pts = p.get("points")
        qg = str(p.get("early_vacant_csv_group") or "").strip()
        pq_raw = p.get("early_vacant_possible_qualities")
        pq_list: List[int] = []
        if isinstance(pq_raw, list):
            for x in pq_raw:
                try:
                    pq_list.append(int(x))
                except (TypeError, ValueError):
                    continue
            pq_list.sort()
        lines = [
            "早期空置单价（排除法）",
            "依据 scan_history 中 quality 扫描 → 空格仍可能的品质集合 → CSV 对应 quality_group 的格均价；"
            "无 quality 扫描时视为 all。",
        ]
        if pq_list:
            tiers = "、".join(str(x) for x in pq_list)
            lines.append(f"仍可能品质档位组合：{tiers}")
        if qg:
            lines.append(f"CSV 均价分组键（对应 map_quality 表一行）：{qg}")
        lines.extend(
            [
                f"U = ¥{u_int:,.0f} / 格（pricing.early_vacant_unit_from_scan）",
                f"顶栏「空置 N 格」与 pricing.vacant 一致，当前 V = {v_eff}。",
            ]
        )
        if p.get("ahmad_pricing_active"):
            lines.append(
                "己方 Ahmad：顶栏仓位估价 points 来自 pricing.ahmad_points（非本式 T+V×U）；"
                f"对照 generic_points = {p.get('generic_points')!s}。"
            )
        else:
            lines.append(
                f"仓位估价 points ≈ T + V×U = {t_val:,.0f} + {v_eff} × {u_int:,.0f}（与 pricing.points 一致）。",
            )
        if pts is not None:
            lines.append(f"当前 pricing.points = {pts!s}")
        return "\n".join(lines)

    def _tooltip_text_main_points(self) -> str:
        """pricing.points / floor / ceiling 摘要。"""
        p = self._last_pricing_for_tooltips
        if not isinstance(p, dict) or not p:
            return "（估价尚未计算）"
        pts = p.get("points")
        pf, pc = p.get("points_floor"), p.get("points_ceiling")
        ahmad_active = bool(p.get("ahmad_pricing_active"))
        head = (
            "仓位估价（Ahmad：points = ahmad_points）"
            if ahmad_active
            else "仓位估价（快照 pricing.points）"
        )
        lines: List[str] = [head]
        if pts is not None:
            try:
                lines.append(f"points = {int(round(float(pts))):,}")
            except (TypeError, ValueError):
                lines.append(f"points = {pts!r}")
            mult = _instant_win_multiplier_for_round(self.state.current_round)
            try:
                pv = float(pts)
                anti = int(round(pv / mult)) if mult > 0 else int(round(pv))
                lines.extend(
                    [
                        "",
                        f"防拍参考：points ÷ 第 {max(1, min(5, int(self.state.current_round or 1)))} 回合秒杀倍率 {mult:g} ≈ {anti:,}",
                    ]
                )
            except (TypeError, ValueError):
                pass
        if ahmad_active:
            lines.append(
                f"通用画板仓位估价（对照）：generic_points = {p.get('generic_points')!s}，"
                f"floor/ceiling = {p.get('generic_points_floor')!s} / {p.get('generic_points_ceiling')!s}"
            )
            lines.append("ahmad_points_detail（各候选）:")
            lines.extend(_lines_from_ahmad_points_detail(p.get("ahmad_points_detail")))
        if pf is not None or pc is not None:
            lines.append(f"points_floor / points_ceiling = {pf!s} / {pc!s}")
        lines.append(
            f"空置 V = {p.get('vacant')!s}；单价 CSV 命中 = {p.get('map_quality_avg_hit')!s}。"
        )
        return "\n".join(lines)

    def _tooltip_text_recommend_bid(self) -> str:
        """顶栏「推荐出价」：展示 ``compute_price`` 与 payload.pricing_reason。"""
        det = self._last_compute_payload
        if not isinstance(det, dict):
            return "推荐出价\n（尚未算出：配置加载或定价链路异常）"
        lines: List[str] = [
            "推荐出价",
            "由 ``bidking.pricing.compute_price`` 基于当前画板快照（含 pricing）与合并后的 runtime/config 计算。",
        ]
        pr = det.get("pricing_reason")
        if pr is not None and str(pr).strip():
            lines.extend(["", "pricing_reason:", str(pr)])
        else:
            rsn = det.get("reason")
            if rsn:
                lines.extend(["", f"说明：{rsn}"])
        if det.get("fallback"):
            lines.extend(["", "（当前走兜底分支；顶栏数字为兜底价）"])
        return "\n".join(lines)

    def _tooltip_text_event_stats(self) -> str:
        """展示 raw_pricing.event_stats（过滤 None）。"""
        rp = self._last_raw_pricing
        if not isinstance(rp, dict):
            rp = self._make_board_snapshot().get("raw_pricing")
            if isinstance(rp, dict):
                self._last_raw_pricing = rp
        st = rp.get("event_stats") if isinstance(rp, dict) else None
        if not isinstance(st, dict):
            return "当局数据（event_stats）\n（暂无数据）"

        lines: List[str] = ["当局数据（event_stats）"]
        for k, v in st.items():
            if v is None:
                continue
            if isinstance(v, float):
                lines.append(f"{k}: {v:g}")
            else:
                lines.append(f"{k}: {v}")
        if len(lines) == 1:
            lines.append("（暂无非空字段）")
        return "\n".join(lines)

    def _update_total_label(self) -> None:
        """更新估算总价标签（pricing.total）。"""
        p = self._last_pricing_for_tooltips
        if not isinstance(p, dict) or p.get("total") is None:
            p = self._build_pricing_snapshot_dict()
        total = float(p.get("total") or 0)
        empty_count = self._compute_empty_zone_count()
        if empty_count and empty_count > 0:
            self._total_label.config(
                text=(f"估算总价  ¥{total:,.0f}" f"    空置 {empty_count} 格")
            )
        else:
            self._total_label.config(text=f"估算总价  ¥{total:,.0f}")

    def _update_vacant_estimate_bar(self) -> None:
        """更新顶栏两行：①仓位估价 points + 推荐出价；②三档 est_* 与仓位估价区间。"""
        if not hasattr(self, "_est_label_red"):
            return
        base = self._make_board_snapshot()
        p = build_snapshot_pricing_dict(
            base,
            snapshot_path_hint=self._snapshot_path,
        )
        self._last_pricing_for_tooltips = p
        pts = p.get("points")
        mult = _instant_win_multiplier_for_round(self.state.current_round)
        if pts is not None:
            try:
                pts_i = int(round(float(pts)))
                anti = int(round(pts_i / mult)) if mult > 0 else pts_i
                self._est_label_aisha.config(
                    text=f"仓位估价  {pts_i:,}  （÷{mult:g}→{anti:,}）",
                )
            except (TypeError, ValueError):
                self._est_label_aisha.config(text=f"仓位估价  {pts!r}")
        else:
            self._est_label_aisha.config(text="仓位估价  —")

        board_for_compute = {**base, "pricing": p}
        rnd = int(self.state.current_round or 1)
        sig = (
            rnd,
            p.get("points"),
            p.get("total"),
            p.get("vacant"),
            p.get("points_floor"),
            p.get("points_ceiling"),
        )
        if self._header_compute_sig != sig:
            try:
                rt = load_runtime()
                cfg_path = rt.source_path or Path.cwd()
                if not isinstance(cfg_path, Path):
                    cfg_path = Path(cfg_path)
                c_price, c_det = compute_price(
                    rt.raw,
                    config_path=cfg_path,
                    round_no=rnd,
                    board_snapshot=board_for_compute,
                )
                self._last_compute_price = int(c_price)
                self._last_compute_payload = c_det
                self._header_compute_sig = sig
            except Exception:
                self._last_compute_price = None
                self._last_compute_payload = None

        if hasattr(self, "_est_label_recommend"):
            if self._last_compute_price is not None:
                cpv = int(self._last_compute_price)
                self._est_label_recommend.config(text=f"推荐出价  {cpv:,}")
            else:
                self._est_label_recommend.config(text="推荐出价  —")

        eu = p.get("early_vacant_unit_from_scan")
        if eu is not None:
            try:
                eu_f = float(eu)
            except (TypeError, ValueError):
                eu_f = None
            if eu_f is not None:
                try:
                    v_scan = int(p.get("vacant") or 0)
                except (TypeError, ValueError):
                    v_scan = 0
                self._est_label_early.config(
                    text=(
                        f"扫描单价 ¥{eu_f:,.0f}/格"
                        f"    空置 {v_scan} 格"
                    ),
                )
                self._est_early_wrap.pack(side="left", padx=(0, 16))
            else:
                self._est_label_early.config(text="")
                self._est_early_wrap.pack_forget()
        else:
            self._est_label_early.config(text="")
            self._est_early_wrap.pack_forget()

        est_red = float(p.get("est_red") or 0)
        est_orange = float(p.get("est_orange") or 0)
        est_gold_red = float(p.get("est_gold_red") or 0)
        self._est_label_red.config(text=f"全红估价  ¥{est_red:,.0f}")
        self._est_label_orange.config(text=f"全橙估价  ¥{est_orange:,.0f}")
        self._est_label_gold_red.config(text=f"金红估价  ¥{est_gold_red:,.0f}")
        rnd = int(self.state.current_round or 1)
        if rnd >= 4:
            pf = int(p.get("points_floor") or 0)
            pc = int(p.get("points_ceiling") or 0)
            self._est_label_floor.config(text=f"仓位估价区间  ¥{pf:,.0f} – ¥{pc:,.0f}")
        else:
            self._est_label_floor.config(text="")

    # ── 界面构建 ──────────────────────────────────────────────────────────

    def _create_topmost_pin_photo(self) -> Optional[Any]:
        """红色图钉小图标（Pillow）；失败时返回 None，改用文字「置顶」。"""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return None
        w, h = 20, 24
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        cx = w // 2
        head_cy = 7
        r = 6
        dr.ellipse((cx - r, head_cy - r, cx + r, head_cy + r), fill=(215, 38, 38, 255))
        dr.ellipse((cx - r + 2, head_cy - r + 1, cx - 1, head_cy - 1), fill=(255, 130, 130, 220))
        dr.polygon(
            [
                (cx - 3, head_cy + r - 1),
                (cx + 3, head_cy + r - 1),
                (cx + 2, h - 2),
                (cx - 2, h - 2),
            ],
            fill=(200, 205, 215, 255),
        )
        dr.line([(cx, head_cy + r - 2), (cx, h - 4)], fill=(160, 42, 42, 255), width=2)
        return ImageTk.PhotoImage(img)

    def _toggle_topmost_pin(self) -> None:
        """切换窗口总在最前（桌面最上层）。"""
        self._topmost_pinned = not self._topmost_pinned
        try:
            self.root.attributes("-topmost", self._topmost_pinned)
            if self._topmost_pinned:
                self.root.lift()
        except tk.TclError:
            self._topmost_pinned = False
        try:
            if self._topmost_pinned:
                self._btn_topmost.config(
                    relief="solid",
                    highlightthickness=1,
                    highlightbackground="#ff5555",
                )
            else:
                self._btn_topmost.config(
                    relief="flat",
                    highlightthickness=0,
                    highlightbackground="#1a1a2e",
                )
        except tk.TclError:
            pass

    def _build_window(self) -> None:
        live_tag = "  ● LIVE" if self._log_path else ""
        self.root = tk.Tk()
        self.root.title(
            f"BidKing 鉴影可视化 v{__version__} "
            f"第 {self.state.current_round} 回合{live_tag}"
            f"{self._board_mode_title_suffix()}"
        )
        self.root.configure(bg="#1a1a2e")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

        self._build_vacant_estimate_bar()
        self._build_info_bar()
        self._build_legend()
        self._build_canvas()
        if self._snapshots:
            self._build_nav_bar()
        self.root.bind(
            "<Control-Shift-V>", lambda _e: self._on_expand_log_items_into_vacant()
        )
        self.root.bind("<Control-Shift-Z>", lambda _e: self._on_restore_manual_shapes())
        self._draw()

    def _on_close_request(self) -> None:
        """用户点窗口关闭或「返回主页」：停 tail、关画板，必要时唤起启动主页。"""
        self._finish_grid_shutdown()

    def _finish_grid_shutdown(self) -> None:
        self._monitor_stop.set()
        home = self._home_shell
        self._home_shell = None
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        if home is not None:
            try:
                home.deiconify()
                home.lift()
                home.focus_force()
            except tk.TclError:
                pass

    def _build_info_bar(self) -> None:
        bar = tk.Frame(self.root, bg="#1a1a2e", pady=4)
        bar.pack(fill="x", padx=8)

        # StringVar 方便后续 _refresh() 直接更新，无需重建 Label
        self._info_text = tk.StringVar(value=self._info_summary_text())
        tk.Label(
            bar,
            textvariable=self._info_text,
            bg="#1a1a2e",
            fg="#ccccdd",
            font=("微软雅黑", 10),
            wraplength=CANVAS_MAX_W - 20,
            justify="left",
        ).pack(side="left")

        right = tk.Frame(bar, bg="#1a1a2e")
        right.pack(side="right", padx=4)
        self._topmost_pin_photo = self._create_topmost_pin_photo()
        pin_kw: Dict[str, Any] = {
            "master": right,
            "command": self._toggle_topmost_pin,
            "bg": "#1a1a2e",
            "activebackground": "#2a3550",
            "relief": "flat",
            "borderwidth": 0,
            "highlightthickness": 0,
            "padx": 2,
            "pady": 0,
            "cursor": "hand2",
            "takefocus": 0,
        }
        if self._topmost_pin_photo is not None:
            pin_kw["image"] = self._topmost_pin_photo
        else:
            pin_kw["text"] = "置顶"
            pin_kw["fg"] = "#e04040"
            pin_kw["font"] = ("微软雅黑", 9)
        self._btn_topmost = tk.Button(**pin_kw)
        self._btn_topmost.pack(side="left", padx=(0, 6))

        if self._home_shell is not None:
            tk.Button(
                right,
                text="返回主页",
                command=self._finish_grid_shutdown,
                bg="#3a4a6a",
                fg="#dde8ff",
                font=("微软雅黑", 9),
                relief="flat",
                padx=8,
                pady=2,
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

        if self._log_path:
            tk.Label(
                right,
                text=" ● LIVE ",
                bg="#c03030",
                fg="#ffffff",
                font=("微软雅黑", 9, "bold"),
                relief="flat",
                padx=4,
            ).pack(side="left")

    def _build_vacant_estimate_bar(self) -> None:
        """窗口最上方：第一行仓位估价 points、推荐出价、扫描单价与当局数据；第二行三档 est 与仓位估价区间。"""
        bar = tk.Frame(self.root, bg="#152030", pady=4)
        bar.pack(fill="x", padx=8, pady=(6, 0))
        row1 = tk.Frame(bar, bg="#152030")
        row1.pack(fill="x", padx=10)
        self._est_aisha_wrap = tk.Frame(row1, bg="#152030")
        self._est_label_aisha = tk.Label(
            self._est_aisha_wrap,
            text="",
            bg="#152030",
            fg="#a8f0c8",
            font=("微软雅黑", 10, "bold"),
            cursor="hand2",
        )
        self._est_label_aisha.pack(side="left")
        self._est_aisha_wrap.pack(side="left", padx=(0, 16))
        self._est_recommend_wrap = tk.Frame(row1, bg="#152030")
        self._est_label_recommend = tk.Label(
            self._est_recommend_wrap,
            text="",
            bg="#152030",
            fg="#ffd080",
            font=("微软雅黑", 10, "bold"),
            cursor="hand2",
        )
        self._est_label_recommend.pack(side="left")
        self._est_recommend_wrap.pack(side="left", padx=(0, 16))
        self._est_early_wrap = tk.Frame(row1, bg="#152030")
        self._est_label_early = tk.Label(
            self._est_early_wrap,
            text="",
            bg="#152030",
            fg="#e8d8a8",
            font=("微软雅黑", 10),
            cursor="hand2",
        )
        self._est_label_early.pack(side="left")
        self._event_stats_wrap = tk.Frame(row1, bg="#152030")
        self._event_stats_label = tk.Label(
            self._event_stats_wrap,
            text="当局数据",
            bg="#152030",
            fg="#9fd9ff",
            font=("微软雅黑", 10),
            cursor="hand2",
        )
        self._event_stats_label.pack(side="left")
        self._event_stats_wrap.pack(side="left", padx=(0, 16))
        row2 = tk.Frame(bar, bg="#152030")
        row2.pack(fill="x", padx=10, pady=(6, 0))
        tip_lbl = dict(
            bg="#152030", fg="#b8e0ff", font=("微软雅黑", 10), cursor="hand2"
        )
        self._est_label_red = tk.Label(row2, text="", **tip_lbl)
        self._est_label_orange = tk.Label(row2, text="", **tip_lbl)
        self._est_label_gold_red = tk.Label(row2, text="", **tip_lbl)
        self._est_label_floor = tk.Label(row2, text="", **tip_lbl)
        self._est_label_red.pack(side="left", padx=(0, 16))
        self._est_label_orange.pack(side="left", padx=(0, 16))
        self._est_label_gold_red.pack(side="left", padx=(0, 16))
        self._est_label_floor.pack(side="left", padx=(0, 0))
        _PricingHoverTip(self._est_label_aisha, self._tooltip_text_main_points)
        _PricingHoverTip(self._est_label_recommend, self._tooltip_text_recommend_bid)
        _PricingHoverTip(self._est_label_early, self._tooltip_text_early_exclusions)
        _PricingHoverTip(self._event_stats_label, self._tooltip_text_event_stats)
        _PricingHoverTip(
            self._est_label_red, lambda: self._tooltip_text_position_estimate("red")
        )
        _PricingHoverTip(
            self._est_label_orange,
            lambda: self._tooltip_text_position_estimate("orange"),
        )
        _PricingHoverTip(
            self._est_label_gold_red,
            lambda: self._tooltip_text_position_estimate("gold_red"),
        )
        _PricingHoverTip(
            self._est_label_floor, lambda: self._tooltip_text_position_estimate("floor")
        )
        self._update_vacant_estimate_bar()

    def _build_legend(self) -> None:
        bar = tk.Frame(self.root, bg="#222233", pady=5)
        bar.pack(fill="x", padx=8)
        row1 = tk.Frame(bar, bg="#222233")
        row1.pack(fill="x")
        row2 = tk.Frame(bar, bg="#222233")
        row2.pack(fill="x", pady=(2, 0))

        # 只保留未知品质色块，已知品质直接通过格子颜色区分。
        tk.Label(
            row1,
            text=" 未知 ",
            bg=UNKNOWN_BG,
            fg="#ffffff",
            font=("微软雅黑", 8),
            relief="flat",
            padx=2,
        ).pack(side="left", padx=(6, 2))

        tk.Button(
            row1,
            text="扩展日志物品",
            command=self._on_expand_log_items_into_vacant,
            bg="#355545",
            fg="#e0ffe8",
            font=("微软雅黑", 8),
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side="left", padx=(8, 4))

        tk.Button(
            row1,
            text="还原轮廓",
            command=self._on_restore_manual_shapes,
            bg="#554535",
            fg="#ffe8e0",
            font=("微软雅黑", 8),
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side="left", padx=(0, 4))

        tk.Label(
            row1,
            text="空置格·右键剔除/恢复",
            bg="#222233",
            fg="#aaaabb",
            font=("微软雅黑", 8),
        ).pack(side="left", padx=(10, 4))

        # 右侧：估算总价（首次绘制后由 _update_total_label 刷新）
        self._total_label = tk.Label(
            row1,
            text="估算总价  ¥0",
            bg="#222233",
            fg="#e8d080",
            font=("微软雅黑", 10, "bold"),
            cursor="hand2",
        )
        self._total_label.pack(side="right", padx=12)
        _PricingHoverTip(self._total_label, self._tooltip_text_grid_total)

        tk.Label(
            row2,
            text=(
                "左键空格拖普通幽灵；Ctrl+左键空格拖金幽灵；Ctrl+右键空格拖红幽灵；"
                "Ctrl+左键命中四角：对角缩放；四边把手仍左键拖；"
                "右键幽灵删格；日志物品轮廓未锁时右键命中可还原手动画框；"
                "弹窗双击行确认；Ctrl+Shift+Z：还原轮廓"
            ),
            bg="#222233",
            fg="#555577",
            font=("微软雅黑", 8),
        ).pack(side="left", padx=8)

    def _build_nav_bar(self) -> None:
        """快照导航栏：上一步 / 当前位置 / 下一步（仅快照模式显示）。"""
        bar = tk.Frame(self.root, bg="#161625", pady=6)
        bar.pack(fill="x", padx=8)

        btn_cfg = dict(
            font=("微软雅黑", 9, "bold"),
            relief="flat",
            padx=14,
            pady=4,
            cursor="hand2",
        )
        self._btn_prev = tk.Button(
            bar,
            text="◀  上一步",
            bg="#334466",
            fg="#aabbdd",
            command=self._snap_prev,
            **btn_cfg,
        )
        self._btn_prev.pack(side="left", padx=8)

        self._nav_label = tk.StringVar()
        tk.Label(
            bar,
            textvariable=self._nav_label,
            bg="#161625",
            fg="#ddddee",
            font=("微软雅黑", 10, "bold"),
        ).pack(side="left", expand=True)

        self._btn_next = tk.Button(
            bar,
            text="下一步  ▶",
            bg="#334466",
            fg="#aabbdd",
            command=self._snap_next,
            **btn_cfg,
        )
        self._btn_next.pack(side="right", padx=8)

        self._update_nav_label()

        # 键盘快捷键
        self.root.bind("<Left>", lambda _: self._snap_prev())
        self.root.bind("<Right>", lambda _: self._snap_next())

    def _update_nav_label(self) -> None:
        if not self._snapshots:
            return
        label = self._snapshots[self._snap_idx][0]
        total = len(self._snapshots)
        self._nav_label.set(f"{label}   ({self._snap_idx + 1} / {total})")
        # 边界禁用按钮
        self._btn_prev.config(
            state="normal" if self._snap_idx > 0 else "disabled",
            bg="#334466" if self._snap_idx > 0 else "#222233",
        )
        self._btn_next.config(
            state="normal" if self._snap_idx < len(self._snapshots) - 1 else "disabled",
            bg="#334466" if self._snap_idx < len(self._snapshots) - 1 else "#222233",
        )

    def _snap_goto(self, idx: int) -> None:
        """跳转到指定快照索引并刷新界面。"""
        if not self._snapshots or not (0 <= idx < len(self._snapshots)):
            return
        self._snap_idx = idx
        self.state = self._snapshots[idx][1]
        self._skill_logs = list(self._snapshots[idx][2])
        self._recalc_vis_rows()
        self._manual_shapes_restore_backup = None

        # 更新窗口标题、信息栏、画布
        label = self._snapshots[idx][0]
        self.root.title(
            f"BidKing 物品格局 v{__version__}  —  对局 {self.state.uid}  {label}"
            f"{self._board_mode_title_suffix()}"
        )
        self._refresh()
        self._update_nav_label()

        # 调整 Canvas 滚动区域以匹配新行数
        cw = GRID_COLS * CELL_W + 1
        ch = GRID_ROWS * CELL_H + 1
        self.canvas.config(scrollregion=(0, 0, cw, ch))

    def _snap_prev(self) -> None:
        self._snap_goto(self._snap_idx - 1)

    def _snap_next(self) -> None:
        self._snap_goto(self._snap_idx + 1)

    def _build_canvas(self) -> None:
        outer = tk.Frame(self.root, bg="#1a1a2e")
        outer.pack(fill="both", expand=True, anchor="w", padx=8, pady=(4, 8))

        cw = GRID_COLS * CELL_W + 1
        ch = GRID_ROWS * CELL_H + 1

        v_sb = tk.Scrollbar(outer, orient="vertical")

        self.canvas = tk.Canvas(
            outer,
            width=min(cw, CANVAS_MAX_W),
            height=min(ch, CANVAS_MAX_H),
            scrollregion=(0, 0, cw, ch),
            yscrollcommand=v_sb.set,
            bg=EMPTY_BG,
            highlightthickness=0,
            takefocus=1,
        )
        v_sb.config(command=self.canvas.yview)
        self.canvas.pack(side="left", fill="y", expand=True)
        v_sb.pack(side="left", fill="y")
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind(
            "<Button-2>", self._on_middle_press
        )  # 中键占位（角缩放已改 Ctrl+左键）
        self.canvas.bind("<B2-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_drag_end)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<B3-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_drag_end)

        # 鼠标滚轮滚动画布内容（Windows）
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.focus_set()
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> str:
        """光标在画布上时滚动 Canvas 内容。"""
        if event.delta:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    # ── 绘制 ──────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._sync_infer_shapes_from_analysis()
        canvas = self.canvas
        canvas.delete("all")

        # 构建共享占位格缓存，供本次绘制所有 _compute_max_size 调用复用
        self._occupied_for_draw = self._build_occupied()

        # ── 1. 空格子背景 + BoxId 标注 ──────────────────────────────────
        for row in range(self.vis_rows):
            for col in range(GRID_COLS):
                x1, y1 = col * CELL_W, row * CELL_H
                x2, y2 = x1 + CELL_W, y1 + CELL_H
                canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=EMPTY_BG,
                    outline=GRID_LINE,
                    width=1,
                )
                bid = row * GRID_COLS + col
                canvas.create_text(
                    x1 + 4,
                    y1 + 3,
                    text=str(bid),
                    anchor="nw",
                    fill="#404050",
                    font=("Consolas", 7),
                )

        # ── 1.5  空置候选区（橘红半透明；诈骗格剔除与计数逻辑一致） ─────
        max_box_id = self._empty_zone_max_box_id()
        if max_box_id >= 0:
            vac_limit = min(max_box_id, GRID_COLS * GRID_ROWS - 1)
            apply_fraud_cells = _grid_overlay.fraud_zone_cell_exclusion_enabled(
                self._vacant_scan_context_snapshot(),
                self._occupied_for_draw,
                vac_limit,
            )
            for bid in range(vac_limit + 1):
                row = bid // GRID_COLS
                col = bid % GRID_COLS
                if (row, col) not in self._occupied_for_draw:
                    if (row, col) in self._vacant_manual_suppress:
                        continue
                    if self._exclude_from_empty_zone_estimate(
                        row,
                        col,
                        self._occupied_for_draw,
                        vac_limit,
                        apply_fraud_filter=apply_fraud_cells,
                    ):
                        continue
                    x1 = col * CELL_W
                    y1 = row * CELL_H
                    canvas.create_rectangle(
                        x1,
                        y1,
                        x1 + CELL_W,
                        y1 + CELL_H,
                        fill=EMPTY_ZONE_COLOR,
                        stipple=EMPTY_ZONE_STIPPLE,
                        outline="",
                    )

        # ── 2. 物品格子（log 数据）────────────────────────────────────────
        for uid, k in self.state.items.items():
            if k.box_id is None:
                continue
            self._draw_item(uid, k)

        # ── 3. 幽灵物品格子（手动画框）────────────────────────────────────
        for phid, pk in self._phantom_items.items():
            if phid in self._manual_shapes:
                self._draw_item(phid, pk)

        # ── 4. 正在拖拽画框的预览虚线框 ────────────────────────────────────
        if self._phantom_draw_state:
            pds = self._phantom_draw_state
            sr, sc = pds["start_row"], pds["start_col"]
            cr, cc = pds["cur_row"], pds["cur_col"]
            min_r, max_r = min(sr, cr), max(sr, cr)
            min_c, max_c = min(sc, cc), max(sc, cc)
            preview_w = max_c - min_c + 1
            preview_h = max_r - min_r + 1
            preview_invalid = self._rect_overlaps_occupied(
                min_r,
                min_c,
                preview_w,
                preview_h,
            )
            if preview_invalid:
                preview_color = "#cc4444"
            elif pds.get("phantom_infer"):
                preview_color = PHANTOM_BORDER
            elif pds.get("default_quality") == 6:
                preview_color = PHANTOM_PINK_BORDER
            else:
                preview_color = PHANTOM_GOLD_BORDER
            px1 = min_c * CELL_W + 1
            py1 = min_r * CELL_H + 1
            px2 = (max_c + 1) * CELL_W - 1
            py2 = (max_r + 1) * CELL_H - 1
            canvas.create_rectangle(
                px1,
                py1,
                px2,
                py2,
                fill="",
                outline=preview_color,
                width=2,
                dash=(6, 3),
            )
            # 显示将要创建的大小
            canvas.create_text(
                (px1 + px2) / 2,
                (py1 + py2) / 2,
                text=f"{preview_w}x{preview_h}" + (" 重叠" if preview_invalid else ""),
                fill=preview_color,
                font=("微软雅黑", 10, "bold"),
            )

        # 每次绘制后同步更新估价标签（先算 pricing 缓存，再刷新总价）
        if hasattr(self, "_est_label_red"):
            self._update_vacant_estimate_bar()
        if hasattr(self, "_total_label"):
            self._update_total_label()
        if hasattr(self, "_info_text"):
            self._info_text.set(self._info_summary_text())

        # 绘制完成，释放缓存
        self._occupied_for_draw = None

    def _draw_item(self, uid: str, k: ItemKnowledge) -> None:
        canvas = self.canvas
        col, row = self._effective_display_origin(uid, k)  # 手动 or BoxId 默认左上角
        w, h = self._effective_shape_wh(uid, k)

        # 超出可视范围则跳过
        if row >= self.vis_rows or col + w > GRID_COLS:
            return

        x1 = col * CELL_W + 2
        y1 = row * CELL_H + 2
        x2 = (col + w) * CELL_W - 2
        y2 = (row + h) * CELL_H - 2
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        is_phantom = uid in self._phantom_items
        q = self._display_quality(uid, k) or 0
        pen = self._phantom_pen_theme(uid) if is_phantom else ""
        if is_phantom:
            if pen == "red":
                bg = PHANTOM_PINK_BG
                fg = PHANTOM_PINK_FG
            elif pen == "gold":
                bg = PHANTOM_GOLD_BG
                fg = PHANTOM_GOLD_FG
            else:
                bg = PHANTOM_BG
                fg = QUALITY_FG.get(q, UNKNOWN_FG) if q else "#e8e8f0"
        else:
            bg = QUALITY_BG.get(q, UNKNOWN_BG)
            fg = QUALITY_FG.get(q, UNKNOWN_FG)
        tag = f"item_{uid}"
        price_value = self._display_price_value(uid, k)
        is_high_value = price_value is not None and price_value >= HIGH_VALUE_THRESHOLD

        # 外边框：幽灵=金/红/青，手动调整=黄色，普通=白色
        if is_phantom:
            if pen == "red":
                border_color = PHANTOM_PINK_BORDER
            elif pen == "gold":
                border_color = PHANTOM_GOLD_BORDER
            else:
                border_color = PHANTOM_BORDER
            border_width = 2
        elif is_high_value:
            border_color = "#ffd34d"
            border_width = 3
        elif uid in self._manual_shapes:
            border_color = "#ffdd00"
            border_width = 2
        elif uid in self._infer_shapes:
            border_color = "#66b3ff"
            border_width = 2
        else:
            border_color = "#ffffff"
            border_width = 1
        canvas.create_rectangle(
            x1 - border_width,
            y1 - border_width,
            x2 + border_width,
            y2 + border_width,
            fill=border_color,
            outline="",
            tags=(tag,),
        )
        canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=bg,
            outline="",
            tags=(tag,),
        )

        # 构建显示文字
        lines = self._item_text_lines(uid, k)
        text = "\n".join(lines)

        canvas.create_text(
            cx,
            cy,
            text=text,
            fill=fg,
            font=("微软雅黑", 8),
            justify="center",
            anchor="center",
            tags=(tag,),
        )

        if is_high_value:
            canvas.create_rectangle(
                x2 - 31,
                y1,
                x2,
                y1 + 14,
                fill="#ffd34d",
                outline="",
                tags=(tag,),
            )
            canvas.create_text(
                x2 - 15,
                y1 + 7,
                text="10万+",
                fill="#3a2600",
                font=("微软雅黑", 7, "bold"),
                tags=(tag,),
            )

        # ── 缩放把手：四边（所有 log 未确认形状的物品均可手动调整） ────────
        if k.shape is None:
            hw = RESIZE_HANDLE_W
            hc = RESIZE_HANDLE_COLOR
            pad = 2
            stipple = "gray50"
            # 东侧（改宽）— 先于南/北绘制，避免视觉上被横条完全盖住
            canvas.create_rectangle(
                x2 - hw,
                y1 + pad,
                x2,
                y2 - pad,
                fill=hc,
                outline="",
                stipple=stipple,
                tags=(tag,),
            )
            # 西侧（改宽，同时移动左边界）
            canvas.create_rectangle(
                x1,
                y1 + pad,
                x1 + hw,
                y2 - pad,
                fill=hc,
                outline="",
                stipple=stipple,
                tags=(tag,),
            )
            # 南侧（改高）
            canvas.create_rectangle(
                x1 + pad,
                y2 - hw,
                x2 - pad,
                y2,
                fill=hc,
                outline="",
                stipple=stipple,
                tags=(tag,),
            )
            # 北侧（改高，同时移动上边界）
            canvas.create_rectangle(
                x1 + pad,
                y1,
                x2 - pad,
                y1 + hw,
                fill=hc,
                outline="",
                stipple=stipple,
                tags=(tag,),
            )
            # 四角实心方块（视觉提示；命中区见 _find_resize_corner_handle_at，配合 Ctrl+左键）
            ch = max(hw, RESIZE_CORNER_HIT // 2 + 4)
            for cx2, cy2 in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                canvas.create_rectangle(
                    cx2 - ch // 2,
                    cy2 - ch // 2,
                    cx2 + ch // 2,
                    cy2 + ch // 2,
                    fill=hc,
                    outline="",
                    tags=(tag,),
                )

    def _item_text_lines(self, uid: str, k: ItemKnowledge) -> List[str]:
        """
        生成格子内显示的文字行（最多 3 行）。
          - 第一行：类型/大小并排显示
          - 唯一确定：显示物品名 + 价格
          - 多候选：显示 N个候选 + 估算价
          - 无匹配：显示 无匹配
        """
        lines: List[str] = []

        # 第 1 行：类型和形状并排显示，节省小格子里的垂直空间
        type_text = ""
        if uid in self._phantom_items:
            type_text = "手动"
        elif k.categories:
            type_text = "/".join(
                _CAT_SHORT.get(c, str(c)) for c in sorted(k.categories)
            )

        if k.shape:
            shape_text = ""
        elif uid in self._manual_shapes:
            mw, mh, mdc, mdr = self._manual_shapes[uid]
            shape_text = f"{mw}x{mh}*"  # * 表示手动设置
        elif uid in self._infer_shapes:
            iw, ih, _, _ = self._infer_shapes[uid]
            shape_text = f"{iw}x{ih}≈"  # ≈ 表示推算
        else:
            shape_text = "?x?"

        header_text = f"{type_text} {shape_text}".strip()
        if header_text:
            lines.append(header_text)

        # 第 2-3 行：识别结果（传入负向约束 + 形状参与过滤）
        best, count, unique, est, _label = self._query_item_for_grid(uid, k)

        def _short(name: str, max_len: int = 5) -> str:
            return name[:max_len] + "…" if len(name) > max_len else name

        if k.price is not None and k.item_cid:
            # 精确已知（200021 或游戏结束揭晓）
            name = (
                self.csv_index[k.item_cid].name
                if k.item_cid in self.csv_index
                else f"CID={k.item_cid}"
            )
            lines.append(_short(name))
            mark = "★" if k.price >= HIGH_VALUE_THRESHOLD else ""
            lines.append(f"{mark}¥{k.price:,}")
        elif best:
            if unique:
                lines.append(_short(best.name))
                mark = "★" if best.base_value >= HIGH_VALUE_THRESHOLD else ""
                lines.append(f"{mark}¥{best.base_value:,}")
            else:
                lines.append(f"{count}个候选")
                if est is not None:
                    mark = "★" if est >= HIGH_VALUE_THRESHOLD else ""
                    lines.append(f"{mark}¥{est:.0f}")
        else:
            lines.append("无匹配")

        return lines

    # ── 点击事件 ──────────────────────────────────────────────────────────

    def _on_click(self, event: tk.Event) -> None:
        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))
        ctrl = (event.state & 0x0004) != 0

        # 1. 四边缩放把手（左键，无需 Ctrl）
        rh = self._find_resize_handle_at(cx, cy)
        if rh:
            uid, direction = rh
            self._start_drag(uid, direction, cx, cy, button=1)
            return

        # 2. Ctrl + 命中四角：对角缩放（原中键/滚轮按下）
        if ctrl:
            cr = self._find_resize_corner_handle_at(cx, cy)
            if cr:
                uid, direction = cr
                self._start_drag(uid, direction, cx, cy, button=1)
                return

        col = cx // CELL_W
        row = cy // CELL_H
        if not (0 <= col < GRID_COLS and 0 <= row < self.vis_rows):
            return

        uid = self._find_item_at(row, col)

        # 3. 有物品 → 弹窗
        if uid is not None:
            k = self._phantom_items.get(uid) or self.state.items.get(uid)
            if k:
                self._show_popup(uid, k, event.x_root, event.y_root)
            return

        # 4. 空格左键拖幽灵：普通(推断) / Ctrl+左键=金（四角缩放已在上方处理）
        self._phantom_draw_state = {
            "start_row": row,
            "start_col": col,
            "cur_row": row,
            "cur_col": col,
            "button": 1,
            "default_quality": None,
            "phantom_infer": not ctrl,
        }

    def _on_middle_press(self, event: tk.Event) -> None:
        """中键（滚轮按下）不再用于四角缩放；对角缩放请用 Ctrl+左键命中四角。"""
        return

    # ── 缩放把手拖动 ──────────────────────────────────────────────────────

    def _on_right_click(self, event: tk.Event) -> None:
        """右键：幽灵物品 → 删除；空格无 Ctrl → 切换手动剔除空置；
        Ctrl+右键 + 空格 → 拖动画红幽灵（Q6）。"""
        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))
        ctrl = (event.state & 0x0004) != 0
        col = cx // CELL_W
        row = cy // CELL_H
        if not (0 <= col < GRID_COLS and 0 <= row < self.vis_rows):
            return
        uid = self._find_item_at(row, col)
        if uid and uid in self._phantom_items:
            self._phantom_items.pop(uid, None)
            self._manual_shapes.pop(uid, None)
            self._phantom_quality_pref.pop(uid, None)
            self._refresh()
            return
        if uid is not None and uid in self.state.items:
            k = self.state.items[uid]
            if k.shape is None and uid in self._manual_shapes:
                self._manual_shapes.pop(uid, None)
                self._refresh()
                return
        if uid is not None:
            return
        if self._phantom_draw_state is not None:
            return
        if not ctrl:
            self._toggle_vacant_manual_suppress(row, col)
            return
        self._phantom_draw_state = {
            "start_row": row,
            "start_col": col,
            "cur_row": row,
            "cur_col": col,
            "button": 3,
            "default_quality": 6,
            "phantom_infer": False,
        }

    def _find_resize_corner_handle_at(
        self, cx: int, cy: int
    ) -> Optional[Tuple[str, str]]:
        """
        Ctrl+左键：命中某物品矩形四角附近（圆形距离）则返回 (uid, 'nw'|'ne'|'sw'|'se')。
        取距离最近的角，避免小格上多角重叠。
        """
        rmax = RESIZE_CORNER_HIT * 1.15
        best: Optional[Tuple[str, str, float]] = None
        for uid, k in self.state.items.items():
            if k.shape is not None or k.box_id is None:
                continue
            dc, dr = self._effective_display_origin(uid, k)
            w, h = self._effective_shape_wh(uid, k)
            x1 = dc * CELL_W + 2
            y1 = dr * CELL_H + 2
            x2 = (dc + w) * CELL_W - 2
            y2 = (dr + h) * CELL_H - 2
            for name, px, py in (
                ("nw", float(x1), float(y1)),
                ("ne", float(x2), float(y1)),
                ("sw", float(x1), float(y2)),
                ("se", float(x2), float(y2)),
            ):
                d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if d <= rmax and (best is None or d < best[2]):
                    best = (uid, name, d)
        if best is None:
            return None
        return best[0], best[1]

    def _find_resize_handle_at(self, cx: int, cy: int) -> Optional[Tuple[str, str]]:
        """
        左键：四边把手（不含角区，避免与 Ctrl+左键四角缩放抢同一像素）。
        先东/西再南/北，避免底边横条抢走右侧竖条命中。
        """
        HZ = RESIZE_HANDLE_W + 6
        corner_ex = RESIZE_CORNER_HIT + 4
        for uid, k in self.state.items.items():
            if k.shape is not None or k.box_id is None:
                continue
            dc, dr = self._effective_display_origin(uid, k)
            w, h = self._effective_shape_wh(uid, k)
            x1 = dc * CELL_W + 2
            y1 = dr * CELL_H + 2
            x2 = (dc + w) * CELL_W - 2
            y2 = (dr + h) * CELL_H - 2
            in_x = x1 <= cx <= x2
            in_y = y1 <= cy <= y2

            # 排除四角（交给 Ctrl+左键四角缩放）
            def _not_corner_zone() -> bool:
                if abs(cx - x1) <= corner_ex and abs(cy - y1) <= corner_ex:
                    return False
                if abs(cx - x2) <= corner_ex and abs(cy - y1) <= corner_ex:
                    return False
                if abs(cx - x1) <= corner_ex and abs(cy - y2) <= corner_ex:
                    return False
                if abs(cx - x2) <= corner_ex and abs(cy - y2) <= corner_ex:
                    return False
                return True

            if not _not_corner_zone():
                continue
            # 东侧
            if x2 - HZ <= cx <= x2 and in_y:
                return uid, "e"
            # 西侧
            if x1 <= cx <= x1 + HZ and in_y:
                return uid, "w"
            # 南侧
            if y2 - HZ <= cy <= y2 and in_x:
                return uid, "s"
            # 北侧
            if y1 <= cy <= y1 + HZ and in_x:
                return uid, "n"
        return None

    def _start_drag(
        self, uid: str, direction: str, cx: int, cy: int, button: int = 1
    ) -> None:
        k = self.state.items.get(uid)
        if not k:
            return
        w, h = self._effective_shape_wh(uid, k)
        dc, dr = self._effective_display_origin(uid, k)
        self._drag_state = {
            "uid": uid,
            "direction": direction,  # 'n'|'s'|'e'|'w'|'nw'|'ne'|'sw'|'se'
            "button": button,
            "start_cx": cx,
            "start_cy": cy,
            "orig_w": w,
            "orig_h": h,
            "orig_dc": dc,  # 拖拽起始显示列
            "orig_dr": dr,  # 拖拽起始显示行
        }

    def _on_drag(self, event: tk.Event) -> None:  # noqa: C901
        """
        拖拽分三模式：
          resize  → 单边 n/s/e/w，或四角 nw/ne/sw/se 二维缩放（Ctrl+左键按下）
          phantom → 左键/Ctrl+左键/Ctrl+右键在空格拖动画幽灵（预览虚线框）

          e/s：右/下边界移动，左上角不动；BoxId 必须保留在矩形内。
          w/n：左/上边界移动，右下角不动；同样保证 BoxId 在矩形内。
        碰撞检测：只对"新增"的格列/行检查是否与已确认物品重叠。
        """
        # ── 画框模式 ──────────────────────────────────────────────────
        if self._phantom_draw_state is not None:
            cx = int(self.canvas.canvasx(event.x))
            cy = int(self.canvas.canvasy(event.y))
            col = max(0, min(cx // CELL_W, GRID_COLS - 1))
            row = max(0, min(cy // CELL_H, self.vis_rows - 1))
            pds = self._phantom_draw_state
            if row != pds["cur_row"] or col != pds["cur_col"]:
                pds["cur_row"] = row
                pds["cur_col"] = col
                self._draw()
            return

        # ── 缩放把手模式 ──────────────────────────────────────────────
        if not self._drag_state:
            return
        ds = self._drag_state
        uid = ds["uid"]
        k = self.state.items.get(uid)
        if not k:
            return

        cx = int(self.canvas.canvasx(event.x))
        cy = int(self.canvas.canvasy(event.y))
        dx_cells = (cx - ds["start_cx"]) / CELL_W
        dy_cells = (cy - ds["start_cy"]) / CELL_H

        w0, h0 = ds["orig_w"], ds["orig_h"]
        dc0, dr0 = ds["orig_dc"], ds["orig_dr"]
        direction = ds["direction"]

        brow = (k.box_id // GRID_COLS) if k.box_id is not None else dr0
        bcol = (k.box_id % GRID_COLS) if k.box_id is not None else dc0

        occ = self._build_occupied(exclude_uid=uid)

        # ── 各方向计算 ────────────────────────────────────────────────────
        if direction == "e":
            # 右边界移动，左上角(dc0,dr0)不变
            delta = round(dx_cells)
            # 扩张时检查新列
            if delta > 0:
                max_ext = 0
                for c in range(dc0 + w0, GRID_COLS):
                    if any((dr0 + r, c) in occ for r in range(h0)):
                        break
                    max_ext += 1
                delta = min(delta, max_ext)
            # 缩短时保证 BoxId 不越出右边界
            new_w = max(bcol - dc0 + 1, max(1, w0 + delta))
            new_h = h0
            new_dc, new_dr = dc0, dr0

        elif direction == "w":
            # 左边界移动，右边(dc0+w0-1)不变
            delta = round(dx_cells)  # 向左为负
            if delta < 0:  # 扩张（往左）
                max_ext = 0
                for c in range(dc0 - 1, -1, -1):
                    if any((dr0 + r, c) in occ for r in range(h0)):
                        break
                    max_ext += 1
                delta = max(delta, -max_ext)
            raw_dc = dc0 + delta
            # 不能越过 BoxId（BoxId 必须在矩形内）
            new_dc = max(0, min(raw_dc, bcol))
            new_w = max(1, dc0 + w0 - new_dc)
            new_h = h0
            new_dr = dr0

        elif direction == "s":
            # 下边界移动，左上角不变
            delta = round(dy_cells)
            if delta > 0:
                max_ext = 0
                for r in range(dr0 + h0, GRID_ROWS):
                    if any((r, dc0 + c) in occ for c in range(w0)):
                        break
                    max_ext += 1
                delta = min(delta, max_ext)
            new_h = max(brow - dr0 + 1, max(1, h0 + delta))
            new_w = w0
            new_dc, new_dr = dc0, dr0

        elif direction == "n":
            # 上边界移动，下边(dr0+h0-1)不变
            delta = round(dy_cells)  # 向上为负
            if delta < 0:
                max_ext = 0
                for r in range(dr0 - 1, -1, -1):
                    if any((r, dc0 + c) in occ for c in range(w0)):
                        break
                    max_ext += 1
                delta = max(delta, -max_ext)
            raw_dr = dr0 + delta
            new_dr = max(0, min(raw_dr, brow))
            new_h = max(1, dr0 + h0 - new_dr)
            new_w = w0
            new_dc = dc0

        elif direction == "se":
            # 先东后南（南向外扩时用当前新宽度扫占用）
            delta_e = round(dx_cells)
            if delta_e > 0:
                max_ext = 0
                for c in range(dc0 + w0, GRID_COLS):
                    if any((dr0 + r, c) in occ for r in range(h0)):
                        break
                    max_ext += 1
                delta_e = min(delta_e, max_ext)
            new_w = max(bcol - dc0 + 1, max(1, w0 + delta_e))
            new_dc, new_dr = dc0, dr0
            w_scan = new_w
            delta_s = round(dy_cells)
            if delta_s > 0:
                max_ext = 0
                for r in range(dr0 + h0, GRID_ROWS):
                    if any((r, dc0 + c) in occ for c in range(w_scan)):
                        break
                    max_ext += 1
                delta_s = min(delta_s, max_ext)
            new_h = max(brow - dr0 + 1, max(1, h0 + delta_s))

        elif direction == "sw":
            delta_s = round(dy_cells)
            if delta_s > 0:
                max_ext = 0
                for r in range(dr0 + h0, GRID_ROWS):
                    if any((r, dc0 + c) in occ for c in range(w0)):
                        break
                    max_ext += 1
                delta_s = min(delta_s, max_ext)
            new_h = max(brow - dr0 + 1, max(1, h0 + delta_s))
            new_dc, new_dr = dc0, dr0
            new_w = w0
            h_scan = new_h
            delta_w = round(dx_cells)
            if delta_w < 0:
                max_ext = 0
                for c in range(dc0 - 1, -1, -1):
                    if any((dr0 + r, c) in occ for r in range(h_scan)):
                        break
                    max_ext += 1
                delta_w = max(delta_w, -max_ext)
            raw_dc = dc0 + delta_w
            new_dc = max(0, min(raw_dc, bcol))
            new_w = max(1, dc0 + w0 - new_dc)

        elif direction == "ne":
            delta_n = round(dy_cells)
            if delta_n < 0:
                max_ext = 0
                for r in range(dr0 - 1, -1, -1):
                    if any((r, dc0 + c) in occ for c in range(w0)):
                        break
                    max_ext += 1
                delta_n = max(delta_n, -max_ext)
            raw_dr = dr0 + delta_n
            new_dr = max(0, min(raw_dr, brow))
            new_h = max(1, dr0 + h0 - new_dr)
            new_dc = dc0
            h_scan = new_h
            delta_e = round(dx_cells)
            if delta_e > 0:
                max_ext = 0
                for c in range(dc0 + w0, GRID_COLS):
                    if any((new_dr + r, c) in occ for r in range(h_scan)):
                        break
                    max_ext += 1
                delta_e = min(delta_e, max_ext)
            new_w = max(bcol - dc0 + 1, max(1, w0 + delta_e))

        elif direction == "nw":
            delta_n = round(dy_cells)
            if delta_n < 0:
                max_ext = 0
                for r in range(dr0 - 1, -1, -1):
                    if any((r, dc0 + c) in occ for c in range(w0)):
                        break
                    max_ext += 1
                delta_n = max(delta_n, -max_ext)
            raw_dr = dr0 + delta_n
            new_dr = max(0, min(raw_dr, brow))
            new_h = max(1, dr0 + h0 - new_dr)
            dr_w, dc_w, w_w, h_w = new_dr, dc0, w0, new_h
            delta_w = round(dx_cells)
            if delta_w < 0:
                max_ext = 0
                for c in range(dc_w - 1, -1, -1):
                    if any((dr_w + r, c) in occ for r in range(h_w)):
                        break
                    max_ext += 1
                delta_w = max(delta_w, -max_ext)
            raw_dc = dc_w + delta_w
            new_dc = max(0, min(raw_dc, bcol))
            new_w = max(1, dc_w + w_w - new_dc)
            new_dr = dr_w
        else:
            return

        # 网格边界最终夹紧
        new_dc = max(0, min(new_dc, GRID_COLS - 1))
        new_dr = max(0, min(new_dr, GRID_ROWS - 1))
        new_w = max(1, min(new_w, GRID_COLS - new_dc))
        new_h = max(1, min(new_h, GRID_ROWS - new_dr))

        new_shape = (new_w, new_h, new_dc, new_dr)
        if self._manual_shapes.get(uid) != new_shape:
            self._manual_shapes[uid] = new_shape
            self._draw()

    def _on_drag_end(self, event: tk.Event) -> None:
        btn = getattr(event, "num", 1)
        if self._phantom_draw_state is not None:
            pds = self._phantom_draw_state
            if btn != pds.get("button", 1):
                return
            sr, sc = pds["start_row"], pds["start_col"]
            cr, cc = pds["cur_row"], pds["cur_col"]
            min_r, max_r = min(sr, cr), max(sr, cr)
            min_c, max_c = min(sc, cc), max(sc, cc)
            dq = pds.get("default_quality")
            use_infer = bool(pds.get("phantom_infer"))
            self._create_phantom(
                min_r,
                min_c,
                max_c - min_c + 1,
                max_r - min_r + 1,
                default_phantom_quality=dq,
                use_infer_quality=use_infer,
            )
            self._phantom_draw_state = None
            self._refresh()
        elif self._drag_state:
            if self._drag_state.get("button", 1) != btn:
                return
            self._drag_state = None
            self._refresh()

    def _find_item_at(self, row: int, col: int) -> Optional[str]:
        """返回覆盖 (row, col) 的物品 UID（含幽灵），无则 None。"""
        for uid, k in self.state.items.items():
            if k.box_id is None:
                continue
            sc, sr = self._effective_display_origin(uid, k)
            w, h = self._effective_shape_wh(uid, k)
            if sr <= row < sr + h and sc <= col < sc + w:
                return uid
        # 幽灵物品（始终有 _manual_shapes 记录）
        for phid in self._phantom_items:
            if phid not in self._manual_shapes:
                continue
            w, h, dc, dr = self._manual_shapes[phid]
            if dr <= row < dr + h and dc <= col < dc + w:
                return phid
        return None

    # ── 候选弹窗 ──────────────────────────────────────────────────────────

    def _reopen_item_candidate_popup(self, uid: str, sx: int, sy: int) -> None:
        """品质/幽灵偏好变更后重开弹窗（避免幽灵已被 reconcile 删掉时 KeyError）。"""
        k = self._phantom_items.get(uid) or self.state.items.get(uid)
        if k:
            self._show_popup(uid, k, sx, sy)

    def _show_popup(
        self,
        uid: str,
        k: ItemKnowledge,
        mouse_x: int = 200,
        mouse_y: int = 200,
    ) -> None:
        popup = tk.Toplevel(self.root)
        popup.title(f"物品候选  BoxId={k.box_id}")
        popup.transient(self.root)
        popup.configure(bg="#f5f5f8")

        # 弹窗尺寸（含幽灵品质行）
        pw, ph = 580, 400

        # 让 tkinter 先完成布局，再读屏幕尺寸
        popup.update_idletasks()
        sw = popup.winfo_screenwidth()
        sh = popup.winfo_screenheight()

        # 以鼠标位置为中心弹出，并确保不超出屏幕边界
        ox = mouse_x - pw // 2
        oy = mouse_y - ph // 2
        if ox + pw > sw:
            ox = max(0, sw - pw)
        if oy + ph > sh:
            oy = max(0, sh - ph)
        ox = max(0, ox)
        oy = max(0, oy)

        popup.geometry(f"{pw}x{ph}+{ox}+{oy}")
        popup.grab_set()

        # ── 标题行 ──────────────────────────────────────────────────────
        hdr_parts = []
        if k.shape:
            hdr_parts.append(f"形状: {fmt_shape(k.shape)}")
        elif uid in self._manual_shapes:
            mw, mh, mdc, mdr = self._manual_shapes[uid]
            tag = "手动画框" if uid in self._phantom_items else "手动设置"
            hdr_parts.append(f"形状: {mw}x{mh}（{tag}，精确匹配）")
        elif uid in self._infer_shapes:
            iw, ih, _, _ = self._infer_shapes[uid]
            hdr_parts.append(f"形状: {iw}x{ih}（推算，非日志锁定）")
        elif k.box_id is not None:
            max_w, max_h = self._compute_max_size(uid, k)
            if max_w < GRID_COLS or max_h < GRID_ROWS:
                hdr_parts.append(f"形状: ≤{max_w}x{max_h}（推断上界，非精确）")
        display_quality = self._display_quality(uid, k)
        if k.quality is not None:
            hdr_parts.append(f"品质: Q{k.quality}")
        elif uid in self._phantom_items:
            pq = self._phantom_quality_pref.get(uid)
            if pq == PHANTOM_Q_INFER:
                if display_quality:
                    hdr_parts.append(f"品质: Q{display_quality}（推断）")
                else:
                    hdr_parts.append("品质: 原推断（含金/红等可能）")
            elif isinstance(pq, int) and 1 <= pq <= 6:
                hdr_parts.append(f"品质: Q{pq}（幽灵指定）")
            else:
                hdr_parts.append("品质: Q5（金默认）")
        elif display_quality:
            if self._unknown_quality_pref_eligible(uid, k) and isinstance(
                self._unknown_cell_quality_pref.get(uid), int
            ):
                hdr_parts.append(f"品质: Q{display_quality}（候选筛选）")
            else:
                hdr_parts.append(f"品质: Q{display_quality}（唯一补齐）")
        if k.categories:
            cats = " / ".join(
                CATEGORY_NAMES.get(c, str(c)) for c in sorted(k.categories)
            )
            hdr_parts.append(f"类别: {cats}")
        if k.item_cid:
            hdr_parts.append(f"CID: {k.item_cid}")
        hdr_text = "    |    ".join(hdr_parts) if hdr_parts else "（属性未知）"

        q = display_quality or 0
        hdr_bg = QUALITY_BG.get(q, "#888888")
        tk.Label(
            popup,
            text=hdr_text,
            bg=hdr_bg,
            fg="#ffffff",
            font=("微软雅黑", 10, "bold"),
            pady=6,
            padx=10,
            anchor="w",
        ).pack(fill="x")

        # 幽灵物品：默认金（Q5）；取消勾选或选「原推断」恢复含金/红等原推断；下拉可指定其它 Q
        if uid in self._phantom_items:
            pq0 = self._phantom_quality_pref.get(uid)
            ph_ex = k.excluded_qualities or set()
            pick_ph = self._hand_pickable_qualities(k)
            show_gold_default = 5 not in ph_ex
            combo_vals_list: List[str] = []
            if show_gold_default:
                combo_vals_list.append("金默认（Q5）")
            combo_vals_list.append("原推断（含金/红）")
            combo_vals_list.extend(f"Q{q}" for q in pick_ph)
            combo_vals = tuple(combo_vals_list)

            if pq0 == PHANTOM_Q_INFER:
                combo_init = "原推断（含金/红）"
            elif isinstance(pq0, int) and pq0 in pick_ph:
                combo_init = f"Q{pq0}"
            elif isinstance(pq0, int) and show_gold_default and pq0 == 5:
                combo_init = "金默认（Q5）"
            else:
                combo_init = "原推断（含金/红）"

            def _phantom_q_apply_and_reopen() -> None:
                self._validate_manual_confirmations()
                self._refresh()
                sx, sy = mouse_x, mouse_y
                try:
                    popup.grab_release()
                except tk.TclError:
                    pass
                popup.destroy()
                self.root.after(
                    20,
                    lambda u=uid, x=sx, y=sy: self._reopen_item_candidate_popup(u, x, y),
                )

            q_block = tk.Frame(popup, bg="#e8f4ff")
            q_block.pack(fill="x", padx=8, pady=(4, 2))
            if show_gold_default:
                chk_var = tk.IntVar(value=0 if pq0 == PHANTOM_Q_INFER else 1)

                def _on_phantom_gold_chk() -> None:
                    if chk_var.get() == 0:
                        self._phantom_quality_pref[uid] = PHANTOM_Q_INFER
                    else:
                        self._phantom_quality_pref.pop(uid, None)
                    _phantom_q_apply_and_reopen()

                tk.Checkbutton(
                    q_block,
                    text="金品质（Q5）默认",
                    variable=chk_var,
                    command=_on_phantom_gold_chk,
                    bg="#e8f4ff",
                    fg="#223344",
                    activebackground="#e8f4ff",
                    font=("微软雅黑", 9),
                ).pack(side="left", padx=(0, 8))

            q_var = tk.StringVar(value=combo_init)
            cb = ttk.Combobox(
                q_block,
                textvariable=q_var,
                width=16,
                state="readonly",
                font=("微软雅黑", 9),
                values=combo_vals,
            )

            def _on_phantom_q_selected(_evt: tk.Event) -> None:
                try:
                    self.root.update_idletasks()
                except tk.TclError:
                    pass
                try:
                    val = _evt.widget.get()
                except tk.TclError:
                    return
                if val == "金默认（Q5）":
                    self._phantom_quality_pref.pop(uid, None)
                elif val == "原推断（含金/红）":
                    self._phantom_quality_pref[uid] = PHANTOM_Q_INFER
                elif val and val[0] == "Q" and len(val) >= 2:
                    self._phantom_quality_pref[uid] = int(val[1:])
                else:
                    return
                pk = self._phantom_items.get(uid)
                if pk and not self._candidate_items_for_grid(uid, pk):
                    self._phantom_quality_pref[uid] = PHANTOM_Q_INFER
                    messagebox.showwarning(
                        "幽灵品质",
                        "当前形状/类别/扫描排除等约束下没有匹配该品质的物品，已改为「原推断」式筛选。",
                    )
                _phantom_q_apply_and_reopen()

            cb.bind("<<ComboboxSelected>>", _on_phantom_q_selected)
            cb.pack(side="left", padx=4)
            if show_gold_default:
                tk.Label(
                    q_block,
                    text="取消勾选=原推断",
                    bg="#e8f4ff",
                    fg="#556677",
                    font=("微软雅黑", 8),
                ).pack(side="left", padx=6)
            elif ph_ex:
                tk.Label(
                    q_block,
                    text="已排除品质以下拉为准（与全图扫描一致）",
                    bg="#e8f4ff",
                    fg="#556677",
                    font=("微软雅黑", 8),
                ).pack(side="left", padx=6)

        # 日志物品品质未知：下拉筛选候选品质（不限 = 与原先多品质候选一致）
        elif self._unknown_quality_pref_eligible(uid, k):
            self._sanitize_unknown_quality_prefs()
            uq0 = self._unknown_cell_quality_pref.get(uid)
            pickable = self._hand_pickable_qualities(k)

            def _unknown_q_apply_and_reopen() -> None:
                self._validate_manual_confirmations()
                self._refresh()
                sx, sy = mouse_x, mouse_y
                try:
                    popup.grab_release()
                except tk.TclError:
                    pass
                popup.destroy()
                self.root.after(
                    20,
                    lambda u=uid, x=sx, y=sy: self._reopen_item_candidate_popup(u, x, y),
                )

            u_block = tk.Frame(popup, bg="#fff4e8")
            u_block.pack(fill="x", padx=8, pady=(4, 2))
            tk.Label(
                u_block,
                text="候选品质:",
                bg="#fff4e8",
                fg="#223344",
                font=("微软雅黑", 9),
            ).pack(side="left", padx=(0, 6))
            combo_vals_u = ("不限品质",) + tuple(f"Q{q}" for q in pickable)
            if isinstance(uq0, int) and 1 <= uq0 <= 6 and uq0 in pickable:
                combo_init_u = f"Q{uq0}"
            else:
                combo_init_u = "不限品质"
            uq_var = tk.StringVar(value=combo_init_u)
            cb_u = ttk.Combobox(
                u_block,
                textvariable=uq_var,
                width=14,
                state="readonly",
                font=("微软雅黑", 9),
                values=combo_vals_u,
            )

            def _on_unknown_q_selected(_evt: tk.Event) -> None:
                try:
                    self.root.update_idletasks()
                except tk.TclError:
                    pass
                try:
                    val = _evt.widget.get()
                except tk.TclError:
                    return
                if val == "不限品质":
                    self._unknown_cell_quality_pref.pop(uid, None)
                elif val and val[0] == "Q" and len(val) >= 2:
                    self._unknown_cell_quality_pref[uid] = int(val[1:])
                else:
                    return
                kk = self.state.items.get(uid)
                if kk and not self._candidate_items_for_grid(uid, kk):
                    self._unknown_cell_quality_pref.pop(uid, None)
                    messagebox.showwarning(
                        "候选品质",
                        "当前形状/类别/扫描排除等约束下没有匹配该品质的物品，已恢复为「不限品质」。",
                    )
                _unknown_q_apply_and_reopen()

            cb_u.bind("<<ComboboxSelected>>", _on_unknown_q_selected)
            cb_u.pack(side="left", padx=4)

        # ── 过滤候选（含负向约束 + 最大尺寸推断） ──────────────────────────
        candidates = self._candidate_items_for_grid(uid, k)
        candidates.sort(key=lambda i: -i.base_value)
        candidate_probs = candidate_probabilities(
            candidates,
            map_category_weights=self._map_category_weights,
            map_id=self.state.map_id,
        )
        prob_source = probability_source_label(candidates, self.state.map_id)

        # ── 统计摘要 ────────────────────────────────────────────────────
        n = len(candidates)
        if n > 1:
            prices = [i.base_value for i in candidates]
            min_p, max_p = min(prices), max(prices)
            _best, _count, _unique, weighted_est, weighted_label = (
                self._query_item_for_grid(uid, k)
            )
            weighted_text = (
                f"{weighted_label}: ¥{weighted_est:,.0f}    "
                if weighted_est is not None
                else ""
            )
            stat_text = (
                f"共 {n} 个候选    "
                f"{weighted_text}"
                f"范围: ¥{min_p:,} ~ ¥{max_p:,}    概率: {prob_source}"
            )
        elif n == 1:
            stat_text = (
                f"唯一确定: {candidates[0].name}    "
                f"¥{candidates[0].base_value:,}    概率: {prob_source}"
            )
        else:
            stat_text = "无匹配候选"

        tk.Label(
            popup,
            text=stat_text,
            bg="#ebebf0",
            fg="#444455",
            font=("微软雅黑", 9),
            pady=4,
            padx=8,
            anchor="w",
        ).pack(fill="x")

        # ── 已排除类别 ──────────────────────────────────────────────────
        if k.excluded_categories:
            excl_names = " / ".join(
                CATEGORY_NAMES.get(c, str(c)) for c in sorted(k.excluded_categories)
            )
            tk.Label(
                popup,
                text=f"  已排除类别（{len(k.excluded_categories)}个）: {excl_names}",
                bg="#f5e8e8",
                fg="#883333",
                font=("微软雅黑", 8),
                pady=3,
                padx=10,
                anchor="w",
            ).pack(fill="x")

        # ── 候选列表 ────────────────────────────────────────────────────
        frame = tk.Frame(popup, bg="#f5f5f8")
        frame.pack(fill="both", expand=True, padx=8, pady=(5, 3))

        cols_def = [
            ("名称", 125, "w"),
            ("品质", 45, "center"),
            ("形状", 50, "center"),
            ("类别", 120, "w"),
            ("概率", 65, "e"),
            ("价格", 75, "e"),
        ]
        tree = ttk.Treeview(
            frame,
            columns=[c[0] for c in cols_def],
            show="headings",
            height=10,
        )
        style = ttk.Style()
        style.configure("Treeview", font=("微软雅黑", 9), rowheight=20)
        style.configure("Treeview.Heading", font=("微软雅黑", 9, "bold"))

        for col_name, width, anchor in cols_def:
            tree.heading(col_name, text=col_name)
            tree.column(col_name, width=width, anchor=anchor, minwidth=40)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        # 用颜色区分价格高低（高于中位价的标黄，最高价标橙）
        median_val = (
            statistics.median([i.base_value for i in candidates]) if n > 1 else 0
        )
        top_val = candidates[0].base_value if candidates else 0
        tree.tag_configure("top", background="#ffe4b0")
        tree.tag_configure("valuable", background="#ffd6d6")
        tree.tag_configure("high", background="#fffff0")
        tree.tag_configure("normal", background="#ffffff")
        tree.tag_configure("confirmed", background="#d9f7d9")

        iid_to_item: Dict[str, CsvItem] = {}
        selected_iid: Optional[str] = None
        confirmed_cid = k.manual_confirm_item_id
        for item in candidates:
            cat_str = " / ".join(
                CATEGORY_NAMES.get(c, str(c)) for c in item.category_tags
            )
            if confirmed_cid and item.item_id == confirmed_cid:
                tag = "confirmed"
            elif item.base_value >= HIGH_VALUE_THRESHOLD:
                tag = "valuable"
            elif item.base_value == top_val and n > 1:
                tag = "top"
            elif item.base_value >= median_val:
                tag = "high"
            else:
                tag = "normal"
            iid = tree.insert(
                "",
                "end",
                values=(
                    item.name,
                    f"Q{item.quality}",
                    fmt_shape(item.shape),
                    cat_str,
                    f"{candidate_probs.get(item.item_id, 0.0) * 100:.2f}%",
                    f"¥{item.base_value:,}",
                ),
                tags=(tag,),
            )
            iid_to_item[iid] = item
            if confirmed_cid and item.item_id == confirmed_cid:
                selected_iid = iid

        status_var = tk.StringVar(
            value="双击候选可确认；确认后将用于价格/估算/品质显示。"
        )

        def _update_status_from_item(item: CsvItem, confirmed: bool = False) -> None:
            if confirmed:
                status_var.set(
                    f"已确认：{item.name}  Q{item.quality}  ¥{item.base_value:,}"
                )
            else:
                status_var.set(
                    f"当前选择：{item.name}  Q{item.quality}  ¥{item.base_value:,}"
                )

        def _on_select(_event: tk.Event) -> None:
            sel = tree.selection()
            if not sel:
                return
            item = iid_to_item.get(sel[0])
            if item:
                _update_status_from_item(item, confirmed=False)

        def _confirm_selected(_event: Optional[tk.Event] = None) -> None:
            sel = tree.selection()
            if not sel:
                return
            item = iid_to_item.get(sel[0])
            if item is None:
                return
            k.manual_confirm_item_id = item.item_id
            self._refresh()
            popup.destroy()

        def _clear_confirmation() -> None:
            if k.manual_confirm_item_id is None:
                popup.destroy()
                return
            k.manual_confirm_item_id = None
            self._refresh()
            popup.destroy()

        tree.bind("<<TreeviewSelect>>", _on_select)
        tree.bind("<Double-1>", _confirm_selected)
        if selected_iid is not None:
            tree.selection_set(selected_iid)
            tree.focus(selected_iid)
            tree.see(selected_iid)
            confirmed_item = iid_to_item.get(selected_iid)
            if confirmed_item:
                _update_status_from_item(confirmed_item, confirmed=True)
        elif candidates:
            first = tree.get_children()[0]
            tree.selection_set(first)
            tree.focus(first)

        # ── 关闭按钮 ────────────────────────────────────────────────────
        tk.Label(
            popup,
            textvariable=status_var,
            bg="#eef3ff",
            fg="#334466",
            font=("微软雅黑", 9),
            pady=4,
            padx=10,
            anchor="w",
        ).pack(fill="x", padx=8, pady=(0, 3))

        btn_frame = tk.Frame(popup, bg="#f5f5f8")
        btn_frame.pack(pady=4)
        tk.Button(
            btn_frame,
            text="确认所选后选项",
            command=_confirm_selected,
            font=("微软雅黑", 9),
            relief="flat",
            bg="#2f8f46",
            fg="white",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=4)
        tk.Button(
            btn_frame,
            text="取消确认",
            command=_clear_confirmation,
            font=("微软雅黑", 9),
            relief="flat",
            bg="#8f5f2f",
            fg="white",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=4)
        tk.Button(
            btn_frame,
            text="  关  闭  ",
            command=popup.destroy,
            font=("微软雅黑", 9),
            relief="flat",
            bg="#5566aa",
            fg="white",
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=4)

    # ── 启动 ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """启动 tkinter 主循环（阻塞直到窗口关闭）。"""
        self.root.mainloop()
