"""调试落盘：把回合截图/裁剪/OCR 文本/上下文存到 runs/<ts>/。

旧入口 ``fresh_bidking_bot.save_round_debug_bundle`` 的等价封装；为了避免
循环依赖，本模块仅提供 *最小* 实现。复杂的版本仍可由 interaction 层在内部
实现，并通过此模块统一出口。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, Optional


def save_round_debug_bundle(
    runs_dir: Path | str,
    *,
    round_no: Optional[int] = None,
    extras: Optional[Mapping[str, Any]] = None,
    images: Optional[Mapping[str, Any]] = None,
    text: Optional[str] = None,
) -> Path:
    """落盘一份调试包；返回目录路径。

    - ``images``: ``{name: PIL.Image-like}``，需要 ``Pillow`` 才能保存（为可选）。
    - ``extras``: 任意 JSON-able 元数据。
    - ``text``: 长文本（如 OCR 识别原文）。
    """
    base = Path(runs_dir)
    base.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    name = f"round_{round_no}_{ts}" if round_no is not None else f"snap_{ts}"
    target = base / name
    target.mkdir(parents=True, exist_ok=True)

    if extras is not None:
        try:
            (target / "meta.json").write_text(
                json.dumps(extras, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (TypeError, ValueError):
            (target / "meta.txt").write_text(repr(extras), encoding="utf-8")

    if text is not None:
        (target / "ocr.txt").write_text(text, encoding="utf-8")

    if images:
        for key, img in images.items():
            save = getattr(img, "save", None)
            if save is None:
                continue
            try:
                save(target / f"{key}.png")
            except OSError:
                continue

    return target
