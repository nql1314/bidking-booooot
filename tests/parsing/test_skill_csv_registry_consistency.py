# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bidking.parsing.constants import resource_path
from bidking.parsing.skill_bindings import validate_skill_registry_vs_csv


class SkillCsvRegistryConsistencyTests(unittest.TestCase):
    def test_skill_export_matches_registry_param16(self) -> None:
        path = resource_path("Skill_export.csv")
        errs = validate_skill_registry_vs_csv(path)
        self.assertEqual(
            errs,
            [],
            "Skill_export 与 skill_bindings 注册表不一致:\n" + "\n".join(errs),
        )


if __name__ == "__main__":
    unittest.main()
