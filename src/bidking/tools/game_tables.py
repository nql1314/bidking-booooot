# -*- coding: utf-8 -*-
"""
从 Unity ``StreamingAssets/Tables`` 风格的 ``Drop.txt`` / ``RankMap.txt`` 解码并导出 CSV。

表体常为整文件 Base64，解码后为 UTF-8、Tab 分隔的明文。``Drop`` 每行第 5 列为
``[[ref_type, ref_id, …, weight], …]`` 形式的 Python 字面量列表，可展开为
``drop_table_weights.csv`` 四列；``RankMap`` 每行 7 列，导出为便于查阅的 CSV。
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import csv
import re
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

_B64_LINE = re.compile(rb"^[A-Za-z0-9+/=\s]+$")


def decode_if_base64(raw: bytes) -> str:
    """
    若整段为 Base64（常见：单行、仅空白换行），则解码为 UTF-8 文本；
    否则按 UTF-8 原样解码（已是明文表时）。
    """
    stripped = raw.strip()
    if not stripped:
        return ""
    if not _B64_LINE.match(stripped):
        return raw.decode("utf-8-sig", errors="replace")
    compact = re.sub(rb"\s+", b"", stripped)
    try:
        decoded = base64.b64decode(compact, validate=False)
    except (binascii.Error, ValueError):
        return raw.decode("utf-8-sig", errors="replace")
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return decoded.decode("utf-8", errors="replace")


def parse_drop_edges(decoded: str) -> List[Tuple[int, int, int, int]]:
    """解析解码后的 ``Drop`` 明文，返回 ``(drop_id, ref_id, weight, ref_type)`` 列表。"""
    edges: List[Tuple[int, int, int, int]] = []
    for raw_line in decoded.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        try:
            drop_id = int(parts[0].strip())
        except ValueError:
            continue
        try:
            refs = ast.literal_eval(parts[-1].strip())
        except (SyntaxError, ValueError):
            continue
        if not isinstance(refs, list):
            continue
        for entry in refs:
            if not isinstance(entry, (list, tuple)) or len(entry) != 5:
                continue
            ref_type, ref_id, _a, _b, weight = entry
            try:
                edges.append((drop_id, int(ref_id), int(weight), int(ref_type)))
            except (TypeError, ValueError):
                continue
    return edges


def parse_rank_map_rows(decoded: str) -> List[List[str]]:
    """解析解码后的 ``RankMap`` 明文，每行 7 列 Tab 字段，原样保留为字符串。"""
    rows: List[List[str]] = []
    for raw_line in decoded.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            # 仍写入，避免静默丢行；列数不足时右侧补空
            parts = parts + [""] * (7 - len(parts))
        rows.append(parts[:7])
    return rows


def write_drop_table_weights_csv(
    path: Path, edges: Sequence[Tuple[int, int, int, int]]
) -> None:
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
    edges: Sequence[Tuple[int, int, int, int]],
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
    write_decoded: bool = False,
    drop_csv: Path | None = None,
    rank_csv: Path | None = None,
    merge_calculator: Path | None = None,
    merge_out: Path | None = None,
) -> None:
    drop_path = data_dir / "Drop.txt"
    rank_path = data_dir / "RankMap.txt"
    edges: List[Tuple[int, int, int, int]] | None = None

    if drop_path.is_file():
        raw = drop_path.read_bytes()
        decoded = decode_if_base64(raw)
        if write_decoded:
            (data_dir / "Drop.decoded.tsv").write_text(decoded, encoding="utf-8")
        edges = parse_drop_edges(decoded)
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
        print(f"跳过 Drop：未找到 {drop_path}", file=sys.stderr)

    if rank_path.is_file():
        raw = rank_path.read_bytes()
        decoded = decode_if_base64(raw)
        if write_decoded:
            (data_dir / "RankMap.decoded.tsv").write_text(decoded, encoding="utf-8")
        rows = parse_rank_map_rows(decoded)
        out_rank = rank_csv or (data_dir / "rank_map_export.csv")
        write_rank_map_csv(out_rank, rows)
        print(f"已写入 {out_rank}（{len(rows)} 行）", file=sys.stderr)
    else:
        print(f"跳过 RankMap：未找到 {rank_path}", file=sys.stderr)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="解码 Drop.txt / RankMap.txt 并导出 drop_table_weights.csv、rank_map_export.csv"
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="含 Drop.txt、RankMap.txt 的目录（默认 ./data）",
    )
    p.add_argument(
        "--write-decoded",
        action="store_true",
        help="在同目录写入 Drop.decoded.tsv / RankMap.decoded.tsv 明文副本",
    )
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
        write_decoded=args.write_decoded,
        drop_csv=args.drop_csv,
        rank_csv=args.rank_csv,
        merge_calculator=args.merge_calculator,
        merge_out=args.merge_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
