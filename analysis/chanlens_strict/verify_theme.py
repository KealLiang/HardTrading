# -*- coding: utf-8 -*-
"""
独立复核 theme.js 的主线判定：直读 CSV 重算行业 20 日涨幅排名，
对每个 lag=1 信号取 discT 日的行业分位，重新分桶，与 JS 结果比对 n 和均值。
只用标准库，不复用 JS 任何代码。
"""
import bisect
import csv
import json
import os
from collections import defaultdict

ROOT = 'D:/Trading'
SW = os.path.join(ROOT, 'data', 'sw_industry')
PACK = os.path.join(ROOT, 'analysis', 'chanlens_strict', 'tmp', 'pack_daily_stock.json')
JS = os.path.join(ROOT, 'analysis', 'chanlens_strict', 'out', 'theme_stock.json')

TOP_Q = 0.75
XS = [3, 5, 10, 20, 60]
BUCKETS = [(0.90, 1.01, '前10%'), (0.75, 0.90, '10~25%'), (0.50, 0.75, '25~50%'),
           (0.25, 0.50, '50~75%'), (0.00, 0.25, '后25%')]


def load_sw():
    meta = json.load(open(os.path.join(SW, 'meta.json'), encoding='utf-8'))
    out = {}
    for code in meta:
        fp = os.path.join(SW, code + '.csv')
        if not os.path.exists(fp):
            continue
        rows = list(csv.DictReader(open(fp, encoding='utf-8-sig')))
        dates = [r['日期'] for r in rows]
        close = [float(r['收盘']) for r in rows]
        out[code] = (dates, close, {d: i for i, d in enumerate(dates)})
    return out


def main():
    sws = load_sw()
    s2s = json.load(open(os.path.join(SW, 'stock2sw.json'), encoding='utf-8'))
    pack = json.load(open(PACK, encoding='utf-8'))

    # 所有行业日期的并集
    alld = sorted({d for code in sws for d in sws[code][0]})
    print('行业 %d 个，日期 %d 个 (%s ~ %s)' % (len(sws), len(alld), alld[0], alld[-1]))

    # 每个交易日 ret20（i>=121）→ 排名分位 i/(n-1)
    rank = {}
    for d in alld:
        vals = []
        for code, (dates, close, idx) in sws.items():
            i = idx.get(d)
            if i is None or i < 121:
                continue
            vals.append((code, close[i] / close[i - 20] - 1))
        if len(vals) < len(sws) * 0.5:
            continue
        vals.sort(key=lambda z: z[1])
        n = len(vals)
        rank[d] = {c: (k / (n - 1) if n > 1 else 0.5) for k, (c, _) in enumerate(vals)}

    # JS 的 rankAt：取当日或之前最近的可用截面（缺数据时回退，不丢信号）
    rdates = sorted(rank.keys())

    def rank_at(d):
        k = bisect.bisect_right(rdates, d) - 1
        return rank[rdates[k]] if k >= 0 else None

    js = json.load(open(JS, encoding='utf-8'))
    js_tab = js['tab']

    # 逐信号判定
    rows = []
    for p in pack['packs']:
        code = p['code']
        swc = s2s.get(code)
        if not swc or swc not in sws:
            continue
        n = len(p['o'])
        # 可交易性
        trad = [True] * n
        for i in range(1, n):
            if p['h'][i] == p['l'][i] and p['o'][i] > p['c'][i - 1] * 1.045:
                trad[i] = False
            elif (pd_parse(p['dates'][i]) - pd_parse(p['dates'][i - 1])) > 15:
                trad[i] = False
        # 250 日价格分位
        pq = [None] * n
        for i in range(250, n):
            win = p['c'][i - 249:i + 1]
            lo, hi = min(win), max(win)
            pq[i] = (p['c'][i] - lo) / (hi - lo) if hi > lo else None

        for b in p.get('buy') or []:
            if b['discT'] - b['readyK'] != 1:
                continue
            if not (1 <= b['level'] <= 3):
                continue
            e = b['discT'] + 1
            if e + 60 > n - 1 or not trad[e] or pq[e] is None:
                continue
            d = p['dates'][b['discT']]
            rk = rank_at(d)
            if rk is None or swc not in rk:
                continue
            rows.append({'code': code, 'sw': swc, 'type': 'L%d' % b['level'],
                         'q': rk[swc], 'date': p['dates'][e]})

    print('信号 %d 个（JS 记 %d）\n' % (len(rows), js['nRows']))

    ok = True
    print('类型  分桶        n(JS)  n(独立)  占比(JS)   一致')
    for ty in ['L1', 'L2', 'L3']:
        s = [z for z in rows if z['type'] == ty]
        for (lo, hi, lab), jso in zip(BUCKETS, js_tab[ty]):
            a = len([z for z in s if lo <= z['q'] < hi])
            same = (a == jso['n'])
            ok = ok and same
            print('%s   %-9s %6d %7d   %7.3f%%  %s' %
                  (ty, lab, jso['n'], a, 100 * a / len(s), 'ok' if same else 'MISMATCH'))

    # 主线/非主线切分
    print('\n类型   主线n(JS)  主线n(独立)  非主线n(JS)  非主线n(独立)')
    for ty in ['L1', 'L2', 'L3']:
        s = [z for z in rows if z['type'] == ty]
        a = len([z for z in s if z['q'] >= TOP_Q])
        c = js['cut'][ty]
        same = (a == c['nIn'] and len(s) - a == c['nOut'])
        ok = ok and same
        print('%s     %7d %11d %11d %13d  %s' %
              (ty, c['nIn'], a, c['nOut'], len(s) - a, 'ok' if same else 'MISMATCH'))

    print('\n' + ('✅ 全部一致' if ok else '❌ 有差异'))


def pd_parse(s):
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    # 简化的日差（够用：只判断 >15 天）
    import datetime
    return datetime.date(y, m, d).toordinal()


if __name__ == '__main__':
    main()
