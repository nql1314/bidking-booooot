# -*- coding: utf-8 -*-
"""
从 bidking-tool 导出的 ``Drop.csv`` / ``RankMap.csv`` 生成 bot 使用的派生 CSV。

``Drop.csv`` 的 ``items_list`` 列为 ``[[ref_type, ref_id, …, weight], …]`` 字面量，
可展开为 ``drop_table_weights.csv`` 四列；``RankMap.csv`` 导出为 ``rank_map_export.csv``。
"""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from bidking.tools.table_csv_io import iter_csv_rows

DropEdge = Tuple[int, int, int, int]


def parse_drop_items_list(drop_id: int, items_list_raw: str) -> List[DropEdge]:
    """解析 ``Drop.csv`` 的 ``items_list`` 列，返回 ``(drop_id, ref_id, weight, ref_type)``。"""
    text = (items_list_raw or "").strip()
    if not text:
        return []
    try:
        refs = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(refs, list):
        return []
    edges: List[DropEdge] = []
    for entry in refs:
        if not isinstance(entry, (list, tuple)) or len(entry) != 5:
            continue
        ref_type, ref_id, _a, _b, weight = entry
        try:
            edges.append((drop_id, int(ref_id), int(weight), int(ref_type)))
        except (TypeError, ValueError):
            continue
    return edges


def load_drop_edges_from_csv(path: Path) -> List[DropEdge]:
    edges: List[DropEdge] = []
    for row in iter_csv_rows(path):
        try:
            drop_id = int((row.get("group_id") or "").strip())
        except ValueError:
            continue
        edges.extend(parse_drop_items_list(drop_id, row.get("items_list") or ""))
    return edges


def load_rank_map_rows_from_csv(path: Path) -> List[List[str]]:
    """读取 ``RankMap.csv``，输出与旧 ``rank_map_export.csv`` 一致的 7 列。"""
    rows: List[List[str]] = []
    for row in iter_csv_rows(path):
        map_id = (row.get("id") or "").strip()
        if not map_id:
            continue
        rows.append(
            [
                map_id,
                (row.get("col_1") or "").strip(),
                (row.get("col_2") or "").strip(),
                (row.get("match_time") or "").strip(),
                (row.get("role_spawn") or "").strip(),
                (row.get("min_bid_range") or "").strip(),
                (row.get("bid_type") or "").strip(),
            ]
        )
    return rows


def write_drop_table_weights_csv(path: Path, edges: Sequence[DropEdge]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = sorted(set(edges))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drop_id", "ref_id", "weight", "ref_type"])
        for drop_id, ref_id, weight, ref_type in unique:
            w.writerow([drop_id, ref_id, weight, ref_type])


_RANK_HEADER = [
    "map_id",
    "name",
    "description",
    "rank_level_brackets",
    "category_weights",
    "value_brackets",
    "extra_params",
]


def write_rank_map_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(_RANK_HEADER)
        for cols in rows:
            w.writerow(list(cols))


def merge_calculator_drop_rows(
    merged_in: Path,
    edges: Sequence[DropEdge],
    merged_out: Path,
) -> None:
    """
    保留 ``calculator_data_merged.csv`` 中非 DROP 行，用 ``edges`` 重写全部 DROP 行
    （列顺序与现有合并表一致）。
    """
    merged_out.parent.mkdir(parents=True, exist_ok=True)
    kept: List[dict] = []
    fieldnames: List[str] | None = None
    with merged_in.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("合并表缺少表头")
        for row in reader:
            rt = (row.get("record_type") or "").strip().upper()
            if rt == "DROP":
                continue
            kept.append(row)

    drop_rows: List[dict] = []
    for drop_id, ref_id, weight, ref_type in sorted(edges):
        drop_rows.append(
            {
                "record_type": "DROP",
                "item_id": "0",
                "name": "0",
                "quality": "0",
                "base_value": "0",
                "shape": "0",
                "drop_id": str(drop_id),
                "ref_id": str(ref_id),
                "weight": str(weight),
                "ref_type": str(ref_type),
            }
        )

    out_rows = kept + drop_rows
    with merged_out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)


def export_from_data_dir(
    data_dir: Path,
    *,
    drop_csv_in: Path | None = None,
    rank_csv_in: Path | None = None,
    drop_csv: Path | None = None,
    rank_csv: Path | None = None,
    merge_calculator: Path | None = None,
    merge_out: Path | None = None,
) -> None:
    drop_in = drop_csv_in or (data_dir / "Drop.csv")
    rank_in = rank_csv_in or (data_dir / "RankMap.csv")
    edges: List[DropEdge] | None = None

    if drop_in.is_file():
        edges = load_drop_edges_from_csv(drop_in)
        out_drop = drop_csv or (data_dir / "drop_table_weights.csv")
        write_drop_table_weights_csv(out_drop, edges)
        print(f"已写入 {out_drop}（{len(set(edges))} 条边，去重后）", file=sys.stderr)
        if merge_calculator:
            m_out = merge_out or merge_calculator.with_name(
                merge_calculator.stem + ".merged_drop.csv"
            )
            merge_calculator_drop_rows(merge_calculator, sorted(set(edges)), m_out)
            print(f"已写入合并表 {m_out}", file=sys.stderr)
    else:
        print(f"跳过 Drop：未找到 {drop_in}", file=sys.stderr)

    if rank_in.is_file():
        rows = load_rank_map_rows_from_csv(rank_in)
        out_rank = rank_csv or (data_dir / "rank_map_export.csv")
        write_rank_map_csv(out_rank, rows)
        print(f"已写入 {out_rank}（{len(rows)} 行）", file=sys.stderr)
    else:
        print(f"跳过 RankMap：未找到 {rank_in}", file=sys.stderr)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="从 Drop.csv / RankMap.csv 导出 drop_table_weights.csv、rank_map_export.csv"
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="含 Drop.csv、RankMap.csv 的目录（默认 ./data）",
    )
    p.add_argument("--drop-csv-in", type=Path, default=None, help="Drop.csv 输入路径")
    p.add_argument("--rank-csv-in", type=Path, default=None, help="RankMap.csv 输入路径")
    p.add_argument("--drop-csv", type=Path, default=None, help="掉落边 CSV 输出路径")
    p.add_argument("--rank-csv", type=Path, default=None, help="RankMap 导出 CSV 路径")
    p.add_argument(
        "--merge-calculator",
        type=Path,
        default=None,
        help="若指定，在保留 ITEM 等行的前提下用本表 DROP 边重写合并表",
    )
    p.add_argument(
        "--merge-out",
        type=Path,
        default=None,
        help="重写合并表的输出路径（默认：<merge-calculator 文件名>.merged_drop.csv）",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    data_dir = args.data_dir
    if not data_dir.is_dir():
        print(f"错误：目录不存在 {data_dir}", file=sys.stderr)
        return 2
    export_from_data_dir(
        data_dir,
        drop_csv_in=args.drop_csv_in,
        rank_csv_in=args.rank_csv_in,
        drop_csv=args.drop_csv,
        rank_csv=args.rank_csv,
        merge_calculator=args.merge_calculator,
        merge_out=args.merge_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
