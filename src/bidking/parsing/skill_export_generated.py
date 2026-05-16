# -*- coding: utf-8 -*-
"""由 ``data/Skill_export.csv`` 自动生成的技能全量定义。

勿手改本文件；更新游戏表后重新导出 CSV 并运行:
``python build/generate_skill_export_table.py``

每行技能对应一个 :class:`SkillExportRow` 实例 ``SKILL_EXP_<skill_id>``，
再按「地图竞拍信息 · 技能效果子类 / 英雄 / 道具工具 · 技能效果子类」分别注册，
最终由 :func:`_skill_export_merge_registered_parts` 汇总为 :data:`SKILL_EXPORT_BY_ID`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SkillExportRow:
    """Skill_export.csv 单列（列名与 skill_table 导出一致）。"""
    skill_id: str
    name_zh: str
    desc_zh: str
    reserved_3: str
    item_name_key: str
    skill_desc_key: str
    reserved_6: str
    param_07: str
    param_08: str
    param_09: str
    param_10: str
    param_11: str
    param_12: str
    param_13: str
    param_14: str
    param_15: str
    param_16: str
    param_17: str
    param_18: str
    param_19: str
    param_20: str
    nested_21: str
    nested_22: str
    nested_23: str
    param_24: str
    param_25: str
    param_26: str

    @property
    def skill_id_int(self) -> int:
        """整数 skill_id。"""
        return int(self.skill_id)

SKILL_EXP_100 = SkillExportRow(skill_id='100', name_zh='全库透视', desc_zh='显示所有藏品的轮廓', reserved_3='', item_name_key='itemName_100100', skill_desc_key='skillDesc_100', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_103 = SkillExportRow(skill_id='103', name_zh='四象窥视', desc_zh='随机显示4件藏品轮廓', reserved_3='', item_name_key='itemName_100101', skill_desc_key='skillDesc_103', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='4', param_16='[1000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_106 = SkillExportRow(skill_id='106', name_zh='十方窥视', desc_zh='随机显示10件藏品轮廓', reserved_3='', item_name_key='itemName_100102', skill_desc_key='skillDesc_106', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='10', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200 = SkillExportRow(skill_id='200', name_zh='总仓储空间', desc_zh='所有藏品的总格数为{0}格', reserved_3='', item_name_key='itemName_100103', skill_desc_key='', reserved_6='skillDesc_200', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_201 = SkillExportRow(skill_id='201', name_zh='普品扫描', desc_zh='所有白色和绿色品质藏品总占位数为{0}格', reserved_3='', item_name_key='itemName_100104', skill_desc_key='', reserved_6='skillDesc_201', param_07='2', param_08='2', param_09='[1,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='1', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_202 = SkillExportRow(skill_id='202', name_zh='良品扫描', desc_zh='所有蓝色品质藏品总占位数为{0}格', reserved_3='', item_name_key='itemName_100105', skill_desc_key='', reserved_6='skillDesc_202', param_07='2', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_203 = SkillExportRow(skill_id='203', name_zh='优品扫描', desc_zh='所有紫色品质藏品总占位数为{0}格', reserved_3='', item_name_key='itemName_100106', skill_desc_key='', reserved_6='skillDesc_203', param_07='2', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_204 = SkillExportRow(skill_id='204', name_zh='极品扫描', desc_zh='所有金色品质藏品总占位数为{0}格', reserved_3='', item_name_key='itemName_100107', skill_desc_key='', reserved_6='skillDesc_204', param_07='2', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_205 = SkillExportRow(skill_id='205', name_zh='珍品扫描', desc_zh='所有红色品质藏品总占位数为{0}格', reserved_3='', item_name_key='itemName_100108', skill_desc_key='', reserved_6='skillDesc_205', param_07='2', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_300 = SkillExportRow(skill_id='300', name_zh='均格评估', desc_zh='所有藏品的平均格数为{0}格', reserved_3='', item_name_key='itemName_100109', skill_desc_key='', reserved_6='skillDesc_300', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_301 = SkillExportRow(skill_id='301', name_zh='普品均格', desc_zh='所有白色和绿色品质藏品平均占位{0}格', reserved_3='', item_name_key='itemName_100110', skill_desc_key='', reserved_6='skillDesc_301', param_07='2', param_08='2', param_09='[1,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='1', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_302 = SkillExportRow(skill_id='302', name_zh='良品均格', desc_zh='所有蓝色品质藏品平均占位{0}格', reserved_3='', item_name_key='itemName_100111', skill_desc_key='', reserved_6='skillDesc_302', param_07='2', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_303 = SkillExportRow(skill_id='303', name_zh='优品均格', desc_zh='所有紫色品质藏品平均占位{0}格', reserved_3='', item_name_key='itemName_100112', skill_desc_key='', reserved_6='skillDesc_303', param_07='2', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_304 = SkillExportRow(skill_id='304', name_zh='极品均格', desc_zh='所有金色品质藏品平均占位{0}格', reserved_3='', item_name_key='itemName_100113', skill_desc_key='', reserved_6='skillDesc_304', param_07='2', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_305 = SkillExportRow(skill_id='305', name_zh='珍品均格', desc_zh='所有红色品质藏品平均占位{0}格', reserved_3='', item_name_key='itemName_100114', skill_desc_key='', reserved_6='skillDesc_305', param_07='2', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_400 = SkillExportRow(skill_id='400', name_zh='库存清点', desc_zh='本次竞拍共有{0}件藏品', reserved_3='', item_name_key='itemName_100115', skill_desc_key='', reserved_6='skillDesc_400', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_401 = SkillExportRow(skill_id='401', name_zh='普品存量', desc_zh='绿色品质藏品的总数量为{0}', reserved_3='', item_name_key='itemName_100116', skill_desc_key='', reserved_6='skillDesc_401', param_07='2', param_08='2', param_09='[2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='1', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_402 = SkillExportRow(skill_id='402', name_zh='良品存量', desc_zh='蓝色品质藏品的总数量为{0}', reserved_3='', item_name_key='itemName_100117', skill_desc_key='', reserved_6='skillDesc_402', param_07='2', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_403 = SkillExportRow(skill_id='403', name_zh='优品存量', desc_zh='紫色品质藏品的总数量为{0}', reserved_3='', item_name_key='itemName_100118', skill_desc_key='', reserved_6='skillDesc_403', param_07='2', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_404 = SkillExportRow(skill_id='404', name_zh='极品存量', desc_zh='金色品质藏品的总数量为{0}', reserved_3='', item_name_key='itemName_100119', skill_desc_key='', reserved_6='skillDesc_404', param_07='2', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_405 = SkillExportRow(skill_id='405', name_zh='珍品存量', desc_zh='红色品质藏品的总数量为{0}', reserved_3='', item_name_key='itemName_100120', skill_desc_key='', reserved_6='skillDesc_405', param_07='2', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_500 = SkillExportRow(skill_id='500', name_zh='终极审计', desc_zh='本次竞拍所有藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100121', skill_desc_key='', reserved_6='skillDesc_500', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='6', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_501 = SkillExportRow(skill_id='501', name_zh='普品估价', desc_zh='所有绿色品质藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100122', skill_desc_key='', reserved_6='skillDesc_501', param_07='2', param_08='2', param_09='[2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='1', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_502 = SkillExportRow(skill_id='502', name_zh='良品估价', desc_zh='所有蓝色品质藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100123', skill_desc_key='', reserved_6='skillDesc_502', param_07='2', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_503 = SkillExportRow(skill_id='503', name_zh='优品估价', desc_zh='所有紫色品质藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100124', skill_desc_key='', reserved_6='skillDesc_503', param_07='2', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_504 = SkillExportRow(skill_id='504', name_zh='极品估价', desc_zh='所有金色品质藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100125', skill_desc_key='', reserved_6='skillDesc_504', param_07='2', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_505 = SkillExportRow(skill_id='505', name_zh='珍品估价', desc_zh='所有红色品质藏品的总价值为{0}', reserved_3='', item_name_key='itemName_100126', skill_desc_key='', reserved_6='skillDesc_505', param_07='2', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='6', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_600 = SkillExportRow(skill_id='600', name_zh='全知全能', desc_zh='显示所有藏品', reserved_3='', item_name_key='itemName_100127', skill_desc_key='skillDesc_600', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[6000]', param_17='6', param_18='[800,900]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_601 = SkillExportRow(skill_id='601', name_zh='随机抽检（1）', desc_zh='随机显示1件藏品', reserved_3='', item_name_key='itemName_100128', skill_desc_key='skillDesc_601', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='1', param_18='[1500,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_602 = SkillExportRow(skill_id='602', name_zh='随机抽检（2）', desc_zh='随机显示2件藏品', reserved_3='', item_name_key='itemName_100129', skill_desc_key='skillDesc_602', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[6000]', param_17='2', param_18='[1400,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_603 = SkillExportRow(skill_id='603', name_zh='随机抽检（4）', desc_zh='随机显示4件藏品', reserved_3='', item_name_key='itemName_100130', skill_desc_key='skillDesc_603', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='4', param_16='[6000]', param_17='3', param_18='[1300,1400]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_604 = SkillExportRow(skill_id='604', name_zh='随机抽检（6）', desc_zh='随机显示6件藏品', reserved_3='', item_name_key='itemName_100131', skill_desc_key='skillDesc_604', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='6', param_16='[6000]', param_17='4', param_18='[1200,1300]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_605 = SkillExportRow(skill_id='605', name_zh='随机抽检（8）', desc_zh='随机显示8件藏品', reserved_3='', item_name_key='itemName_100132', skill_desc_key='skillDesc_605', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='8', param_16='[6000]', param_17='5', param_18='[1100,1200]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_606 = SkillExportRow(skill_id='606', name_zh='随机抽检（10）', desc_zh='随机显示12件藏品', reserved_3='', item_name_key='itemName_100133', skill_desc_key='skillDesc_606', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='10', param_16='[6000]', param_17='6', param_18='[1000,1100]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_700 = SkillExportRow(skill_id='700', name_zh='明镜之眼', desc_zh='显示所有藏品的品质', reserved_3='', item_name_key='itemName_100134', skill_desc_key='skillDesc_700', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='6', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_701 = SkillExportRow(skill_id='701', name_zh='宝光双鉴', desc_zh='随机显示2件藏品的品质', reserved_3='', item_name_key='itemName_100135', skill_desc_key='skillDesc_701', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='1', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_702 = SkillExportRow(skill_id='702', name_zh='宝光四鉴', desc_zh='随机显示4件藏品的品质', reserved_3='', item_name_key='itemName_100136', skill_desc_key='skillDesc_702', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='4', param_16='[7000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_703 = SkillExportRow(skill_id='703', name_zh='宝光六鉴', desc_zh='随机显示6件藏品的品质', reserved_3='', item_name_key='itemName_100137', skill_desc_key='skillDesc_703', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='6', param_16='[7000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_704 = SkillExportRow(skill_id='704', name_zh='宝光八鉴', desc_zh='随机显示8件藏品的品质', reserved_3='', item_name_key='itemName_100138', skill_desc_key='skillDesc_704', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='8', param_16='[7000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_705 = SkillExportRow(skill_id='705', name_zh='宝光十鉴', desc_zh='随机显示10件藏品的品质', reserved_3='', item_name_key='itemName_100139', skill_desc_key='skillDesc_705', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='10', param_16='[7000]', param_17='5', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_706 = SkillExportRow(skill_id='706', name_zh='华丽宝光', desc_zh='随机显示15件藏品的品质', reserved_3='', item_name_key='itemName_100140', skill_desc_key='skillDesc_706', reserved_6='', param_07='2', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='15', param_16='[7000]', param_17='6', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_801 = SkillExportRow(skill_id='801', name_zh='【能源交通】检定', desc_zh='显示能源交通的藏品的轮廓和品质', reserved_3='', item_name_key='itemName_100174', skill_desc_key='skillDesc_801', reserved_6='', param_07='2', param_08='1', param_09='[108]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2001 = SkillExportRow(skill_id='2001', name_zh='【家具物品】鉴影', desc_zh='显示家具物品的藏品的轮廓', reserved_3='', item_name_key='itemName_100151', skill_desc_key='skillDesc_2001', reserved_6='', param_07='2', param_08='1', param_09='[101]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2002 = SkillExportRow(skill_id='2002', name_zh='【医疗药品】鉴影', desc_zh='显示医疗药品的藏品的轮廓', reserved_3='', item_name_key='itemName_100152', skill_desc_key='skillDesc_2002', reserved_6='', param_07='2', param_08='1', param_09='[102]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2003 = SkillExportRow(skill_id='2003', name_zh='【时尚潮流】鉴影', desc_zh='显示时尚潮流的藏品的轮廓', reserved_3='', item_name_key='itemName_100153', skill_desc_key='skillDesc_2003', reserved_6='', param_07='2', param_08='1', param_09='[103]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2004 = SkillExportRow(skill_id='2004', name_zh='【兵装军火】鉴影', desc_zh='显示兵装军火的藏品的轮廓', reserved_3='', item_name_key='itemName_100154', skill_desc_key='skillDesc_2004', reserved_6='', param_07='2', param_08='1', param_09='[104]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2005 = SkillExportRow(skill_id='2005', name_zh='【珠宝矿藏】鉴影', desc_zh='显示珠宝矿藏的藏品的轮廓', reserved_3='', item_name_key='itemName_100155', skill_desc_key='skillDesc_2005', reserved_6='', param_07='2', param_08='1', param_09='[105]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2006 = SkillExportRow(skill_id='2006', name_zh='【文物古董】鉴影', desc_zh='显示文物古董的藏品的轮廓', reserved_3='', item_name_key='itemName_100156', skill_desc_key='skillDesc_2006', reserved_6='', param_07='2', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2007 = SkillExportRow(skill_id='2007', name_zh='【数码娱乐】鉴影', desc_zh='显示数码娱乐的藏品的轮廓', reserved_3='', item_name_key='itemName_100157', skill_desc_key='skillDesc_2007', reserved_6='', param_07='2', param_08='1', param_09='[107]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2008 = SkillExportRow(skill_id='2008', name_zh='【能源交通】鉴影', desc_zh='显示能源交通的藏品的轮廓', reserved_3='', item_name_key='itemName_100158', skill_desc_key='skillDesc_2008', reserved_6='', param_07='2', param_08='1', param_09='[108]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2009 = SkillExportRow(skill_id='2009', name_zh='【食饮珍馐】鉴影', desc_zh='显示食饮珍馐的藏品的轮廓', reserved_3='', item_name_key='itemName_100159', skill_desc_key='skillDesc_2009', reserved_6='', param_07='2', param_08='1', param_09='[109]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_2010 = SkillExportRow(skill_id='2010', name_zh='【书画古籍】鉴影', desc_zh='显示书画古籍的藏品的轮廓', reserved_3='', item_name_key='itemName_100160', skill_desc_key='skillDesc_2010', reserved_6='', param_07='2', param_08='1', param_09='[110]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='3', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10000 = SkillExportRow(skill_id='10000', name_zh='至宝寻踪', desc_zh='显示随机1个最高品质藏品的轮廓', reserved_3='', item_name_key='itemName_100161', skill_desc_key='skillDesc_10000', reserved_6='', param_07='2', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[1000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10001 = SkillExportRow(skill_id='10001', name_zh='至宝体量', desc_zh='显示随机1个最高品质藏品的格子数量', reserved_3='', item_name_key='itemName_100162', skill_desc_key='skillDesc_10001', reserved_6='', param_07='2', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[11000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10002 = SkillExportRow(skill_id='10002', name_zh='至宝估价', desc_zh='显示随机1个最高品质藏品的价值', reserved_3='', item_name_key='itemName_100163', skill_desc_key='skillDesc_10002', reserved_6='', param_07='2', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[5000]', param_17='4', param_18='[1100,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10003 = SkillExportRow(skill_id='10003', name_zh='至宝抽样', desc_zh='显示随机1个最高品质的藏品', reserved_3='', item_name_key='itemName_100164', skill_desc_key='skillDesc_10003', reserved_6='', param_07='2', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='5', param_18='[1100,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10010 = SkillExportRow(skill_id='10010', name_zh='巨物标识', desc_zh='显示随机1个格子占用最多藏品的轮廓', reserved_3='', item_name_key='itemName_100165', skill_desc_key='skillDesc_10010', reserved_6='', param_07='2', param_08='6', param_09='[0,0,2,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[1000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10011 = SkillExportRow(skill_id='10011', name_zh='巨物鉴定', desc_zh='显示随机1个格子占用最多藏品的品质', reserved_3='', item_name_key='itemName_100166', skill_desc_key='skillDesc_10011', reserved_6='', param_07='2', param_08='6', param_09='[0,0,2,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[7000]', param_17='2', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10012 = SkillExportRow(skill_id='10012', name_zh='巨物估价', desc_zh='显示随机1个格子占用最多藏品的价值', reserved_3='', item_name_key='itemName_100167', skill_desc_key='skillDesc_10012', reserved_6='', param_07='2', param_08='6', param_09='[0,0,2,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[5000]', param_17='3', param_18='[1100,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10013 = SkillExportRow(skill_id='10013', name_zh='巨物抽样', desc_zh='显示随机1个格子占用最多的藏品', reserved_3='', item_name_key='itemName_100168', skill_desc_key='skillDesc_10013', reserved_6='', param_07='2', param_08='6', param_09='[0,0,2,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='3', param_18='[1100,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10014 = SkillExportRow(skill_id='10014', name_zh='单格均价', desc_zh='占位1格藏品的平均价值为{0}', reserved_3='', item_name_key='itemName_100169', skill_desc_key='', reserved_6='skillDesc_10014', param_07='2', param_08='7', param_09='[1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10015 = SkillExportRow(skill_id='10015', name_zh='两格均价', desc_zh='占位2格藏品的平均价值为{0}', reserved_3='', item_name_key='itemName_100170', skill_desc_key='', reserved_6='skillDesc_10015', param_07='2', param_08='7', param_09='[2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10016 = SkillExportRow(skill_id='10016', name_zh='三格均价', desc_zh='占位3格藏品的平均价值为{0}', reserved_3='', item_name_key='itemName_100171', skill_desc_key='', reserved_6='skillDesc_10016', param_07='2', param_08='7', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10017 = SkillExportRow(skill_id='10017', name_zh='四格均价', desc_zh='占位4格藏品的平均价值为{0}', reserved_3='', item_name_key='itemName_100172', skill_desc_key='', reserved_6='skillDesc_10017', param_07='2', param_08='7', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10018 = SkillExportRow(skill_id='10018', name_zh='六格均价', desc_zh='占位6格藏品的平均价值为{0}', reserved_3='', item_name_key='itemName_100173', skill_desc_key='', reserved_6='skillDesc_10018', param_07='2', param_08='7', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='4', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100101 = SkillExportRow(skill_id='100101', name_zh='法蒂玛', desc_zh='拍卖开始时，显示1件最高价值的文物古董类藏品的品质和轮廓', reserved_3='', item_name_key='hero_skill_101', skill_desc_key='skillDesc_100101', reserved_6='', param_07='0', param_08='6', param_09='[1,106,3,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001011 = SkillExportRow(skill_id='1001011', name_zh='法蒂玛', desc_zh='随机显示 3 件轮廓未知的文玩古董类藏品的轮廓', reserved_3='', item_name_key='hero_skill_101', skill_desc_key='skillDesc_1001011', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001012 = SkillExportRow(skill_id='1001012', name_zh='法蒂玛', desc_zh='随机显示 3 件品质未知的文玩古董类藏品的品质', reserved_3='', item_name_key='hero_skill_101', skill_desc_key='skillDesc_1001012', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001013 = SkillExportRow(skill_id='1001013', name_zh='法蒂玛', desc_zh='随机显示 3 件轮廓未知的文玩古董类藏品的轮廓', reserved_3='', item_name_key='hero_skill_101', skill_desc_key='skillDesc_1001011', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001014 = SkillExportRow(skill_id='1001014', name_zh='法蒂玛', desc_zh='随机显示 3 件品质未知的文玩古董类藏品的品质', reserved_3='', item_name_key='hero_skill_101', skill_desc_key='skillDesc_1001012', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100102 = SkillExportRow(skill_id='100102', name_zh='陈美', desc_zh='拍卖开始时，显示所有珠宝矿藏藏品的品质和轮廓', reserved_3='', item_name_key='hero_skill_102', skill_desc_key='skillDesc_100102', reserved_6='', param_07='0', param_08='1', param_09='[105]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001031 = SkillExportRow(skill_id='1001031', name_zh='艾莎', desc_zh='显示所有蓝色品质道具的轮廓和品质', reserved_3='', item_name_key='hero_skill_103', skill_desc_key='skillDesc_1001031', reserved_6='', param_07='0', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001032 = SkillExportRow(skill_id='1001032', name_zh='艾莎', desc_zh='显示所有绿色品质道具的轮廓和品质', reserved_3='', item_name_key='hero_skill_103', skill_desc_key='skillDesc_1001032', reserved_6='', param_07='0', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001033 = SkillExportRow(skill_id='1001033', name_zh='艾莎', desc_zh='显示所有白色品质道具的轮廓和品质', reserved_3='', item_name_key='hero_skill_103', skill_desc_key='skillDesc_1001033', reserved_6='', param_07='0', param_08='2', param_09='[2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001034 = SkillExportRow(skill_id='1001034', name_zh='艾莎', desc_zh='显示所有白色品质道具的轮廓和品质', reserved_3='', item_name_key='hero_skill_103', skill_desc_key='skillDesc_1001034', reserved_6='', param_07='0', param_08='2', param_09='[1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001041 = SkillExportRow(skill_id='1001041', name_zh='加布里埃拉', desc_zh='随机显示2个信息完全未知藏品的轮廓和品质。', reserved_3='', item_name_key='hero_skill_104', skill_desc_key='skillDesc_1001041', reserved_6='', param_07='0', param_08='10', param_09='[2,2,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001042 = SkillExportRow(skill_id='1001042', name_zh='加布里埃拉', desc_zh='随机显示2个信息完全未知藏品的轮廓和品质。', reserved_3='', item_name_key='hero_skill_104', skill_desc_key='skillDesc_1001041', reserved_6='', param_07='0', param_08='10', param_09='[2,2,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001043 = SkillExportRow(skill_id='1001043', name_zh='加布里埃拉', desc_zh='随机显示2个信息完全未知藏品的轮廓和品质。', reserved_3='', item_name_key='hero_skill_104', skill_desc_key='skillDesc_1001041', reserved_6='', param_07='0', param_08='10', param_09='[2,2,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001044 = SkillExportRow(skill_id='1001044', name_zh='加布里埃拉', desc_zh='随机显示2个信息完全未知藏品的轮廓和品质。', reserved_3='', item_name_key='hero_skill_104', skill_desc_key='skillDesc_1001041', reserved_6='', param_07='0', param_08='10', param_09='[2,2,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001045 = SkillExportRow(skill_id='1001045', name_zh='加布里埃拉', desc_zh='随机显示2个信息完全未知藏品的轮廓和品质。', reserved_3='', item_name_key='hero_skill_104', skill_desc_key='skillDesc_1001041', reserved_6='', param_07='0', param_08='10', param_09='[2,2,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100105 = SkillExportRow(skill_id='100105', name_zh='塔蒂安娜', desc_zh='拍卖开始时，显示所有时尚潮流类藏品的品质和轮廓', reserved_3='', item_name_key='hero_skill_105', skill_desc_key='skillDesc_100105', reserved_6='', param_07='0', param_08='1', param_09='[103]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100106 = SkillExportRow(skill_id='100106', name_zh='娜奥米', desc_zh='所有时尚潮流与数码电子类藏品金色和红色品质数量之和是{0}', reserved_3='', item_name_key='hero_skill_106', skill_desc_key='', reserved_6='skillDesc_100106', param_07='0', param_08='1', param_09='[103,107]', param_10='2', param_11='[5,6]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001061 = SkillExportRow(skill_id='1001061', name_zh='娜奥米', desc_zh='显示所有时尚潮流与数码电子类藏品的轮廓', reserved_3='100106', item_name_key='hero_skill_107', skill_desc_key='skillDesc_1001061', reserved_6='', param_07='0', param_08='1', param_09='[103,107]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100107 = SkillExportRow(skill_id='100107', name_zh='索菲', desc_zh='拍卖开始时，随机显示5件藏品的品质', reserved_3='', item_name_key='hero_skill_107', skill_desc_key='skillDesc_100107', reserved_6='', param_07='0', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='5', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001071 = SkillExportRow(skill_id='1001071', name_zh='索菲', desc_zh='随机显示2件未知品质藏品的品质', reserved_3='', item_name_key='hero_skill_107', skill_desc_key='skillDesc_1001071', reserved_6='', param_07='0', param_08='10', param_09='[0,2,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001072 = SkillExportRow(skill_id='1001072', name_zh='索菲', desc_zh='随机显示2件未知品质藏品的品质', reserved_3='', item_name_key='hero_skill_107', skill_desc_key='skillDesc_1001071', reserved_6='', param_07='0', param_08='10', param_09='[0,2,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001073 = SkillExportRow(skill_id='1001073', name_zh='索菲', desc_zh='随机显示2件未知品质藏品的品质', reserved_3='', item_name_key='hero_skill_107', skill_desc_key='skillDesc_1001071', reserved_6='', param_07='0', param_08='10', param_09='[0,2,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001074 = SkillExportRow(skill_id='1001074', name_zh='索菲', desc_zh='随机显示2件未知品质藏品的品质', reserved_3='', item_name_key='hero_skill_107', skill_desc_key='skillDesc_1001071', reserved_6='', param_07='0', param_08='10', param_09='[0,2,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100108 = SkillExportRow(skill_id='100108', name_zh='玛丽亚', desc_zh='本次竞拍白色、绿色、蓝色品质的藏品的总价值为{0}', reserved_3='', item_name_key='hero_skill_108', skill_desc_key='', reserved_6='skillDesc_100108', param_07='0', param_08='2', param_09='[1,2,3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10010801 = SkillExportRow(skill_id='10010801', name_zh='玛丽亚', desc_zh='拍卖开始时，显示白色、绿色品质藏品的总价值和品质', reserved_3='100108', item_name_key='hero_skill_108', skill_desc_key='skillDesc_10010801', reserved_6='', param_07='0', param_08='2', param_09='[1,2,3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100109 = SkillExportRow(skill_id='100109', name_zh='海琳娜', desc_zh='拍卖开始时，显示所有医疗药品类藏品的品质', reserved_3='', item_name_key='hero_skill_109', skill_desc_key='skillDesc_100109', reserved_6='', param_07='0', param_08='1', param_09='[102]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001091 = SkillExportRow(skill_id='1001091', name_zh='海琳娜', desc_zh='显示2个轮廓未知的医疗类藏品的轮廓', reserved_3='', item_name_key='hero_skill_109', skill_desc_key='skillDesc_1001091', reserved_6='', param_07='0', param_08='1', param_09='[102]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001092 = SkillExportRow(skill_id='1001092', name_zh='海琳娜', desc_zh='显示2个轮廓未知的医疗类藏品的轮廓', reserved_3='', item_name_key='hero_skill_109', skill_desc_key='skillDesc_1001091', reserved_6='', param_07='0', param_08='1', param_09='[102]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001093 = SkillExportRow(skill_id='1001093', name_zh='海琳娜', desc_zh='显示2个轮廓未知的医疗类藏品的轮廓', reserved_3='', item_name_key='hero_skill_109', skill_desc_key='skillDesc_1001091', reserved_6='', param_07='0', param_08='1', param_09='[102]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001094 = SkillExportRow(skill_id='1001094', name_zh='海琳娜', desc_zh='显示2个轮廓未知的医疗类藏品的轮廓', reserved_3='', item_name_key='hero_skill_109', skill_desc_key='skillDesc_1001091', reserved_6='', param_07='0', param_08='1', param_09='[102]', param_10='10', param_11='[2,0,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100110 = SkillExportRow(skill_id='100110', name_zh='伊莎贝拉', desc_zh='显示本场竞品质最高的1件藏品', reserved_3='', item_name_key='hero_skill_110', skill_desc_key='skillDesc_100110', reserved_6='', param_07='0', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1001101 = SkillExportRow(skill_id='1001101', name_zh='伊莎贝拉', desc_zh='显示4个珠宝矿藏的轮廓', reserved_3='100110', item_name_key='hero_skill_110', skill_desc_key='skillDesc_1001101', reserved_6='', param_07='0', param_08='1', param_09='[105]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='4', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100201 = SkillExportRow(skill_id='100201', name_zh='乔治', desc_zh='拍卖开始时，显示所有武器装备类藏品的品质和轮廓', reserved_3='', item_name_key='hero_skill_201', skill_desc_key='skillDesc_100201', reserved_6='', param_07='0', param_08='1', param_09='[104]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100202 = SkillExportRow(skill_id='100202', name_zh='卡洛斯', desc_zh='拍卖开始时，显示所有家居日用与数码电子类藏品的轮廓', reserved_3='', item_name_key='hero_skill_202', skill_desc_key='skillDesc_100202', reserved_6='', param_07='0', param_08='1', param_09='[101,107]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002021 = SkillExportRow(skill_id='1002021', name_zh='卡洛斯', desc_zh='随机显示 2 件品质未知的家居日用或数码电子类藏品的品质。', reserved_3='', item_name_key='hero_skill_202', skill_desc_key='skillDesc_1002021', reserved_6='', param_07='0', param_08='1', param_09='[101,107]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002022 = SkillExportRow(skill_id='1002022', name_zh='卡洛斯', desc_zh='随机显示 2 件品质未知的家居日用或数码电子类藏品的品质。', reserved_3='', item_name_key='hero_skill_202', skill_desc_key='skillDesc_1002021', reserved_6='', param_07='0', param_08='1', param_09='[101,107]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002023 = SkillExportRow(skill_id='1002023', name_zh='卡洛斯', desc_zh='随机显示 2 件品质未知的家居日用或数码电子类藏品的品质。', reserved_3='', item_name_key='hero_skill_202', skill_desc_key='skillDesc_1002021', reserved_6='', param_07='0', param_08='1', param_09='[101,107]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002024 = SkillExportRow(skill_id='1002024', name_zh='卡洛斯', desc_zh='随机显示 2 件品质未知的家居日用或数码电子类藏品的品质。', reserved_3='', item_name_key='hero_skill_202', skill_desc_key='skillDesc_1002021', reserved_6='', param_07='0', param_08='1', param_09='[101,107]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100203 = SkillExportRow(skill_id='100203', name_zh='莱昂纳德', desc_zh='拍卖开始时，显示所有饮食烹饪类藏品品质', reserved_3='', item_name_key='hero_skill_203', skill_desc_key='skillDesc_100203', reserved_6='', param_07='0', param_08='1', param_09='[109]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10002031 = SkillExportRow(skill_id='10002031', name_zh='莱昂纳德', desc_zh='拍卖开始时，显示2个文物古董的品质', reserved_3='100203', item_name_key='hero_skill_203', skill_desc_key='skillDesc_10002031', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100204 = SkillExportRow(skill_id='100204', name_zh='艾哈迈德', desc_zh='本次竞拍的总藏品数量为{0}件', reserved_3='', item_name_key='hero_skill_204', skill_desc_key='', reserved_6='skillDesc_100204', param_07='0', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002041 = SkillExportRow(skill_id='1002041', name_zh='艾哈迈德', desc_zh='本次竞拍橙色品质藏品平均格数约为{0}格', reserved_3='', item_name_key='hero_skill_204', skill_desc_key='', reserved_6='skillDesc_1002041', param_07='0', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002042 = SkillExportRow(skill_id='1002042', name_zh='艾哈迈德', desc_zh='本次竞拍紫色品质藏品平均格数约为{0}格', reserved_3='', item_name_key='hero_skill_204', skill_desc_key='', reserved_6='skillDesc_1002042', param_07='0', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002043 = SkillExportRow(skill_id='1002043', name_zh='艾哈迈德', desc_zh='本次竞拍蓝色色品质藏品平均格数约为{0}格', reserved_3='', item_name_key='hero_skill_204', skill_desc_key='', reserved_6='skillDesc_1002043', param_07='0', param_08='2', param_09='[3]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002044 = SkillExportRow(skill_id='1002044', name_zh='艾哈迈德', desc_zh='本次竞拍白色和绿色品质藏品数量为{0}件', reserved_3='', item_name_key='hero_skill_204', skill_desc_key='', reserved_6='skillDesc_1002044', param_07='0', param_08='2', param_09='[1,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100205 = SkillExportRow(skill_id='100205', name_zh='伊万', desc_zh='拍卖开始时，显示所有武器装备、能源交通类藏品的轮廓', reserved_3='', item_name_key='hero_skill_205', skill_desc_key='skillDesc_100205', reserved_6='', param_07='0', param_08='1', param_09='[104,108]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100206 = SkillExportRow(skill_id='100206', name_zh='武田宏志', desc_zh='本次竞拍的书画古籍类藏品数量为{0}件', reserved_3='', item_name_key='hero_skill_206', skill_desc_key='', reserved_6='skillDesc_100206', param_07='0', param_08='1', param_09='[110]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002061 = SkillExportRow(skill_id='1002061', name_zh='武田宏志', desc_zh='显示书画古籍类藏品的轮廓', reserved_3='100206', item_name_key='hero_skill_206', skill_desc_key='skillDesc_1002061', reserved_6='', param_07='0', param_08='1', param_09='[110]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002062 = SkillExportRow(skill_id='1002062', name_zh='武田宏志', desc_zh='回合开始时，随机显示品质未知2件书画古籍类藏品的品质', reserved_3='', item_name_key='hero_skill_206', skill_desc_key='skillDesc_1002062', reserved_6='', param_07='0', param_08='1', param_09='[110]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002063 = SkillExportRow(skill_id='1002063', name_zh='武田宏志', desc_zh='回合开始时，随机显示品质未知2件书画古籍类藏品的品质', reserved_3='', item_name_key='hero_skill_206', skill_desc_key='skillDesc_1002062', reserved_6='', param_07='0', param_08='1', param_09='[110]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002064 = SkillExportRow(skill_id='1002064', name_zh='武田宏志', desc_zh='回合开始时，随机显示品质未知2件书画古籍类藏品的品质', reserved_3='', item_name_key='hero_skill_206', skill_desc_key='skillDesc_1002062', reserved_6='', param_07='0', param_08='1', param_09='[110]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002065 = SkillExportRow(skill_id='1002065', name_zh='武田宏志', desc_zh='回合开始时，随机显示品质未知2件书画古籍类藏品的品质', reserved_3='', item_name_key='hero_skill_206', skill_desc_key='skillDesc_1002062', reserved_6='', param_07='0', param_08='1', param_09='[110]', param_10='10', param_11='[0,2,0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100207 = SkillExportRow(skill_id='100207', name_zh='吴起灵', desc_zh='看大局：本次竞拍共有文玩古董类藏品{0}件', reserved_3='', item_name_key='hero_skill_207', skill_desc_key='', reserved_6='skillDesc_100207', param_07='0', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10002071 = SkillExportRow(skill_id='10002071', name_zh='吴起灵', desc_zh='辨细节：显示所有文玩古董类藏品的轮廓', reserved_3='', item_name_key='hero_skill_207', skill_desc_key='skillDesc_10002071', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10002072 = SkillExportRow(skill_id='10002072', name_zh='吴起灵', desc_zh='试筋骨：显示所有文玩古董类藏品的品质', reserved_3='', item_name_key='hero_skill_207', skill_desc_key='skillDesc_10002072', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_10002073 = SkillExportRow(skill_id='10002073', name_zh='吴起灵', desc_zh='定灵犀：随机显示1/3文玩古董类藏品完整信息', reserved_3='', item_name_key='hero_skill_207', skill_desc_key='skillDesc_10002073', reserved_6='', param_07='0', param_08='1', param_09='[106]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='2', param_15='3333', param_16='[6000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002081 = SkillExportRow(skill_id='1002081', name_zh='伊森', desc_zh='随机显示5种类型藏品各自的轮廓', reserved_3='', item_name_key='hero_skill_208', skill_desc_key='skillDesc_1002081', reserved_6='', param_07='0', param_08='4', param_09='[5,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002082 = SkillExportRow(skill_id='1002082', name_zh='伊森', desc_zh='显示所有已知品质的藏品各自的轮廓', reserved_3='', item_name_key='hero_skill_208', skill_desc_key='skillDesc_100208', reserved_6='', param_07='0', param_08='10', param_09='[0,1,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002083 = SkillExportRow(skill_id='1002083', name_zh='伊森', desc_zh='显示所有已知品质的藏品各自的轮廓', reserved_3='', item_name_key='hero_skill_208', skill_desc_key='skillDesc_100208', reserved_6='', param_07='0', param_08='10', param_09='[0,1,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002084 = SkillExportRow(skill_id='1002084', name_zh='伊森', desc_zh='显示所有已知品质的藏品各自的轮廓', reserved_3='', item_name_key='hero_skill_208', skill_desc_key='skillDesc_100208', reserved_6='', param_07='0', param_08='10', param_09='[0,1,0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_1002085 = SkillExportRow(skill_id='1002085', name_zh='伊森', desc_zh='显示所有藏品轮廓的轮廓', reserved_3='', item_name_key='hero_skill_208', skill_desc_key='skillDesc_1002085', reserved_6='', param_07='0', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100209 = SkillExportRow(skill_id='100209', name_zh='维克托', desc_zh='本次竞拍共有品质紫色、金色、红藏品{0}件', reserved_3='', item_name_key='hero_skill_209', skill_desc_key='', reserved_6='skillDesc_100209', param_07='0', param_08='2', param_09='[4,5,6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_100301 = SkillExportRow(skill_id='100301', name_zh='拉文', desc_zh='当拍卖到第五回合开始时，显示所有藏品的品质', reserved_3='', item_name_key='hero_skill_301', skill_desc_key='skillDesc_100301', reserved_6='', param_07='0', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200001 = SkillExportRow(skill_id='200001', name_zh='竞拍信息', desc_zh='显示所有紫色品质藏品的轮廓', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200001', reserved_6='', param_07='1', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200002 = SkillExportRow(skill_id='200002', name_zh='竞拍信息', desc_zh='显示所有金色品质藏品的轮廓', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200002', reserved_6='', param_07='1', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200003 = SkillExportRow(skill_id='200003', name_zh='竞拍信息', desc_zh='显示所有红色品质藏品的轮廓', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200003', reserved_6='', param_07='1', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000,7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200004 = SkillExportRow(skill_id='200004', name_zh='竞拍信息', desc_zh='显示所有藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200004', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200005 = SkillExportRow(skill_id='200005', name_zh='竞拍信息', desc_zh='本场拍卖，有2种藏品类型占位每格的均价是{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200005', param_07='1', param_08='4', param_09='[2,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[9000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200006 = SkillExportRow(skill_id='200006', name_zh='竞拍信息', desc_zh='本场拍卖，有4种藏品类型占位每格的均价是{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200006', param_07='1', param_08='4', param_09='[4,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[9000]', param_17='', param_18='[1100,1300]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200007 = SkillExportRow(skill_id='200007', name_zh='竞拍信息', desc_zh='本场拍卖，有6种藏品类型占位每格的均价是{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200007', param_07='1', param_08='4', param_09='[6,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[9000]', param_17='', param_18='[800,1000]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200008 = SkillExportRow(skill_id='200008', name_zh='竞拍信息', desc_zh='本场拍卖，所有藏品占位每格的均价是{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200008', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[9000]', param_17='', param_18='[800,850]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200009 = SkillExportRow(skill_id='200009', name_zh='竞拍信息', desc_zh='所有藏品总占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200009', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200010 = SkillExportRow(skill_id='200010', name_zh='竞拍信息', desc_zh='紫色品质总占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200010', param_07='1', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200011 = SkillExportRow(skill_id='200011', name_zh='竞拍信息', desc_zh='金色品质总占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200011', param_07='1', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200012 = SkillExportRow(skill_id='200012', name_zh='竞拍信息', desc_zh='红色品质总占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200012', param_07='1', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[2000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200013 = SkillExportRow(skill_id='200013', name_zh='竞拍信息', desc_zh='紫色品质藏品平均占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200013', param_07='1', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200014 = SkillExportRow(skill_id='200014', name_zh='竞拍信息', desc_zh='每件藏品平均占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200014', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200015 = SkillExportRow(skill_id='200015', name_zh='竞拍信息', desc_zh='金色品质藏品平均占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200015', param_07='1', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200016 = SkillExportRow(skill_id='200016', name_zh='竞拍信息', desc_zh='红色品质藏品平均占用的格子数量为{0}格', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200016', param_07='1', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[3000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200017 = SkillExportRow(skill_id='200017', name_zh='竞拍信息', desc_zh='本场拍卖共有道具{0}件', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200017', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200018 = SkillExportRow(skill_id='200018', name_zh='竞拍信息', desc_zh='本场拍卖共有紫色品质道具{0}件', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200018', param_07='1', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200019 = SkillExportRow(skill_id='200019', name_zh='竞拍信息', desc_zh='本场拍卖共有金色品质道具{0}件', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200019', param_07='1', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200020 = SkillExportRow(skill_id='200020', name_zh='竞拍信息', desc_zh='本场拍卖共有红色品质道具{0}件', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200020', param_07='1', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200021 = SkillExportRow(skill_id='200021', name_zh='竞拍信息', desc_zh='随机显示2件藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200021', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='2', param_16='[6000]', param_17='', param_18='[1500,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200022 = SkillExportRow(skill_id='200022', name_zh='竞拍信息', desc_zh='随机显示4件藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200022', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='4', param_16='[6000]', param_17='', param_18='[1400,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200023 = SkillExportRow(skill_id='200023', name_zh='竞拍信息', desc_zh='随机显示6件藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200023', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='6', param_16='[6000]', param_17='', param_18='[1300,1400]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200024 = SkillExportRow(skill_id='200024', name_zh='竞拍信息', desc_zh='随机显示8件藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200024', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='8', param_16='[6000]', param_17='', param_18='[1200,1300]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200025 = SkillExportRow(skill_id='200025', name_zh='竞拍信息', desc_zh='随机显示12件藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200025', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='12', param_16='[6000]', param_17='', param_18='[1100,1200]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200026 = SkillExportRow(skill_id='200026', name_zh='竞拍信息', desc_zh='随机显示3件藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200026', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200027 = SkillExportRow(skill_id='200027', name_zh='竞拍信息', desc_zh='随机显示6件藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200027', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='6', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200028 = SkillExportRow(skill_id='200028', name_zh='竞拍信息', desc_zh='随机显示9件藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200028', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='9', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200029 = SkillExportRow(skill_id='200029', name_zh='竞拍信息', desc_zh='随机显示12件藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200029', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='12', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200030 = SkillExportRow(skill_id='200030', name_zh='竞拍信息', desc_zh='显示所有藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200030', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200031 = SkillExportRow(skill_id='200031', name_zh='竞拍信息', desc_zh='随机选择的3件藏品平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200031', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='3', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200032 = SkillExportRow(skill_id='200032', name_zh='竞拍信息', desc_zh='随机选择的6件藏品平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200032', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='6', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200033 = SkillExportRow(skill_id='200033', name_zh='竞拍信息', desc_zh='随机选择的9件藏品平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200033', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='9', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200034 = SkillExportRow(skill_id='200034', name_zh='竞拍信息', desc_zh='随机选择的12件藏品平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200034', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='12', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200035 = SkillExportRow(skill_id='200035', name_zh='竞拍信息', desc_zh='所有藏品的平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200035', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200036 = SkillExportRow(skill_id='200036', name_zh='竞拍信息', desc_zh='所有紫色品质藏品的平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200036', param_07='1', param_08='2', param_09='[4]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='', param_18='[1500,1600]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200037 = SkillExportRow(skill_id='200037', name_zh='竞拍信息', desc_zh='所有金色品质藏品的平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200037', param_07='1', param_08='2', param_09='[5]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='', param_18='[1400,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200038 = SkillExportRow(skill_id='200038', name_zh='竞拍信息', desc_zh='所有红色品质藏品的平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200038', param_07='1', param_08='2', param_09='[6]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='', param_18='[1000,1100]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200039 = SkillExportRow(skill_id='200039', name_zh='竞拍信息', desc_zh='显示所有道具的轮廓', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200039', reserved_6='', param_07='1', param_08='0', param_09='[0]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[1000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200040 = SkillExportRow(skill_id='200040', name_zh='竞拍信息', desc_zh='随机显示2种藏品类型所有藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200040', reserved_6='', param_07='1', param_08='4', param_09='[2,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200041 = SkillExportRow(skill_id='200041', name_zh='竞拍信息', desc_zh='随机显示4种藏品类型所有藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200041', reserved_6='', param_07='1', param_08='4', param_09='[4,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200042 = SkillExportRow(skill_id='200042', name_zh='竞拍信息', desc_zh='随机显示6种藏品类型所有藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200042', reserved_6='', param_07='1', param_08='4', param_09='[6,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200043 = SkillExportRow(skill_id='200043', name_zh='竞拍信息', desc_zh='{1}类藏品的平均价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200043', param_07='1', param_08='4', param_09='[1,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[8000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200044 = SkillExportRow(skill_id='200044', name_zh='竞拍信息', desc_zh='本场拍卖类型{1}藏品总价值为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200044', param_07='1', param_08='4', param_09='[1,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[10000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200045 = SkillExportRow(skill_id='200045', name_zh='竞拍信息', desc_zh='本场拍卖类型{1}藏品总数量为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200045', param_07='1', param_08='4', param_09='[1,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[4000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200046 = SkillExportRow(skill_id='200046', name_zh='竞拍信息', desc_zh='随机显示1种类型藏品的品质', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200046', reserved_6='', param_07='1', param_08='4', param_09='[1,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[7000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200047 = SkillExportRow(skill_id='200047', name_zh='竞拍信息', desc_zh='随机显示1种藏品类型的所有藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200047', reserved_6='', param_07='1', param_08='4', param_09='[1,101,100,102,100,103,100,104,100,105,100,106,100,107,100,108,100,109,100,110,100]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[6000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200048 = SkillExportRow(skill_id='200048', name_zh='竞拍信息', desc_zh='随机显示1件最高品质的藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200048', reserved_6='', param_07='1', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200049 = SkillExportRow(skill_id='200049', name_zh='竞拍信息', desc_zh='显示1件最高价值的藏品', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200049', reserved_6='', param_07='1', param_08='6', param_09='[0,0,3,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200050 = SkillExportRow(skill_id='200050', name_zh='竞拍信息', desc_zh='显示1件占位格数最高的道具', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200050', reserved_6='', param_07='1', param_08='6', param_09='[0,0,2,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[6000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200051 = SkillExportRow(skill_id='200051', name_zh='竞拍信息', desc_zh='显示数量最少藏品类型的所有道具', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='skillDesc_200051', reserved_6='', param_07='1', param_08='6', param_09='[0,0,6,2]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='0', param_16='[6000]', param_17='', param_18='[1100,1500]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')
SKILL_EXP_200052 = SkillExportRow(skill_id='200052', name_zh='竞拍信息', desc_zh='本场竞拍竞拍最高品质为{0}', reserved_3='', item_name_key='skill_Name_Type_20000', skill_desc_key='', reserved_6='skillDesc_200052', param_07='1', param_08='6', param_09='[0,0,1,1]', param_10='0', param_11='[0]', param_12='0', param_13='[0]', param_14='1', param_15='1', param_16='[12000]', param_17='', param_18='[]', param_19='1', param_20='0', nested_21='[[0]]', nested_22='[[0]]', nested_23='[[1,1000,0]]', param_24='0', param_25='0', param_26='0')


def _skill_export_rows_to_dict(*rows: SkillExportRow) -> Dict[int, SkillExportRow]:
    """底层：多行 ``SkillExportRow`` → ``skill_id`` 字典（后者覆盖前者）。"""
    out: Dict[int, SkillExportRow] = {}
    for r in rows:
        out[int(r.skill_id)] = r
    return out


def _skill_export_merge_dict_parts(*parts: Dict[int, SkillExportRow]) -> Dict[int, SkillExportRow]:
    """底层：合并多段子表；``skill_id`` 重复则报错。"""
    out: Dict[int, SkillExportRow] = {}
    for p in parts:
        for k, v in p.items():
            if k in out:
                raise RuntimeError(f"SKILL_EXPORT 合并冲突: skill_id={k} 出现在多个分组中")
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# 地图竞拍信息（param_07=1）：按技能效果拆分子注册表
# ---------------------------------------------------------------------------


def _registry_map_tier_outline_and_quality() -> Dict[int, SkillExportRow]:
    """紫/金/红单档：轮廓 + 品质（``param_16`` 含 1000 与 7000）。

    具体 skill_id：200001, 200002, 200003。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_200001, SKILL_EXP_200002, SKILL_EXP_200003)


def _registry_map_board_mass_reveal_lines() -> Dict[int, SkillExportRow]:
    """全场类揭示：全图品质、全图轮廓等（单技能一条）。

    具体 skill_id：200004, 200030, 200039。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_200004, SKILL_EXP_200039, SKILL_EXP_200030)


def _registry_map_category_mixture_cell_avg_price() -> Dict[int, SkillExportRow]:
    """多类型混合：按类型占位均价线（``param_16`` 含 9000）。

    具体 skill_id：200005, 200006, 200007, 200008。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200005,
        SKILL_EXP_200006,
        SKILL_EXP_200007,
        SKILL_EXP_200008,
    )


def _registry_map_hidden_cell_scan_lines() -> Dict[int, SkillExportRow]:
    """仓储格数：总格与紫/金/红分档（``param_16`` 含 2000）。

    具体 skill_id：200009, 200010, 200011, 200012。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200009,
        SKILL_EXP_200010,
        SKILL_EXP_200011,
        SKILL_EXP_200012,
    )


def _registry_map_avg_cell_scan_lines() -> Dict[int, SkillExportRow]:
    """均格：全场与紫/金/红分档（``param_16`` 含 3000）。

    具体 skill_id：200013, 200014, 200015, 200016。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200013,
        SKILL_EXP_200014,
        SKILL_EXP_200015,
        SKILL_EXP_200016,
    )


def _registry_map_hit_item_count_lines() -> Dict[int, SkillExportRow]:
    """件数清点：全场与紫/金/红分档（``param_16`` 含 4000）。

    具体 skill_id：200017, 200018, 200019, 200020。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200017,
        SKILL_EXP_200018,
        SKILL_EXP_200019,
        SKILL_EXP_200020,
    )


def _registry_map_random_piece_reveal_lines() -> Dict[int, SkillExportRow]:
    """随机揭示实体件数线（``param_16`` 含 6000）。

    具体 skill_id：200021, 200022, 200023, 200024, 200025。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200021,
        SKILL_EXP_200022,
        SKILL_EXP_200023,
        SKILL_EXP_200024,
        SKILL_EXP_200025,
    )


def _registry_map_random_quality_snippet_lines() -> Dict[int, SkillExportRow]:
    """随机揭示品质件数线（``param_16`` 含 7000，不含品类多选块）。

    具体 skill_id：200026, 200027, 200028, 200029。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200026,
        SKILL_EXP_200027,
        SKILL_EXP_200028,
        SKILL_EXP_200029,
    )


def _registry_map_random_hit_avg_price_lines() -> Dict[int, SkillExportRow]:
    """随机命中均价：按命中件数与分档紫/金/红（``param_16`` 含 8000）。

    具体 skill_id：200031, 200032, 200033, 200034, 200035, 200036, 200037, 200038。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200031,
        SKILL_EXP_200032,
        SKILL_EXP_200033,
        SKILL_EXP_200034,
        SKILL_EXP_200035,
        SKILL_EXP_200036,
        SKILL_EXP_200037,
        SKILL_EXP_200038,
    )


def _registry_map_category_random_quality_lines() -> Dict[int, SkillExportRow]:
    """随机 N 类：全图品质揭示（``param_08=4`` + ``param_16`` 7000）。

    具体 skill_id：200040, 200041, 200042。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_200040, SKILL_EXP_200041, SKILL_EXP_200042)


def _registry_map_category_price_count_quality_piece_lines() -> Dict[int, SkillExportRow]:
    """随机单类：均价 / 总价 / 件数 / 品质 / 全显 等竞拍信息行。

    具体 skill_id：200043, 200044, 200045, 200046, 200047。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200043,
        SKILL_EXP_200044,
        SKILL_EXP_200045,
        SKILL_EXP_200046,
        SKILL_EXP_200047,
    )


def _registry_map_oracle_and_board_meta_lines() -> Dict[int, SkillExportRow]:
    """Oracle 类：最高品质/最高价值/最大占位等揭示与最高品质档位文本。

    具体 skill_id：200048, 200049, 200050, 200051, 200052。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200048,
        SKILL_EXP_200049,
        SKILL_EXP_200050,
        SKILL_EXP_200051,
        SKILL_EXP_200052,
    )


def _skill_export_part_map_auction_board() -> Dict[int, SkillExportRow]:
    """地图竞拍信息（param_07=1）：合并各技能效果子组。

    具体 skill_id：200001, 200002, …, 200052（连续 52 条，为各 ``_registry_map_*`` 并集）。
    """
    return _skill_export_merge_dict_parts(
        _registry_map_tier_outline_and_quality(),
        _registry_map_board_mass_reveal_lines(),
        _registry_map_category_mixture_cell_avg_price(),
        _registry_map_hidden_cell_scan_lines(),
        _registry_map_avg_cell_scan_lines(),
        _registry_map_hit_item_count_lines(),
        _registry_map_random_piece_reveal_lines(),
        _registry_map_random_quality_snippet_lines(),
        _registry_map_random_hit_avg_price_lines(),
        _registry_map_category_random_quality_lines(),
        _registry_map_category_price_count_quality_piece_lines(),
        _registry_map_oracle_and_board_meta_lines(),
    )


# ---------------------------------------------------------------------------
# 英雄技能（param_07=0）：按英雄 item_name_key 分组注册
# ---------------------------------------------------------------------------


def _registry_hero_fatima_skills() -> Dict[int, SkillExportRow]:
    """法蒂玛（hero_skill_101）：高价值古董轮廓+品质、随机轮廓/品质线。

    具体 skill_id：100101, 1001011, 1001012, 1001013, 1001014。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100101,
        SKILL_EXP_1001011,
        SKILL_EXP_1001012,
        SKILL_EXP_1001013,
        SKILL_EXP_1001014,
    )


def _registry_hero_carmen_skills() -> Dict[int, SkillExportRow]:
    """陈美（hero_skill_102）：珠宝矿藏类轮廓+品质。

    具体 skill_id：100102。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100102)


def _registry_hero_aisha_skills() -> Dict[int, SkillExportRow]:
    """艾莎（hero_skill_103）：按品质档揭示轮廓+品质。

    具体 skill_id：1001031, 1001032, 1001033, 1001034。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_1001031,
        SKILL_EXP_1001032,
        SKILL_EXP_1001033,
        SKILL_EXP_1001034,
    )


def _registry_hero_gabriela_skills() -> Dict[int, SkillExportRow]:
    """加布里埃拉（hero_skill_104）：随机未知件轮廓+品质。

    具体 skill_id：1001041, 1001042, 1001043, 1001044, 1001045。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_1001041,
        SKILL_EXP_1001042,
        SKILL_EXP_1001043,
        SKILL_EXP_1001044,
        SKILL_EXP_1001045,
    )


def _registry_hero_tatiana_skills() -> Dict[int, SkillExportRow]:
    """塔蒂安娜 / 娜奥米（hero_skill_105/106）：类目揭示与件数统计。

    具体 skill_id：100105, 100106, 1001061。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100105,
        SKILL_EXP_100106,
        SKILL_EXP_1001061,
    )


def _registry_hero_sofia_skills() -> Dict[int, SkillExportRow]:
    """索菲（hero_skill_107）：随机品质揭示。

    具体 skill_id：100107, 1001071, 1001072, 1001073, 1001074。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100107,
        SKILL_EXP_1001071,
        SKILL_EXP_1001072,
        SKILL_EXP_1001073,
        SKILL_EXP_1001074,
    )


def _registry_hero_maria_skills() -> Dict[int, SkillExportRow]:
    """玛丽亚（hero_skill_108）：Q123 总价 ``q123_price_total``（``100108``/``HitItemTotalPrice``）与揭示扫描 ``q123_count``（``10010801``/``HitBoxList``）。

    具体 skill_id：100108, 10010801。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100108, SKILL_EXP_10010801)


def _registry_hero_helena_skills() -> Dict[int, SkillExportRow]:
    """海琳娜（hero_skill_109）：医疗类品质/随机轮廓。

    具体 skill_id：100109, 1001091, 1001092, 1001093, 1001094。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100109,
        SKILL_EXP_1001091,
        SKILL_EXP_1001092,
        SKILL_EXP_1001093,
        SKILL_EXP_1001094,
    )


def _registry_hero_isabella_skills() -> Dict[int, SkillExportRow]:
    """伊莎贝拉（hero_skill_110）：最高品质揭示与珠宝轮廓。

    具体 skill_id：100110, 1001101。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100110, SKILL_EXP_1001101)


def _registry_hero_george_skills() -> Dict[int, SkillExportRow]:
    """乔治（hero_skill_201）：兵装军火类轮廓+品质。

    具体 skill_id：100201。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100201)


def _registry_hero_carlos_skills() -> Dict[int, SkillExportRow]:
    """卡洛斯（hero_skill_202）：家居+数码轮廓与随机品质。

    具体 skill_id：100202, 1002021, 1002022, 1002023, 1002024。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100202,
        SKILL_EXP_1002021,
        SKILL_EXP_1002022,
        SKILL_EXP_1002023,
        SKILL_EXP_1002024,
    )


def _registry_hero_leonard_skills() -> Dict[int, SkillExportRow]:
    """莱昂纳德（hero_skill_203）：食饮品质与文玩古董品质。

    具体 skill_id：100203, 10002031。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100203, SKILL_EXP_10002031)


def _registry_hero_ahmad_skills() -> Dict[int, SkillExportRow]:
    """艾哈迈德（hero_skill_204）：总件数、分档均格/件数。

    具体 skill_id：100204, 1002041, 1002042, 1002043, 1002044。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100204,
        SKILL_EXP_1002041,
        SKILL_EXP_1002042,
        SKILL_EXP_1002043,
        SKILL_EXP_1002044,
    )


def _registry_hero_ivan_skills() -> Dict[int, SkillExportRow]:
    """伊万（hero_skill_205）：多类目轮廓。

    具体 skill_id：100205。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100205)


def _registry_hero_takeshi_skills() -> Dict[int, SkillExportRow]:
    """武田宏志（hero_skill_206）：书画古籍件数/轮廓/随机品质。

    具体 skill_id：100206, 1002061, 1002062, 1002063, 1002064, 1002065。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100206,
        SKILL_EXP_1002061,
        SKILL_EXP_1002062,
        SKILL_EXP_1002063,
        SKILL_EXP_1002064,
        SKILL_EXP_1002065,
    )


def _registry_hero_wu_qiling_skills() -> Dict[int, SkillExportRow]:
    """吴起灵（hero_skill_207）：文玩件数/轮廓/品质/随机全显。

    具体 skill_id：100207, 10002071, 10002072, 10002073。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100207,
        SKILL_EXP_10002071,
        SKILL_EXP_10002072,
        SKILL_EXP_10002073,
    )


def _registry_hero_ethan_skills() -> Dict[int, SkillExportRow]:
    """伊森（hero_skill_208）：多类型轮廓与已知品质轮廓。

    具体 skill_id：1002081, 1002082, 1002083, 1002084, 1002085。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_1002081,
        SKILL_EXP_1002082,
        SKILL_EXP_1002083,
        SKILL_EXP_1002084,
        SKILL_EXP_1002085,
    )


def _registry_hero_viktor_skills() -> Dict[int, SkillExportRow]:
    """维克托（hero_skill_209）：紫/金/红件数统计。

    具体 skill_id：100209。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100209)


def _registry_hero_raven_skills() -> Dict[int, SkillExportRow]:
    """拉文（hero_skill_301）：延时全场品质。

    具体 skill_id：100301。
    """
    return _skill_export_rows_to_dict(SKILL_EXP_100301)


def _skill_export_part_hero_skills() -> Dict[int, SkillExportRow]:
    """英雄携带技能（param_07=0）：合并各英雄子组。

    具体 skill_id（共 63 条，为各 ``_registry_hero_*`` 并集）：
    100101, 1001011, 1001012, 1001013, 1001014, 100102, 1001031, 1001032, 1001033, 1001034,
    1001041, 1001042, 1001043, 1001044, 1001045, 100105, 100106, 1001061, 100107, 1001071,
    1001072, 1001073, 1001074, 100108, 10010801, 100109, 1001091, 1001092, 1001093, 1001094,
    100110, 1001101, 100201, 100202, 1002021, 1002022, 1002023, 1002024, 100203, 10002031,
    100204, 1002041, 1002042, 1002043, 1002044, 100205, 100206, 1002061, 1002062, 1002063,
    1002064, 1002065, 100207, 10002071, 10002072, 10002073, 1002081, 1002082, 1002083,
    1002084, 1002085, 100209, 100301。
    """
    return _skill_export_merge_dict_parts(
        _registry_hero_fatima_skills(),
        _registry_hero_carmen_skills(),
        _registry_hero_aisha_skills(),
        _registry_hero_gabriela_skills(),
        _registry_hero_tatiana_skills(),
        _registry_hero_sofia_skills(),
        _registry_hero_maria_skills(),
        _registry_hero_helena_skills(),
        _registry_hero_isabella_skills(),
        _registry_hero_george_skills(),
        _registry_hero_carlos_skills(),
        _registry_hero_leonard_skills(),
        _registry_hero_ahmad_skills(),
        _registry_hero_ivan_skills(),
        _registry_hero_takeshi_skills(),
        _registry_hero_wu_qiling_skills(),
        _registry_hero_ethan_skills(),
        _registry_hero_viktor_skills(),
        _registry_hero_raven_skills(),
    )


def _skill_export_part_item_hidden_cell_scan() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 仓储格数扫描（param_16 含 2000，不含总价/随机价干扰）。

    解析侧：``TotalHitBoxIndex`` → ``event_stats`` 的 ``*_grid_count``。

    具体 skill_id：200, 201, 202, 203, 204, 205。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_200,
        SKILL_EXP_201,
        SKILL_EXP_202,
        SKILL_EXP_203,
        SKILL_EXP_204,
        SKILL_EXP_205,
    )


def _skill_export_part_item_avg_cell_scan() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 均格评估（param_16 含 3000）。

    解析侧：``AllHitItemAvgBoxIndex`` → ``*_grid_avg``。

    具体 skill_id：300, 301, 302, 303, 304, 305。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_300,
        SKILL_EXP_301,
        SKILL_EXP_302,
        SKILL_EXP_303,
        SKILL_EXP_304,
        SKILL_EXP_305,
    )


def _skill_export_part_item_hit_count_scan() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 件数清点（param_16 含 4000）。

    解析侧：``HitItemIndex`` → ``*_count``。

    具体 skill_id：400, 401, 402, 403, 404, 405。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_400,
        SKILL_EXP_401,
        SKILL_EXP_402,
        SKILL_EXP_403,
        SKILL_EXP_404,
        SKILL_EXP_405,
    )


def _skill_export_part_item_price_total_scan() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 分档总价（param_16 含 10000）。

    解析侧：``HitItemTotalPrice`` → ``*_price_total``。

    具体 skill_id：500, 501, 502, 503, 504, 505。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_500,
        SKILL_EXP_501,
        SKILL_EXP_502,
        SKILL_EXP_503,
        SKILL_EXP_504,
        SKILL_EXP_505,
    )


def _skill_export_part_item_outline_peek_random_count() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 轮廓窥视（仅 1000，param_08≠1 的随机件数轮廓）。

    解析侧：轮廓揭示类事件，与全库/四象等随机轮廓计数相关。

    具体 skill_id：100, 103, 106。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_100,
        SKILL_EXP_103,
        SKILL_EXP_106,
    )


def _skill_export_part_item_random_piece_reveal() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 随机件数揭示实体（param_16 含 6000）。

    解析侧：随机抽检/全知类 ``RevealPiece`` 等日志事件。

    具体 skill_id：600, 601, 602, 603, 604, 605, 606。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_600,
        SKILL_EXP_601,
        SKILL_EXP_602,
        SKILL_EXP_603,
        SKILL_EXP_604,
        SKILL_EXP_605,
        SKILL_EXP_606,
    )


def _skill_export_part_item_quality_reveal() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 品质揭示（param_16 仅含 7000 或与轮廓拆分后的品质线）。

    解析侧：品质扫描、宝光系列等 ``RevealQuality`` 相关统计。

    具体 skill_id：700, 701, 702, 703, 704, 705, 706。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_700,
        SKILL_EXP_701,
        SKILL_EXP_702,
        SKILL_EXP_703,
        SKILL_EXP_704,
        SKILL_EXP_705,
        SKILL_EXP_706,
    )


def _skill_export_part_item_category_outline_and_quality() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 类目轮廓+品质（param_16 同时含 1000 与 7000）。

    解析侧：单类目轮廓与品质同显（如行业检定）。

    具体 skill_id：801。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_801,
    )


def _skill_export_part_item_category_lane_outline() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 类目鉴影轮廓（param_16 为 [1000] 且 param_08=1）。

    解析侧：各品类 ``itemName_100151``…``100160`` 鉴影轮廓技能。

    具体 skill_id：2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_2001,
        SKILL_EXP_2002,
        SKILL_EXP_2003,
        SKILL_EXP_2004,
        SKILL_EXP_2005,
        SKILL_EXP_2006,
        SKILL_EXP_2007,
        SKILL_EXP_2008,
        SKILL_EXP_2009,
        SKILL_EXP_2010,
    )


def _skill_export_part_item_oracle_meter_and_treasure() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 至宝/巨物/占位档随机均价（param_08 为 6 或 7）。

    解析侧：最高品质/最大占位/按格随机均价等 Oracle 类道具效果。

    具体 skill_id：10000, 10001, 10002, 10003, 10010, 10011, 10012, 10013, 10014,
    10015, 10016, 10017, 10018。
    """
    return _skill_export_rows_to_dict(
        SKILL_EXP_10000,
        SKILL_EXP_10001,
        SKILL_EXP_10002,
        SKILL_EXP_10003,
        SKILL_EXP_10010,
        SKILL_EXP_10011,
        SKILL_EXP_10012,
        SKILL_EXP_10013,
        SKILL_EXP_10014,
        SKILL_EXP_10015,
        SKILL_EXP_10016,
        SKILL_EXP_10017,
        SKILL_EXP_10018,
    )


def _skill_export_part_item_tool_fallback() -> Dict[int, SkillExportRow]:
    """
    道具工具 · 未归类行（生成时应为空；若出现需补充 ``_registry_part_key`` 规则）。

    具体 skill_id：无（恒为空表）。
    """
    return {}


def _skill_export_merge_registered_parts() -> Dict[int, SkillExportRow]:
    """合并各分组注册表；键冲突则报错（CSV 不应重复 skill_id）。"""
    return _skill_export_merge_dict_parts(
        _skill_export_part_map_auction_board(),
        _skill_export_part_hero_skills(),
        _skill_export_part_item_hidden_cell_scan(),
        _skill_export_part_item_avg_cell_scan(),
        _skill_export_part_item_hit_count_scan(),
        _skill_export_part_item_price_total_scan(),
        _skill_export_part_item_outline_peek_random_count(),
        _skill_export_part_item_random_piece_reveal(),
        _skill_export_part_item_quality_reveal(),
        _skill_export_part_item_category_outline_and_quality(),
        _skill_export_part_item_category_lane_outline(),
        _skill_export_part_item_oracle_meter_and_treasure(),
        _skill_export_part_item_tool_fallback(),
    )


SKILL_EXPORT_BY_ID: Dict[int, SkillExportRow] = _skill_export_merge_registered_parts()

ALL_SKILL_IDS: tuple[int, ...] = tuple(sorted(SKILL_EXPORT_BY_ID.keys()))


def get_skill_export(skill_id: int) -> SkillExportRow | None:
    """按 skill_id 取行；不存在返回 None。"""
    return SKILL_EXPORT_BY_ID.get(int(skill_id))

