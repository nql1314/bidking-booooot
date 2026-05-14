# -*- coding: utf-8 -*-
import base64
import csv
from pathlib import Path

from bidking.tools import game_tables as gt


def _b64_utf8(s: str) -> bytes:
    return base64.b64encode(s.encode("utf-8"))


def test_decode_if_base64_roundtrip_plaintext():
    plain = "1000\t\t名称\t1\t[[14,1,1,1,100]]\n"
    assert gt.decode_if_base64(plain.encode("utf-8")) == plain


def test_decode_if_base64_wrapped():
    inner = "801\t\t测试\t2\t[[8,8001,1,1,10]]\n"
    blob = _b64_utf8(inner)
    assert gt.decode_if_base64(blob) == inner


def test_parse_drop_edges():
    text = (
        "801\t\t个人测试\t2\t[[8,8001,1,1,10],[11,9001,1,1,5]]\n"
        "802\t\t\t1\t[]\n"
    )
    edges = gt.parse_drop_edges(text)
    assert (801, 8001, 10, 8) in edges
    assert (801, 9001, 5, 11) in edges
    assert len(edges) == 2


def test_parse_rank_map_rows():
    text = (
        "2101\t未知\t描述\t[[1,2,3]]\t[[101,50]]\t[]\t[1,2]\n"
        "2102\tb\tc\td\te\tf\tg\n"
    )
    rows = gt.parse_rank_map_rows(text)
    assert rows[0][0] == "2101"
    assert rows[0][6] == "[1,2]"
    assert rows[1] == ["2102", "b", "c", "d", "e", "f", "g"]


def test_merge_calculator_drop_rows(tmp_path: Path):
    merged = tmp_path / "calculator_data_merged.csv"
    merged.write_text(
        "record_type,item_id,name,quality,base_value,shape,drop_id,ref_id,weight,ref_type\n"
        'ITEM,1,n,1,1,1,0,0,0,0\n'
        'DROP,0,0,0,0,0,801,8001,10,8\n',
        encoding="utf-8-sig",
    )
    out = tmp_path / "out.csv"
    gt.merge_calculator_drop_rows(merged, [(802, 1, 20, 9)], out)
    with out.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    items = [r for r in rows if r["record_type"] == "ITEM"]
    drops = [r for r in rows if r["record_type"] == "DROP"]
    assert len(items) == 1
    assert items[0]["item_id"] == "1"
    assert len(drops) == 1
    assert drops[0]["drop_id"] == "802"
    assert drops[0]["ref_id"] == "1"
    assert drops[0]["weight"] == "20"
    assert drops[0]["ref_type"] == "9"
