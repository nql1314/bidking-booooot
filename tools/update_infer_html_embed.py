# -*- coding: utf-8 -*-
"""
重算 ``data/物品轮廓爆率推断器.html`` 内的 ``NEST_W``、``SUBMAP_PRIOR_MULT``，
可选同步 ``EMBED_CSV.item``（来自 ``item_prices.csv``）。

算法与 HTML 说明一致：
  - NEST_W[nest]：该巢穴根 drop 池在品质 1..6 下的条件期望件均价
  - SUBMAP_PRIOR_MULT[tier][map_id][item_id]：
    子图巢穴池内物品归一化份额 ÷ 同档基础子图（2101–2107 等）均值

依赖（默认 ``data/``）：
  - item_prices.csv
  - calculator_data_merged.csv
  - 物品轮廓爆率推断器.html（读 SUBMAPS_BY_TIER 可选；未解析时用 item_db 规则）

用法（仓库根目录）:
  python tools\\update_infer_html_embed.py
  python tools\\update_infer_html_embed.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (SRC, ROOT):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from bidking.parsing import item_db  # noqa: E402

DATA_DIR = ROOT / "data"
DEFAULT_HTML = DATA_DIR / "物品轮廓爆率推断器.html"
DEFAULT_ITEMS = DATA_DIR / "item_prices.csv"
GRID_SIZE = "[10,5]"


def _tier_base_submap_ids(tier: int) -> List[int]:
    """与 HTML ``SUBMAPS_BY_TIER`` 对齐：每档仅 21xx–25xx 末两位 01–10 的基础子图。"""
    tier_digit = tier - 100 + 20
    prefix = tier_digit * 100
    out: List[int] = []
    for mid, (t, _nest) in item_db.MAP_TO_TIER_NEST.items():
        if t != tier:
            continue
        slot = mid % 100
        if mid // 100 != tier_digit or slot < 1 or slot > 10:
            continue
        out.append(mid)
    return sorted(out)


def _collect_nest_ids() -> Set[int]:
    nests: Set[int] = set()
    for _mid, (_tier, nest) in item_db.MAP_TO_TIER_NEST.items():
        nests.add(nest)
    return nests


def compute_nest_w(index: Dict[int, object], known_ids: Set[int]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for nest in sorted(_collect_nest_ids()):
        probs = item_db._resolve_drop_to_items(nest, known_ids)
        row: List[float] = []
        for quality in range(1, 7):
            sp = spv = 0.0
            for iid, p in probs.items():
                if p <= 0:
                    continue
                it = index.get(iid)
                if it is None or it.quality != quality:
                    continue
                sp += p
                spv += p * it.base_value
            row.append(round(spv / sp, 2) if sp > 0 else 0.0)
        out[str(nest)] = row
    return out


def compute_submap_prior_mult(
    index: Dict[int, object], known_ids: Set[int]
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for tier in range(101, 106):
        map_ids = _tier_base_submap_ids(tier)
        if not map_ids:
            continue
        probs_by_map: Dict[int, Dict[int, float]] = {}
        for mid in map_ids:
            nest = item_db.MAP_TO_TIER_NEST[mid][1]
            probs_by_map[mid] = item_db._resolve_drop_to_items(nest, known_ids)

        all_items: Set[int] = set()
        for probs in probs_by_map.values():
            all_items.update(iid for iid, p in probs.items() if p > 0)

        mean_share: Dict[int, float] = {}
        n_maps = len(map_ids)
        for iid in all_items:
            mean_share[iid] = sum(probs_by_map[mid].get(iid, 0.0) for mid in map_ids) / n_maps

        tier_key = str(tier)
        out[tier_key] = {}
        for mid in map_ids:
            item_mult: Dict[str, float] = {}
            for iid in all_items:
                share = probs_by_map[mid].get(iid, 0.0)
                denom = mean_share[iid]
                if share > 0 and denom > 0:
                    item_mult[str(iid)] = round(share / denom, 6)
            out[tier_key][str(mid)] = item_mult
    return out


def item_prices_to_embed_csv(path: Path) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        ["item_id", "name", "category_tags", "shape", "quality", "base_value", "grid_size"]
    )
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            w.writerow(
                [
                    row["item_id"],
                    row["name"],
                    row["category_tags"],
                    row["shape"],
                    row["quality"],
                    row["base_value"],
                    row.get("grid_size") or GRID_SIZE,
                ]
            )
    return buf.getvalue()


def _json_compact(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def patch_html(
    html_path: Path,
    *,
    nest_w: Dict[str, List[float]],
    submap_mult: Dict[str, Dict[str, Dict[str, float]]],
    embed_item_csv: str | None,
) -> str:
    text = html_path.read_text(encoding="utf-8")
    text, n1 = re.subn(
        r"const\s+NEST_W\s*=\s*\{.*?\};",
        f"const NEST_W = {_json_compact(nest_w)};",
        text,
        count=1,
        flags=re.S,
    )
    text, n2 = re.subn(
        r"const\s+SUBMAP_PRIOR_MULT\s*=\s*\{.*?\};\s*(?=const\s+SUBMAPS_BY_TIER)",
        f"const SUBMAP_PRIOR_MULT = {_json_compact(submap_mult)};\n    ",
        text,
        count=1,
        flags=re.S,
    )
    if n1 != 1 or n2 != 1:
        raise ValueError(f"HTML 替换失败: NEST_W={n1}, SUBMAP_PRIOR_MULT={n2}")

    if embed_item_csv is not None:
        rate_match = re.search(
            r'(const\s+EMBED_CSV\s*=\s*\{"item":\s*")(.*?)("\s*,\s*"rate":\s*")',
            text,
            re.S,
        )
        if not rate_match:
            raise ValueError("未找到 EMBED_CSV.item 锚点")
        escaped = json.dumps(embed_item_csv, ensure_ascii=False)[1:-1]
        text = (
            text[: rate_match.start(2)]
            + escaped
            + text[rate_match.end(2) :]
        )
    return text


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="重算推断器 HTML 内 NEST_W / SUBMAP_PRIOR_MULT")
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--items", type=Path, default=DEFAULT_ITEMS)
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写 HTML")
    ap.add_argument(
        "--sync-embed-item",
        action="store_true",
        help="同时用 item_prices.csv 覆盖 EMBED_CSV.item",
    )
    args = ap.parse_args(argv)

    if not args.items.is_file():
        print(f"错误：未找到 {args.items}", file=sys.stderr)
        return 2
    if not args.html.is_file():
        print(f"错误：未找到 {args.html}", file=sys.stderr)
        return 2

    index, _items = item_db.load_csv(str(args.items))
    item_db.load_drop_weights(str(DATA_DIR / item_db.MERGED_DATA_CSV))

    known_ids = set(index.keys())
    nest_w = compute_nest_w(index, known_ids)
    submap_mult = compute_submap_prior_mult(index, known_ids)
    embed_csv = item_prices_to_embed_csv(args.items) if args.sync_embed_item else None

    n_nest = len(nest_w)
    n_mult = sum(len(m) for t in submap_mult.values() for m in t.values())
    print(f"NEST_W: {n_nest} 个巢穴", file=sys.stderr)
    print(f"SUBMAP_PRIOR_MULT: {len(submap_mult)} 档, {n_mult} 条物品倍率", file=sys.stderr)

    if args.dry_run:
        print("NEST_W[2001] =", nest_w.get("2001"), file=sys.stderr)
        print(
            "SUBMAP_PRIOR_MULT[101][2101][1011001] =",
            submap_mult.get("101", {}).get("2101", {}).get("1011001"),
            file=sys.stderr,
        )
        return 0

    new_html = patch_html(
        args.html,
        nest_w=nest_w,
        submap_mult=submap_mult,
        embed_item_csv=embed_csv,
    )
    args.html.write_text(new_html, encoding="utf-8")
    print(f"已写入 {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
