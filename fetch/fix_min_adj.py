# -*- coding: utf-8 -*-
"""
分钟线复权修正（通用）：把不复权的 min 线调整为前复权，口径对齐 data/etfs/ 日线

用法: python fix_min_adj.py <src_dir> <dst_dir>
  python fix_min_adj.py D:/Trading/data/etfs_bt_30m     D:/Trading/data/etfs_bt_30m_adj
  python fix_min_adj.py D:/Trading/data/etfs_bt_60m     D:/Trading/data/etfs_bt_60m_adj

原理:
  raw_d   = 日线前复权收盘_d / min线当日末根收盘_d
  正常日 raw 恒定；除权日 raw 跳变
  从最新日往前，仅在跳变日（|Δ|>0.4%）更新因子，其余沿用 → 阶梯因子
  每个 bar 的 OHLC 乘当日因子；成交量不动
"""
import os
import csv
import sys

DDIR = r'D:/Trading/data/etfs'
JUMP = 0.004


def load_daily(code):
    m = {}
    p = os.path.join(DDIR, code + '.csv')
    if not os.path.exists(p):
        return m
    for row in csv.DictReader(open(p, encoding='utf-8-sig')):
        d = (row.get('日期') or '')[:10]
        if d:
            m[d] = float(row['收盘'])
    return m


def load_min(code, src):
    rows = list(csv.DictReader(open(os.path.join(src, code + '.csv'), encoding='utf-8-sig')))
    return [{
        't': (r['时间'] or '').strip(),
        'o': float(r['开盘']), 'c': float(r['收盘']),
        'h': float(r['最高']), 'l': float(r['最低']),
        'v': r['成交量'],
    } for r in rows if r.get('时间')]


def build_adj(bars, daily):
    last = {}
    for b in bars:
        last[b['t'][:10]] = b['c']
    raw = {d: daily[d] / last[d] for d in last if d in daily and daily[d] > 0 and last[d] > 0}
    days = sorted(last)
    adj = {}
    prev = None
    for d in reversed(days):
        if d not in raw:
            continue
        if prev is None:
            f = 1.0
        elif abs(raw[d] / raw[prev] - 1) > JUMP:
            f = adj[prev] * (raw[d] / raw[prev])
        else:
            f = adj[prev]
        adj[d] = f
        prev = d
    return adj


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else r'D:/Trading/data/etfs_bt_60m'
    dst = sys.argv[2] if len(sys.argv) > 2 else src + '_adj'
    os.makedirs(dst, exist_ok=True)
    codes = sorted(f[:-4] for f in os.listdir(src) if f.endswith('.csv'))
    print('src=%s\ndst=%s\n标的 %d 只' % (src, dst, len(codes)))
    worst_all = 0.0
    for code in codes:
        bars = load_min(code, src)
        daily = load_daily(code)
        if not daily:
            print('%s 无日线，跳过' % code)
            continue
        adj = build_adj(bars, daily)
        out = []
        for b in bars:
            f = adj.get(b['t'][:10], 1.0)
            out.append([b['t'], '%.3f' % (b['o'] * f), '%.3f' % (b['c'] * f),
                        '%.3f' % (b['h'] * f), '%.3f' % (b['l'] * f), b['v']])
        with open(os.path.join(dst, code + '.csv'), 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['时间', '开盘', '收盘', '最高', '最低', '成交量'])
            w.writerows(out)
        # 校验
        last = {}
        for b in out:
            last[b[0][:10]] = float(b[2])
        worst = 1.0
        for d, c in last.items():
            if d in daily:
                r = c / daily[d]
                if abs(r - 1) > abs(worst - 1):
                    worst = r
        worst_all = max(worst_all, abs(worst - 1))
        fs = sorted(set(round(v, 6) for v in adj.values()))
        print('%s n=%d 复权后最差 ratio %.5f 因子档位 %d' % (code, len(out), worst, len(fs)))
    print('全池最大偏差 %.4f%%' % (100 * worst_all))


if __name__ == '__main__':
    main()
