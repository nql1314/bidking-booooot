# -*- coding: utf-8 -*-
"""从 ``Drop.csv`` 展开掉落边（调试脚本）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bidking.tools.game_tables import load_drop_edges_from_csv


def main() -> int:
    p = argparse.ArgumentParser(description="读取 Drop.csv 并打印掉落边样例")
    p.add_argument(
        "drop_csv",
        nargs="?",
        type=Path,
        default=Path("data") / "Drop.csv",
        help="Drop.csv 路径（默认 data/Drop.csv）",
    )
    p.add_argument("--search", type=int, default=None, help="仅打印指定 drop_id 的边")
    args = p.parse_args()
    if not args.drop_csv.is_file():
        print(f"未找到 {args.drop_csv}", file=sys.stderr)
        return 2
    edges = load_drop_edges_from_csv(args.drop_csv)
    shown = 0
    for drop_id, ref_id, weight, ref_type in sorted(edges):
        if args.search is not None and drop_id != args.search:
            continue
        print(f"drop_id={drop_id} ref_id={ref_id} weight={weight} ref_type={ref_type}")
        shown += 1
        if args.search is None and shown >= 20:
            print(f"... 共 {len(edges)} 条边（仅显示前 20 条）")
            break
    if shown == 0:
        print("无匹配边")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
