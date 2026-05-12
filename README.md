# bidking-booooot

将历史项目 `bidking-bot`（自动化 + OCR + 出价循环）与 `bidking-master`（日志解析 + 画板/估价）整合到一个**分层架构**：

```
src/bidking/
├── interaction/  # 第1层 游戏交互 (window/ocr/input/observe/round_flow/text_patch)
├── parsing/      # 第2层 日志解析 + 数据 (events/state/processors/handlers)
├── analysis/     # 第3层 数据分析 (snapshot/grid_overlay/quality_stats/scan_inference/unknown_value/map_avg_csv)
├── pricing/      # 第4层 出价策略 (ahmad/aisha/post_process/strategy)
├── ui/           # 第5层 tkinter UI 与画板
├── logsys/       # 第6层 日志 (app_log/perf_log/ocr_log/mouse_log/debug_dump)
├── config/       # 第7层 配置 (runtime + pricing + 按地图覆盖)
├── bridge/       # 跨层胶水：snapshot_store + 可选文件写出
└── runner/       # 入口：bot_main / aisha_main / viewer_main
```

## Python 与 OCR 依赖

- **Python 3.13**：PyPI 上 `rapidocr-onnxruntime` 无适用 wheel（要求 `python_version < 3.13`）。本项目 `pyproject.toml` 在 3.13 下会改为依赖 **`rapidocr`**；运行时 OCR 统一走 `bidking.interaction.ocr.get_engine()`（含 `_legacy_bot` / 对手价 OCR），两种包名任选其一装好即可。


**本仓库自建 venv（任意兼容版本）：**

```powershell
cd D:/workzone/bidking-booooot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```


## 配置

- `configs/runtime.json` —— 游戏必备：窗口/截图/OCR/automation/timing/clicks/debug（`advisor.price_config_path` 建议为与 runtime 同目录的 `pricing.json`，勿写 `configs/pricing.json` 以免拼成 `configs/configs/...`）
- `configs/pricing.json` —— 全局默认价格策略
- `configs/pricing.maps/<map_id>.json` —— 按地图深合并覆盖

## 入口

未 `pip install -e .` 时请先 `cd` 到仓库根目录并设置 `PYTHONPATH=src`。

```powershell
python -m bidking.runner.viewer_main     # 纯看板（tail / replay）
python -c "from bidking.ui.app import main; main()"   # tkinter 总控 GUI
python -m unittest discover -s tests -t .             # 测试
python -m bidking.runner.bot_main      # 艾哈迈德路径
python -m bidking.runner.aisha_main      # 艾莎路径
```

## 数据

`data/` 下放 CSV/HTML 资源：`item_prices.csv`、`drop_table_weights.csv`、
`calculator_data_merged.csv`、`map_quality_avg_out.csv`、
`物品轮廓爆率推断器.html`。

## Windows 打包（GUI）

### 打包方式

在 **Windows x64** 上，用 PowerShell 在仓库根目录执行打包脚本，会生成一个 **单文件、无控制台窗口** 的 GUI 程序：

| 产物 | 说明 |
|------|------|
| `dist/grid_view.exe` | 画板看板 / 日志 tail·回放（`bidking.runner.viewer_main`）；启动页含两个标签：「启动看板」与「策略配置」（出价参数 + 棋盘快照 + 主配置 JSON / 地图自定义 JSON 编辑），「启动看板」里还有「启动 Bot 总控（谨慎使用）」按钮，在独立窗口打开 `bidking.ui.app` 总控 |

**前置条件**

- 本机已安装与上文一致的 **Python**（建议单独 `venv`，避免污染全局环境）。
- 当前 shell 能调用到该 Python（脚本内部会执行 `pip install` / `PyInstaller`）。

**命令**

```powershell
cd D:/workzone/bidking-booooot
# 可选：.\.venv\Scripts\Activate.ps1
.\scripts\build_windows.ps1
```

**可选脚本参数**

- `-NoObfuscation`：跳过 PyArmor，仅用 PyInstaller 打包（调试或 PyArmor 不可用时常用）。
- `-VersionTag <字符串>`：仅在构建结束时的日志里打印版本标记，**不会**改写 exe 文件名。

**脚本会做什么（摘要）**

- `pip install -e ".[build]"`，再安装/升级 `pyinstaller`（及可选 `pyarmor`）。
- 默认尝试用 PyArmor 混淆 `src/bidking` 后再打包；失败则自动回退为普通 PyInstaller 构建。
- PyInstaller 使用 `--onefile --windowed`，并把 `pyautogui`、`rapidocr` 等 GUI/OCR 相关依赖一并收集进 exe。

**兼容性**

- 目标机器一般 **无需安装 Python**；仅保证在 **Windows x64** 上运行。Linux/macOS 需各自环境单独打包。

### exe 使用方式

打包脚本**不会**把仓库里的 `configs/`、`data/` 打进 exe。运行期仍按 `bidking.config.paths` 解析：**配置与 CSV 等资源需与 exe 放在可用的「项目根」下**。

**推荐目录布局**（将 `dist` 里生成的 exe 拷到仓库根目录，与下面两个目录并列即可）：

```text
<项目根>/
├── grid_view.exe
├── configs/            # runtime.json、pricing.json、config.json 等
└── data/               # item_prices.csv 等数据文件
```

**启动方式**

- **双击 / 命令行**：在资源管理器中双击，或在 PowerShell 里先 `cd` 到上述 **项目根** 再运行 `.\grid_view.exe`，保证**当前工作目录**就是含 `configs` 与 `data` 的根目录。
- **环境变量 `BIDKING_HOME`**：若 exe 放在别的路径、或快捷方式导致工作目录不对，可设置 `BIDKING_HOME` 为 **项目根的绝对路径**（该目录下必须同时存在 `configs` 与 `data` 子目录）。

**程序分工**

- `grid_view.exe`：看板；默认会尝试游戏默认的 `Player.log` 路径，也会尝试 **当前工作目录** 下的 `Player.log` / `Player - 副本.log`。若日志不在默认路径，可在界面中自选日志文件（与源码运行行为一致）。
- **策略配置**：在 `grid_view.exe` 启动页的「策略配置」标签里编辑「出价参数」、「棋盘快照（己方 UID / 名称关键字）」、「主配置 overlay JSON」与「地图自定义 JSON」；点对应「保存」按钮（或勾选「编辑合法后自动保存」）即可写入 `configs/`。**Bot 总控窗口不再自带这些表单**，启动 bot 前须先在此配置完毕。
- **Bot 总控（自动化）**：原 `bot_runner.exe` 的 `bidking.ui.app` 入口已合并到 `grid_view.exe` 启动页 —— 点「启动 Bot 总控（谨慎使用）」即可切换到总控 GUI；**会接管鼠标/键盘做自动竞拍，启动前请核对 `configs/` 与游戏分辨率**。总控只保留「选图 / 重复次数 / 自动化脚本 / 道具回合 / 启动停止 / 日志」，其余字段一律从磁盘读取。

**分发给别人时**：除 exe 外，请一并提供（或说明从仓库拷贝）完整的 **`configs/`** 与 **`data/`**，并按上文设置工作目录或 `BIDKING_HOME`。

## 不在范围

- 拉文（Raven）相关分支 —— `pricing/strategy.py` 仅保留接口位
