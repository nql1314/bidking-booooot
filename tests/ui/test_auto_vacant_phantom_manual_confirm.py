# -*- coding: utf-8 -*-
"""自动 phantom_vac_* 用户手动物品确认在 purge 重算后应保留。"""

from __future__ import annotations

import unittest

from bidking.analysis.grid_overlay_infer_vacant_rects import VacantRectPhantomSpec
from bidking.parsing.state import ItemKnowledge
from bidking.ui.grid._overlay_reconcile import (
    AutoVacantPhantomSavedState,
    apply_auto_vacant_phantom_manual_confirm,
    restore_auto_vacant_phantom_user_locked,
    snapshot_auto_vacant_phantom_user_state,
)


class AutoVacantPhantomManualConfirmTests(unittest.TestCase):
    def test_snapshot_restores_user_locked_manual_confirm_over_infer(self) -> None:
        uid = "phantom_vac_0_0_2x2"
        pk = ItemKnowledge(uid=uid)
        pk.manual_confirm_item_id = 1033003
        ph = {uid: pk}
        pref: dict = {uid: "_phantom_q_infer"}
        locked = {uid}
        saved = snapshot_auto_vacant_phantom_user_state(ph, pref, locked)
        self.assertEqual(saved[uid].manual_confirm_item_id, 1033003)
        self.assertTrue(saved[uid].user_locked)

        pk2 = ItemKnowledge(uid=uid)
        spec = VacantRectPhantomSpec(
            uid=uid,
            w=2,
            h=2,
            dc=0,
            dr=0,
            manual_confirm_item_id=9999999,
        )
        apply_auto_vacant_phantom_manual_confirm(uid, pk2, spec, saved)
        self.assertEqual(pk2.manual_confirm_item_id, 1033003)

        locked_out: set = set()
        restore_auto_vacant_phantom_user_locked(uid, saved, locked_out)
        self.assertIn(uid, locked_out)

    def test_infer_manual_confirm_used_when_not_user_locked(self) -> None:
        uid = "phantom_vac_1_1_1x1"
        pk = ItemKnowledge(uid=uid)
        ph = {uid: pk}
        saved = snapshot_auto_vacant_phantom_user_state(ph, {}, set())
        spec = VacantRectPhantomSpec(
            uid=uid,
            w=1,
            h=1,
            dc=1,
            dr=1,
            manual_confirm_item_id=42,
        )
        apply_auto_vacant_phantom_manual_confirm(uid, pk, spec, saved)
        self.assertEqual(pk.manual_confirm_item_id, 42)

    def test_pricing_manual_confirm_restored_after_purge_without_user_lock(self) -> None:
        """定价写回的 ``manual_confirm_item_id`` 在 purge 重算后应保留（回放翻页）。"""
        uid = "phantom_vac_0001_3x1"
        pk = ItemKnowledge(uid=uid)
        pk.manual_confirm_item_id = 1046007
        ph = {uid: pk}
        saved = snapshot_auto_vacant_phantom_user_state(ph, {}, set())
        self.assertFalse(saved[uid].user_locked)

        pk2 = ItemKnowledge(uid=uid)
        spec = VacantRectPhantomSpec(uid=uid, w=3, h=1, dc=1, dr=0)
        apply_auto_vacant_phantom_manual_confirm(uid, pk2, spec, saved)
        self.assertEqual(pk2.manual_confirm_item_id, 1046007)


if __name__ == "__main__":
    unittest.main()
