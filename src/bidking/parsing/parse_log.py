#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BidKing 游戏日志解析器 — CLI 入口

用法（需在含 ``bidking`` 包的源码树或已安装包的环境中运行）::

  python -m bidking.parsing.parse_log           # 自动查找日志文件，批量处理
  python -m bidking.parsing.parse_log --tail    # 实时监听模式
  python -m bidking.parsing.parse_log --log <路径>
  python -m bidking.parsing.parse_log --output out.txt

业务逻辑在 :mod:`bidking.parsing._legacy_runner`，本模块仅负责参数解析与控制台编码。
"""

from __future__ import annotations

import argparse
import os
import sys

from ._legacy_runner import run
from .constants import CSV_PATH, DEFAULT_GAME_LOG, LOCAL_LOG


def main() -> None:
    parser = argparse.ArgumentParser(
        description='BidKing 游戏日志解析器 — 逐回合输出物品判断信息',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python -m bidking.parsing.parse_log                 # 自动查找日志，批量处理
  python -m bidking.parsing.parse_log --tail          # 实时监听游戏日志
  python -m bidking.parsing.parse_log --log Player.log
  python -m bidking.parsing.parse_log --output result.txt""",
    )
    parser.add_argument(
        '--log', default=None,
        help='日志文件路径（默认：优先 ./Player.log，其次游戏目录）',
    )
    parser.add_argument(
        '--csv', default=CSV_PATH,
        help=f'物品价格 CSV 路径（默认: {CSV_PATH}）',
    )
    parser.add_argument(
        '--tail', action='store_true',
        help='实时监听模式：持续读取追加的日志行',
    )
    parser.add_argument(
        '--output', default=None,
        help='结果输出文件路径（默认输出到控制台）',
    )
    args = parser.parse_args()

    log_path = args.log
    if log_path is None:
        if os.path.exists(LOCAL_LOG):
            log_path = LOCAL_LOG
        elif os.path.exists(DEFAULT_GAME_LOG):
            log_path = DEFAULT_GAME_LOG
        else:
            print(
                f"错误: 找不到日志文件。请用 --log 参数指定路径。\n"
                f"  尝试过: {LOCAL_LOG}\n"
                f"          {DEFAULT_GAME_LOG}",
                file=sys.stderr,
            )
            sys.exit(1)

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"错误: 找不到CSV文件: {csv_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as out_file:
            try:
                run(log_path, csv_path, tail=args.tail, out=out_file)
            except KeyboardInterrupt:
                print("\n已停止监听。", file=sys.stderr)
        print(f"结果已写入: {args.output}", file=sys.stderr)
    else:
        if sys.platform == 'win32':
            import io as _io
            sys.stdout = _io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
        else:
            sys.stdout.reconfigure(line_buffering=True)
        try:
            run(log_path, csv_path, tail=args.tail, out=sys.stdout)
        except KeyboardInterrupt:
            print("\n已停止监听。", file=sys.stderr)


if __name__ == '__main__':
    main()
