# -*- coding: utf-8 -*-

import csv
from pathlib import Path

from bidking.tools import item_table as it


def test_parse_int_list():
    assert it.parse_int_list("[101,109]") == [101, 109]
    assert it.parse_int_list("14") == [14]
    assert it.parse_int_list("") == []


def test_include_item_rules():
    assert it.include_item(1013001, [101, 109])
    assert it.include_item(1410101, [14])
    assert it.include_item(1006001, [100])
    assert not it.include_item(101, [2])
    assert not it.include_item(1001, [7])


def test_parse_item_csv_rows_filters_and_maps(tmp_path: Path):
    item = tmp_path / "Item.csv"
    item.write_text(
        "id,col_1,col_2,item_name,item_nm,item_desc,item_type_id,slot_type,item_quality,base_value\n"
        "1013001,烧烤架,,itemName_1013001,,,\"[101,109]\",22,3,3855\n",
        encoding="utf-8-sig",
    )
    rows = it.parse_item_csv_rows(item, {})
    assert len(rows) == 1
    row = rows[0]
    assert row.item_id == 1013001
    assert row.name == "烧烤架"
    assert row.category_tags == (101, 109)
    assert row.shape == 22
    assert row.quality == 3
    assert row.base_value == 3855


def test_export_item_csv_writes_csv(tmp_path: Path):
    item = tmp_path / "Item.csv"
    item.write_text(
        "id,col_1,col_2,item_name,item_nm,item_desc,item_type_id,slot_type,item_quality,base_value\n"
        "1013001,烧烤架,,itemName_1013001,,,\"[101,109]\",22,3,3855\n",
        encoding="utf-8-sig",
    )
    out = tmp_path / "item_prices.csv"
    n = it.export_item_csv(item, out)
    assert n == 1
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["item_id"] == "1013001"
    assert rows[0]["name"] == "烧烤架"
    assert rows[0]["category_tags"] == "[101,109]"
    assert rows[0]["shape"] == "22"
    assert rows[0]["quality"] == "3"
    assert rows[0]["base_value"] == "3855"
    assert rows[0]["grid_size"] == "[10,5]"
