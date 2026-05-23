# BidKing 配置文档

本文档说明 `configs/` 目录下所有**非 Runtime 配置**的 JSON 文件。

---

## 配置文件总览

| 文件 | 用途 | 说明 |
|------|------|------|
| `config.json` | 主配置文件 | 包含定价策略、UI设置、自动化参数、时序控制等 |
| `pricing.maps/210.json` | 快递盲盒堆地图策略 | 新手地图定价策略 |
| `pricing.maps/220.json` | 废弃仓库地图策略 | 低级图定价策略 |
| `pricing.maps/230.json` | 航运集装箱地图策略 | 中级图定价策略 |
| `pricing.maps/240.json` | 空置别墅地图策略 | 高级图定价策略 |
| `pricing.maps/250.json` | 沉船密封舱地图策略 | 进阶级地图定价策略 |
| `pricing.maps/260.json` | 隐秘拍卖行地图策略 | 最高级地图定价策略 |
| `pricing.maps/440.json` | 幽静别墅地图策略 | 隐秘拍卖档定价策略 |
| `pricing.maps/450.json` | 深海沉船地图策略 | 隐秘拍卖档定价策略 |

> **注意**: `runtime.json` 是 Runtime 配置，记录运行时状态（窗口句柄、点击坐标等），不在本文档讨论范围内。

### 已废弃（勿再写入配置）

| 配置项 | 说明 |
|--------|------|
| `timing.tool_after_wait_seconds` | 代码中无读取，已删除 |
| `automation.safe_guard_enabled` / `safe_guard_max_increase_ratio` | 旧版保护逻辑，已删除（保存时仍会剔除残留） |
| `board_snapshot.self_name_substring` | 已由 `self_user_uid` / 跨局推断替代，已删除 |
| `grid_view.fraud_empty_cells_tiling_n` | 已删除；请用 `fraud_empty_cells_algorithm`: `["tiling", n]` 或 `{"tiling": n}` |
| `pricing.maps` 内的 `automation.default_map` | 误写项，应只在 `config.json` 的 `automation.default_map` |

---

## 1. 主配置文件 (config.json)

### 1.1 pricing - 定价策略配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_vacant_red_floor_ceiling_pick` | bool | `true` | 启用空置红楼层/天花板优先选择策略 |
| `enable_opponent_bid_adjustment` | bool | `true` | 启用对手出价调整策略 |
| `infer_unknown_contour_shapes` | bool | `true` | 推断未知轮廓形状 |
| `price_avg_infer_max_item_count` | int | `30` | 价格推断时最大物品数量限制 |
| `grid_avg_infer_max_item_count` | int | `30` | 网格推断时最大物品数量限制 |
| `grid_avg_infer_max_grid_count` | int | `300` | 网格推断时最大网格数量限制 |

### 1.2 grid_view - 网格视图配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `unknown_bg` | string | `"#1a7394"` | 未知单元格背景颜色 |
| `fraud_empty_cells_algorithm` | string | `"tiling_strict"` | 虚假空格检测算法 |

### 1.3 board_snapshot - 画板快照配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用快照功能 |
| `path` | string | `"data/board_snapshot.json"` | 快照存储路径 |
| `write_mode` | string | `"both"` | 写入模式 (both/file/memory) |
| `schema_version_min` | int | `1` | 最小快照格式版本 |
| `self_user_uid` | string | `"358372071974712"` | 自身用户UID |

### 1.4 automation - 自动化配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `bot_runner` | string | `"fresh_aisha_bot"` | 使用的机器人运行器 |
| `selected_mode` | string | `"aisha_premium"` | 选定的自动化模式 |
| `tool_rounds` | array | `[]` | 使用道具的回合列表 |
| `enable_aisha_round4_tool_vacant_gate` | bool | `false` | 艾莎且勾选第4回合用道具时，按空置格是否超过阈值决定是否实际使用道具；**已公开** ``raw_pricing.event_stats`` 的 ``q5_grid_count`` 或 ``q5_grid_avg`` 时第4回合不用道具；**开启后第5回合一律不用道具**（忽略 ``tool_rounds`` 勾选）。可写在主配置 ``automation`` 或当前地图 ``configs/pricing.maps/<地图>.json`` 的 ``automation`` 段（bot 会按对局 ``map_id`` 合并） |
| `aisha_round4_tool_min_vacant` | int | `5` | 上项开启时：仅当 ``pricing.vacant`` **大于等于** 该值才在第4回合使用道具（否则跳过）；可与上项同样写在地图 JSON |
| `default_map` | string | `"1"` | 默认地图ID（仅写在 `config.json`，勿写入 `pricing.maps`） |
| `default_runs` | int | `1` | 默认运行次数 |
| `selected_map` | string | `"440"` | 当前选定地图 |
| `selected_runs` | int | `10` | 当前选定运行次数 |
| `run_cycles` | int | `2` | 运行周期数 |
| `cycle_rest_minutes` | float | `0.0` | 周期间休息分钟数 |
| `warehouse_auto_sort.enabled` | bool | `true` | 仓库自动排序功能开关 |

### 1.5 timing - 时序控制配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `poll_seconds` | float | `1` | 轮询间隔秒数 |
| `round_detect_wait_seconds` | float | `5.0` | 回合检测等待时间 |
| `round1_extra_wait_seconds` | float | `5.0` | 第1回合额外等待时间 |
| `click_pause_seconds` | float | `0.12` | 点击间隔暂停时间 |
| `after_bid_confirm_wait_seconds` | float | `1.0` | 出价确认后等待时间 |
| `bid_confirm_verify_max_seconds` | int | `30` | 出价确认验证最大等待秒数 |
| `bid_confirm_retry_pause_seconds` | float | `0.35` | 出价确认重试暂停时间 |
| `bid_confirm_capture_delay_seconds` | int | `0` | 出价确认捕获延迟 |
| `transition_debounce_seconds` | float | `5.0` | 状态转换防抖时间 |
| `reward_continue_debounce_seconds` | float | `1.0` | 奖励继续防抖时间 |

### 1.6 advisor - 顾问配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `role` | string | `"aisha"` | 顾问角色名称 |

---

## 2. 地图定价策略文件 (pricing.maps/*.json)

地图定价策略文件位于 `configs/pricing.maps/` 目录下，文件名对应地图ID（如 `210.json`）。

这些文件在运行时会**覆盖** `config.json` 中的同名配置项，实现不同地图使用不同定价策略。

### 2.1 文件与地图对应关系

| 文件名 | 地图名称 | 地图ID | 门票价格 | 策略特点 |
|--------|----------|--------|----------|----------|
| `210.json` | 快递盲盒堆 | 210 | 100 | 新手图，保守策略，第5回合激进 |
| `220.json` | 废弃仓库 | 220 | 2000 | 低级图，高比例系数 |
| `230.json` | 航运集装箱 | 230 | 5000 | 中级图，稳健递增 |
| `240.json` | 空置别墅 | 240 | 10000 | 高级图，启用所有调整策略 |
| `250.json` | 沉船密封舱 | 250 | 25000 | 进阶级，normal模式空置红策略 |
| `260.json` | 隐秘拍卖行 | 260 | 100000 | 最高级，禁用大金调整 |
| `440.json` | 幽静别墅 | 440 | 10000 | 隐秘拍卖档，特殊对手排名乘数 |
| `450.json` | 深海沉船 | 450 | 25000 | 隐秘拍卖档，特殊对手排名乘数 |

### 2.2 配置结构

所有地图定价配置文件包含以下两个主要部分：

```json
{
  "pricing": {
    // 定价策略相关配置
  },
  "automation": {
    // 自动化参数相关配置
  }
}
```

### 2.3 pricing 配置项

| 配置项 | 类型 | 常见值 | 说明 |
|--------|------|--------|------|
| `fallback_bid_price` | int | `8888~222222` | 当无法计算价格时的兜底出价 |
| `vacant_red_floor_ceiling_pick_mode` | string | `"normal"` 或 `"aggressive"` | 空置红选择模式 |
| `enable_opponent_bid_adjustment` | bool | `true`/`false` | 是否启用对手出价调整 |
| `enable_vacant_red_floor_ceiling_pick` | bool | `true`/`false` | 是否启用空置红楼层/天花板选择 |
| `enable_big_gold_adjustment` | bool | `true`/`false` | 是否启用大金物品调整 |
| `secret_auction_rank_opponent_multipliers` | object | 见下方 | 隐秘拍卖档对手排名乘数 |

**secret_auction_rank_opponent_multipliers 结构:**（上回合己方 **1-based 排位** → 对手预估 = `bid_pre × 系数`）

| 键 | 说明 | 默认 |
|----|------|------|
| `"1"` / `rank_1` | 上回合第 1 名 | `1.0` |
| `"2"` / `rank_2` | 上回合第 2 名 | `1.1` |
| `"3"` / `rank_3` | 上回合第 3 名 | `1.2` |
| `"4"` / `rank_4` / `"4+"` | 上回合第 4 名 | `1.3` |
| `default` / `rank_default` | 第 5 名及以后或未单独配置的排位 | `1.3` |

示例（`configs/pricing.maps/450.json`）：

```json
"secret_auction_rank_opponent_multipliers": {
  "1": 1.0,
  "2": 1.1,
  "3": 1.2,
  "4": 1.3,
  "default": 1.3
}
```

### 2.4 automation 配置项

| 配置项 | 类型 | 常见值 | 说明 |
|--------|------|--------|------|
| `bid_cap_price` | int | `200000~5000000` | 出价上限（封顶价格） |
| `bid_ratio_by_round` | object | 见下方 | 各回合出价比例系数 |

**bid_ratio_by_round 结构:**

```json
{
  "1": 0.55,  // 第1回合出价为基础价的55%
  "2": 0.65,  // 第2回合出价为基础价的65%
  "3": 0.75,  // 第3回合出价为基础价的75%
  "4": 0.95,  // 第4回合出价为基础价的95%
  "5": 1.0    // 第5回合出价为基础价的100%
}
```

### 2.5 各地图详细配置对比

#### 210 - 快递盲盒堆（新手图）
- **fallback_bid_price**: 22222
- **bid_cap_price**: 250000
- **回合系数**: 从0.9逐渐上升到1.2（第5回合最激进）
- **特点**: 低门槛，保守入场，后期激进

#### 220 - 废弃仓库（低级图）
- **fallback_bid_price**: 33334
- **bid_cap_price**: 400000
- **回合系数**: 从0.6到0.95
- **特点**: 比例系数相对较高

#### 230 - 航运集装箱（中级图）
- **fallback_bid_price**: 111222
- **bid_cap_price**: 800000
- **回合系数**: 从0.55到1.0
- **特点**: 稳健递增，无明显禁用项

#### 240 - 空置别墅（高级图）
- **fallback_bid_price**: 155555
- **bid_cap_price**: 1500000
- **回合系数**: 从0.65到1.0
- **启用策略**: 对手调整、空置红选择、大金调整

#### 250 - 沉船密封舱（进阶级）
- **fallback_bid_price**: 222222
- **bid_cap_price**: 3000000
- **回合系数**: 从0.55到1.0
- **vacant_red_mode**: normal
- **启用策略**: 对手调整、空置红选择、大金调整

#### 260 - 隐秘拍卖行（最高级）
- **fallback_bid_price**: 155555
- **bid_cap_price**: 5000000
- **回合系数**: 从0.55到1.0
- **禁用策略**: 大金调整 (enable_big_gold_adjustment: false)

#### 440 - 幽静别墅（隐秘拍卖档）
- **fallback_bid_price**: 8888
- **bid_cap_price**: 2000000
- **回合系数**: 从0.55到1.1
- **启用策略**: 对手调整、空置红选择、大金调整
- **特殊配置**: 对手排名乘数调整

#### 450 - 深海沉船（隐秘拍卖档）
- **fallback_bid_price**: 155555
- **bid_cap_price**: 2000000
- **回合系数**: 从0.55到0.9
- **vacant_red_mode**: normal
- **启用策略**: 对手调整、空置红选择、大金调整
- **特殊配置**: 对手排名乘数调整

---

## 3. 配置加载优先级

当程序运行时，配置的加载和合并顺序如下：

```
1. config.json (基础配置)
       ↓
2. pricing.maps/<map_id>.json (地图特定覆盖层)
       ↓
3. 合并后的有效配置 (用于出价计算)
```

**合并规则**: 深合并（deep merge），地图配置会覆盖 `config.json` 中的同名配置项。

---

## 4. 配置修改建议

### 4.1 调整出价激进程度
修改 `bid_ratio_by_round` 中的值：
- 值 < 1.0: 保守出价（低于估价）
- 值 = 1.0: 按估价出价
- 值 > 1.0: 激进出价（高于估价）

### 4.2 调整出价上限
修改 `bid_cap_price`：
- 担心亏损：降低该值
- 追求高价值物品：提高该值

### 4.3 空置红策略选择
- **normal 模式**: 标准空置红推断
- **aggressive 模式**: 积极模式，对手价格高时快速跟进
- **适用地图**: 440、450 为隐秘拍卖档，有特殊排名乘数配置

### 4.4 对手出价调整
- 启用 `enable_opponent_bid_adjustment` 时，Bot 会根据对手出价动态调整自身出价
- 在竞争激烈的高级图中建议启用

---

## 5. 注意事项

1. **JSON 格式**: 所有配置文件必须符合 JSON 格式，注意逗号和引号
2. **数字类型**: `bid_cap_price` 和 `fallback_bid_price` 必须是整数
3. **比例范围**: `bid_ratio_by_round` 建议保持在 0.3~1.5 之间
4. **备份配置**: 修改前请备份原配置文件
5. **验证配置**: 修改后建议运行测试验证配置有效性

---

*文档生成时间: 2026-05-21*
*适用版本: BidKing Bot 自动化系统*
