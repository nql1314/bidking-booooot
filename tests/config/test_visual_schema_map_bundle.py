# -*- coding: utf-8 -*-
"""visual_schema：map_bundle_keys 按地图档键过滤字段。"""

from bidking.config.visual_schema import (
    field_matches_map_bundle,
    load_visual_config_schema,
    schema_fields_for_scope,
)


def test_field_matches_map_bundle() -> None:
    field = {"map_bundle_keys": ["210"]}
    assert field_matches_map_bundle(field, "210") is True
    assert field_matches_map_bundle(field, "230") is False
    assert field_matches_map_bundle(field, None) is False
    assert field_matches_map_bundle({}, "210") is True


def test_map_bundle_scoped_fields_resolve() -> None:
    schema = load_visual_config_schema()
    fields_210 = schema_fields_for_scope(schema, "map", map_bundle_key="210")
    assert any(
        str(f.get("path")) == "automation.bid_cap_price" for f in fields_210
    )
