# -*- coding: utf-8 -*-
"""getlog.board_pricing 单测（不依赖 tkinter）。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidking.analysis import _board_pricing as bp
from bidking.analysis import grid_overlay as grid_overlay_mod
from bidking.analysis.strategy import common as strategy_common
from bidking.analysis.map_avg_csv import set_map_quality_csv_override
from bidking.analysis.raw_pricing import build_raw_pricing_dict
from bidking.analysis.scan_inference import (
    csv_quality_group_from_possible_set,
    possible_qualities_from_scan_history,
    vacant_early_unit_from_exclusions,
)


def _fill_phantoms_then_expand_log_shapes(
    grid_overlay_mod,
    *,
    game_state,
    manual_shapes,
    phantom_items,
    phantom_quality_pref,
    occupied_cells,
    vacant_manual_suppress,
    max_box_id,
    raw_pricing,
    current_round,
    fraud_cells=None,
):
    """与画板一致：先 ``phantom_vac`` 填充，再日志轮廓扩展。"""
    fill = grid_overlay_mod.compute_vacant_rect_phantom_specs(
        game_state=game_state,
        manual_shapes=manual_shapes,
        phantom_items=phantom_items,
        phantom_quality_pref=phantom_quality_pref,
        occupied_cells=set(occupied_cells),
        vacant_manual_suppress=set(vacant_manual_suppress),
        max_box_id=max_box_id,
        raw_pricing=raw_pricing,
        current_round=current_round,
        fraud_cells=fraud_cells,
        enabled=True,
    )
    log = grid_overlay_mod.compute_unknown_contour_log_shapes(
        game_state=game_state,
        manual_shapes=manual_shapes,
        phantom_items=phantom_items,
        phantom_quality_pref=phantom_quality_pref,
        occupied_cells=set(occupied_cells),
        vacant_manual_suppress=set(vacant_manual_suppress),
        max_box_id=max_box_id,
        raw_pricing=raw_pricing,
        phantom_specs=fill.specs,
        recorded_cell_source=fill.recorded_cell_source,
        enabled=True,
    )
    return fill, log


class BoardPricingTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        from bidking.pricing._self_uid_inference import reset_self_uid_inference_state

        reset_self_uid_inference_state()
        self._prev_persist_disable = os.environ.get(
            "BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST"
        )
        os.environ["BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST"] = "1"

    def tearDown(self) -> None:
        import os

        if self._prev_persist_disable is None:
            os.environ.pop("BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST", None)
        else:
            os.environ["BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST"] = (
                self._prev_persist_disable
            )

    def tearDown(self) -> None:
        set_map_quality_csv_override(None)

    def test_csv_quality_group_from_possible_set(self) -> None:
        self.assertIsNone(csv_quality_group_from_possible_set(frozenset()))
        self.assertEqual(
            csv_quality_group_from_possible_set(frozenset(range(1, 7))),
            "all",
        )
        self.assertEqual(csv_quality_group_from_possible_set(frozenset({3})), "q3")
        self.assertEqual(
            csv_quality_group_from_possible_set(frozenset({5, 6})),
            "q5+q6",
        )

    def test_possible_qualities_empty_when_no_unknown_items(self) -> None:
        """无 quality 扫描时：空格品质推断不读 items，仍视为全集。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 3,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": 5,
                },
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        self.assertEqual(
            possible_qualities_from_scan_history(snap),
            frozenset(range(1, 7)),
        )

    def test_possible_qualities_from_scan_history_miss_implies_not_that_tier(self) -> None:
        """品质扫描的 hit_uids 为已揭示该档的物品；未知 uid 未命中则排除该档。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "unk": {
                    "uid": "unk",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["814463533815838"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["814463533815815"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["814463533815811"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["814463533815812"]},
                {"scan_type": "category", "value": 101, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({5, 6}))

    def test_possible_qualities_quality_scan_same_value_last_overwrites(self) -> None:
        """同一 value 多条 quality 扫描时以后出现的 hit_uids 为准。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "unk": {
                    "uid": "unk",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 3, "hit_uids": ["unk"]},
                {"scan_type": "quality", "value": 3, "hit_uids": []},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({1, 2, 4, 5, 6}))

    def test_possible_qualities_no_quality_scans_is_all(self) -> None:
        """无 quality 扫描时未知物品仍可能品质为全集 → 全局 all。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [1, 2, 3, 4],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        all_q = frozenset(range(1, 7))
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, all_q)
        self.assertEqual(csv_quality_group_from_possible_set(poss), "all")

    def test_possible_qualities_scan_only_q56(self) -> None:
        """仅 scan_history：未知 uid 未出现在 1–4 档 hit → 仍可能 5、6。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["814463533815838"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["814463533815815"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["814463533815811"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["814463533815812"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({5, 6}))
        self.assertEqual(csv_quality_group_from_possible_set(poss), "q5+q6")

    def test_vacant_early_unit_csv_miss_is_zero(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        unit, qg, _ = vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw={"q3": 99.0},
            pricing={},
        )
        self.assertEqual(qg, "q5+q6")
        self.assertEqual(unit, 0)

    def test_vacant_early_unit_csv_hit(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 4, "hit_uids": ["x"]},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1.0}, "skill_logs": []}
        raw = {"q5+q6": 1234.56}
        unit, qg, _ = vacant_early_unit_from_exclusions(
            board_snapshot=snap,
            csv_cells_raw=raw,
            pricing={},
        )
        self.assertEqual(qg, "q5+q6")
        self.assertEqual(unit, 1235)

    def test_possible_qualities_intersection_unknown_items(self) -> None:
        """仅 scan_history：各档扫描若仅此且空 hit → 该档不可能；未扫描的档仍可能（与 items 数量无关）。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 0,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
                "b": {
                    "uid": "b",
                    "box_id": 1,
                    "box_id_confirmed": True,
                    "quality": None,
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": []},
                {"scan_type": "quality", "value": 2, "hit_uids": []},
                {"scan_type": "quality", "value": 4, "hit_uids": []},
                {"scan_type": "quality", "value": 5, "hit_uids": []},
                {"scan_type": "quality", "value": 6, "hit_uids": []},
            ],
        }
        snap = {"game_state": gs, "pricing": {"total": 1000.0}, "skill_logs": []}
        poss = possible_qualities_from_scan_history(snap)
        self.assertEqual(poss, frozenset({3}))

    def test_map_skill_total_hidden_for_overlay_from_raw_pricing(self) -> None:
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": 200009, "TotalHitBoxIndex": 42},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
        self.assertEqual(grid_overlay_mod.map_skill_total_hidden_for_overlay({"raw_pricing": raw}), 42)
        self.assertIsNone(grid_overlay_mod.map_skill_total_hidden_for_overlay(None))
        self.assertIsNone(grid_overlay_mod.map_skill_total_hidden_for_overlay({}))

    def test_merged_items_applies_overlay_manual_shape(self) -> None:
        """``grid_overlay.manual_shapes`` 写入定价用外形（w*10+h），含日志 ``shape`` 为空时。"""
        snap = {
            "game_state": {
                "items": {
                    "x": {
                        "uid": "x",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": None,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {"manual_shapes": {"x": [2, 1, 0, 0]}},
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["x"]["shape"], 21)
        self.assertEqual(m["x"].get("_overlay_shape_origin"), "manual")

    def test_merged_items_manual_shape_overrides_log_shape(self) -> None:
        """手动画框覆盖日志已有 ``shape``（拖框改形后与画板一致）。"""
        snap = {
            "game_state": {
                "items": {
                    "x": {
                        "uid": "x",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {"manual_shapes": {"x": [2, 1, 0, 0]}},
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["x"]["shape"], 21)
        self.assertEqual(m["x"].get("_overlay_shape_origin"), "manual")

    def test_merged_items_dict_from_snapshot_reapplies_manual_shapes_on_cache(self) -> None:
        """命中 ``merged_items_dict`` 缓存时仍应用当前 ``manual_shapes``，覆盖陈旧推断外形。"""
        snap = {
            "game_state": {
                "items": {
                    "z": {
                        "uid": "z",
                        "box_id": 55,
                        "box_id_confirmed": False,
                        "shape": None,
                        "quality": 6,
                        "categories": [],
                        "categories_any": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {
                "manual_shapes": {"z": [2, 1, 0, 0]},
                "merged_items_dict": {
                    "z": {
                        "uid": "z",
                        "box_id": 55,
                        "box_id_confirmed": False,
                        "shape": 12,
                        "quality": 6,
                        "categories": [],
                        "categories_any": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
            },
        }
        m = grid_overlay_mod.merged_items_dict_from_snapshot(snap)
        self.assertEqual(m["z"]["shape"], 21)
        self.assertEqual(m["z"].get("_overlay_shape_origin"), "manual")

    def test_pricing_shape_int_for_csv_uses_merged_shape(self) -> None:
        """合并行上的 ``shape`` 须参与 CSV 轮廓匹配。"""
        self.assertEqual(
            bp._pricing_shape_int_for_csv({"shape": 11, "quality": 6}),
            11,
        )
        self.assertEqual(
            bp._pricing_shape_int_for_csv({"shape": 22, "_overlay_shape_origin": "game"}),
            22,
        )
        self.assertIsNone(bp._pricing_shape_int_for_csv({"shape": None}))

    def test_merged_items_applies_phantom_quality_pref(self) -> None:
        """``phantom_quality_pref`` 须并入合并表 ``quality``，定价才按红笔等已知档位计价。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_9": {
                        "uid": "phantom_9",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "manual_shapes": {"phantom_9": [2, 2, 0, 0]},
                "phantom_quality_pref": {"phantom_9": 6},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["phantom_9"].get("quality"), 6)

    def test_merged_items_phantom_without_pref_defaults_quality_5(self) -> None:
        """无 ``phantom_quality_pref`` 条目时与画板缺省金笔一致：合并表 ``quality`` 为 5。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_1": {
                        "uid": "phantom_1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "manual_shapes": {"phantom_1": [1, 1, 0, 0]},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["phantom_1"].get("quality"), 5)

    def test_merged_items_phantom_infer_pref_keeps_quality_none(self) -> None:
        """推断笔偏好 ``_phantom_q_infer``：合并表 ``quality`` 保持 None。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_1": {
                        "uid": "phantom_1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "manual_shapes": {"phantom_1": [1, 1, 0, 0]},
                "phantom_quality_pref": {"phantom_1": "_phantom_q_infer"},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertIsNone(m["phantom_1"].get("quality"))

    def test_merged_items_phantom_default_skips_q5_when_q5_excluded(self) -> None:
        """普查/扫描排除 Q5 时不再缺省写入 Q5（与 ``_phantom_effective_quality`` 一致）。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_1": {
                        "uid": "phantom_1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [5, 6],
                    }
                },
                "manual_shapes": {"phantom_1": [1, 1, 0, 0]},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertIsNone(m["phantom_1"].get("quality"))

    def test_merged_items_phantom_pref_falls_back_q5_when_only_q6_excluded(self) -> None:
        """红笔偏好但仅排除 Q6 时：显式档无效，仍缺省 Q5（与 ``_phantom_effective_quality``）。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_9": {
                        "uid": "phantom_9",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [6],
                    }
                },
                "manual_shapes": {"phantom_9": [2, 2, 0, 0]},
                "phantom_quality_pref": {"phantom_9": 6},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["phantom_9"].get("quality"), 5)

    def test_merged_items_phantom_pref_and_default_blocked_when_q5_q6_excluded(
        self,
    ) -> None:
        """金红皆已排除时：显式红笔与缺省金笔均不写入 ``quality``。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_9": {
                        "uid": "phantom_9",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [5, 6],
                    }
                },
                "manual_shapes": {"phantom_9": [2, 2, 0, 0]},
                "phantom_quality_pref": {"phantom_9": 6},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertIsNone(m["phantom_9"].get("quality"))

    def test_merged_items_applies_unknown_cell_quality_pref(self) -> None:
        """``unknown_cell_quality_pref`` 须并入合并表 ``quality``，与弹窗候选品质手选一致。"""
        snap = {
            "game_state": {
                "items": {
                    "u1": {
                        "uid": "u1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {
                "unknown_cell_quality_pref": {"u1": 5},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertEqual(m["u1"].get("quality"), 5)

    def test_merged_items_unknown_cell_quality_pref_skips_when_price_locked(
        self,
    ) -> None:
        """已精确价 + CID 时不再用候选品质覆盖（与画板 ``_unknown_quality_pref_eligible`` 一致）。"""
        snap = {
            "game_state": {
                "items": {
                    "u1": {
                        "uid": "u1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": 200021,
                        "price": 100,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {
                "unknown_cell_quality_pref": {"u1": 5},
            },
        }
        m = grid_overlay_mod.merged_items_dict(snap)
        self.assertIsNone(m["u1"].get("quality"))

    def test_merged_items_dict_from_snapshot_applies_pref_on_cached_merged(self) -> None:
        """读出缓存 ``merged_items_dict`` 时仍应用 ``phantom_quality_pref``（兼容旧写出）。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_quality_pref": {"phantom_9": 6},
                "merged_items_dict": {
                    "phantom_9": {
                        "uid": "phantom_9",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
            },
        }
        m = grid_overlay_mod.merged_items_dict_from_snapshot(snap)
        self.assertEqual(m["phantom_9"].get("quality"), 6)

    def test_merged_items_dict_from_snapshot_default_q5_on_cached(self) -> None:
        """缓存里 ``quality: null``、且无偏好条目时，读出仍补齐 Q5。"""
        snap = {
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    "phantom_1": {
                        "uid": "phantom_1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "merged_items_dict": {
                    "phantom_1": {
                        "uid": "phantom_1",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
            },
        }
        m = grid_overlay_mod.merged_items_dict_from_snapshot(snap)
        self.assertEqual(m["phantom_1"].get("quality"), 5)

    def test_merged_items_dict_from_snapshot_invalidates_cache_when_manual_confirm_changes(
        self,
    ) -> None:
        """``game_state`` 已写入 ``manual_confirm_item_id`` 但 ``merged_items_dict`` 仍为旧导出时，须全量重合并并投影 CSV 外形/价。"""
        snap = {
            "game_state": {
                "items": {
                    "t1": {
                        "uid": "t1",
                        "box_id": 55,
                        "box_id_confirmed": False,
                        "shape": None,
                        "quality": 6,
                        "categories": [],
                        "categories_any": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": 1033003,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "grid_overlay": {
                "merged_items_dict": {
                    "t1": {
                        "uid": "t1",
                        "box_id": 55,
                        "box_id_confirmed": False,
                        "shape": 12,
                        "quality": 6,
                        "categories": [],
                        "categories_any": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
            },
        }
        m = grid_overlay_mod.merged_items_dict_from_snapshot(snap)
        self.assertEqual(m["t1"].get("shape"), 23)
        self.assertEqual(m["t1"].get("item_cid"), 1033003)
        self.assertEqual(m["t1"].get("price"), 3875)
        self.assertEqual(m["t1"].get("quality"), 3)
        self.assertEqual(m["t1"].get("_overlay_shape_origin"), "game")

    def test_infer_round4_auto_fill_switch_shared(self) -> None:
        from bidking.config.runtime import (
            infer_unknown_contour_shapes_enabled,
            infer_vacant_rect_phantoms_enabled,
        )

        cfg_on = {"pricing": {"infer_vacant_rect_phantoms": True}}
        cfg_off = {"pricing": {"infer_vacant_rect_phantoms": False}}
        legacy_off = {"pricing": {"infer_unknown_contour_shapes": False}}
        self.assertTrue(
            infer_unknown_contour_shapes_enabled(cfg_on, current_round=4)
        )
        self.assertTrue(
            infer_vacant_rect_phantoms_enabled(cfg_on, current_round=4)
        )
        self.assertFalse(
            infer_vacant_rect_phantoms_enabled(cfg_off, current_round=4)
        )
        self.assertFalse(
            infer_unknown_contour_shapes_enabled(legacy_off, current_round=4)
        )

    def test_log_contour_expand_early_round_without_phantom_fill(self) -> None:
        """第 2 回合：不跑 phantom 填充，仅权重价日志扩形。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 2
        st.map_id = 4509
        st.items["log_q3"] = ItemKnowledge(
            uid="log_q3",
            box_id=15,
            box_id_confirmed=False,
            shape=None,
            quality=3,
            excluded_qualities=set(),
            excluded_categories=set(),
        )
        occ = {(1, 5)}
        fill = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=set(occ),
            vacant_manual_suppress=set(),
            max_box_id=20,
            raw_pricing={"event_stats": {}},
            current_round=2,
            enabled=True,
        )
        self.assertEqual(fill.specs, [])
        log = grid_overlay_mod.compute_unknown_contour_log_shapes(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=set(occ),
            vacant_manual_suppress=set(),
            max_box_id=20,
            raw_pricing={"event_stats": {}},
            phantom_specs=[],
            recorded_cell_source={},
            enabled=True,
        )
        self.assertIsInstance(log.inferred_log_shapes, dict)

    def test_log_contour_expand_anchor_not_self_overlap(self) -> None:
        """扩形矩形含锚格时，exclude_uid 下不应因自身锚格被判重叠。"""
        from bidking.analysis.grid_overlay_vacant_zone import build_occupied_cells
        from bidking.parsing.state import ItemKnowledge

        log = ItemKnowledge(
            uid="log_x",
            box_id=15,
            box_id_confirmed=False,
            shape=None,
            quality=3,
        )
        items = {"log_x": log}
        occ_full = build_occupied_cells(
            items=items, phantom_items={}, manual_shapes={}
        )
        self.assertIn((1, 5), occ_full)
        occ_other = build_occupied_cells(
            items=items,
            phantom_items={},
            manual_shapes={},
            exclude_uid="log_x",
        )
        expand_cells = {(1, 5), (1, 6), (2, 5), (2, 6)}
        self.assertFalse(expand_cells & occ_other)

    def test_log_contour_expand_excludes_stale_auto_manual_shapes(self) -> None:
        """排除上轮自动写入的 manual_shapes 后，日志物品仍可重新参与推断。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 2
        st.map_id = 4509
        st.items["log_a"] = ItemKnowledge(
            uid="log_a",
            box_id=15,
            box_id_confirmed=False,
            shape=None,
            quality=3,
            excluded_qualities=set(),
            excluded_categories=set(),
        )
        stale = {"log_a": (4, 3, 2, 1)}
        occ = {(1, 5)}
        kwargs = dict(
            game_state=st,
            manual_shapes=stale,
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=set(occ),
            vacant_manual_suppress=set(),
            max_box_id=20,
            raw_pricing={"event_stats": {}},
            phantom_specs=[],
            recorded_cell_source={},
            enabled=True,
        )
        blocked = grid_overlay_mod.compute_unknown_contour_log_shapes(**kwargs)
        refreshed = grid_overlay_mod.compute_unknown_contour_log_shapes(
            **kwargs,
            exclude_manual_shape_uids={"log_a"},
        )
        self.assertNotIn("log_a", blocked.inferred_log_shapes)
        self.assertIn("log_a", refreshed.inferred_log_shapes)

    def test_auto_expand_log_contour_switch_independent(self) -> None:
        from bidking.config.runtime import (
            auto_expand_log_contour_config_enabled,
            auto_expand_log_contour_enabled,
            infer_vacant_rect_phantoms_config_enabled,
        )

        cfg = {
            "pricing": {"infer_vacant_rect_phantoms": False},
            "grid_view": {"auto_expand_log_contour": True},
        }
        self.assertFalse(infer_vacant_rect_phantoms_config_enabled(cfg))
        self.assertTrue(auto_expand_log_contour_config_enabled(cfg))
        self.assertTrue(auto_expand_log_contour_enabled(cfg, current_round=4))
        self.assertTrue(auto_expand_log_contour_enabled(cfg, current_round=3))
        self.assertTrue(
            auto_expand_log_contour_config_enabled(
                {"grid_view": {"auto_expand_log_items_on_discovery": True}}
            )
        )

    def test_infer_vacant_rect_phantoms_enabled_from_raw(self) -> None:
        from bidking.config.runtime import infer_vacant_rect_phantoms_enabled

        self.assertTrue(infer_vacant_rect_phantoms_enabled({"pricing": {}}))
        self.assertFalse(
            infer_vacant_rect_phantoms_enabled(
                {"pricing": {"infer_vacant_rect_phantoms": False}}
            )
        )
        self.assertFalse(
            infer_vacant_rect_phantoms_enabled({"pricing": {}}, current_round=3)
        )
        self.assertTrue(
            infer_vacant_rect_phantoms_enabled({"pricing": {}}, current_round=4)
        )
        self.assertTrue(
            infer_vacant_rect_phantoms_enabled({"pricing": {}}, current_round=5)
        )

    def test_vacant_rect_phantom_specs_round4_solid_region(self) -> None:
        """第 4 回合、Q1–Q4 已扫且低阶轮廓齐：实心空置矩形生成 phantom_vac 与唯一品质/候选。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        _, csv_items = bp._load_item_prices_db()
        excl_q = {1, 2, 3, 4}
        pick_shape: int | None = None
        pick_quality: int | None = None
        pick_confirm: int | None = None
        for sh in sorted({i.shape for i in csv_items}):
            pool = [
                i
                for i in csv_items
                if i.shape == sh
                and 1 <= int(i.quality) <= 6
                and int(i.quality) not in excl_q
            ]
            if len(pool) != 1 or int(pool[0].item_id) <= 0:
                continue
            pick_shape = int(sh)
            pick_quality = int(pool[0].quality)
            pick_confirm = int(pool[0].item_id)
            break
        self.assertIsNotNone(pick_shape, "need a shape with single Q5/Q6 quality in CSV")
        assert pick_shape is not None and pick_quality is not None
        from bidking.analysis._shape_wh import shape_wh_from_snapshot

        w, h = shape_wh_from_snapshot(pick_shape)

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            uid = f"log_q{q}"
            st.items[uid] = ItemKnowledge(
                uid=uid,
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        dr, dc = 3, 3
        occ = {(r, c) for r, c in anchors}
        for pad_r in range(-1, h + 1):
            for pad_c in range(-1, w + 1):
                r, c = dr + pad_r, dc + pad_c
                if not (0 <= r < 10 and 0 <= c < 10):
                    continue
                if dr <= r < dr + h and dc <= c < dc + w:
                    continue
                occ.add((r, c))
        max_box_id = (dr + h) * 10 + (dc + w)
        for bid in range(max_box_id + 1):
            r, c = bid // 10, bid % 10
            if r < dr - 1 or r > dr + h or c < dc - 1 or c > dc + w:
                occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {f"q{pick_quality}_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        self.assertEqual(len(specs), 1)
        sp = specs[0]
        self.assertTrue(sp.uid.startswith(grid_overlay_mod.AUTO_VACANT_RECT_PHANTOM_PREFIX))
        self.assertEqual((sp.w, sp.h, sp.dc, sp.dr), (w, h, dc, dr))
        self.assertEqual(sp.quality, pick_quality)
        self.assertEqual(sp.manual_confirm_item_id, pick_confirm)

    def test_vacant_rect_phantom_skips_bottom_boundary_1xn(self) -> None:
        """贴棋盘底边的 1×n 横条不生成 phantom_vac（外形易误判）。"""
        from bidking.analysis.grid_overlay_dims import GRID_COLS, GRID_ROWS
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            uid = f"log_q{q}"
            st.items[uid] = ItemKnowledge(
                uid=uid,
                box_id=r * GRID_COLS + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        w, h, dc = 3, 1, 2
        dr = 9
        max_box_id = (dr + h) * GRID_COLS + (dc + w - 1)
        occ = {(r, c) for r, c in anchors}
        for pad_r in (-1, h):
            for pad_c in range(-1, w + 1):
                r, c = dr + pad_r, dc + pad_c
                if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                    if not (dr <= r < dr + h and dc <= c < dc + w):
                        occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        prefix_bottom = max_box_id // GRID_COLS
        bottom_uids = {
            s.uid for s in specs if s.h == 1 and s.dr + s.h - 1 >= prefix_bottom
        }
        self.assertEqual(bottom_uids, set())

    def test_vacant_rect_pass2_6x1_corridor_strip(self) -> None:
        """上下夹住的 6×1 横条：第 1 步不得拆掉两端，第 2 步应整段推断为 phantom_vac。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        w, h, dc, dr = 6, 1, 2, 5
        occ = {(r, c) for r, c in anchors}
        for c in range(dc, dc + w):
            occ.add((dr - 1, c))
            occ.add((dr + 1, c))
        max_box_id = (dr + 1) * 10 + (dc + w - 1)
        for bid in range(max_box_id + 1):
            r, c = bid // 10, bid % 10
            if dr <= r < dr + h and dc <= c < dc + w:
                continue
            occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        six_by_one = [s for s in specs if (s.w, s.h) == (w, h)]
        self.assertEqual(len(six_by_one), 1)
        sp = six_by_one[0]
        self.assertEqual((sp.w, sp.h, sp.dc, sp.dr), (w, h, dc, dr))
        self.assertTrue(sp.uid.startswith(grid_overlay_mod.AUTO_VACANT_RECT_PHANTOM_PREFIX))

    def test_vacant_rect_pass1_enclosed_1x1_deferred_emit(self) -> None:
        """四面围住的孤立 1×1 先作临时占格，2/3 步后再输出幽灵。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            uid = f"log_q{q}"
            st.items[uid] = ItemKnowledge(
                uid=uid,
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        pocket = (2, 2)
        pr, pc = pocket
        max_box_id = 35
        occ = {(r, c) for r, c in anchors}
        for bid in range(max_box_id + 1):
            r, c = bid // 10, bid % 10
            if (r, c) != pocket:
                occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        one_by_one = [s for s in specs if s.w == 1 and s.h == 1]
        self.assertEqual(len(one_by_one), 1)
        lp = one_by_one[0]
        self.assertEqual((lp.w, lp.h, lp.dc, lp.dr), (1, 1, pc, pr))

    def test_vacant_rect_pass5_merge_adjacent_1x1_phantoms(self) -> None:
        """第 6 步：相邻 1×1 幽灵并集为矩形时合并，合并结果继续重复。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        pockets = [(1, 3), (1, 4), (1, 5)]
        occ = {(r, c) for r, c in anchors}
        for pr, pc in pockets:
            occ.update({(pr - 1, pc), (pr + 1, pc)})
        occ.update({(1, 2), (1, 6)})
        max_box_id = 2 * 10 + 5
        for bid in range(max_box_id + 1):
            r, c = bid // 10, bid % 10
            if (r, c) not in pockets:
                occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        self.assertEqual(len(specs), 1)
        sp = specs[0]
        self.assertEqual((sp.w, sp.h, sp.dc, sp.dr), (3, 1, 3, 1))

    def test_vacant_rect_pass3_rank_prefers_squarer_rect(self) -> None:
        """第 3 步 tie-break：方度优先，3×3 > 2×5/5×2，同 min 时面积更大者优先。"""
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _greedy_expand_rect_candidates,
            _vacant_rect_rank_key,
        )

        rk = _vacant_rect_rank_key
        self.assertGreater(rk(3, 3), rk(2, 5))
        self.assertGreater(rk(3, 3), rk(5, 2))
        self.assertGreater(rk(2, 2), rk(1, 4))
        self.assertGreater(rk(4, 3), rk(3, 3))

        work = {
            (11, 0), (11, 1), (11, 2), (11, 3), (11, 4),
            (12, 0), (12, 1), (12, 2), (12, 3), (12, 4),
            (13, 0), (13, 1), (13, 2),
        }
        top = _greedy_expand_rect_candidates(work, work, min_bbox_area=1)[0]
        self.assertEqual(top[:2], (3, 3))

    def test_vacant_rect_post4_shrink_bottom_fraud_row(self) -> None:
        """含底行诈骗格时缩回仍不含诈骗的实心矩形（如 4×3 → 4×2）。"""
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _shrink_rect_phantom_bbox_excluding_fraud,
        )

        bbox = (4, 3, 1, 9)
        fraud = {(11, c) for c in range(1, 5)}
        shrunk = _shrink_rect_phantom_bbox_excluding_fraud(
            bbox, fraud, min_bbox_area=1
        )
        self.assertEqual(shrunk, (4, 2, 1, 9))

    def test_vacant_rect_post4_shrink_non_solid_good_returns_none(self) -> None:
        """非诈骗格不成实心矩形时无法缩回。"""
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _shrink_rect_phantom_bbox_excluding_fraud,
        )

        bbox = (3, 3, 0, 0)
        fraud = {(0, 0), (0, 1), (1, 0)}
        self.assertIsNone(
            _shrink_rect_phantom_bbox_excluding_fraud(bbox, fraud, min_bbox_area=1)
        )

    def test_vacant_rect_pass3_greedy_on_geometric_vacant(self) -> None:
        """第 3 步：几何空置（含原会被标为诈骗的格）上贪心可扩出完整 3×3。"""
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _greedy_expand_rect_candidates,
        )

        dr, dc = 5, 5
        ring = {
            (dr, dc),
            (dr, dc + 1),
            (dr, dc + 2),
            (dr + 1, dc),
            (dr + 1, dc + 2),
            (dr + 2, dc),
            (dr + 2, dc + 1),
            (dr + 2, dc + 2),
        }
        geo_work = ring | {(dr + 1, dc + 1)}
        top = _greedy_expand_rect_candidates(geo_work, geo_work, min_bbox_area=1)[0]
        self.assertEqual(top[:2], (3, 3))

    def test_vacant_rect_pass3_from_pricing_context_bottom_block(self) -> None:
        """pricing_context：几何推断可出幽灵；步骤 4 后完全落在诈骗格内的幽灵被剔除。"""
        import json
        from pathlib import Path

        from bidking.analysis.fraud_empty_cells import (
            fraud_empty_cells_for_algorithm,
            fraud_placed_items_from_merged_items,
        )
        from bidking.analysis.grid_overlay_dims import GRID_COLS
        from bidking.parsing.state import GameState, ItemKnowledge
        from bidking.ui.grid._grid_overlay_payload import (
            max_anchor_box_id_from_overlay_ui,
        )

        path = Path(__file__).resolve().parents[2] / "data" / "pricing_context.json"
        if not path.is_file():
            self.skipTest("pricing_context.json missing")
        data = json.loads(path.read_text(encoding="utf-8"))
        bs = data["board_snapshot"]
        go = bs["grid_overlay"]
        gs = bs["game_state"]
        occ_bids = set(go["occupied_cell_bids"])
        raw_manual = go.get("manual_shapes") or {}
        manual = dict(raw_manual) if isinstance(raw_manual, dict) else {}
        merged = go.get("merged_items_dict") or gs.get("items") or {}
        for uid, sh in list(manual.items()):
            if not str(uid).startswith(grid_overlay_mod.AUTO_VACANT_RECT_PHANTOM_PREFIX):
                continue
            w, h, dc, dr = (int(sh[0]), int(sh[1]), int(sh[2]), int(sh[3]))
            for ddr in range(h):
                for ddc in range(w):
                    occ_bids.discard((dr + ddr) * GRID_COLS + (dc + ddc))
            manual.pop(uid, None)

        st_items = {}
        for uid, raw_item in merged.items():
            st_items[str(uid)] = ItemKnowledge(
                uid=str(uid),
                box_id=raw_item.get("box_id"),
                box_id_confirmed=bool(raw_item.get("box_id_confirmed")),
                shape=raw_item.get("shape"),
                quality=raw_item.get("quality"),
            )
        limit = max_anchor_box_id_from_overlay_ui(st_items, {})
        occ_set = {(b // GRID_COLS, b % GRID_COLS) for b in occ_bids}
        placed = fraud_placed_items_from_merged_items(merged)
        fraud = fraud_empty_cells_for_algorithm(
            "tiling_strict", occ_set, limit, placed
        )
        st = GameState()
        st.current_round = 4
        st.map_id = gs.get("map_id")
        for uid, raw_item in merged.items():
            st.items[str(uid)] = ItemKnowledge(
                uid=str(uid),
                box_id=raw_item.get("box_id"),
                box_id_confirmed=bool(raw_item.get("box_id_confirmed")),
                shape=raw_item.get("shape"),
                quality=raw_item.get("quality"),
            )
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset()))
        kw = dict(
            game_state=st,
            manual_shapes=manual,
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ_set,
            vacant_manual_suppress=set(),
            max_box_id=limit,
            raw_pricing=data.get("raw") or {},
            current_round=4,
            enabled=True,
        )
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _phantom_spec_cells,
        )

        specs_geo = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            **kw, fraud_cells=set()
        ).specs
        self.assertTrue(
            specs_geo,
            "expected geometric vacant-rect phantoms before fraud filter",
        )
        specs_filtered = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            **kw, fraud_cells=fraud
        ).specs
        for spec in specs_filtered:
            cells = _phantom_spec_cells(spec)
            self.assertFalse(
                cells & fraud,
                "phantom %s must not overlap fraud cells after trim" % spec.uid,
            )
        dropped_uids = {
            s.uid for s in specs_geo if _phantom_spec_cells(s) <= fraud
        }
        self.assertTrue(
            dropped_uids,
            "pricing_context should have at least one phantom fully in fraud cells",
        )
        self.assertEqual(
            {s.uid for s in specs_filtered},
            {s.uid for s in specs_geo if s.uid not in dropped_uids},
        )

    def test_vacant_rect_pass3_geo_prefers_4x3_over_3x3(self) -> None:
        """pricing_context 类：行 9–11 列 1–4 共 12 格几何空置，应优先 4×3。"""
        from bidking.analysis.grid_overlay_infer_vacant_rects import (
            _greedy_expand_rect_candidates,
            _vacant_rect_rank_key,
        )

        geo_work = {
            (r, c) for r in range(9, 12) for c in range(1, 5)
        }
        top = _greedy_expand_rect_candidates(geo_work, geo_work, min_bbox_area=1)[0]
        self.assertEqual(top[:2], (4, 3))
        self.assertGreater(_vacant_rect_rank_key(4, 3), _vacant_rect_rank_key(3, 3))

    def test_vacant_rect_pass3_three_sided_l_shaped_alcove(self) -> None:
        """第 3 步：L 形/敞口不规则区无单格三面 seed，仍应递归贴边取最大矩形。"""
        from bidking.analysis.grid_overlay_dims import GRID_COLS
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (5, 0), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * GRID_COLS + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        # 右上角 L 形空置（与 board_snapshot 同类：无单格三面 seed）
        alcove = {
            (0, 6), (0, 7), (0, 8), (0, 9),
            (1, 6), (1, 7), (1, 8), (1, 9),
            (2, 4), (2, 5), (2, 6), (2, 7), (2, 8), (2, 9),
            (3, 4), (3, 5), (3, 8), (3, 9),
        }
        max_box_id = 5 * GRID_COLS + 9
        occ = {(r, c) for r, c in anchors}
        for bid in range(max_box_id + 1):
            r, c = bid // GRID_COLS, bid % GRID_COLS
            if (r, c) not in alcove:
                occ.add((r, c))
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        covered: set[tuple[int, int]] = set()
        for sp in specs:
            for dr in range(sp.dr, sp.dr + sp.h):
                for dc in range(sp.dc, sp.dc + sp.w):
                    covered.add((dr, dc))
        self.assertEqual(alcove, covered)

    def test_vacant_rect_pass1_enclosed_1x1_before_larger_fill(self) -> None:
        """三面围住的 1×1 临时占格后，外侧仍可推断更大矩形，且不输出该 1×1。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        _, csv_items = bp._load_item_prices_db()
        excl_q = {1, 2, 3, 4}
        pool = [
            i
            for i in csv_items
            if int(i.shape) == 22
            and 1 <= int(i.quality) <= 6
            and int(i.quality) not in excl_q
        ]
        if len(pool) != 1:
            self.skipTest("need shape 22 with single Q5/Q6 quality in CSV")
        pick_quality = int(pool[0].quality)
        w, h = 2, 2

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        dr, dc = 3, 3
        ghost = (dr, dc)
        occ = {(r, c) for r, c in anchors}
        occ.add((dr - 1, dc))
        occ.add((dr, dc - 1))
        occ.add((dr, dc + 1))
        max_box_id = (dr + 1) * 10 + (dc + w)
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={"event_stats": {f"q{pick_quality}_count": 99}},
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        one_by_one = [s for s in specs if s.w == 1 and s.h == 1]
        self.assertEqual(one_by_one, [])
        larger = [s for s in specs if s.w > 1 or s.h > 1]
        self.assertEqual(len(larger), 1)
        lp = larger[0]
        self.assertEqual((lp.w, lp.h, lp.dc, lp.dr), (w, h, dc + 1, dr))
        self.assertEqual(lp.quality, pick_quality)
        ghost_cells = {
            (lp.dr + ddr, lp.dc + ddc)
            for ddr in range(lp.h)
            for ddc in range(lp.w)
        }
        self.assertNotIn(ghost, ghost_cells)

    def test_unknown_contour_log_merges_infer_phantom_vac_before_emit(self) -> None:
        """轮廓未知 Q5 日志 1×1 锚格释放后，空置推断矩形覆盖锚格并写入 Q5。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 4509
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({f"log_q{q}"})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        st.items["log_g5"] = ItemKnowledge(
            uid="log_g5",
            box_id=49,
            box_id_confirmed=False,
            shape=None,
            quality=5,
            excluded_qualities={1, 2, 3, 4},
            excluded_categories={101},
        )
        occ = set(anchors)
        occ.update([(3, 8), (4, 7), (5, 8), (4, 9)])
        fill, log = _fill_phantoms_then_expand_log_shapes(
            grid_overlay_mod,
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=55,
            raw_pricing={"event_stats": {"q5_count": 99}},
            current_round=4,
        )
        self.assertIn("log_g5", log.inferred_log_shapes)
        w, h, dc, dr = log.inferred_log_shapes["log_g5"]
        self.assertGreater(w * h, 1)
        self.assertTrue(log.absorbed_phantom_uids)
        for sp in log.phantom_specs:
            self.assertNotIn(sp.uid, log.absorbed_phantom_uids)
        anchor = (4, 9)
        self.assertIn(
            anchor,
            {
                (dr + ddr, dc + ddc)
                for ddr in range(h)
                for ddc in range(w)
            },
        )

    def test_unknown_contour_log_anchor_released_into_vacant_infer(self) -> None:
        """Q5 日志 1×1 锚格释放后参与空置推断，覆盖锚格的幽灵带 Q5。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 4509
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({f"log_q{q}"})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        st.items["log_g5"] = ItemKnowledge(
            uid="log_g5",
            box_id=49,
            box_id_confirmed=False,
            shape=None,
            quality=5,
            excluded_qualities={1, 2, 3, 4},
            excluded_categories={101},
        )
        occ = set(anchors)
        occ.update([(3, 7), (4, 7), (5, 8), (4, 9), (3, 8)])
        _fill, log = _fill_phantoms_then_expand_log_shapes(
            grid_overlay_mod,
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=55,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
        )
        self.assertIn("log_g5", log.inferred_log_shapes)
        w, h, dc, dr = log.inferred_log_shapes["log_g5"]
        self.assertGreater(w * h, 1)
        self.assertTrue(log.absorbed_phantom_uids)

    def test_two_1x1_unknown_contour_logs_get_disjoint_inferred_rects(self) -> None:
        """同块空置里两枚 1×1 锚格须分到不同 phantom/轮廓，步骤 6 扩形不得重叠。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        def _footprint(shape: tuple[int, int, int, int]) -> set[tuple[int, int]]:
            w, h, dc, dr = shape
            return {
                (dr + ddr, dc + ddc)
                for ddr in range(int(h))
                for ddc in range(int(w))
            }

        st = GameState()
        st.current_round = 4
        st.map_id = 4509
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({f"log_q{q}"})))
        corners = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), corners):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        st.items["log_g5a"] = ItemKnowledge(
            uid="log_g5a",
            box_id=48,
            box_id_confirmed=False,
            shape=None,
            quality=5,
            excluded_qualities={1, 2, 3, 4},
            excluded_categories={101},
        )
        st.items["log_g5b"] = ItemKnowledge(
            uid="log_g5b",
            box_id=49,
            box_id_confirmed=False,
            shape=None,
            quality=5,
            excluded_qualities={1, 2, 3, 4},
            excluded_categories={101},
        )
        occ = set(corners)
        occ.update([(3, 7), (4, 7), (5, 7), (3, 8), (5, 8), (3, 9), (5, 9)])
        _fill, log = _fill_phantoms_then_expand_log_shapes(
            grid_overlay_mod,
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=occ,
            vacant_manual_suppress=set(),
            max_box_id=55,
            raw_pricing={"event_stats": {"q5_count": 99, "q6_count": 99}},
            current_round=4,
        )
        self.assertIn("log_g5a", log.inferred_log_shapes)
        self.assertIn("log_g5b", log.inferred_log_shapes)
        fp_a = _footprint(log.inferred_log_shapes["log_g5a"])
        fp_b = _footprint(log.inferred_log_shapes["log_g5b"])
        self.assertFalse(fp_a & fp_b)
        self.assertIn((4, 8), fp_a)
        self.assertIn((4, 9), fp_b)

    def test_vacant_rect_phantom_respects_total_grid_count(self) -> None:
        """``total_grid_count`` 已知时，推断幽灵 footprint 不得使总占位超过该总数。"""
        from bidking.parsing.state import GameState, ItemKnowledge

        st = GameState()
        st.current_round = 4
        st.map_id = 2101
        for q in (1, 2, 3, 4):
            st._scan_history.append(("quality", q, frozenset({"log_q%d" % q})))
        anchors = [(0, 0), (0, 9), (9, 0), (9, 9)]
        for q, (r, c) in zip((1, 2, 3, 4), anchors):
            st.items[f"log_q{q}"] = ItemKnowledge(
                uid=f"log_q{q}",
                box_id=r * 10 + c,
                box_id_confirmed=True,
                shape=11,
                quality=q,
            )
        w, h, dc, dr = 6, 1, 2, 5
        occ = {(r, c) for r, c in anchors}
        for c in range(dc, dc + w):
            occ.add((dr - 1, c))
            occ.add((dr + 1, c))
        max_box_id = (dr + 1) * 10 + (dc + w - 1)
        for bid in range(max_box_id + 1):
            r, c = bid // 10, bid % 10
            if dr <= r < dr + h and dc <= c < dc + w:
                continue
            occ.add((r, c))
        total_grid = len(occ) + 2
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=set(occ),
            vacant_manual_suppress=set(),
            max_box_id=max_box_id,
            raw_pricing={
                "event_stats": {
                    "total_grid_count": total_grid,
                    "q5_count": 99,
                    "q6_count": 99,
                }
            },
            current_round=4,
            fraud_cells=set(),
            enabled=True,
        ).specs
        phantom_cells = sum(int(s.w) * int(s.h) for s in specs)
        self.assertLessEqual(phantom_cells, 2)
        self.assertLessEqual(len(occ) + phantom_cells, total_grid)
        six_by_one = [s for s in specs if (s.w, s.h) == (w, h)]
        self.assertEqual(six_by_one, [])

    def test_vacant_rect_phantom_skipped_until_q1234_ready(self) -> None:
        """扫描史未覆盖 Q1–Q4 时不推断 phantom_vac（与回合数无关）。"""
        from bidking.parsing.state import GameState

        st = GameState()
        st.map_id = 2101
        specs = grid_overlay_mod.compute_vacant_rect_phantom_specs(
            game_state=st,
            manual_shapes={},
            phantom_items={},
            phantom_quality_pref={},
            occupied_cells=set(),
            vacant_manual_suppress=set(),
            max_box_id=30,
            raw_pricing={},
            current_round=4,
            enabled=True,
        ).specs
        self.assertEqual(specs, [])

    def test_unique_item_cid_without_snapshot_shape_price_matches_csv_row(self) -> None:
        """CSV 已唯一锁定 item_cid、快照无 shape 时：汇总价仍为该行 ``base_value``。"""
        _, csv_items = bp._load_item_prices_db()
        pick = next(
            (
                i
                for i in csv_items
                if len(str(i.shape)) == 2
                and int(str(i.shape)[0]) * int(str(i.shape)[1]) > 1
            ),
            None,
        )
        self.assertIsNotNone(pick)
        assert pick is not None
        q = int(pick.quality)
        snap = {
            "game_state": {
                "items": {
                    "x": {
                        "uid": "x",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": None,
                        "quality": q,
                        "categories": sorted(pick.category_tags),
                        "item_cid": int(pick.item_id),
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                }
            },
            "map_id": 2101,
        }
        total = bp.compute_items_total(snap)
        self.assertAlmostEqual(total, float(pick.base_value))

    def test_confirmed_tier_footprint_unknown_contour_counts_one_cell(self) -> None:
        """品质已知、无 shape：``confirmed_tier_footprint_q456`` 按 1×1 计 1 格。"""
        snap = {
            "game_state": {
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 8,
                        "box_id_confirmed": True,
                        "shape": None,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    },
                    "b": {
                        "uid": "b",
                        "box_id": 9,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": 6,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    },
                }
            },
        }
        cq4, cq5, cq6 = strategy_common.confirmed_tier_footprint_q456(snap)
        self.assertEqual((cq4, cq5, cq6), (0, 1, 4))

    def test_confirmed_tier_footprint_unknown_contour_without_box_id_confirmed(
        self,
    ) -> None:
        """品质已知、轮廓未知：不要求 ``box_id_confirmed`` 仍按 1×1 计 1 格。"""
        snap = {
            "game_state": {
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 10,
                        "box_id_confirmed": False,
                        "shape": None,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    },
                }
            },
        }
        self.assertEqual(strategy_common.confirmed_tier_footprint_q456(snap), (0, 1, 0))

    def test_phantom_gold_capped_when_vacant_lt_rem5_and_pool_exceeds_budget(self) -> None:
        """``rem5 = q5_grid_min - cq5``：空格不足时也不得整池标金（池 45 格、预算 44）。"""
        from bidking.analysis.strategy import common as strat_common

        excl = [1, 2, 3, 4]
        ph: dict = {}
        manual: dict = {}
        total_fp = 0
        specs = [
            ("ph_a", 25, 10),
            ("ph_b", 33, 9),
            ("ph_c", 33, 9),
            ("ph_d", 22, 4),
            ("ph_e", 22, 4),
            ("ph_f", 22, 4),
            ("ph_g", 12, 2),
            ("ph_h", 11, 1),
            ("ph_i", 11, 1),
            ("ph_j", 11, 1),
        ]
        for uid, shape, cells in specs:
            total_fp += cells
            ph[uid] = {
                "uid": uid,
                "box_id": 0,
                "box_id_confirmed": True,
                "shape": shape,
                "quality": None,
                "categories": [7],
                "item_cid": None,
                "price": None,
                "manual_confirm_item_id": None,
                "excluded_categories": [],
                "excluded_qualities": excl,
            }
            manual[uid] = [2, 2, 0, 0] if shape == 22 else [shape // 10, shape % 10, 0, 0]
        self.assertEqual(total_fp, 45)
        snap = {
            "game_state": {
                "items": {
                    "real_gold_uc": {
                        "uid": "real_gold_uc",
                        "box_id": 10,
                        "box_id_confirmed": False,
                        "shape": None,
                        "quality": 5,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "map_id": 4501,
                "current_round": 4,
            },
            "skill_logs": [],
            "map_id": 4501,
            "current_round": 4,
            "grid_overlay": {
                "vacant": {"geometric": 1, "source": "test"},
                "phantom_items": ph,
                "manual_shapes": manual,
                "phantom_quality_pref": {k: "_phantom_q_infer" for k in ph},
            },
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 44,
                "q5_grid_min": 45,
                "q5_grid_count": 45,
            },
        }
        board = {**snap, "raw_pricing": raw}
        cq5_before = strat_common.confirmed_tier_footprint_q456(board)[1]
        self.assertEqual(cq5_before, 1)
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=cq5_before,
            confirmed_q6=0,
        )
        self.assertAlmostEqual(float(detail.get("tier_credit_q5") or 0), 44.0)
        self.assertAlmostEqual(float(detail.get("gr_remaining_budget_final_q5") or 0), 0.0)
        self.assertTrue(
            any(
                s.get("reason") == "vacant_lt_rem5_greedy_capped"
                for s in (detail.get("gold_allocation_steps") or [])
            )
        )
        cq5_after = strat_common.confirmed_tier_footprint_q456(board)[1]
        self.assertEqual(cq5_after, 45)
        ph = board["grid_overlay"]["phantom_items"]
        gold_fp = sum(
            int(
                round(
                    float(
                        strat_common._geo_footprint_cells_from_shape_field(
                            row.get("shape")
                        )
                        or 0
                    )
                )
            )
            for row in ph.values()
            if isinstance(row, dict) and int(row.get("quality") or 0) == 5
        )
        self.assertEqual(gold_fp, 44)

    def test_phantom_effective_q5_budget_is_q5_grid_min_minus_cq5(self) -> None:
        """幽灵金格贪心预算 = ``q5_grid_min - confirmed_q5``（与 ``cq5`` 一致）。"""
        rem5, count_known = strategy_common._phantom_effective_q5_budget(
            {"q5_grid_min": 3},
            confirmed_q5=1,
        )
        self.assertAlmostEqual(rem5, 2.0)
        self.assertFalse(count_known)
        rem5_cap, _ = strategy_common._phantom_effective_q5_budget(
            {"q5_grid_min": 3, "q5_grid_count": 1},
            confirmed_q5=1,
        )
        self.assertAlmostEqual(rem5_cap, 0.0)

    def test_unknown_contour_log_pricing_uses_inferred_max_shape_wh(self) -> None:
        """轮廓未知日志：``compute_items_total`` 与画板一致，按锚格四向扫描 ``max_shape_wh`` 筛候选。"""
        from bidking.analysis.grid_overlay_vacant_zone import (
            infer_max_shape_wh_for_unknown_contour_merged_row,
        )

        gs = {
            "uid": "u1",
            "map_id": 4501,
            "current_round": 4,
            "players": {},
            "items": {
                "log_red": {
                    "uid": "log_red",
                    "box_id": 49,
                    "box_id_confirmed": False,
                    "shape": None,
                    "quality": 6,
                    "categories": [],
                    "categories_any": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [1, 2, 3, 4],
                },
                "blk_l": {
                    "uid": "blk_l",
                    "box_id": 48,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "categories_any": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                },
                "blk_r": {
                    "uid": "blk_r",
                    "box_id": 50,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "categories_any": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                },
                "blk_u": {
                    "uid": "blk_u",
                    "box_id": 39,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "categories_any": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                },
                "blk_d": {
                    "uid": "blk_d",
                    "box_id": 59,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "categories_any": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                },
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 4501, "current_round": 4}
        merged = grid_overlay_mod.merged_items_dict_from_snapshot(snap)
        max_wh = infer_max_shape_wh_for_unknown_contour_merged_row(
            "log_red", merged["log_red"], merged
        )
        self.assertEqual(max_wh, (1, 1))
        v = bp.estimate_snapshot_item_price_for_uid(snap, "log_red")
        self.assertIsNotNone(v)
        assert v is not None
        _, csv_items = bp._load_item_prices_db()
        from bidking.parsing import item_db

        csv_index, _ = bp._load_item_prices_db()
        _b, c_wide, _, e_wide, _ = item_db.query_item(
            None,
            6,
            set(),
            None,
            csv_index,
            csv_items,
            excluded_qualities={1, 2, 3, 4},
            max_shape_wh=None,
            map_id=4501,
        )
        _b2, c_narrow, _, e_narrow, _ = item_db.query_item(
            None,
            6,
            set(),
            None,
            csv_index,
            csv_items,
            excluded_qualities={1, 2, 3, 4},
            max_shape_wh=(1, 1),
            map_id=4501,
        )
        self.assertGreater(c_wide, c_narrow)
        self.assertAlmostEqual(float(v), float(e_narrow), delta=1.0)
        self.assertEqual(
            item_db.weighted_est_max_item_base_value(None, quality=6),
            item_db.WEIGHTED_EST_MAX_1X1_ITEM_BASE_VALUE,
        )
        self.assertEqual(
            item_db.weighted_est_max_item_base_value(None, quality=5),
            item_db.WEIGHTED_EST_MAX_ITEM_BASE_VALUE,
        )
        # 宽池与 1×1 窄池共用 10 万 cap，期望价应接近（差仅来自候选集合大小）
        self.assertAlmostEqual(float(e_wide), float(e_narrow), delta=float(e_narrow) * 0.2)

    def test_unknown_contour_q6_reduces_tier_extra_by_weighted_footprint(self) -> None:
        """无 shape 的红档占位：``confirmed_q6`` 按权重等效格计，再扣减 ``q6_grid_min`` tier_extra。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 10,
                    "box_id_confirmed": True,
                    "shape": None,
                    "quality": 6,
                    "categories": [],
                    "item_cid": 100161,
                    "price": 8000,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        csv_cells = raw["csv_quality_groups_avg_per_cell"]
        _cq4, _cq5, cq6 = strategy_common.confirmed_tier_footprint_q456(
            snap, csv_cells_raw=csv_cells
        )
        self.assertGreater(cq6, 1)
        eff_need = max(0, 4 - int(cq6))
        self.assertEqual(int(p.get("tier_extra_cells") or 0), eff_need)
        self.assertAlmostEqual(
            float(p.get("tier_extra_value") or 0.0),
            float(eff_need) * 200.0,
        )

    def test_unknown_contour_excess_subtract_skips_tier_with_grid_min(self) -> None:
        """有 ``q4_grid_min`` 时紫档超额进 tier_extra；金/红/低档超额仍扣 ``vacant_adj``。"""
        from bidking.analysis.strategy import common as strat_common

        uc_detail = {
            "detail_per_item": [
                {"quality": 4, "excess_over_one_cell": 1.8},
                {"quality": 5, "excess_over_one_cell": 2.4},
                {"quality": 6, "excess_over_one_cell": 3.0},
                {"quality": 2, "excess_over_one_cell": 1.1},
            ]
        }
        st = {"q4_grid_min": 10}
        self.assertEqual(
            strat_common.unknown_contour_vacant_cell_excess_subtract(uc_detail, st),
            6,
        )

    def test_early_round_vacant_dict_uses_geometry(self) -> None:
        """无 200009 时：``vacant_dict_from_board_snapshot`` 按几何前缀区计空置（与定价同源）。"""
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 2,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 5,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 5,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2101,
            "current_round": 2,
        }
        vb = grid_overlay_mod.vacant_dict_from_board_snapshot(snap)
        self.assertEqual(vb.get("geometric"), 5)
        self.assertEqual(vb.get("source"), "geometric_empty_zone")
        p = bp.build_snapshot_pricing_dict(snap, snapshot_path_hint=None)
        self.assertEqual(p["vacant"], 5)

    def test_map_quality_csv_uses_normalize_map_id_41xx(self) -> None:
        """CSV 仅含 21xx 时，日志 41xx（等价 MapCid）应命中同一行。"""
        keys = [
            "map_id",
            "tier",
            "nest_drop_id",
            "quality_group",
            "prob_in_group",
            "avg_price_per_item",
            "avg_price_per_cell",
        ]
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            suffix=".csv",
            delete=False,
            newline="",
        ) as tf:
            path = tf.name
            w = csv.DictWriter(tf, fieldnames=keys)
            w.writeheader()
            base = {
                "map_id": "2101",
                "tier": "101",
                "nest_drop_id": "2001",
                "prob_in_group": "1",
                "avg_price_per_item": "1",
            }
            w.writerow({**base, "quality_group": "q5", "avg_price_per_cell": "111"})
            w.writerow({**base, "quality_group": "q5+q6", "avg_price_per_cell": "222"})
            w.writerow({**base, "quality_group": "q6", "avg_price_per_cell": "333"})
        try:
            set_map_quality_csv_override(path)
            pricing = bp.build_snapshot_pricing_dict(
                {
                    "game_state": {"map_id": 4101, "current_round": 4, "items": {}},
                    "skill_logs": [],
                    "map_id": 4101,
                    "current_round": 4,
                    "grid_overlay": {
                        "vacant": {
                            "effective_count": 1,
                            "geometric": 1,
                            "source": "test",
                        }
                    },
                },
                snapshot_path_hint=None,
            )
            self.assertTrue(pricing.get("map_quality_avg_hit"))
            self.assertEqual(pricing.get("vacant_unit_all_orange"), 111)
            self.assertEqual(pricing.get("vacant_unit_gold_red"), 222)
            self.assertEqual(pricing.get("vacant_unit_all_red"), 333)
        finally:
            set_map_quality_csv_override(None)
            Path(path).unlink(missing_ok=True)

    def test_vacant_200009_total_minus_board_occupied(self) -> None:
        """有 200009 总藏品格数时，定价空置 = 总数 − 画板占位格数。"""
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": 200009, "TotalHitBoxIndex": 61},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
        self.assertEqual(
            grid_overlay_mod.map_skill_hidden_vacant(
                grid_overlay_mod.map_skill_total_hidden_for_overlay({"raw_pricing": raw}),
                occupied_cell_count=10,
            ),
            51,
        )
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            {
                "game_state": gs,
                "skill_logs": logs,
                "map_id": 0,
                "current_round": 5,
            },
            snapshot_path_hint=None,
        )
        self.assertEqual(p.get("vacant"), 61)

    def test_vacant_from_raw_pricing_when_skill_logs_empty(self) -> None:
        """``skill_logs`` 已剥离但 ``raw_pricing`` 含 200009 时，仍按总格数 − 占位算空置。"""
        logs = [
            {
                "game_data": {
                    "MapSkillLog": [
                        {"SkillCid": 200009, "TotalHitBoxIndex": 61},
                    ]
                }
            }
        ]
        raw = build_raw_pricing_dict(map_id=0, skill_logs=logs, snapshot_path_hint=None)
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            {
                "game_state": gs,
                "skill_logs": [],
                "map_id": 0,
                "current_round": 5,
                "raw_pricing": raw,
            },
            snapshot_path_hint=None,
        )
        self.assertEqual(p.get("vacant_source"), "map_skill_total_hidden_minus_occupied")
        self.assertEqual(p.get("vacant"), 61)

    def test_build_snapshot_three_position_totals(self) -> None:
        """定价重算空置：需有已确认锚点，前缀区内 3 格空则 ``vacant==3``。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        p = bp.build_snapshot_pricing_dict(
            {
                "game_state": gs,
                "skill_logs": [],
                "map_id": 0,
                "current_round": 5,
            },
            snapshot_path_hint=None,
        )
        self.assertIn("total", p)
        self.assertIn("points", p)
        self.assertIn("points_floor", p)
        self.assertIn("points_ceiling", p)
        self.assertIn("est_orange", p)
        self.assertIn("est_gold_red", p)
        self.assertIn("est_red", p)
        self.assertEqual(p["vacant"], 3)

    def test_generic_points_track_red_estimate_when_q5_grid_count_known(self) -> None:
        """低档总格齐备且仅公开 ``q5_grid_count`` 时，空置主价按红格单价（余量必为红）。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        csv = {
            "q4": 10.0,
            "q5": 1000.0,
            "q6": 100.0,
            "q5+q6": 550.0,
            "all": 1.0,
        }
        ev = {
            "q12_grid_count": 1,
            "q3_grid_count": 1,
            "q4_grid_count": 1,
            "q5_grid_count": 10,
        }
        raw = {"csv_quality_groups_avg_per_cell": csv, "event_stats": ev}
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertFalse(p.get("ahmad_pricing_active"))
        self.assertEqual(p.get("points"), p.get("est_red"))
        self.assertEqual(p.get("points_floor"), p.get("est_red"))
        self.assertEqual(p.get("points_ceiling"), p.get("est_red"))

    def test_generic_points_track_orange_when_q6_grid_count_known_only(self) -> None:
        """低档总格齐备且仅公开 ``q6_grid_count`` 时，主价三字段均按金单价（余量必为金）。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        csv = {
            "q4": 10.0,
            "q5": 1000.0,
            "q6": 100.0,
            "q5+q6": 550.0,
            "all": 1.0,
        }
        ev = {
            "q12_grid_count": 1,
            "q3_grid_count": 1,
            "q4_grid_count": 1,
            "q6_grid_count": 8,
        }
        raw = {"csv_quality_groups_avg_per_cell": csv, "event_stats": ev}
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertFalse(p.get("ahmad_pricing_active"))
        self.assertEqual(p.get("points"), p.get("est_orange"))
        self.assertEqual(p.get("points_floor"), p.get("est_orange"))
        self.assertEqual(p.get("points_ceiling"), p.get("est_orange"))

    def test_tier_grid_min_adjusts_early_points(self) -> None:
        """``q*_grid_min`` 有值时：相对无 ``grid_min`` 的基准，先按档加价并减少空置乘数项格数。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw_base = {
            "csv_quality_groups_avg_per_cell": {
                "q4": 10.0,
                "q5": 1.0,
                "q5+q6": 1.0,
                "q6": 1.0,
                "all": 1000.0,
            },
            "event_stats": {},
        }
        raw_min = {**raw_base, "event_stats": {"q4_grid_min": 2}}
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        p0 = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_base}, snapshot_path_hint=None)
        p1 = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_min}, snapshot_path_hint=None)
        self.assertEqual(p1["vacant"], 3)
        # 少乘 2 格 u_early、多 2*q4 单价：差 = -2*1000 + 2*10 = -1980
        self.assertEqual(p1["points"], p0["points"] - 1980)

    def test_tier_grid_min_skips_q4_when_q4_grid_avg_known_but_total_unknown(self) -> None:
        """紫均格已知、紫总格未知时，``q4_grid_min`` 不计入 tier_extra。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw_base = {
            "csv_quality_groups_avg_per_cell": {
                "q4": 10.0,
                "q5": 1.0,
                "q5+q6": 1.0,
                "q6": 1.0,
                "all": 1000.0,
            },
            "event_stats": {},
        }
        raw_skip = {
            **raw_base,
            "event_stats": {"q4_grid_min": 2, "q4_grid_avg": 2.5},
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        p0 = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_base}, snapshot_path_hint=None)
        p_skip = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_skip}, snapshot_path_hint=None)
        self.assertEqual(p_skip["points"], p0["points"])

    def test_early_vacant_unit_excludes_q4_when_q4_grid_count_known(self) -> None:
        """事件给出 ``q4_grid_count`` 且扫描可能仍含紫时，早单价改查不含 q4 的 CSV 组合键。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
            ],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q4+q5+q6": 12000.0,
                "q5+q6": 3000.0,
                "q5": 2000.0,
                "q6": 1000.0,
            },
            "event_stats": {"q4_grid_count": 37},
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw}
        p = bp.build_snapshot_pricing_dict(snap, snapshot_path_hint=None)
        self.assertEqual(p.get("early_vacant_csv_group"), "q5+q6")
        self.assertEqual(p.get("early_vacant_unit_from_scan"), 3000)

    def test_early_vacant_unit_no_blend_when_q123_not_all_scanned(self) -> None:
        """q123 未齐扫描时，即使有 ``q4_grid_min`` 也不做 q456/q56 混合，仍用扫描推断单价。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 3,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
            ],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q4+q5+q6": 12000.0,
                "q5+q6": 3000.0,
                "q4": 8000.0,
            },
            "event_stats": {"q4_grid_min": 2},
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 3, "raw_pricing": raw}
        p = bp.build_snapshot_pricing_dict(snap, snapshot_path_hint=None)
        self.assertNotEqual(p.get("early_vacant_csv_group"), "q4+q5+q6~q5+q6")
        self.assertNotEqual(p.get("early_vacant_unit_from_scan"), 7500)

    def test_early_vacant_unit_no_blend_when_q4_grid_avg_missing(self) -> None:
        """q123 已齐、有 ``q4_grid_min`` 但无 ``q4_grid_avg`` 时不做 q456/q56 混合。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [
                {"scan_type": "quality", "value": 1, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 2, "hit_uids": ["x"]},
                {"scan_type": "quality", "value": 3, "hit_uids": ["x"]},
            ],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q4+q5+q6": 12000.0,
                "q5+q6": 3000.0,
                "q4": 8000.0,
            },
            "event_stats": {"q4_grid_min": 2},
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw}
        p = bp.build_snapshot_pricing_dict(snap, snapshot_path_hint=None)
        self.assertNotEqual(p.get("early_vacant_csv_group"), "q4+q5+q6~q5+q6")
        self.assertNotEqual(p.get("early_vacant_unit_from_scan"), 7500)

    def test_parse_auto_vacant_phantom_price_quantile(self) -> None:
        from bidking.config.runtime import (
            parse_auto_vacant_phantom_price_quantile,
            resolve_auto_vacant_phantom_price_quantile,
        )
        from bidking.parsing import item_db
        from bidking.parsing.state import CsvItem

        self.assertIsNone(parse_auto_vacant_phantom_price_quantile(None))
        self.assertIsNone(parse_auto_vacant_phantom_price_quantile("avg"))
        self.assertAlmostEqual(
            parse_auto_vacant_phantom_price_quantile("p50") or 0.0, 0.5
        )
        self.assertAlmostEqual(
            parse_auto_vacant_phantom_price_quantile("p25") or 0.0, 0.25
        )
        self.assertAlmostEqual(
            resolve_auto_vacant_phantom_price_quantile(
                pricing_dict={"auto_vacant_phantom_price": "p50"}
            )
            or 0.0,
            0.5,
        )
        pairs = [(100.0, 0.9), (10_000.0, 0.05), (20_000.0, 0.05)]
        self.assertAlmostEqual(item_db.weighted_percentile(pairs, 0.25), 100.0)
        mean = sum(v * w for v, w in pairs) / sum(w for _, w in pairs)
        self.assertGreater(mean, 500.0)
        cands = [
            CsvItem(901, "low", [101], 22, 5, 100),
            CsvItem(902, "mid", [101], 22, 5, 10_000),
            CsvItem(903, "high", [101], 22, 6, 20_000),
        ]
        est_avg = item_db._weighted_est_price(cands, None, None, quantile=None)
        est_p25 = item_db._weighted_est_price(cands, None, None, quantile=0.25)
        self.assertAlmostEqual(est_p25, 100.0)
        self.assertGreater(est_avg or 0.0, est_p25 or 0.0)

    def test_auto_vacant_phantom_total_respects_p25_config(self) -> None:
        from unittest.mock import patch

        from bidking.parsing.state import CsvItem

        uid = "phantom_vac_3_3_2x2"
        snap = {
            "map_id": 2101,
            "game_state": {"items": {}},
            "grid_overlay": {
                "phantom_items": {
                    uid: {
                        "uid": uid,
                        "box_id": 33,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [1, 2, 3, 4],
                    }
                },
                "manual_shapes": {uid: [2, 2, 3, 3]},
                "phantom_quality_pref": {uid: "_phantom_q_infer"},
            },
        }
        fake = [
            CsvItem(901, "low", [101], 22, 5, 100),
            CsvItem(902, "mid", [101], 22, 5, 10_000),
            CsvItem(903, "high", [101], 22, 6, 20_000),
        ]
        idx = {i.item_id: i for i in fake}
        with patch.object(bp, "_load_item_prices_db", return_value=(idx, fake)):
            total_avg = bp.compute_items_total(
                {**snap, "raw_pricing": {"auto_vacant_phantom_price": "avg"}}
            )
            total_p25 = bp.compute_items_total(
                {**snap, "raw_pricing": {"auto_vacant_phantom_price": "p25"}}
            )
            hand_snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
            hand_avg = bp.compute_items_total(
                {**hand_snap, "raw_pricing": {"auto_vacant_phantom_price": "p25"}}
            )
        self.assertAlmostEqual(total_p25, 100.0)
        self.assertGreater(total_avg, total_p25)
        self.assertGreater(hand_avg, total_p25)
        with patch.object(bp, "_load_item_prices_db", return_value=(idx, fake)):
            est_p25 = bp.estimate_snapshot_item_price_for_uid(
                {**snap, "raw_pricing": {"auto_vacant_phantom_price": "p25"}},
                uid,
            )
            est_avg = bp.estimate_snapshot_item_price_for_uid(
                {**snap, "raw_pricing": {"auto_vacant_phantom_price": "avg"}},
                uid,
            )
        self.assertAlmostEqual(est_p25 or 0.0, 100.0)
        self.assertGreater(est_avg or 0.0, est_p25 or 0.0)

    def _phantom_only_snapshot(
        self,
        *,
        quality_pref: int | str,
        excluded_qualities: list | None = None,
    ) -> dict:
        excl = list(excluded_qualities) if excluded_qualities is not None else []
        return {
            "game_state": {"items": {}, "map_id": 0, "current_round": 5},
            "skill_logs": [],
            "map_id": 0,
            "current_round": 5,
            "grid_overlay": {
                "phantom_items": {
                    "phantom_9": {
                        "uid": "phantom_9",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    }
                },
                "manual_shapes": {"phantom_9": [2, 2, 0, 0]},
                "phantom_quality_pref": {"phantom_9": quality_pref},
            },
        }

    def test_phantom_known_q6_in_pricing_total_and_tier_footprint(self) -> None:
        """显式红笔幽灵：计入 ``pricing.total``，且 ``q6_grid_min`` 按 2×2 占位抵扣 tier_extra。"""
        snap = self._phantom_only_snapshot(quality_pref=6)
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q4": 10.0,
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        item_total = bp.compute_items_total(snap)
        self.assertGreater(item_total, 0.0)
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertAlmostEqual(float(p["total"]), item_total)
        self.assertEqual(int(p.get("tier_extra_cells") or 0), 0)
        self.assertAlmostEqual(float(p.get("tier_extra_value") or 0.0), 0.0)

    def test_phantom_infer_tier_credit_splits_q5_q6_grid_min(self) -> None:
        """已知 ``q5_grid_min`` 且几何空格不足：2×2 推断笔按 ``rem5`` 记金，``q6_grid_min`` 仍补 tier。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_min": 2,
                "q6_grid_min": 2,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        # 幽灵仅消耗 ``rem5=2`` 金格预算，盘面金占位不足，q5/q6 各补 2 格 tier_extra
        self.assertEqual(int(p.get("tier_extra_cells") or 0), 4)
        self.assertNotIn("phantom_unknown_quality", p)
        ph_row = (snap.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertGreaterEqual(
            float(ph_row.get("phantom_tier_credit_by_quality", {}).get("5") or 0),
            2.0,
        )

    def test_phantom_infer_excluded_gr_no_tier_credit(self) -> None:
        """金红皆排除：无 phantom tier 分摊，``q6_grid_min`` 仍全额补格。"""
        snap = self._phantom_only_snapshot(
            quality_pref="_phantom_q_infer",
            excluded_qualities=[5, 6],
        )
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertNotIn("phantom_unknown_quality", p)
        self.assertEqual(int(p.get("tier_extra_cells") or 0), 4)
        self.assertAlmostEqual(float(p.get("tier_extra_value") or 0.0), 800.0)

    def test_phantom_infer_partial_credit_when_only_q6_grid_min(self) -> None:
        """仅 ``q6_grid_min``：2×2 推断笔在剩余红格预算内全额记入 Q6，无 tier_extra。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertEqual(int(p.get("tier_extra_cells") or 0), 0)
        self.assertAlmostEqual(float(p.get("tier_extra_value") or 0.0), 0.0)
        self.assertNotIn("phantom_unknown_quality", p)
        ph_row = (snap.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertEqual(int(ph_row.get("quality") or 0), 6)

    def test_phantom_no_gold_alloc_when_q5_grid_count_zero(self) -> None:
        """末盘金格已满（``q5_grid_count`` 用尽）：新幽灵只分红，不写金品质。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 0,
                "q6_grid_min": 7,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertNotIn("phantom_unknown_quality", p)
        ph_row = (snap.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertEqual(int(ph_row.get("quality") or 0), 6)

    def _phantom_multi_infer_snapshot(
        self,
        *,
        vacant_geometric: int = 5,
    ) -> dict:
        excl = [1, 2, 3, 4]
        pref = "_phantom_q_infer"
        return {
            "game_state": {"items": {}, "map_id": 0, "current_round": 5},
            "skill_logs": [],
            "map_id": 0,
            "current_round": 5,
            "grid_overlay": {
                "vacant": {
                    "geometric": int(vacant_geometric),
                    "source": "test",
                },
                "phantom_items": {
                    "ph_big": {
                        "uid": "ph_big",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 23,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                    "ph_s1": {
                        "uid": "ph_s1",
                        "box_id": 10,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                    "ph_s2": {
                        "uid": "ph_s2",
                        "box_id": 11,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "manual_shapes": {
                    "ph_big": [2, 3, 0, 0],
                    "ph_s1": [1, 1, 5, 0],
                    "ph_s2": [1, 1, 6, 0],
                },
                "phantom_quality_pref": {
                    "ph_big": pref,
                    "ph_s1": pref,
                    "ph_s2": pref,
                },
            },
        }

    def test_phantom_item_prob_locks_red_1x3_when_gold_budget_full(self) -> None:
        """金满后 1×3：古剑 >60% 应第一轮锁定 ``manual_confirm_item_id``，而非沙发。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        snap["grid_overlay"]["phantom_items"]["phantom_9"]["shape"] = 31
        snap["grid_overlay"]["manual_shapes"]["phantom_9"] = [3, 1, 0, 0]
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 0,
            },
        }
        board = {**snap, "raw_pricing": raw}
        strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        ph_row = (board.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertEqual(int(ph_row.get("manual_confirm_item_id") or 0), 1046007)
        self.assertEqual(int(ph_row.get("quality") or 0), 6)
        self.assertEqual(int(ph_row.get("item_cid") or 0), 1046007)

    def test_phantom_gold_exact_match_backtrack(self) -> None:
        """高置信金候选：回退选取 footprint 之和正好等于 ``rem5`` 的矩形。"""
        from bidking.analysis.strategy import common as strat_common

        excl = [1, 2, 3, 4]
        pref = "_phantom_q_infer"
        snap = {
            "game_state": {"items": {}, "map_id": 0, "current_round": 5},
            "skill_logs": [],
            "map_id": 0,
            "current_round": 5,
            "grid_overlay": {
                "vacant": {"geometric": 0, "source": "test"},
                "phantom_items": {
                    "ph_a": {
                        "uid": "ph_a",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                    "ph_b": {
                        "uid": "ph_b",
                        "box_id": 10,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                    "ph_c": {
                        "uid": "ph_c",
                        "box_id": 11,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "manual_shapes": {
                    "ph_a": [2, 2, 0, 0],
                    "ph_b": [1, 1, 5, 0],
                    "ph_c": [1, 1, 6, 0],
                },
                "phantom_quality_pref": {
                    "ph_a": pref,
                    "ph_b": pref,
                    "ph_c": pref,
                },
            },
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 2,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        overlay = board.get("grid_overlay") or {}
        ph = overlay.get("phantom_items") or {}
        self.assertEqual(int(ph["ph_b"].get("quality") or 0), 5)
        self.assertEqual(int(ph["ph_c"].get("quality") or 0), 5)
        self.assertEqual(int(ph["ph_a"].get("quality") or 0), 6)
        self.assertAlmostEqual(float(detail.get("gr_remaining_budget_final_q5") or 0), 0.0)

    def test_phantom_all_gold_when_vacant_less_than_q5_grid_min(self) -> None:
        """几何空格 < ``rem5`` 时仍按 ``rem5`` 贪心记金（池内格数不超过预算时仍可全金）。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_multi_infer_snapshot(vacant_geometric=5)
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_min": 10,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        overlay = board.get("grid_overlay") or {}
        ph = overlay.get("phantom_items") or {}
        self.assertEqual(int(ph["ph_s1"].get("quality") or 0), 5)
        self.assertEqual(int(ph["ph_s2"].get("quality") or 0), 5)
        self.assertEqual(int(ph["ph_big"].get("quality") or 0), 5)
        global_steps = detail.get("gold_allocation_steps") or []
        self.assertTrue(
            any(
                step.get("reason") == "vacant_lt_rem5_greedy_capped"
                for step in global_steps
            )
        )

    def test_phantom_greedy_gold_when_q5_grid_min_no_exact_match(self) -> None:
        """已知 ``q5_grid_min`` 且空格充足：无精确组合时按金权重贪心略超，余格记红（有 count）。"""
        from bidking.analysis.strategy import common as strat_common

        excl = [1, 2, 3, 4]
        pref = "_phantom_q_infer"
        snap = {
            "game_state": {"items": {}, "map_id": 0, "current_round": 5},
            "skill_logs": [],
            "map_id": 0,
            "current_round": 5,
            "grid_overlay": {
                "vacant": {"geometric": 0, "source": "test"},
                "phantom_items": {
                    "ph_big": {
                        "uid": "ph_big",
                        "box_id": 0,
                        "box_id_confirmed": True,
                        "shape": 22,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                    "ph_s1": {
                        "uid": "ph_s1",
                        "box_id": 5,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "manual_shapes": {
                    "ph_big": [2, 2, 0, 0],
                    "ph_s1": [1, 1, 5, 0],
                },
                "phantom_quality_pref": {
                    "ph_big": pref,
                    "ph_s1": pref,
                },
            },
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_min": 3,
                "q5_grid_count": 3,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        self.assertTrue(detail.get("q5_grid_min_known"))
        overlay = board.get("grid_overlay") or {}
        ph = overlay.get("phantom_items") or {}
        # vacant=0 < rem5=3：幽灵池 6 格，金预算内最多记 3 格金
        self.assertAlmostEqual(float(detail.get("gr_remaining_budget_final_q5") or 0), 0.0)
        gold_cells = sum(
            float((row.get("tier_credit_by_quality") or {}).get("5") or 0.0)
            for row in (detail.get("items") or [])
            if isinstance(row, dict)
        )
        self.assertAlmostEqual(gold_cells, 3.0)

    def test_phantom_rebalance_red_to_gold_when_rem5_exceeds_vacant(self) -> None:
        """``q5_grid_count`` 已知且几何空格用尽后仍有 rem5：还原强制红为空置吸收，用尽金预算。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_multi_infer_snapshot(vacant_geometric=5)
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 10,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        global_steps = detail.get("gold_allocation_steps") or []
        self.assertTrue(
            any(
                step.get("reason") == "vacant_absorb" and float(step.get("cells") or 0) == 5.0
                for step in global_steps
            )
        )
        self.assertTrue(
            any(
                step.get("reason") == "phantom_red_revert_vacant_absorb"
                and float(step.get("cells") or 0) == 5.0
                for step in global_steps
            )
        )
        self.assertAlmostEqual(float(detail.get("gr_remaining_budget_final_q5") or 0), 0.0)

    def test_known_contour_unknown_quality_log_joins_gold_pool(self) -> None:
        """合并表日志行（有 shape、品质未知）与幽灵一并参与金格精确匹配。"""
        from bidking.analysis.strategy import common as strat_common

        excl = [1, 2, 3, 4]
        snap = {
            "game_state": {
                "items": {
                    "log_kc": {
                        "uid": "log_kc",
                        "box_id": 7,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "map_id": 0,
                "current_round": 5,
            },
            "skill_logs": [],
            "map_id": 0,
            "current_round": 5,
            "grid_overlay": {
                "vacant": {"geometric": 0, "source": "test"},
                "phantom_items": {
                    "ph_one": {
                        "uid": "ph_one",
                        "box_id": 8,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": None,
                        "categories": [7],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": excl,
                    },
                },
                "manual_shapes": {
                    "ph_one": [1, 1, 0, 0],
                    "log_kc": [1, 1, 1, 0],
                },
                "phantom_quality_pref": {"ph_one": "_phantom_q_infer"},
            },
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 2,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
            confirmed_q5=0,
            confirmed_q6=0,
        )
        uids = {row.get("uid") for row in (detail.get("items") or []) if isinstance(row, dict)}
        self.assertIn("log_kc", uids)
        self.assertIn("ph_one", uids)
        self.assertAlmostEqual(float(detail.get("gr_remaining_budget_final_q5") or 0), 0.0)
        gs_item = (board.get("game_state") or {}).get("items", {}).get("log_kc") or {}
        self.assertIn(int(gs_item.get("quality") or 0), (5, 6))

    def test_phantom_red_only_when_gold_budget_zero_without_q6_stat(self) -> None:
        """``rem5=0`` 且无 ``q6_grid_*`` 时仍写 Q6（末盘只剩金红候选）。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 0,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertNotIn("phantom_unknown_quality", p)
        ph_row = (snap.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertEqual(int(ph_row.get("quality") or 0), 6)

    def test_phantom_post_gold_threshold_configurable(self) -> None:
        """``post_gold_quality_threshold_q5/q6`` 可分别配置；红阈值抬高时不直接定红。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
            "phantom_unknown_tier": {
                "post_gold_quality_threshold_q5": 0.5,
                "post_gold_quality_threshold_q6": 0.99,
            },
        }
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertNotIn("phantom_unknown_quality", p)
        alloc = strategy_common.resolve_phantom_unknown_tier_config(
            snapshot_override=raw.get("phantom_unknown_tier"),
        )
        self.assertAlmostEqual(alloc["post_gold_quality_threshold_q5"], 0.5)
        self.assertAlmostEqual(alloc["post_gold_quality_threshold_q6"], 0.99)
        ph_row = (snap.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertIsNone(ph_row.get("quality"))
        self.assertIsInstance(ph_row.get("phantom_tier_credit_by_quality"), dict)

    def test_phantom_post_gold_legacy_threshold_sets_both(self) -> None:
        """旧键 ``post_gold_quality_threshold`` 同时填充 q5/q6，且可被分档键覆盖。"""
        from bidking.analysis.strategy import common as strat_common

        cfg = strat_common.resolve_phantom_unknown_tier_config(
            snapshot_override={
                "post_gold_quality_threshold": 0.55,
                "post_gold_quality_threshold_q6": 0.88,
            },
        )
        self.assertAlmostEqual(cfg["post_gold_quality_threshold_q5"], 0.55)
        self.assertAlmostEqual(cfg["post_gold_quality_threshold_q6"], 0.88)

    def test_phantom_auto_alloc_skips_manual_confirm_item(self) -> None:
        """已 ``manual_confirm_item_id`` 的幽灵格不再参与自动分摊。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        snap["grid_overlay"]["phantom_items"]["phantom_9"]["manual_confirm_item_id"] = 1033003
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 0,
            },
            "phantom_unknown_tier": {},
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
        )
        self.assertEqual(detail.get("items") or [], [])
        ph_row = (board.get("grid_overlay", {}).get("phantom_items") or {}).get(
            "phantom_9"
        ) or {}
        self.assertEqual(int(ph_row.get("manual_confirm_item_id") or 0), 1033003)
        self.assertIsNone(ph_row.get("phantom_tier_credit_by_quality"))

    def test_phantom_auto_alloc_skips_explicit_quality_pref(self) -> None:
        """显式红笔偏好（非推断笔）的幽灵格不再参与自动分摊。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_only_snapshot(quality_pref=6)
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_count": 0,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
        )
        self.assertEqual(detail.get("items") or [], [])

    def test_phantom_pricing_syncs_overlay_to_ui_item_knowledge(self) -> None:
        """定价写回 overlay 后，``sync_phantom_items_from_overlay_after_pricing`` 对齐画板幽灵态。"""
        from bidking.analysis.phantom_pricing_ui_sync import (
            PHANTOM_Q_INFER,
            sync_phantom_items_from_overlay_after_pricing,
        )
        from bidking.parsing.state import ItemKnowledge

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        board = {**snap, "raw_pricing": raw}
        bp.build_snapshot_pricing_dict(board, snapshot_path_hint=None)
        overlay = board.get("grid_overlay") or {}
        ph_row = (overlay.get("phantom_items") or {}).get("phantom_9") or {}
        self.assertEqual(int(ph_row.get("quality") or 0), 6)

        pk = ItemKnowledge(uid="phantom_9")
        pk.quality = None
        ph_items = {"phantom_9": pk}
        pref: dict = {"phantom_9": PHANTOM_Q_INFER}
        changed = sync_phantom_items_from_overlay_after_pricing(
            overlay, ph_items, pref
        )
        self.assertIn("phantom_9", changed)
        self.assertEqual(pk.quality, 6)
        self.assertEqual(pref["phantom_9"], 6)

    def test_phantom_manual_quality_override_after_auto_alloc(self) -> None:
        """自动分摊指定 Q6 后，用户手改 ``phantom_quality_pref`` 应保持 Q5 且不再参与分摊。"""
        from bidking.analysis.phantom_pricing_ui_sync import (
            PHANTOM_Q_INFER,
            clear_phantom_auto_resolution_on_item,
            sync_phantom_items_from_overlay_after_pricing,
        )
        from bidking.analysis.strategy import common as strat_common
        from bidking.parsing.state import ItemKnowledge

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        board = {**snap, "raw_pricing": raw}
        bp.build_snapshot_pricing_dict(board, snapshot_path_hint=None)
        overlay = board.get("grid_overlay") or {}
        ph_row = (overlay.get("phantom_items") or {}).get("phantom_9") or {}
        self.assertEqual(int(ph_row.get("quality") or 0), 6)

        pk = ItemKnowledge(uid="phantom_9")
        pk.box_id = 0
        pk.box_id_confirmed = True
        pk.quality = 6
        pk.manual_confirm_item_id = None
        ph_items = {"phantom_9": pk}
        pref: dict = {"phantom_9": 6}
        clear_phantom_auto_resolution_on_item(pk)
        pref["phantom_9"] = 5
        overlay["phantom_quality_pref"] = {"phantom_9": 5}
        overlay["phantom_quality_user_locked"] = ["phantom_9"]
        overlay["phantom_items"]["phantom_9"] = {
            **overlay["phantom_items"]["phantom_9"],
            "quality": None,
            "manual_confirm_item_id": None,
        }

        sync_phantom_items_from_overlay_after_pricing(overlay, ph_items, pref)
        self.assertEqual(pk.quality, 5)
        self.assertEqual(pref["phantom_9"], 5)

        board2 = {**snap, "raw_pricing": raw, "grid_overlay": overlay}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board2,
            event_stats=raw["event_stats"],
        )
        self.assertEqual(detail.get("items") or [], [])
        merged = strat_common._grid_overlay.merged_items_dict(board2)
        self.assertEqual(int((merged.get("phantom_9") or {}).get("quality") or 0), 5)

    def test_phantom_alloc_synced_row_skips_repeat_allocation(self) -> None:
        """分摊写回且 ``quality`` 与 ``phantom_quality_pref`` 对齐后，同快照重算不再重复分摊。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        overlay = snap["grid_overlay"]
        overlay["phantom_items"]["phantom_9"]["quality"] = 6
        overlay["phantom_quality_pref"] = {"phantom_9": 6}
        raw = {
            "csv_quality_groups_avg_per_cell": {"q6": 200.0, "all": 1000.0},
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q6_grid_min": 4,
            },
        }
        board = {**snap, "raw_pricing": raw}
        merged = strat_common._grid_overlay.merged_items_dict(board)
        self.assertTrue(
            strat_common._phantom_row_manually_confirmed(
                board, "phantom_9", merged["phantom_9"]
            )
        )
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
        )
        self.assertEqual(detail.get("items") or [], [])

    def test_phantom_item_confirm_syncs_pref_for_idempotent_repricing(self) -> None:
        """分摊锁定物品后 ``phantom_quality_pref`` 与品质对齐，重算 ``pricing`` 与首次一致。"""
        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        overlay = snap["grid_overlay"]
        overlay["phantom_items"]["phantom_9"]["shape"] = 52
        overlay["manual_shapes"] = {"phantom_9": [5, 2, 0, 0]}
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_min": 10,
                "q5_grid_count": 0,
            },
        }
        board = {**snap, "raw_pricing": raw}
        p1 = bp.build_snapshot_pricing_dict(board, snapshot_path_hint=None)
        ph_row = (board["grid_overlay"]["phantom_items"])["phantom_9"]
        self.assertIsNotNone(ph_row.get("manual_confirm_item_id"))
        self.assertEqual(
            board["grid_overlay"]["phantom_quality_pref"]["phantom_9"],
            int(ph_row["quality"]),
        )
        board2 = json.loads(json.dumps(board))
        p2 = bp.build_snapshot_pricing_dict(board2, snapshot_path_hint=None)
        self.assertEqual(p1.get("points"), p2.get("points"))
        self.assertEqual(p1.get("total"), p2.get("total"))
        self.assertEqual(p1.get("tier_extra_cells"), p2.get("tier_extra_cells"))

    def test_phantom_user_infer_pref_skips_auto_alloc(self) -> None:
        """用户手选「原推断」锁定后：弹窗仍看多品质权重，但不参与自动分摊。"""
        from bidking.analysis.strategy import common as strat_common

        snap = self._phantom_only_snapshot(quality_pref="_phantom_q_infer")
        overlay = snap["grid_overlay"]
        overlay["phantom_quality_user_locked"] = ["phantom_9"]
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 100.0,
                "q6": 200.0,
                "q5+q6": 150.0,
                "all": 1000.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "q5_grid_min": 2,
                "q6_grid_min": 2,
            },
        }
        board = {**snap, "raw_pricing": raw}
        _, detail = strat_common.phantom_unknown_tier_credit_q456(
            board,
            event_stats=raw["event_stats"],
        )
        self.assertEqual(detail.get("items") or [], [])
        merged = strat_common._grid_overlay.merged_items_dict(board)
        self.assertIsNone((merged.get("phantom_9") or {}).get("quality"))

    def test_tier_grid_min_no_extra_when_min_le_confirmed(self) -> None:
        """``q4_grid_min`` 不大于已确认紫格占位时，与未填 ``q4_grid_min`` 的 points 一致。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {
                "p": {
                    "uid": "p",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 4,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw_base = {
            "csv_quality_groups_avg_per_cell": {"q4": 10.0, "all": 1000.0},
            "event_stats": {},
        }
        raw_min = {**raw_base, "event_stats": {"q4_grid_min": 1}}
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5}
        p0 = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_base}, snapshot_path_hint=None)
        p1 = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw_min}, snapshot_path_hint=None)
        self.assertEqual(p1["points"], p0["points"])

    def test_ahmad_points_from_event_stats(self) -> None:
        """``pricing.ahmad_points`` 由 ``raw_pricing.event_stats`` 简单公式汇总。"""
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        p = bp.build_snapshot_pricing_dict(
            {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw},
            snapshot_path_hint=None,
        )
        # 20*1000 + 5*1000 + 0 + 0
        self.assertEqual(p.get("ahmad_points"), 25000)
        self.assertFalse(p.get("ahmad_pricing_active"))
        self.assertNotIn("generic_points", p)

    def test_ahmad_hero_204_main_points_match_ahmad_points(self) -> None:
        """己方 hero_cid=204 且快递站地图（档键 210）时 points/floor/ceiling 取 ahmad_points，并保留 generic_* 对照。"""
        self_uid = "358372071974712"
        gs = {
            "uid": "u1",
            "map_id": 2102,
            "current_round": 5,
            "players": {self_uid: {"name": "me", "hero_cid": 204}},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2102,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p = bp.build_snapshot_pricing_dict(
            snap,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": self_uid},
        )
        self.assertTrue(p.get("ahmad_pricing_active"))
        self.assertEqual(p.get("ahmad_points"), 25000)
        self.assertEqual(p.get("points"), 25000)
        self.assertEqual(p.get("points_floor"), 25000)
        self.assertEqual(p.get("points_ceiling"), 25000)
        self.assertIn("generic_points", p)
        self.assertNotEqual(p.get("generic_points"), p.get("points"))
        detail = p.get("ahmad_points_detail")
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("ahmad_points"), 25000)

    def test_ahmad_hero_resolve_self_by_cross_game_uid_inference(self) -> None:
        """跨对局 UID 交集唯一时，无显式 ``self_user_uid`` 也可启用 Ahmad 主价。"""
        shared = "941456831344888"
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        gs1 = {
            "uid": "game_one",
            "map_id": 2102,
            "current_round": 5,
            "players": {
                shared: {"name": "me", "hero_cid": 204},
                "431695757047642": {"name": "opp", "hero_cid": 209},
            },
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap1 = {
            "game_state": gs1,
            "skill_logs": [],
            "map_id": 2102,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p1 = bp.build_snapshot_pricing_dict(
            snap1,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": ""},
        )
        self.assertFalse(p1.get("ahmad_pricing_active"))

        gs2 = {
            "uid": "game_two",
            "map_id": 2102,
            "current_round": 5,
            "players": {
                shared: {"name": "me", "hero_cid": 204},
                "777777777777777": {"name": "newopp", "hero_cid": 209},
            },
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap2 = {
            "game_state": gs2,
            "skill_logs": [],
            "map_id": 2102,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p2 = bp.build_snapshot_pricing_dict(
            snap2,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": ""},
        )
        self.assertTrue(p2.get("ahmad_pricing_active"))
        self.assertEqual(p2.get("points"), p2.get("ahmad_points"))
        inf = p2.get("self_uid_inference") or {}
        self.assertEqual(inf.get("inferred_self_user_uid"), shared)

    def test_configured_self_uid_in_players_uses_config_no_inference(self) -> None:
        """配置 UID 在本局 players 中：走 configured_in_players，首局即可 Ahmad。"""
        me = "358372071974712"
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        gs = {
            "uid": "g_one",
            "map_id": 2102,
            "current_round": 5,
            "players": {
                me: {"name": "a", "hero_cid": 204},
                "999": {"name": "b", "hero_cid": 209},
            },
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2102,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p = bp.build_snapshot_pricing_dict(
            snap,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": me},
        )
        self.assertTrue(p.get("ahmad_pricing_active"))
        inf = p.get("self_uid_inference") or {}
        self.assertEqual(inf.get("identity_mode"), "configured_in_players")
        self.assertEqual(inf.get("resolved_self_user_uid"), me)

    def test_first_game_two_players_no_inference_ahmad_inactive(self) -> None:
        """首局两玩家且无显式 UID：无法唯一推断己方，Ahmad 主价不启用。"""
        gs = {
            "uid": "u_only_one_game",
            "map_id": 2102,
            "current_round": 5,
            "players": {
                "1": {"name": "PlayerA_x", "hero_cid": 204},
                "2": {"name": "PlayerB_x", "hero_cid": 209},
            },
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {"total_count": 20},
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2102,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p = bp.build_snapshot_pricing_dict(
            snap,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": ""},
        )
        self.assertFalse(p.get("ahmad_pricing_active"))
        self.assertTrue(bp.map_bundle_is_express_station_series(2101))
        self.assertTrue(bp.map_bundle_is_express_station_series(2107))
        self.assertFalse(bp.map_bundle_is_express_station_series(2306))
        self.assertFalse(bp.map_bundle_is_express_station_series(0))

    def test_ahmad_hero_204_non_express_uses_generic_pricing(self) -> None:
        """己方 Ahmad 但非快递站地图时不启用 ahmad 主价（无 generic_* 对照段）。"""
        self_uid = "358372071974712"
        gs = {
            "uid": "u1",
            "map_id": 2306,
            "current_round": 5,
            "players": {self_uid: {"name": "me", "hero_cid": 204}},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {"q5": 1.0, "q5+q6": 1.0, "q6": 1.0},
            "event_stats": {
                "total_count": 20,
                "q4_grid_min": 5,
                "q5_grid_min": None,
                "q6_grid_min": None,
            },
        }
        snap = {
            "game_state": gs,
            "skill_logs": [],
            "map_id": 2306,
            "current_round": 5,
            "raw_pricing": raw,
        }
        p = bp.build_snapshot_pricing_dict(
            snap,
            snapshot_path_hint=None,
            board_snapshot_config={"self_user_uid": self_uid},
        )
        self.assertFalse(p.get("ahmad_pricing_active"))
        self.assertNotIn("generic_points", p)
        self.assertEqual(p.get("ahmad_points"), 25000)

    def test_raw_pricing_contains_requested_event_stats(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 2101,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        logs = [
            {"game_data": {"MapSkillLog": [{"SkillCid": 200017, "HitItemIndex": 21, "AllHitItemAvgPrice": 123.5}]}},
            {"game_data": {"HeroSkillLog": [{"SkillCid": 1002044, "HitItemIndex": 6}]}},
            {"game_data": {"MapSkillLog": [{"SkillCid": 200019, "HitItemIndex": 3}]}},
            {
                "game_data": {
                    "MapSkillLog": [
                        {
                            "SkillCid": 200038,
                            "HitItemIndex": 1,
                            "AllHitItemAvgPrice": 456.7,
                        }
                    ]
                }
            },
            {
                "game_data": {
                    "MapSkillLog": [
                        {
                            "SkillCid": 200037,
                            "HitItemIndex": 3,
                            "AllHitItemAvgPrice": 99.5,
                        }
                    ]
                }
            },
            {
                "game_data": {
                    "ItemSkillLog": [
                        {
                            "SkillCid": 504,
                            "ItemCid": 100125,
                            "HitItemTotalPrice": 298,
                        },
                        {
                            "SkillCid": 505,
                            "ItemCid": 100126,
                            "HitItemTotalPrice": 457,
                        },
                    ]
                }
            },
        ]
        raw = build_raw_pricing_dict(
            map_id=2101,
            skill_logs=logs,
            snapshot_path_hint=None,
        )
        st = raw.get("event_stats") or {}
        self.assertIn("csv_quality_groups_avg_per_cell", raw)
        self.assertIn("csv_quality_groups_avg_per_item", raw)
        self.assertIn("total_count", st)
        self.assertEqual(st.get("total_count"), 21)
        self.assertIn("total_grid_count", st)
        self.assertIn("q5_count", st)
        self.assertEqual(st.get("q5_count"), 3)
        self.assertIn("q5_grid_count", st)
        self.assertEqual(st.get("q5_price_avg"), 99.5)
        self.assertEqual(st.get("q5_price_total"), 298)
        self.assertIn("q6_price_avg", st)
        self.assertEqual(st.get("q6_price_total"), 457)
        self.assertIn("q6_count_min", st)

    def test_build_snapshot_pricing_from_snapshot_with_raw_pricing(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 0,
            "current_round": 5,
            "players": {},
            "items": {},
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = build_raw_pricing_dict(
            map_id=0,
            skill_logs=[],
            snapshot_path_hint=None,
        )
        snap = {"game_state": gs, "skill_logs": [], "map_id": 0, "current_round": 5, "raw_pricing": raw}
        p = bp.build_snapshot_pricing_dict(snap)
        self.assertEqual(p.get("total"), 0.0)

    def test_build_snapshot_uses_raw_pricing_csv_units(self) -> None:
        snap = {
            "game_state": {
                "uid": "u1",
                "map_id": 9999,
                "current_round": 5,
                "players": {},
                "items": {
                    "a": {
                        "uid": "a",
                        "box_id": 2,
                        "box_id_confirmed": True,
                        "shape": 11,
                        "quality": 1,
                        "categories": [],
                        "item_cid": None,
                        "price": None,
                        "manual_confirm_item_id": None,
                        "excluded_categories": [],
                        "excluded_qualities": [],
                    }
                },
                "displayed_event_uids": [],
                "scan_history": [],
            },
            "skill_logs": [],
            "current_round": 5,
            "map_id": 9999,
            "raw_pricing": {
                "csv_quality_groups_avg_per_cell": {
                    "q5": 111.0,
                    "q5+q6": 222.0,
                    "q6": 333.0,
                }
            },
        }
        p = bp.build_snapshot_pricing_dict(snap)
        self.assertEqual(p.get("vacant_unit_all_orange"), 111)
        self.assertEqual(p.get("vacant_unit_gold_red"), 222)
        self.assertEqual(p.get("vacant_unit_all_red"), 333)
        self.assertEqual(p.get("vacant"), 2)
        t = float(p.get("total") or 0.0)
        vac = int(p.get("vacant") or 0)
        self.assertEqual(p.get("known_contour_weighted_price"), 0.0)
        self.assertEqual(p.get("known_contour_weighted_cells"), 0)
        self.assertEqual(p.get("est_orange"), int(round(t + float(vac) * 111.0)))
        self.assertEqual(p.get("vacant_pts_base"), t)
        self.assertEqual(p.get("vacant_adj"), vac)

    def test_blend_random_avg_helper_q14_separate_floor_ceiling(self) -> None:
        ev = {"random_avg_price_min": 1_531_348}
        pts, pf, pc, blended = bp._blend_points_with_random_avg_min_if_dominant(
            270_243.0,
            270_243.0,
            501_215.0,
            ev,
            collapse_floor_ceiling=False,
        )
        self.assertTrue(blended)
        self.assertEqual(pts, 1_531_348 + 270_243 / 3)
        self.assertEqual(pf, 1_531_348 + 270_243 / 3)
        self.assertEqual(pc, 1_531_348 + 501_215 / 3)

    def test_blend_random_avg_helper_early_collapses_floor_ceiling(self) -> None:
        ev = {"random_avg_price_min": 900_000}
        pts, pf, pc, blended = bp._blend_points_with_random_avg_min_if_dominant(
            200_000.0,
            200_000.0,
            200_000.0,
            ev,
            collapse_floor_ceiling=True,
        )
        self.assertTrue(blended)
        self.assertEqual(pts, pf)
        self.assertEqual(pts, 900_000 + 200_000 / 3)

    def test_blend_random_avg_skipped_when_not_dominant(self) -> None:
        ev = {"random_avg_price_min": 100_000}
        pts, pf, pc, blended = bp._blend_points_with_random_avg_min_if_dominant(
            300_000.0,
            280_000.0,
            500_000.0,
            ev,
            collapse_floor_ceiling=False,
        )
        self.assertFalse(blended)
        self.assertEqual(pts, 300_000.0)
        self.assertEqual(pf, 280_000.0)
        self.assertEqual(pc, 500_000.0)

    def test_q14_known_random_avg_blended_in_snapshot_pricing(self) -> None:
        gs = {
            "uid": "u1",
            "map_id": 4510,
            "current_round": 5,
            "players": {},
            "items": {
                "a": {
                    "uid": "a",
                    "box_id": 3,
                    "box_id_confirmed": True,
                    "shape": 11,
                    "quality": 1,
                    "categories": [],
                    "item_cid": None,
                    "price": None,
                    "manual_confirm_item_id": None,
                    "excluded_categories": [],
                    "excluded_qualities": [],
                }
            },
            "displayed_event_uids": [],
            "scan_history": [],
        }
        raw = {
            "csv_quality_groups_avg_per_cell": {
                "q5": 9435.0,
                "q5+q6": 25933.0,
                "q6": 51093.0,
            },
            "event_stats": {
                "q1_grid_count": 1,
                "q2_grid_count": 1,
                "q3_grid_count": 1,
                "q4_grid_count": 1,
                "random_avg_price_min": 1_500_000,
            },
        }
        snap = {"game_state": gs, "skill_logs": [], "map_id": 4510, "current_round": 5}
        p = bp.build_snapshot_pricing_dict({**snap, "raw_pricing": raw}, snapshot_path_hint=None)
        self.assertTrue(p.get("early_points_blended_with_random_avg"))
        base_pts = p["total"] + p["vacant"] * 9435
        self.assertEqual(p["points"], int(round(1_500_000 + base_pts / 3)))


class SelfUidInferencePersistTests(unittest.TestCase):
    """单独验证推断 UID 写回 ``config.json`` overlay（不继承 BoardPricingTests 的禁用写盘）。"""

    def setUp(self) -> None:
        import os

        from bidking.pricing._self_uid_inference import reset_self_uid_inference_state

        reset_self_uid_inference_state()
        self._prev = os.environ.get("BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST")
        os.environ.pop("BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST", None)

    def tearDown(self) -> None:
        import os

        from bidking.pricing._self_uid_inference import reset_self_uid_inference_state

        reset_self_uid_inference_state()
        if self._prev is None:
            os.environ.pop("BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST", None)
        else:
            os.environ["BIDKING_DISABLE_SELF_UID_CONFIG_PERSIST"] = self._prev

    def test_inferred_uid_written_to_config_overlay(self) -> None:
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import bidking.config.paths as paths_mod

        from bidking.analysis import _board_pricing as bp

        if "BIDKING_SELF_USER_UID" in os.environ:
            self.skipTest("skip when env forces uid")

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            p.write_text(
                json.dumps({"board_snapshot": {"enabled": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(paths_mod, "config_overlay_path", return_value=p.resolve()):
                uid = "501112223334455"
                raw = {
                    "csv_quality_groups_avg_per_cell": {
                        "q5": 1.0,
                        "q5+q6": 1.0,
                        "q6": 1.0,
                    },
                    "event_stats": {"total_count": 20},
                }
                gs = {
                    "uid": "solo",
                    "map_id": 2102,
                    "current_round": 2,
                    "players": {uid: {"name": "solo", "hero_cid": 204}},
                    "items": {},
                    "displayed_event_uids": [],
                    "scan_history": [],
                }
                snap = {
                    "game_state": gs,
                    "skill_logs": [],
                    "map_id": 2102,
                    "current_round": 2,
                    "raw_pricing": raw,
                }
                bp.build_snapshot_pricing_dict(
                    snap,
                    board_snapshot_config={"self_user_uid": ""},
                )
                data = json.loads(p.read_text(encoding="utf-8"))
                self.assertEqual(
                    (data.get("board_snapshot") or {}).get("self_user_uid"),
                    uid,
                )


if __name__ == "__main__":
    unittest.main()
