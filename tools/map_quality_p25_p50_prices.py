# -*- coding: utf-8 -*-
"""
按地图根掉落池计算：品质 1–6 的**全部非空子集**组合下的条件分位「件价」「每格价」
（P25 / P50，各 63 组），并附加一行 ``all`` 表示整张掉落池的无条件分位。

逻辑与 ``map_quality_avg_prices.py`` 相同，仅将条件期望改为按掉落权重的加权分位数。

数据依赖（与 bidking.parsing.item_db 一致，默认从仓库 ``data/`` 读取）：
  - data/item_prices.csv
  - data/calculator_data_merged.csv（优先）或 data/drop_table_weights.csv
  - data/物品轮廓爆率推断器.html（可选，用于巢权重等）

用法（在仓库根目录）:
  python tools/map_quality_p25_p50_prices.py
  python tools\\map_quality_p25_p50_prices.py --csv-p25 data\\map_quality_p25_out.csv --csv-p50 data\\map_quality_p50_out.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (SRC, ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from bidking.parsing import item_db  # noqa: E402

DATA_DIR = ROOT / "data"


def shape_cells(shape: int) -> int:
    """ItemSlotType：十位=宽、个位=高，占格 = 宽 * 高。"""
    w, h = shape // 10, shape % 10
    return max(w * h, 1)


def iter_quality_groups() -> list[tuple[str, frozenset[int]]]:
    """品质 1..6 的全部非空子集，按子集大小再按品质编号升序排列。"""
    qs = range(1, 7)
    out: list[tuple[str, frozenset[int]]] = []
    for r in range(1, 7):
        for comb in combinations(qs, r):
            name = "+".join(f"q{c}" for c in comb)
            out.append((name, frozenset(comb)))
    return out


QUALITY_GROUPS: list[tuple[str, frozenset[int]]] = iter_quality_groups()


def map_item_probs(map_id: int) -> dict[int, float]:
    nest = item_db.MAP_TO_TIER_NEST[map_id][1]
    return item_db._resolve_drop_to_items(nest, item_db._KNOWN_ITEM_IDS)


def weighted_percentile(
    pairs: list[tuple[float, float]], quantile: float
) -> float | None:
    """按权重 ``pairs=(value, weight)`` 求分位；``quantile`` 为 0.25 / 0.5 等。"""
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    target = quantile * total
    cum = 0.0
    for val, w in sorted(pairs, key=lambda x: x[0]):
        cum += w
        if cum >= target - 1e-15:
            return val
    return pairs[-1][0]


def agg_percentiles(
    probs: dict[int, float],
    index: dict,
    qset: frozenset[int],
) -> tuple[float, float | None, float | None, float | None, float | None]:
    sp = 0.0
    item_pairs: list[tuple[float, float]] = []
    cell_pairs: list[tuple[float, float]] = []
    for iid, p in probs.items():
        if p <= 0:
            continue
        it = index.get(iid)
        if it is None or it.quality not in qset:
            continue
        c = shape_cells(it.shape)
        sp += p
        item_pairs.append((float(it.base_value), p))
        cell_pairs.append((float(it.base_value) / c, p))
    if sp <= 0:
        return sp, None, None, None, None
    return (
        sp,
        weighted_percentile(item_pairs, 0.25),
        weighted_percentile(item_pairs, 0.50),
        weighted_percentile(cell_pairs, 0.25),
        weighted_percentile(cell_pairs, 0.50),
    )


def build_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    index_path = str(DATA_DIR / "item_prices.csv")
    index, _items = item_db.load_csv(index_path)

    rows_p25: list[dict[str, object]] = []
    rows_p50: list[dict[str, object]] = []

    for map_id in sorted(item_db.MAP_TO_TIER_NEST):
        probs = map_item_probs(map_id)
        tier, nest = item_db.MAP_TO_TIER_NEST[map_id]

        def row_base(gname: str, sp: float) -> dict[str, object]:
            return {
                "map_id": map_id,
                "tier": tier,
                "nest_drop_id": nest,
                "quality_group": gname,
                "prob_in_group": round(sp, 8) if sp > 0 else round(sp, 8),
            }

        for gname, qset in QUALITY_GROUPS:
            sp, p25_item, p50_item, p25_cell, p50_cell = agg_percentiles(
                probs, index, qset
            )
            base = row_base(gname, sp)
            r25 = dict(base)
            r50 = dict(base)
            if sp <= 0:
                r25["p25_price_per_item"] = ""
                r25["p25_price_per_cell"] = ""
                r50["p50_price_per_item"] = ""
                r50["p50_price_per_cell"] = ""
            else:
                r25["p25_price_per_item"] = round(p25_item, 4) if p25_item is not None else ""
                r25["p25_price_per_cell"] = round(p25_cell, 4) if p25_cell is not None else ""
                r50["p50_price_per_item"] = round(p50_item, 4) if p50_item is not None else ""
                r50["p50_price_per_cell"] = round(p50_cell, 4) if p50_cell is not None else ""
            rows_p25.append(r25)
            rows_p50.append(r50)

        # ``all``：不按品质过滤，与均价脚本一致
        sp_all = sum(probs.values())
        item_pairs_all: list[tuple[float, float]] = []
        cell_pairs_all: list[tuple[float, float]] = []
        for iid, p in probs.items():
            if p <= 0 or iid not in index:
                continue
            it = index[iid]
            c = shape_cells(it.shape)
            item_pairs_all.append((float(it.base_value), p))
            cell_pairs_all.append((float(it.base_value) / c, p))

        base_all = row_base("all", sp_all)
        r25_all = dict(base_all)
        r50_all = dict(base_all)
        if sp_all <= 0:
            r25_all["p25_price_per_item"] = ""
            r25_all["p25_price_per_cell"] = ""
            r50_all["p50_price_per_item"] = ""
            r50_all["p50_price_per_cell"] = ""
        else:
            p25_i = weighted_percentile(item_pairs_all, 0.25)
            p50_i = weighted_percentile(item_pairs_all, 0.50)
            p25_c = weighted_percentile(cell_pairs_all, 0.25)
            p50_c = weighted_percentile(cell_pairs_all, 0.50)
            r25_all["p25_price_per_item"] = round(p25_i, 4) if p25_i is not None else ""
            r25_all["p25_price_per_cell"] = round(p25_c, 4) if p25_c is not None else ""
            r50_all["p50_price_per_item"] = round(p50_i, 4) if p50_i is not None else ""
            r50_all["p50_price_per_cell"] = round(p50_c, 4) if p50_c is not None else ""
        rows_p25.append(r25_all)
        rows_p50.append(r50_all)

    return rows_p25, rows_p50


def write_csv(path: Path, keys: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv-p25",
        default=str(DATA_DIR / "map_quality_p25_out.csv"),
        help="P25 结果 CSV（默认 data/map_quality_p25_out.csv）",
    )
    ap.add_argument(
        "--csv-p50",
        default=str(DATA_DIR / "map_quality_p50_out.csv"),
        help="P50 结果 CSV（默认 data/map_quality_p50_out.csv）",
    )
    ap.add_argument(
        "--no-write",
        action="store_true",
        help="不写文件，仅打印样例行",
    )
    args = ap.parse_args()

    rows_p25, rows_p50 = build_rows()

    keys_p25 = [
        "map_id",
        "tier",
        "nest_drop_id",
        "quality_group",
        "prob_in_group",
        "p25_price_per_item",
        "p25_price_per_cell",
    ]
    keys_p50 = [
        "map_id",
        "tier",
        "nest_drop_id",
        "quality_group",
        "prob_in_group",
        "p50_price_per_item",
        "p50_price_per_cell",
    ]

    if args.no_write:
        print("p25 sample:", json.dumps(rows_p25[:6], ensure_ascii=False, indent=2))
        print("p50 sample:", json.dumps(rows_p50[:6], ensure_ascii=False, indent=2))
        print("...", "total rows each", len(rows_p25))
        return 0

    p25_path = Path(args.csv_p25)
    p50_path = Path(args.csv_p50)
    write_csv(p25_path, keys_p25, rows_p25)
    write_csv(p50_path, keys_p50, rows_p50)
    print("wrote", p25_path)
    print("wrote", p50_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
