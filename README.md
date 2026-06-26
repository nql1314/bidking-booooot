# bidking-booooot

Steam 游戏《竞拍之王》（BidKing）的**画板看板 + 日志解析 + OCR 自动竞拍**辅助工具。将历史项目 `bidking-bot` 与 `bidking-master` 整合为分层 Python 包（Apache 2.0）。

**免责声明**：本仓库为社区辅助工具，请遵守游戏服务条款与当地法律；自动化操作风险自负。

## 功能

- 读取 `Player.log` 解析对局、技能与出价
- tkinter 画板展示棋盘、估价与回放
- 可选 Bot：pyautogui + rapidocr 驱动窗口自动选图、出价
- 艾哈迈德 / 艾莎两套本地出价策略（`ahmad_premium` / `aisha_premium`）

**开源版不包含**：远程 Bot 开关、社区黑名单同步、快递站暗号协作等需联网或共享玩家数据的特性。

## 架构

```
src/bidking/
├── interaction/  # 游戏交互 (window/ocr/input/round_flow)
├── parsing/      # 日志解析
├── analysis/     # 画板快照、网格、品质统计
├── pricing/      # 出价策略
├── ui/           # tkinter UI 与画板
├── logsys/       # 运行日志
├── config/       # runtime + pricing + 地图覆盖
├── bridge/       # 快照存储
└── runner/       # bot_main / aisha_main / viewer_main
```

## 环境

- **Python 3.13+**
- OCR：`rapidocr` + `onnxruntime`（见 `pyproject.toml`）

```cmd
cd /d D:\workzone\bidking-booooot
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## 首次配置

```cmd
copy /Y configs\config.json.example configs\config.json
```

按需编辑 `configs/config.json`（个人 UID 建议用环境变量 `BIDKING_SELF_USER_UID`，勿提交真实 UID）。

| 文件 | 说明 |
|------|------|
| `configs/runtime.json` | 窗口、截图、OCR、点击坐标、timing（基底配置） |
| `configs/config.json` | 用户覆盖层（本地，不入库） |
| `configs/pricing.maps/<档>.json` | 按地图深合并出价参数 |

可选环境变量见 [`.env.example`](.env.example)。

## 入口

```cmd
python -m bidking.runner.viewer_main
python -m pytest -q
```

## 数据

`data/` 含 `item_prices.csv`、`drop_table_weights.csv` 等静态表。版本更新流程见 [`data/版本更新手册.md`](data/版本更新手册.md)。

## Windows 打包

在仓库根目录执行 `scripts\build_windows.ps1`（建议加 `-NoObfuscation`）。产物 `dist/grid_view.exe` **不含** `configs/` 与 `data/`，分发时需一并提供；可用 `BIDKING_HOME` 指定项目根。

## 贡献与安全

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题：[SECURITY.md](SECURITY.md)

## 不在范围

- 拉文（Raven）策略分支 — `pricing/strategy.py` 仅保留接口位
