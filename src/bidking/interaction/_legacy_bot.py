#!/usr/bin/env python3
"""Fresh BidKing automation loop.

This script intentionally ignores the old auto-loop logic.  It follows the
user-provided flow exactly:
- Wait until central OCR sees a round number.
- Wait a fixed delay, use the leftmost tool, wait for animation.
- OCR central info, calculate a bid, input it, confirm.
- If OCR sees "对局结束", run the fixed post-round transition clicks.
"""

from __future__ import annotations

import random
import argparse
import json
import math
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyautogui
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent

from ._bid_history_parser import (  # noqa: E402
    coerce_valid_lobby_player_count,
    get_max_other_players_last_bid_from_image,
    read_multiplayer_layout_for_count,
    resolve_lobby_player_count_for_opponent_bid,
)
from ._central_info_parser import merge_patch, parse_central_info  # noqa: E402
from .window import capture_window_frame, find_window, scale_point  # noqa: E402
from ..logsys.app_log import append_app_log, log_timestamp, set_app_log_file  # noqa: E402
from ..logsys.perf_log import perf_log, perf_log_elapsed  # noqa: E402
from ..pricing.ahmad import compute_ahmad_premium_w, compute_value_anchor_ceiling_w  # noqa: E402
from ..pricing._constraint_solver import (  # noqa: E402
    as_non_neg_float,
    as_non_neg_int,
    get_color_constraint,
    normalize_role,
    validate_input,
)

ROUND_RULES = {
    1: {"multiplier": 2.0, "pace": 0.42, "label": "两倍出价第二直接获得"},
    2: {"multiplier": 1.6, "pace": 0.56, "label": "1.6 倍出价第二直接获得"},
    3: {"multiplier": 1.3, "pace": 0.77, "label": "1.3 倍出价第二直接获得"},
    4: {"multiplier": 1.1, "pace": 0.91, "label": "1.1 倍出价第二直接获得"},
    5: {"multiplier": 1.0, "pace": 1.00, "label": "价高者得"},
}

# 参考客户端 1920×1080：出价状态文案区（「已出价」/「弃权」等）
DEFAULT_BID_CONFIRM_REGION = {"left": 704, "top": 962, "width": 303, "height": 75}


def advisor_evaluate_for_bid(data: dict[str, Any]) -> dict[str, Any]:
    """供出价前复用 flat_solve 与 observed_low；仅服务 ahmad_premium 流程。"""
    from ..pricing.ahmad import COLORS_BPGR, solved_ahmad_flat_solve

    errors = validate_input(data)
    summary = {"observed_low_price": as_non_neg_float(data.get("observed_low_price"))}
    if errors:
        return {"errors": errors, "warns": [], "summary": summary}
    max_count = as_non_neg_int(data.get("max_count")) or 60
    avg_tolerance = as_non_neg_float(data.get("avg_tolerance")) or 0.05
    total_all = as_non_neg_int(data.get("total_all"))
    if total_all is None:
        return {"errors": ["缺少 total_all（总藏品数）"], "warns": [], "summary": summary}
    constraints = {color: get_color_constraint(data, color) for color in COLORS_BPGR}
    solved, warns = solved_ahmad_flat_solve(data, int(total_all), constraints, max_count, avg_tolerance)
    return {"errors": [], "warns": warns, "summary": summary, "solved": solved}

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
    parsed: dict[str, Any]


@dataclass
class Observation:
    capture: CaptureResult
    end_text: str  # poll: 整窗 OCR；round: 空串（不维护整窗文案）
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
    print(line, flush=True)
    append_app_log(line)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
        "selected_map": str(auto.get("selected_map") or auto.get("default_map", "4")),
        "max_runs": int(auto.get("selected_runs") or auto.get("default_runs", 1)),
        "game_start_timeout_seconds": float(auto.get("game_start_timeout_seconds", 60.0)),
    }


def apply_pyautogui_from_config(config: dict[str, Any]) -> None:
    safety = config.get("safety") or {}
    pyautogui.FAILSAFE = bool(safety.get("failsafe", True))
    pyautogui.PAUSE = float(safety.get("move_pause_seconds", 0.08))


def resolve_path(config_path: Path, raw_path: str | None, default_name: str) -> Path:
    if not raw_path:
        return config_path.parent / default_name
    path = Path(raw_path)
    if path.is_absolute():
        return path
    # runtime.json 位于 configs/ 时，勿把 "configs/pricing.json" 拼成 configs/configs/pricing.json
    parts = path.parts
    if parts and parts[0] == "configs" and config_path.parent.name == "configs":
        path = Path(*parts[1:]) if len(parts) > 1 else Path(default_name)
    return config_path.parent / path


def default_advisor_input() -> dict[str, Any]:
    return {
        "round": 1,
        "my_role": "ahmad",
        "total_all": None,
        "avg_grid_all": None,
        "count_green": None,
        "count_white": None,
        "min_count_green": 0,
        "min_count_white": 0,
        "max_count": 60,
        "max_show": 20,
        "avg_tolerance": 0.05,
        "grid_price_green": 0.0,
        "grid_price_white": 0.0,
        "grid_price_blue": 0.0,
        "grid_price_purple": 0.28,
        "grid_price_gold": 1.13,
        "grid_price_red": 4.77,
        "total_grid_rounding": "round",
        "constraints": {
            "blue": {"avg": None, "count": None, "grid": None, "min_count": None},
            "purple": {"avg": None, "count": None, "grid": None, "min_count": None},
            "gold": {"avg": None, "count": None, "grid": None, "min_count": None},
            "red": {"avg": None, "count": None, "grid": None, "min_count": None},
        },
        "category_weights": {f"cat{index}": 1 for index in range(1, 11)},
        "rank_signal": {
            "my_rank": 2,
            "players": 4,
            "pressure": 0.55,
            "suspected_bluff": 0.35,
        },
        "style": {
            "risk_bias": "balanced",
            "need_comeback": False,
        },
        "selected_mode": "ahmad_premium",
    }


def apply_price_config(data: dict[str, Any], price_config: dict[str, Any]) -> dict[str, Any]:
    grid_prices = price_config.get("grid_prices", {})
    for color in ("green", "white", "blue", "purple", "gold", "red"):
        if color in grid_prices:
            data[f"grid_price_{color}"] = float(grid_prices[color])
    if "avg_tolerance" in price_config:
        data["avg_tolerance"] = float(price_config["avg_tolerance"])
    if "category_weights" in price_config:
        data["category_weights"] = dict(price_config["category_weights"])
    if "burst_limit" in price_config:
        data["burst_limit"] = float(price_config["burst_limit"])
    if "round_rules" in price_config:
        data["round_rules"] = dict(price_config["round_rules"])
    return data


def build_advisor_input(config: dict[str, Any], text: str, round_no: int, price_config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    advisor = config.get("advisor", {})
    parsed = parse_central_info(text)
    data = default_advisor_input()
    data = apply_price_config(data, price_config)
    data["round"] = int(round_no)
    data["my_role"] = advisor.get("role", "ahmad")
    sel_mode = str(config.get("automation", {}).get("selected_mode", "ahmad_premium")).strip().lower()
    if sel_mode in ("normal", "express"):
        sel_mode = "ahmad_premium"
    data["selected_mode"] = sel_mode
    sm = config.get("automation", {}).get("selected_map")
    if sm is None:
        sm = config.get("automation", {}).get("default_map", "4")
    data["selected_map"] = str(sm)
    data["avg_grid_all"] = advisor.get("avg_grid_all")
    data["total_grid_rounding"] = advisor.get("total_grid_rounding", "round")
    green_count = advisor.get("green_count")
    white_count = advisor.get("white_count")
    data["count_green"] = None if green_count in (None, "") else int(green_count)
    data["count_white"] = None if white_count in (None, "") else int(white_count)
    merged = merge_patch(data, parsed)
    merged["round"] = int(round_no)
    return merged, parsed


def merge_parsed_memory(current: dict[str, Any] | None, new_patch: dict[str, Any]) -> dict[str, Any]:
    if not current:
        return json.loads(json.dumps(new_patch, ensure_ascii=False))

    merged = json.loads(json.dumps(current, ensure_ascii=False))
    current_round = current.get("round")
    new_round = new_patch.get("round")
    try:
        cr_i = int(current_round) if current_round is not None else None
        nr_i = int(new_round) if new_round is not None else None
    except (TypeError, ValueError):
        cr_i, nr_i = None, None
    # 新一局：中央轮次从 ≥2 回到 1（与主循环「round1 且曾处理过更高轮」一致）；清本场才出现的随机均价
    if cr_i is not None and nr_i == 1 and cr_i >= 2:
        merged.pop("random_pick_count", None)
        merged.pop("random_pick_avg_price", None)
    same_round = (
        current_round is not None and new_round is not None and int(current_round) == int(new_round)
    )
    sticky_scalar_fields = {
        "total_all",
        "total_grid_all",
        "wg_total",
        "count_green",
        "count_white",
        "avg_grid_all",
        # 竞拍中央信息里「随机选择 n 件平均价值」整场通常只出现一次；跨轮保留供 ahmad_premium random_avg 使用
        "random_pick_count",
        "random_pick_avg_price",
    }
    sticky_constraint_fields = {"count", "grid", "avg"}
    if not same_round:
        for key in list(merged.keys()):
            if key in ("constraints", "parsed_facts", "unparsed_lines", "round"):
                continue
            if key.startswith("avg_price_") or key.startswith("total_price_"):
                merged.pop(key, None)
                continue
            if key in {
                "observed_low_price",
                "mixed_type_count",
                "mixed_type_avg_grid_price",
            }:
                merged.pop(key, None)
    for key, value in new_patch.items():
        if key in ("parsed_facts", "unparsed_lines"):
            continue
        if key == "constraints":
            merged.setdefault("constraints", {})
            for color, fields in value.items():
                merged["constraints"].setdefault(color, {})
                for field, field_value in fields.items():
                    if field_value is not None and (same_round or field in sticky_constraint_fields):
                        merged["constraints"][color][field] = field_value
        else:
            if value is not None and (same_round or key in sticky_scalar_fields):
                merged[key] = value

    merged_facts = list(current.get("parsed_facts") or [])
    merged_facts.extend(new_patch.get("parsed_facts") or [])
    merged["parsed_facts"] = merged_facts

    merged_unparsed = list(current.get("unparsed_lines") or [])
    merged_unparsed.extend(new_patch.get("unparsed_lines") or [])
    merged["unparsed_lines"] = merged_unparsed
    return merged


def sanitize_parsed_patch_for_memory(parsed_patch: dict[str, Any], round_no: int | None) -> dict[str, Any]:
    patch = json.loads(json.dumps(parsed_patch or {}, ensure_ascii=False))
    if patch.get("round") is not None and round_no is not None and int(patch.get("round")) != int(round_no):
        return {"parsed_facts": [], "unparsed_lines": []}

    current_round = int(round_no) if round_no is not None else None
    if current_round is not None:
        patch["round"] = current_round
    return patch


def build_advisor_input_from_patch(config: dict[str, Any], parsed_patch: dict[str, Any], round_no: int, price_config: dict[str, Any]) -> dict[str, Any]:
    advisor = config.get("advisor", {})
    data = default_advisor_input()
    data = apply_price_config(data, price_config)
    data["round"] = int(round_no)
    data["my_role"] = advisor.get("role", "ahmad")
    sel_mode = str(config.get("automation", {}).get("selected_mode", "ahmad_premium")).strip().lower()
    if sel_mode in ("normal", "express"):
        sel_mode = "ahmad_premium"
    data["selected_mode"] = sel_mode
    sm = config.get("automation", {}).get("selected_map")
    if sm is None:
        sm = config.get("automation", {}).get("default_map", "4")
    data["selected_map"] = str(sm)
    data["avg_grid_all"] = advisor.get("avg_grid_all")
    data["total_grid_rounding"] = advisor.get("total_grid_rounding", "round")
    green_count = advisor.get("green_count")
    white_count = advisor.get("white_count")
    data["count_green"] = None if green_count in (None, "") else int(green_count)
    data["count_white"] = None if white_count in (None, "") else int(white_count)
    merged = merge_patch(data, parsed_patch)
    merged["round"] = int(round_no)
    return merged


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


def reset_capture_scan_session(sess: dict[str, Any] | None) -> None:
    """新对局/大厅等时机重置：最少价值缓存、对手价己方席位缓存。"""
    if sess is None:
        return
    sess.clear()
    sess["min_price_cached_points"] = None
    sess["min_price_central_trigger_count_prev"] = 0
    sess["opp_lobby_key"] = None
    sess["opp_self_slot"] = None


def _min_price_trigger_phrases(config: dict[str, Any]) -> list[str]:
    cap = config.get("capture", {}) or {}
    raw = cap.get("min_price_scan_trigger_phrases", ["随机显示"])
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return ["随机显示"]


def _count_min_price_triggers_in_central(central_text: str, phrases: list[str]) -> int:
    """统计各触发词在中央 OCR 文本中的出现次数之和（``str.count``，非重叠）。"""
    if not central_text or not phrases:
        return 0
    total = 0
    for p in phrases:
        if p:
            total += central_text.count(p)
    return total


def _opponent_price_only_rescan_enabled(config: dict[str, Any]) -> bool:
    cap = config.get("capture", {}) or {}
    raw = cap.get("opponent_bid_price_only_rescan_enabled")
    if raw is None:
        return True
    return bool(raw)


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


def read_min_price_text_from_frame(config: dict[str, Any], frame: Image.Image) -> tuple[str, tuple[int, int, int, int]]:
    """OCR `capture.min_price_region` on an already-captured client-area RGB image."""
    region = config.get("capture", {}).get("min_price_region")
    if not region:
        return "", (0, 0, 0, 0)
    box = scaled_region_box(region, config, frame.width, frame.height)
    crop = frame.crop(box)
    text = rapidocr_once(ImageOps.grayscale(crop).convert("RGB"))
    return text, box


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


def read_opponent_last_bid_from_frame(
    config: dict[str, Any],
    frame: Image.Image,
    *,
    round_no: int | None = None,
    lobby_player_count: int | None = None,
    config_path: Path | None = None,
    known_self_slot_index: int | None = None,
) -> tuple[int | None, int | None]:
    """按 ``capture.bid_history_multiplayer`` 与当前轮次 OCR 各席价格区，用角色名+称号排除己方后取最高价。

    ``lobby_player_count`` 若传入则须为 2/4/5；否则按 ``automation.maps[selected_map].player_count`` →
    ``advisor.lobby_player_count`` 解析。轮次 ``round_no`` 用于选取各席 ``rounds`` 中对应价格区键 ``"1"``…``"4"``；
    可与中央情报轮次不同（例如起手读 ``max(1, 当前轮-1)`` 列以取上一轮对手出价）。

    若 ``known_self_slot_index`` 有效，则跳过各席身份 OCR，只对 ``n-1`` 个对手价区 OCR（同轮复用）。

    若传入 ``config_path`` 且 ``debug.save_crops`` / ``debug.save_ocr_text`` 之一为真，将各席 OCR 裁剪与文本写入 ``runs``（见 parser 命名规则）。

    返回 ``(max_other_bid, self_slot_index)``；后者仅在完整身份识别成功或快速路径传入的已知席位时给出。
    """
    adv = config.get("advisor", {}) or {}
    capture = config.get("capture", {}) or {}
    if lobby_player_count is not None:
        lobby_count = coerce_valid_lobby_player_count(lobby_player_count)
        if lobby_count is None:
            return None, None
    else:
        lobby_count = resolve_lobby_player_count_for_opponent_bid(config)
        if lobby_count is None:
            return None, None
    players = read_multiplayer_layout_for_count(capture, lobby_count)
    if not players:
        return None, None
    ref = config.get("window", {}).get("reference_client_size", {}) or {}
    rw = max(1, int(ref.get("width") or 1920))
    rh = max(1, int(ref.get("height") or 1080))
    name = str(adv.get("character_name") or "艾哈迈德")
    raw_titles = adv.get("character_titles", adv.get("my_titles"))
    titles: list[str] | None = None
    if isinstance(raw_titles, str) and raw_titles.strip():
        titles = [raw_titles.strip()]
    elif isinstance(raw_titles, (list, tuple)):
        titles = [str(t).strip() for t in raw_titles if str(t).strip()]
    dbg = config.get("debug", {}) or {}
    save_crops = bool(dbg.get("save_crops", True))
    save_ocr = bool(dbg.get("save_ocr_text", True))
    runs_dir: Path | None = None
    if config_path is not None and (save_crops or save_ocr):
        runs_dir = ensure_output_dir(config, config_path)
    mp = get_max_other_players_last_bid_from_image(
        frame,
        lobby_player_count=lobby_count,
        current_round=round_no,
        players=players,
        my_character_name=name,
        my_titles=titles,
        reference_size=(rw, rh),
        ocr_fn=lambda im: rapidocr_once(ImageOps.grayscale(im).convert("RGB")),
        debug_runs_dir=runs_dir,
        debug_save_crops=save_crops,
        debug_save_ocr_text=save_ocr,
        known_self_slot_index=known_self_slot_index,
    )
    return mp.max_other_last_bid, mp.self_slot_index


def read_min_price_text(config: dict[str, Any], config_path: Path) -> tuple[str, tuple[int, int, int, int]]:
    """Bring game window forward, capture client, OCR lowest-price region."""
    t0 = time.perf_counter()
    bring_window_to_front(config)
    t_cap = time.perf_counter()
    frame, _info = capture_window_frame(config)
    perf_log_elapsed("read_min_price_text capture_window_frame", t_cap)
    text, box = read_min_price_text_from_frame(config, frame)
    runs_dir = ensure_output_dir(config, config_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if bool(config.get("debug", {}).get("save_crops", True)) and box != (0, 0, 0, 0):
        crop = frame.crop(box)
        crop.save(runs_dir / f"{timestamp}_min_price_region.png")
    if bool(config.get("debug", {}).get("save_ocr_text", True)) and text:
        (runs_dir / f"{timestamp}_min_price_region.txt").write_text(text, encoding="utf-8")
    perf_log_elapsed("read_min_price_text 总计(含 OCR)", t0)
    return text, box


def _observe_opponent_last_bid_block(
    config: dict[str, Any],
    config_path: Path,
    label: str,
    *,
    frame: Image.Image,
    bid_round_no: int | None,
    opponent_bid_lobby_count: int | None,
    scan_session: dict[str, Any] | None,
) -> int | None:
    """对手价网格 OCR；先于中央区完整解析与底价 OCR 调用。"""
    lobby_resolved: int | None = None
    if opponent_bid_lobby_count is not None:
        lobby_resolved = coerce_valid_lobby_player_count(opponent_bid_lobby_count)
    else:
        lobby_resolved = resolve_lobby_player_count_for_opponent_bid(config)
    known_self_slot: int | None = None
    if scan_session is not None and _opponent_price_only_rescan_enabled(config):
        lobby_key = int(lobby_resolved) if lobby_resolved is not None else 0
        prev_lobby = scan_session.get("opp_lobby_key")
        if prev_lobby is not None and prev_lobby != lobby_key:
            scan_session["opp_self_slot"] = None
        scan_session["opp_lobby_key"] = lobby_key
        known_self_slot = scan_session.get("opp_self_slot")
    t_opp = time.perf_counter()
    opponent_last_bid, slot_from_read = read_opponent_last_bid_from_frame(
        config,
        frame,
        round_no=bid_round_no,
        lobby_player_count=opponent_bid_lobby_count,
        config_path=config_path,
        known_self_slot_index=known_self_slot,
    )
    perf_log_elapsed(f"observe[{label}] read_opponent_last_bid_from_frame", t_opp)
    if scan_session is not None and slot_from_read is not None:
        scan_session["opp_self_slot"] = int(slot_from_read)
    return opponent_last_bid


def _observe_min_price_block(
    config: dict[str, Any],
    label: str,
    *,
    frame: Image.Image,
    runs_dir: Path,
    timestamp: str,
    central_text: str,
    scan_session: dict[str, Any] | None,
) -> str:
    """底价区 OCR；触发词统计使用 ``central_text``。"""
    min_price_text = ""
    min_price_box = (0, 0, 0, 0)
    t_minp = time.perf_counter()
    if scan_session is None:
        min_price_text, min_price_box = read_min_price_text_from_frame(config, frame)
        perf_log_elapsed(f"observe[{label}] read_min_price_text_from_frame", t_minp)
    else:
        phrases = _min_price_trigger_phrases(config)
        cur_trig = _count_min_price_triggers_in_central(central_text or "", phrases)
        prev_trig = int(scan_session.get("min_price_central_trigger_count_prev", 0) or 0)
        increased = cur_trig > prev_trig
        cached_pts = scan_session.get("min_price_cached_points")
        if increased:
            min_price_text, min_price_box = read_min_price_text_from_frame(config, frame)
            perf_log_elapsed(f"observe[{label}] read_min_price_text_from_frame", t_minp)
            pt = parse_min_price_ocr_to_int(min_price_text)
            if pt is not None:
                scan_session["min_price_cached_points"] = int(pt)
                scan_session["min_price_central_trigger_count_prev"] = cur_trig
        else:
            if cur_trig > 0 and cached_pts is not None:
                cp = int(cached_pts)
                if cp > 0:
                    min_price_text = str(cp)
                perf_log_elapsed(f"observe[{label}] min_price_use_cache", t_minp)
            else:
                perf_log_elapsed(f"observe[{label}] min_price_skip_no_scan", t_minp)
            if cur_trig == 0:
                scan_session["min_price_cached_points"] = None
            scan_session["min_price_central_trigger_count_prev"] = cur_trig
    if (
        min_price_text
        and min_price_box != (0, 0, 0, 0)
        and bool(config.get("debug", {}).get("save_crops", True))
    ):
        min_crop = frame.crop(min_price_box)
        min_crop.save(runs_dir / f"{timestamp}_{label}_min_price.png")
    if min_price_text and bool(config.get("debug", {}).get("save_ocr_text", True)):
        (runs_dir / f"{timestamp}_{label}_min_price.txt").write_text(min_price_text, encoding="utf-8")
    return min_price_text


def _observe_finalize_round(
    config: dict[str, Any],
    config_path: Path,
    label: str,
    *,
    t_obs: float,
    frame: Image.Image,
    runs_dir: Path,
    timestamp: str,
    image_path: Path | None,
    central_text: str,
    opponent_last_bid: int | None,
    scan_session: dict[str, Any] | None,
) -> tuple[Observation, str, int | None]:
    """回合内：中央区 OCR 之后解析情报与底价 OCR；``opponent_last_bid`` 由调用方在中央区 OCR 之前算好。返回 ``(Observation, min_price_text, opponent_last_bid)``。"""

    t_parse = time.perf_counter()
    capture = CaptureResult(text=central_text, image_path=image_path, parsed=parse_central_info(central_text))
    perf_log_elapsed(f"observe[{label}] parse_central_info", t_parse)
    round_no = parse_round_number(central_text)

    min_price_text = _observe_min_price_block(
        config,
        label,
        frame=frame,
        runs_dir=runs_dir,
        timestamp=timestamp,
        central_text=central_text,
        scan_session=scan_session,
    )

    perf_log_elapsed(f"observe[{label}] 总计", t_obs)
    return (
        Observation(
            capture=capture,
            end_text="",
            round_no=round_no,
            end_prompt=False,
            reward_continue=False,
            failed_auction_settlement=False,
            auction_lobby=False,
            home_bid_button=False,
            has_any_signal=False,
        ),
        min_price_text,
        opponent_last_bid,
    )


def _observe_finalize_poll(
    label: str,
    *,
    t_obs: float,
    image_path: Path | None,
    central_text: str,
    full_window_text: str,
    home_bid_text: str,
) -> Observation:
    """主循环轮询：整窗 + home 信号；``end_text`` 为整窗 OCR 串。"""
    t_parse = time.perf_counter()
    capture = CaptureResult(text=central_text, image_path=image_path, parsed=parse_central_info(central_text))
    perf_log_elapsed(f"observe[{label}] parse_central_info", t_parse)
    round_no = parse_round_number(central_text) or parse_round_number(full_window_text)
    parsed_facts = capture.parsed.get("parsed_facts") or []
    failed_settlement = has_failed_auction_settlement(full_window_text)

    any_signal = bool(
        parsed_facts
        or round_no is not None
        or has_end_prompt(full_window_text)
        or has_reward_continue(full_window_text)
        or failed_settlement
        or has_auction_lobby(full_window_text)
        or has_home_bid_button(home_bid_text)
    )
    perf_log_elapsed(f"observe[{label}] 总计", t_obs)
    return Observation(
        capture=capture,
        end_text=full_window_text,
        round_no=round_no,
        end_prompt=has_end_prompt(full_window_text),
        reward_continue=has_reward_continue(full_window_text),
        failed_auction_settlement=failed_settlement,
        auction_lobby=has_auction_lobby(full_window_text),
        home_bid_button=has_home_bid_button(home_bid_text),
        has_any_signal=any_signal,
    )


def observe_state_round(
    config: dict[str, Any],
    config_path: Path,
    label: str,
    *,
    opponent_bid_round_no: int | None = None,
    opponent_bid_lobby_count: int | None = None,
    scan_session: dict[str, Any] | None = None,
    auction_round_no: int | None = None,
) -> tuple[Observation, str, int | None]:
    """回合内：先对手价网格 OCR；再满足 ``timing.round_detect_wait_seconds``（首轮加 ``round1_extra_wait_seconds``）后再截屏做中央区与底价 OCR。不 OCR home、不保留整窗合并文案。"""
    t_obs = time.perf_counter()
    bring_window_to_front(config)
    t_cap = time.perf_counter()
    frame, _info = capture_window_frame(config)
    perf_log_elapsed(f"observe[{label}] capture_window_frame", t_cap)
    runs_dir = ensure_output_dir(config, config_path)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    image_path: Path | None = None
    if bool(config.get("debug", {}).get("save_crops", True)):
        image_path = runs_dir / f"{timestamp}_{label}_full_window.png"
        frame.save(image_path)

    timing_cfg = config.get("timing", {}) or {}
    target_pre_central = max(
        0.0,
        float(timing_cfg.get("round_detect_wait_seconds", 0.0) or 0.0)
        + (
            float(timing_cfg.get("round1_extra_wait_seconds", 0.0) or 0.0)
            if auction_round_no == 1
            else 0.0
        ),
    )
    t_pre_central_budget = time.perf_counter()
    bid_round_for_opponent = int(opponent_bid_round_no) if opponent_bid_round_no is not None else None
    opponent_last_bid = _observe_opponent_last_bid_block(
        config,
        config_path,
        label,
        frame=frame,
        bid_round_no=bid_round_for_opponent,
        opponent_bid_lobby_count=opponent_bid_lobby_count,
        scan_session=scan_session,
    )
    elapsed_toward_pre_central = time.perf_counter() - t_pre_central_budget
    remaining_pre_central = max(0.0, target_pre_central - elapsed_toward_pre_central)
    if remaining_pre_central > 0:
        t_pad = time.perf_counter()
        sleep_interruptible(remaining_pre_central)
        perf_log_elapsed(f"observe[{label}] round_detect_wait_pad", t_pad)
    frame, _info = capture_window_frame(config)
    central_region = config.get("capture", {}).get("central_info_region")
    t_ocr = time.perf_counter()

    if central_region:
        central_box = scaled_region_box(central_region, config, frame.width, frame.height)
        t_central = time.perf_counter()
        central_crop = frame.crop(central_box)
        central_text = rapidocr_once(ImageOps.grayscale(central_crop).convert("RGB"))
        if bool(config.get("debug", {}).get("save_crops", True)):
            central_crop.save(runs_dir / f"{timestamp}_{label}_central_info.png")
        if bool(config.get("debug", {}).get("save_ocr_text", True)):
            (runs_dir / f"{timestamp}_{label}_central_info.txt").write_text(central_text, encoding="utf-8")
        perf_log_elapsed(f"observe[{label}] OCR_central_region", t_central)
    else:
        central_text = rapidocr_once(ImageOps.grayscale(frame).convert("RGB"))
        perf_log_elapsed(f"observe[{label}] OCR_full_window_as_central_fallback", t_ocr)
        if bool(config.get("debug", {}).get("save_ocr_text", True)):
            (runs_dir / f"{timestamp}_{label}_full_window.txt").write_text(central_text, encoding="utf-8")
    perf_log_elapsed(f"observe[{label}] round_ocr_done", t_ocr)

    return _observe_finalize_round(
        config,
        config_path,
        label,
        t_obs=t_obs,
        frame=frame,
        runs_dir=runs_dir,
        timestamp=timestamp,
        image_path=image_path,
        central_text=central_text,
        opponent_last_bid=opponent_last_bid,
        scan_session=scan_session,
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

    central_text = full_window_text
    return _observe_finalize_poll(
        label,
        t_obs=t_obs,
        image_path=image_path,
        central_text=central_text,
        full_window_text=full_window_text,
        home_bid_text=home_bid_text,
    )


def apply_observation_memory(observation: Observation, knowledge_patch: dict[str, Any] | None) -> dict[str, Any] | None:
    parsed = sanitize_parsed_patch_for_memory(observation.capture.parsed or {}, observation.round_no)
    facts = parsed.get("parsed_facts") or []
    if not facts:
        return knowledge_patch
    return merge_parsed_memory(knowledge_patch, parsed)


def save_round_debug_bundle(
    config: dict[str, Any],
    config_path: Path,
    *,
    round_no: int,
    raw_text: str,
    knowledge_patch: dict[str, Any] | None,
    advisor_input: dict[str, Any],
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
    (prefix.with_suffix(".knowledge.json")).write_text(
        json.dumps(knowledge_patch or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (prefix.with_suffix(".advisor_input.json")).write_text(
        json.dumps(advisor_input, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload = {
        "final_price": final_price,
        "details": details,
    }
    (prefix.with_suffix(".result.json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def persist_last_submitted_price(
    config_path: Path,
    price: int | None,
    runtime_config: dict[str, Any] | None = None,
) -> None:
    normalized_price = None if price is None else int(price)
    if runtime_config is not None:
        runtime_config.setdefault("pricing", {})
        runtime_config["pricing"]["last_submitted_price"] = normalized_price
    try:
        config = load_json(config_path)
    except Exception:
        return
    config.setdefault("pricing", {})
    config["pricing"]["last_submitted_price"] = normalized_price
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


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
    for index in range(repeat):
        ensure_not_stopped()
        log(f"click {name} #{index + 1}: screen={x},{y}", gui_verbose_only=True)
        if not dry_run:
            pyautogui.click(x, y)
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
        pyautogui.click(int(x), int(y))
    sleep_interruptible(pause_value)


def loot_overlay_in_bidding_poll_snapshot(observation: Observation, round_no: int | None) -> bool:
    """主循环里 ``observed round=N … end=False lobby=False … any=True`` 一类状态：有轮次、在拍、无其它弹层。"""
    if round_no is None or not observation.has_any_signal:
        return False
    return not (
        observation.end_prompt
        or observation.auction_lobby
        or observation.reward_continue
        or observation.failed_auction_settlement
        or observation.home_bid_button
    )


def click_loot_overlay_dismiss_if_enabled(config: dict[str, Any]) -> None:
    """关闭右侧战利品半透明遮罩：``handle_round`` 开头与主轮询（见 ``loot_overlay_dismiss.poll_*``）均可调用。

    ``click_screen`` 与 ``clicks`` 相同：以 ``window.reference_client_size`` 为基准的客户区逻辑坐标，
    经 ``client_to_screen`` 缩放并加上客户区在屏幕上的原点；不是 ``stuck_after_handled_round`` 那种裸屏幕像素。
    """
    section = config.get("safety", {}).get("loot_overlay_dismiss", {})
    if not bool(section.get("enabled", False)):
        return
    cx, cy = _screen_click_pair_from_config(section.get("click_screen"), (1264, 171))
    sx, sy = client_to_screen(config, {"x": cx, "y": cy})
    log(f"loot_overlay_dismiss: round-start ref_client=({cx},{cy}) -> screen=({sx},{sy})", gui_verbose_only=True)
    click_absolute_screen(config, sx, sy, "loot_overlay_dismiss")
    sleep_interruptible(float(section.get("after_dismiss_pause_seconds", 0.35)))
    park_mouse_if_configured(config)


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
        pyautogui.moveTo(x, y, duration=0.05)
    except Exception as exc:
        log(f"warn: park mouse skipped: {exc}")


def press_escape(config: dict[str, Any]) -> None:
    ensure_not_stopped()
    bring_window_to_front(config)
    dry_run = bool(config.get("safety", {}).get("dry_run", False))
    log("press key: esc", gui_verbose_only=True)
    if not dry_run:
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
    pyautogui.hotkey("ctrl", "a")
    sleep_interruptible(pause)
    ensure_not_stopped()
    pyautogui.write(str(price), interval=0.02)
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
        pyautogui.click(sx, sy)
    sleep_interruptible(float(config.get("timing", {}).get("click_pause_seconds", 0.12)))
    sleep_interruptible(2.0)
    park_mouse_if_configured(config)
    click_point(config, "post_continue_confirm")
    confirm_at = time.monotonic()
    log("map selection transition complete; waiting for round OCR", gui_verbose_only=True)
    return confirm_at


def choose_rounding(value: float, rounding: str) -> int:
    if rounding == "ceil_int":
        return int(math.ceil(value))
    if rounding == "round_int":
        return int(round(value))
    return int(math.floor(value))


def parse_float_config(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def parse_int_config(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def apply_observed_low_price_floor(result: dict[str, Any], price: int, rounding: str) -> tuple[int, str | None]:
    summary = (result or {}).get("summary") or {}
    observed_low_price = summary.get("observed_low_price")
    if observed_low_price is None:
        return int(price), None
    try:
        observed_low_price = float(observed_low_price)
    except Exception:
        return int(price), None
    if observed_low_price <= 0:
        return int(price), None
    if observed_low_price > float(price):
        raised = choose_rounding(observed_low_price * 1.25, rounding)
        return int(max(price, raised)), f"observed_low_price={observed_low_price:.0f} -> raised={raised}"
    return int(price), None


def choose_bid_value_by_mode(config: dict[str, Any], result: dict[str, Any]) -> tuple[float | None, str]:
    selected_risk = str(config.get("automation", {}).get("selected_risk", "均衡")).strip()
    summary = (result or {}).get("summary") or {}
    custom_factor = parse_float_config(config.get("automation", {}).get("custom_risk_factor"), 0.0)
    if selected_risk in ("保守", "conservative", "floor_price"):
        return summary.get("floor_price"), "保守=floor_price"
    if selected_risk in ("激进", "aggressive", "avg_price_plus_25"):
        avg_price = summary.get("avg_price")
        return (float(avg_price) * 1.25 if avg_price is not None else None), "激进=avg_price*1.25"
    if selected_risk in ("自定义", "custom", "custom_factor"):
        avg_price = summary.get("avg_price")
        return (float(avg_price) * (1.0 + custom_factor) if avg_price is not None else None), f"自定义=avg_price*(1+{custom_factor:.4f})"
    return summary.get("avg_price"), "均衡=avg_price"


def apply_bid_cap(config: dict[str, Any], final_price: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    automation = config.get("automation", {})
    bid_cap = max(0, parse_int_config(automation.get("bid_cap_price"), 0))
    if bid_cap <= 0:
        payload["bid_cap"] = {"enabled": False, "cap_price": 0, "applied": False}
        return int(final_price), payload
    capped = min(int(final_price), bid_cap)
    payload["bid_cap"] = {
        "enabled": True,
        "cap_price": bid_cap,
        "applied": capped != int(final_price),
        "original_price": int(final_price),
    }
    return int(capped), payload


def apply_safe_guard(config: dict[str, Any], final_price: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    automation = config.get("automation", {})
    safe_enabled = bool(automation.get("safe_guard_enabled", False))
    safe_limit = max(0.0, parse_float_config(automation.get("safe_guard_max_increase_ratio"), 0.0))
    previous_price = config.get("pricing", {}).get("last_submitted_price")
    if not safe_enabled:
        payload["safe_guard"] = {"enabled": False, "triggered": False}
        return int(final_price), payload
    try:
        previous = int(previous_price) if previous_price not in (None, "") else None
    except Exception:
        previous = None
    if previous is None or previous <= 0:
        payload["safe_guard"] = {"enabled": True, "triggered": False, "previous_price": previous}
        return int(final_price), payload
    limit_price = int(math.floor(previous * (1.0 + safe_limit)))
    triggered = final_price > limit_price
    payload["safe_guard"] = {
        "enabled": True,
        "triggered": triggered,
        "previous_price": previous,
        "limit_price": limit_price,
        "safe_limit_ratio": safe_limit,
    }
    if triggered:
        payload["skip_submit"] = True
        payload["reason"] = (
            f"safe_guard blocked: {final_price} > {limit_price} "
            f"(previous={previous}, ratio={safe_limit:.4f})"
        )
        return int(final_price), payload
    return int(final_price), payload


def resolve_round_multiplier(round_no: int, price_config: dict[str, Any]) -> float:
    r = max(1, min(5, int(round_no)))
    rr = price_config.get("round_rules") or {}
    item = rr.get(str(r))
    if isinstance(item, dict) and item.get("multiplier") is not None:
        return float(item["multiplier"])
    return float(ROUND_RULES.get(r, ROUND_RULES[5])["multiplier"])


def apply_opponent_bid_adjustment(
    config: dict[str, Any],
    bid: int,
    round_no: int,
    o_prev: int | None,
    price_config: dict[str, Any],
    min_price_points: int | None = None,
) -> tuple[int, str | None]:
    au = config.get("automation", {})
    omin = max(0, parse_int_config(au.get("opponent_bid_min"), 20000))
    omax = max(0, parse_int_config(au.get("opponent_bid_max"), 300000))
    sticky = parse_int_config(au.get("opponent_bid_sticky_ratio"), 0.1)
    if int(round_no) < 2 or o_prev is None:
        return int(bid), None

    if o_prev < omin or o_prev > omax:
        return int(bid), None
    k_inc = parse_float_config(au.get("opponent_bid_k_increment"), 1.02)
    mult = resolve_round_multiplier(round_no, price_config)
    bid_f = float(bid)
    adj = int(math.floor(float(o_prev) * k_inc * mult + 1000))
    mp = as_non_neg_int(min_price_points)
    bid_s =int(bid_f * (1 + sticky) + random.randint(500, 1500))
    if round_no >= 2:
        if bid_f > adj:
            if round_no <= 3:
                if mp is not None and mp > adj:
                    return int(bid), None
                return min(int(bid), adj), "opp_low"
            return max(int((bid + adj)/2), adj), "opp_avg" 
    if round_no >= 5:
        return max(bid_s, int(o_prev *1.1 + random.randint(500, 1500))), "opp_final"
    if round_no == 3:
        return max(bid_s, int(o_prev * k_inc *(1 + sticky) + random.randint(500, 1500))), "opp_sticky"
    if bid_f > float(o_prev):
        return int(bid)+ random.randint(500, 1500), "opp_random"
    return max(bid_s, int(o_prev * k_inc * 1/mult * 1.1 *(1 + sticky) + random.randint(500, 1500))), "opp_sticky"


def compute_value_anchor_ceiling_points(
    advisor_input: dict[str, Any],
    price_config: dict[str, Any],
    min_price_points: int | None,
    price_multiplier: int,
    rounding: str,
    *,
    local_solved: dict[str, Any] | None = None,
) -> tuple[int | None, dict[str, Any]]:
    ceiling_w = compute_value_anchor_ceiling_w(
        advisor_input, price_config, min_price_points=min_price_points, local_solved=local_solved
    )
    if ceiling_w is None or ceiling_w <= 0:
        return None, {"reason": "no_ceiling_computed"}
    ceiling_pts = choose_rounding(float(ceiling_w) * float(price_multiplier), rounding)
    ceiling_pts = max(1, int(ceiling_pts))
    return ceiling_pts, {"ceiling_w": ceiling_w, "ceiling_points": ceiling_pts}


def apply_price_post_processing(
    config: dict[str, Any],
    advisor_input: dict[str, Any],
    price_config: dict[str, Any],
    round_no: int,
    min_price_points: int | None,
    opponent_last_bid: int | None,
    final_price: int,
    payload: dict[str, Any],
    *,
    price_multiplier: int,
    rounding: str,
    value_anchor_local_solved: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    t_post = time.perf_counter()
    fin = int(final_price)
    fin_before_opp = fin
    t_va = time.perf_counter()
    ceiling_pts, va_meta = compute_value_anchor_ceiling_points(
        advisor_input,
        price_config,
        min_price_points,
        price_multiplier,
        rounding,
        local_solved=value_anchor_local_solved,
    )
    perf_log_elapsed("post.compute_value_anchor_ceiling_points", t_va)

    if not payload.get("fallback"):
        fin_before_opp = fin
        fin, opp_tag = apply_opponent_bid_adjustment(
            config,
            fin,
            int(round_no),
            opponent_last_bid,
            price_config,
            min_price_points=min_price_points,
        )
        if opp_tag:
            payload["opponent_bid"] = {"applied": True, "tag": opp_tag, "before": fin_before_opp, "after": fin, "o_prev": opponent_last_bid,"ceiling_pts": ceiling_pts}
        else:
            payload["opponent_bid"] = {"applied": False, "o_prev": opponent_last_bid, "ceiling_pts": ceiling_pts}
    else:
        payload["opponent_bid"] = {"applied": False, "skipped": "fallback"}
    fin, payload = apply_ceiling_points(fin, fin_before_opp, ceiling_pts, payload, int(round_no))
    fin, payload = apply_bid_cap(config, fin, payload)
    fin, payload = apply_safe_guard(config, fin, payload)  
    perf_log_elapsed("post.apply_price_post_processing 总计", t_post)
    return fin, payload

def apply_ceiling_points(fin: int, fin_before_opp: int, ceiling_pts: int | None, payload: dict[str, Any], round_no: int) -> tuple[int, dict[str, Any]]:
    if ceiling_pts is None:
        return int(fin), payload
    if round_no >= 5 and fin <= ceiling_pts * 1.2:
        return int(fin), payload
    if round_no >= 3 and fin <= ceiling_pts * 1.1:
        return int(fin), payload
    return int(fin_before_opp), payload

def parse_min_price_ocr_to_int(min_price_text: str) -> int | None:
    """从 min_price_region OCR（界面「当前预估最低价格」等）解析最少价值整数（如「7,140」→ 7140）。"""
    if not (min_price_text or "").strip():
        return None
    best: int | None = None
    for m in re.finditer(r"[\d,]+", min_price_text):
        chunk = m.group(0).replace(",", "")
        if chunk.isdigit():
            v = int(chunk)
            if v > 0 and (best is None or v > best):
                best = v
    return best


def compute_bid_price(
    config: dict[str, Any],
    parsed_patch: dict[str, Any],
    round_no: int,
    price_config: dict[str, Any],
    *,
    min_price_ocr_text: str = "",
    opponent_last_bid: int | None = None,
) -> tuple[int, dict[str, Any]]:
    pricing = config.get("pricing", {})
    fallback = parse_int_config(pricing.get("fallback_bid_price"), 22223)
    min_facts = int(pricing.get("min_useful_facts", 1))
    multiplier = int(pricing.get("computed_price_multiplier", 10000))
    rounding = str(pricing.get("rounding", "floor_int"))
    mode = str(config.get("automation", {}).get("selected_mode", "ahmad_premium")).strip().lower()
    if mode in ("normal", "express"):
        mode = "ahmad_premium"
    t_bid = time.perf_counter()
    ocr_floor_reason: str | None = None
    low_price_reason: str | None = None
    price = 0
    value = 0.0
    source_reason = ""

    parsed = parsed_patch
    t0 = time.perf_counter()
    advisor_input = build_advisor_input_from_patch(config, parsed_patch, round_no, price_config)
    perf_log_elapsed(f"bid_price.build_advisor_input mode={mode}", t0)
    facts = parsed.get("parsed_facts") or []
    payload: dict[str, Any] = {
        "fallback": False,
        "reason": "",
        "facts": len(facts),
        "parsed": parsed,
        "advisor_input": advisor_input,
        "result": {},
        "source_value": None,
    }
    mp_common = parse_min_price_ocr_to_int(min_price_ocr_text)
    va_reuse_solved: dict[str, Any] | None = None

    def _return_with_post(final: int) -> tuple[int, dict[str, Any]]:
        out, pl = apply_price_post_processing(
            config,
            advisor_input,
            price_config,
            int(round_no),
            mp_common,
            opponent_last_bid,
            int(final),
            payload,
            price_multiplier=multiplier,
            rounding=rounding,
            value_anchor_local_solved=va_reuse_solved,
        )
        va = pl.get("value_anchor") or {}
        if va.get("applied"):
            pl["reason"] = (pl.get("reason") or "") + f"; value_anchor_cap={va.get('ceiling_points')}"
        ob = pl.get("opponent_bid") or {}
        if ob.get("applied"):
            pl["reason"] = (pl.get("reason") or "") + f"; opponent_bid={ob.get('tag')}"
        return out, pl

    if mode == "aisha_premium":
        payload["fallback"] = True
        payload["reason"] = "aisha_premium 请使用 fresh_aisha_bot.py（画板快照专用入口）"
        return _return_with_post(fallback)

    if len(facts) < min_facts:
        payload["fallback"] = True
        payload["reason"] = f"not enough parsed facts: {len(facts)}"
        return _return_with_post(fallback)

    t_ev = time.perf_counter()
    result = advisor_evaluate_for_bid(advisor_input)
    perf_log_elapsed(f"bid_price.evaluate mode={mode}", t_ev)
    payload["result"] = result
    errors = result.get("errors") or []

    use_ahmad_premium = mode == "ahmad_premium" and normalize_role(advisor_input.get("my_role", "ahmad")) in (
        "ahmad",
        "none",
    )
    if errors and not use_ahmad_premium:
        payload["fallback"] = True
        payload["reason"] = "; ".join(str(item) for item in errors)
        return _return_with_post(fallback)

    if use_ahmad_premium:
        ocr_min_for_ap = mp_common
        va_reuse_solved = result.get("solved")
        t_ap = time.perf_counter()
        value_w, source_reason, _ap_sig, ap_msgs, _base_w = compute_ahmad_premium_w(
            advisor_input,
            price_config,
            min_price_points=ocr_min_for_ap,
            local_solved=va_reuse_solved if isinstance(va_reuse_solved, dict) else None,
        )
        perf_log_elapsed("bid_price.compute_ahmad_premium_w", t_ap)
        if value_w is None:
            payload["fallback"] = True
            payload["reason"] = f"ahmad_premium: {source_reason}; " + "; ".join(str(x) for x in ap_msgs)
            return _return_with_post(fallback)
        value = float(value_w)
        payload["source_value"] = value
        if ap_msgs:
            source_reason += f" [advisor校验: {'; '.join(ap_msgs)}]"
        if value <= 0:
            payload["fallback"] = True
            payload["reason"] = f"non-positive source value: {value}"
            return _return_with_post(fallback)
        price = choose_rounding(value * multiplier, rounding)
        if price <= 0:
            payload["fallback"] = True
            payload["reason"] = f"non-positive final price: {price}"
            return _return_with_post(fallback)
        final_price, low_price_reason = apply_observed_low_price_floor(result, price, rounding)
    else:
        t_nb = time.perf_counter()
        value, source_reason = choose_bid_value_by_mode(config, result)
        perf_log_elapsed("bid_price.choose_bid_value_by_mode", t_nb)
        if value is None:
            payload["fallback"] = True
            payload["reason"] = f"missing bid value: {source_reason}"
            return _return_with_post(fallback)
        value = float(value)
        payload["source_value"] = value
        if value <= 0:
            payload["fallback"] = True
            payload["reason"] = f"non-positive source value: {value}"
            return _return_with_post(fallback)
        price = choose_rounding(value * multiplier, rounding)
        if price <= 0:
            payload["fallback"] = True
            payload["reason"] = f"non-positive final price: {price}"
            return _return_with_post(fallback)
        final_price, low_price_reason = apply_observed_low_price_floor(result, price, rounding)

    if low_price_reason:
        payload["reason"] = (
            f"{source_reason}: {value:.4f}w * {multiplier} -> input={price}; {low_price_reason}; pre_post={final_price}"
        )
    else:
        payload["reason"] = f"{source_reason}: {value:.4f}w * {multiplier} -> pre_post={final_price}"
    if ocr_floor_reason:
        payload["reason"] += f"; {ocr_floor_reason}"
    
    final_price, payload = _return_with_post(int(final_price))
    bid_cap_info = payload.get("bid_cap") or {}
    if bid_cap_info.get("applied"):
        payload["reason"] += f"; bid_cap={bid_cap_info.get('cap_price')}"
    perf_log_elapsed("bid_price.compute_bid_price 本轮总计(成功路径)", t_bid)
    return int(final_price), payload

def handle_round(
    config: dict[str, Any],
    config_path: Path,
    price_config: dict[str, Any],
    round_no: int,
    knowledge_patch: dict[str, Any] | None,
    scan_session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ensure_not_stopped()
    click_loot_overlay_dismiss_if_enabled(config)
    tool_rounds = {int(item) for item in config.get("automation", {}).get("tool_rounds", [1, 2])}
    ran_tool_this_round = int(round_no) in tool_rounds
    seconds = float(config.get("timing", {}).get("tool_after_wait_seconds", 5.0))
    if ran_tool_this_round:
        run_tool_sequence(config)
        log(f"after tool: wait {seconds:g}s", gui_verbose_only=True)
        if seconds > 0:
            sleep_interruptible(seconds)
    else:
        log(f"round {round_no}: tool skipped by config", gui_verbose_only=True)
    # Bid-history grid: the current round's column is often still empty right after
    # round start; read the previous round's column for opponent_last_bid (round 1 -> col "1").
    opponent_bid_grid_round = max(1, int(round_no) - 1)
    observation, min_price_text, opponent_last_bid = observe_state_round(
        config,
        config_path,
        f"round{round_no}_after_tool",
        opponent_bid_round_no=opponent_bid_grid_round,
        scan_session=scan_session,
        auction_round_no=int(round_no),
    )
    knowledge_patch = apply_observation_memory(observation, knowledge_patch)
    effective_patch = knowledge_patch or observation.capture.parsed
    price, details = compute_bid_price(
        config,
        effective_patch,
        round_no,
        price_config,
        min_price_ocr_text=min_price_text,
        opponent_last_bid=opponent_last_bid,
    )
    summary = (details.get("result") or {}).get("summary") or {}
    advisor_input = details.get("advisor_input") or build_advisor_input_from_patch(config, effective_patch, round_no, price_config)
    if details.get("fallback"):
        log(f"price fallback: {price}; reason={details.get('reason')}")
    else:
        log(
            "price computed: "
            f"{price}; {details.get('reason')}; "
            f"facts={details.get('facts')} combo={summary.get('combo_count')}"
        )
    log(
        "opponent_bid: "
        + json.dumps(
            {
                "opponent_bid": details.get("opponent_bid"),
            },
            ensure_ascii=False,
        )
    )
    if bool(config.get("debug", {}).get("print_ocr_snippet", False)):
        log("ocr snippet: " + compact_text(observation.capture.text)[:160])
    if bool(config.get("debug", {}).get("print_round_debug", True)):
        # log(f"debug advisor input keys: {sorted(advisor_input.keys())}")
        log(f"debug parsed facts: {len((effective_patch or {}).get('parsed_facts') or [])}")
    save_round_debug_bundle(
        config,
        config_path,
        round_no=round_no,
        raw_text=observation.capture.text,
        knowledge_patch=effective_patch,
        advisor_input=advisor_input,
        details=details,
        final_price=price,
    )
    if details.get("skip_submit"):
        log(f"bid skipped: {details.get('reason')}")
        return knowledge_patch
    input_bid(config, price, config_path=config_path)
    persist_last_submitted_price(config_path, price, config)
    return knowledge_patch


def load_price_config(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    price_path = resolve_path(config_path, config.get("advisor", {}).get("price_config_path"), "price_config.json")
    if not price_path.exists():
        log(f"warn: price config not found, using defaults: {price_path}")
        return {}
    return load_json(price_path)


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


def run_loop(config_path: Path) -> None:
    # 与控制台同内容的运行日志；cwd 在脚本与 PyInstaller exe 下均为进程当前工作目录
    set_app_log_file(Path.cwd() / "bidking_fresh_bot.log")
    config = load_json(config_path)
    set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
    persist_last_submitted_price(config_path, None, config)
    apply_pyautogui_from_config(config)
    lv = refresh_poll_loop_locals(config)
    selected_map = lv["selected_map"]
    max_runs = lv["max_runs"]
    prepare_target_window(config, center=True)

    log("fresh bot started（按 F9 停止）")
    log("mode: full-window OCR -> lobby/end/round handling", gui_verbose_only=True)

    handled_rounds: set[int] = set()
    knowledge_patch: dict[str, Any] | None = None
    scan_session: dict[str, Any] = {
        "min_price_cached_points": None,
        "min_price_central_trigger_count_prev": 0,
        "opp_lobby_key": None,
        "opp_self_slot": None,
    }
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
    last_loot_poll_overlay_dismiss_at = 0.0

    while True:
        loop_index += 1
        try:
            ensure_not_stopped()
            # 与 GUI 写入的 config.json / price_config.json 同步，便于不停止脚本时调整参数
            config = load_json(config_path)
            set_gui_log_verbose(bool((config.get("debug") or {}).get("gui_verbose", False)))
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
            price_config = load_price_config(config, config_path)
            observation = observe_state_poll(config, config_path, "poll")
            knowledge_patch = apply_observation_memory(observation, knowledge_patch)
            round_no = observation.round_no
            log(
                f"loop {loop_index}: observed round={round_no} "
                f"end={observation.end_prompt} lobby={observation.auction_lobby} "
                f"reward_continue={observation.reward_continue} "
                f"failed_auction={observation.failed_auction_settlement} "
                f"home_bid={observation.home_bid_button} any={observation.has_any_signal}",
                gui_verbose_only=True,
            )
            loot_poll = config.get("safety", {}).get("loot_overlay_dismiss", {}) or {}
            if (
                bool(loot_poll.get("enabled", False))
                and bool(loot_poll.get("poll_dismiss_enabled", True))
                and loot_overlay_in_bidding_poll_snapshot(observation, round_no)
            ):
                poll_min = max(0.0, float(loot_poll.get("poll_dismiss_min_seconds", 2.5)))
                if time.monotonic() - last_loot_poll_overlay_dismiss_at >= poll_min:
                    click_loot_overlay_dismiss_if_enabled(config)
                    last_loot_poll_overlay_dismiss_at = time.monotonic()

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
                knowledge_patch = None
                reset_capture_scan_session(scan_session)
                persist_last_submitted_price(config_path, None, config)
                log(f"completed runs: {completed_runs}/{max_runs}")
                if completed_runs >= max_runs:
                    log("target runs reached; exit")
                    return
                sleep_interruptible(poll_seconds)
                continue

            if observation.reward_continue:
                if time.monotonic() - last_reward_continue_at >= reward_continue_debounce:
                    run_reward_continue_transition(config)
                    knowledge_patch = None
                    reset_capture_scan_session(scan_session)
                    last_reward_continue_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: reward continue ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.failed_auction_settlement:
                if time.monotonic() - last_failed_auction_at >= transition_debounce:
                    run_failed_auction_settlement_transition(config)
                    knowledge_patch = None
                    reset_capture_scan_session(scan_session)
                    handled_rounds.clear()
                    persist_last_submitted_price(config_path, None, config)
                    last_failed_auction_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: failed auction settlement ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.auction_lobby:
                if time.monotonic() - last_lobby_at >= transition_debounce:
                    confirm_at = run_map_selection_transition(config, selected_map)
                    if confirm_at:
                        last_post_continue_confirm_at = confirm_at
                    handled_rounds.clear()
                    knowledge_patch = None
                    reset_capture_scan_session(scan_session)
                    persist_last_submitted_price(config_path, None, config)
                    last_lobby_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: auction lobby ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if observation.home_bid_button:
                if time.monotonic() - last_home_bid_at >= transition_debounce:
                    run_home_bid_button_transition(config)
                    knowledge_patch = None
                    reset_capture_scan_session(scan_session)
                    persist_last_submitted_price(config_path, None, config)
                    last_home_bid_at = time.monotonic()
                else:
                    log(f"loop {loop_index}: home bid button ignored by debounce", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if round_no is None:
                log(f"loop {loop_index}: no round detected; waiting", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            if round_no == 1 and any(value > 1 for value in handled_rounds):
                log("new auction inferred from round 1; reset handled rounds")
                handled_rounds.clear()
                knowledge_patch = apply_observation_memory(observation, None)
                reset_capture_scan_session(scan_session)
                persist_last_submitted_price(config_path, None, config)

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
                    knowledge_patch = None
                    reset_capture_scan_session(scan_session)
                    persist_last_submitted_price(config_path, None, config)
                    sleep_interruptible(poll_seconds)
                    continue
                log(f"loop {loop_index}: round {round_no} already handled; waiting", gui_verbose_only=True)
                sleep_interruptible(poll_seconds)
                continue

            log(f"loop {loop_index}: round {round_no} detected", gui_verbose_only=True)
            knowledge_patch = handle_round(
                config, config_path, price_config, round_no, knowledge_patch, scan_session
            )
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
            knowledge_patch = None
            reset_capture_scan_session(scan_session)
            persist_last_submitted_price(config_path, None, config)
            log(f"completed runs: {completed_runs}/{max_runs}")
            if completed_runs >= max_runs:
                log("target runs reached; exit")
                return
            sleep_interruptible(poll_seconds)
        except Exception as exc:
            log(f"error: {type(exc).__name__}: {exc}")
            sleep_interruptible(max(1.0, poll_seconds))


def print_click_positions(config_path: Path) -> None:
    config = load_json(config_path)
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
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--print-clicks", action="store_true", help="Print converted screen click positions and exit.")
    parser.add_argument(
        "--ocr-min-price",
        action="store_true",
        help="OCR capture.min_price_region from the game window and print JSON, then exit.",
    )
    parser.add_argument(
        "--ocr-min-price-image",
        default="",
        metavar="PATH",
        help="With --ocr-min-price, read this image file instead of live capture (1920x1080 client screenshot).",
    )
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    if args.print_clicks:
        print_click_positions(config_path)
        return 0
    if args.ocr_min_price:
        config = load_json(config_path)
        if args.ocr_min_price_image:
            frame = Image.open(Path(args.ocr_min_price_image)).convert("RGB")
            text, box = read_min_price_text_from_frame(config, frame)
        else:
            text, box = read_min_price_text(config, config_path)
        print(
            json.dumps(
                {"crop_box": list(box), "text": text, "repr": repr(text)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    else:
        config = load_json(config_path)
        maps = config.get("automation", {}).get("maps", {})
        default_map = str(config.get("automation", {}).get("default_map", "4"))
        default_runs = int(config.get("automation", {}).get("default_runs", 1))
        print("请选择地图：")
        for key in ("1", "2", "3", "4", "5", "6", "7"):
            item = maps.get(key, {})
            print(f"{key}. {item.get('name', key)}")
        map_input = input(f"地图编号 [默认 {default_map}]: ").strip() or default_map
        runs_input = input(f"刷取次数 [默认 {default_runs}]: ").strip() or str(default_runs)
        selected_runs = int(runs_input) if runs_input.isdigit() and int(runs_input) > 0 else default_runs
        config.setdefault("automation", {})
        config["automation"]["selected_map"] = map_input
        config["automation"]["selected_runs"] = selected_runs
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        reset_stop()
        run_loop(config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
