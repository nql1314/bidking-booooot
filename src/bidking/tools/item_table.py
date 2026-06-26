# -*- coding: utf-8 -*-
"""从 bidking-tool 导出的 ``Item.csv`` 生成 ``item_prices.csv``。"""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

from bidking.tools.table_csv_io import iter_csv_rows, load_language_map_csv

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


def resolve_item_name(row: dict[str, str], lang: Dict[str, str]) -> str:
    display = (row.get("col_1") or "").strip()
    if display:
        return display
    name_key = (row.get("item_name") or "").strip()
    if name_key and name_key in lang:
        return lang[name_key]
    if name_key:
        return name_key
    return (row.get("id") or "").strip()


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


def parse_item_csv_rows(item_csv: Path, lang: Dict[str, str]) -> List[ItemRow]:
    rows: List[ItemRow] = []
    for row in iter_csv_rows(item_csv):
        raw_id = (row.get("id") or "").strip()
        if not raw_id:
            continue
        try:
            item_id = int(raw_id)
        except ValueError:
            continue
        category_tags = tuple(parse_int_list(row.get("item_type_id") or ""))
        if not include_item(item_id, category_tags):
            continue
        try:
            shape = int((row.get("slot_type") or "0").strip() or "0")
            quality = int((row.get("item_quality") or "0").strip() or "0")
            base_value = int((row.get("base_value") or "0").strip() or "0")
        except ValueError:
            continue
        rows.append(
            ItemRow(
                item_id=item_id,
                name=resolve_item_name(row, lang),
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


def export_item_csv(
    item_csv: Path,
    out_csv: Path,
    *,
    lang_csv: Path | None = None,
) -> int:
    lang = load_language_map_csv(lang_csv)
    rows = parse_item_csv_rows(item_csv, lang)
    write_item_prices_csv(out_csv, rows)
    return len(rows)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="从 Item.csv 导出 item_prices.csv")
    p.add_argument(
        "--item-csv",
        type=Path,
        default=Path("data") / "Item.csv",
        help="Item.csv 路径（默认 ./data/Item.csv）",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data") / "item_prices.csv",
        help="输出 CSV（默认 ./data/item_prices.csv）",
    )
    p.add_argument(
        "--lang-csv",
        type=Path,
        default=None,
        help="可选 Language.csv，用于 col_1 为空时解析 item_name 键",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    item_path = args.item_csv
    if not item_path.is_file():
        print(f"错误：未找到 {item_path}", file=sys.stderr)
        return 2
    n = export_item_csv(item_path, args.out, lang_csv=args.lang_csv)
    print(f"已写入 {args.out}（{n} 行）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
