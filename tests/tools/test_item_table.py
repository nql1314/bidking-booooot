# -*- coding: utf-8 -*-

import base64
import csv
from pathlib import Path

from bidking.tools import item_table as it


def _b64_utf8(s: str) -> bytes:
    return base64.b64encode(s.encode("utf-8"))


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


def test_parse_item_rows_filters_and_maps():
    line = "\t".join(
        [
            "1013001",
            "烧烤架",
            "",
            "itemName_1013001",
            "",
            "",
            "[101,109]",
            "22",
            "3",
            "3855",
        ]
    )
    rows = it.parse_item_rows(line + "\n", {})
    assert len(rows) == 1
    row = rows[0]
    assert row.item_id == 1013001
    assert row.name == "烧烤架"
    assert row.category_tags == (101, 109)
    assert row.shape == 22
    assert row.quality == 3
    assert row.base_value == 3855


def test_export_item_txt_writes_csv(tmp_path: Path):
    inner = "\t".join(
        [
            "1013001",
            "烧烤架",
            "",
            "itemName_1013001",
            "",
            "",
            "[101,109]",
            "22",
            "3",
            "3855",
        ]
    )
    item = tmp_path / "Item.txt"
    item.write_bytes(_b64_utf8(inner))
    out = tmp_path / "item_prices.csv"
    n = it.export_item_txt(item, out)
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
