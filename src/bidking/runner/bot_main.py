"""艾哈迈德路径入口：交互+解析+分析+策略+UI。

最小化包装：当前直接调用历史内核 ``interaction._legacy_bot.run_loop``，并
在启动时安装 ``bridge`` 与日志通道。后续可逐步接管为分层调用。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config.paths import config_overlay_path
from ..interaction import _legacy_bot as _bot
from ._common import configure_logging, install_snapshot_file_writer, load_all


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="BidKing bot — 统一交互循环；ahmad_premium 可走 OCR 或 board_snapshot，由配置决定",
    )
    parser.add_argument(
        "--app-log",
        default="bidking_fresh_bot.log",
        help="应用主日志文件（默认 cwd/bidking_fresh_bot.log）",
    )
    args = parser.parse_args(argv)

    runtime, _pricing = load_all()
    configure_logging(runtime, app_log_path=Path(args.app_log).resolve())
    install_snapshot_file_writer(runtime)

    cfg_path = config_overlay_path()

    if hasattr(_bot, "run_loop"):
        _bot.run_loop(cfg_path)
    else:
        raise SystemExit("interaction._legacy_bot.run_loop 不可用，请检查迁移结果。")


if __name__ == "__main__":
    main()
