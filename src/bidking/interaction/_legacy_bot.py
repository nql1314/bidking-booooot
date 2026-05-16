#!/usr/bin/env python3
"""Fresh BidKing automation loop.

- 整窗 / 区域 OCR 识别大厅、结束、回合等界面状态；
- 固定流程：每回合先 OCR ``bid_confirm_region`` 见「出价」→ 道具 → 截图 OCR → :func:`compute_price`（读画板快照）→ 输入出价 → 确认；
- 若 OCR 见到「对局结束」等，执行固定的局后点击链。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyautogui
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent

from ..pricing.compute import compute_price as pricing_compute_price  # noqa: E402
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
}


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
    append_app_log(line)
    if gui_verbose_only and not _GUI_LOG_VERBOSE:
        return
    print(line, flush=True)


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
        elif br.get("skipped_multiplier_opponent_hero_103_or_107"):
            parts.append("ratio_skipped_r5_hero")

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

    bc = details.get("bid_cap")
    if isinstance(bc, dict) and bc.get("applied"):
        parts.append(f"bid_cap->{bc.get('cap_price')}")

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


def refresh_poll_loop_locals(config: dict[str, Any]) -> dict[str, Any]:
    """从 config 读取轮询间隔、地图与回合限制等，便于与 GUI 写入的 config.json 同步。"""
    timing = config.get("timing") or {}
    auto = config.get("automation") or {}
    safety = config.get("safety") or {}
    stuck = safety.get("stuck_after_handled_round") or {}
    return {
        "poll_seconds": float(timing.get("poll_seconds", 1.0)),
        "transition_debounce": float(timing.get("transition_debounce_seconds", 8.0)),
        "reward_continue_debounce": float(timing.get("reward_continue_debounce_seconds", 1.0)),
        "unknown_escape_cooldown": float(auto.get("unknown_escape_cooldown_seconds", 2.0)),
        "post_confirm_escape_block_seconds": float(auto.get("post_confirm_escape_block_seconds", 30.0)),
        "stuck_handled_enabled": bool(stuck.get("enabled", True)),
        "stuck_handled_threshold": max(1, int(stuck.get("consecutive_poll_threshold", 60))),
        "selected_map": resolve_automation_map_config_key(auto),
        "max_runs": int(auto.get("selected_runs") or auto.get("default_runs", 1)),
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
) -> tuple[int, dict[str, Any]]:
    """出价计算：调用 ``bidking.pricing``（读画板快照等均在 pricing 层完成）。"""
    bs_cfg = config.get("board_snapshot") or {}
    bs_data = load_board_snapshot_for_loop(config) if bool(bs_cfg.get("enabled")) else None
    effective_round = int(round_no)
    if bs_data is not None:
        sr = current_round_from_snapshot(bs_data)
        if sr is not None:
            effective_round = int(sr)
    return pricing_compute_price(
        config,
        config_path=config_path,
        round_no=effective_round,
        board_snapshot=bs_data,
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
        return value if 1 <= value <= 5 else None
    value = CHINESE_ROUND_NUMBERS.get(token)
    if value is not None and 1 <= value <= 5:
        return value
    return None


def parse_round_number(text: str) -> int | None:
    raw = normalize_text(text)
    patterns = [
        r"第\s*([1-5一二两三四五壹贰叁肆伍IⅤVⅡⅢⅣ]+)\s*(?:轮|回合)",
        r"(?:当前|现在)?(?:轮次|回合)\s*[:：]?\s*第?\s*([1-5一二两三四五壹贰叁肆伍IⅤVⅡⅢⅣ]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            value = round_token_to_int(match.group(1).upper())
            if value is not None:
                return value

    tight = compact_text(raw)
    for pattern in (
        r"第([1-5一二两三四五壹贰叁肆伍IⅤVⅡⅢⅣ]+)(?:轮|回合)",
        r"(?:轮次|回合)[:：]?第?([1-5一二两三四五壹贰叁肆伍IⅤVⅡⅢⅣ]+)",
    ):
        match = re.search(pattern, tight, flags=re.IGNORECASE)
        if match:
            value = round_token_to_int(match.group(1).upper())
            if value is not None:
                return value
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


def classify_bid_confirm_status(ocr_text: str) -> str:
    """根据出价状态区 OCR 文本分类：``bid_ok`` / ``abstain`` / ``unknown``。"""
    tight = compact_text(ocr_text)
    if "已出价" in tight:
        return "bid_ok"
    if "出价" in tight and ("已" in tight or "巳" in tight):
        return "bid_ok"
    if "弃权" in tight:
        return "abstain"
    return "unknown"


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


def _perform_bid_ui_sequence(config: dict[str, Any], price: int) -> None:
    log("bid sequence: open/input/confirm", gui_verbose_only=True)
    click_point(config, "bid_button")
    click_point(config, "bid_input_box")
    type_price(config, price)
    if bool(config.get("safety", {}).get("confirm_after_type", True)):
        click_point(config, "bid_confirm")
        click_point(config, "tool_confirm")


BidConfirmOutcome = Literal["bid_ok", "abstain", "verify_timeout", "unverified"]


def input_bid(
    config: dict[str, Any], price: int, *, config_path: Path | None = None
) -> BidConfirmOutcome:
    timing = config.get("timing", {}) or {}
    post_wait = float(timing.get("after_bid_confirm_wait_seconds", 1.0))

    if not bool(config.get("safety", {}).get("verify_bid_confirm_ocr", True)):
        _perform_bid_ui_sequence(config, price)
        sleep_interruptible(post_wait)
        return "unverified"

    max_sec = max(0.0, float(timing.get("bid_confirm_verify_max_seconds", 30.0)))
    retry_pause = max(0.0, float(timing.get("bid_confirm_retry_pause_seconds", 0.35)))
    capture_delay = max(0.0, float(timing.get("bid_confirm_capture_delay_seconds", 0.0)))
    deadline = time.monotonic() + max_sec
    attempt = 0

    while True:
        ensure_not_stopped()
        attempt += 1
        _perform_bid_ui_sequence(config, price)

        if capture_delay > 0:
            sleep_interruptible(capture_delay)

        bring_window_to_front(config)
        t_cap = time.perf_counter()
        frame, _info = capture_window_frame(config)
        perf_log_elapsed(f"bid_confirm_verify capture attempt={attempt}", t_cap)

        text, box = read_bid_confirm_region_text_from_frame(config, frame)
        status = classify_bid_confirm_status(text)

        if config_path is not None and box != (0, 0, 0, 0):
            dbg = config.get("debug", {}) or {}
            if bool(dbg.get("save_crops", True)) or bool(dbg.get("save_ocr_text", True)):
                runs_dir = ensure_output_dir(config, config_path)
                ts = time.strftime("%Y%m%d_%H%M%S")
                stem = f"{ts}_bid_confirm_try{attempt}"
                if bool(dbg.get("save_crops", True)):
                    frame.crop(box).save(runs_dir / f"{stem}.png")
                if bool(dbg.get("save_ocr_text", True)):
                    (runs_dir / f"{stem}.txt").write_text(text or "", encoding="utf-8")

        tight_preview = compact_text(text)[:160]
        log(f"bid_confirm OCR attempt {attempt}: status={status} text={tight_preview!r}", gui_verbose_only=True)

        if status == "bid_ok":
            sleep_interruptible(post_wait)
            return "bid_ok"
        if status == "abstain":
            log("bid_confirm: detected 弃权 (timeout/abstain); stop retrying", gui_verbose_only=True)
            sleep_interruptible(post_wait)
            return "abstain"

        if time.monotonic() >= deadline:
            log(f"bid_confirm: verify timeout after {attempt} attempt(s); never saw 已出价", gui_verbose_only=True)
            sleep_interruptible(post_wait)
            return "verify_timeout"

        log(f"bid_confirm: no 已出价 yet, retry after {retry_pause}s", gui_verbose_only=True)
        sleep_interruptible(retry_pause)


def exit_round_after_bid_confirm_verify_timeout(config: dict[str, Any]) -> None:
    """出价确认 OCR 超时（始终未见 已出价）后：ESC 关层并点通用确认，尽量退出本局/出价流程。"""
    log("bid_confirm: verify_timeout -> ESC + tool_confirm 退出该局", gui_verbose_only=True)
    press_escape(config)
    click_point(config, "tool_confirm")


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
    sleep_interruptible(float(config.get("timing", {}).get("click_pause_seconds", 0.12)))
    sleep_interruptible(2.0)
    park_mouse_if_configured(config)
    click_point(config, "post_continue_confirm")
    confirm_at = time.monotonic()
    log("map selection transition complete; waiting for round OCR", gui_verbose_only=True)
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
        "auto_sort_click": {"origin": "left_top", "x": 1601, "y": 1048},
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


def run_aisha_loop(config_path: Path) -> None:
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
    )


def handle_round(
    config: dict[str, Any],
    config_path: Path,
    round_no: int,
) -> None:
    ensure_not_stopped()
    timing_cfg = config.get("timing", {}) or {}
    # wait_for_round_bid_button_ready_ocr(config, round_no=int(round_no))
    if (round_no == 1):
        sleep_interruptible(float(timing_cfg.get("round1_extra_wait_seconds", 0.0) + float(timing_cfg.get("round_detect_wait_seconds", 0.0) or 0.0)))
    else:
        sleep_interruptible(float(timing_cfg.get("round_detect_wait_seconds", 0.0) or 0.0))
    tool_rounds = {int(item) for item in config.get("automation", {}).get("tool_rounds", [1, 2])}
    ran_tool_this_round = int(round_no) in tool_rounds
    
    if ran_tool_this_round:
        run_tool_sequence(config)
        log(f"after tool", gui_verbose_only=True)
        sleep_interruptible(5)
    else:
        log(f"round {round_no}: tool skipped by config", gui_verbose_only=True)

    price, details = compute_price(
        config,
        config_path=config_path,
        round_no=int(round_no),
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
    input_bid(config, price, config_path=config_path)


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
) -> None:
    # 与控制台同内容的运行日志；cwd 在脚本与 PyInstaller exe 下均为进程当前工作目录
    set_app_log_file(app_log_path or (Path.cwd() / "bidking_fresh_bot.log"))
    config = load_merged_bot_config(config_path)
    set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
    if clear_snapshot_on_start:
        clear_board_snapshot_file(config)
    if force_selected_mode:
        config.setdefault("automation", {})["selected_mode"] = str(force_selected_mode)
    apply_pyautogui_from_config(config)
    lv = refresh_poll_loop_locals(config)
    selected_map = lv["selected_map"]
    max_runs = lv["max_runs"]
    prepare_target_window(config, center=True)

    log("BidKing bot 已启动（交互层；出价由 pricing.compute_price 读快照计算）；按 F9 停止")
    log("mode: full-window OCR -> lobby/end/round handling", gui_verbose_only=True)

    handled_rounds: set[int] = set()
    cached_game_uid: str | None = None
    preflight_esc_before_next_map_select = True
    await_non_lobby_after_preflight_esc = False
    await_non_lobby_stuck_polls = 0
    pending_game_start_deadline: float | None = None
    map_select_no_start_streak = 0
    startup_warehouse_sort_done = False
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
            selected_map = lv["selected_map"]
            max_runs = lv["max_runs"]
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
            round_no = observation.round_no

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
                    f"loop {loop_index}: 新局 game_uid {cached_game_uid!r} -> {game_uid!r}；重置回合状态"
                )
                handled_rounds.clear()
            if game_uid is not None:
                cached_game_uid = game_uid

            log(
                f"loop {loop_index}: snap_round={snap_round} poll_round={observation.round_no} "
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
                last_end_at, confirm_at = handle_end_transition(
                    config,
                    handled_rounds,
                    last_end_at,
                    transition_debounce,
                    f"loop {loop_index}",
                )
                if confirm_at:
                    last_post_continue_confirm_at = confirm_at
                completed_runs += 1
                preflight_esc_before_next_map_select = True
                log(f"completed runs: {completed_runs}/{max_runs}")
                if completed_runs >= max_runs:
                    log("target runs reached; exit")
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
            handle_round(config, config_path, round_no)
            handled_rounds.add(round_no)

            if round_no >= 5:
                log("round 5 handled; waiting for end prompt or a new OCR state", gui_verbose_only=True)

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
            completed_runs += 1
            preflight_esc_before_next_map_select = True
            log(f"completed runs: {completed_runs}/{max_runs}")
            if completed_runs >= max_runs:
                log("target runs reached; exit")
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
        run_loop(config_path)
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
    run_aisha_loop(config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
