# -*- coding: utf-8 -*-
"""CLI：将腾讯文档快递黑名单「临时表」同步到「汇总表」。"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from bidking.config.runtime import load_runtime
from bidking.tools.blacklist_sheet_merge import sync_temp_blacklist_to_summary_sheet


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "经腾讯文档 Open API V3 将临时表同步到汇总表（见 docs/tencent_sheet_openapi_v3.md）。"
            "须配置 sheet_merge.book_id、openapi 与 BIDKING_TENCENT_DOCS_ACCESS_TOKEN；"
            "无 token 时仅用 dop-api 预览且无法读取 round/bid。"
            "临时表 A–E：game_uid/uid/name/round/bid，数据自第 4 行。"
        )
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="实际写入汇总表并清理临时表（默认仅预览）",
    )
    p.add_argument(
        "--delete-mode",
        choices=("clear", "delete"),
        default="clear",
        help="临时表清理方式：clear=清空单元格（默认），delete=删行",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=25.0,
        help="拉取/写入 HTTP 超时秒数",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    ok, note, _plan = sync_temp_blacklist_to_summary_sheet(
        load_runtime().raw,
        dry_run=not args.apply,
        timeout=args.timeout,
        delete_mode=args.delete_mode,
    )
    print(note, file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
