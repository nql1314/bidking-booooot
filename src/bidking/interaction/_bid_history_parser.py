#!/usr/bin/env python3
"""多人出价历史：每席仅从 OCR 读名字区、称号区；与 advisor 比对为己方则跳过价格 OCR，否则读当前轮价格并取最大。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageOps

# 与出价历史 UI 布局一致的人数场（与 ``layouts`` 的键对应）。
VALID_OPPONENT_BID_LOBBY_COUNTS: frozenset[int] = frozenset((2, 4, 5))

def _sorted_ocr_lines(result: Any) -> str:
    if not result:
        return ""
    rows = sorted(result, key=lambda item: (min(p[1] for p in item[0]), min(p[0] for p in item[0])))
    return "\n".join(str(item[1]) for item in rows)


def scale_region_box(
    region: dict[str, int],
    image_width: int,
    image_height: int,
    ref_width: int = 1920,
    ref_height: int = 1080,
) -> tuple[int, int, int, int]:
    rw = max(1, ref_width)
    rh = max(1, ref_height)
    left = round(float(region["left"]) * image_width / rw)
    top = round(float(region["top"]) * image_height / rh)
    width = round(float(region["width"]) * image_width / rw)
    height = round(float(region["height"]) * image_height / rh)
    right = min(image_width, max(0, left + width))
    bottom = min(image_height, max(0, top + height))
    left = min(max(0, left), right)
    top = min(max(0, top), bottom)
    return int(left), int(top), int(right), int(bottom)


def _default_ocr(image: Image.Image) -> str:
    """使用进程内单例 RapidOCR，避免每次裁剪都重新加载模型。"""
    import numpy as np

    from .ocr import infer_lines

    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    result = infer_lines(arr)
    return _sorted_ocr_lines(result)


_K_SUFFIX_TAIL = r"[KkＫｋ]"


def _k_suffix_price_candidates(compact: str) -> list[int]:
    """
    高价常用 ``数字+K``（千为单位）：``123.46K`` → 123460，``123K`` → 123000。
    逗号视为小数点（如 ``123,46K``）。
    """
    out: list[int] = []
    kt = _K_SUFFIX_TAIL
    for m in re.finditer(rf"(\d+[.,]\d+)\s*{kt}", compact):
        s = m.group(1).replace(",", ".")
        if s.count(".") != 1:
            continue
        try:
            out.append(int(round(float(s) * 1000)))
        except ValueError:
            continue
    for m in re.finditer(rf"(?<![.,])(\d+)\s*{kt}", compact):
        try:
            out.append(int(m.group(1)) * 1000)
        except ValueError:
            continue
    return out


def _digit_runs_preserve_lines(text: str) -> list[str]:
    """
    按行提取数字段，避免 OCR 把 ``50,000`` 断成两行后去掉换行粘成 ``00050`` 只得到一个 token。
    """
    runs: list[str] = []
    for ln in re.split(r"[\n\r]+", text):
        ln = ln.strip()
        if not ln:
            continue
        runs.extend(re.findall(r"\d+", ln))
    return runs


def extract_price_int_from_ocr_block(text: str) -> int | None:
    """
    从**单独裁剪的价格区域** OCR 文本解析整数（完整数值，不做末位截取）。

    优先匹配完整千分位 ``55,000``；超过约 10 万时界面可能显示 ``123.46K``（千单位），按数值×1000 解析。
    若千分位被换行打断（如 ``,000`` 与 ``50,`` 分两行），
    按行取数字段后按「高段×1000 + 低段三位」合并；长串 ``\\d{4,}`` 仅在值≥1000 时采纳，避免 ``00050``→50。
    """
    if not text or not text.strip():
        return None
    blob = (
        text.replace("：", ":")
        .replace("，", ",")
        .replace("O", "0")
        .replace("o", "0")
        .replace("l", "1")
    )
    compact = re.sub(r"\s+", "", blob)
    candidates: list[int] = []
    candidates.extend(_k_suffix_price_candidates(compact))
    for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", compact):
        s = m.group(0).split(".", 1)[0]
        candidates.append(int(s.replace(",", "")))
    parts = _digit_runs_preserve_lines(blob)
    if not parts:
        parts = re.findall(r"\d+", compact)
    # 带 K 的单价（如 ``170.71k``）同一行 OCR 常拆成 ``170``/``71`` 两段；若仍做「高三位+低三位」合并会得到 ``71*1000+170``（71170）错误。
    # 含 K 的一侧属于金额后半（小数+k），应交给 ``_k_suffix_price_candidates``，禁止此 hi-lo 启发式。
    has_k_suffix = bool(re.search(_K_SUFFIX_TAIL, blob))
    if (
        len(parts) == 2
        and (len(parts[0]) < 3 or len(parts[1]) < 3)
        and not has_k_suffix
    ):
        a, b = parts[0], parts[1]
        n_hi_lo: list[int] = []
        if len(b) == 3 and 1 <= len(a) <= 3:
            n_hi_lo.append(int(a) * 1000 + int(b))
        if len(a) == 3 and 1 <= len(b) <= 3:
            n_hi_lo.append(int(b) * 1000 + int(a))
        candidates.extend(n_hi_lo)
    for m in re.finditer(r"\d{4,}", compact):
        v = int(m.group(0))
        if v >= 1000:
            candidates.append(v)
    if not candidates:
        for m in re.finditer(r"\d+", compact):
            candidates.append(int(m.group(0)))
    if not candidates:
        return None
    return max(candidates)


@dataclass(frozen=True)
class PlayerRoundOcrTrace:
    """某一席：OCR 身份区 + 当前轮价格（己方不 OCR 价格）。"""

    slot_index: int
    ocr_name_text: str
    ocr_titles_text: str
    is_self: bool
    round_key: str
    name_region_ref: dict[str, int] | None
    titles_region_ref: dict[str, int] | None
    price_region_ref: dict[str, int] | None
    price_ocr_text: str
    price: int | None


@dataclass(frozen=True)
class MultiplayerMaxOtherBidResult:
    """其余玩家在当前轮次解析出的价格中的最大值。"""

    max_other_last_bid: int | None
    traces: tuple[PlayerRoundOcrTrace, ...]
    note: str | None
    #: 完整身份识别且恰有一席为己方时的席位下标；供同轮后续仅 OCR 对手价区时复用。
    self_slot_index: int | None = None


def _normalize_title_markers(titles: Iterable[str] | None) -> tuple[str, ...]:
    if not titles:
        return ()
    out: list[str] = []
    for raw in titles:
        s = (raw or "").strip()
        if s and s not in out:
            out.append(s)
    return tuple(out)


def _coerce_region(v: Any) -> dict[str, int] | None:
    if not isinstance(v, dict):
        return None
    try:
        return {
            "left": int(v["left"]),
            "top": int(v["top"]),
            "width": int(v["width"]),
            "height": int(v["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _merge_round_regions(player: dict[str, Any]) -> dict[str, dict[str, int]]:
    """仅接受 ``rounds`` 下 ``\"1\"``…``\"4\"`` 四个键，各为 ``{left,top,width,height}``。"""
    boxes: dict[str, dict[str, int]] = {}
    raw = player.get("rounds")
    if not isinstance(raw, dict):
        return boxes
    for k in ("1", "2", "3", "4"):
        br = _coerce_region(raw.get(k))
        if br:
            boxes[k] = br
    return boxes


def _validate_player_layout(p: dict[str, Any], slot_index: int) -> str | None:
    """若配置不合法返回错误说明，否则返回 None。"""
    _, err = _player_layout_and_round_boxes(p, slot_index)
    return err


def _player_layout_and_round_boxes(
    p: dict[str, Any], slot_index: int
) -> tuple[dict[str, dict[str, int]] | None, str | None]:
    """校验布局并返回已合并的 ``rounds`` 矩形；错误时返回 ``(None, 说明)``。"""
    if _coerce_region(p.get("character_name")) is None:
        return None, f"第 {slot_index + 1} 席：character_name 须为 OCR 区域 {{left,top,width,height}}"
    if _coerce_region(p.get("character_titles")) is None:
        return None, f"第 {slot_index + 1} 席：character_titles 须为 OCR 区域 {{left,top,width,height}}"
    rb = _merge_round_regions(p)
    for k in ("1", "2", "3", "4"):
        if k not in rb:
            return None, f"第 {slot_index + 1} 席：rounds 内须包含键 \"1\"、\"2\"、\"3\"、\"4\" 且均为有效矩形"
    return rb, None


def _ocr_region(
    image: Image.Image,
    region: dict[str, int],
    *,
    ref_w: int,
    ref_h: int,
    ocr_fn: Callable[[Image.Image], str],
) -> str:
    left, top, right, bottom = scale_region_box(region, image.width, image.height, ref_w, ref_h)
    crop = image.crop((left, top, right, bottom))
    return ocr_fn(ImageOps.grayscale(crop).convert("RGB")).strip()


def _resolve_slot_identity_text(
    p: dict[str, Any],
    image: Image.Image,
    *,
    ref_w: int,
    ref_h: int,
    ocr_fn: Callable[[Image.Image], str],
) -> tuple[str, str, dict[str, int], dict[str, int]]:
    """仅从 OCR 读取名字、称号（须已通过 `_validate_player_layout`）。"""
    name_ref = _coerce_region(p.get("character_name"))
    titles_ref = _coerce_region(p.get("character_titles"))
    if name_ref is None or titles_ref is None:
        raise RuntimeError("bid_history: character_name / character_titles 区域无效")
    name_text = _ocr_region(image, name_ref, ref_w=ref_w, ref_h=ref_h, ocr_fn=ocr_fn)
    titles_text = _ocr_region(image, titles_ref, ref_w=ref_w, ref_h=ref_h, ocr_fn=ocr_fn)
    return name_text, titles_text, name_ref, titles_ref


def ocr_identity_matches_advisor(
    name_text: str,
    titles_text: str,
    *,
    my_character_name: str,
    my_titles: tuple[str, ...],
) -> bool:
    """OCR 得到的角色名、称号文本是否与 advisor 一致：角色名须出现在文本中，每条己方称号均须出现。"""
    blob = (name_text or "") + "\n" + (titles_text or "")
    name = (my_character_name or "").strip()
    if not name:
        return False
    if name not in blob:
        return False
    for t in my_titles:
        ts = (t or "").strip()
        if ts and ts not in blob:
            return False
    return True


def _round_lookup_key(current_round: int | None) -> str:
    r = 1 if current_round is None else int(current_round)
    if r < 1:
        r = 1
    if r > 4:
        r = 4
    return str(r)


def _gray_rgb_crop(
    image: Image.Image,
    region: dict[str, int],
    *,
    ref_w: int,
    ref_h: int,
) -> Image.Image:
    left, top, right, bottom = scale_region_box(region, image.width, image.height, ref_w, ref_h)
    return ImageOps.grayscale(image.crop((left, top, right, bottom))).convert("RGB")


def _ocr_price_for_round_box(
    image: Image.Image,
    box: dict[str, int],
    *,
    ref_w: int,
    ref_h: int,
    ocr_fn: Callable[[Image.Image], str],
) -> tuple[str, int | None, Image.Image]:
    """裁剪当前轮价格区并 OCR，返回 (文本, 解析价, 灰度 RGB 图供 debug 保存)。"""
    left, top, right, bottom = scale_region_box(box, image.width, image.height, ref_w, ref_h)
    crop = image.crop((left, top, right, bottom))
    price_rgb = ImageOps.grayscale(crop).convert("RGB")
    price_text = ocr_fn(price_rgb).strip()
    price = extract_price_int_from_ocr_block(price_text)
    return price_text, price, price_rgb


def _apply_self_price_fallback_when_no_opponent(
    traces_list: list[PlayerRoundOcrTrace],
    image: Image.Image,
    *,
    ref_w: int,
    ref_h: int,
    ocr_fn: Callable[[Image.Image], str],
    rk: str,
    dbg_dir: Path | None,
    do_ocr_debug: bool,
    debug_save_crops: bool,
    debug_save_ocr_text: bool,
) -> tuple[list[PlayerRoundOcrTrace], int | None]:
    """
    当未解析到任何对手价时，对 ``is_self=True`` 且配置了价格区的席位补 OCR，
    取解析出的整数价的最大值作为对手价估计。
    """
    self_prices: list[int] = []
    out: list[PlayerRoundOcrTrace] = []
    for t in traces_list:
        if not t.is_self or t.price_region_ref is None:
            out.append(t)
            continue
        box = t.price_region_ref
        price_text, price, price_rgb = _ocr_price_for_round_box(
            image, box, ref_w=ref_w, ref_h=ref_h, ocr_fn=ocr_fn
        )
        if do_ocr_debug and dbg_dir is not None:
            _save_bid_history_ocr_debug(
                dbg_dir,
                t.slot_index,
                rk,
                "price",
                crop=price_rgb,
                text=price_text,
                save_crops=debug_save_crops,
                save_txt=debug_save_ocr_text,
            )
        out.append(
            PlayerRoundOcrTrace(
                slot_index=t.slot_index,
                ocr_name_text=t.ocr_name_text,
                ocr_titles_text=t.ocr_titles_text,
                is_self=t.is_self,
                round_key=t.round_key,
                name_region_ref=t.name_region_ref,
                titles_region_ref=t.titles_region_ref,
                price_region_ref=t.price_region_ref,
                price_ocr_text=price_text,
                price=price,
            )
        )
        if price is not None:
            self_prices.append(price)
    fb_max = max(self_prices) if self_prices else None
    return out, fb_max


def _save_bid_history_ocr_debug(
    runs_dir: Path,
    slot_index: int,
    round_key: str,
    part: str,
    *,
    crop: Image.Image | None,
    text: str | None,
    save_crops: bool,
    save_txt: bool,
) -> None:
    """文件名：``{角色席位index}_{round}_{name|titles|price}`` + ``.png`` / ``.txt``。"""
    if not save_crops and not save_txt:
        return
    stem = f"{slot_index}_{round_key}_{part}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    if save_crops and crop is not None:
        crop.save(runs_dir / f"{stem}.png")
    if save_txt:
        (runs_dir / f"{stem}.txt").write_text(text if text is not None else "", encoding="utf-8")


def get_max_other_players_last_bid_from_image(
    image: Image.Image,
    *,
    lobby_player_count: int,
    current_round: int | None,
    players: list[dict[str, Any]],
    my_character_name: str,
    my_titles: Iterable[str] | None = None,
    reference_size: tuple[int, int] = (1920, 1080),
    ocr_fn: Callable[[Image.Image], str] | None = None,
    debug_runs_dir: Path | str | None = None,
    debug_save_crops: bool = False,
    debug_save_ocr_text: bool = False,
    known_self_slot_index: int | None = None,
) -> MultiplayerMaxOtherBidResult:
    """
    每席：OCR 名字区、称号区；与 advisor 比对为己方则跳过价格 OCR；
    否则 OCR 当前轮价格区并解析整数，取非己方中的最大值。

    若传入 ``known_self_slot_index``（0-based 且与 ``players`` 顺序一致），则不再 OCR 各席名字/称号，
    仅对非己方的 ``n-1`` 个价格区做 OCR（同轮内复用首轮识别结果以省 OCR）。

    若 ``debug_runs_dir`` 非空且 ``debug_save_crops`` / ``debug_save_ocr_text`` 其一为真，
    在对应目录写入 ``{席位index}_{轮次}_{name|titles|price}.png`` 与 ``.txt``。
    """
    titles = _normalize_title_markers(my_titles)
    ocr = ocr_fn or _default_ocr
    ref_w, ref_h = reference_size
    rk = _round_lookup_key(current_round)
    traces: list[PlayerRoundOcrTrace] = []
    dbg_dir = Path(debug_runs_dir) if debug_runs_dir is not None else None
    do_ocr_debug = dbg_dir is not None and (debug_save_crops or debug_save_ocr_text)

    if lobby_player_count not in VALID_OPPONENT_BID_LOBBY_COUNTS:
        return MultiplayerMaxOtherBidResult(
            max_other_last_bid=None,
            traces=(),
            note="lobby_player_count 须为 2、4 或 5",
        )
    if len(players) != lobby_player_count:
        return MultiplayerMaxOtherBidResult(
            max_other_last_bid=None,
            traces=(),
            note=f"布局人数与 lobby 不一致：配置 {len(players)} 席，当前 {lobby_player_count} 人场",
        )

    round_boxes_per_player: list[dict[str, dict[str, int]]] = []
    for idx, p in enumerate(players):
        rb, err = _player_layout_and_round_boxes(p, idx)
        if err is not None:
            return MultiplayerMaxOtherBidResult(max_other_last_bid=None, traces=(), note=err)
        round_boxes_per_player.append(rb)

    k_known = known_self_slot_index
    if k_known is not None and (int(k_known) < 0 or int(k_known) >= len(players)):
        k_known = None

    if k_known is not None:
        traces_fast: list[PlayerRoundOcrTrace] = []
        others_prices_fast: list[int] = []
        self_idx = int(k_known)
        for idx, p in enumerate(players):
            rb = round_boxes_per_player[idx]
            nr = _coerce_region(p.get("character_name"))
            tr = _coerce_region(p.get("character_titles"))
            if nr is None or tr is None:
                return MultiplayerMaxOtherBidResult(
                    max_other_last_bid=None,
                    traces=(),
                    note=f"第 {idx + 1} 席：布局缺少 character_name / character_titles",
                )
            box = rb.get(rk)
            if idx == self_idx:
                traces_fast.append(
                    PlayerRoundOcrTrace(
                        slot_index=idx,
                        ocr_name_text="",
                        ocr_titles_text="",
                        is_self=True,
                        round_key=rk,
                        name_region_ref=dict(nr),
                        titles_region_ref=dict(tr),
                        price_region_ref=dict(box) if box is not None else None,
                        price_ocr_text="",
                        price=None,
                    )
                )
                continue
            if box is None:
                traces_fast.append(
                    PlayerRoundOcrTrace(
                        slot_index=idx,
                        ocr_name_text="",
                        ocr_titles_text="",
                        is_self=False,
                        round_key=rk,
                        name_region_ref=dict(nr),
                        titles_region_ref=dict(tr),
                        price_region_ref=None,
                        price_ocr_text="",
                        price=None,
                    )
                )
                continue
            left, top, right, bottom = scale_region_box(box, image.width, image.height, ref_w, ref_h)
            crop = image.crop((left, top, right, bottom))
            price_rgb = ImageOps.grayscale(crop).convert("RGB")
            price_text = ocr(price_rgb).strip()
            price = extract_price_int_from_ocr_block(price_text)
            if do_ocr_debug and dbg_dir is not None:
                _save_bid_history_ocr_debug(
                    dbg_dir,
                    idx,
                    rk,
                    "price",
                    crop=price_rgb,
                    text=price_text,
                    save_crops=debug_save_crops,
                    save_txt=debug_save_ocr_text,
                )
            traces_fast.append(
                PlayerRoundOcrTrace(
                    slot_index=idx,
                    ocr_name_text="",
                    ocr_titles_text="",
                    is_self=False,
                    round_key=rk,
                    name_region_ref=dict(nr),
                    titles_region_ref=dict(tr),
                    price_region_ref=dict(box),
                    price_ocr_text=price_text,
                    price=price,
                )
            )
            if price is not None:
                others_prices_fast.append(price)
        max_o = max(others_prices_fast) if others_prices_fast else None
        note_f: str | None = None
        any_other_fast = any(i != self_idx for i in range(len(players)))
        if max_o is None and not others_prices_fast and any_other_fast:
            note_f = "其余席位均未解析出有效整数价格（快速路径：仅价格区）"
        if max_o is None and any_other_fast:
            traces_fast, fb_max = _apply_self_price_fallback_when_no_opponent(
                traces_fast,
                image,
                ref_w=ref_w,
                ref_h=ref_h,
                ocr_fn=ocr,
                rk=rk,
                dbg_dir=dbg_dir,
                do_ocr_debug=do_ocr_debug,
                debug_save_crops=debug_save_crops,
                debug_save_ocr_text=debug_save_ocr_text,
            )
            if fb_max is not None:
                max_o = fb_max
                note_f = (note_f + "；" if note_f else "") + "未获取对手价，已用己方价格区最大值替代"
        return MultiplayerMaxOtherBidResult(
            max_other_last_bid=max_o,
            traces=tuple(traces_fast),
            note=note_f,
            self_slot_index=self_idx,
        )

    identity_rows: list[tuple[str, str, bool, dict[str, int], dict[str, int]]] = []
    for idx, p in enumerate(players):
        name_t, titles_t, nr, tr = _resolve_slot_identity_text(p, image, ref_w=ref_w, ref_h=ref_h, ocr_fn=ocr)
        is_self = ocr_identity_matches_advisor(
            name_t, titles_t, my_character_name=my_character_name, my_titles=titles
        )
        identity_rows.append((name_t, titles_t, is_self, nr, tr))
        if do_ocr_debug and dbg_dir is not None:
            name_im = _gray_rgb_crop(image, nr, ref_w=ref_w, ref_h=ref_h)
            titles_im = _gray_rgb_crop(image, tr, ref_w=ref_w, ref_h=ref_h)
            _save_bid_history_ocr_debug(
                dbg_dir,
                idx,
                rk,
                "name",
                crop=name_im,
                text=name_t,
                save_crops=debug_save_crops,
                save_txt=debug_save_ocr_text,
            )
            _save_bid_history_ocr_debug(
                dbg_dir,
                idx,
                rk,
                "titles",
                crop=titles_im,
                text=titles_t,
                save_crops=debug_save_crops,
                save_txt=debug_save_ocr_text,
            )

    n_self = sum(1 for row in identity_rows if row[2])
    if n_self == 0:
        return MultiplayerMaxOtherBidResult(
            max_other_last_bid=None,
            traces=(),
            note="未识别到己方：名字区与称号区 OCR 文本中须能同时匹配 advisor 的角色名与全部称号",
        )

    others_prices: list[int] = []

    for idx in range(len(players)):
        name_t, titles_t, is_self, name_ref, titles_ref = identity_rows[idx]
        box = round_boxes_per_player[idx].get(rk)
        if box is None:
            traces.append(
                PlayerRoundOcrTrace(
                    slot_index=idx,
                    ocr_name_text=name_t,
                    ocr_titles_text=titles_t,
                    is_self=is_self,
                    round_key=rk,
                    name_region_ref=name_ref,
                    titles_region_ref=titles_ref,
                    price_region_ref=None,
                    price_ocr_text="",
                    price=None,
                )
            )
            continue

        if is_self:
            traces.append(
                PlayerRoundOcrTrace(
                    slot_index=idx,
                    ocr_name_text=name_t,
                    ocr_titles_text=titles_t,
                    is_self=True,
                    round_key=rk,
                    name_region_ref=name_ref,
                    titles_region_ref=titles_ref,
                    price_region_ref=dict(box),
                    price_ocr_text="",
                    price=None,
                )
            )
            continue

        left, top, right, bottom = scale_region_box(box, image.width, image.height, ref_w, ref_h)
        crop = image.crop((left, top, right, bottom))
        price_rgb = ImageOps.grayscale(crop).convert("RGB")
        price_text = ocr(price_rgb).strip()
        price = extract_price_int_from_ocr_block(price_text)
        if do_ocr_debug and dbg_dir is not None:
            _save_bid_history_ocr_debug(
                dbg_dir,
                idx,
                rk,
                "price",
                crop=price_rgb,
                text=price_text,
                save_crops=debug_save_crops,
                save_txt=debug_save_ocr_text,
            )
        traces.append(
            PlayerRoundOcrTrace(
                slot_index=idx,
                ocr_name_text=name_t,
                ocr_titles_text=titles_t,
                is_self=False,
                round_key=rk,
                name_region_ref=name_ref,
                titles_region_ref=titles_ref,
                price_region_ref=dict(box),
                price_ocr_text=price_text,
                price=price,
            )
        )
        if price is not None:
            others_prices.append(price)

    max_other = max(others_prices) if others_prices else None
    note: str | None = None
    any_other = any(not identity_rows[i][2] for i in range(len(players)))
    if max_other is None and not others_prices and any_other:
        note = "其余席位均未解析出有效整数价格"
    if max_other is None and any_other:
        traces, fb_max = _apply_self_price_fallback_when_no_opponent(
            traces,
            image,
            ref_w=ref_w,
            ref_h=ref_h,
            ocr_fn=ocr,
            rk=rk,
            dbg_dir=dbg_dir,
            do_ocr_debug=do_ocr_debug,
            debug_save_crops=debug_save_crops,
            debug_save_ocr_text=debug_save_ocr_text,
        )
        if fb_max is not None:
            max_other = fb_max
            note = (note + "；" if note else "") + "未获取对手价，已用己方价格区最大值替代"
    self_slot_only: int | None = None
    if n_self == 1:
        for si, row in enumerate(identity_rows):
            if row[2]:
                self_slot_only = si
                break
    return MultiplayerMaxOtherBidResult(
        max_other_last_bid=max_other,
        traces=tuple(traces),
        note=note,
        self_slot_index=self_slot_only,
    )


def read_multiplayer_layout_for_count(capture: dict[str, Any], lobby_player_count: int) -> list[dict[str, Any]] | None:
    """从 ``capture.bid_history_multiplayer.layouts`` 读取对应人数的布局列表。"""
    multi = capture.get("bid_history_multiplayer")
    if not isinstance(multi, dict):
        return None
    layouts = multi.get("layouts")
    if not isinstance(layouts, dict):
        return None
    key = str(int(lobby_player_count))
    block = layouts.get(key)
    if not isinstance(block, list) or not block:
        return None
    return [p for p in block if isinstance(p, dict)]


def coerce_valid_lobby_player_count(raw: Any) -> int | None:
    """将配置值规范为 2 / 4 / 5 之一，否则 ``None``。"""
    try:
        n = int(raw) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        return None
    return n if n in VALID_OPPONENT_BID_LOBBY_COUNTS else None


def resolve_lobby_player_count_for_opponent_bid(
    config: dict[str, Any],
    *,
    override: int | None = None,
) -> int | None:
    """解析 OCR 对手价所需人数场。

    优先级：``override`` → ``automation.maps[selected_map].player_count``（或 ``lobby_player_count``）
    → ``advisor.lobby_player_count``。
    """
    if override is not None:
        return coerce_valid_lobby_player_count(override)
    au = config.get("automation", {}) or {}
    sel = str(au.get("selected_map") or au.get("default_map") or "1").strip() or "1"
    maps = au.get("maps")
    if isinstance(maps, dict):
        item = maps.get(sel)
        if isinstance(item, dict):
            n = coerce_valid_lobby_player_count(item.get("player_count", item.get("lobby_player_count")))
            if n is not None:
                return n
    adv = config.get("advisor", {}) or {}
    return coerce_valid_lobby_player_count(adv.get("lobby_player_count"))
