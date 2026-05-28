# -*- coding: utf-8 -*-
"""画板快照定价流水线上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple


@dataclass
class SnapshotPricingContext:
    """``build_snapshot_pricing_dict`` 流水线中间态。"""

    board_snapshot: Dict[str, Any]
    snap_full: Dict[str, Any]
    raw: Dict[str, Any]
    map_id: int
    current_round: int
    csv_cells_for_est: Dict[str, float]
    board_snapshot_config: Optional[Dict[str, Any]] = None
    self_uid_infer_detail: Dict[str, Any] = field(default_factory=dict)

    total_f: float = 0.0
    vacant_num: int = 0
    vacant_src: str = ""
    vacant_adj: int = 0
    vacant_pts_base: float = 0.0

    u_orange: int = 0
    u_gr: int = 0
    u_red: int = 0
    u_early: int = 0
    qg_early: str = ""
    pq_early: Set[int] = field(default_factory=set)

    cq4: int = 0
    cq5: int = 0
    cq6: int = 0
    tier_extra_val: float = 0.0
    tier_extra_cells: int = 0
    kcw_val: float = 0.0
    kcw_geo: int = 0
    uc_vacant_subtract: int = 0
    uc_excess_detail: Dict[str, Any] = field(default_factory=dict)
    phantom_unknown_detail: Dict[str, Any] = field(default_factory=dict)

    est_orange: float = 0.0
    est_gold_red: float = 0.0
    est_red: float = 0.0

    pts: float = 0.0
    pts_floor: float = 0.0
    pts_ceiling: float = 0.0
    q14_grid_known: bool = False
    early_pts_blended_with_random_avg: bool = False

    st_ev: Any = None
