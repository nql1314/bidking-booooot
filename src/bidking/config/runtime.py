"""runtime.json + config.json 加载与轻量类型化访问。

默认读取 ``configs/runtime.json`` 为基底，再与 ``configs/config.json`` **深合并**
（后者覆盖前者）。显式传入 ``path`` 时仅加载该文件（供测试或单文件模式）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import config_overlay_path, runtime_path


@dataclass
class RuntimeConfig:
    raw: Dict[str, Any]
    source_path: Optional[Path] = None

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def safety(self) -> Dict[str, Any]:
        return self.raw.get("safety", {})

    @property
    def window(self) -> Dict[str, Any]:
        return self.raw.get("window", {})

    @property
    def capture(self) -> Dict[str, Any]:
        return self.raw.get("capture", {})

    @property
    def ocr(self) -> Dict[str, Any]:
        return self.raw.get("ocr", {})

    @property
    def advisor(self) -> Dict[str, Any]:
        return self.raw.get("advisor", {})

    @property
    def pricing(self) -> Dict[str, Any]:
        return self.raw.get("pricing", {})

    @property
    def board_snapshot(self) -> Dict[str, Any]:
        return self.raw.get("board_snapshot", {})

    @property
    def automation(self) -> Dict[str, Any]:
        return self.raw.get("automation", {})

    @property
    def timing(self) -> Dict[str, Any]:
        return self.raw.get("timing", {})

    @property
    def clicks(self) -> Dict[str, Any]:
        return self.raw.get("clicks", {})

    @property
    def debug(self) -> Dict[str, Any]:
        return self.raw.get("debug", {})


def load_runtime(path: Optional[Path | str] = None) -> RuntimeConfig:
    if path is not None:
        p = Path(path).resolve()
        with p.open("r", encoding="utf-8-sig") as fp:
            data = json.load(fp)
        return RuntimeConfig(raw=data, source_path=p)

    from .pricing import deep_merge

    rp = runtime_path()
    cp = config_overlay_path()
    base: Dict[str, Any] = {}
    if rp.is_file():
        with rp.open("r", encoding="utf-8-sig") as fp:
            base = json.load(fp)
    overlay: Dict[str, Any] = {}
    if cp.is_file():
        with cp.open("r", encoding="utf-8-sig") as fp:
            overlay = json.load(fp)
    merged = deep_merge(base, overlay)
    src = cp if cp.is_file() else rp
    return RuntimeConfig(raw=merged, source_path=src.resolve() if src.is_file() else cp.resolve())
