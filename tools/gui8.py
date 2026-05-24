# -*- coding: utf-8 -*-
"""
拍卖利润模拟器 — 通用版（R1~R5全系数可调 + 阻止分析）
运行: D:\python3.12\python.exe 拍卖模拟器.py
"""

import csv
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

# ============================================================
MULTIPLIERS = [2.0, 1.6, 1.3, 1.1]  # R1~R4 秒杀倍数
PREMIUM_MIN = 10000


# ============================================================
# CSV 解析
# ============================================================
def parse_bids(bid_str):
    result = [None] * 5
    if not bid_str or not bid_str.strip():
        return result
    for part in bid_str.split(';'):
        part = part.strip()
        if ':' not in part:
            continue
        k, v = part.split(':', 1)
        k, v = k.strip(), v.strip()
        if k.startswith('R') and k[1:].isdigit():
            idx = int(k[1:]) - 1
            if 0 <= idx < 5:
                try:
                    result[idx] = int(v)
                except ValueError:
                    pass
    return result


def load_games(filepath):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))

    games_dict = {}
    name_counts = Counter()

    for row in rows[1:]:
        if len(row) < 8:
            continue
        uid = row[0].strip()
        name = row[3].strip()
        bids = parse_bids(row[5])
        try:
            item_value = int(row[6])
        except ValueError:
            item_value = 0
        try:
            csv_profit = int(row[7])
        except ValueError:
            csv_profit = 0

        name_counts[name] += 1

        if uid not in games_dict:
            games_dict[uid] = {'uid': uid, 'players': [], 'prize_pool': 0}
        games_dict[uid]['players'].append({
            'name': name, 'bids': bids,
            'item_value': item_value, 'csv_profit': csv_profit,
        })
        if item_value > games_dict[uid]['prize_pool']:
            games_dict[uid]['prize_pool'] = item_value

    games = list(games_dict.values())
    games.sort(key=lambda g: g['uid'])
    top_name = name_counts.most_common(1)[0][0] if name_counts else ''
    return games, top_name


# ============================================================
# 模拟引擎
# ============================================================
def simulate_auction(players):
    for rnd in range(5):
        entries = []
        for p in players:
            b = p['bids'][rnd]
            if b is not None and b > 0:
                entries.append((p['name'], b))
        if not entries:
            continue
        entries.sort(key=lambda x: x[1], reverse=True)

        if rnd == 4:
            return entries[0][0], entries[0][1], 5
        if len(entries) == 1:
            return entries[0][0], entries[0][1], rnd + 1

        highest, second = entries[0][1], entries[1][1]
        if highest >= second * MULTIPLIERS[rnd]:
            return entries[0][0], highest, rnd + 1
    return None, 0, 0


def calc_target_profit(winner_name, winner_round_bid, prize_pool,
                       target_name, target_round_bid, ticket):
    if winner_name is None:
        return -ticket
    if winner_name == target_name:
        return prize_pool - target_round_bid - ticket
    premium = winner_round_bid - prize_pool
    if premium > PREMIUM_MIN:
        return round(premium * 0.1) - ticket
    return -ticket


def safe_round(orig_val, orig_coef, new_coef):
    if orig_val is None or orig_val <= 0 or orig_coef == 0:
        return orig_val
    d_val = Decimal(str(orig_val))
    d_orig = Decimal(str(orig_coef))
    d_new = Decimal(str(new_coef))
    est = d_val / d_orig
    return int((est * d_new).to_integral_value(ROUND_HALF_UP))


# ============================================================
# 单局模拟
# ============================================================
def simulate_raw(game, target_name, ticket):
    players = [{'name': p['name'], 'bids': p['bids'].copy()} for p in game['players']]
    winner, w_bid, rnd = simulate_auction(players)

    t_bid = 0
    if winner == target_name:
        for p in players:
            if p['name'] == target_name:
                t_bid = p['bids'][rnd - 1] or 0
                break

    profit = calc_target_profit(winner, w_bid, game['prize_pool'],
                                target_name, t_bid, ticket)
    return {'winner': winner or '无人', 'round': rnd, 'winner_bid': w_bid,
            'target_profit': profit, 'target_rbid': t_bid}


def simulate_adjusted(game, target_name, orig_coefs, new_coefs, ticket):
    target_bids = None
    target_csv_profit = None
    for p in game['players']:
        if p['name'] == target_name:
            target_bids = p['bids'].copy()
            target_csv_profit = p['csv_profit']
            break

    if target_bids is None:
        return None

    ests = [None] * 5
    new_bids = target_bids.copy()
    for i in range(5):
        ov = target_bids[i]
        oc = orig_coefs[i]
        nc = new_coefs[i]
        if ov is not None and ov > 0 and oc and oc != 0:
            ests[i] = ov / oc
            new_bids[i] = safe_round(ov, oc, nc)

    players = []
    for p in game['players']:
        bids = new_bids if p['name'] == target_name else p['bids'].copy()
        players.append({'name': p['name'], 'bids': bids})

    winner, w_bid, rnd = simulate_auction(players)

    t_bid = 0
    if winner == target_name:
        for p in players:
            if p['name'] == target_name:
                t_bid = p['bids'][rnd - 1] or 0
                break

    profit = calc_target_profit(winner, w_bid, game['prize_pool'],
                                target_name, t_bid, ticket)
    return {
        'winner': winner or '无人', 'round': rnd, 'winner_bid': w_bid,
        'target_profit': profit, 'target_rbid': t_bid,
        'ests': ests,
        'orig_bids': target_bids,
        'new_bids': new_bids,
        'csv_profit': target_csv_profit,
    }


# ============================================================
# GUI
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("拍卖利润模拟器")
        self.root.geometry("1300x750")
        self.root.resizable(True, True)

        self.games = []
        self.top_name = ''
        self.baseline = {}
        self.sim_results = {}
        self._sel_uid = None

        self.orig_entries = []
        self.new_spins = []
        self.new_vars = []

        self._build_ui()
        self._auto_load()

    # ======================== UI ========================
    def _build_ui(self):
        # ── ① CSV + 基础参数 ──
        f1 = ttk.Frame(self.root, padding=5)
        f1.pack(fill=tk.X)
        ttk.Label(f1, text="CSV:").pack(side=tk.LEFT)
        self.file_var = tk.StringVar()
        ttk.Entry(f1, textvariable=self.file_var, width=80).pack(side=tk.LEFT, padx=5)
        ttk.Button(f1, text="浏览", command=self._browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(f1, text="加载", command=self._do_load).pack(side=tk.LEFT, padx=2)

        ttk.Separator(f1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        ttk.Label(f1, text="目标玩家:").pack(side=tk.LEFT)
        self.target_var = tk.StringVar(value='')
        ttk.Entry(f1, textvariable=self.target_var, width=14).pack(side=tk.LEFT, padx=3)

        ttk.Label(f1, text="门票:").pack(side=tk.LEFT, padx=(8, 0))
        self.ticket_var = tk.StringVar(value='5000')
        ttk.Entry(f1, textvariable=self.ticket_var, width=7).pack(side=tk.LEFT, padx=2)

        ttk.Button(f1, text="▶ 全部模拟", command=self._sim_all).pack(side=tk.LEFT, padx=10)

        # ── ② 系数表 ──
        grp_coef = ttk.LabelFrame(self.root, text="系数设置（原系数用于反推估价，新系数用于生成出价）",
                                  padding=10)
        grp_coef.pack(fill=tk.X, padx=10, pady=(8, 0))

        ttk.Label(grp_coef, text="", width=4).grid(row=0, column=0)
        ttk.Label(grp_coef, text="原系数", width=8).grid(row=0, column=1)
        ttk.Label(grp_coef, text="新系数", width=8).grid(row=0, column=2)
        ttk.Label(grp_coef, text="", width=2).grid(row=0, column=3)

        defaults_orig = ['0.55', '0.60', '0.75', '0.80', '0.86']
        defaults_new  = ['0.55', '0.60', '0.75', '0.80', '0.86']

        for i in range(5):
            row = i + 1
            ttk.Label(grp_coef, text=f"R{i+1}", width=4,
                      font=('', 9, 'bold')).grid(row=row, column=0, pady=2, sticky=tk.E)

            ev = tk.StringVar(value=defaults_orig[i])
            e = ttk.Entry(grp_coef, textvariable=ev, width=7)
            e.grid(row=row, column=1, padx=4, pady=1)
            self.orig_entries.append(e)

            sv = tk.StringVar(value=defaults_new[i])
            sp = tk.Spinbox(grp_coef, textvariable=sv,
                            from_=0.01, to=5.00, increment=0.01,
                            width=7, format='%.2f',
                            command=self._sim_all)
            sp.grid(row=row, column=2, padx=4, pady=1)
            sp.bind('<Return>', lambda e: self._sim_all())
            self.new_spins.append(sp)
            self.new_vars.append(sv)

        ttk.Button(grp_coef, text="导出CSV", command=self._export).grid(
            row=1, column=3, rowspan=2, padx=20, sticky='ns')

        # ── ③ 表格 ──
        f_table = ttk.Frame(self.root, padding=5)
        f_table.pack(fill=tk.BOTH, expand=True, padx=5)

        cols = ('uid',
                'orig_r1', 'orig_r2', 'orig_r3', 'orig_r4', 'orig_r5',
                'new_r1', 'new_r2', 'new_r3', 'new_r4', 'new_r5',
                'base', 'sim', 'delta')
        self.tree = ttk.Treeview(f_table, columns=cols, show='headings')

        cfg = [
            ('uid',     '对局UID',      195),
            ('orig_r1', '原R1',          65),
            ('orig_r2', '原R2',          65),
            ('orig_r3', '原R3',          65),
            ('orig_r4', '原R4',          65),
            ('orig_r5', '原R5',          65),
            ('new_r1',  '新R1',          65),
            ('new_r2',  '新R2',          65),
            ('new_r3',  '新R3',          65),
            ('new_r4',  '新R4',          65),
            ('new_r5',  '新R5',          65),
            ('base',    '基准利润',       75),
            ('sim',     '模拟利润',       75),
            ('delta',   '变化',          70),
        ]
        for c, label, w in cfg:
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor='center')

        sb = ttk.Scrollbar(f_table, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        # ── ④ 详情 ──
        f_detail = ttk.Frame(self.root, padding=5)
        f_detail.pack(fill=tk.X)
        self.detail_var = tk.StringVar(value="—")
        ttk.Label(f_detail, textvariable=self.detail_var,
                  relief=tk.SUNKEN, anchor=tk.W, padding=4).pack(fill=tk.X)

        # ── ⑤ 状态栏（双行） ──
        f_status = ttk.Frame(self.root)
        f_status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="就绪 — 请加载 CSV")
        ttk.Label(f_status, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=4).pack(fill=tk.X)
        self.analysis_var = tk.StringVar(value="")
        ttk.Label(f_status, textvariable=self.analysis_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=4, foreground='#0066cc').pack(fill=tk.X)

    # ======================== 事件 ========================
    def _auto_load(self):
        candidates = [
            r'D:\下载\竞拍之王工具\测试2\game_match_reports_20260519_034157.csv',
            r'D:\下载\竞拍之王工具\测试\1.csv',
        ]
        for p in candidates:
            if os.path.exists(p):
                self.file_var.set(p)
                self._do_load()
                return

    def _browse(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("所有", "*.*")])
        if path:
            self.file_var.set(path)

    def _do_load(self):
        path = self.file_var.get().strip()
        if not path:
            return
        try:
            self.games, self.top_name = load_games(path)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return

        self.target_var.set(self.top_name)
        self._sim_all()

    # ======================== 参数读取 ========================
    def _read_params(self):
        target = self.target_var.get().strip()
        try:
            ticket = int(self.ticket_var.get().strip())
        except ValueError:
            ticket = 5000

        orig_coefs = []
        new_coefs = []
        for i in range(5):
            try:
                orig_coefs.append(float(self.orig_entries[i].get().strip()))
            except ValueError:
                orig_coefs.append(0.0)
            try:
                new_coefs.append(float(self.new_vars[i].get().strip()))
            except ValueError:
                new_coefs.append(0.0)

        return target, ticket, orig_coefs, new_coefs

    # ======================== 全部模拟 ========================
    def _sim_all(self, *args):
        if not self.games:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        if not target:
            return

        self.baseline.clear()
        self.sim_results.clear()
        for g in self.games:
            self.baseline[g['uid']] = simulate_raw(g, target, ticket)
            sr = simulate_adjusted(g, target, orig_coefs, new_coefs, ticket)
            self.sim_results[g['uid']] = sr

        self._refresh_tree()

    # ======================== 表格 ========================
    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        target, ticket, orig_coefs, new_coefs = self._read_params()

        for g in self.games:
            uid = g['uid']
            bl = self.baseline.get(uid, {})
            sr = self.sim_results.get(uid)

            if sr is None:
                self.tree.insert('', tk.END, values=(
                    uid, *(['—'] * 10), '—', '—', '—'
                ))
                continue

            bp = bl.get('target_profit', 0)
            sp = sr.get('target_profit', 0)
            delta = sp - bp
            delta_s = f"+{delta}" if delta > 0 else str(delta)

            orig = sr['orig_bids']
            newb = sr['new_bids']

            self.tree.insert('', tk.END, values=(
                uid,
                _b(orig[0]), _b(orig[1]), _b(orig[2]), _b(orig[3]), _b(orig[4]),
                _b(newb[0]), _b(newb[1]), _b(newb[2]), _b(newb[3]), _b(newb[4]),
                str(bp), str(sp), delta_s,
            ))

        self._update_status()

    def _update_status(self):
        if not self.sim_results:
            return

        valid = [sr for sr in self.sim_results.values() if sr is not None]
        if not valid:
            return

        target, ticket, orig_coefs, new_coefs = self._read_params()

        csv_sum = sum(sr['csv_profit'] for sr in valid)
        base_sum = sum(self.baseline[g['uid']]['target_profit']
                       for g in self.games
                       if self.sim_results.get(g['uid']) is not None)
        sim_sum = sum(sr['target_profit'] for sr in valid)
        d = sim_sum - base_sum

        # 系数不变时出价一致性检查
        mismatch = 0
        for sr in valid:
            for i in range(5):
                if sr['orig_bids'][i] is not None and sr['new_bids'][i] is not None:
                    if sr['orig_bids'][i] != sr['new_bids'][i]:
                        mismatch += 1
                        break

        self.status_var.set(
            f"共 {len(valid)} 局 | 目标: {target} | CSV原始: {csv_sum:,} | "
            f"门票={ticket} | "
            f"原系数 {_fmt5(orig_coefs)} → 新系数 {_fmt5(new_coefs)} | "
            f"基准: {base_sum:,} | 模拟: {sim_sum:,} | 变化: {d:+,}"
            + (f" | ⚠出价不一致:{mismatch}局" if mismatch else "")
        )

        # ── 阻止分析 ──
        blocked = []  # [(uid, orig_winner, orig_profit, new_profit)]
        for g in self.games:
            sr = self.sim_results.get(g['uid'])
            if sr is None:
                continue
            bl = self.baseline.get(g['uid'])
            if bl is None:
                continue

            orig_winner = bl.get('winner', '无人')
            if orig_winner == target or orig_winner == '无人':
                continue

            sim_winner = sr.get('winner', '无人')
            if sim_winner != orig_winner:
                # 这个原始赢家被阻止了
                prize_pool = g['prize_pool']
                orig_w_profit = prize_pool - bl['winner_bid'] - ticket
                new_w_profit = -ticket  # 输了只亏门票
                blocked.append((g['uid'], orig_winner, orig_w_profit, new_w_profit))

        if blocked:
            total_change = sum(owp - nwp for _, _, owp, nwp in blocked)
            # 找变化最大的 3 个
            blocked.sort(key=lambda x: abs(x[2] - x[3]), reverse=True)
            top3 = blocked[:3]
            top_strs = []
            for uid, name, owp, nwp in top3:
                ch = owp - nwp
                short_uid = uid[-20:] if len(uid) > 20 else uid
                top_strs.append(f"{short_uid}/{name}:{owp:+,}→{nwp:+,}")

            self.analysis_var.set(
                f"阻止 {len(blocked)} 人拍下仓 | 他们利润变化合计: {total_change:+,} | "
                + "Top: " + "  ".join(top_strs)
            )
        else:
            self.analysis_var.set("阻止 0 人（无人被阻止）")

    # ======================== 选中行 ========================
    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        self._sel_uid = self.tree.item(sel[0], 'values')[0]
        self._show_detail(self._sel_uid)

    def _show_detail(self, uid):
        g = next((g for g in self.games if g['uid'] == uid), None)
        if not g:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        bl = self.baseline.get(uid, {})
        sr = self.sim_results.get(uid)

        if sr is None:
            self.detail_var.set(f"[{uid}] 目标玩家「{target}」不在本局")
            return

        ests = sr['ests']
        orig = sr['orig_bids']
        newb = sr['new_bids']

        parts = []
        for i in range(5):
            e = _i(ests[i])
            o = _b(orig[i])
            n = _b(newb[i])
            ok = "✓" if (orig[i] == newb[i]) else "✗"
            parts.append(f"R{i+1}:估价={e}(÷{orig_coefs[i]}) 原={o}→×{new_coefs[i]}→新={n}[{ok}]")

        # 阻止信息
        blocked_info = ""
        orig_winner = bl.get('winner', '无人')
        sim_winner = sr.get('winner', '无人')
        if orig_winner != target and orig_winner != '无人' and sim_winner != orig_winner:
            prize_pool = g['prize_pool']
            owp = prize_pool - bl['winner_bid'] - ticket
            nwp = -ticket
            blocked_info = f" | ⛔阻止了{orig_winner} 利润{owp:+,}→{nwp:+,}"

        self.detail_var.set(
            f"[{uid}]  藏品价值={g['prize_pool']:,} | "
            + " | ".join(parts) + " | "
            f"基准: {bl.get('winner','—')}(R{bl.get('round','—')}) "
            f"利润={bl.get('target_profit','—')} | "
            f"模拟: {sr.get('winner','—')}(R{sr.get('round','—')}) "
            f"利润={sr.get('target_profit','—')}"
            + blocked_info
        )

    # ======================== 导出 ========================
    def _export(self):
        if not self.games or not self.sim_results:
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv',
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        target, ticket, orig_coefs, new_coefs = self._read_params()
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['对局UID',
                        '估价1', '估价2', '估价3', '估价4', '估价5',
                        '原R1', '原R2', '原R3', '原R4', '原R5',
                        '新R1', '新R2', '新R3', '新R4', '新R5',
                        '基准利润', '模拟利润', '利润变化',
                        '原始赢家', '模拟赢家', '是否被阻止'])
            for g in self.games:
                sr = self.sim_results.get(g['uid'])
                if sr is None:
                    continue
                bl = self.baseline.get(g['uid'], {})
                ests = sr['ests']
                orig = sr['orig_bids']
                newb = sr['new_bids']
                bp = bl.get('target_profit', 0)
                sp = sr.get('target_profit', 0)

                orig_w = bl.get('winner', '无人')
                sim_w = sr.get('winner', '无人')
                was_blocked = (orig_w != target and orig_w != '无人'
                               and sim_w != orig_w)

                w.writerow([
                    g['uid'],
                    *[round(e) if e else '' for e in ests],
                    *[_b(orig[i]) for i in range(5)],
                    *[_b(newb[i]) for i in range(5)],
                    bp, sp, sp - bp,
                    orig_w, sim_w,
                    '是' if was_blocked else '',
                ])
        messagebox.showinfo("导出成功", f"已保存到:\n{path}")


def _fmt5(coefs):
    return '×'.join(f'{c:.2f}' for c in coefs)


def _b(v):
    if v is None or v == '':
        return '—'
    return str(v)


def _i(v):
    if v is None:
        return '—'
    return str(round(v))


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
