#!/usr/bin/env python3
"""Fresh BidKing automation loop.

- 整窗 / 区域 OCR 识别大厅、结束、回合等界面状态；
- 固定流程：每回合先 OCR ``bid_confirm_region`` 见「出价」→ 道具 → 截图 OCR → :func:`compute_price`（读画板快照）→ 输入出价 → 确认；确认以快照 ``C2S_34_game_bid`` 为准（可配置重试间隔）；
- 若 OCR 见到「对局结束」等，执行固定的局后点击链。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

import pyautogui
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent

from ..pricing.compute import compute_price as pricing_compute_price  # noqa: E402
from ..pricing.snapshot_io import resolve_effective_round  # noqa: E402
from .board_snapshot_util import (  # noqa: E402
    clear_board_snapshot_file,
    current_round_from_snapshot,
    game_uid_from_snapshot,
    load_board_snapshot_for_loop,
)
from .window import capture_window_frame, find_window, scale_point  # noqa: E402
from ..config.map_runtime_overlay import (  # noqa: E402
    automation_maps_sorted_keys,
    resolve_automation_map_config_key,
)
from ..config.paths import config_overlay_path  # noqa: E402
from ..config.pricing import deep_merge  # noqa: E402
from ..logsys.app_log import append_app_log, log_timestamp, set_app_log_file  # noqa: E402
from ..logsys.perf_log import perf_log, perf_log_elapsed  # noqa: E402
from ..parsing.asset_amount import (  # noqa: E402
    map_entry_money_by_map_key,
    parse_asset_amount_from_bidking_home,
    parse_uid_from_home_full_window,
)
from ..pricing._self_uid_inference import persist_self_user_uid_to_config  # noqa: E402

# 参考客户端 1920×1080：出价状态文案区（「已出价」/「弃权」等）
DEFAULT_BID_CONFIRM_REGION = {"left": 704, "top": 962, "width": 303, "height": 75}
try:
    import ctypes
    import ctypes.wintypes as wt

    USER32 = ctypes.windll.user32
except Exception:  # pragma: no cover - only used on Windows desktops.
    USER32 = None
    wt = None

_STOP_EVENT = threading.Event()

HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class StopRequested(RuntimeError):
    pass


def request_stop() -> None:
    _STOP_EVENT.set()


def reset_stop() -> None:
    _STOP_EVENT.clear()


def stop_requested() -> bool:
    return _STOP_EVENT.is_set()


_GUI_LOG_VERBOSE = False


def set_gui_log_verbose(verbose: bool) -> None:
    """GUI 日志：为 True 时显示点击/OCR/轮询等详细行（见 log(..., gui_verbose_only=True)）。"""
    global _GUI_LOG_VERBOSE
    _GUI_LOG_VERBOSE = bool(verbose)


def gui_log_verbose() -> bool:
    return _GUI_LOG_VERBOSE


def _poll_f9_stop_hotkey() -> None:
    """全局热键：按下 F9 时请求停止（依赖 ensure_not_stopped / sleep_interruptible 抛出 StopRequested）。"""
    if USER32 is None:
        return
    try:
        # VK_F9 = 0x78；高位表示当前处于按下状态。
        if int(USER32.GetAsyncKeyState(0x78)) & 0x8000:
            request_stop()
    except Exception:
        pass


def ensure_not_stopped() -> None:
    _poll_f9_stop_hotkey()
    if stop_requested():
        raise StopRequested()


def maybe_shutdown_system_after_run_completed(config: dict[str, Any]) -> None:
    """达到计划局数正常结束后，按配置调度 Windows 关机（可用 ``shutdown /a`` 取消）。"""
    auto = config.get("automation") or {}
    if not bool(auto.get("shutdown_after_run_enabled", False)):
        return
    try:
        delay = max(0, int(auto.get("shutdown_after_run_delay_seconds", 60)))
    except (TypeError, ValueError):
        delay = 60
    if sys.platform != "win32":
        log(f"shutdown_after_run: 非 Windows，已跳过关机（delay={delay}s）")
        return
    log(
        f"已达目标局数，{delay} 秒后关机；"
        "可在命令行执行 shutdown /a 取消",
    )
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["shutdown", "/s", "/t", str(delay)],
            check=False,
            creationflags=flags,
        )
    except Exception as exc:
        log(f"shutdown_after_run: 调度关机失败: {type(exc).__name__}: {exc}")


def _on_target_runs_reached(config: dict[str, Any]) -> None:
    log("target runs reached; exit")
    maybe_shutdown_system_after_run_completed(config)


def sleep_interruptible(seconds: float, step: float = 0.05) -> None:
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        ensure_not_stopped()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(float(step), remaining))


CHINESE_ROUND_NUMBERS = {
    "一": 1,
    "壹": 1,
    "二": 2,
    "两": 2,
    "贰": 2,
    "三": 3,
    "叁": 3,
    "四": 4,
    "肆": 4,
    "五": 5,
    "伍": 5,
    "I": 1,
    "Ⅰ": 1,
    "l": 1,
    "丨": 1,
    "II": 2,
    "Ⅱ": 2,
    "III": 3,
    "Ⅲ": 3,
    "IV": 4,
    "Ⅳ": 4,
    "V": 5,
    "Ⅴ": 5,
    "六": 6,
    "陆": 6,
    "VI": 6,
    "Ⅵ": 6,
}

# OCR / 主循环识别的最大回合（第五回合同价可加赛第六轮）
MAX_PARSED_ROUND_NO = 6
# 第 6 轮及以后（含加赛）一律不使用道具，与 ``automation.tool_rounds`` 无关
NO_TOOL_FROM_ROUND = 6


@dataclass
class CaptureResult:
    text: str
    image_path: Path | None


@dataclass
class Observation:
    """轮询/回合 OCR 结果与界面布尔信号；整窗原文在 ``capture.text``。"""
    capture: CaptureResult
    round_no: int | None
    end_prompt: bool
    reward_continue: bool
    failed_auction_settlement: bool
    auction_lobby: bool
    home_bid_button: bool
    has_any_signal: bool


class EndPromptDetected(RuntimeError):
    def __init__(self, source: str):
        super().__init__(source)
        self.source = source


def log(message: str, *, gui_verbose_only: bool = False) -> None:
    line = f"[{log_timestamp()}] {message}"
    if gui_verbose_only and not _GUI_LOG_VERBOSE:
        append_app_log(line)
        return
    print(line, flush=True)


def _log_aisha_vacant_gate(message: str) -> None:
    """艾莎第 4 回合道具空置门控：GUI 运行日志 + ``fresh_aisha_bot.log`` 等应用日志文件。"""
    line = f"[aisha_vacant_gate] {message}"
    # GUI 将 ``log`` 换成 GuiLogger（只写文本框、不走 stdout tee），需显式 append_app_log。
    if type(log).__name__ == "GuiLogger":
        log(line)
        append_app_log(f"[{log_timestamp()}] {line}")
    else:
        log(line)


def format_bid_details_line(details: dict[str, Any]) -> str:
    """将 :func:`compute_price` 返回的 ``details`` 压成单行，便于控制台查看出价链路。"""
    parts: list[str] = []
    role = details.get("role")
    if role:
        parts.append(f"role={role}")
    fr = details.get("final_round_used")
    if fr is not None:
        parts.append(f"eff_round={fr}")
    if details.get("fallback"):
        parts.append("fallback")
    reason = str(details.get("reason") or "").strip()
    if reason:
        parts.append(f"reason={reason}" if len(reason) <= 140 else f"reason={reason[:137]}...")

    bb = details.get("board_snapshot_bid")
    if isinstance(bb, dict):
        src = bb.get("bid_points_source")
        if src:
            parts.append(f"src={src}")
        pts = bb.get("points")
        if pts is not None:
            parts.append(f"base_pts={pts}")
        vac = bb.get("vacant_red_floor_ceiling_pick")
        if isinstance(vac, dict) and vac.get("applied"):
            parts.append(
                f"vac_pick->{vac.get('chosen_points')} "
                f"(infer_red={vac.get('has_red_inferred')})"
            )

    br = details.get("bid_ratio")
    if isinstance(br, dict):
        ratio_raw = br.get("ratio")
        try:
            ratio_f = float(ratio_raw) if ratio_raw is not None else 1.0
        except (TypeError, ValueError):
            ratio_f = 1.0
        if abs(ratio_f - 1.0) > 1e-9:
            parts.append(f"ratio x{ratio_raw} ({br.get('before')}->{br.get('after')})")

    opp = details.get("opponent_bid")
    if isinstance(opp, dict):
        if opp.get("applied"):
            parts.append(
                f"opp {opp.get('tag')} o_prev={opp.get('o_prev')} "
                f"{opp.get('before')}->{opp.get('after')}"
            )
        elif opp.get("o_prev") is not None:
            parts.append(f"opp idle o_prev={opp.get('o_prev')}")

    ceil = details.get("ceiling_points")
    if isinstance(ceil, dict) and ceil.get("applied"):
        extra = " clamped" if ceil.get("clamped") else ""
        parts.append(f"ceil{extra} {ceil.get('before')}->{ceil.get('after')}")

    ht = details.get("human_price_tail")
    if isinstance(ht, dict):
        parts.append(f"tail[{ht.get('pattern')}] {ht.get('before')}->{ht.get('after')}")

    erf = details.get("early_round_fallback_floor")
    if isinstance(erf, dict) and erf.get("applied"):
        parts.append(f"early_floor {erf.get('before')}->{erf.get('after')}")

    lrs = details.get("late_round_low_bid_surrender")
    if isinstance(lrs, dict) and lrs.get("applied"):
        parts.append(f"surrender {lrs.get('before')}->{lrs.get('after')}")

    bc = details.get("bid_cap")
    if isinstance(bc, dict) and bc.get("applied"):
        parts.append(f"bid_cap->{bc.get('cap_price')}")

    sig = details.get("express_emoji_signal")
    if isinstance(sig, dict):
        if sig.get("price_mode") == "public_blacklist_force":
            parts.append(
                f"emoji_force_bid={sig.get('forced_bid')} "
                f"self_cid={sig.get('self_emoji_cid')} opp_cid={sig.get('opponent_emoji_cid')}"
            )
        elif sig.get("price_mode") == "random":
            lo, hi = sig.get("random_lo"), sig.get("random_hi")
            range_note = (
                f" range={lo}-{hi}" if lo is not None and hi is not None else ""
            )
            r1 = sig.get("round1_signal_bid")
            r1_note = f" r1={r1}" if r1 is not None else ""
            parts.append(
                f"emoji_random={sig.get('random_price')}{range_note}{r1_note} "
                f"self_cid={sig.get('self_emoji_cid')} opp_cid={sig.get('opponent_emoji_cid')}"
            )
        else:
            pick = "random" if sig.get("seat_random_pick") else "fixed"
            parts.append(
                f"emoji_seat={sig.get('seat')}({pick}) price={sig.get('seat_price')} "
                f"self_cid={sig.get('self_emoji_cid')} opp_cid={sig.get('opponent_emoji_cid')}"
            )

    return " | ".join(parts) if parts else "(empty details)"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_merged_bot_config(overlay_path: Path) -> dict[str, Any]:
    """``runtime.json`` 为基底，``overlay_path``（通常为 ``config.json``）覆盖。"""
    from ..config.paths import runtime_path
    from ..config.runtime import apply_board_snapshot_env_overrides

    rp = runtime_path()
    base: dict[str, Any] = {}
    if rp.is_file():
        base = load_json(rp)
    overlay: dict[str, Any] = {}
    if overlay_path.is_file():
        overlay = load_json(overlay_path)
    merged = deep_merge(base, overlay)
    apply_board_snapshot_env_overrides(merged)
    return merged


def persist_overlay_patch(overlay_path: Path, patch: dict[str, Any]) -> None:
    existing: dict[str, Any] = {}
    if overlay_path.is_file():
        existing = load_json(overlay_path)
    merged_overlay = deep_merge(existing, patch)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(
        json.dumps(merged_overlay, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _automation_run_schedule(
    auto: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, int, int, float]:
    """解析链式地图计划（见 ``bidking.config.map_chain``）。"""
    from ..config.map_chain import automation_run_schedule

    return automation_run_schedule(auto)


def refresh_poll_loop_locals(config: dict[str, Any]) -> dict[str, Any]:
    """从 config 读取轮询间隔、地图与回合限制等，便于与 GUI 写入的 config.json 同步。"""
    timing = config.get("timing") or {}
    auto = config.get("automation") or {}
    safety = config.get("safety") or {}
    stuck = safety.get("stuck_after_handled_round") or {}
    map_chain, runs_per_big_cycle, run_cycles, max_runs, cycle_rest_minutes = (
        _automation_run_schedule(auto)
    )
    first_map = str(map_chain[0]["map_id"]) if map_chain else resolve_automation_map_config_key(auto)
    return {
        "poll_seconds": float(timing.get("poll_seconds", 1.0)),
        "transition_debounce": float(timing.get("transition_debounce_seconds", 8.0)),
        "reward_continue_debounce": float(timing.get("reward_continue_debounce_seconds", 1.0)),
        "unknown_escape_cooldown": float(auto.get("unknown_escape_cooldown_seconds", 2.0)),
        "post_confirm_escape_block_seconds": float(auto.get("post_confirm_escape_block_seconds", 30.0)),
        "stuck_handled_enabled": bool(stuck.get("enabled", True)),
        "stuck_handled_threshold": max(1, int(stuck.get("consecutive_poll_threshold", 60))),
        "selected_map": first_map,
        "map_chain": map_chain,
        "runs_per_big_cycle": runs_per_big_cycle,
        "runs_per_cycle": runs_per_big_cycle,
        "run_cycles": run_cycles,
        "cycle_rest_minutes": cycle_rest_minutes,
        "max_runs": max_runs,
        "game_start_timeout_seconds": float(auto.get("game_start_timeout_seconds", 60.0)),
        "map_select_no_start_esc_after": max(1, int(auto.get("map_select_no_start_esc_after", 3))),
    }


def apply_pyautogui_from_config(config: dict[str, Any]) -> None:
    safety = config.get("safety") or {}
    pyautogui.FAILSAFE = bool(safety.get("failsafe", True))
    pyautogui.PAUSE = float(safety.get("move_pause_seconds", 0.08))


def _humanize_merged(config: dict[str, Any]) -> dict[str, Any]:
    """拟人化参数：``config["humanize"]`` 覆盖默认值；``enabled: false`` 关闭轨迹/抖动/输入随机间隔。"""
    defaults: dict[str, Any] = {
        "enabled": True,
        "click_jitter_pixels": 3,
        "move_duration_min": 0.07,
        "move_duration_max": 0.38,
        "move_steps_min": 3,
        "move_steps_max": 10,
        "arc_strength_min": 0.35,
        "arc_strength_max": 1.25,
        "pre_click_delay_min": 0.0,
        "pre_click_delay_max": 0.07,
        "price_char_interval_min": 0.038,
        "price_char_interval_max": 0.11,
        "price_stutter_probability": 0.11,
        "price_stutter_extra_min": 0.1,
        "price_stutter_extra_max": 0.42,
        "pre_select_all_delay_min": 0.02,
        "pre_select_all_delay_max": 0.12,
        "post_select_all_delay_scale_min": 0.85,
        "post_select_all_delay_scale_max": 1.35,
    }
    raw = config.get("humanize")
    if not isinstance(raw, dict):
        return dict(defaults)
    out = dict(defaults)
    for key, val in raw.items():
        out[key] = val
    return out


def _jitter_screen_point(x: int, y: int, jitter_px: float) -> tuple[int, int]:
    if jitter_px <= 0:
        return x, y
    j = float(jitter_px)
    return int(round(x + random.uniform(-j, j))), int(round(y + random.uniform(-j, j)))


def _quad_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    x = u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0]
    y = u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1]
    return x, y


def human_move_to_screen(config: dict[str, Any], x: int, y: int) -> None:
    """带弧度的分段移动，接近真实鼠标轨迹（非瞬时直线）。"""
    ensure_not_stopped()
    h = _humanize_merged(config)
    tx, ty = float(x), float(y)
    if not h["enabled"]:
        pyautogui.moveTo(int(x), int(y), duration=0.05, tween=pyautogui.linear)
        return
    cx, cy = map(float, pyautogui.position())
    dx, dy = tx - cx, ty - cy
    dist = math.hypot(dx, dy)
    if dist < 6.0:
        pyautogui.moveTo(
            int(x),
            int(y),
            duration=random.uniform(0.04, 0.12),
            tween=pyautogui.easeOutQuad,
        )
        return
    mx, my = (cx + tx) / 2.0, (cy + ty) / 2.0
    inv = 1.0 / max(dist, 1e-6)
    nx, ny = -dy * inv, dx * inv
    arc = random.uniform(float(h["arc_strength_min"]), float(h["arc_strength_max"]))
    arc *= min(dist * 0.12, 72.0)
    if random.random() < 0.5:
        arc = -arc
    p0 = (cx, cy)
    p1 = (mx + nx * arc, my + ny * arc)
    p2 = (tx, ty)
    steps = int(
        round(
            random.uniform(float(h["move_steps_min"]), float(h["move_steps_max"]))
            + min(4.0, dist / 120.0)
        )
    )
    steps = max(int(h["move_steps_min"]), min(24, steps))
    dur_total = random.uniform(float(h["move_duration_min"]), float(h["move_duration_max"]))
    dur_total *= min(1.15, max(0.35, dist / 420.0))
    dur_total = max(float(h["move_duration_min"]), min(float(h["move_duration_max"]), dur_total))
    base = dur_total / float(steps)
    for i in range(1, steps + 1):
        ensure_not_stopped()
        t = i / steps
        bx, by = _quad_bezier(p0, p1, p2, t)
        ix, iy = (int(x), int(y)) if i == steps else (int(round(bx)), int(round(by)))
        step_dur = base * random.uniform(0.85, 1.22)
        step_dur = max(0.011, min(0.26, step_dur))
        tween = pyautogui.easeOutQuad if i == steps else pyautogui.easeInOutQuad
        pyautogui.moveTo(ix, iy, duration=step_dur, tween=tween)
    # 若浮点累计导致未贴边，最后再对齐一次（通常已是最后一步）
    fx, fy = pyautogui.position()
    if abs(fx - x) > 1 or abs(fy - y) > 1:
        pyautogui.moveTo(int(x), int(y), duration=random.uniform(0.02, 0.06), tween=pyautogui.easeOutQuad)


def human_click_at_screen(
    config: dict[str, Any],
    x: int,
    y: int,
    *,
    log_detail: str = "",
) -> None:
    """先拟人移动再点击当前位置，带像素抖动与点击前微停顿。"""
    ensure_not_stopped()
    h = _humanize_merged(config)
    jx, jy = _jitter_screen_point(x, y, float(h["click_jitter_pixels"])) if h["enabled"] else (x, y)
    if log_detail:
        log(
            f"human click {log_detail}: logical=({x},{y}) jitter=({jx},{jy})",
            gui_verbose_only=True,
        )
    human_move_to_screen(config, jx, jy)
    if h["enabled"]:
        pre_lo = float(h["pre_click_delay_min"])
        pre_hi = float(h["pre_click_delay_max"])
        if pre_hi > pre_lo:
            sleep_interruptible(random.uniform(pre_lo, pre_hi))
        elif pre_hi > 0:
            sleep_interruptible(pre_hi)
    ensure_not_stopped()
    pyautogui.click()


def human_type_price_digits(config: dict[str, Any], price: int) -> None:
    """逐字符输入，随机间隔与偶发「卡顿」停顿，模拟真实敲数字。"""
    h = _humanize_merged(config)
    s = str(int(price))
    if not h["enabled"]:
        pyautogui.write(s, interval=0.02)
        return
    p_stutter = float(h["price_stutter_probability"])
    lo = float(h["price_char_interval_min"])
    hi = float(h["price_char_interval_max"])
    ex_lo = float(h["price_stutter_extra_min"])
    ex_hi = float(h["price_stutter_extra_max"])
    for ch in s:
        ensure_not_stopped()
        pyautogui.write(ch, interval=0)
        gap = random.uniform(lo, hi)
        if random.random() < p_stutter:
            gap += random.uniform(ex_lo, ex_hi)
        sleep_interruptible(gap)


def _select_all_field(config: dict[str, Any]) -> None:
    """全选输入框：拟人模式下 Ctrl 与 A 之间带短随机间隔。"""
    h = _humanize_merged(config)
    if not h["enabled"]:
        pyautogui.hotkey("ctrl", "a")
        return
    pyautogui.keyDown("ctrl")
    sleep_interruptible(random.uniform(0.018, 0.055))
    ensure_not_stopped()
    pyautogui.press("a")
    sleep_interruptible(random.uniform(0.02, 0.05))
    pyautogui.keyUp("ctrl")


def compute_price(
    config: dict[str, Any],
    *,
    config_path: Path,
    round_no: int,
    board_snapshot: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """出价计算：快递站表情暗号价优先；否则调用 ``bidking.pricing``。"""
    bs_cfg = config.get("board_snapshot") or {}
    if board_snapshot is None and bool(bs_cfg.get("enabled")):
        board_snapshot = load_board_snapshot_for_loop(config)
    signal = try_resolve_express_emoji_signal_price(
        config, board_snapshot, round_no=int(round_no)
    )
    if signal is not None:
        return signal
    return pricing_compute_price(
        config,
        config_path=config_path,
        round_no=int(round_no),
        board_snapshot=board_snapshot,
    )


def normalize_text(text: str) -> str:
    table = str.maketrans(
        {
            "０": "0",
            "１": "1",
            "２": "2",
            "３": "3",
            "４": "4",
            "５": "5",
            "６": "6",
            "７": "7",
            "８": "8",
            "９": "9",
            "Ⅰ": "I",
            "Ⅱ": "II",
            "Ⅲ": "III",
            "Ⅳ": "IV",
            "Ⅴ": "V",
        }
    )
    return (text or "").translate(table)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text))


def round_token_to_int(token: str) -> int | None:
    token = normalize_text(token).strip()
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= MAX_PARSED_ROUND_NO else None
    value = CHINESE_ROUND_NUMBERS.get(token)
    if value is not None and 1 <= value <= MAX_PARSED_ROUND_NO:
        return value
    return None


_ROUND_TOKEN_CLASS = (
    r"[1-6一二两三四五六壹贰叁肆伍陆IⅤVⅡⅢⅣⅥVI]+"
)


def parse_round_number(text: str) -> int | None:
    raw = normalize_text(text)
    patterns = [
        rf"第\s*({_ROUND_TOKEN_CLASS})\s*(?:轮|回合)",
        rf"(?:当前|现在)?(?:轮次|回合)\s*[:：]?\s*第?\s*({_ROUND_TOKEN_CLASS})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            value = round_token_to_int(match.group(1).upper())
            if value is not None:
                return value

    tight = compact_text(raw)
    for pattern in (
        rf"第({_ROUND_TOKEN_CLASS})(?:轮|回合)",
        rf"(?:轮次|回合)[:：]?第?({_ROUND_TOKEN_CLASS})",
    ):
        match = re.search(pattern, tight, flags=re.IGNORECASE)
        if match:
            value = round_token_to_int(match.group(1).upper())
            if value is not None:
                return value
    return None


def resolve_loop_round_no(
    poll_round: int | None,
    board_snapshot: dict[str, Any] | None,
) -> int | None:
    """主循环有效回合：OCR 与画板 ``current_round`` 取较大值；OCR 缺失时用快照。"""
    snap_r = (
        current_round_from_snapshot(board_snapshot)
        if isinstance(board_snapshot, dict)
        else None
    )
    if poll_round is not None:
        return resolve_effective_round(int(poll_round), board_snapshot)
    if snap_r is not None:
        return int(snap_r)
    return None


def has_end_prompt(text: str) -> bool:
    tight = compact_text(text)
    if "对局结束" in tight:
        return True
    return "对局" in tight and "结束" in tight


def has_auction_lobby(text: str) -> bool:
    tight = compact_text(text)
    if "竞拍大厅" in tight:
        return True
    return "竞拍" in tight and "大厅" in tight


def has_home_bid_button(text: str) -> bool:
    tight = compact_text(text)
    return "竞拍" in tight


def has_reward_continue(text: str) -> bool:
    tight = compact_text(text)
    return "EXP" in tight.upper() and "\u7ee7\u7eed" in tight


def has_failed_auction_settlement(text: str) -> bool:
    """流拍结算等界面：无对局结束/奖励继续文案时仍须点击关闭，否则 only ESC 易卡住。"""
    tight = compact_text(text)
    if "流拍" in tight:
        return True
    return False


def ensure_output_dir(config: dict[str, Any], config_path: Path) -> Path:
    debug = config.get("debug", {})
    raw = debug.get("runs_dir", "runs")
    path = Path(raw)
    if not path.is_absolute():
        path = config_path.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def rapidocr_once(image: Image.Image) -> str:
    from .ocr import infer_lines

    t0 = time.perf_counter()
    try:
        result = infer_lines(image)
        if not result:
            return ""
        rows = sorted(result, key=lambda item: (min(point[1] for point in item[0]), min(point[0] for point in item[0])))
        return "\n".join(str(item[1]) for item in rows)
    finally:
        perf_log_elapsed("rapidocr_once", t0)


def scaled_region_box(region: dict[str, Any], config: dict[str, Any], image_width: int, image_height: int) -> tuple[int, int, int, int]:
    reference = config.get("window", {}).get("reference_client_size", {})
    ref_width = max(1, int(reference.get("width") or image_width))
    ref_height = max(1, int(reference.get("height") or image_height))
    left = round(float(region["left"]) * image_width / ref_width)
    top = round(float(region["top"]) * image_height / ref_height)
    width = round(float(region["width"]) * image_width / ref_width)
    height = round(float(region["height"]) * image_height / ref_height)
    right = min(image_width, max(0, left + width))
    bottom = min(image_height, max(0, top + height))
    left = min(max(0, left), right)
    top = min(max(0, top), bottom)
    return int(left), int(top), int(right), int(bottom)


def read_bid_confirm_region_text_from_frame(
    config: dict[str, Any], frame: Image.Image
) -> tuple[str, tuple[int, int, int, int]]:
    """OCR ``capture.bid_confirm_region``（默认同 ``DEFAULT_BID_CONFIRM_REGION``）用于校验是否已出价。"""
    cap = config.get("capture", {}) or {}
    region = cap.get("bid_confirm_region") or DEFAULT_BID_CONFIRM_REGION
    if not isinstance(region, dict) or not region:
        return "", (0, 0, 0, 0)
    box = scaled_region_box(region, config, frame.width, frame.height)
    crop = frame.crop(box)
    text = rapidocr_once(ImageOps.grayscale(crop).convert("RGB"))
    return text, box


def _sync_home_screen_uid_to_config(
    config: dict[str, Any],
    config_path: Path,
    full_window_text: str,
) -> None:
    uid = parse_uid_from_home_full_window(full_window_text)
    if not uid:
        return
    bs = config.setdefault("board_snapshot", {})
    if not isinstance(bs, dict):
        bs = {}
        config["board_snapshot"] = bs
    bs["self_user_uid"] = uid
    if persist_self_user_uid_to_config(uid):
        log(f"主界面 UID：{uid}（已写入 {config_path.name}）")
    else:
        log(f"主界面 UID：{uid}")


def enforce_map_entry_money_on_home_screen(
    config: dict[str, Any],
    config_path: Path,
    *,
    selected_map: str,
    full_window_text: str,
    sync_home_uid: bool = True,
) -> bool:
    """主界面整窗 OCR：``BidKing`` 下资产、``UID:`` 行。

    返回 ``True`` 表示因资产不足应停止 bot；未能识别或解析异常时返回 ``False``（不抛异常，继续运行）。

    ``sync_home_uid`` 为 ``True`` 时从整窗 OCR 解析 ``UID:`` 并写入配置；bot 仅在会话内首次回到主界面时应传入 ``True``。

    ``automation.enable_map_entry_money_check`` 默认 ``True``；设为 ``False`` 时不做资产 OCR 与地图准入校验。
    """
    auto = config.get("automation") or {}
    if sync_home_uid:
        try:
            _sync_home_screen_uid_to_config(config, config_path, full_window_text)
        except Exception as exc:
            log(f"主界面 UID：同步异常（已忽略）：{exc}")
    if not bool(auto.get("enable_map_entry_money_check", True)):
        log(
            "主界面资产准入：已关闭（automation.enable_map_entry_money_check=false），跳过检查",
            gui_verbose_only=True,
        )
        return False

    try:
        current = parse_asset_amount_from_bidking_home(full_window_text)
    except Exception as exc:
        log(f"主界面当前资产：检查异常（已跳过准入检查，继续运行）：{exc}")
        return False

    if current is None:
        preview = "\n".join((full_window_text or "").splitlines()[:6])
        log(
            f"主界面当前资产：未能识别（未找到 BidKing 下方金额；OCR 前几行=\n{preview}）"
            "；跳过准入检查，继续运行"
        )
        return False

    required = map_entry_money_by_map_key(auto, selected_map)
    if required > 0:
        log(f"主界面当前资产：{current:,}（地图 {selected_map} 准入 {required:,}）")
    else:
        log(f"主界面当前资产：{current:,}")

    if required <= 0:
        return False
    if current < required:
        log(
            f"资产不足：当前 {current:,} < 地图 {selected_map} 准入 {required:,}，自动停止 bot"
        )
        return True
    return False


def has_ingame_bid_button_label_visible(text: str) -> bool:
    """``bid_confirm_region`` OCR：可出价且未提交时出现「出价」；排除「已出价」等。"""
    tight = compact_text(text)
    if not tight:
        return False
    if "已出价" in tight or "巳出价" in tight:
        return False
    if "弃权" in tight:
        return False
    return "出价" in tight


def wait_for_round_bid_button_ready_ocr(config: dict[str, Any], *, round_no: int) -> None:
    """每回合开始：轮询 :func:`read_bid_confirm_region_text_from_frame` 直至状态区出现「出价」，再进入道具/定价/输入。"""
    if bool((config.get("safety") or {}).get("skip_round_bid_button_ocr_gate", False)):
        log(f"round {round_no}: 已跳过出价状态区 OCR 门控（safety.skip_round_bid_button_ocr_gate）", gui_verbose_only=True)
        return
    cap = config.get("capture", {}) or {}
    region = cap.get("bid_confirm_region") or DEFAULT_BID_CONFIRM_REGION
    if not isinstance(region, dict) or not region:
        log(f"round {round_no}: 未配置 bid_confirm_region，跳过回合出价 OCR 门控")
        return
    timing = config.get("timing", {}) or {}
    max_sec = float(timing.get("round_bid_button_gate_max_seconds", 120.0))
    step = max(0.05, float(timing.get("round_bid_button_gate_poll_seconds", 0.4)))
    deadline = time.monotonic() + max_sec if max_sec > 0 else None
    log(f"round {round_no}: 等待 bid_confirm 区域 OCR（须识别「出价」）…", gui_verbose_only=True)
    attempt = 0
    while True:
        ensure_not_stopped()
        attempt += 1
        bring_window_to_front(config)
        t_cap = time.perf_counter()
        frame, _info = capture_window_frame(config)
        perf_log_elapsed(f"round_bid_gate capture attempt={attempt}", t_cap)
        text, _box = read_bid_confirm_region_text_from_frame(config, frame)
        tight = compact_text(text)
        if has_ingame_bid_button_label_visible(text):
            log(
                f"round {round_no}: bid_confirm 区域 OCR 就绪 text={tight!r}",
                gui_verbose_only=True,
            )
            return
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(
                f"round {round_no}: 在 {max_sec:.0f}s 内 bid_confirm 区域未见「出价」OCR（末次 text={tight!r}）"
            )
        log(
            f"round {round_no}: bid_confirm 尚未就绪 attempt={attempt} text={tight!r}；{step:.2f}s 后重试",
            gui_verbose_only=True,
        )
        sleep_interruptible(step)


def _observe_finalize_poll(
    label: str,
    *,
    t_obs: float,
    image_path: Path | None,
    full_window_text: str,
    home_bid_text: str,
) -> Observation:
    """主循环轮询：整窗 + 主页竞拍区 OCR → 布尔信号与 ``round_no``。"""
    t_parse = time.perf_counter()
    capture = CaptureResult(text=full_window_text, image_path=image_path)
    perf_log_elapsed(f"observe[{label}] capture_meta", t_parse)
    round_no = parse_round_number(full_window_text)
    failed_settlement = has_failed_auction_settlement(full_window_text)

    any_signal = bool(
        round_no is not None
        or has_end_prompt(full_window_text)
        or has_reward_continue(full_window_text)
        or failed_settlement
        or has_auction_lobby(full_window_text)
        or has_home_bid_button(home_bid_text)
    )
    perf_log_elapsed(f"observe[{label}] 总计", t_obs)
    return Observation(
        capture=capture,
        round_no=round_no,
        end_prompt=has_end_prompt(full_window_text),
        reward_continue=has_reward_continue(full_window_text),
        failed_auction_settlement=failed_settlement,
        auction_lobby=has_auction_lobby(full_window_text),
        home_bid_button=has_home_bid_button(home_bid_text),
        has_any_signal=any_signal,
    )


def observe_state_poll(
    config: dict[str, Any],
    config_path: Path,
    label: str,
) -> Observation:
    """Main-loop poll: one full-window OCR for end/lobby/reward signals; separate home-bid region OCR; no central crop OCR (parse facts from full-window text)."""
    t_obs = time.perf_counter()
    bring_window_to_front(config)
    # park_mouse_if_configured(config)
    t_cap = time.perf_counter()
    frame, _info = capture_window_frame(config)
    perf_log_elapsed(f"observe[{label}] capture_window_frame", t_cap)
    runs_dir = ensure_output_dir(config, config_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    image_path: Path | None = None
    if bool(config.get("debug", {}).get("save_crops", True)):
        image_path = runs_dir / f"{timestamp}_{label}_full_window.png"
        frame.save(image_path)

    home_region = config.get("capture", {}).get("home_bid_button_region")
    home_bid_text = ""
    t_ocr_full = time.perf_counter()
    full_window_text = rapidocr_once(ImageOps.grayscale(frame).convert("RGB"))
    perf_log_elapsed(f"observe[{label}] OCR_full_window", t_ocr_full)
    if bool(config.get("debug", {}).get("save_ocr_text", True)):
        (runs_dir / f"{timestamp}_{label}_full_window.txt").write_text(full_window_text, encoding="utf-8")
    if home_region:
        t_home = time.perf_counter()
        box = scaled_region_box(home_region, config, frame.width, frame.height)
        home_crop = frame.crop(box)
        home_bid_text = rapidocr_once(ImageOps.grayscale(home_crop).convert("RGB"))
        perf_log_elapsed(f"observe[{label}] OCR_home_bid_region", t_home)

    return _observe_finalize_poll(
        label,
        t_obs=t_obs,
        image_path=image_path,
        full_window_text=full_window_text,
        home_bid_text=home_bid_text,
    )


def save_round_debug_bundle(
    config: dict[str, Any],
    config_path: Path,
    *,
    round_no: int,
    raw_text: str,
    details: dict[str, Any],
    final_price: int,
) -> None:
    debug = config.get("debug", {})
    if not bool(debug.get("save_round_debug", True)):
        return
    runs_dir = ensure_output_dir(config, config_path)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = runs_dir / f"{stamp}_round{round_no}"
    (prefix.with_suffix(".ocr.txt")).write_text(raw_text or "", encoding="utf-8")
    payload = {
        "final_price": final_price,
        "details": details,
    }
    (prefix.with_suffix(".result.json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def virtual_screen_rect() -> tuple[int, int, int, int]:
    if USER32 is None:
        return 0, 0, 1920, 1080
    left = int(USER32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(USER32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(USER32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(USER32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return left, top, left + max(1, width), top + max(1, height)


def get_window_outer_rect(hwnd: int) -> tuple[int, int, int, int]:
    if USER32 is None or wt is None:
        return 0, 0, 1920, 1080
    rect = wt.RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0, 0, 1920, 1080
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def screen_center_position(width: int, height: int) -> tuple[int, int]:
    left, top, right, bottom = virtual_screen_rect()
    screen_width = max(1, right - left)
    screen_height = max(1, bottom - top)
    x = left + max(0, (screen_width - width) // 2)
    y = top + max(0, (screen_height - height) // 2)
    return int(x), int(y)


def prepare_target_window(config: dict[str, Any], *, center: bool) -> None:
    ensure_not_stopped()
    if USER32 is None:
        return
    window_options = config.get("window", {})
    if not bool(config.get("safety", {}).get("bring_window_to_front", True)):
        return
    try:
        info = find_window(window_options)
        hwnd = int(info.hwnd)
        USER32.ShowWindow(hwnd, SW_RESTORE)
        sleep_interruptible(0.05)

        left, top, right, bottom = get_window_outer_rect(hwnd)
        width = max(1, right - left)
        height = max(1, bottom - top)
        if center and bool(window_options.get("center_on_start", True)):
            x, y = screen_center_position(width, height)
            USER32.SetWindowPos(hwnd, HWND_TOP, int(x), int(y), width, height, SWP_SHOWWINDOW)
            sleep_interruptible(0.08)
            log(f"window centered: hwnd={hwnd} pos={x},{y} size={width}x{height}", gui_verbose_only=True)

        if bool(window_options.get("force_topmost_bump", True)):
            USER32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            sleep_interruptible(0.03)
            USER32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            sleep_interruptible(0.03)

        USER32.SetForegroundWindow(hwnd)
        sleep_interruptible(float(config.get("timing", {}).get("click_pause_seconds", 0.12)))
    except Exception as exc:
        log(f"warn: failed to prepare target window: {exc}")


def bring_window_to_front(config: dict[str, Any]) -> None:
    prepare_target_window(config, center=False)


def client_to_screen(config: dict[str, Any], point: dict[str, Any]) -> tuple[int, int]:
    info = find_window(config.get("window", {}))
    reference = config.get("window", {}).get("reference_client_size", {})
    raw_point = dict(point)
    if str(raw_point.get("origin", "left_top")).strip().lower() in {"left_bottom", "bottom_left"}:
        ref_height = int(reference.get("height") or info.height or 1080)
        raw_point["y"] = ref_height - int(raw_point["y"])
    x, y = scale_point(raw_point, reference, info.width, info.height)
    origin_x, origin_y = info.client_origin
    return origin_x + x, origin_y + y


def click_point(config: dict[str, Any], name: str, repeat: int = 1, pause: float | None = None) -> None:
    bring_window_to_front(config)
    point = config["clicks"][name]
    timing = config.get("timing", {})
    pause_value = float(timing.get("click_pause_seconds", 0.12) if pause is None else pause)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    x, y = client_to_screen(config, point)
    point_json = json.dumps(point, ensure_ascii=False, sort_keys=True)
    for index in range(repeat):
        ensure_not_stopped()
        log(
            f"click {name} #{index + 1}: point={point_json} screen={x},{y}",
            gui_verbose_only=True,
        )
        if not dry_run:
            human_click_at_screen(config, int(x), int(y), log_detail=f"{name}#{index + 1}")
        sleep_interruptible(pause_value)
    if bool(config.get("safety", {}).get("park_mouse_after_clicks", True)):
        park_mouse_if_configured(config)


def _screen_click_pair_from_config(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    if isinstance(value, dict) and "x" in value and "y" in value:
        return int(value["x"]), int(value["y"])
    return default


def click_client_left_top(
    config: dict[str, Any],
    x: int,
    y: int,
    label: str,
    *,
    pause: float | None = None,
) -> None:
    """点击游戏窗口客户端坐标（原点左上 ``left_top``），经窗口缩放与 ClientToScreen 换算。"""
    bring_window_to_front(config)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    timing = config.get("timing", {})
    pause_value = float(
        timing.get("click_pause_seconds", 0.12) if pause is None else pause
    )
    ensure_not_stopped()
    sx, sy = client_to_screen(
        config, {"origin": "left_top", "x": int(x), "y": int(y)}
    )
    log(
        f"click {label}: client_left_top=({x},{y}) screen=({sx},{sy})",
        gui_verbose_only=True,
    )
    if not dry_run:
        human_click_at_screen(config, int(sx), int(sy), log_detail=label)
    sleep_interruptible(pause_value)


def click_absolute_screen(config: dict[str, Any], x: int, y: int, label: str) -> None:
    """点击物理屏幕坐标（不经 client_to_screen 换算），用于卡死恢复等固定像素操作。"""
    bring_window_to_front(config)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    timing = config.get("timing", {})
    pause_value = float(timing.get("click_pause_seconds", 0.12))
    ensure_not_stopped()
    log(f"click screen {label}: {x},{y}", gui_verbose_only=True)
    if not dry_run:
        human_click_at_screen(config, int(x), int(y), log_detail=label)
    sleep_interruptible(pause_value)


def run_stuck_after_handled_recovery(config: dict[str, Any]) -> None:
    """游戏在出价后卡死、长期停在「本回合已处理」轮询时使用：两次固定屏幕点击退出当前局。"""
    section = config.get("safety", {}).get("stuck_after_handled_round", {})
    first = _screen_click_pair_from_config(section.get("first_click_screen"), (1874, 72))
    second = _screen_click_pair_from_config(section.get("second_click_screen"), (1178, 684))
    between = float(section.get("between_clicks_seconds", 1.0))
    log("stuck recovery: first screen click (exit stuck UI)", gui_verbose_only=True)
    click_absolute_screen(config, first[0], first[1], "stuck_recovery_1")
    sleep_interruptible(max(0.0, between))
    log("stuck recovery: second screen click (leave round)", gui_verbose_only=True)
    click_absolute_screen(config, second[0], second[1], "stuck_recovery_2")


def park_mouse_if_configured(config: dict[str, Any]) -> None:
    """在轮询/OCR 前把光标移到安全区（例如左半屏），避免长期压在右侧按钮上。"""
    point = config.get("safety", {}).get("mouse_park") or config.get("clicks", {}).get("mouse_park")
    if not isinstance(point, dict):
        return
    if bool(config.get("safety", {}).get("dry_run", False)):
        return
    try:
        x, y = client_to_screen(config, point)
        log(f"park mouse: screen={x},{y}", gui_verbose_only=True)
        human_move_to_screen(config, int(x), int(y))
    except Exception as exc:
        log(f"warn: park mouse skipped: {exc}")


def press_escape(config: dict[str, Any]) -> None:
    ensure_not_stopped()
    bring_window_to_front(config)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    log("press key: esc", gui_verbose_only=True)
    if not dry_run:
        h = _humanize_merged(config)
        if h["enabled"]:
            sleep_interruptible(random.uniform(0.03, 0.11))
            ensure_not_stopped()
        pyautogui.press("esc")
    sleep_interruptible(float(config.get("timing", {}).get("click_pause_seconds", 0.12)))


def type_price(config: dict[str, Any], price: int) -> None:
    ensure_not_stopped()
    bring_window_to_front(config)
    timing = config.get("timing", {})
    pause = float(timing.get("click_pause_seconds", 0.12))
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    log(f"type price: {price}", gui_verbose_only=True)
    if dry_run:
        return
    h = _humanize_merged(config)
    if h["enabled"]:
        sleep_interruptible(
            random.uniform(float(h["pre_select_all_delay_min"]), float(h["pre_select_all_delay_max"]))
        )
        ensure_not_stopped()
    _select_all_field(config)
    pause_after_select = pause
    if h["enabled"]:
        pause_after_select *= random.uniform(
            float(h["post_select_all_delay_scale_min"]),
            float(h["post_select_all_delay_scale_max"]),
        )
    sleep_interruptible(pause_after_select)
    ensure_not_stopped()
    human_type_price_digits(config, price)
    if h["enabled"]:
        sleep_interruptible(pause * random.uniform(0.88, 1.18))
    else:
        sleep_interruptible(pause)


def run_tool_sequence(config: dict[str, Any]) -> None:
    log("tool sequence: open/select/confirm", gui_verbose_only=True)
    click_point(config, "tool_button")
    click_point(config, "leftmost_tool")
    click_point(config, "tool_confirm")
    # 无道具时确认后界面可能仍挂层，点空白处关闭以免卡死
    click_point(config, "tool_post_confirm")


def _perform_bid_ui_sequence(config: dict[str, Any], price: int) -> None:
    log("bid sequence: open/input/confirm", gui_verbose_only=True)
    click_point(config, "bid_button")
    click_point(config, "bid_input_box")
    type_price(config, price)
    if bool(config.get("safety", {}).get("confirm_after_type", True)):
        click_point(config, "bid_confirm")
        click_point(config, "tool_confirm")


def _bid_confirm_snapshot_verify_enabled(config: dict[str, Any]) -> bool:
    """画板快照中见到 ``C2S_34_game_bid`` 才视为出价完成（见 :class:`~bidking.parsing.events.GameBidEvent`）。"""
    safety = config.get("safety") or {}
    explicit = safety.get("verify_bid_confirm_snapshot")
    if explicit is not None:
        return bool(explicit)
    return bool((config.get("board_snapshot") or {}).get("enabled", False))


def _iter_c2s34_bids_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """从 ``skill_logs`` / ``game_state.self_bid_events`` 收集 C2S_34 出价记录。"""
    if not isinstance(snapshot, dict):
        return []
    rows: list[dict[str, Any]] = []
    for entry in snapshot.get("skill_logs") or []:
        if not isinstance(entry, dict) or entry.get("event_type") != "C2S_34_game_bid":
            continue
        ub = entry.get("user_bid")
        if not isinstance(ub, dict):
            continue
        rnd = ub.get("Round")
        rows.append(
            {
                "game_uid": str(ub.get("GameUid") or ""),
                "bid_price": int(ub.get("BidPrice") or 0),
                "round": int(rnd) if rnd is not None else None,
                "token": str(ub.get("Token") or ""),
            }
        )
    gs = snapshot.get("game_state") or {}
    if isinstance(gs, dict):
        for entry in gs.get("self_bid_events") or []:
            if not isinstance(entry, dict):
                continue
            rnd = entry.get("round")
            rows.append(
                {
                    "game_uid": str(entry.get("game_uid") or ""),
                    "bid_price": int(entry.get("bid_price") or 0),
                    "round": int(rnd) if rnd is not None else None,
                    "token": str(entry.get("token") or ""),
                }
            )
    return rows


def _c2s34_bid_match_keys(snapshot: dict[str, Any] | None) -> frozenset[tuple[str, int, int]]:
    """去重键：``(game_uid, bid_price, round)``；``round`` 未知记为 ``-1``。"""
    if not isinstance(snapshot, dict):
        return frozenset()
    keys: set[tuple[str, int, int]] = set()
    for row in _iter_c2s34_bids_from_snapshot(snapshot):
        rnd = row.get("round")
        try:
            rn = int(rnd) if rnd is not None else -1
        except (TypeError, ValueError):
            rn = -1
        keys.add((str(row.get("game_uid") or ""), int(row.get("bid_price") or 0), rn))
    return frozenset(keys)


def _snapshot_has_new_c2s34_for_round(
    snapshot: dict[str, Any],
    round_no: int,
    prior_keys: frozenset[tuple[str, int, int]],
) -> bool:
    for row in _iter_c2s34_bids_from_snapshot(snapshot):
        if int(row.get("bid_price") or 0) <= 0:
            continue
        rnd = row.get("round")
        try:
            rn = int(rnd) if rnd is not None else None
        except (TypeError, ValueError):
            rn = None
        if rn is not None and rn != int(round_no):
            continue
        if rn is None:
            cr = current_round_from_snapshot(snapshot)
            if cr is not None and int(cr) != int(round_no):
                continue
        key = (
            str(row.get("game_uid") or ""),
            int(row.get("bid_price") or 0),
            int(rn) if rn is not None else -1,
        )
        if key in prior_keys:
            continue
        return True
    return False


def _snapshot_round_advanced_past(snapshot: dict[str, Any] | None, round_no: int) -> bool:
    if not isinstance(snapshot, dict):
        return False
    cr = current_round_from_snapshot(snapshot)
    if cr is None:
        return False
    return int(cr) > int(round_no)


def _snapshot_has_game_over_notify(snapshot: dict[str, Any] | None) -> bool:
    """快照 ``skill_logs`` 中是否已有 ``S2C_45_game_over_notify``（:class:`~bidking.parsing.events.GameOverEvent`）。"""
    if not isinstance(snapshot, dict):
        return False
    for entry in snapshot.get("skill_logs") or []:
        if isinstance(entry, dict) and entry.get("event_type") == "S2C_45_game_over_notify":
            return True
    return False


def _wait_bid_confirm_snapshot(
    config: dict[str, Any],
    *,
    round_no: int,
    prior_keys: frozenset[tuple[str, int, int]],
    wait_seconds: float,
    poll_seconds: float,
    global_deadline: float,
) -> Literal["confirmed", "next_round", "game_over", "pending"]:
    """在 ``wait_seconds`` 内轮询快照，直至 C2S_34、回合推进或 game over。"""
    wait_until = time.monotonic() + max(0.0, wait_seconds)
    poll = max(0.08, float(poll_seconds))
    while time.monotonic() < global_deadline:
        ensure_not_stopped()
        fresh = load_board_snapshot_for_loop(config)
        if isinstance(fresh, dict):
            if _snapshot_has_new_c2s34_for_round(fresh, round_no, prior_keys):
                return "confirmed"
            if _snapshot_has_game_over_notify(fresh):
                return "game_over"
            if _snapshot_round_advanced_past(fresh, round_no):
                return "next_round"
        if time.monotonic() >= wait_until:
            return "pending"
        remain = min(poll, wait_until - time.monotonic(), global_deadline - time.monotonic())
        if remain <= 0:
            return "pending"
        sleep_interruptible(remain)
    return "pending"


BidConfirmOutcome = Literal[
    "bid_ok", "verify_timeout", "unverified", "next_round", "game_over"
]


def input_bid(
    config: dict[str, Any],
    price: int,
    *,
    round_no: int | None = None,
) -> BidConfirmOutcome:
    timing = config.get("timing", {}) or {}
    post_wait = float(timing.get("after_bid_confirm_wait_seconds", 1.0))
    use_snapshot = _bid_confirm_snapshot_verify_enabled(config)

    if not use_snapshot:
        _perform_bid_ui_sequence(config, price)
        sleep_interruptible(post_wait)
        return "unverified"

    if round_no is None:
        _perform_bid_ui_sequence(config, price)
        sleep_interruptible(post_wait)
        return "unverified"

    max_sec = max(0.0, float(timing.get("bid_confirm_verify_max_seconds", 30.0)))
    retry_pause = max(0.0, float(timing.get("bid_confirm_retry_pause_seconds", 0.35)))
    snapshot_poll = max(
        0.08,
        float(timing.get("bid_confirm_snapshot_poll_seconds", retry_pause) or retry_pause),
    )
    deadline = time.monotonic() + max_sec
    attempt = 0
    prior_keys = _c2s34_bid_match_keys(load_board_snapshot_for_loop(config))
    effective_round = int(round_no)

    while True:
        ensure_not_stopped()
        attempt += 1
        _perform_bid_ui_sequence(config, price)

        snap_outcome = _wait_bid_confirm_snapshot(
            config,
            round_no=effective_round,
            prior_keys=prior_keys,
            wait_seconds=retry_pause,
            poll_seconds=snapshot_poll,
            global_deadline=deadline,
        )
        if snap_outcome == "confirmed":
            log(
                f"bid_confirm: snapshot C2S_34_game_bid confirmed "
                f"(round {effective_round}, attempt {attempt})",
                gui_verbose_only=True,
            )
            sleep_interruptible(post_wait)
            return "bid_ok"
        if snap_outcome == "next_round":
            log(
                f"bid_confirm: snapshot advanced past round {effective_round} "
                f"without new C2S_34 (attempt {attempt})",
                gui_verbose_only=True,
            )
            sleep_interruptible(post_wait)
            return "next_round"
        if snap_outcome == "game_over":
            log(
                f"bid_confirm: snapshot S2C_45_game_over_notify (attempt {attempt}); stop retry",
                gui_verbose_only=True,
            )
            sleep_interruptible(post_wait)
            return "game_over"

        if time.monotonic() >= deadline:
            log(
                f"bid_confirm: snapshot verify timeout after {attempt} attempt(s); "
                "never saw C2S_34_game_bid",
                gui_verbose_only=True,
            )
            sleep_interruptible(post_wait)
            return "verify_timeout"

        log(
            f"bid_confirm: no C2S_34 in snapshot yet, retry UI after {retry_pause}s",
            gui_verbose_only=True,
        )
        sleep_interruptible(retry_pause)


def run_post_round_transition(config: dict[str, Any]) -> float:
    log("post-round transition: fixed click chain", gui_verbose_only=True)
    click_point(config, "end_reward_click", repeat=2)
    sleep_interruptible(1.0)
    click_point(config, "end_close_click", repeat=2)
    sleep_interruptible(1.0)
    click_point(config, "continue_button", repeat=3)
    log("post-round transition complete; waiting for auction lobby OCR", gui_verbose_only=True)


def run_auction_lobby_transition(config: dict[str, Any]) -> None:
    log("auction lobby detected: enter selected room", gui_verbose_only=True)
    sleep_interruptible(1.0)
    click_point(config, "post_continue_action")
    sleep_interruptible(2.0)
    click_point(config, "post_continue_confirm")
    confirm_at = time.monotonic()
    log("auction lobby transition complete; waiting for round OCR", gui_verbose_only=True)
    return confirm_at


def run_home_bid_button_transition(config: dict[str, Any]) -> None:
    log("home bid button detected: click auction entry", gui_verbose_only=True)
    click_point(config, "home_bid_button")
    log("home bid button transition complete; waiting for next OCR", gui_verbose_only=True)


def run_reward_continue_transition(config: dict[str, Any]) -> None:
    log("reward continue detected: click continue", gui_verbose_only=True)
    click_point(config, "reward_continue_button")
    log("reward continue click complete; waiting for next OCR", gui_verbose_only=True)


def run_failed_auction_settlement_transition(config: dict[str, Any]) -> None:
    """关闭流拍结算面板：无经验条时用 continue/关闭 位，与正常结算后半段一致。"""
    log("failed auction settlement: dismiss with continue/close chain", gui_verbose_only=True)
    click_point(config, "end_close_click", repeat=1)
    sleep_interruptible(0.35)
    click_point(config, "continue_button", repeat=3)
    sleep_interruptible(0.35)
    click_point(config, "reward_continue_button", repeat=1)
    log("failed auction settlement transition complete; waiting for next OCR", gui_verbose_only=True)


def current_map_point(config: dict[str, Any], selected_map: str) -> dict[str, Any] | None:
    maps = config.get("automation", {}).get("maps", {})
    item = maps.get(str(selected_map), {})
    point = item.get("point")
    return point if isinstance(point, dict) else None


def run_map_selection_transition(config: dict[str, Any], selected_map: str) -> float | None:
    maps = config.get("automation", {}).get("maps", {})
    item = maps.get(str(selected_map), {})
    name = str(item.get("name") or selected_map)
    point = current_map_point(config, selected_map)
    if not point:
        log(f"map selection skipped: no point configured for {selected_map}.{name}")
        return None
    log(f"auction lobby detected: select map {selected_map}.{name}", gui_verbose_only=True)
    bring_window_to_front(config)
    sleep_interruptible(1.0)
    sx, sy = client_to_screen(config, point)
    log(f"click map point: screen={sx},{sy}", gui_verbose_only=True)
    if not bool(config.get("safety", {}).get("dry_run", False)):
        human_click_at_screen(config, sx, sy, log_detail=f"map_select.{selected_map}")
    timing = config.get("timing", {}) or {}
    sleep_interruptible(float(timing.get("click_pause_seconds", 0.12)))
    click_point(config, "post_continue_confirm")
    sleep_interruptible(float(timing.get("after_map_select_wait_seconds", 2.0)))
    confirm_at = time.monotonic()
    log(
        "map start-match confirm clicked; waiting for game load / round OCR",
        gui_verbose_only=True,
    )
    return confirm_at


def board_snapshot_file_missing(config: dict[str, Any]) -> bool:
    """``board_snapshot`` 已启用但快照文件尚不存在（含使用默认 ``data/board_snapshot.json`` 时）。"""
    bs = config.get("board_snapshot") or {}
    if not bs.get("enabled"):
        return False
    raw_path = str(bs.get("path") or "").strip()
    from ..config.paths import resolve_board_snapshot_path

    path = resolve_board_snapshot_path(raw_path)
    try:
        return not path.is_file()
    except OSError:
        return True


def game_started_from_poll(
    observation: Observation,
) -> bool:
    """选图后轮询：快照回合或整窗 OCR 回合任一表明已进入竞拍。

    若整窗 OCR 仍识别为拍卖大厅，则不视为已开局（画板快照常为上一局残留，易与大厅同时为真）。"""
    if observation.auction_lobby:
        return False
    rn = observation.round_no
    return rn is not None and int(rn) >= 1


def _default_warehouse_auto_sort_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "wait_after_warehouse_click_seconds": 5.0,
        "wait_after_auto_sort_click_seconds": 5.0,
        # 客户区逻辑坐标（同 ``clicks``），非区域中心；旧档可用 ``warehouse_button_region`` 矩形兜底
        "warehouse_button_click": {"origin": "left_top", "x": 127, "y": 1019},
        # 自动排序按钮：客户区坐标；旧档可用 ``auto_sort_region`` 矩形兜底
        "auto_sort_click": {"origin": "left_top", "x": 1510, "y": 1014},
    }


def merge_warehouse_auto_sort_settings(config: dict[str, Any]) -> dict[str, Any]:
    """合并 ``automation.warehouse_auto_sort``。

    仓库入口优先 ``warehouse_button_click``（客户区坐标）；仍支持旧键 ``warehouse_button_region`` 矩形取中心点击。
    自动排序优先 ``auto_sort_click``；仍支持旧键 ``auto_sort_region`` 矩形取中心点击。
    """
    defaults = _default_warehouse_auto_sort_settings()
    raw = (config.get("automation") or {}).get("warehouse_auto_sort")
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for key, val in raw.items():
        if key in (
            "warehouse_button_click",
            "warehouse_button_region",
            "auto_sort_click",
            "auto_sort_region",
        ) and isinstance(val, dict):
            base = dict(defaults[key]) if isinstance(defaults.get(key), dict) else {}
            base.update(val)
            out[key] = base
        else:
            out[key] = val
    return out


def _click_client_point(
    config: dict[str, Any],
    point: dict[str, Any],
    label: str,
) -> None:
    ensure_not_stopped()
    bring_window_to_front(config)
    sx, sy = client_to_screen(config, point)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    pause = float(config.get("timing", {}).get("click_pause_seconds", 0.12))
    raw = dict(point)
    cx = int(raw.get("x", 0))
    cy = int(raw.get("y", 0))
    log(
        f"warehouse auto_sort: click {label} ref_client=({cx},{cy}) -> screen=({sx},{sy})",
        gui_verbose_only=True,
    )
    if not dry_run:
        human_click_at_screen(config, sx, sy, log_detail=label)
    sleep_interruptible(pause)
    if bool(config.get("safety", {}).get("park_mouse_after_clicks", True)):
        park_mouse_if_configured(config)


def _click_client_region_center(
    config: dict[str, Any],
    region: dict[str, Any],
    label: str,
) -> None:
    ensure_not_stopped()
    bring_window_to_front(config)
    frame, _info = capture_window_frame(config)
    left, top, right, bottom = scaled_region_box(region, config, frame.width, frame.height)
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    sx, sy = client_to_screen(config, {"x": cx, "y": cy})
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    pause = float(config.get("timing", {}).get("click_pause_seconds", 0.12))
    log(
        f"warehouse auto_sort: click {label} client_center=({cx},{cy}) -> screen=({sx},{sy})",
        gui_verbose_only=True,
    )
    if not dry_run:
        human_click_at_screen(config, sx, sy, log_detail=label)
    sleep_interruptible(pause)
    if bool(config.get("safety", {}).get("park_mouse_after_clicks", True)):
        park_mouse_if_configured(config)


def run_warehouse_auto_sort(config: dict[str, Any]) -> None:
    """主页：点仓库 → 等待 → 自动排序 → 等待 → ESC 回主界面。"""
    wc = merge_warehouse_auto_sort_settings(config)
    if not bool(wc.get("enabled", True)):
        return
    wh_click = wc.get("warehouse_button_click")
    wh_region = wc.get("warehouse_button_region")
    sort_click = wc.get("auto_sort_click")
    sort_region = wc.get("auto_sort_region")
    use_point = isinstance(wh_click, dict) and "x" in wh_click and "y" in wh_click
    use_legacy_region = (
        isinstance(wh_region, dict)
        and all(k in wh_region for k in ("left", "top", "width", "height"))
    )
    use_sort_point = isinstance(sort_click, dict) and "x" in sort_click and "y" in sort_click
    use_sort_legacy = (
        isinstance(sort_region, dict)
        and all(k in sort_region for k in ("left", "top", "width", "height"))
    )
    if not use_point and not use_legacy_region:
        log("warehouse auto_sort: 仓库按钮坐标（warehouse_button_click）或旧版区域无效，跳过")
        return
    if not use_sort_point and not use_sort_legacy:
        log("warehouse auto_sort: 自动排序坐标（auto_sort_click）或旧版区域无效，跳过")
        return
    w1 = max(0.0, float(wc.get("wait_after_warehouse_click_seconds", 5.0) or 0.0))
    w2 = max(0.0, float(wc.get("wait_after_auto_sort_click_seconds", 5.0) or 0.0))
    log("warehouse auto_sort: 进入仓库并自动排序", gui_verbose_only=True)
    if use_point:
        _click_client_point(config, wh_click, "warehouse_entry")
    else:
        _click_client_region_center(config, wh_region, "warehouse_entry")
    if w1 > 0:
        sleep_interruptible(w1)
    if use_sort_point:
        _click_client_point(config, sort_click, "auto_sort")
    else:
        _click_client_region_center(config, sort_region, "auto_sort")
    if w2 > 0:
        sleep_interruptible(w2)
    press_escape(config)
    log("warehouse auto_sort: 已 ESC 返回主界面", gui_verbose_only=True)


AISHA_HERO_CID = 103
AISHA_ROUND4_TOOL_ROUND = 4
AISHA_ROUND5_TOOL_ROUND = 5

_EXPRESS_STATION_EMOJI_DEFAULT = "惊讶"
_WEEKDAY_EMOJI_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_EMOJI_KEYS_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _default_express_station_emoji_by_weekday() -> dict[str, str]:
    """快递站开局表情：周一～周日默认均为「问候」（可在 ``emoji_by_weekday`` 覆盖）。"""
    return {k: _EXPRESS_STATION_EMOJI_DEFAULT for k in _WEEKDAY_EMOJI_KEYS}


def _weekday_lookup_keys(on: date) -> tuple[str, ...]:
    """按本地日历日解析星期：``weekday()`` 0=周一 … 6=周日。"""
    wd = int(on.weekday())
    if wd < 0 or wd > 6:
        wd = 0
    return (
        _WEEKDAY_EMOJI_KEYS[wd],
        _WEEKDAY_EMOJI_KEYS_ZH[wd],
        str(wd + 1),
        str(wd),
    )


def _express_station_weekday_emoji_schedule(
    raw: dict[str, Any] | None,
) -> dict[str, str] | None:
    """若配置了非空 ``emoji_by_weekday``，返回与默认合并后的整周表；否则 ``None``（走旧版单 ``emoji``）。"""
    if not isinstance(raw, dict):
        return None
    raw_map = raw.get("emoji_by_weekday")
    if not isinstance(raw_map, dict) or not raw_map:
        return None
    out = _default_express_station_emoji_by_weekday()
    for key, val in raw_map.items():
        name = str(val or "").strip()
        if not name:
            continue
        k = str(key).strip()
        if not k:
            continue
        kl = k.lower()
        if kl in _WEEKDAY_EMOJI_KEYS:
            out[kl] = name
            continue
        if k in _WEEKDAY_EMOJI_KEYS_ZH:
            out[_WEEKDAY_EMOJI_KEYS[_WEEKDAY_EMOJI_KEYS_ZH.index(k)]] = name
            continue
        if kl.isdigit():
            try:
                n = int(kl)
            except ValueError:
                continue
            if 1 <= n <= 7:
                out[_WEEKDAY_EMOJI_KEYS[n - 1]] = name
            elif 0 <= n <= 6:
                out[_WEEKDAY_EMOJI_KEYS[n]] = name
    return out


def _emoji_from_weekday_schedule(
    schedule: dict[str, str],
    *,
    known_names: set[str] | None,
    on: date | None = None,
) -> str:
    on = on or date.today()
    for key in _weekday_lookup_keys(on):
        if key in schedule:
            emoji = str(schedule[key]).strip()
            if emoji and (not known_names or emoji in known_names):
                return emoji
    return _EXPRESS_STATION_EMOJI_DEFAULT


def _resolve_express_station_effective_emoji(
    raw: dict[str, Any],
    known_names: set[str] | None,
    *,
    on: date | None = None,
) -> tuple[str, Literal["weekday", "force", "legacy"]]:
    """
    解析快递站第 1 回合实际使用的表情名。

    - 配置了 ``emoji_by_weekday``：默认取当天星期；``emoji`` + ``emoji_force_date`` 为当天
      的强制覆盖，次日凌晨（本地日期变更）后失效。
    - 未配置星期表：沿用 ``emoji`` 单字段（兼容旧配置）。
    """
    on = on or date.today()
    schedule = _express_station_weekday_emoji_schedule(raw)
    if schedule is not None:
        scheduled = _emoji_from_weekday_schedule(
            schedule, known_names=known_names, on=on
        )
        force_date = str(raw.get("emoji_force_date") or "").strip()
        if force_date == on.isoformat():
            forced = str(raw.get("emoji") or "").strip()
            if forced and (not known_names or forced in known_names):
                return forced, "force"
        return scheduled, "weekday"
    emoji = str(raw.get("emoji") or _EXPRESS_STATION_EMOJI_DEFAULT).strip()
    if known_names and emoji not in known_names:
        emoji = _EXPRESS_STATION_EMOJI_DEFAULT
    return emoji, "legacy"


def express_station_effective_emoji(
    raw: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
    *,
    on: date | None = None,
) -> str:
    """供 UI / 配置保存使用的当日有效表情（含强制覆盖）。"""
    if not isinstance(raw, dict):
        return _EXPRESS_STATION_EMOJI_DEFAULT
    known_targets = (
        merge_express_station_round1_emoji_clicks(config or {}).get("targets") or {}
    )
    known_names = (
        set(known_targets.keys()) if isinstance(known_targets, dict) else set()
    )
    emoji, _src = _resolve_express_station_effective_emoji(
        raw, known_names, on=on
    )
    return emoji


def sync_express_station_emoji_force_after_manual_edit(
    doc: dict[str, Any],
    *,
    on: date | None = None,
) -> None:
    """
    可视化面板保存地图档后调用：手动改 ``emoji`` 且与当日星期表不一致时写入
    ``emoji_force_date``（仅当天有效）；与星期表一致则清除强制标记。
    """
    on = on or date.today()
    au = doc.get("automation")
    if not isinstance(au, dict):
        return
    block = au.get("express_station_round1_emoji")
    if not isinstance(block, dict):
        return
    schedule = _express_station_weekday_emoji_schedule(block)
    if schedule is None:
        block.pop("emoji_force_date", None)
        return
    known_names = set(_default_express_station_round1_emoji_clicks()["targets"].keys())
    chosen = str(block.get("emoji") or "").strip()
    if not chosen:
        block.pop("emoji_force_date", None)
        return
    if known_names and chosen not in known_names:
        return
    scheduled = _emoji_from_weekday_schedule(schedule, known_names=known_names, on=on)
    if chosen == scheduled:
        block.pop("emoji_force_date", None)
        return
    block["emoji_force_date"] = on.isoformat()


def _default_express_station_round1_emoji_clicks() -> dict[str, Any]:
    """快递站第 1 回合开局表情点击（客户端 left_top，参考 1920×1080）。默认见 ``runtime.json`` → ``clicks``。"""
    return {
        "panel": {"origin": "left_top", "x": 57, "y": 1000},
        "panel_wait_seconds": 1.0,
        "targets": {
            "问候": {"x": 230, "y": 469},
            "自信": {"x": 230, "y": 538},
            "嘲讽": {"x": 230, "y": 618},
            "惊讶": {"x": 230, "y": 688},
            "遗憾": {"x": 230, "y": 777},
            "感谢": {"x": 230, "y": 838},
            "赞赏": {"x": 230, "y": 913},
            "生气": {"x": 230, "y": 987},
        },
    }


def merge_express_station_round1_emoji_clicks(config: dict[str, Any]) -> dict[str, Any]:
    """合并 ``clicks.express_station_round1_emoji``（``runtime.json`` 可配）。"""
    defaults = _default_express_station_round1_emoji_clicks()
    raw = (config.get("clicks") or {}).get("express_station_round1_emoji")
    if not isinstance(raw, dict):
        return dict(defaults)
    out = dict(defaults)
    if isinstance(raw.get("panel"), dict):
        base = dict(defaults["panel"])
        base.update(raw["panel"])
        out["panel"] = base
    try:
        wait = float(raw.get("panel_wait_seconds", defaults["panel_wait_seconds"]))
    except (TypeError, ValueError):
        wait = float(defaults["panel_wait_seconds"])
    out["panel_wait_seconds"] = max(0.0, wait)
    raw_targets = raw.get("targets")
    if isinstance(raw_targets, dict):
        targets = dict(defaults["targets"])
        for name, val in raw_targets.items():
            key = str(name).strip()
            if not key:
                continue
            if isinstance(val, dict) and "x" in val and "y" in val:
                targets[key] = {"x": int(val["x"]), "y": int(val["y"])}
            elif isinstance(val, (list, tuple)) and len(val) >= 2:
                targets[key] = {"x": int(val[0]), "y": int(val[1])}
        out["targets"] = targets
    return out


def _express_station_emoji_panel_xy(clicks: dict[str, Any]) -> tuple[int, int]:
    panel = clicks.get("panel")
    if isinstance(panel, dict) and "x" in panel and "y" in panel:
        return int(panel["x"]), int(panel["y"])
    dp = _default_express_station_round1_emoji_clicks()["panel"]
    return int(dp["x"]), int(dp["y"])


def _express_station_emoji_target_xy(
    clicks: dict[str, Any], emoji: str
) -> tuple[int, int] | None:
    targets = clicks.get("targets")
    if not isinstance(targets, dict):
        return None
    pt = targets.get(emoji)
    if isinstance(pt, dict) and "x" in pt and "y" in pt:
        return int(pt["x"]), int(pt["y"])
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        return int(pt[0]), int(pt[1])
    return None
_EXPRESS_ROUND2_PLUS_HIGH_RANDOM_MAX_DEFAULT = 888
_express_round1_signal_bid_by_game: dict[str, int] = {}


def _automation_with_map_overlay(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """合并 ``configs/pricing.maps/<地图>.json`` 的 ``automation``（与出价计算同源）。"""
    from ..analysis._board_pricing import map_id_from_board_snapshot
    from ..config.map_runtime_overlay import merged_runtime_with_map_pricing
    from ..parsing.item_db import map_bundle_key_for_automation

    map_bundle_key: str | None = None
    if isinstance(board_snapshot, dict):
        mid_snap = map_id_from_board_snapshot(board_snapshot)
        if mid_snap is not None and int(mid_snap) > 0:
            map_bundle_key = map_bundle_key_for_automation(int(mid_snap))
    merged = merged_runtime_with_map_pricing(
        config, map_bundle_key=map_bundle_key
    )
    auto = merged.get("automation")
    return auto if isinstance(auto, dict) else {}


def _express_station_round1_emoji_settings(
    automation: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    known_targets = (merge_express_station_round1_emoji_clicks(config or {}).get("targets") or {})
    known_names = set(known_targets.keys()) if isinstance(known_targets, dict) else set()
    raw = (automation or {}).get("express_station_round1_emoji")
    if not isinstance(raw, dict):
        return {
            "enabled": False,
            "emoji": _EXPRESS_STATION_EMOJI_DEFAULT,
            "emoji_source": "legacy",
            "seat_1_price": 250,
            "seat_2_price": 886,
            "wait_after_send_seconds": 3.0,
            "self_emoji_cid": 0,
            "anti_routine_enabled": False,
            "round2_plus_high_random_max": _EXPRESS_ROUND2_PLUS_HIGH_RANDOM_MAX_DEFAULT,
        }
    emoji, emoji_source = _resolve_express_station_effective_emoji(
        raw, known_names if known_names else None
    )

    def _seat_price(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    try:
        wait_after = float(raw.get("wait_after_send_seconds", 3.0))
    except (TypeError, ValueError):
        wait_after = 3.0
    if wait_after < 0.0:
        wait_after = 0.0

    from ..parsing.constants import EMOJI_NAME_TO_CID

    self_emoji_cid = int(EMOJI_NAME_TO_CID.get(emoji, 0))

    try:
        round2_high_max = int(
            raw.get("round2_plus_high_random_max", _EXPRESS_ROUND2_PLUS_HIGH_RANDOM_MAX_DEFAULT)
        )
    except (TypeError, ValueError):
        round2_high_max = _EXPRESS_ROUND2_PLUS_HIGH_RANDOM_MAX_DEFAULT

    return {
        "enabled": bool(raw.get("enabled", False)),
        "emoji": emoji,
        "emoji_source": emoji_source,
        "anti_routine_enabled": bool(raw.get("anti_routine_enabled", False)),
        "seat_1_price": _seat_price("seat_1_price", 250),
        "seat_2_price": _seat_price("seat_2_price", 886),
        "wait_after_send_seconds": wait_after,
        "self_emoji_cid": self_emoji_cid,
        "round2_plus_high_random_max": max(1, round2_high_max),
    }


def _emoji_events_from_board_snapshot(
    board_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """合并 ``game_state.emoji_events`` 与 ``skill_logs`` 中的 S2C_265 表情信号。"""
    out: list[dict[str, Any]] = []
    gs = board_snapshot.get("game_state")
    if isinstance(gs, dict):
        for row in gs.get("emoji_events") or []:
            if isinstance(row, dict):
                out.append(dict(row))
    for block in board_snapshot.get("skill_logs") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("event_type") or "") != "S2C_265_game_use_emoji_notify":
            continue
        sig = block.get("emoji_signal")
        if not isinstance(sig, dict):
            continue
        out.append(
            {
                "game_uid": str(sig.get("GameUid") or ""),
                "user_uid": str(sig.get("UserUid") or ""),
                "emoji_cid": int(sig.get("EmojiCid") or 0),
            }
        )
    return out


def _express_random_seat_for_signal() -> int:
    """第 1 回合暗号价：随机座次 1 或 2（各用对应 ``seat_*_price``）。"""
    return random.choice((1, 2))


def _express_remember_round1_signal_bid(
    board_snapshot: dict[str, Any], bid: int
) -> None:
    g = game_uid_from_snapshot(board_snapshot)
    if g:
        _express_round1_signal_bid_by_game[str(g)] = int(bid)


def _express_round1_signal_bid_for_followup(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    seat_prices: dict[int, int],
) -> int | None:
    """第 2 回合及以后：读取本局第 1 回合暗号出价（缓存或快照）。"""
    from ..pricing.self_bid_cache import get_self_gold_bid

    r1 = get_self_gold_bid(config, board_snapshot, 1)
    if r1 is not None and int(r1) > 0:
        return int(r1)
    g = game_uid_from_snapshot(board_snapshot)
    if g:
        cached = _express_round1_signal_bid_by_game.get(str(g))
        if cached is not None and int(cached) > 0:
            return int(cached)
    return None


def _express_round2_plus_random_bounds(
    seat_prices: dict[int, int],
    round1_bid: int,
    *,
    high_random_max: int,
) -> tuple[int, int]:
    """
    第 2 回合及以后随机区间。

    第 1 回合为座次 1 价（如 520）→ ``[1, seat_2_price]``；
    第 1 回合为座次 2 价（如 144）→ ``[seat_1_price, high_random_max]``（默认上限 888）。
    """
    seat_1 = int(seat_prices[1])
    seat_2 = int(seat_prices[2])
    r1 = int(round1_bid)
    if r1 == seat_1:
        lo, hi = 1, seat_2
    elif r1 == seat_2:
        lo, hi = seat_1, int(high_random_max)
    elif abs(r1 - seat_1) <= abs(r1 - seat_2):
        lo, hi = 1, seat_2
    else:
        lo, hi = seat_1, int(high_random_max)
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _express_round2_plus_random_price(
    config: dict[str, Any],
    board_snapshot: dict[str, Any],
    seat_prices: dict[int, int],
    emoji_cfg: dict[str, Any],
) -> tuple[int, int, int, int | None]:
    """返回 ``(price, lo, hi, round1_bid)``。"""
    high_max = int(
        emoji_cfg.get("round2_plus_high_random_max")
        or _EXPRESS_ROUND2_PLUS_HIGH_RANDOM_MAX_DEFAULT
    )
    r1 = _express_round1_signal_bid_for_followup(config, board_snapshot, seat_prices)
    if r1 is None:
        lo, hi = 1, 100
    else:
        lo, hi = _express_round2_plus_random_bounds(
            seat_prices, r1, high_random_max=high_max
        )
    price = random.randint(int(lo), int(hi))
    return price, lo, hi, r1


def _expected_self_emoji_cid_for_signal(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> int:
    """己方配置表情对应的 ``EmojiCid``（101–108）。"""
    automation = _automation_with_map_overlay(config, board_snapshot)
    return int(
        _express_station_round1_emoji_settings(automation, config).get("self_emoji_cid") or 0
    )


def _opponent_matched_emoji_signal(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    *,
    expected_emoji_cid: int | None = None,
) -> bool:
    """对手是否发了与己方配置相同的表情（暗号对上）。"""
    from ..pricing.snapshot_players import board_snapshot_self_identity

    expected = int(expected_emoji_cid or 0)
    if expected <= 0:
        expected = _expected_self_emoji_cid_for_signal(config, board_snapshot)
    if expected <= 0:
        return False

    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    if not self_uid:
        return False
    for ev in _emoji_events_from_board_snapshot(board_snapshot):
        uid = str(ev.get("user_uid") or "")
        if not uid or uid == str(self_uid):
            continue
        if int(ev.get("emoji_cid") or 0) == expected:
            return True
    return False


def _opponent_matching_emoji_cid(
    board_snapshot: dict[str, Any],
    config: dict[str, Any],
    *,
    expected_emoji_cid: int,
) -> int | None:
    from ..pricing.snapshot_players import board_snapshot_self_identity

    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    if not self_uid or expected_emoji_cid <= 0:
        return None
    for ev in _emoji_events_from_board_snapshot(board_snapshot):
        uid = str(ev.get("user_uid") or "")
        if not uid or uid == str(self_uid):
            continue
        cid = int(ev.get("emoji_cid") or 0)
        if cid == int(expected_emoji_cid):
            return cid
    return None


def _express_after_snapshot_hooks(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> None:
    """
    暗号已对上的快递站局：快照更新后补写对局黑名单。

    避免首回合即结算、无第 2 回合时对手出价尚未写入快照而漏记。
    """
    if not isinstance(board_snapshot, dict):
        return
    if not _express_station_emoji_handshake_enabled(config, board_snapshot):
        return
    automation = _automation_with_map_overlay(config, board_snapshot)
    emoji_cfg = _express_station_round1_emoji_settings(automation, config)
    if not emoji_cfg.get("enabled"):
        return
    self_emoji_cid = int(emoji_cfg.get("self_emoji_cid") or 0)
    if not _opponent_matched_emoji_signal(
        board_snapshot, config, expected_emoji_cid=self_emoji_cid
    ):
        return
    if emoji_cfg.get("anti_routine_enabled"):
        return
    from .emoji_signal_blacklist import maybe_update_steal_express_blacklist

    maybe_update_steal_express_blacklist(config, board_snapshot)


def try_resolve_express_emoji_signal_price(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
    *,
    round_no: int,
) -> tuple[int, dict[str, Any]] | None:
    """
    快递站 + 开局表情已开启 + 对手回了与己方相同的表情：跳过快照估价。

    第 1 回合随机座次 1/2 并使用对应 ``seat_*_price``。

    第 2 回合及以后按第 1 回合出价分档随机：首回合为座次 1 价则在
    ``[1, seat_2_price]``；首回合为座次 2 价则在 ``[seat_1_price, round2_plus_high_random_max]``
    （默认 888）。
    """
    from ..analysis._board_pricing import map_id_from_board_snapshot
    from ..analysis.strategy.ahmad import map_bundle_is_express_station_series
    from ..config.map_runtime_overlay import merged_runtime_with_map_pricing
    from ..parsing.item_db import map_bundle_key_for_automation
    from ..analysis._board_pricing import compute_known_items_total
    from ..pricing.postprocess import apply_bid_cap, known_items_total_from_pricing
    from ..pricing.snapshot_io import resolve_effective_round
    from ..pricing.snapshot_players import board_snapshot_self_identity

    if not isinstance(board_snapshot, dict):
        return None
    mid = map_id_from_board_snapshot(board_snapshot)
    if mid is None or not map_bundle_is_express_station_series(int(mid)):
        return None

    automation = _automation_with_map_overlay(config, board_snapshot)
    emoji_cfg = _express_station_round1_emoji_settings(automation, config)
    if not emoji_cfg["enabled"]:
        return None
    self_emoji_cid = int(emoji_cfg.get("self_emoji_cid") or 0)
    if not _opponent_matched_emoji_signal(
        board_snapshot, config, expected_emoji_cid=self_emoji_cid
    ):
        return None

    if emoji_cfg.get("anti_routine_enabled"):
        log(
            "快递站反套路：暗号已对上，发表情流程不变，出价走后端估价（不写黑名单）",
            gui_verbose_only=True,
        )
        return None

    from .emoji_signal_blacklist import (
        SELF_PUBLIC_BLACKLIST_FORCE_BID,
        is_self_on_public_blacklist,
        maybe_update_steal_express_blacklist,
        opponent_blocks_express_emoji_signal_price,
        record_opponent_steal_express_bids_from_snapshot,
    )

    opp_r1_bid = maybe_update_steal_express_blacklist(config, board_snapshot)

    self_uid, _ = board_snapshot_self_identity(config, board_snapshot)
    map_bundle_key = map_bundle_key_for_automation(int(mid))
    effective_config = merged_runtime_with_map_pricing(
        config, map_bundle_key=map_bundle_key
    )
    effective_round = resolve_effective_round(int(round_no), board_snapshot)
    opp_emoji_cid = _opponent_matching_emoji_cid(
        board_snapshot, config, expected_emoji_cid=self_emoji_cid
    )

    if is_self_on_public_blacklist(config, board_snapshot):
        price = int(SELF_PUBLIC_BLACKLIST_FORCE_BID)
        signal_detail: dict[str, Any] = {
            "price_mode": "public_blacklist_force",
            "forced_bid": price,
            "self_user_uid": self_uid,
            "self_emoji_cid": self_emoji_cid,
            "opponent_emoji_cid": opp_emoji_cid,
        }
        payload: dict[str, Any] = {
            "fallback": False,
            "reason": "express_emoji_public_blacklist_force",
            "pricing_strategy": "express_emoji_public_blacklist_force",
            "role": None,
            "effective_round": effective_round,
            "source_value": float(price),
            "express_emoji_signal": signal_detail,
        }
        pricing = board_snapshot.get("pricing")
        known_total = (
            known_items_total_from_pricing(pricing)
            if isinstance(pricing, dict)
            else None
        )
        if known_total is None:
            known_total = float(compute_known_items_total(board_snapshot))
        fin, payload = apply_bid_cap(
            effective_config, price, payload, known_items_total=known_total
        )
        payload["final_round_used"] = effective_round
        log(
            f"快递站表情暗号：己方在公共黑名单，强制出价 -> {fin}",
            gui_verbose_only=True,
        )
        return int(fin), payload

    blocked, block_reason = opponent_blocks_express_emoji_signal_price(
        config, board_snapshot
    )
    if blocked:
        # 对手已在黑名单仍追记异常出价（快照可能晚于首次 maybe_update 才有完整出价）
        record_opponent_steal_express_bids_from_snapshot(config, board_snapshot)
        opp_bid_note = (
            f" 对手首回合出价={opp_r1_bid}" if opp_r1_bid is not None else ""
        )
        log(
            f"快递站表情暗号：对手在{'公共' if block_reason == 'public' else '对局'}黑名单，"
            f"改走后端估价{opp_bid_note}",
            gui_verbose_only=True,
        )
        return None

    seat_prices = {1: int(emoji_cfg["seat_1_price"]), 2: int(emoji_cfg["seat_2_price"])}

    if effective_round >= 2:
        price, rand_lo, rand_hi, round1_bid = _express_round2_plus_random_price(
            config, board_snapshot, seat_prices, emoji_cfg
        )
        pricing_strategy = "express_emoji_random_signal"
        signal_detail = {
            "price_mode": "random",
            "random_price": price,
            "random_lo": rand_lo,
            "random_hi": rand_hi,
            "round1_signal_bid": round1_bid,
            "self_user_uid": self_uid,
            "self_emoji_cid": self_emoji_cid,
            "opponent_emoji_cid": opp_emoji_cid,
            "seat_1_price": seat_prices[1],
            "seat_2_price": seat_prices[2],
        }
    else:
        seat = _express_random_seat_for_signal()
        price = int(seat_prices[seat])
        if price <= 0:
            return None
        pricing_strategy = "express_emoji_seat_signal"
        signal_detail = {
            "price_mode": "seat",
            "seat": seat,
            "seat_price": price,
            "seat_random_pick": True,
            "self_user_uid": self_uid,
            "self_emoji_cid": self_emoji_cid,
            "opponent_emoji_cid": opp_emoji_cid,
            "seat_1_price": seat_prices[1],
            "seat_2_price": seat_prices[2],
        }
        log(
            f"快递站表情暗号：随机座次 seat={seat} -> 出价 {price}",
            gui_verbose_only=True,
        )
        _express_remember_round1_signal_bid(board_snapshot, price)

    payload: dict[str, Any] = {
        "fallback": False,
        "reason": pricing_strategy,
        "pricing_strategy": pricing_strategy,
        "role": None,
        "effective_round": effective_round,
        "source_value": float(price),
        "express_emoji_signal": signal_detail,
    }
    pricing = board_snapshot.get("pricing")
    known_total = (
        known_items_total_from_pricing(pricing)
        if isinstance(pricing, dict)
        else None
    )
    if known_total is None:
        known_total = float(compute_known_items_total(board_snapshot))
    fin, payload = apply_bid_cap(
        effective_config, price, payload, known_items_total=known_total
    )
    payload["final_round_used"] = effective_round
    if effective_round >= 2:
        lo = signal_detail.get("random_lo")
        hi = signal_detail.get("random_hi")
        r1 = signal_detail.get("round1_signal_bid")
        log(
            f"快递站表情暗号出价: 第{effective_round}回合随机 -> {fin}（"
            f"第1回合={r1} 区间 {lo}-{hi} 随机价 {price}）",
            gui_verbose_only=True,
        )
    else:
        seat = signal_detail.get("seat")
        log(
            f"快递站表情暗号出价: 座位{seat} -> {fin}（配置座位价 {price}）",
            gui_verbose_only=True,
        )
    return int(fin), payload


def _express_station_emoji_handshake_enabled(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> bool:
    """快递站地图且已开启开局表情/暗号判断。"""
    from ..analysis._board_pricing import map_id_from_board_snapshot
    from ..analysis.strategy.ahmad import map_bundle_is_express_station_series

    if not isinstance(board_snapshot, dict):
        return False
    mid = map_id_from_board_snapshot(board_snapshot)
    if mid is None or int(mid) <= 0:
        return False
    if not map_bundle_is_express_station_series(int(mid)):
        return False
    return bool(
        _express_station_round1_emoji_settings(
            _automation_with_map_overlay(config, board_snapshot),
            config,
        ).get("enabled")
    )


def try_send_express_station_round1_emoji(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> bool:
    """快递站系列地图第 1 回合：打开表情面板并点选配置的表情。"""
    if not _express_station_emoji_handshake_enabled(config, board_snapshot):
        return False
    settings = _express_station_round1_emoji_settings(
        _automation_with_map_overlay(config, board_snapshot),
        config,
    )

    emoji = settings["emoji"]
    clicks_cfg = merge_express_station_round1_emoji_clicks(config)
    target = _express_station_emoji_target_xy(clicks_cfg, emoji)
    if target is None:
        log(
            f"warn: 快递站开局表情坐标未配置: {emoji!r}（clicks.express_station_round1_emoji.targets）",
            gui_verbose_only=True,
        )
        return False
    ex, ey = target
    px, py = _express_station_emoji_panel_xy(clicks_cfg)
    panel_wait = float(clicks_cfg.get("panel_wait_seconds", 1.0))
    log(
        f"快递站第1回合发表情: {emoji} panel=({px},{py}) target=({ex},{ey}) "
        f"panel_wait={panel_wait:g}s [left_top]",
        gui_verbose_only=True,
    )
    click_client_left_top(config, px, py, "express_emoji_panel")
    sleep_interruptible(panel_wait)
    click_client_left_top(config, ex, ey, f"express_emoji_{emoji}")
    return True


def wait_after_express_station_round1_emoji(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    发表情后轮询画板快照，等待对手回**相同**表情（最长 ``wait_after_send_seconds``）。

    仅当对手 ``EmojiCid`` 与己方配置表情一致时视为暗号对上；否则超时后走后端估价。
    """
    from ..analysis._board_pricing import map_id_from_board_snapshot
    from ..analysis.strategy.ahmad import map_bundle_is_express_station_series

    if not isinstance(board_snapshot, dict):
        return board_snapshot
    mid = map_id_from_board_snapshot(board_snapshot)
    if mid is None or not map_bundle_is_express_station_series(int(mid)):
        return board_snapshot

    settings = _express_station_round1_emoji_settings(
        _automation_with_map_overlay(config, board_snapshot),
        config,
    )
    if not settings["enabled"]:
        return board_snapshot

    wait_sec = float(settings["wait_after_send_seconds"])
    if wait_sec <= 0.0:
        return load_board_snapshot_for_loop(config) or board_snapshot

    self_emoji_cid = int(settings.get("self_emoji_cid") or 0)
    emoji_name = str(settings.get("emoji") or "")
    log(
        f"快递站发表情后等待对手回相同表情「{emoji_name}」(cid={self_emoji_cid})，"
        f"最长 {wait_sec:g} 秒…",
        gui_verbose_only=True,
    )
    deadline = time.monotonic() + wait_sec
    poll = min(0.5, max(0.25, wait_sec / 6.0))

    while time.monotonic() < deadline:
        ensure_not_stopped()
        bs = load_board_snapshot_for_loop(config)
        if isinstance(bs, dict) and _opponent_matched_emoji_signal(
            bs, config, expected_emoji_cid=self_emoji_cid
        ):
            log("对手已回相同表情，暗号对上，提前结束等待", gui_verbose_only=True)
            return bs
        remain = deadline - time.monotonic()
        if remain <= 0.0:
            break
        sleep_interruptible(min(poll, remain))

    bs_final = load_board_snapshot_for_loop(config) or board_snapshot
    if _opponent_matched_emoji_signal(
        bs_final, config, expected_emoji_cid=self_emoji_cid
    ):
        log("等待结束：对手表情与己方一致（暗号价）", gui_verbose_only=True)
    else:
        log(
            "等待结束：对手未回相同表情或未回表情，走后端估价出价",
            gui_verbose_only=True,
        )
    return bs_final if isinstance(bs_final, dict) else board_snapshot


# 实时道具推送；``S2C_37`` 汇总里也可能带 ItemSkillLog，但 bot 点道具后等 S2C_39 落盘。
_TOOL_ITEM_SKILL_LOG_EVENT_TYPES = frozenset({"S2C_39_game_use_item"})


def _item_skill_log_keys_from_snapshot(
    board_snapshot: dict[str, Any] | None,
    *,
    event_types: frozenset[str] | None = _TOOL_ITEM_SKILL_LOG_EVENT_TYPES,
) -> frozenset[str]:
    """``skill_logs`` 中 ``ItemSkillLog`` 条目键：优先 ``Uid``，无则退化为事件指纹。"""
    if not isinstance(board_snapshot, dict):
        return frozenset()
    keys: set[str] = set()
    for block in board_snapshot.get("skill_logs") or []:
        if not isinstance(block, dict):
            continue
        et = str(block.get("event_type") or "")
        if event_types is not None and et not in event_types:
            continue
        gd = block.get("game_data")
        if not isinstance(gd, dict):
            continue
        logs = gd.get("ItemSkillLog")
        if not isinstance(logs, list) or not logs:
            continue
        rx = block.get("received_at_unix")
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            uid = str(entry.get("Uid") or "").strip()
            if uid:
                keys.add(uid)
                continue
            try:
                item_cid = int(entry.get("ItemCid") or 0)
                skill_cid = int(entry.get("SkillCid") or 0)
            except (TypeError, ValueError):
                item_cid = 0
                skill_cid = 0
            cast_time = str(entry.get("CastTime") or "")
            keys.add(f"{et}|{rx}|{skill_cid}|{item_cid}|{cast_time}")
    return frozenset(keys)


def _new_item_skill_log_detail(
    fresh: dict[str, Any],
    prior_item_log_keys: frozenset[str],
) -> str | None:
    new_item_keys = _item_skill_log_keys_from_snapshot(fresh) - prior_item_log_keys
    if not new_item_keys:
        return None
    sample = next(iter(new_item_keys))
    extra = len(new_item_keys) - 1
    detail = sample if extra <= 0 else f"{sample} (+{extra})"
    return f"new ItemSkillLog {detail}"


def wait_board_snapshot_after_tool(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """道具后：轮询快照直至出现新 ``ItemSkillLog``，再固定等待 ``tool_after_wait_seconds`` 供游戏渲染。

    - ``tool_after_snapshot_poll_seconds``：最长轮询等待新道具日志落盘（默认 8s）。
    - ``tool_after_wait_seconds``：见到新日志后的固定渲染等待（默认 5s），与轮询提前结束无关。

    grid_view 在日志 tail 发现 ``S2C_39_game_use_item`` 后写入 ``skill_logs`` 并重算
    ``pricing``；bot 若在回合初缓存快照且道具后不重读，会按道具前画板估价出价。
    """
    timing = config.get("timing", {}) or {}
    render_wait = float(timing.get("tool_after_wait_seconds", 5.0) or 0.0)
    poll_timeout = float(timing.get("tool_after_snapshot_poll_seconds", 8.0) or 0.0)
    prior_item_log_keys = _item_skill_log_keys_from_snapshot(board_snapshot)

    if poll_timeout <= 0.0 and render_wait <= 0.0:
        fresh = load_board_snapshot_for_loop(config)
        return fresh if isinstance(fresh, dict) else board_snapshot

    poll = min(0.5, max(0.25, poll_timeout / 10.0) if poll_timeout > 0 else 0.25)
    deadline = time.monotonic() + max(0.0, poll_timeout)
    best: dict[str, Any] | None = (
        board_snapshot if isinstance(board_snapshot, dict) else None
    )

    def _sleep_render_wait() -> None:
        if render_wait <= 0.0:
            return
        log(
            f"after tool: 已获得新 ItemSkillLog，等待游戏渲染 {render_wait:g}s …",
            gui_verbose_only=True,
        )
        sleep_interruptible(render_wait)

    while poll_timeout > 0.0:
        ensure_not_stopped()
        fresh = load_board_snapshot_for_loop(config)
        if isinstance(fresh, dict):
            best = fresh
            reason = _new_item_skill_log_detail(fresh, prior_item_log_keys)
            if reason:
                log(f"after tool: snapshot {reason}", gui_verbose_only=True)
                _sleep_render_wait()
                return fresh
        remain = deadline - time.monotonic()
        if remain <= 0.0:
            break
        sleep_interruptible(min(poll, remain))

    if _item_skill_log_keys_from_snapshot(best) == prior_item_log_keys:
        log(
            f"after tool: 轮询 {poll_timeout:g}s 后仍无新 ItemSkillLog，按当前快照出价",
            gui_verbose_only=True,
        )
    return best if isinstance(best, dict) else board_snapshot


def _aisha_round4_vacant_gate_enabled(
    config: dict[str, Any],
    board_snapshot: dict[str, Any] | None = None,
) -> bool:
    return bool(
        _automation_with_map_overlay(config, board_snapshot).get(
            "enable_aisha_round4_tool_vacant_gate", False
        )
    )


def _aisha_round4_tool_min_vacant(automation: dict[str, Any]) -> int:
    if "aisha_round4_tool_min_vacant" in automation:
        return int(automation["aisha_round4_tool_min_vacant"])
    # 兼容旧键：语义同为「空置格 >= n 才用道具」
    return int(automation.get("tool_skip_vacant_threshold", 30))


def _aisha_round4_tool_gate_vacant_count(
    board_snapshot: dict[str, Any],
) -> tuple[int | None, int, int]:
    """第 4 回合道具门控用空置量：几何空置 + 自动 ``phantom_vac_*`` 占格。

    返回 ``(effective, geometric, auto_phantom_cells)``；几何空置未知时 ``effective`` 为 ``None``。
    """
    from ..analysis.grid_overlay import auto_vacant_rect_phantom_cell_count_from_snapshot

    pricing = board_snapshot.get("pricing") or {}
    vacant = pricing.get("vacant")
    if vacant is None:
        _log_aisha_vacant_gate(
            "effective=None (pricing.vacant 未知，无法计算 geom+auto_phantom)"
        )
        return None, 0, 0
    geom = int(vacant)
    auto_cells = auto_vacant_rect_phantom_cell_count_from_snapshot(board_snapshot)
    effective = geom + auto_cells
    _log_aisha_vacant_gate(
        f"effective={effective} = pricing.vacant({geom}) + auto_phantom_cells({auto_cells})"
    )
    return effective, geom, auto_cells


def _aisha_round4_q5_grid_stats_known(
    board_snapshot: dict[str, Any],
) -> tuple[bool, str]:
    """``raw_pricing.event_stats`` 中 ``q5_grid_count`` 或 ``q5_grid_avg`` 已公开。"""
    from ..analysis._board_pricing import _event_stat_grid_count_optional

    raw = board_snapshot.get("raw_pricing")
    if not isinstance(raw, dict):
        return False, ""
    st = raw.get("event_stats")
    if not isinstance(st, dict):
        return False, ""
    if _event_stat_grid_count_optional(st, "q5_grid_count") is not None:
        return True, "q5_grid_count"
    avg = st.get("q5_grid_avg")
    if avg is not None:
        try:
            if float(avg) >= 0:
                return True, "q5_grid_avg"
        except (TypeError, ValueError):
            pass
    return False, ""


def _self_hero_cid_from_snapshot(
    board_snapshot: dict[str, Any] | None,
    config: dict[str, Any],
) -> int | None:
    if not isinstance(board_snapshot, dict):
        return None
    from ..analysis._board_pricing import _self_player_hero_cid

    bs_cfg = config.get("board_snapshot") or {}
    return _self_player_hero_cid(
        board_snapshot,
        board_snapshot_config=bs_cfg if isinstance(bs_cfg, dict) else None,
    )


def should_skip_tool_for_aisha_vacant_gate(
    *,
    config: dict[str, Any],
    round_no: int,
    tool_rounds: set[int],
    board_snapshot: dict[str, Any] | None,
) -> tuple[bool, str]:
    """是否因艾莎空置格规则跳过道具。

    返回 ``(skip_tool, reason)``：``True``=本回合不用道具，``False``=本函数不拦截
    （是否用道具仍由 ``tool_rounds`` 等决定）。

    功能开关开启时：第5回合一律 ``skip``；第4回合艾莎且已勾选时若已公开
    ``q5_grid_count`` / ``q5_grid_avg`` 则 ``skip``；否则仅
    ``pricing.vacant + 自动 phantom_vac_* 占格 >= min_vacant`` 时不 ``skip``。
    """
    if not _aisha_round4_vacant_gate_enabled(config, board_snapshot):
        return False, ""
    rn = int(round_no)
    if rn == AISHA_ROUND5_TOOL_ROUND:
        return True, f"round {rn}: aisha vacant-gate enabled, round5 tool disabled"
    if rn != AISHA_ROUND4_TOOL_ROUND:
        return False, ""
    if AISHA_ROUND4_TOOL_ROUND not in tool_rounds:
        return False, ""
    if _self_hero_cid_from_snapshot(board_snapshot, config) != AISHA_HERO_CID:
        return False, ""
    auto = _automation_with_map_overlay(config, board_snapshot)
    min_vacant = _aisha_round4_tool_min_vacant(auto)
    if not isinstance(board_snapshot, dict):
        _log_aisha_vacant_gate(f"round {rn}: no board snapshot, skip tool")
        return True, f"round {rn}: aisha round4 no board snapshot, skip tool"
    effective, geom, auto_phantom = _aisha_round4_tool_gate_vacant_count(
        board_snapshot
    )
    _log_aisha_vacant_gate(
        f"round {rn}: min_vacant={min_vacant} (aisha_round4_tool_min_vacant)"
    )
    q5_known, q5_key = _aisha_round4_q5_grid_stats_known(board_snapshot)
    if q5_known:
        _log_aisha_vacant_gate(
            f"round {rn}: {q5_key} known -> skip tool (effective 见上条)"
        )
        return True, f"round {rn}: aisha round4 {q5_key} known, skip tool"
    if effective is None:
        return True, f"round {rn}: aisha round4 vacant unknown, skip tool"
    if int(effective) < min_vacant:
        vac_detail = f"vacant={geom}"
        if auto_phantom > 0:
            vac_detail = f"{vac_detail}+auto_phantom={auto_phantom}={effective}"
        _log_aisha_vacant_gate(
            f"round {rn}: {vac_detail} < {min_vacant} -> skip tool"
        )
        return (
            True,
            f"round {rn}: aisha round4 {vac_detail} < {min_vacant}, skip tool",
        )
    _log_aisha_vacant_gate(
        f"round {rn}: effective={effective} >= {min_vacant} -> 不拦截道具"
    )
    return False, ""


def should_skip_aisha_round4_tool_by_vacant(
    *,
    config: dict[str, Any],
    round_no: int,
    tool_rounds: set[int],
    board_snapshot: dict[str, Any] | None,
) -> bool:
    """兼容旧调用：仅返回是否跳过（见 :func:`should_skip_tool_for_aisha_vacant_gate`）。"""
    skip, _ = should_skip_tool_for_aisha_vacant_gate(
        config=config,
        round_no=round_no,
        tool_rounds=tool_rounds,
        board_snapshot=board_snapshot,
    )
    return skip


def run_aisha_loop(config_path: Path, **run_loop_kwargs: Any) -> None:
    """兼容入口：清快照、强制 ``aisha_premium`` 后进入 :func:`run_loop`。"""
    cfg0 = load_merged_bot_config(config_path)
    if board_snapshot_file_missing(cfg0):
        log(
            "启动时未发现 board_snapshot 文件：按新一局处理；请先在游戏内开局，"
            "画板监听写入快照后即可继续。"
        )
    run_loop(
        config_path,
        app_log_path=Path.cwd() / "fresh_aisha_bot.log",
        clear_snapshot_on_start=True,
        force_selected_mode="aisha_premium",
        **run_loop_kwargs,
    )


def handle_round(
    config: dict[str, Any],
    config_path: Path,
    round_no: int,
    *,
    tool_rounds: set[int] | None = None,
) -> None:
    ensure_not_stopped()
    bs_data = load_board_snapshot_for_loop(config)
    timing_cfg = config.get("timing", {}) or {}
    if int(round_no) <= 1:
        sleep_interruptible(
            float(timing_cfg.get("round1_extra_wait_seconds", 0.0))
        )
        if try_send_express_station_round1_emoji(config, bs_data):
            waited = wait_after_express_station_round1_emoji(config, bs_data)
            if isinstance(waited, dict):
                bs_data = waited
    sleep_interruptible(float(timing_cfg.get("round_detect_wait_seconds", 0.0) or 0.0))
    if tool_rounds is None:
        from ..config.map_chain import default_tool_rounds

        tool_rounds = set(default_tool_rounds(config.get("automation") or {}))
    rn = int(round_no)
    ran_tool_this_round = rn in tool_rounds
    if rn >= NO_TOOL_FROM_ROUND:
        if ran_tool_this_round:
            log(
                f"round {rn}: tool disabled (round>={NO_TOOL_FROM_ROUND})",
                gui_verbose_only=True,
            )
        ran_tool_this_round = False
    skip_tool, skip_reason = should_skip_tool_for_aisha_vacant_gate(
        config=config,
        round_no=int(round_no),
        tool_rounds=tool_rounds,
        board_snapshot=bs_data,
    )
    if int(round_no) == AISHA_ROUND4_TOOL_ROUND:
        _log_aisha_vacant_gate(
            f"handle_round: skip_tool={skip_tool}"
            + (f" reason={skip_reason}" if skip_reason else " (门控未介入)")
        )
    if ran_tool_this_round and skip_tool:
        log(skip_reason, gui_verbose_only=True)
        ran_tool_this_round = False

    if ran_tool_this_round:
        run_tool_sequence(config)
        log(f"after tool", gui_verbose_only=True)
        bs_data = wait_board_snapshot_after_tool(config, bs_data)
    else:
        log(f"round {round_no}: tool skipped", gui_verbose_only=True)

    fresh_bs = load_board_snapshot_for_loop(config)
    if isinstance(fresh_bs, dict):
        bs_data = fresh_bs

    price, details = compute_price(
        config,
        config_path=config_path,
        round_no=int(round_no),
        board_snapshot=bs_data,
    )
    log(f"compute_price -> {price}")
    log(f"bid details: {format_bid_details_line(details)}")
    if details.get("fallback"):
        log(f"price fallback: {price}; reason={details.get('reason')}")
    save_round_debug_bundle(
        config,
        config_path,
        round_no=round_no,
        raw_text="",
        details=details,
        final_price=price,
    )
    bid_outcome = input_bid(config, price, round_no=int(round_no))
    if bid_outcome in ("bid_ok", "unverified"):
        try:
            from ..pricing.self_bid_cache import (
                record_self_gold_bid,
                resolve_self_bid_cache_amount,
            )

            bs_rec = load_board_snapshot_for_loop(config)
            cache_amount = resolve_self_bid_cache_amount(int(price), details)
            record_self_gold_bid(
                config,
                round_no=int(round_no),
                bid_amount=cache_amount,
                board_snapshot=bs_rec,
            )
        except Exception:
            pass
    elif bid_outcome == "verify_timeout":
        log(f"round {round_no}: bid confirm failed (verify_timeout)", gui_verbose_only=True)
    elif bid_outcome == "next_round":
        log(
            f"round {round_no}: bid confirm stopped (entered next round in snapshot)",
            gui_verbose_only=True,
        )
    elif bid_outcome == "game_over":
        log(
            f"round {round_no}: bid confirm stopped (S2C_45_game_over_notify in snapshot)",
            gui_verbose_only=True,
        )
    bs_after_bid = load_board_snapshot_for_loop(config)
    _express_after_snapshot_hooks(config, bs_after_bid)


def handle_end_transition(
    config: dict[str, Any],
    handled_rounds: set[int],
    last_end_at: float,
    transition_debounce: float,
    source: str,
) -> tuple[float, float]:
    if time.monotonic() - last_end_at < transition_debounce:
        log(f"{source}: end prompt ignored by debounce", gui_verbose_only=True)
        return last_end_at, 0.0
    log(f"{source}: end prompt detected", gui_verbose_only=True)
    confirm_at = run_post_round_transition(config)
    handled_rounds.clear()
    return time.monotonic(), confirm_at


def run_loop(
    config_path: Path,
    *,
    app_log_path: Path | None = None,
    clear_snapshot_on_start: bool = False,
    force_selected_mode: str | None = None,
    progress_sink: Callable[[int, int], None] | None = None,
) -> None:
    # 与控制台同内容的运行日志；cwd 在脚本与 PyInstaller exe 下均为进程当前工作目录
    set_app_log_file(app_log_path or (Path.cwd() / "bidking_fresh_bot.log"))
    config = load_merged_bot_config(config_path)
    from .bot_startup_gate import BotStartupBlocked, ensure_bot_startup_allowed

    ensure_bot_startup_allowed()  # 使用启动阶段已缓存的远程开关
    set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
    if clear_snapshot_on_start:
        clear_board_snapshot_file(config)
    if force_selected_mode:
        config.setdefault("automation", {})["selected_mode"] = str(force_selected_mode)
    apply_pyautogui_from_config(config)
    lv = refresh_poll_loop_locals(config)
    map_chain: list[dict[str, Any]] = list(lv["map_chain"])
    selected_map = lv["selected_map"]
    max_runs = lv["max_runs"]
    runs_per_big_cycle = lv["runs_per_big_cycle"]
    run_cycles = lv["run_cycles"]
    cycle_rest_minutes = lv["cycle_rest_minutes"]
    chain_step_index = 0
    runs_on_chain_step = 0
    prepare_target_window(config, center=True)

    log("BidKing bot 已启动（交互层；出价由 pricing.compute_price 读快照计算）；按 F9 停止")
    if _aisha_round4_vacant_gate_enabled(config):
        auto = _automation_with_map_overlay(config)
        _log_aisha_vacant_gate(
            "已启用第4回合道具空置门控；"
            f"min_vacant={_aisha_round4_tool_min_vacant(auto)}；"
            "第4回合将打印 effective=pricing.vacant+auto_phantom_cells"
        )
    log("mode: full-window OCR -> lobby/end/round handling", gui_verbose_only=True)
    from ..config.map_chain import format_map_chain_plan

    auto_maps = (config.get("automation") or {}).get("maps") or {}
    log(
        format_map_chain_plan(
            map_chain,
            auto_maps if isinstance(auto_maps, dict) else {},
            runs_per_big_cycle=runs_per_big_cycle,
            run_cycles=run_cycles,
            max_runs=max_runs,
            cycle_rest_minutes=cycle_rest_minutes,
        ),
    )

    handled_rounds: set[int] = set()
    cached_game_uid: str | None = None
    preflight_esc_before_next_map_select = True
    await_non_lobby_after_preflight_esc = False
    await_non_lobby_stuck_polls = 0
    pending_game_start_deadline: float | None = None
    map_select_no_start_streak = 0
    startup_warehouse_sort_done = False
    home_uid_sync_done = False
    warehouse_sort_milestones_done: set[int] = set()
    completed_runs = 0
    last_end_at = 0.0
    last_lobby_at = 0.0
    last_home_bid_at = 0.0
    last_reward_continue_at = 0.0
    last_failed_auction_at = 0.0
    last_unknown_escape_at = 0.0
    last_post_continue_confirm_at = 0.0
    poll_seconds = lv["poll_seconds"]
    transition_debounce = lv["transition_debounce"]
    reward_continue_debounce = lv["reward_continue_debounce"]
    unknown_escape_cooldown = lv["unknown_escape_cooldown"]
    post_confirm_escape_block_seconds = lv["post_confirm_escape_block_seconds"]
    stuck_handled_enabled = lv["stuck_handled_enabled"]
    stuck_handled_threshold = lv["stuck_handled_threshold"]
    stuck_already_handled_polls = 0
    loop_index = 0

    def _notify_run_progress() -> None:
        if progress_sink is not None:
            progress_sink(completed_runs, max_runs)

    def _map_display_name(map_key: str) -> str:
        maps_cfg = (config.get("automation") or {}).get("maps") or {}
        if isinstance(maps_cfg, dict):
            item = maps_cfg.get(str(map_key), {})
            if isinstance(item, dict):
                return str(item.get("name") or map_key)
        return str(map_key)

    def _advance_map_chain_after_run() -> bool:
        """本局结束后推进链式下标；若走完一整条链返回 True（可触发大循环休息）。"""
        nonlocal chain_step_index, runs_on_chain_step, selected_map, map_chain
        if not map_chain:
            return False
        runs_on_chain_step += 1
        step = map_chain[chain_step_index]
        if runs_on_chain_step < int(step["runs"]):
            return False
        runs_on_chain_step = 0
        finished_big_cycle = False
        next_index = chain_step_index + 1
        if next_index >= len(map_chain):
            chain_step_index = 0
            finished_big_cycle = True
        else:
            chain_step_index = next_index
        prev_map = selected_map
        selected_map = str(map_chain[chain_step_index]["map_id"])
        if prev_map != selected_map:
            log(
                f"链式切图：{prev_map}.{_map_display_name(prev_map)} "
                f"→ {selected_map}.{_map_display_name(selected_map)}"
            )
        return finished_big_cycle

    def _maybe_cycle_rest(*, finished_big_cycle: bool) -> None:
        if (
            finished_big_cycle
            and completed_runs < max_runs
            and cycle_rest_minutes > 0.0
        ):
            rest_sec = float(cycle_rest_minutes) * 60.0 * random.uniform(0.9, 1.1)
            log(
                f"已完成一整条地图链（{runs_per_big_cycle} 局，累计 {completed_runs}/{max_runs}），"
                f"大循环休息约 {rest_sec / 60.0:.2f} 分钟（配置 {cycle_rest_minutes:g} 分钟 ±10%）…"
            )
            sleep_interruptible(rest_sec)

    def _on_single_run_completed() -> bool:
        """登记完成一局并处理链式/休息；返回 True 表示已达目标局数应退出。"""
        nonlocal completed_runs, preflight_esc_before_next_map_select
        completed_runs += 1
        preflight_esc_before_next_map_select = True
        log(f"completed runs: {completed_runs}/{max_runs}")
        _notify_run_progress()
        finished_big = _advance_map_chain_after_run()
        _maybe_cycle_rest(finished_big_cycle=finished_big)
        return completed_runs >= max_runs

    _notify_run_progress()
    while True:
        loop_index += 1
        try:
            ensure_not_stopped()
            # 与 GUI 写入的 config.json 同步，便于不停止脚本时调整参数
            config = load_merged_bot_config(config_path)
            set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
            if force_selected_mode:
                config.setdefault("automation", {})["selected_mode"] = str(force_selected_mode)
            apply_pyautogui_from_config(config)
            lv = refresh_poll_loop_locals(config)
            poll_seconds = lv["poll_seconds"]
            transition_debounce = lv["transition_debounce"]
            reward_continue_debounce = lv["reward_continue_debounce"]
            unknown_escape_cooldown = lv["unknown_escape_cooldown"]
            post_confirm_escape_block_seconds = lv["post_confirm_escape_block_seconds"]
            stuck_handled_enabled = lv["stuck_handled_enabled"]
            stuck_handled_threshold = lv["stuck_handled_threshold"]
            new_chain = list(lv["map_chain"])
            if new_chain:
                map_chain[:] = new_chain
                if chain_step_index >= len(map_chain):
                    chain_step_index = 0
                    runs_on_chain_step = 0
                selected_map = str(map_chain[chain_step_index]["map_id"])
            max_runs = lv["max_runs"]
            runs_per_big_cycle = lv["runs_per_big_cycle"]
            run_cycles = lv["run_cycles"]
            cycle_rest_minutes = lv["cycle_rest_minutes"]
            _notify_run_progress()
            game_start_timeout_seconds = lv["game_start_timeout_seconds"]
            map_select_no_start_esc_after = lv["map_select_no_start_esc_after"]
            mode_loop = str(
                (config.get("automation") or {}).get("selected_mode", "ahmad_premium")
            ).strip().lower()
            if mode_loop in ("normal", "express"):
                mode_loop = "ahmad_premium"

            observation = observe_state_poll(config, config_path, "poll")

            bs_cfg = config.get("board_snapshot") or {}
            bs_data = load_board_snapshot_for_loop(config)
            snap_round = current_round_from_snapshot(bs_data) if bs_data else None
            poll_round = observation.round_no
            round_no = resolve_loop_round_no(poll_round, bs_data)

            if await_non_lobby_after_preflight_esc and not observation.auction_lobby:
                await_non_lobby_after_preflight_esc = False
                await_non_lobby_stuck_polls = 0

            if pending_game_start_deadline is not None:
                if game_started_from_poll(observation):
                    pending_game_start_deadline = None
                    map_select_no_start_streak = 0
                elif time.monotonic() >= pending_game_start_deadline:
                    map_select_no_start_streak += 1
                    if map_select_no_start_streak >= map_select_no_start_esc_after:
                        log(
                            f"loop {loop_index}: 连续 {map_select_no_start_esc_after} 次选图后仍未检测到开局，"
                            "按 ESC 回主界面后重试"
                        )
                        press_escape(config)
                        preflight_esc_before_next_map_select = False
                        await_non_lobby_after_preflight_esc = True
                        await_non_lobby_stuck_polls = 0
                        pending_game_start_deadline = None
                        map_select_no_start_streak = 0
                        last_lobby_at = 0.0
                    else:
                        log(
                            f"loop {loop_index}: 选图后 {game_start_timeout_seconds:.0f}s 内未检测到开局 "
                            f"（{map_select_no_start_streak}/{map_select_no_start_esc_after}），"
                            "不重按 ESC，直接重试选图",
                            gui_verbose_only=True,
                        )
                        pending_game_start_deadline = None
                        last_lobby_at = 0.0
                    sleep_interruptible(poll_seconds)
                    continue

            game_uid = game_uid_from_snapshot(bs_data)
            if (
                game_uid is not None
                and cached_game_uid is not None
                and game_uid != cached_game_uid
            ):
                log(
                    f"loop {loop_index}: 新局 game_uid {cached_game_uid!r} -> {game_uid!r}；"
                    "重置回合状态并清空 self_bid_cache"
                )
                handled_rounds.clear()
                _express_round1_signal_bid_by_game.clear()
                try:
                    from ..pricing.self_bid_cache import clear_self_bid_disk_cache

                    clear_self_bid_disk_cache(reason="bot_loop_new_game_uid")
                except Exception:
                    pass
            if game_uid is not None:
                cached_game_uid = game_uid

            if isinstance(bs_data, dict):
                _express_after_snapshot_hooks(config, bs_data)

            log(
                f"loop {loop_index}: snap_round={snap_round} poll_round={poll_round} "
                f"effective_round={round_no} "
                f"end={observation.end_prompt} lobby={observation.auction_lobby} "
                f"reward_continue={observation.reward_continue} "
                f"failed_auction={observation.failed_auction_settlement} "
                f"home_bid={observation.home_bid_button} any={observation.has_any_signal}",
                gui_verbose_only=True,
            )

            if not observation.has_any_signal:
                since_post_confirm = time.monotonic() - last_post_continue_confirm_at
                if since_post_confirm < post_confirm_escape_block_seconds:
                    log(
                        f"loop {loop_index}: no signal, esc blocked after post_continue_confirm "
                        f"({since_post_confirm:.1f}/{post_confirm_escape_block_seconds:.1f}s)",
                        gui_verbose_only=True,
                    )
                elif time.monotonic() - last_unknown_escape_at >= unknown_escape_cooldown:
                    press_escape(config)
                    last_unknown_escape_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: no signal, esc on cooldown", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.end_prompt:
                pending_game_start_deadline = None
                map_select_no_start_streak = 0
                if isinstance(bs_data, dict):
                    _express_after_snapshot_hooks(config, bs_data)
                last_end_at, confirm_at = handle_end_transition(
                    config,
                    handled_rounds,
                    last_end_at,
                    transition_debounce,
                    f"loop {loop_index}",
                )
                if confirm_at:
                    last_post_continue_confirm_at = confirm_at
                if _on_single_run_completed():
                    _on_target_runs_reached(config)
                    return
                sleep_interruptible(poll_seconds)
                continue

            if observation.reward_continue:
                pending_game_start_deadline = None
                map_select_no_start_streak = 0
                if time.monotonic() - last_reward_continue_at >= reward_continue_debounce:
                    run_reward_continue_transition(config)
                    last_reward_continue_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: reward continue ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.failed_auction_settlement:
                pending_game_start_deadline = None
                map_select_no_start_streak = 0
                if time.monotonic() - last_failed_auction_at >= transition_debounce:
                    run_failed_auction_settlement_transition(config)
                    preflight_esc_before_next_map_select = True
                    handled_rounds.clear()
                    last_failed_auction_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: failed auction settlement ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.auction_lobby:
                if time.monotonic() - last_lobby_at >= transition_debounce:
                    if preflight_esc_before_next_map_select:
                        log(
                            f"loop {loop_index}: auction lobby: 开局前先 ESC 回主界面，"
                            "再由主页进入选图",
                            gui_verbose_only=True,
                        )
                        press_escape(config)
                        preflight_esc_before_next_map_select = False
                        await_non_lobby_after_preflight_esc = True
                        await_non_lobby_stuck_polls = 0
                        last_lobby_at = time.monotonic()
                    elif await_non_lobby_after_preflight_esc:
                        await_non_lobby_stuck_polls += 1
                        if await_non_lobby_stuck_polls > 5:
                            log(
                                f"loop {loop_index}: auction lobby: 已 ESC 后仍在大厅 "
                                f"（{await_non_lobby_stuck_polls} 次轮询），再按一次 ESC",
                                gui_verbose_only=True,
                            )
                            press_escape(config)
                            await_non_lobby_stuck_polls = 0
                        else:
                            log(
                                f"loop {loop_index}: auction lobby: 已 ESC，"
                                "等待退出大厅界面后再从主页进入选图",
                                gui_verbose_only=True,
                            )
                        sleep_interruptible(poll_seconds)
                        continue
                    else:
                        confirm_at = run_map_selection_transition(config, selected_map)
                        if confirm_at:
                            last_post_continue_confirm_at = confirm_at
                            pending_game_start_deadline = (
                                time.monotonic() + game_start_timeout_seconds
                            )
                        handled_rounds.clear()
                        last_lobby_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: auction lobby ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.home_bid_button:
                if time.monotonic() - last_home_bid_at >= transition_debounce:
                    sync_home_uid = not home_uid_sync_done
                    if enforce_map_entry_money_on_home_screen(
                        config,
                        config_path,
                        selected_map=selected_map,
                        full_window_text=observation.capture.text,
                        sync_home_uid=sync_home_uid,
                    ):
                        request_stop()
                        return
                    if sync_home_uid:
                        home_uid_sync_done = True
                    wc = merge_warehouse_auto_sort_settings(config)
                    if bool(wc.get("enabled", True)):
                        need_wh_sort = False
                        reason = ""
                        if not startup_warehouse_sort_done:
                            need_wh_sort = True
                            reason = "开局首次回到主页"
                        elif (
                            completed_runs > 0
                            and completed_runs % 10 == 0
                            and completed_runs not in warehouse_sort_milestones_done
                        ):
                            need_wh_sort = True
                            reason = f"已完成 {completed_runs} 局（每 10 局整理）"
                        if need_wh_sort:
                            log(f"warehouse auto_sort: 触发整理 ({reason})", gui_verbose_only=True)
                            run_warehouse_auto_sort(config)
                            startup_warehouse_sort_done = True
                            if completed_runs > 0 and completed_runs % 10 == 0:
                                warehouse_sort_milestones_done.add(int(completed_runs))
                run_home_bid_button_transition(config)
                last_home_bid_at = time.monotonic()
                sleep_interruptible(poll_seconds)
                continue

            if round_no is None:
                if not bs_data:
                    log(
                        f"loop {loop_index}: 尚无有效 board_snapshot 且无 OCR 回合；"
                        "可先开局，等待画板写入快照",
                        gui_verbose_only=True,
                    )
                else:
                    log(f"loop {loop_index}: no round detected; waiting", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if round_no == 1 and any(value > 1 for value in handled_rounds):
                log("new auction inferred from round 1; reset handled rounds")
                handled_rounds.clear()
            if round_no not in handled_rounds:
                stuck_already_handled_polls = 0

            if round_no in handled_rounds:
                stuck_already_handled_polls += 1
                if (
                    stuck_handled_enabled
                    and stuck_already_handled_polls >= stuck_handled_threshold
                ):
                    log(
                        f"stuck after handled round: {stuck_already_handled_polls} consecutive polls "
                        f"(threshold={stuck_handled_threshold}); running screen recovery"
                    )
                    run_stuck_after_handled_recovery(config)
                    stuck_already_handled_polls = 0
                    handled_rounds.clear()
                    sleep_interruptible(poll_seconds)
                    continue
                log(f"loop {loop_index}: round {round_no} already handled; waiting", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            log(f"loop {loop_index}: round {round_no} -> handle_round", gui_verbose_only=True)
            from ..config.map_chain import tool_rounds_set_for_chain_step

            auto_cfg = config.get("automation") or {}
            if map_chain and 0 <= chain_step_index < len(map_chain):
                round_tools = tool_rounds_set_for_chain_step(
                    map_chain[chain_step_index], auto_cfg
                )
            else:
                from ..config.map_chain import default_tool_rounds

                round_tools = set(default_tool_rounds(auto_cfg))
            handle_round(config, config_path, round_no, tool_rounds=round_tools)
            handled_rounds.add(round_no)

            if round_no >= 5:
                log(
                    f"round {round_no} handled; waiting for end prompt or a new OCR state",
                    gui_verbose_only=True,
                )

            sleep_interruptible(poll_seconds)
        except KeyboardInterrupt:
            log("stopped by Ctrl+C")
            return
        except StopRequested:
            log("stopped by GUI")
            return
        except EndPromptDetected as exc:
            pending_game_start_deadline = None
            map_select_no_start_streak = 0
            last_end_at, confirm_at = handle_end_transition(
                config,
                handled_rounds,
                last_end_at,
                transition_debounce,
                f"active handling ({exc.source})",
            )
            if confirm_at:
                last_post_continue_confirm_at = confirm_at
            if _on_single_run_completed():
                _on_target_runs_reached(config)
                return
            sleep_interruptible(poll_seconds)
        except Exception as exc:
            log(f"error: {type(exc).__name__}: {exc}")
            sleep_interruptible(max(1.0, poll_seconds))


def print_click_positions(config_path: Path) -> None:
    config = load_merged_bot_config(config_path)
    info = find_window(config.get("window", {}))
    log(
        f"window hwnd={info.hwnd} client_origin={info.client_origin} client_size={info.width}x{info.height}",
        gui_verbose_only=True,
    )
    for name in (
        "tool_button",
        "leftmost_tool",
        "tool_confirm",
        "tool_post_confirm",
        "bid_button",
        "bid_input_box",
        "bid_confirm",
        "end_reward_click",
        "end_close_click",
        "continue_button",
        "post_continue_action",
        "post_continue_confirm",
        "reward_continue_button",
    ):
        point = config.get("clicks", {}).get(name)
        if not point:
            continue
        sx, sy = client_to_screen(config, point)
        origin = point.get("origin", "left_top")
        log(
            f"{name}: config=({point['x']},{point['y']}) origin={origin} -> screen=({sx},{sy})",
            gui_verbose_only=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh BidKing bot loop.")
    parser.add_argument("--config", default=str(config_overlay_path()))
    parser.add_argument("--print-clicks", action="store_true", help="Print converted screen click positions and exit.")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.print_clicks:
        print_click_positions(config_path)
        return 0
    else:
        config = load_merged_bot_config(config_path)
        auto = config.get("automation") or {}
        maps = auto.get("maps") if isinstance(auto.get("maps"), dict) else {}
        default_map = resolve_automation_map_config_key(auto)
        default_runs = int(config.get("automation", {}).get("default_runs", 1))
        print("请选择地图：")
        for key in automation_maps_sorted_keys(maps):
            item = maps.get(key, {})
            print(f"{key}. {item.get('name', key)}")
        map_input = input(f"地图编号 [默认 {default_map}]: ").strip() or default_map
        runs_input = input(f"刷取次数 [默认 {default_runs}]: ").strip() or str(default_runs)
        selected_runs = int(runs_input) if runs_input.isdigit() and int(runs_input) > 0 else default_runs
        persist_overlay_patch(
            config_path,
            {"automation": {"selected_map": map_input, "selected_runs": selected_runs}},
        )
        reset_stop()
        from .bot_startup_gate import BotStartupBlocked, prime_bot_gate_cache

        prime_bot_gate_cache(load_merged_bot_config(config_path), force=True)
        try:
            run_loop(config_path)
        except BotStartupBlocked as exc:
            print(str(exc))
            return 1
    return 0


def main_aisha() -> int:
    """交互式选择地图/次数后写入配置并启动 :func:`run_aisha_loop`（旧 ``_legacy_aisha.main``）。"""
    parser = argparse.ArgumentParser(description="BidKing 艾莎兼容 CLI（fresh_aisha_bot）。")
    parser.add_argument("--config", default=str(config_overlay_path()))
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_merged_bot_config(config_path)
    auto = config.get("automation") or {}
    maps = auto.get("maps") if isinstance(auto.get("maps"), dict) else {}
    default_map = resolve_automation_map_config_key(auto)
    default_runs = int(config.get("automation", {}).get("default_runs", 1))
    print("fresh_aisha_bot — 请选择地图：")
    for key in automation_maps_sorted_keys(maps):
        item = maps.get(key, {})
        print(f"{key}. {item.get('name', key)}")
    map_input = input(f"地图编号 [默认 {default_map}]: ").strip() or default_map
    runs_input = input(f"刷取次数 [默认 {default_runs}]: ").strip() or str(default_runs)
    selected_runs = int(runs_input) if runs_input.isdigit() and int(runs_input) > 0 else default_runs
    persist_overlay_patch(
        config_path,
        {
            "automation": {
                "selected_map": map_input,
                "selected_runs": selected_runs,
                "selected_mode": "aisha_premium",
            }
        },
    )
    reset_stop()
    from .bot_startup_gate import BotStartupBlocked, prime_bot_gate_cache

    prime_bot_gate_cache(load_merged_bot_config(config_path), force=True)
    try:
        run_aisha_loop(config_path)
    except BotStartupBlocked as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
