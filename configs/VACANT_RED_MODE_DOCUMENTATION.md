# vacant_red_floor_ceiling_pick_mode 配置说明

## 概述

`vacant_red_floor_ceiling_pick_mode` 控制 Bot 在第 4、5 回合使用**空置舱**时的出价锚定策略。它决定 Bot 在"保守估价"(floor) 和"激进估价"(ceiling/red) 之间如何选择。

---

## 工作原理

### 基本概念

| 术语 | 说明 |
|------|------|
| `points_floor` | **橙价** - 保守估价，基于物品橙色品质的价值计算 |
| `points_ceiling` | **红价** - 激进估价，假设存在红色稀有物品的最高估价 |
| `avg_price` | **均价** - (floor + ceiling) / 2 |
| `vacant` | 空置舱已使用次数 |

### 生效时机

- **仅在第 4、5 回合生效**
- 仅在 `enable_vacant_red_floor_ceiling_pick: true` 时生效
- 低档图（config_map_key 为 "1" 或 "2"）禁用此功能

---

## 两种模式对比

### 1. normal 模式（默认）

```json
{
  "pricing": {
    "vacant_red_floor_ceiling_pick_mode": "normal"
  }
}
```

**策略逻辑**：
1. 分析对手历史出价（第 3 回合或第 4 回合）
2. 推断"空置舱里是否有红"（通过 `infer_vacant_has_red_from_opponent_history`）
3. **有红 → 使用红价 (ceiling)**
4. **无红 → 使用橙价 (floor)**

**推断有红的条件**（第 4 回合为例）：
- 空置舱使用次数 > 4
- 至少 2 个对手出价 ≥ 1.2 倍我方出价，或 ≥ 1.1 倍 floor
- 或者 1 个对手出价 ≥ 1.3 倍我方出价，或 ≥ 1.1 倍 floor
- 空置舱使用次数 >= 20 时强制推断有红

**特点**：
- 对对手行为敏感，动态调整
- 二选一（floor 或 ceiling，无中间值）
- 适合稳健型策略

---

### 2. aggressive 模式（积极模式）

```json
{
  "pricing": {
    "vacant_red_floor_ceiling_pick_mode": "aggressive"
  }
}
```

**核心特点**：
- 引入**均价** (avg) 作为中间选项
- 根据空置舱使用次数、对手出价、地图类型综合判断
- **非暗图时考虑对手出价**；**暗图时不考虑对手出价**（440/450）

#### aggressive 模式决策流程（代码逻辑顺序）

```
1. vacant <= 4
   └── 返回 floor（橙价）

2. 非暗图 AND 有对手出价数据:
   ├── floor > 对手最大出价 × 1.2
   │   └── 返回 floor（我方估价远高于对手）
   ├── floor > 对手最大出价
   │   └── 返回 avg（均价）
   ├── 对手 >= floor × 1.2
   │   └── 返回 ceiling（红价）
   └── 对手 >= ceiling
       └── 返回 ceiling（红价）

3. 5 <= vacant <= 12
   └── 返回 avg（均价）

4. vacant >= 12:
   ├── 暗图（440/450）→ 返回 avg（均价）
   └── 非暗图 → 返回 ceiling（红价）

5. 兜底（暗图）→ 返回 avg
6. 兜底（非暗图）→ 返回 ceiling
```

#### aggressive 模式的关键判断点

| 条件 | 返回值 | 场景说明 |
|------|--------|----------|
| vacant ≤ 4 | floor | 空置舱使用次数极少，保守处理 |
| floor > 对手×1.2 | floor | 我方估价远高于对手，对手不争 |
| floor > 对手 | avg | 我方估价略高于对手，取中间 |
| 5 ≤ vacant ≤ 12 | avg | 中等使用次数，默认均价 |
| vacant ≥ 12 + 暗图 | avg | 暗图高使用次数，不使用红价 |
| vacant ≥ 12 + 普通图 | ceiling | 普通图高使用次数，激进跟价 |
| 对手 ≥ floor×1.2 | ceiling | 对手很激进，跟进红价 |

#### 暗图特殊处理（440、450）

```python
# 暗图判断
_AGGRESSIVE_DARK_MAP_BUNDLE_KEYS = frozenset({"440", "450"})

# 暗图特性：
# - prices 为名次而非金币，不宜直接比较对手出价
# - aggressive 模式下不获取 max_opponent_bid
# - vacant >= 12 时强制使用均价（而非红价）
```

---

## 模式对比总结

| 维度 | normal 模式 | aggressive 模式 |
|------|-------------|-----------------|
| **可选价格** | floor 或 ceiling | floor、avg、ceiling |
| **对手出价权重** | 高（推断有红/无红） | 非暗图时中等，暗图时忽略 |
| **空置舱次数权重** | 仅判断是否>4或>20 | 分段判断（≤4、5-12、≥12） |
| **暗图特殊处理** | 无 | vacant≥12 时强制均价 |
| **策略风格** | 二值判断（有无红） | 多值梯度判断 |

---

## 配置建议

### 各地图推荐配置

| 地图 | 地图ID | 推荐模式 | 原因 |
|------|--------|----------|------|
| 快递盲盒堆 | 210 | normal | 新手图，二值判断足够 |
| 废弃仓库 | 220 | normal | 低级图，复杂逻辑收益有限 |
| 航运集装箱 | 230 | normal | 中级图，normal 足够 |
| 空置别墅 | 240 | aggressive | 高级图，三档价格更精细 |
| 沉船密封舱 | 250 | aggressive | 进阶级，推荐使用 |
| 隐秘拍卖行 | 260 | aggressive | 最高级图，需要精细策略 |
| 幽静别墅 | 440 | aggressive | **暗图，vacant≥12 强制均价** |
| 深海沉船 | 450 | aggressive | **暗图，vacant≥12 强制均价** |

### 当前配置现状

```
250.json: "vacant_red_floor_ceiling_pick_mode": "normal"  [建议改为 aggressive]
260.json: "vacant_red_floor_ceiling_pick_mode": "normal"  [建议改为 aggressive]
440.json: [未配置，默认 normal]                           [建议改为 aggressive]
450.json: "vacant_red_floor_ceiling_pick_mode": "normal"  [建议改为 aggressive]
```

---

## 效果对比示例

假设某局第 5 回合：
- floor（橙价）= 100,000
- ceiling（红价）= 300,000  
- avg（均价）= 200,000
- vacant（空置舱使用次数）= 10
- 对手最大出价 = 120,000

### normal 模式
- 推断对手出价 120,000 未达阈值 → 推断**无红**
- 返回 **100,000** (floor)

### aggressive 模式（非暗图）
- vacant = 10，满足 5 ≤ vacant ≤ 12
- 返回 **200,000** (avg)

### aggressive 模式（暗图 440/450）
- vacant = 10，满足 5 ≤ vacant ≤ 12
- 返回 **200,000** (avg)

---

## 再举一例（高 vacant）

假设：
- floor = 100,000, ceiling = 300,000, avg = 200,000
- vacant = 15
- 对手最大出价 = 180,000

### normal 模式
- vacant > 4 且对手出价未达 1.2×floor → 可能推断无红
- 返回 **100,000** (floor)

### aggressive 模式（非暗图）
- vacant ≥ 12 且非暗图
- 返回 **300,000** (ceiling)

### aggressive 模式（暗图 440/450）
- vacant ≥ 12 但暗图强制均价
- 返回 **200,000** (avg)

---

## 注意事项

1. **配置位置**：此配置在 `pricing.maps/<map_id>.json` 的 `pricing` 节下

2. **默认值**：若未配置，默认为 `"normal"`

3. **中文别名**：代码中也支持 `"激进"` 或 `"积极"` 作为 aggressive 的别名

4. **前置条件**：必须同时启用 `enable_vacant_red_floor_ceiling_pick: true`

5. **低档图排除**：地图 config_key 为 "1" 或 "2" 时，此功能强制禁用

6. **暗图识别**：代码通过地图 bundle key 判断是否为暗图（440、450）

---

## 配置示例

### 高级图使用 aggressive 模式

```json
{
  "pricing": {
    "vacant_red_floor_ceiling_pick_mode": "aggressive",
    "enable_vacant_red_floor_ceiling_pick": true,
    "enable_opponent_bid_adjustment": true,
    "enable_big_gold_adjustment": true,
    "fallback_bid_price": 155555
  },
  "automation": {
    "bid_cap_price": 1500000,
    "bid_ratio_by_round": {
      "1": 0.65,
      "2": 0.70,
      "3": 0.80,
      "4": 0.95,
      "5": 1.0
    }
  }
}
```

---

*文档更新时间: 2026-05-21*
