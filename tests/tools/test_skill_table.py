# -*- coding: utf-8 -*-

from pathlib import Path

from bidking.tools import skill_table as st


def test_skill_csv_row_to_export_cols() -> None:
    row = {
        "id": "100",
        "col_1": "全库透视",
        "col_2": "显示轮廓",
        "skill_group": "",
        "skill_name": "itemName_100100",
        "skilldesc": "skillDesc_100",
        "skill_textshow": "",
        "skill_type": "2",
        "skilltarget": "0",
        "skilltargetvalue": "[0]",
        "skilltarget2": "0",
        "skilltargetvalue2": "[0]",
        "skilltarget3": "0",
        "skilltargetvalue3": "[0]",
        "skill_count_type": "1",
        "skill_count": "0",
        "skilleffect_position": "[1000]",
        "skill_icon": "5",
        "skill_value": "[]",
        "skill_active_type": "1",
        "skill_opt": "0",
        "skill_opt_param1": "[[0]]",
        "skill_opt_param2": "[[0]]",
        "skill_cast": "[[1,1000,0]]",
        "skill_round": "0",
        "skill_CD": "0",
        "show_type": "0",
    }
    cols = st.skill_csv_row_to_export_cols(row)
    assert cols[0] == "100"
    assert cols[1] == "全库透视"
    assert cols[16] == "[1000]"
    assert len(cols) == len(st._SKILL_CSV_FIELDS)


def test_export_skill_csv_writes_rows(tmp_path: Path) -> None:
    skill = tmp_path / "Skill.csv"
    skill.write_text(
        "id,col_1,col_2,skill_group,skill_name,skilldesc,skill_textshow,skill_type,"
        "skilltarget,skilltargetvalue,skilltarget2,skilltargetvalue2,skilltarget3,"
        "skilltargetvalue3,skill_count_type,skill_count,skilleffect_position,skill_icon,"
        "skill_value,skill_active_type,skill_opt,skill_opt_param1,skill_opt_param2,"
        "skill_cast,skill_round,skill_CD,show_type\n"
        "100,n,d,,itemName_100100,skillDesc_100,,2,0,[0],0,[0],0,[0],1,0,[1000],5,[],1,0,"
        "[[0]],[[0]],[[1,1000,0]]],0,0,0\n",
        encoding="utf-8-sig",
    )
    out = tmp_path / "out.csv"
    n = st.export_skill_csv(skill, out)
    assert n == 1
    text = out.read_text(encoding="utf-8-sig")
    assert "skill_id" in text
    assert "100" in text
