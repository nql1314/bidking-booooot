# -*- coding: utf-8 -*-
import csv
from pathlib import Path

from bidking.tools import game_tables as gt


def test_parse_drop_items_list():
    raw = "[[8,8001,1,1,10],[11,9001,1,1,5]]"
    edges = gt.parse_drop_items_list(801, raw)
    assert (801, 8001, 10, 8) in edges
    assert (801, 9001, 5, 11) in edges
    assert len(edges) == 2
    assert gt.parse_drop_items_list(802, "[]") == []


def test_load_drop_edges_from_csv(tmp_path: Path):
    drop = tmp_path / "Drop.csv"
    drop.write_text(
        "group_id,col_1,col_2,weight_type,items_list\n"
        '801,,个人测试,2,"[[8,8001,1,1,10],[11,9001,1,1,5]]"\n'
        "802,,,1,[]\n",
        encoding="utf-8-sig",
    )
    edges = gt.load_drop_edges_from_csv(drop)
    assert (801, 8001, 10, 8) in edges
    assert (801, 9001, 5, 11) in edges
    assert len(edges) == 2


def test_load_rank_map_rows_from_csv(tmp_path: Path):
    rank = tmp_path / "RankMap.csv"
    rank.write_text(
        "id,col_1,col_2,match_time,role_spawn,min_bid_range,bid_type\n"
        '2101,未知,描述,"[[1,2,3]]","[[101,50]]","[]","[1,2]"\n'
        "2102,b,c,d,e,f,g\n",
        encoding="utf-8-sig",
    )
    rows = gt.load_rank_map_rows_from_csv(rank)
    assert rows[0][0] == "2101"
    assert rows[0][3] == "[[1,2,3]]"
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
