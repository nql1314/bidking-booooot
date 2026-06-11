# -*- coding: utf-8 -*-
"""将 ``Item.txt``（整文件 Base64）解码并导出 ``item_prices.csv``。"""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from bidking.tools.game_tables import decode_if_base64

# Table_Item.cs Load() 列索引
_COL_ID = 0
_COL_DISPLAY = 1
_COL_NAME_KEY = 3
_COL_TYPE_IDS = 6
_COL_SLOT_TYPE = 7
_COL_QUALITY = 8
_COL_BASE_VALUE = 9

CATEGORY_MIN = 101
CATEGORY_MAX = 110
EXTRA_CATEGORY_TAGS = frozenset({14, 100})
DEFAULT_GRID_SIZE = "[10,5]"

_ITEM_PRICES_HEADER = (
    "item_id",
    "name",
    "category_tags",
    "shape",
    "quality",
    "base_value",
    "grid_size",
)


@dataclass(frozen=True)
class ItemRow:
    item_id: int
    name: str
    category_tags: tuple[int, ...]
    shape: int
    quality: int
    base_value: int


def parse_int_list(raw: str) -> List[int]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []
    if isinstance(parsed, int):
        return [parsed]
    if not isinstance(parsed, list):
        return []
    out: List[int] = []
    for value in parsed:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def load_language_map(path: Path | None) -> Dict[str, str]:
    if path is None or not path.is_file():
        return {}
    text = decode_if_base64(path.read_bytes())
    mapping: Dict[str, str] = {}
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        mapping[parts[0].strip()] = parts[1].strip()
    return mapping


def resolve_item_name(parts: Sequence[str], lang: Dict[str, str]) -> str:
    display = parts[_COL_DISPLAY].strip() if len(parts) > _COL_DISPLAY else ""
    if display:
        return display
    name_key = parts[_COL_NAME_KEY].strip() if len(parts) > _COL_NAME_KEY else ""
    if name_key and name_key in lang:
        return lang[name_key]
    if name_key:
        return name_key
    return parts[_COL_ID].strip() if parts else ""


def include_item(item_id: int, category_tags: Sequence[int]) -> bool:
    """与现有 ``item_prices.csv`` 对齐：棋盘藏品 + 皮肤 + 特殊 100 档。"""
    if item_id <= 1_000_000:
        return False
    if any(CATEGORY_MIN <= tag <= CATEGORY_MAX for tag in category_tags):
        return True
    return any(tag in EXTRA_CATEGORY_TAGS for tag in category_tags)


def item_sort_key(row: ItemRow) -> tuple[int, int]:
    tags = set(row.category_tags)
    if 14 in tags:
        return (0, row.item_id)
    if tags.intersection(range(CATEGORY_MIN, CATEGORY_MAX + 1)):
        return (1, row.item_id)
    if 100 in tags:
        return (2, row.item_id)
    return (3, row.item_id)


def parse_item_rows(decoded: str, lang: Dict[str, str]) -> List[ItemRow]:
    rows: List[ItemRow] = []
    for raw_line in decoded.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        try:
            item_id = int(parts[0].strip())
        except ValueError:
            continue
        category_tags = tuple(parse_int_list(parts[_COL_TYPE_IDS] if len(parts) > _COL_TYPE_IDS else ""))
        if not include_item(item_id, category_tags):
            continue
        try:
            shape = int(parts[_COL_SLOT_TYPE]) if len(parts) > _COL_SLOT_TYPE and parts[_COL_SLOT_TYPE].strip() else 0
            quality = int(parts[_COL_QUALITY]) if len(parts) > _COL_QUALITY and parts[_COL_QUALITY].strip() else 0
            base_value = int(parts[_COL_BASE_VALUE]) if len(parts) > _COL_BASE_VALUE and parts[_COL_BASE_VALUE].strip() else 0
        except ValueError:
            continue
        rows.append(
            ItemRow(
                item_id=item_id,
                name=resolve_item_name(parts, lang),
                category_tags=category_tags,
                shape=shape,
                quality=quality,
                base_value=base_value,
            )
        )
    rows.sort(key=item_sort_key)
    return rows


def write_item_prices_csv(path: Path, rows: Sequence[ItemRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(_ITEM_PRICES_HEADER)
        for row in rows:
            writer.writerow(
                [
                    row.item_id,
                    row.name,
                    str(list(row.category_tags)).replace(" ", ""),
                    row.shape,
                    row.quality,
                    row.base_value,
                    DEFAULT_GRID_SIZE,
                ]
            )


def export_item_txt(
    item_txt: Path,
    out_csv: Path,
    *,
    lang_txt: Path | None = None,
) -> int:
    raw = item_txt.read_bytes()
    decoded = decode_if_base64(raw)
    lang = load_language_map(lang_txt)
    rows = parse_item_rows(decoded, lang)
    write_item_prices_csv(out_csv, rows)
    return len(rows)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="解码 Item.txt（Base64）并导出 item_prices.csv")
    p.add_argument(
        "--item-txt",
        type=Path,
        default=Path("data") / "Item.txt",
        help="Item.txt 路径（默认 ./data/Item.txt）",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data") / "item_prices.csv",
        help="输出 CSV（默认 ./data/item_prices.csv）",
    )
    p.add_argument(
        "--lang-txt",
        type=Path,
        default=None,
        help="可选 Language.txt，用于 display 为空时解析 item_name 键",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    item_path = args.item_txt
    if not item_path.is_file():
        print(f"错误：未找到 {item_path}", file=sys.stderr)
        return 2
    n = export_item_txt(item_path, args.out, lang_txt=args.lang_txt)
    print(f"已写入 {args.out}（{n} 行）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
