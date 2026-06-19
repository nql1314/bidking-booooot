# -*- coding: utf-8 -*-
from pathlib import Path

from bidking.parsing import item_db


def test_normalize_activity_ship_map_45xx_to_25xx() -> None:
    assert item_db.normalize_map_id(4525) == 2525
    assert item_db.normalize_map_id(2525) == 2525


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


def test_rank_map_decoded_covers_all_map_ids() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "RankMap.decoded.tsv"
    if not path.is_file():
        return
    ids = [
        int(line.split("\t", 1)[0])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    missing = [
        mid
        for mid in ids
        if item_db.normalize_map_id(mid) not in item_db.MAP_TO_TIER_NEST
    ]
    assert missing == [], f"RankMap ids missing from MAP_TO_TIER_NEST: {missing}"
