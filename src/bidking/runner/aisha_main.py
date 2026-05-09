"""艾莎路径入口：交互+(snapshot bridge)+策略+UI。"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config.paths import runtime_path
from ..interaction import _legacy_aisha as _aisha
from ._common import configure_logging, install_snapshot_file_writer, load_all


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="BidKing artistic bot — Aisha path (snapshot-driven)",
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

    cfg_path = runtime.source_path or runtime_path()

    if hasattr(_aisha, "run_aisha_loop"):
        _aisha.run_aisha_loop(cfg_path)
    else:
        raise SystemExit("interaction._legacy_aisha.run_aisha_loop 不可用，请检查迁移结果。")


if __name__ == "__main__":
    main()
