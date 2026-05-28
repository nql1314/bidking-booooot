# 幽灵格（品质未知）定价规则 — 草案

> **状态**：**一期已实现**（§5.2 tier 分摊 + `pricing.phantom_unknown_quality`）；`total` 维持 as-is。详见 `board_snapshot_pricing.md` 与 `strategy.common.phantom_unknown_tier_credit_q456`。  
> **前置**：「品质已知 / 已确认」幽灵格已与画板 `phantom_quality_pref` / `excluded_qualities` 对齐（见 `grid_overlay_item_merge` 单测与 `test_phantom_known_q6_in_pricing_total_and_tier_footprint`）。

---

## 1. 术语与范围

| 概念 | 判定（合并表 `merged_items_dict` 之后） |
|------|----------------------------------------|
| **幽灵行** | `uid` 存在于 `grid_overlay.phantom_items`（含手画 `phantom_*`、`phantom_vac_*`） |
| **品质已知幽灵** | `quality ∈ {1..6}`（显式 `phantom_quality_pref`、缺省 Q5、自动填充唯一品质、`manual_confirm` 投影等） |
| **品质未知幽灵** | 幽灵行且 `quality is None` |
| **金/红候选幽灵** | 品质未知幽灵，且有效候选档位 ⊆ `{5, 6}`（见 §3.1） |

本草案只处理 **品质未知幽灵**；已知档位的规则仍以 `board_snapshot_pricing.md` 第一～八节为准。

**典型来源**

- 手画幽灵 + `phantom_quality_pref = "_phantom_q_infer"`（推断笔）；
- 手画幽灵无偏好键，但扫描/普查使 `5 ∈ excluded_qualities`（无法缺省金笔，与画板 `_phantom_effective_quality` 为 `None` 一致）；
- 自动 `phantom_vac_*`：矩形候选在 CSV 中对应 **多个品质**（`VacantRectPhantomSpec.quality is None`），偏好写入 `_phantom_q_infer`。

**使用场景（手画）**

- 手画幽灵通常在 **爱莎局且 Q1–Q4 低阶轮廓已齐** 后才会落笔；此时扫描负向 / `excluded_qualities` 往往已排除低阶，行上 `query_item(shape, quality=None, excluded_*)` 的候选集在实践中以 **金/红（及已扫档）** 为主。
- 因此 **不宜把「Q1–Q4 同外形低价候选拉低 `total`」当作手画幽灵的主矛盾**；一期实现可 **维持现有 `_item_value` 计入 `total`**，把改动重心放在 `tier_extra`（§5.2）。

**不在此草案内**

- 日志物品 `quality is None`（无 `phantom_items`）— 已有扫描负向 + `unknown_contour`（无 `shape`）路径；
- 品质已知幽灵（含缺省 Q5、显式 Q6、自动唯一品质、精确 `manual_confirm_item_id`）。

---

## 2. 现状（as-is）

对 **有 `shape`（含 `manual_shapes` / `infer_shapes`）且 `quality is None`** 的幽灵行，`compute_items_total` → `_item_value` 行为为：

```text
query_item(shape=sh, quality=None, excluded_*=行上字段)
→ 在「所有未排除品质 × 该外形」的 CSV 候选上做权重期望价（_weighted_est_price）
```

并行效应：

| 维度 | 现状 | 问题 / 备注 |
|------|------|-------------|
| **`pricing.total`** | 计入上述权重价（`quality=None` + 行上 `excluded_*`） | 手画场景下低阶轮廓已出，**一般可不单独改 `total` 口径**（见 §1 使用场景）。实验室快照若未带扫描负向，全档混合价可能偏低，属数据不完整而非手画常态。 |
| **`vacant` / 占格** | `box_id_confirmed` + `shape` → 进入 `occupied`，减少几何空置 | ✅ 合理 |
| **`confirmed_q5/q6`（tier_extra）** | 仅统计 `quality ∈ {4,5,6}` 且有 `shape` 的行 | 未知幽灵 **不计入** 已确认占位 → `q*_grid_min` 可能 **多补 tier_extra** → **一期必改** |
| **`unknown_contour_vacant_weighted_excess`** | 要求 **无 `shape`** | 有外形的未知幽灵 **不走** 此路径 |
| **主价 `points*`** | 仅由 `vacant_adj` 与 `u_early` / `u_orange` / `u_red` 决定 | 未知幽灵不直接改单价，主要通过 **`tier_extra`**（及现有 `total`）间接影响 `vacant_pts_base` / `vacant_adj` |

---

## 3. 设计原则

1. **与画板一致**：候选集合、负向约束与 `GridWindow` / `apply_scan_history_to_phantom_items` / `census_absent_qualities` 同源（快照里的 `excluded_qualities` / `excluded_categories`）。
2. **不重复计价**：已知档沿用「价在 `total`、超额格抵扣 `tier_extra`」；未知幽灵有 `shape` 时 **tier 分摊** 与 `unknown_contour` 互斥（§5.2）。
3. **一期重心在 `tier_extra`**：手画未知幽灵多为金/红候选；`total` 可继续用现有 `_item_value`（依赖行上排除集），**tier 占位**则在 `C_gr = {5,6} \ excluded` 上分摊。
4. **可观测**：新增 `pricing` 子结构记录每只未知幽灵的 `C_gr`、占位分摊（及可选的现有 `total` 贡献），便于 UI 对照与回归。

---

## 4. 判定：哪些是「品质未知幽灵」

在 `merged_items_dict_from_snapshot` 完成之后，对每行 `uid`：

```text
is_phantom_row(uid)     ⇔ uid ∈ keys(grid_overlay.phantom_items)
is_unknown_quality(it)  ⇔ it.quality is None
is_unknown_phantom      ⇔ is_phantom_row ∧ is_unknown_quality ∧ valid box_id
```

可选：排除已锁价行（`item_cid` + `price` 已由 `manual_confirm` 写入）— 此类应走 **已知** 路径，不再视为未知。

**金/红候选有效档位集合**（用于限价与 tier 分摊）：

```text
C_gr(it) = {5, 6} \ excluded_qualities(it)
```

| \|C_gr\| | 语义 | 建议归类 |
|----------|------|----------|
| 2 | 金、红皆可能 | **金/红候选未知**（本草案核心） |
| 1 | 仅金或仅红 | **退化为品质已知**（§5.3） |
| 0 | 普查/扫描已排除金红 | **无法计价**；`total` 贡献 0；tier 不分摊（与画板 neutral 一致） |

---

## 5. 提议规则

### 5.1 物品价 `total`（一期：维持现状）

**手画 / 常规快照（推荐）**

- 品质未知幽灵仍走现有 `compute_items_total` → `_item_value(shape, quality=None, excluded_*=行上字段)`。
- 爱莎局 Q1–Q4 轮廓已出后，行上 `excluded_qualities` / 扫描负向通常已收窄候选，**无需为「剔除 Q1–Q4 同外形」单独加分支**。
- `manual_confirm_item_id` 唯一投影 → 仍走已知路径精确价。

**可选增强（二期或仅 `phantom_vac_*`）**

若将来需要在 **无扫描负向的测试快照** 或自动矩形幽灵上强制「仅金/红候选权重」，可引入：

```text
v_phantom_gr = weighted_est_price(候选 c：c.shape 匹配且 c.quality ∈ C_gr)
```

并仅在该子集上归一化权重。手画生产路径 **不依赖** 此增强。

### 5.2 档位最少格 `tier_extra`（按候选分摊占位）— 一期必做

对 **品质未知幽灵** 且 `shape` 有几何 footprint `cells = w×h`：

```text
对每个 q ∈ C_gr（若 |C_gr|=2）：
  phantom_tier_credit[q] += cells / |C_gr|
```

在现有 `tier_min_extra_value_and_cells` 中：

```text
confirmed_q5' = confirmed_q5 + round(phantom_tier_credit[5])
confirmed_q6' = confirmed_q6 + round(phantom_tier_credit[6])
need_q = max(0, q*_grid_min − confirmed_q*')
…（其后与现公式相同）
```

说明：

- **均匀分摊**：金/红各分一半格数，避免 `grid_min` 因未知幽灵完全未扣而高估补价。
- 若 \|C_gr\| = 1（§5.3），`cells` 全额计入该档。
- 与 `unknown_contour`（无 shape）的 `uc_q` 抵扣 **互斥**：有 `shape` 的幽灵只走 `phantom_tier_credit`，不走 `unknown_contour_vacant_weighted_excess`。

### 5.3 退化为「品质已知」

| 条件 | 处理 |
|------|------|
| \|C_gr\| = 1 | 合并表可 **虚拟写入** `quality = 唯一元素`（仅定价管线，不改快照），或 tier/total 按该档单行计算 |
| 自动 `phantom_vac_*` 且 `VacantRectPhantomSpec.quality` 非空 | 已有：写入 `phantom_quality_pref` 或 JSON `quality` → **已知路径** |
| `manual_confirm_item_id` 唯一 | **已知路径**（精确价 + 外形） |
| 无偏好键且 `5 ∉ excluded` | 缺省 Q5 → **已知路径**（已实现） |

### 5.4 几何空置 `vacant` / `vacant_adj`

**维持现状**：未知幽灵只要 `box_id_confirmed` 且有 `shape`，仍占 `occupied`，减少 `vacant`；`vacant_adj = vacant − tier_extra_cells` 在 §5.2 更新 `tier_extra_cells` 后自动联动。

不在 `vacant_adj` 上单独做 kcw 或二次扣减。

### 5.5 主价 `points` / `points_floor` / `points_ceiling`

**维持现状**：仍由 `q14` 是否齐备、`q5_grid_count` / `q6_grid_count` 与 `u_early` / `u_orange` / `u_red` 决定；未知幽灵 **不引入** 新的空置单价键。

影响仅通过：

```text
vacant_pts_base = total + tier_extra_value
vacant_adj      = max(0, vacant − tier_extra_cells)
points*         = vacant_pts_base + vacant_adj × u*
```

### 5.6 非金/红未知幽灵（扩展位，二期）

若 `quality is None` 但 `C_gr` 为空且扫描可能集 `possible_qualities` 仍含 4 等：

- **方案 A（保守）**：`v_phantom = 0`，不占 tier（与 \|C_gr\|=0 相同）；
- **方案 B**：在 `possible_qualities ∩ {4,5,6}` 上重复 §5.1–5.2。

**建议一期只做 §5.2（tier 分摊）**；§5.1 维持 `_item_value`；紫档未知幽灵量少，二期再定。

---

## 6. 与画板 / 快照字段对齐

| 画板 | 定价草案 |
|------|----------|
| `phantom_quality_pref[uid] == "_phantom_q_infer"` | 品质未知 |
| 无键 + 未排除 Q5 | 缺省 Q5 → 已知 |
| 无键 + `5 ∈ excluded_qualities` | 品质未知（金/红候选） |
| `apply_scan_history_to_phantom_items`：未命中扫描 → `excluded_qualities` | 缩小 `C_gr` |
| `census_absent_qualities` 对幽灵 **全量** 并入排除 | `C_gr` 可能为空 → `v_phantom=0` |
| 自动 `phantom_vac_*` 多品质候选 | `_phantom_q_infer` + §5.2（`total` 仍可用 `_item_value`） |
| 自动填充唯一 `quality` / `manual_confirm_item_id` | 已知路径 |

快照写出前 UI 应保证 `phantom_items[uid].excluded_qualities` 与运行时一致（已有 reconcile）。

---

## 7. 建议新增的 `pricing` 字段（可观测）

```json
"phantom_unknown_quality": {
  "items": [
    {
      "uid": "phantom_1",
      "shape": 22,
      "cells": 4,
      "candidate_qualities": [5, 6],
      "value": 12345.67,
      "tier_credit_by_quality": {"5": 2.0, "6": 2.0}
    }
  ],
  "value_sum": 12345.67,
  "tier_credit_q5": 2,
  "tier_credit_q6": 2
}
```

（字段名实现时可微调；核心是 **可回归、可对照 UI**。）

---

## 8. 实现触点（预估）

| 模块 | 改动 |
|------|------|
| `analysis/grid_overlay_item_merge.py` | 可选：`phantom_row_meta` 或复用 `uid in phantom_items` 判断 |
| `analysis/_board_pricing.py` | 一期可 **不改**；二期可选 `v_phantom_gr` 分支 |
| `analysis/strategy/common.py` | `confirmed_tier_footprint_q456` 或新函数合并 `phantom_tier_credit` |
| `analysis/strategy/pipeline.py` | `compute_base_metrics` 调用顺序：merge → phantom_unknown 估价 → tier_extra |
| `analysis/strategy/generic.py` | 写出 `phantom_unknown_quality` |
| `tests/analysis/test_board_pricing.py` | 金/红推断笔 **`tier_extra`** 回归（`total` 维持 as-is） |

**不建议**改 `unknown_value.py` 主体逻辑（无 shape 专用）；避免与 `unknown_contour` 混用。

---

## 9. 测试计划（实现后）

1. **q6_grid_min=4 + 推断笔 2×2 红金候选**：`tier_extra_cells=0`（4 格按 2+2 分摊进 confirmed_q6/q5）；`total` 与改前 `_item_value` 一致。
2. **excluded {5,6}**：`tier_credit` 全 0；`total` 按 as-is（多为 0）。
3. **仅排除 Q6 + 推断笔**：合并 `quality=5`（已知）— 走已知 tier 全格计入 Q5，不被未知分摊覆盖。
4. **自动 phantom_vac 唯一 Q6**：仍走已知路径单测。
5. **（可选二期）** 无扫描负向快照：`v_phantom_gr` 与全档 `_item_value` 差异回归。

---

## 10. 待决问题（评审）

1. **tier 分摊**：均匀 `cells/2` vs 按候选条数比例分摊 — 一期均匀是否可接受？
2. **\|C_gr\|=1 退化**：tier 全额计入该档；是否在合并表写虚拟 `quality` — 建议仅 tier 分支，不改快照。
3. **是否调整 `est_*`**：参考估价是否展示未知幽灵占位 — UI 需求决定。
4. **二期 `total` 限价**：是否仅为 `phantom_vac_*` / 无负向测试快照引入 `v_phantom_gr`（手画默认不需要）。
5. **与 Bot 出价层**：一期主要改变 `tier_extra` → `vacant_adj`；用典型快照回放 `points` 是否需调参。

---

## 11. 小结

| 项目 | 已知幽灵（已对齐） | 未知幽灵（本草案 · 一期） |
|------|-------------------|---------------------------|
| `total` | shape + quality → CSV | **维持** `_item_value`（`quality=None` + 行上 `excluded_*`） |
| `vacant` | 占格扣除 | 不变 |
| `tier_extra` | 全格计入对应档 | **按 C_gr 均匀分摊** footprint（必做） |
| `points*` | 间接 | 间接（不改单价键） |

评审通过后：先实现 **§5.2** + §7 字段 + §9 单测，再更新 `board_snapshot_pricing.md` 正式章节。

---

*草案版本：2026-05-28（修订：手画场景不将 Q1–Q4 拉低 `total` 作为主矛盾；一期以 `tier_extra` 为主）*
