# -*- coding: utf-8 -*-
"""skill_log_game_data_subset：S2C_39 等协议根级 ItemSkillLog 须并入 skill_logs。"""

from bidking.parsing.log_source import skill_log_game_data_subset


def test_subset_prefers_game_data_over_root_when_both_present() -> None:
    data = {
        "GameData": {"ItemSkillLog": [{"ItemCid": 1}], "Round": 2},
        "ItemSkillLog": [{"ItemCid": 99}],
    }
    out = skill_log_game_data_subset(data)
    assert out["ItemSkillLog"] == [{"ItemCid": 1}]
    assert out["Round"] == 2


def test_subset_root_item_skill_log_when_not_in_game_data() -> None:
    data = {"ItemSkillLog": [{"ItemCid": 100136, "SkillCid": 0}]}
    out = skill_log_game_data_subset(data)
    assert out["ItemSkillLog"] == [{"ItemCid": 100136, "SkillCid": 0}]


def test_subset_merges_game_data_and_root() -> None:
    data = {
        "GameData": {"Round": 3, "MapId": 2301},
        "ItemSkillLog": [{"ItemCid": 1}],
    }
    out = skill_log_game_data_subset(data)
    assert out["Round"] == 3
    assert out["MapId"] == 2301
    assert out["ItemSkillLog"] == [{"ItemCid": 1}]
