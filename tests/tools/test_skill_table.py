# -*- coding: utf-8 -*-

from pathlib import Path

from bidking.tools import skill_table as st


def test_parse_skill_tsv_pads_and_truncates(tmp_path: Path) -> None:
    decoded = "a\tb\tc\n" + "\t".join(str(i) for i in range(30))
    rows = st.parse_skill_tsv(decoded)
    assert len(rows) == 2
    assert rows[0] == ["a", "b", "c"] + [""] * (st._NCOL - 3)
    assert len(rows[1]) == st._NCOL
    assert rows[1][0] == "0"
    assert rows[1][-1] == "26"


def test_export_skill_txt_writes_rows(tmp_path: Path) -> None:
    inner = "\t".join(["100", "n", "d"] + [""] * (st._NCOL - 3))
    b64 = __import__("base64").b64encode(inner.encode("utf-8"))
    skill = tmp_path / "Skill.txt"
    skill.write_bytes(b64)
    out = tmp_path / "out.csv"
    n = st.export_skill_txt(skill, out)
    assert n == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "skill_id" in text
    assert "100" in text
