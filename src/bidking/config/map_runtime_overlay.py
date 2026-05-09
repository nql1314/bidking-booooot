"""按当前选中地图合并 ``configs/pricing.maps/<map_id>.json`` 到运行时 config。

GUI 将兜底价、封顶、护栏、``bid_ratio_by_round`` 等写入地图文件；
:func:`merged_runtime_with_map_pricing` 在出价计算前叠加以便与 bot 主配置一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import pricing_map_overlay_path
from .pricing import deep_merge


def merged_runtime_with_map_pricing(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return dict(config)
    auto = config.get("automation")
    auto_d = auto if isinstance(auto, dict) else {}
    mid = str(auto_d.get("selected_map") or auto_d.get("default_map") or "1")
    p: Path = pricing_map_overlay_path(mid)
    if not p.is_file():
        return dict(config)
    try:
        overlay = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(config)
    if not isinstance(overlay, dict):
        return dict(config)
    return deep_merge(dict(config), overlay)
