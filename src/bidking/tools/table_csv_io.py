# -*- coding: utf-8 -*-
"""读取 bidking-tool ``wiki-build tables-to-csv`` 导出的带表头 CSV。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterator


def iter_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def load_language_map_csv(path: Path | None) -> Dict[str, str]:
    """``Language.csv``：``Id`` → ``Chinese``。"""
    if path is None or not path.is_file():
        return {}
    mapping: Dict[str, str] = {}
    for row in iter_csv_rows(path):
        key = (row.get("Id") or row.get("id") or "").strip()
        zh = (row.get("Chinese") or row.get("chinese") or "").strip()
        if key:
            mapping[key] = zh
    return mapping
