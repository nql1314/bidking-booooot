"""runtime.json 加载与轻量类型化访问。

为避免破坏既有大量 ``cfg["a"]["b"]`` 风格的访问，``RuntimeConfig`` 同时
暴露 ``raw`` 字典与若干便利属性。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import runtime_path


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
    p = Path(path) if path else runtime_path()
    with p.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    return RuntimeConfig(raw=data, source_path=p)
