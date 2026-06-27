# -*- coding: utf-8 -*-
from pathlib import Path

from bidking.parsing import item_db


def test_normalize_activity_ship_map_45xx_to_25xx() -> None:
    assert item_db.normalize_map_id(4525) == 2525
    assert item_db.normalize_map_id(2525) == 2525


def test_normalize_rank_villa_map_56xx_to_2401_pool() -> None:
    for mid in range(5601, 5612):
        assert item_db.normalize_map_id(mid) == 2401


def test_rank_villa_maps_share_2401_tier_nest() -> None:
    nest = item_db.MAP_TO_TIER_NEST[2401]
    for mid in range(5601, 5612):
        assert item_db.MAP_TO_TIER_NEST[mid] == nest == (104, 2031)


def test_activity_ship_maps_share_base_tier_nest() -> None:
    assert item_db.MAP_TO_TIER_NEST[2521] == item_db.MAP_TO_TIER_NEST[2501]
    assert item_db.MAP_TO_TIER_NEST[2530] == item_db.MAP_TO_TIER_NEST[2510]
    assert item_db.MAP_TO_TIER_NEST[2521] == (105, 2041)


def test_ship_series_weight_fallback_map_id() -> None:
    assert item_db.ship_series_weight_fallback_map_id(2521) == 2501
    assert item_db.ship_series_weight_fallback_map_id(2530) == 2510
    assert item_db.ship_series_weight_fallback_map_id(2515) == 2505
    assert item_db.ship_series_weight_fallback_map_id(2535) == 2505
    assert item_db.ship_series_weight_fallback_map_id(4531) == 2501
    assert item_db.ship_series_weight_fallback_map_id(4525) == 2505
    assert item_db.ship_series_weight_fallback_map_id(2511) == 2501
    assert item_db.ship_series_weight_fallback_map_id(2501) is None
    assert item_db.ship_series_weight_fallback_map_id(2401) is None


def test_normalize_unknown_ship_series_to_base_submap() -> None:
    assert item_db.normalize_map_id(2535) == 2505
    assert item_db.normalize_map_id(4535) == 2505
    assert item_db.normalize_map_id(6535) == 6535


def test_map_id_for_drop_weights_activity_matches_base() -> None:
    item_db.load_drop_weights(
        str(Path(__file__).resolve().parents[2] / "data" / "calculator_data_merged.csv")
    )
    assert item_db.map_tier_nest_for_weights(2521) == item_db.map_tier_nest_for_weights(2501)
    assert item_db.map_tier_nest_for_weights(4525) == item_db.map_tier_nest_for_weights(4505)
    assert item_db.map_tier_nest_for_weights(2535) == item_db.map_tier_nest_for_weights(2505)
    assert item_db.map_tier_nest_for_weights(2521) == (105, 2041)
    assert item_db.map_id_for_drop_weights(2511) == 2511


def test_merge_config_overrides_560_independent_of_240() -> None:
    from bidking.analysis.map_avg_csv import resolve_map_id_for_quality_csv
    from bidking.analysis.map_quality_unit_config import merge_config_overrides_into_runtime
    from bidking.config.map_runtime_overlay import merged_runtime_with_map_pricing
    from bidking.parsing.item_db import map_bundle_key_for_automation

    assert map_bundle_key_for_automation(5607) == "560"
    resolved_5607 = resolve_map_id_for_quality_csv(5607)
    assert resolved_5607 != 2401
    assert 5601 <= resolved_5607 <= 5611

    base: dict = {"pricing": {}, "automation": {"selected_map": "210"}}
    q560 = (
        merged_runtime_with_map_pricing(base, map_bundle_key="560")
        .get("pricing", {})
        .get("map_quality_unit_per_cell", {})
    )
    q240 = (
        merged_runtime_with_map_pricing(base, map_bundle_key="240")
        .get("pricing", {})
        .get("map_quality_unit_per_cell", {})
    )
    assert q560.get("q56") == 22000.0
    assert q240.get("q56") == 22000.0
    assert merge_config_overrides_into_runtime(base, 5607) == q560
    assert merge_config_overrides_into_runtime(base, 2401) == q240


def test_rank_map_csv_covers_all_map_ids() -> None:
    data = Path(__file__).resolve().parents[2] / "data"
    for name in ("RankMap.csv", "rank_map_export.csv"):
        path = data / name
        if path.is_file():
            break
    else:
        return
    if path.name == "rank_map_export.csv":
        import csv

        with path.open(encoding="utf-8-sig", newline="") as f:
            ids = [int(row["map_id"]) for row in csv.DictReader(f) if row.get("map_id")]
    else:
        from bidking.tools.game_tables import load_rank_map_rows_from_csv

        ids = [int(row[0]) for row in load_rank_map_rows_from_csv(path)]
    missing = [
        mid
        for mid in ids
        if item_db.normalize_map_id(mid) not in item_db.MAP_TO_TIER_NEST
    ]
    assert missing == [], f"RankMap ids missing from MAP_TO_TIER_NEST: {missing}"
