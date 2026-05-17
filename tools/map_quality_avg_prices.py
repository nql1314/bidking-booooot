# -*- coding: utf-8 -*-
"""
按地图根掉落池计算：品质 1–6 的**全部非空子集**组合下的条件期望「件均价」「每格均价」
（共 63 组），并附加一行 ``all`` 表示整张掉落池的无条件期望。

数据依赖（与 bidking.parsing.item_db 一致，默认从仓库 ``data/`` 读取）：
  - data/item_prices.csv
  - data/calculator_data_merged.csv（优先）或 data/drop_table_weights.csv
  - data/物品轮廓爆率推断器.html（可选，用于巢权重等）

用法（在仓库根目录）:
  python tools/map_quality_avg_prices.py
  python tools\\map_quality_avg_prices.py --csv data\\map_quality_avg_out.csv
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="写入结果 CSV 路径")
    args = ap.parse_args()

    index_path = str(DATA_DIR / "item_prices.csv")
    index, _items = item_db.load_csv(index_path)

    rows: list[dict[str, object]] = []
    for map_id in sorted(item_db.MAP_TO_TIER_NEST):
        probs = map_item_probs(map_id)
        tier, nest = item_db.MAP_TO_TIER_NEST[map_id]

        def agg(qset: frozenset[int]) -> tuple[float, float, float]:
            spv = spc = sp = 0.0
            for iid, p in probs.items():
                if p <= 0:
                    continue
                it = index.get(iid)
                if it is None or it.quality not in qset:
                    continue
                c = shape_cells(it.shape)
                sp += p
                spv += p * it.base_value
                spc += p * c
            return sp, spv, spc

        for gname, qset in QUALITY_GROUPS:
            sp, spv, spc = agg(qset)
            row: dict[str, object] = {
                "map_id": map_id,
                "tier": tier,
                "nest_drop_id": nest,
                "quality_group": gname,
                "prob_in_group": round(sp, 8),
            }
            if sp <= 0:
                row["avg_price_per_item"] = ""
                row["avg_price_per_cell"] = ""
            else:
                row["avg_price_per_item"] = round(spv / sp, 4)
                row["avg_price_per_cell"] = round(spv / spc, 4) if spc > 0 else ""
            rows.append(row)

        sp_all = sum(probs.values())
        spv_all = sum(probs[i] * index[i].base_value for i in probs if i in index)
        spc_all = sum(
            probs[i] * shape_cells(index[i].shape) for i in probs if i in index
        )
        rows.append(
            {
                "map_id": map_id,
                "tier": tier,
                "nest_drop_id": nest,
                "quality_group": "all",
                "prob_in_group": round(sp_all, 8),
                "avg_price_per_item": round(spv_all / sp_all, 4) if sp_all > 0 else "",
                "avg_price_per_cell": round(spv_all / spc_all, 4)
                if sp_all > 0 and spc_all > 0
                else "",
            }
        )

    keys = [
        "map_id",
        "tier",
        "nest_drop_id",
        "quality_group",
        "prob_in_group",
        "avg_price_per_item",
        "avg_price_per_cell",
    ]
    if args.csv:
        outp = Path(args.csv)
        outp.parent.mkdir(parents=True, exist_ok=True)
        with outp.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in keys})
        print("wrote", outp)
    else:
        print(json.dumps(rows[:12], ensure_ascii=False, indent=2))
        print("...", "total rows", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
