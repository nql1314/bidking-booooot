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
python -m bidking.runner.bot_main      # 艾哈迈德路径
python -m bidking.runner.aisha_main      # 艾莎路径
python -m bidking.runner.viewer_main     # 纯看板（tail / replay）
python -c "from bidking.ui.app import main; main()"   # tkinter 总控 GUI
python -m unittest discover -s tests -t .             # 测试
```

## 数据

`data/` 下放 CSV/HTML 资源：`item_prices.csv`、`drop_table_weights.csv`、
`calculator_data_merged.csv`、`map_quality_avg_out.csv`、
`物品轮廓爆率推断器.html`。

## Windows 打包（GUI）

生成两个 GUI 启动程序：

- `bot_runner.exe`（总控 GUI）
- `grid_view.exe`（看板/回放）

```powershell
cd D:/workzone/bidking-booooot
.\scripts\build_windows.ps1
```

可选参数：

- `-NoObfuscation`：禁用 PyArmor 混淆，只做普通 PyInstaller 打包

说明：

- 默认会尝试安装并使用 PyArmor 先混淆 `src/bidking`，再交给 PyInstaller 打包；
- 脚本会先执行 `pip install -e ".[build]"`，确保 `pyautogui` 等运行依赖一并打入 exe；
- 若 PyArmor 不可用，会自动降级为普通打包（仍不直接携带 `.py` 源文件）。

兼容性提示：

- 产物是 **Windows x64 单文件 exe**，目标机器通常不需要额外安装 Python；
- 仅保证同平台（Windows）运行，跨平台（Linux/macOS）需分别打包。

## 不在范围

- 拉文（Raven）相关分支 —— `pricing/strategy.py` 仅保留接口位
