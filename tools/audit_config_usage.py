# -*- coding: utf-8 -*-
"""审计 visual_config_schema 字段在 src 中是否被引用。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# 与 generate_visual_config_schema.DEPRECATED_PATHS 保持一致
DEPRECATED_PATHS = frozenset({
    "timing.tool_after_snapshot_poll_seconds",
    "timing.tool_after_wait_seconds",
    "automation.safe_guard_enabled",
    "automation.safe_guard_max_increase_ratio",
    "board_snapshot.self_name_substring",
    "grid_view.fraud_empty_cells_tiling_n",
})


def load_src() -> str:
    parts: list[str] = []
    for p in SRC.rglob("*.py"):
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def path_referenced(path: str, src: str) -> bool:
    if path in src:
        return True
    segments = [s for s in path.split(".") if not s.isdigit()]
    for seg in segments:
        if f'"{seg}"' not in src and f"'{seg}'" not in src:
            return False
    return True


def main() -> None:
    schema = json.loads(
        (ROOT / "configs/visual_config_schema.json").read_text(encoding="utf-8-sig")
    )
    src = load_src()
    unused: list[str] = []
    deprecated_in_schema: list[str] = []
    for field in schema.get("fields", []):
        path = field.get("path", "")
        if not path:
            continue
        if path in DEPRECATED_PATHS:
            deprecated_in_schema.append(path)
            continue
        if not path_referenced(path, src):
            unused.append(path)
    if deprecated_in_schema:
        print(f"Deprecated but still in schema ({len(deprecated_in_schema)}):")
        for p in deprecated_in_schema:
            print(f"  {p}")
    print(f"Unreferenced in src ({len(unused)}):")
    for p in unused:
        print(f"  {p}")


if __name__ == "__main__":
    main()
