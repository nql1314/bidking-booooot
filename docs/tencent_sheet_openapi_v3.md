# 腾讯文档在线表格 Open API V3（BidKing 黑名单同步）

本文说明 BidKing「临时表 → 汇总表」同步所使用的 [腾讯文档 Open API V3 在线表格](https://docs.qq.com/open/document/app/openapi/v3/sheet/overview.html) 接口。V2（`/openapi/sheetbook/v2/...`）已废弃，不再用于读写。

## 前置条件

| 项 | 说明 |
| --- | --- |
| 权限 | `scope.sheet`（读写）或只读场景下 `scope.sheet.readonly` |
| 配置 | `configs/runtime.json` → `sheet_merge.book_id`（即文档 `fileId`） |
| 凭证 | `sheet_merge.openapi.client_id`、`open_id`；`access_token` 放环境变量（默认 `BIDKING_TENCENT_DOCS_ACCESS_TOKEN`） |
| 表结构 | 临时表 `xz3aq0`：A=`game_uid` B=`uid` C=`name` D=`round` E=`bid`；数据自第 4 行 |
| 汇总表 `BB08J2` | A=UID B=昵称 C=次数 D=加入日期 |

申请与授权见 [开放平台入门](https://docs.qq.com/open/document/app/get_started.html)。

## 本项目的 V3 调用一览

实现位于 `src/bidking/tools/tencent_sheet_v3.py`，由 `blacklist_sheet_merge.py` 调用。

| 操作 | 方法 | Path | 说明 |
| --- | --- | --- | --- |
| 读区域 | `GET` | `/openapi/spreadsheet/v3/files/{fileId}/{sheetId}/{range}` | 解析 `gridData.rows`，得到完整 A–E 列 |
| 写区域 | `POST` `batchUpdate` | `/openapi/spreadsheet/v3/files/{fileId}/batchUpdate` | `updateRangeRequest` 写入/清空单元格 |
| 删行 | 同上 | 同上 | `deleteDimensionRequest`，`dimension=ROW` |

公共请求头（所有请求）：

```http
Access-Token: {ACCESS_TOKEN}
Client-Id: {CLIENT_ID}
Open-Id: {OPEN_ID}
Accept: application/json
Content-Type: application/json
```

## 1. 范围查询（读临时表 / 汇总表）

文档：[获取范围内的表格信息](https://docs.qq.com/open/document/app/openapi/v3/sheet/get/get_range.html)

```http
GET https://docs.qq.com/openapi/spreadsheet/v3/files/{fileId}/{sheetId}/A4:E200
```

- `fileId`：配置中的 `book_id`（例 `300000000$CHPaUrsWPlRG`）
- `sheetId`：子表 ID（临时表 `xz3aq0`，汇总表 `BB08J2`）
- `range`：A1 表示法，**不要**带 `sheetId!` 前缀

限制：行数 ≤1000、列数 ≤200、单元格总数 ≤10000。

响应中表格数据在 `data.gridData`：

- `startRow` / `startColumn`：区域起点（**0-based**）
- `rows[].values[].cellValue`：支持 `text`、`number`、`link`

BidKing 将每行转为字符串列表，再按业务规则分类（仅 `round=1` 写入汇总等）。

## 2. 批量更新（写汇总表 / 清空临时表）

文档：[在线表格批量更新](https://docs.qq.com/open/document/app/openapi/v3/sheet/batchupdate/update.html)、[Request 类型](https://docs.qq.com/open/document/app/openapi/v3/sheet/batchupdate/request.html)

```http
POST https://docs.qq.com/openapi/spreadsheet/v3/files/{fileId}/batchUpdate
```

```json
{
  "requests": [
    {
      "updateRangeRequest": {
        "sheetId": "BB08J2",
        "gridData": {
          "startRow": 9,
          "startColumn": 0,
          "rows": [
            {
              "values": [
                { "cellValue": { "text": "884144787915084" } },
                { "cellValue": { "text": "昵称" } },
                { "cellValue": { "text": "3" } },
                { "cellValue": { "text": "2026-05-28" } }
              ]
            }
          ]
        }
      }
    }
  ]
}
```

- `startRow` / `startColumn`：**0-based**（表第 4 行 → `startRow=3`）
- 单次 `batchUpdate` 最多 **5** 个 `requests`；代码会自动分批
- 写入汇总、追加新行、清空 `A:E` 均使用 `updateRangeRequest`

## 3. 删除临时表行

同一 `batchUpdate` 接口，使用 `deleteDimensionRequest`：

```json
{
  "deleteDimensionRequest": {
    "sheetId": "xz3aq0",
    "dimension": "ROW",
    "startIndex": 4,
    "endIndex": 5
  }
}
```

- `startIndex` / `endIndex`：**1-based**，左闭右开 `[start, end)`
- 删除表第 4 行：`startIndex=4`, `endIndex=5`
- CLI `--delete-mode delete` 时启用；失败则回退为清空 `A:E`

## 与 dop-api 的关系

| 来源 | 用途 |
| --- | --- |
| **V3 Open API**（推荐） | 临时表完整五列；汇总表读写；正式同步与预览（需 token） |
| `dop-api/sheet/data` | 仅在没有 token 时作**粗略**预览；压缩块常缺 D/E 列 `round`/`bid`，**不能**作为同步依据 |

## 本地命令

```bash
# 预览（需环境变量 token 才能读到 round/bid）
python -m bidking.tools.blacklist_sheet_sync

# 实际写入并清理临时表
python -m bidking.tools.blacklist_sheet_sync --apply

# 删行而非清空单元格
python -m bidking.tools.blacklist_sheet_sync --apply --delete-mode delete
```

## 配置示例

```json
{
  "sheet_merge": {
    "book_id": "300000000$CHPaUrsWPlRG",
    "temp_tab": "xz3aq0",
    "summary_tab": "BB08J2",
    "temp_read_range": "A4:E500",
    "summary_read_range": "A4:D500",
    "max_sync_bid": 25000,
    "openapi": {
      "client_id": "...",
      "open_id": "...",
      "access_token_env": "BIDKING_TENCENT_DOCS_ACCESS_TOKEN"
    }
  }
}
```

## 业务规则（同步逻辑）

1. **写入汇总**：有 `game_uid`、`round == 1`、出价 ≤ `max_sync_bid`
2. **仅清理临时表**：有 `game_uid`，且（`round > 1` 或 出价超阈值）
3. **不处理**：无 `game_uid`（不汇总、不删行）

## 错误排查

| 现象 | 可能原因 |
| --- | --- |
| HTTP 401 | token 过期或未设置环境变量 |
| `ret != 0` | 无 `scope.sheet`、fileId/sheetId 错误 |
| 预览仍无 round/bid | 未配置 token，回退到 dop-api |
| 批量失败 | 单次超过 5 个 request 或单元格超 10000（实现已分批） |

官方索引：[V3 在线表格总览](https://docs.qq.com/open/document/app/openapi/v3/sheet/overview.html)
