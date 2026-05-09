"""艾莎路径入口：交互+(snapshot bridge)+策略+UI。"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config.paths import config_overlay_path
from ..interaction._legacy_bot import run_aisha_loop
from ._common import configure_logging, install_snapshot_file_writer, load_all


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="BidKing bot — 兼容入口，等价于强制 aisha_premium 的统一主循环",
    )
    parser.add_argument(
        "--app-log",
        default="fresh_aisha_bot.log",
        help="应用主日志文件（默认 cwd/fresh_aisha_bot.log）",
    )
    args = parser.parse_args(argv)

    runtime, _pricing = load_all()
    configure_logging(runtime, app_log_path=Path(args.app_log).resolve())
    install_snapshot_file_writer(runtime)

    cfg_path = config_overlay_path()

    run_aisha_loop(cfg_path)


if __name__ == "__main__":
    main()
