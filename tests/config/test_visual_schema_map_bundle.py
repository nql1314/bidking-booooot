# -*- coding: utf-8 -*-
"""visual_schema：map_bundle_keys 按地图档键过滤字段。"""

from bidking.config.visual_schema import (
    field_matches_map_bundle,
    load_visual_config_schema,
    schema_fields_for_scope,
)


def test_express_emoji_fields_only_on_map_210() -> None:
    schema = load_visual_config_schema()
    paths_210 = {
        f["path"]
        for f in schema_fields_for_scope(schema, "map", map_bundle_key="210")
        if str(f.get("path", "")).startswith("automation.express_station_round1_emoji")
    }
    paths_230 = {
        f["path"]
        for f in schema_fields_for_scope(schema, "map", map_bundle_key="230")
        if str(f.get("path", "")).startswith("automation.express_station_round1_emoji")
    }
    assert "automation.express_station_round1_emoji.enabled" in paths_210
    assert "automation.express_station_round1_emoji.character_name" in paths_210
    assert "automation.express_station_round1_emoji.character_title" in paths_210
    assert paths_230 == set()


def test_field_matches_map_bundle() -> None:
    field = {"map_bundle_keys": ["210"]}
    assert field_matches_map_bundle(field, "210") is True
    assert field_matches_map_bundle(field, "230") is False
    assert field_matches_map_bundle(field, None) is False
    assert field_matches_map_bundle({}, "210") is True
