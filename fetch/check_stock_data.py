# -*- coding: utf-8 -*-
"""个股日线数据质检。

查四类问题：
  1. 负价 / 零价         —— 减法式前复权的典型症状
  2. OHLC 不自洽         —— low>min(open,close) 或 high<max(open,close)
  3. 单日涨跌幅超限      —— 主板 ±10%、创业板/科创板 ±20%，超 25% 视为异常
  4. 日期重复 / 长期断档 —— 重复行、相邻交易日间隔 >15 自然日（停牌）

用法：python check_stock_data.py
"""
import os, glob, datetime

D = 'D:/Trading/data/stocks'


def limit_of(code):
    """涨跌幅上限（2020-08 注册制后创业板 20%，此前 10%；科创板一直 20%）"""
    return 0.20 if code.startswith(('300', '301', '688')) else 0.10


rows = []
for f in sorted(glob.glob(os.path.join(D, '*.csv'))):
    code = os.path.basename(f)[:-4]
    with open(f, encoding='utf-8') as fh:
        head = fh.readline().strip()
        data = [l.strip().split(',') for l in fh if l.strip()]
    if not data:
        print('%-7s EMPTY' % code); continue
    neg = ohlc_bad = jump = 0
    dup = gap = 0
    prev = None
    seen = set()
    worst = (0, '')
    lim = limit_of(code)
    for r in data:
        try:
            d, o, c, h, l = r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])
        except Exception:
            ohlc_bad += 1; continue
        if min(o, c, h, l) <= 0: neg += 1
        if l > min(o, c) + 1e-6 or h < max(o, c) - 1e-6: ohlc_bad += 1
        if d in seen:
            dup += 1
        seen.add(d)
        if prev:
            pc, pd = prev
            chg = c / pc - 1
            if abs(chg) > lim * 2.5:
                jump += 1
                if abs(chg) > abs(worst[0]): worst = (chg, d)
            if (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(pd)).days > 15:
                gap += 1
        prev = (c, d)
    rows.append((code, len(data), data[0][0], data[-1][0], neg, ohlc_bad, jump, gap,
                 (worst[1], round(100 * worst[0], 2))))

print('%-7s %6s %-11s %-11s %5s %5s %5s %4s  %s' % ('code', 'bars', 'start', 'end', 'neg', 'ohlc', 'jump', 'gap', 'worst'))
bad = 0
for r in sorted(rows):
    flag = '*' if (r[4] or r[5] or r[6]) else ' '
    if flag == '*': bad += 1
    print('%s%-7s %6d %-11s %-11s %5d %5d %5d %4d  %s' % (flag, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
print('\n合计 %d 只，异常 %d 只' % (len(rows), bad))
