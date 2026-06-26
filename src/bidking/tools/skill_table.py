# -*- coding: utf-8 -*-
"""从 bidking-tool 导出的 ``Skill.csv`` 生成 bot 使用的 ``Skill_export.csv``。"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Sequence

from bidking.tools.table_csv_io import iter_csv_rows

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

_SKILL_CSV_FIELDS = (
    "id",
    "col_1",
    "col_2",
    "skill_group",
    "skill_name",
    "skilldesc",
    "skill_textshow",
    "skill_type",
    "skilltarget",
    "skilltargetvalue",
    "skilltarget2",
    "skilltargetvalue2",
    "skilltarget3",
    "skilltargetvalue3",
    "skill_count_type",
    "skill_count",
    "skilleffect_position",
    "skill_icon",
    "skill_value",
    "skill_active_type",
    "skill_opt",
    "skill_opt_param1",
    "skill_opt_param2",
    "skill_cast",
    "skill_round",
    "skill_CD",
    "show_type",
)


def skill_csv_row_to_export_cols(row: dict[str, str]) -> List[str]:
    return [(row.get(src) or "").strip() for src in _SKILL_CSV_FIELDS]


def load_skill_export_rows(skill_csv: Path) -> List[List[str]]:
    rows: List[List[str]] = []
    for row in iter_csv_rows(skill_csv):
        if not (row.get("id") or "").strip():
            continue
        rows.append(skill_csv_row_to_export_cols(row))
    return rows


def write_skill_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(_SKILL_COLUMNS)
        for cols in rows:
            w.writerow(list(cols))


def export_skill_csv(skill_csv: Path, out_csv: Path) -> int:
    rows = load_skill_export_rows(skill_csv)
    write_skill_csv(out_csv, rows)
    return len(rows)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="从 Skill.csv 导出 Skill_export.csv")
    p.add_argument(
        "--skill-csv",
        type=Path,
        default=Path("data") / "Skill.csv",
        help="Skill.csv 路径（默认 ./data/Skill.csv）",
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
    skill_path = args.skill_csv
    if not skill_path.is_file():
        print(f"错误：未找到 {skill_path}", file=sys.stderr)
        return 2
    n = export_skill_csv(skill_path, args.out)
    print(f"已写入 {args.out}（{n} 行）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
