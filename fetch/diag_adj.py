# -*- coding: utf-8 -*-
"""ETF 数据质检：腾讯 qfq 与新浪不复权的比值 R=qfq/raw。
正确的 qfq：R 只在除权日跳变（幅度 = 分红率，通常 1~5%），其余日子仅舍入噪声（<0.3%）。
R 出现 >2% 的跳变且非除权 → 复权因子有 bug。

用法：python diag_adj.py            # 质检 EXT 18 只
      python diag_adj.py 510050     # 指定
"""
import sys, csv
import akshare as ak

EXT = ['510050', '510500', '512100', '588000', '512010', '512170', '512400', '512070', '512690',
       '159920', '513100', '513500', '515210', '159996', '516160', '159611', '516970', '159865']
OLD = ['159819', '159825', '159857', '159869', '159928', '159949', '159992', '159995',
       '510300', '511010', '512200', '512480', '512660', '512800', '512880', '512890',
       '512980', '513050', '513260', '515220', '515700', '515880', '518880', '562500']


def check(code):
    sym = ('sh' if code[0] in '56' else 'sz') + code
    try:
        raw = ak.fund_etf_hist_sina(symbol=sym)
    except Exception as e:
        return code, 'SINA_ERR', str(e)[:50], None
    R = {}
    for r in raw.itertuples():
        c = float(r.close)
        if c > 0:
            R[str(r.date)] = c
    qq = {}
    with open('D:/Trading/data/etfs/%s.csv' % code, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            qq[row['日期']] = float(row['收盘'])
    common = sorted(set(R) & set(qq))
    if not common:
        return code, 'NO_OVERLAP', '', None
    big = []
    prev = None
    for d in common:
        if qq[d] <= 0 or R[d] <= 0:
            continue
        r = qq[d] / R[d]
        if prev is not None and prev > 0 and abs(r - prev) / prev > 0.02:
            big.append((d, round((r / prev - 1) * 100, 1)))
        prev = r
    r0 = qq[common[0]] / R[common[0]] if R[common[0]] else None
    r1 = qq[common[-1]] / R[common[-1]] if R[common[-1]] else None
    return code, ('OK' if not big else 'BAD'), 'R0=%.3f R1=%.3f 大跳变%d' % (r0, r1, len(big)), big[:6]


codes = sys.argv[1:] or (EXT + OLD)
for c in codes:
    code, st, msg, big = check(c)
    tag = '新增' if c in EXT else '原池'
    print('%-7s %-4s %-4s %-30s %s' % (code, tag, st, msg, ('' if not big else str(big))))
