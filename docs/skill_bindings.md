# Skill bindings 实现说明

本文说明 `bidking.parsing.skill_bindings` 如何把 **游戏技能表导出**（`data/Skill_export.csv` → `skill_export_generated.SKILL_EXPORT_BY_ID`）编译成 **日志解析与定价管线** 使用的绑定表，以及与 `skill_event_stats_from_logs`、`raw_pricing` 的衔接。

---

## 1. 职责边界

| 层次 | 模块 | 做什么 |
|------|------|--------|
| 编译期 | `skill_bindings` | 从每行 `SkillExportRow` 推导「哪个键、用哪个日志 ID、读哪个字段」 |
| 合并日志 | `skill_event_stats_from_logs.merge_latest_skill_entries` | `HeroSkillLog` / `MapSkillLog` / `ItemSkillLog` → `Dict[int, dict]`，键为 `SkillCid` 或 `ItemCid` |
| 直读标量 | `parse_skill_entries_to_event_stats_direct` | 按绑定表从 `skill_entries` 填 `event_stats`（含轮廓补全） |
| 推理 | `raw_pricing.build_raw_pricing_dict` | 分档互推、随机均价下界、零一致性等（**不在** `skill_bindings` 内） |

`skill_bindings` **不读玩家日志**；只读静态技能表，生成常量元组/字典，在 import 时一次性求值。

---

## 2. 技能行上用到的表字段

实现里主要读这些列（见 `SkillExportRow`）：

- **`skill_id`**：地图/英雄侧日志合并键 `SkillCid`；与道具行的「技能编号」一致，但道具直读往往用 `ItemCid`（见下）。
- **`param_07`**：行类型。参与 `_build_direct_skill_int/float` 的为 `"0"` / `"1"` / `"2"`；**仅道具整型直读** `_build_direct_item_int` 要求 `"2"`。
- **`param_08`**：轮廓表里用于排除一类行（`_build_outline_skill_quality`：`param_08 == "1"` 则跳过）。
- **`param_09`**：品质列表，经 `ast.literal_eval` 得到 `_qualities(row)`，用于把「扫描/计数/均价/总价」映射到 `q*` / `total_*` / `q12_*` 等 **event_stats 键名**；**轮廓** `OUTLINE_SKILL_QUALITY` 仅当 `param_09` 为**单一档位** `1..6` 时从本列推断分档（见 §5.2）。
- **`param_15`**：竞拍「随机均价」行里表示默认命中件数（仅 `_map_announce_random_avg_price_skill_by_hit_count` 使用）。
- **`param_16`**：能力码列表 → `_codes(row)`（`Set[int]`），与 `param_09` 组合决定是否产生某条绑定。
- **`item_name_key`**：形如 `itemName_100104` → 正则抽出 **道具 `ItemCid`**（`_item_cid_from_item_name_key`）。

---

## 3. `param_16` 能力码与直读绑定（核心规则）

下列逻辑与源码一一对应（道具行的 `2000` 分支**不含** `9000` 判断，与地图侧略有差别）。

### 3.1 地图/英雄/通用行（`param_07 ∈ {0,1,2}`）→ `SkillCid` 直读

**整型 `RAW_PRICING_DIRECT_SKILL_INT_BINDINGS`**

| 条件（`codes = param_16`） | `param_09` → 函数 | 写入键 `event_stats` | 日志字段 |
|----------------------------|-------------------|----------------------|----------|
| `2000 ∈ codes` 且 `10000,8000,9000 ∉ codes` | `_grid_count_event_key(qs)` | `total_grid_count` / `q12_grid_count` / `qN_grid_count` | `TotalHitBoxIndex` |
| `4000 ∈ codes` | `_count_event_key(qs)` | `total_count` / `q12_count` / `qN_count` | `HitItemIndex` |

**浮点 `RAW_PRICING_DIRECT_SKILL_FLOAT_BINDINGS`**

| 条件 | 函数 | 写入键 | 日志字段 |
|------|------|--------|----------|
| `3000 ∈ codes` | `_grid_avg_event_key(qs)` | `total_grid_avg` / `q12_grid_avg` / `qN_grid_avg` | `AllHitItemAvgBoxIndex` |

### 3.2 仅道具行（`param_07 == "2"`）→ `ItemCid` 直读

**整型 `RAW_PRICING_DIRECT_ITEM_INT_BINDINGS`**

| 条件 | 函数 | 写入键 | 日志字段 |
|------|------|--------|----------|
| `2000 ∈ codes` 且 `10000,8000 ∉ codes` | `_grid_count_event_key` | 同上 | `TotalHitBoxIndex` |
| `4000 ∈ codes` | `_count_event_key` | 同上 | `HitItemIndex` |
| `10000 ∈ codes` | `_price_total_event_key` | `q12_price_total` 或 `q3..q6_price_total`（见下） | `HitItemTotalPrice` |

道具侧 **没有** `9000` 对 `2000` 的排除；地图侧有（避免某类行误占格数键）。

### 3.3 `param_09` → 键名函数（同一品质语义在「格数 / 件数 / 均格 / 总价」上对称）

- **全品质 / 未知**：`qs` 空或 `(0,)` → 多为 `total_*`；总价在 `_price_total_event_key` 中空则**不产生**绑定。
- **白+绿**：`set(qs) ⊆ {1,2}` 时，格数/均格/总价用 **`q12_*`**；件数要求 `len(qs) >= 2` 才得到 `q12_count`（与单档 `qN_count` 区分）。
- **单档 1..6**：格数、均格、单价总价的单档键为 **`q{档位}_*`**；总价仅当单档 `3..6` 时映射到 `q3_price_total`…`q6_price_total`（见 `_price_total_event_key`）。

具体分支以 `skill_bindings.py` 中四个 `_grid_*` / `_count_*` / `_price_total_*` 为准。

---

## 4. 同一 `event_stats` 键多技能冲突：去重规则

`_build_direct_skill_int` / `_build_direct_skill_float` 在收集完「候选三元组」后，按 **event_stats 键** 去重，只保留一条：

- 调用 `_dedupe_int_bindings` / `_dedupe_float_bindings`。
- 择优函数 `_prefer_row_for_event_key`：**优先保留 `param_07 == "1"`（竞拍信息）**；否则保留 **`skill_id` 更大** 的那一行。

因此：**多行技能表可能“想”写同一个键，但运行期绑定表里每个键只对应一个 `SkillCid`**。道具侧 `RAW_PRICING_DIRECT_ITEM_INT_BINDINGS` **不做** 这种按键去重（按 `(键, ItemCid, 字段)` 去重）。

---

## 5. 非 `param_16` 推导的静态表

### 5.1 地图日志价直读（固定 `SkillCid`）

- **`SKILL_LOG_PRICE_AVG_BINDINGS`**：`Tuple3P = (skill_cid, 日志字段, event_stats 键)`  
  - 例：`(200036, "AllHitItemAvgPrice", "q4_price_avg")` 等。
- **`SKILL_LOG_PRICE_TOTAL_BINDINGS`**：如 `(503/504/505, "HitItemTotalPrice", "q4/q5/q6_price_total")`。

在 `parse_skill_entries_to_event_stats_direct` 里通过 `read_skill_log_direct_prices` 写入，与「整型直读绑定」并行存在；同一总价键可能既来自地图 `SkillCid` 又来自道具 `ItemCid` 覆盖策略（见解析模块实现）。

### 5.2 英雄 / 地图强制品质 / 轮廓

- **`HERO_SKILL_QUALITY`**：写死扫描 `skill_id ∈ {1001031,1001032,1001033,1001034}`，若 `param_09` 为单一 `1..6`，则 `SkillCid → 品质`。
- **`MAP_SKILL_FORCE_QUALITY`**：`param_07==1` 且 `param_16` 解析集合**恰好** `{1000,7000}`，且单档品质，`skill_id ∈ {200001,200002,200003}` 时收录。
- **`OUTLINE_SKILL_QUALITY`**：`param_16 == {1000}`、`param_08 != "1"`，且 **`param_09` 解析为恰好一个整数 `1..6`** 时，`SkillCid → 该档品质`，供 `apply_outline_hitbox_to_event_stats` 从 `HitBoxList` 汇总 `qN_count` / `qN_grid_count` / `qN_grid_avg`。`param_09` 为 `[0]`、多元素、类别 tag（如 `101`）等行**不会**进入本表。

### 5.3 道具 → 规范地图 `SkillCid`（鉴影类）

- **`ITEM_SKILL_CANONICAL_SKILL_CID`**：与 `constants.ITEM_TOOLS` 首元一致，避免循环 import 在模块内复制一份。  
- 含义：`ItemSkillLog` 合并时除写入 `out[item_cid]` 外，还可把同一条 entry 复制到 `out[canon_skill_cid]`，使地图侧绑定能读到鉴影道具日志（见 `merge_latest_skill_entries`）。

### 5.4 竞拍「随机 n 件轮廓」均价技能 ID

- **`_map_announce_random_avg_price_skill_by_hit_count`**：在 `param_07==1` 且 `8000 ∈ param_16` 的行中，按 `param_15 ∈ {3,6,9,12}` 分组，每组取 **最大 `skill_id`**。
- 导出为 **`MAP_SKILL_RANDOM3_AVG_PRICE`** 等四个常量；若缺任一组会在 **import 时 `RuntimeError`**。
- 这些技能参与 **`raw_pricing`** 里 `random_avg_price_min` 的推理（`AllHitItemAvgPrice` × `HitItemIndex`），**不是** `RAW_PRICING_DIRECT_*` 三元组的一部分。

### 5.5 从去重后的整型表反查「代表技能」

- **`_skill_cid_for_int_stat(stat_key)`**：在 `RAW_PRICING_DIRECT_SKILL_INT_BINDINGS` 里按键查找，供：
  - **`MAP_SKILL_TOTAL_HIDDEN_CELLS`**：`total_grid_count` 对应 `SkillCid`
  - **`MAP_SKILL_TOTAL_GOLD_COUNT`**：`q5_count` 对应 `SkillCid`  
  若键不存在则 **抛 `KeyError`**（表结构变更时需同步技能表或绑定逻辑）。

---

## 6. UI / 文案类导出

- **`MAP_SKILL_DESC`**：`skill_id → name_zh`（全表）。
- **`ITEM_SKILL_DESC`**：仅 `param_07==2` 且有 `itemName_*` 的行 → `ItemCid → name_zh`。
- **`ITEM_SKILL_EVENT_STATS`**：与道具直读规则一致，列出每个 `ItemCid` 可能贡献的 **event_stats 键元组**（无则 `()`，但仍出现在 dict 里以便与 `ITEM_SKILL_DESC` 对齐）。

---

## 7. 与日志合并、解析的顺序要点

1. **`merge_latest_skill_entries`**：后出现的日志块覆盖先出现的；同一列表内靠后的条目覆盖靠前的。道具条目总是写入 **`out[ItemCid]`**；若存在规范键则再写 **`out[canon]`**。
2. **`parse_skill_entries_to_event_stats_direct`**：先 `read_skill_log_direct_prices`，再按 `RAW_PRICING_DIRECT_SKILL_*` / `ITEM_*` 循环填充；道具整型在值非 `None` 时 **覆盖** 已有键。
3. **`EVENT_STATS_ATTRIBUTE_SOURCES`**（`skill_event_stats_from_logs`）：由上述绑定表 **自动生成** 人类可读溯源说明，便于排查「某个 `event_stats` 键可能来自哪里」。

---

## 8. 维护与校验

1. 修改 `data/Skill_export.csv` 后运行：  
   `python build/generate_skill_export_table.py`  
   再跑测试与（可选）`skill_bindings.validate_skill_registry_vs_csv(csv_path)`，核对 `param_16` 等与生成文件一致。
2. 需要**全表技能 ↔ 解析键**对照表时，可运行：  
   `python build/generate_skill_parsing_report.py`  
   输出默认 `data/skill_parsing_report.csv`（含「主线/旁路」去重说明列）。

---

## 9. 源码索引

| 内容 | 位置 |
|------|------|
| 绑定构建与常量 | `src/bidking/parsing/skill_bindings.py` |
| 日志合并与 `event_stats` 直读 | `src/bidking/analysis/skill_event_stats_from_logs.py` |
| 再导出绑定 | `src/bidking/parsing/constants.py`（从 `skill_bindings` import） |
| 技能表生成 | `build/generate_skill_export_table.py` |
| 解析报表生成 | `build/generate_skill_parsing_report.py` |

以上即当前仓库中 **Skill bindings** 的完整实现要点。
