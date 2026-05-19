# -*- coding: utf-8 -*-
"""
爱莎第四回合鉴影组合分析：基于 item_prices.csv（或带类别列的 CSV）。

模型（与实战一致）：
  - 每回合使用 1 个类别鉴影（常用 3 或 4 件套）；
  - 鉴影显示该类物品的轮廓；未显示则该物品不含此类别（负向约束）；
  - 第四回合已知全部非金红（Q1~Q4），场上未知格仅可能为金红（Q5/Q6）；
  - 结合轮廓 shape + N 位类别命中模式，在金红池内匹配候选。

输出：每种 N 鉴影组合能「唯一确认」的百万物品与高价值物品列表及汇总报表。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

# 与 data/item_prices_category.csv 列名一致；tag 101~110 对应顺序
CATS = ["家居", "医疗", "时尚", "武器", "珠宝", "文玩", "数码", "交通", "饮食", "书籍"]
CAT_TAG = {c: 101 + i for i, c in enumerate(CATS)}
TAG_CAT = {v: k for k, v in CAT_TAG.items()}

MILLION = 1_000_000
HIGH_VALUE = 100_000  # 10 万+，与既有分析口径一致


@dataclass
class ItemRow:
    item_id: str
    name: str
    shape: str
    quality: int
    base_value: int
    cats: tuple[str, ...]


@dataclass
class ComboResult:
    combo: tuple[str, ...]
    # 严格：在金红全池内 shape+模式 唯一（第四回合实战口径）
    unique_million: list[ItemRow] = field(default_factory=list)
    unique_high: list[ItemRow] = field(default_factory=list)
    ambiguous_million: list[tuple[ItemRow, int]] = field(default_factory=list)
    # 宽松：仅在「百万子集」内唯一（同类高价不撞模式时也算；供对照）
    unique_million_relaxed: list[ItemRow] = field(default_factory=list)
    unique_high_relaxed: list[ItemRow] = field(default_factory=list)

    @property
    def million_count(self) -> int:
        return len(self.unique_million)

    @property
    def million_relaxed_count(self) -> int:
        return len(self.unique_million_relaxed)

    @property
    def high_count(self) -> int:
        return len(self.unique_high)

    @property
    def high_relaxed_count(self) -> int:
        return len(self.unique_high_relaxed)


def _decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("无法解码 CSV")


def load_rows_category_csv(path: Path) -> list[ItemRow]:
    text = _decode_csv_bytes(path.read_bytes())
    rows: list[ItemRow] = []
    for r in csv.DictReader(io.StringIO(text)):
        cats = tuple(c for c in CATS if (r.get(c) or "").strip())
        if not cats:
            continue
        rows.append(
            ItemRow(
                item_id=r["item_id"],
                name=r["name"],
                shape=str(r["shape"]).strip(),
                quality=int(r["quality"]),
                base_value=int(float(r["base_value"])),
                cats=cats,
            )
        )
    return rows


def load_rows_prices_csv(path: Path) -> list[ItemRow]:
    text = _decode_csv_bytes(path.read_bytes())
    rows: list[ItemRow] = []
    for r in csv.DictReader(io.StringIO(text)):
        tags_raw = (r.get("category_tags") or "").strip()
        if not tags_raw:
            continue
        if not tags_raw.startswith("["):
            tags_raw = f"[{tags_raw}]"
        tags: list[int] = json.loads(tags_raw)
        cats = tuple(TAG_CAT[t] for t in tags if t in TAG_CAT)
        if not cats:
            continue
        rows.append(
            ItemRow(
                item_id=r["item_id"],
                name=r["name"],
                shape=str(r["shape"]).strip(),
                quality=int(r["quality"]),
                base_value=int(float(r["base_value"])),
                cats=cats,
            )
        )
    return rows


def load_rows(path: Path) -> list[ItemRow]:
    text_sample = path.read_bytes()[:4096].decode("utf-8-sig", errors="replace")
    if "category_tags" in text_sample.split("\n", 1)[0]:
        return load_rows_prices_csv(path)
    return load_rows_category_csv(path)


def cat_set_key(cats: tuple[str, ...]) -> str:
    return "+".join(sorted(cats))


def pattern_bits(item: ItemRow, scanned: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(1 if c in item.cats else 0 for c in scanned)


def pattern_key(item: ItemRow, scanned: tuple[str, ...]) -> tuple[str, tuple[int, ...]]:
    return (item.shape, pattern_bits(item, scanned))


def bits_str(bits: tuple[int, ...]) -> str:
    return "".join(str(b) for b in bits)


def bucket_pool(pool: list[ItemRow], scanned: tuple[str, ...]) -> dict[tuple[str, tuple[int, ...]], list[ItemRow]]:
    buckets: dict[tuple[str, tuple[int, ...]], list[ItemRow]] = defaultdict(list)
    for r in pool:
        buckets[pattern_key(r, scanned)].append(r)
    return buckets


def analyze_combo(
    pool: list[ItemRow],
    million_pool: list[ItemRow],
    high_pool: list[ItemRow],
    combo: tuple[str, ...],
) -> ComboResult:
    buckets = bucket_pool(pool, combo)
    hi_buckets = bucket_pool(million_pool, combo)
    hv_buckets = bucket_pool(high_pool, combo)
    res = ComboResult(combo=combo)

    for r in million_pool:
        key = pattern_key(r, combo)
        mates = buckets[key]
        if len(mates) == 1:
            res.unique_million.append(r)
        else:
            res.ambiguous_million.append((r, len(mates)))
        if len(hi_buckets[key]) == 1:
            res.unique_million_relaxed.append(r)

    for r in high_pool:
        key = pattern_key(r, combo)
        if len(buckets[key]) == 1:
            res.unique_high.append(r)
        if len(hv_buckets[key]) == 1:
            res.unique_high_relaxed.append(r)

    res.unique_million.sort(key=lambda x: (-x.base_value, x.name))
    res.unique_high.sort(key=lambda x: (-x.base_value, x.name))
    res.unique_million_relaxed.sort(key=lambda x: (-x.base_value, x.name))
    res.unique_high_relaxed.sort(key=lambda x: (-x.base_value, x.name))
    res.ambiguous_million.sort(key=lambda x: (-x[0].base_value, x[0].name))
    return res


def format_item(r: ItemRow, combo: tuple[str, ...] | None = None) -> str:
    pat = ""
    if combo is not None:
        pat = f" pat={bits_str(pattern_bits(r, combo))}"
    return (
        f"{r.name} | {r.base_value:,} | Q{r.quality} | shape={r.shape} "
        f"| [{cat_set_key(r.cats)}]{pat}"
    )


def build_report(
    all_rows: list[ItemRow],
    *,
    combo_size: int = 4,
    min_million_unique: int = 1,
) -> tuple[str, list[ComboResult]]:
    if combo_size < 1 or combo_size > len(CATS):
        raise ValueError(f"combo_size 须在 1~{len(CATS)} 之间，收到 {combo_size}")

    gold_red = [r for r in all_rows if r.quality in (5, 6)]
    gr_million = [r for r in gold_red if r.base_value >= MILLION]
    gr_high = [r for r in gold_red if r.base_value >= HIGH_VALUE]
    total_combo_count = len(list(combinations(CATS, combo_size)))

    all_combos: list[ComboResult] = []
    for combo in combinations(CATS, combo_size):
        cr = analyze_combo(gold_red, gr_million, gr_high, combo)
        if cr.million_count >= min_million_unique:
            all_combos.append(cr)

    all_combos.sort(
        key=lambda x: (
            -x.million_count,
            -x.high_count,
            -x.million_relaxed_count,
            ",".join(x.combo),
        )
    )

    lines: list[str] = []
    w = lines.append

    w("=" * 72)
    w(f"爱莎 R4 鉴影{combo_size}件套组合分析报告")
    w("=" * 72)
    w(f"数据源物品总数: {len(all_rows)}")
    w(f"金红(Q5/Q6)池: {len(gold_red)}")
    w(f"金红百万(>={MILLION:,}): {len(gr_million)}")
    w(f"金红高价值(>={HIGH_VALUE:,}): {len(gr_high)}")
    w("")
    w(f"判定规则: 轮廓 shape + {combo_size} 次鉴影正/负向类别约束；")
    w("  [严格] 在金红(Q5/Q6)全池匹配，候选数=1 → 第四回合可唯一确认该格物品；")
    w("  [宽松] 仅在百万/高价值子集内匹配（低价同模式不计入），供对照旧分析口径。")
    w("")

    w("--- 金红百万物品一览 ---")
    for r in sorted(gr_million, key=lambda x: (-x.base_value, x.name)):
        w(f"  {format_item(r)}")
    w("")

    dup_sig: dict[tuple[str, tuple[str, ...]], list[ItemRow]] = defaultdict(list)
    for r in gr_million:
        dup_sig[(r.shape, r.cats)].append(r)
    hard = {k: v for k, v in dup_sig.items() if len(v) > 1}
    if hard:
        w(f"--- 同轮廓+同类别集的金红百万（{combo_size} 鉴影无法仅靠模式拆分）---")
        for k, v in sorted(hard.items(), key=lambda x: -max(i.base_value for i in x[1])):
            w(f"  shape={k[0]} [{cat_set_key(k[1])}]")
            for r in sorted(v, key=lambda x: -x.base_value):
                w(f"    {r.name} {r.base_value:,}")
        w("")

    qualifying = len(all_combos)
    w(
        f"--- 满足「至少唯一确认 {min_million_unique} 种百万物品」的 "
        f"{combo_size} 鉴影组合: {qualifying} / {total_combo_count} ---"
    )
    w("")

    w("--- 组合排行 [严格口径]（百万唯一数 ↓，高价值唯一数 ↓）---")
    w(
        f"{'排名':>4}  {'百万':>4}  {'高价值':>6}  {'百万*':>5}  "
        f"鉴影{combo_size}件套  (*=宽松)"
    )
    for i, cr in enumerate(all_combos[:30], 1):
        w(
            f"{i:4d}  {cr.million_count:4d}  {cr.high_count:6d}  "
            f"{cr.million_relaxed_count:5d}  {', '.join(cr.combo)}"
        )
    if len(all_combos) > 30:
        w(f"  ... 另有 {len(all_combos) - 30} 组，详见下方明细")
    w("")

    w("=" * 72)
    w("各组合明细")
    w("=" * 72)

    for idx, cr in enumerate(all_combos, 1):
        w("")
        w(f"[{idx}] 鉴影: {', '.join(cr.combo)}  (tag: {', '.join(str(CAT_TAG[c]) for c in cr.combo)})")
        w(
            f"     [严格] 唯一百万: {cr.million_count}/{len(gr_million)}  |  "
            f"唯一高价值: {cr.high_count}/{len(gr_high)}"
        )
        w(
            f"     [宽松] 唯一百万: {cr.million_relaxed_count}/{len(gr_million)}  |  "
            f"唯一高价值: {cr.high_relaxed_count}/{len(gr_high)}"
        )
        w("     --- [严格] 可唯一确认的百万物品 ---")
        if cr.unique_million:
            for r in cr.unique_million:
                w(f"       [OK] {format_item(r, cr.combo)}")
        else:
            w("       (无)")
        only_relaxed = [
            r
            for r in cr.unique_million_relaxed
            if r not in cr.unique_million
        ]
        if only_relaxed:
            w("     --- [宽松] 仅子集内唯一、全池仍歧义的百万 ---")
            for r in only_relaxed:
                w(f"       ~ {format_item(r, cr.combo)}")
        w("     --- [严格] 可唯一确认的高价值物品（非百万部分）---")
        extra_high = [r for r in cr.unique_high if r.base_value < MILLION]
        if extra_high:
            for r in extra_high[:40]:
                w(f"       + {format_item(r, cr.combo)}")
            if len(extra_high) > 40:
                w(f"       ... 另有 {len(extra_high) - 40} 件")
        elif not cr.unique_million:
            w("       (无)")
        if cr.ambiguous_million:
            w("     --- 仍歧义的百万物品（同模式候选数）---")
            for r, n in cr.ambiguous_million:
                w(f"       ? {r.name} {r.base_value:,} 歧义×{n}  {format_item(r, cr.combo)}")

    w("")
    w("=" * 72)
    w("推荐摘要")
    w("=" * 72)
    if all_combos:
        best = all_combos[0]
        w(
            f"[严格] 百万覆盖最多: {', '.join(best.combo)} "
            f"→ {best.million_count} 种"
        )
        best_relaxed = max(all_combos, key=lambda x: x.million_relaxed_count)
        w(
            f"[宽松] 百万覆盖最多: {', '.join(best_relaxed.combo)} "
            f"→ {best_relaxed.million_relaxed_count} 种"
        )
        best_hi = max(all_combos, key=lambda x: x.high_count)
        if best_hi.combo != best.combo:
            w(
                f"[严格] 高价值覆盖最多: {', '.join(best_hi.combo)} "
                f"→ {best_hi.high_count} 种 >=10万"
            )
        full_million = [cr for cr in all_combos if cr.million_count == len(gr_million)]
        w(f"[严格] 能唯一确认全部 {len(gr_million)} 种百万的组合数: {len(full_million)}")
        if not full_million:
            w("  → 不存在；需结合已知非金红格、空格子数、同类低价已排除等辅助信息。")
    w("")
    return "\n".join(lines), all_combos


def write_combo_csv(path: Path, results: list[ComboResult]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "combo",
                "million_strict",
                "high_strict",
                "million_relaxed",
                "high_relaxed",
                "million_items_strict",
                "million_items_relaxed_only",
                "high_value_extra_strict",
            ]
        )
        for cr in results:
            million_names = ";".join(f"{r.name}({r.base_value})" for r in cr.unique_million)
            relaxed_only = [r for r in cr.unique_million_relaxed if r not in cr.unique_million]
            relaxed_names = ";".join(f"{r.name}({r.base_value})" for r in relaxed_only)
            extra = [r for r in cr.unique_high if r.base_value < MILLION]
            high_names = ";".join(f"{r.name}({r.base_value})" for r in extra[:50])
            w.writerow(
                [
                    "+".join(cr.combo),
                    cr.million_count,
                    cr.high_count,
                    cr.million_relaxed_count,
                    cr.high_relaxed_count,
                    million_names,
                    relaxed_names,
                    high_names,
                ]
            )


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="爱莎 R4 鉴影 N 件套组合分析报表")
    parser.add_argument(
        "-n",
        "--combo-size",
        type=int,
        default=4,
        choices=range(1, len(CATS) + 1),
        metavar="N",
        help="鉴影类别数量（默认 4；传 3 生成三件套报表）",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=root / "data" / "item_prices.csv",
        help="物品表 CSV（item_prices.csv 或 item_prices_category.csv）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="文本报表路径（默认 tools/jianying_combo_report_{N}.txt）",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="组合汇总 CSV（默认 tools/jianying_combo_report_{N}.csv）",
    )
    parser.add_argument(
        "--min-million",
        type=int,
        default=1,
        help="至少能唯一确认的百万物品种数（过滤组合）",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="不打印报表到控制台（仅写文件）",
    )
    args = parser.parse_args(argv)

    if args.output is None:
        if args.combo_size == 4:
            args.output = root / "tools" / "jianying_combo_report.txt"
        else:
            args.output = root / "tools" / f"jianying_combo_report_{args.combo_size}.txt"
    if args.csv_out is None:
        if args.combo_size == 4:
            args.csv_out = root / "tools" / "jianying_combo_report.csv"
        else:
            args.csv_out = root / "tools" / f"jianying_combo_report_{args.combo_size}.csv"

    if not args.csv.is_file():
        alt = root / "data" / "item_prices_category.csv"
        if alt.is_file():
            args.csv = alt
        else:
            print(f"找不到 CSV: {args.csv}", file=sys.stderr)
            return 1

    rows = load_rows(args.csv)
    report, results = build_report(
        rows,
        combo_size=args.combo_size,
        min_million_unique=args.min_million,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    write_combo_csv(args.csv_out, results)

    if not args.quiet:
        print(report)
    print(f"\n已写入: {args.output}")
    print(f"已写入: {args.csv_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
