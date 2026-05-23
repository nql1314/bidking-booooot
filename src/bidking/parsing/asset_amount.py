# -*- coding: utf-8 -*-
"""主界面资产 OCR 文本解析与地图金币准入门槛查询。"""

from __future__ import annotations

import re
from typing import Any, Mapping

_SUFFIX_MULTIPLIER = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
}


def _normalize_ocr_amount_text(text: str) -> str:
    raw = (text or "").translate(
        str.maketrans(
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
                "，": ",",
                "．": ".",
                "ｋ": "K",
                "ｍ": "M",
                "ｂ": "B",
            }
        )
    )
    return re.sub(r"\s+", " ", raw).strip().upper()


def _collapse_amount_whitespace(text: str) -> str:
    """合并 OCR 在千分位逗号、数字与 K/M/B 后缀之间误插的空格（如 ``9, 665K``）。"""
    t = text
    while True:
        prev = t
        t = re.sub(r"(?<=,)\s+(?=\d)", "", t)
        t = re.sub(r"(?<=\d)\s+(?=[KMB])", "", t, flags=re.IGNORECASE)
        if t == prev:
            break
    return t


_ASSET_AMOUNT_TOKEN_RE = re.compile(r"\d[\d,\.]*[KMB]?", re.IGNORECASE)


def _digits_only_amount(num_part: str) -> float | None:
    s = num_part.strip()
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        tail = s.split(",")[-1]
        if len(tail) == 3 and all(ch.isdigit() for ch in tail):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_single_amount_token(token: str) -> int | None:
    tok = token.strip().upper()
    if not tok or not tok[0].isdigit():
        return None
    suffix = ""
    if tok[-1] in _SUFFIX_MULTIPLIER:
        suffix = tok[-1]
        tok = tok[:-1]
    base = _digits_only_amount(tok)
    if base is None or base < 0:
        return None
    mult = _SUFFIX_MULTIPLIER.get(suffix, 1)
    return int(round(base * mult))


def _parse_primary_amount_on_line(line: str) -> int | None:
    """解析单行中的主金额（优先带 K/M/B 后缀的 token）。"""
    collapsed = _collapse_amount_whitespace(_normalize_ocr_amount_text(line))
    if not collapsed:
        return None
    tokens = [m.group(0) for m in _ASSET_AMOUNT_TOKEN_RE.finditer(collapsed)]
    if not tokens:
        return None
    for tok in tokens:
        if tok[-1] in _SUFFIX_MULTIPLIER:
            value = _parse_single_amount_token(tok)
            if value is not None:
                return value
    best: int | None = None
    for tok in tokens:
        value = _parse_single_amount_token(tok)
        if value is None:
            continue
        if best is None or value > best:
            best = value
    return best


def _is_bidking_label_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", (line or "")).upper()
    return compact in ("BIDKING", "BIDKING.", "BIDKING:")


def _is_amount_like_line(line: str) -> bool:
    """金额行仅含数字/千分位与可选 K/M/B 后缀，排除 ``Nico666`` 等昵称。"""
    collapsed = _collapse_amount_whitespace(_normalize_ocr_amount_text(line))
    if not collapsed or _HOME_UID_RE.search(collapsed):
        return False
    body = collapsed
    if body[-1] in _SUFFIX_MULTIPLIER:
        body = body[:-1]
    return bool(body) and all(ch in "0123456789,." for ch in body)


_HOME_UID_RE = re.compile(r"UID\s*[:：]?\s*(\d{6,})", re.IGNORECASE)


def parse_uid_from_home_full_window(full_window_text: str) -> str | None:
    """从主界面整窗 OCR 解析 ``UID:358372071974712`` 形式的玩家 UID。"""
    for line in (full_window_text or "").splitlines():
        match = _HOME_UID_RE.search(line.strip())
        if match:
            return match.group(1)
    match = _HOME_UID_RE.search(full_window_text or "")
    return match.group(1) if match else None


def parse_asset_amount_from_bidking_home(full_window_text: str) -> int | None:
    """
    从主界面整窗 OCR 中读取 ``BidKing`` 标签正下方的当前资产。

    BidKing 下常有 2 个数字（如门票 ``650`` 与资产 ``9,674K``），取较大者。
    """
    lines = [ln.strip() for ln in (full_window_text or "").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if not _is_bidking_label_line(line):
            continue
        best: int | None = None
        for next_line in lines[i + 1 : i + 4]:
            if not _is_amount_like_line(next_line):
                continue
            value = _parse_primary_amount_on_line(next_line)
            if value is None:
                continue
            if best is None or value > best:
                best = value
        if best is not None:
            return best
    return None


def parse_asset_amount_from_ocr(text: str) -> int | None:
    """
    解析 OCR 文本中的金额，支持 ``11,111``、``11,111K``、``111M`` 等缩写。

    若文本含多个候选，取数值最大者。
    """
    normalized = _normalize_ocr_amount_text(text)
    if not normalized:
        return None
    collapsed = _collapse_amount_whitespace(normalized)
    best: int | None = None
    for match in _ASSET_AMOUNT_TOKEN_RE.finditer(collapsed):
        value = _parse_single_amount_token(match.group(0))
        if value is None:
            continue
        if best is None or value > best:
            best = value
    return best


def _safe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def map_entry_money_by_map_key(automation: Mapping[str, Any], map_key: str) -> int:
    """从 ``automation.map_entry_money_by_map_id`` 读取地图金币准入门槛。"""
    key = str(map_key or "").strip()
    if not key:
        return 0
    by_id = automation.get("map_entry_money_by_map_id")
    if not isinstance(by_id, dict):
        return 0
    raw = by_id.get(key)
    if raw is None and key.isdigit():
        raw = by_id.get(int(key))
    v = _safe_int(raw)
    if v is not None and v > 0:
        return int(v)
    return 0
