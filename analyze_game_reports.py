#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Match Reports 统计分析脚本
统计230系列地图的数据
"""

import os
import csv
import glob
from collections import defaultdict
from datetime import datetime

# 目标文件夹路径
TARGET_DIR = r"c:\Users\49479\Desktop\竞拍统计\竞拍统计"

def parse_uid(uid):
    """解析UID，返回地图编号和唯一ID"""
    if ':' in uid:
        map_id, unique_id = uid.split(':', 1)
        return map_id, unique_id
    return None, uid

def is_230_series(map_id):
    """判断是否为230系列地图"""
    if map_id and map_id.startswith('230'):
        return True
    return False

def analyze_csv_file(filepath):
    """分析单个CSV文件，返回统计结果"""
    filename = os.path.basename(filepath)

    # 存储统计信息
    match_start_times = set()  # 对局开始时间（去重）
    unique_uids = set()  # 唯一的对局UID
    non_zero_values = []  # 非0的藏品价值
    nico666_rewards = []  # Nico666的收益
    air1314_rewards = []  # AIR1314的收益

    encodings = ['utf-8-sig', 'gbk', 'gb2312', 'utf-8']
    file_opened = False
    rows = []

    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                file_opened = True
                break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if not file_opened:
        return {
            'filename': filename,
            'error': '无法解码文件，尝试了 utf-8/gbk/gb2312 编码'
        }

    try:
        for row in rows:
            uid = row.get('对局UID', '')
            map_id, _ = parse_uid(uid)

            # 只处理230系列地图
            if not is_230_series(map_id):
                continue

            # 记录对局信息
            start_time = row.get('对局开始时间', '')
            if start_time:
                match_start_times.add(start_time)
                unique_uids.add(uid)

            # 藏品价值（非0）
            value_str = row.get('最终藏品价值', '0').strip()
            try:
                value = int(value_str)
                if value > 0:
                    non_zero_values.append(value)
            except ValueError:
                pass

            # 玩家收益统计
            reward_str = row.get('最终收益', '0').strip()
            try:
                reward = int(reward_str)
            except ValueError:
                reward = 0

            player_name = row.get('角色名称', '').strip()
            if player_name == 'Nico666':
                nico666_rewards.append(reward)
            elif player_name == 'AIR1314':
                air1314_rewards.append(reward)

    except Exception as e:
        return {
            'filename': filename,
            'error': str(e)
        }

    # 计算统计数据
    total_matches = len(unique_uids)

    # 非0藏品平均价值
    avg_non_zero_value = sum(non_zero_values) / len(non_zero_values) if non_zero_values else 0

    # Nico666和AIR1314的平均收益（除以总对局数）
    total_nico666 = sum(nico666_rewards) if nico666_rewards else 0
    total_air1314 = sum(air1314_rewards) if air1314_rewards else 0

    # 平均收益 = 总收益 / 总对局数
    avg_nico666_per_match = total_nico666 / total_matches if total_matches > 0 else 0
    avg_air1314_per_match = total_air1314 / total_matches if total_matches > 0 else 0

    # 对局开始时间排序
    sorted_times = sorted(match_start_times)

    return {
        'filename': filename,
        'filepath': filepath,
        'match_times': sorted_times,
        'total_matches': total_matches,
        'non_zero_values_count': len(non_zero_values),
        'avg_non_zero_value': round(avg_non_zero_value, 2),
        'nico666_count': len(nico666_rewards),
        'total_nico666_reward': total_nico666,
        'avg_nico666_per_match': round(avg_nico666_per_match, 2),
        'air1314_count': len(air1314_rewards),
        'total_air1314_reward': total_air1314,
        'avg_air1314_per_match': round(avg_air1314_per_match, 2),
    }

def format_time_range(time_list):
    """格式化时间范围显示"""
    if not time_list:
        return "无数据"
    if len(time_list) == 1:
        return time_list[0]
    return f"{time_list[0]} 至 {time_list[-1]}"

def main():
    # 查找所有CSV文件
    csv_pattern = os.path.join(TARGET_DIR, "game_match_reports_*.csv")
    csv_files = glob.glob(csv_pattern)

    # 排除history文件
    csv_files = [f for f in csv_files if 'history' not in os.path.basename(f).lower()]

    # 按文件名排序
    csv_files.sort()

    print(f"找到 {len(csv_files)} 个CSV文件")
    print("=" * 100)

    results = []
    for filepath in csv_files:
        result = analyze_csv_file(filepath)
        results.append(result)

    # 打印报表
    print("\n" + "=" * 100)
    print("230系列地图 对局统计报表")
    print("=" * 100)

    for idx, r in enumerate(results, 1):
        if 'error' in r:
            print(f"\n【{idx}】文件: {r['filename']}")
            print(f"    错误: {r['error']}")
            continue

        print(f"\n【{idx}】文件: {r['filename']}")
        print("-" * 80)
        print(f"    [时间] 对局时间范围: {format_time_range(r['match_times'])}")
        print(f"    [对局] 对局总数: {r['total_matches']} 局")
        print(f"    [藏品] 非0藏品统计:")
        print(f"       - 非0藏品数量: {r['non_zero_values_count']} 个")
        print(f"       - 非0藏品平均价值: {r['avg_non_zero_value']:,.0f}")
        print(f"    [Nico666] 统计:")
        print(f"       - 出现次数: {r['nico666_count']} 次")
        print(f"       - 总收益: {r['total_nico666_reward']:+,}")
        print(f"       - 平均每局收益: {r['avg_nico666_per_match']:+.2f}")
        print(f"    [AIR1314] 统计:")
        print(f"       - 出现次数: {r['air1314_count']} 次")
        print(f"       - 总收益: {r['total_air1314_reward']:+,}")
        print(f"       - 平均每局收益: {r['avg_air1314_per_match']:+.2f}")

    # 汇总统计
    print("\n" + "=" * 100)
    print("[汇总] 统计")
    print("=" * 100)

    total_all_matches = sum(r['total_matches'] for r in results if 'error' not in r)
    total_nico666_all = sum(r['total_nico666_reward'] for r in results if 'error' not in r)
    total_air1314_all = sum(r['total_air1314_reward'] for r in results if 'error' not in r)

    all_non_zero_values = []
    for r in results:
        if 'error' not in r and r['non_zero_values_count'] > 0:
            all_non_zero_values.append(r['avg_non_zero_value'])

    overall_avg_non_zero = sum(all_non_zero_values) / len(all_non_zero_values) if all_non_zero_values else 0
    overall_avg_nico666 = total_nico666_all / total_all_matches if total_all_matches > 0 else 0
    overall_avg_air1314 = total_air1314_all / total_all_matches if total_all_matches > 0 else 0

    print(f"    [文件] 处理文件数: {len(results)} 个")
    print(f"    [对局] 230系列对局总数: {total_all_matches} 局")
    print(f"    [藏品] 非0藏品平均价值: {overall_avg_non_zero:,.2f}")
    print(f"    [Nico666] 平均每局收益: {overall_avg_nico666:+.2f}")
    print(f"    [AIR1314] 平均每局收益: {overall_avg_air1314:+.2f}")

    # 生成CSV报表
    output_csv = os.path.join(TARGET_DIR, "230系列统计报表.csv")
    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            '序号', '文件名', '对局开始时间范围', '对局总数',
            '非0藏品数量', '非0藏品平均价值',
            'Nico666出现次数', 'Nico666总收益', 'Nico666平均每局收益',
            'AIR1314出现次数', 'AIR1314总收益', 'AIR1314平均每局收益'
        ])

        for idx, r in enumerate(results, 1):
            if 'error' in r:
                writer.writerow([idx, r['filename'], f"错误: {r['error']}", '', '', '', '', '', '', '', '', ''])
            else:
                writer.writerow([
                    idx,
                    r['filename'],
                    format_time_range(r['match_times']),
                    r['total_matches'],
                    r['non_zero_values_count'],
                    r['avg_non_zero_value'],
                    r['nico666_count'],
                    r['total_nico666_reward'],
                    r['avg_nico666_per_match'],
                    r['air1314_count'],
                    r['total_air1314_reward'],
                    r['avg_air1314_per_match']
                ])

    print(f"\n[完成] CSV报表已保存到: {output_csv}")

if __name__ == '__main__':
    main()
