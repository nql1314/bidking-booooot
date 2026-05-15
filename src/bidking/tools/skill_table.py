# -*- coding: utf-8 -*-
"""将 ``Skill.txt``（整文件 Base64）解码为 UTF-8 Tab 表并导出 CSV。"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Sequence

from bidking.tools.game_tables import decode_if_base64

_SKILL_COLUMNS = (
    "skill_id",
    "name_zh",
    "desc_zh",
    "reserved_3",
    "item_name_key",
    "skill_desc_key",
    "reserved_6",
    "param_07",
    "param_08",
    "param_09",
    "param_10",
    "param_11",
    "param_12",
    "param_13",
    "param_14",
    "param_15",
    "param_16",
    "param_17",
    "param_18",
    "param_19",
    "param_20",
    "nested_21",
    "nested_22",
    "nested_23",
    "param_24",
    "param_25",
    "param_26",
)

_NCOL = len(_SKILL_COLUMNS)


def parse_skill_tsv(decoded: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw in decoded.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < _NCOL:
            parts = parts + [""] * (_NCOL - len(parts))
        else:
            parts = parts[:_NCOL]
        rows.append(parts)
    return rows


def write_skill_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(_SKILL_COLUMNS)
        for cols in rows:
            w.writerow(list(cols))


def export_skill_txt(skill_txt: Path, out_csv: Path) -> int:
    raw = skill_txt.read_bytes()
    decoded = decode_if_base64(raw)
    rows = parse_skill_tsv(decoded)
    write_skill_csv(out_csv, rows)
    return len(rows)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="解码 Skill.txt（Base64）并导出 CSV")
    p.add_argument(
        "--skill-txt",
        type=Path,
        default=Path("data") / "Skill.txt",
        help="Skill.txt 路径（默认 ./data/Skill.txt）",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data") / "Skill_export.csv",
        help="输出 CSV（默认 ./data/Skill_export.csv）",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    skill_path = args.skill_txt
    if not skill_path.is_file():
        print(f"错误：未找到 {skill_path}", file=sys.stderr)
        return 2
    n = export_skill_txt(skill_path, args.out)
    print(f"已写入 {args.out}（{n} 行）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
