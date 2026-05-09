# 按地图覆盖的价格配置

每个文件名为 `<map_id>.json`（如 `1.json`、`2.json`），与 `configs/pricing.json` 同 schema。

加载时由 `bidking.config.pricing.resolve_for(map_id)` 做**深合并**：
全局 `pricing.json` 为基底，`<map_id>.json` 内同名字段覆盖叶子值；dict
按 key 递归合并；list 整体替换。

示例 `1.json`：

```json
{
  "ahmad_premium": {
    "round1_base_factor": 1.2,
    "grid_rate_w": { "red": 5.2 }
  }
}
```
