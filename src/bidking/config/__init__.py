"""第 7 层 · 配置：runtime + pricing（按地图深合并覆盖）。"""

from .paths import (
    board_snapshot_default_path,
    project_root,
    configs_dir,
    data_dir,
    resolve_board_snapshot_path,
    runtime_path,
    config_overlay_path,
    pricing_path,
    pricing_map_overlay_path,
    pricing_map_override_path,
)
from .runtime import (
    RuntimeConfig,
    apply_board_snapshot_env_overrides,
    infer_unknown_contour_shapes_enabled,
    load_runtime,
)
from .pricing import load_pricing, resolve_for, deep_merge
from .map_runtime_overlay import merged_runtime_with_map_pricing

__all__ = [
    "board_snapshot_default_path",
    "project_root",
    "configs_dir",
    "data_dir",
    "resolve_board_snapshot_path",
    "runtime_path",
    "config_overlay_path",
    "pricing_path",
    "pricing_map_overlay_path",
    "pricing_map_override_path",
    "RuntimeConfig",
    "apply_board_snapshot_env_overrides",
    "load_runtime",
    "infer_unknown_contour_shapes_enabled",
    "load_pricing",
    "resolve_for",
    "deep_merge",
    "merged_runtime_with_map_pricing",
]
