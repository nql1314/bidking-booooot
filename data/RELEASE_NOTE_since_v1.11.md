# Release Note（相对 Git 标签 `v.1.11`）

本文对比仓库标签 **`v.1.11`** 与当前主线功能，仅说明**用户可见能力与配置用法**，不涉及实现细节。

---

## 一、功能变更摘要

### 1. 鉴影看板：通用模式与艾哈迈德快递站

- **通用看板（universal）**：启动可视化时可选择「通用」看板角色，面向多英雄场景；配套修正了部分底价/估价表现，使通用模式与既有角色策略更一致。
- **艾哈迈德（快递站特化）**：新增独立看板选项「艾哈迈德(快递站特化）」。当对局为己方 Ahmad 且地图属于快递站系列时，顶栏仓位估价与说明会采用**快递站专用估价**（含多候选说明），与通用公式的展示区分。

### 2. 日志中的「物品技能」与估价输入

- 解析 Player.log 时，对 **道具使用类** 推送中 `ItemSkillLog` 等字段的提取范围与游戏内协议对齐，避免因字段落在根级或 `GameData` 下不一致而**漏记道具相关技能日志**，从而改善后续 raw 定价与看板数据完整性。

### 3. 估算总价：推断增强与「总价为 0」修复

- 在均价、档内总价、件数等关系可约束时，增强**总价/件数/总格**等量的推断与一致性处理；修复部分场景下界面与日志看似正常但**估算总价恒为 0** 的问题，使看板「估算总价」与快照内定价汇总一致。

### 4. 品质扫描与「普查缺席档」

- 结合全图品质普查结果，将**已可排除的品质档**纳入与品质扫描历史等价的负向信息，用于推断「空格仍可能出现的品质」等看板辅助信息，减少与轮廓/日志不一致时的歧义。

### 5. 隐秘拍卖地图：对手名次与出价调整开关

- 对 **幽静别墅 / 沉船密封舱** 等按「排名」理解对手出价的地图档（配置中档键 **440 / 450**），支持按己方相对名次对估价做倍数调整。
- 新增总开关 **`enable_opponent_bid_adjustment`**：可在全局或单地图关闭该类「按对手出价/名次调整」，便于对照实验或保守策略。

### 6. Bot 自动化：拟人化轨迹与输入节奏

- 自动化点击、移动、输入价格等行为支持 **`humanize`** 配置块（可选）：控制是否启用曲线移动、点击抖动、价格输入字符间隔与偶发停顿等，用于更接近真人操作节奏；

### 7. 项目根路径与画板快照默认位置

- 配置与数据路径优先解析环境变量 **`BIDKING_HOME`**；否则自动向上查找同时包含 `configs/` 与 `data/` 的目录作为项目根。
- **画板快照**默认文件改为项目下的 **`data/board_snapshot.json`**（仍可在配置里改为绝对路径或相对项目根的路径）。

### 8. 棋盘快照：识别「自己」

- `board_snapshot` 增加 **`self_user_uid`**、**`self_name_substring`**，用于在快照中稳定识别己方玩家，供隐秘拍卖对手价、名次等逻辑使用。
- 二者也可通过环境变量覆盖（变量存在即生效，便于不把账号信息写入仓库）：
  - **`BIDKING_SELF_USER_UID`** → `board_snapshot.self_user_uid`
  - **`BIDKING_SELF_NAME_SUBSTRING`** → `board_snapshot.self_name_substring`

---

## 二、配置结构与使用方式

配置加载顺序简述：**`configs/runtime.json` 为基底**，与 **`configs/config.json`（本机覆盖）深合并**；出价相关还可按地图读取 **`configs/pricing.maps/<地图档键>.json`**，并与上述合并结果再合并（地图文件优先于全局中的同名字段）。

### 1. `configs/config.json`（覆盖层）新增/常用项

| 配置路径 | 作用 |
|----------|------|
| `pricing.enable_opponent_bid_adjustment` | 是否启用「按对手出价/名次」的估价调整（隐秘拍卖等）。`false` / `0` / `"off"` 等可关闭。未在地图文件中单独指定时，以此全局为准。 |
| `board_snapshot.path` | 快照 JSON 路径。留空或未配置时使用 `<项目根>/data/board_snapshot.json`。可写 `data/board_snapshot.json` 或绝对路径。 |
| `board_snapshot.self_user_uid` | 己方用户 UID 字符串。 |
| `board_snapshot.self_name_substring` | 己方显示名子串（例如固定前缀），与 UID 二选一或组合用于识别自己。 |

其余 `board_snapshot` 项（如 `enabled`、`write_mode`、`schema_version_min`）与 `v.1.11` 一致，仍按原方式使用。

### 2. `configs/pricing.maps/440.json` 与 `450.json`（隐秘拍卖档）

在 **`pricing`** 下除原有 **`fallback_bid_price`** 外，典型包含：

| 字段 | 作用 |
|------|------|
| `enable_opponent_bid_adjustment` | 仅对本档地图覆盖全局开关；未写则继承 `config.json` / 默认。 |
| `secret_auction_rank_opponent_multipliers` | 按己方相对对手名次区间设定倍数，键名包括：`behind_ge_2`、`behind_1`、`behind_0`、`behind_lt_0`、`no_opponent_bid`（具体语义以界面与实盘需求为准，可按需微调数值）。 |

**`automation`** 段内仍可使用 **`bid_cap_price`**、**`bid_ratio_by_round`** 等与 `v.1.11` 相同的自动化出价参数。

### 3. `configs/pricing.maps/230.json` 等其它地图

- 与 `v.1.11` 相同：按地图档键维护 **`fallback_bid_price`**、**`bid_cap_price`**、**`bid_ratio_by_round`** 等即可。
- 自 `v.1.11` 起示例仓库中 **230** 的默认 **`fallback_bid_price`** 数值有更新，部署时请以自己的业务为准核对。

### 4. Bot 拟人化（可选，写入合并后的配置 JSON）

在 **`runtime.json` 或 `config.json`** 中增加同级键 **`humanize`**（对象），常用字段示例：

- `enabled`：`true` / `false`，总开关。
- `click_jitter_pixels`：点击位置抖动像素。
- `move_duration_min` / `move_duration_max`、`move_steps_min` / `move_steps_max`、`arc_strength_min` / `arc_strength_max`：移动轨迹与弧度。
- `price_char_interval_min` / `price_char_interval_max`、`price_stutter_probability` 等：价格输入节奏与偶发停顿。

未配置时 Bot 使用内置默认拟人化参数；仅需关闭时设置 `"humanize": { "enabled": false }` 即可。

### 5. 环境变量速查

| 变量 | 作用 |
|------|------|
| `BIDKING_HOME` | 项目根目录（需含 `configs/` 与 `data/`）。 |
| `BIDKING_SELF_USER_UID` | 覆盖 `board_snapshot.self_user_uid`。 |
| `BIDKING_SELF_NAME_SUBSTRING` | 覆盖 `board_snapshot.self_name_substring`。 |

---

## 三、升级自 `v.1.11` 时的建议检查清单

1. 将 **`board_snapshot.path`** 从本机绝对路径改为 **`data/board_snapshot.json`**（或继续用绝对路径），并确认 **`BIDKING_HOME`** 或工作目录指向含 `data/` 的工程根。
2. 若使用隐秘拍卖地图 **440 / 450**：在对应 **`pricing.maps`** 文件中确认 **`secret_auction_rank_opponent_multipliers`** 与 **`enable_opponent_bid_adjustment`** 是否符合预期；全局 `config.json` 中的 **`pricing.enable_opponent_bid_adjustment`** 会与地图文件联动。
3. 填写 **`self_user_uid` / `self_name_substring`**（或环境变量），否则依赖「己方」的逻辑可能无法正确区分玩家。
4. 鉴影工具启动时按需选择 **通用** 或 **艾哈迈德(快递站特化）** 看板角色。

---

*文档生成依据：`git diff v.1.11..HEAD` 与提交说明整理；标签以仓库实际为准：`v.1.11`。*
