# -*- coding: utf-8 -*-
"""个股日线抓取（新浪源，标准等比后复权），供「日线买点」个股回测使用。

为什么不用腾讯：腾讯 ifzq 的复权是「加法式」（p ± 累计分红），倒推到早年会出现
负价（600519 2001 年 qfq = -314.30），且加法复权会把收益率按 p/(p+累计分红) 压缩，
送股无法还原。akshare 的新浪源是标准等比后复权，送转分红都按比例调整。

已验证：600519 后复权 2001-08-27 开 34.51 → 2026-10-30 开 12106.86（约 351 倍），
与「上市价 34.51、现价 1392、期间多次送转」的常识一致；腾讯 hfq 同 9468.80 明显偏低。

输出列：日期,开盘,收盘,最高,最低,成交量 （lib.js parseCsv 只要求前五列）
用法：
  python fetch_stock_sina.py --all
  python fetch_stock_sina.py --codes 600519,000858
  python fetch_stock_sina.py --all --resume
"""
import os, sys, argparse, time

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ[k] = ''
os.environ['NO_PROXY'] = '*'

import akshare as ak

OUT = 'D:/Trading/data/stocks'
HDRS = ['日期', '开盘', '收盘', '最高', '最低', '成交量']

# 组 → 代码 → 简称（大市值 / 高换手 / 知名；避开小盘题材）
GROUP = {
    '金融': [('600036', '招商银行'), ('601318', '中国平安'), ('600030', '中信证券'), ('601166', '兴业银行')],
    '消费': [('600519', '贵州茅台'), ('000858', '五粮液'), ('000333', '美的集团'),
             ('000651', '格力电器'), ('600887', '伊利股份'), ('600600', '青岛啤酒')],
    '医药': [('600276', '恒瑞医药'), ('000538', '云南白药'), ('600196', '复星医药'), ('000963', '华东医药')],
    '科技': [('002415', '海康威视'), ('000725', '京东方A'), ('000063', '中兴通讯'),
             ('600584', '长电科技'), ('002049', '紫光国微'), ('002230', '科大讯飞')],
    '新能源': [('002594', '比亚迪'), ('601012', '隆基绿能'), ('002460', '赣锋锂业'),
               ('600438', '通威股份'), ('300750', '宁德时代')],
    '周期': [('601899', '紫金矿业'), ('601088', '中国神华'), ('600019', '宝钢股份'), ('600585', '海螺水泥')],
    '军工': [('600760', '中航沈飞'), ('600893', '航发动力')],
    '地产建筑': [('000002', '万科A'), ('601668', '中国建筑'), ('600048', '保利发展')],
    '公用': [('600900', '长江电力'), ('600011', '华能国际')],
    '农业': [('002714', '牧原股份'), ('000876', '新希望')],
    '传媒': [('300059', '东方财富'), ('002027', '分众传媒')],
    '汽车机械': [('600104', '上汽集团'), ('600031', '三一重工'), ('601766', '中国中车')],
}
CODES = [c for g in GROUP.values() for c, _ in g]
NAME = {c: n for g in GROUP.values() for c, n in g}


def sym(code):
    return ('sh' if code[0] in '56' else 'sz') + code


def save(code, df):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, code + '.csv')
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(HDRS) + '\n')
        for _, r in df.iterrows():
            f.write('%s,%.4f,%.4f,%.4f,%.4f,%.2f\n' % (
                str(r['date'])[:10], r['open'], r['close'], r['high'], r['low'], r['volume']))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--codes', default='')
    ap.add_argument('--resume', action='store_true', help='跳过已存在的 csv')
    a = ap.parse_args()
    codes = CODES if a.all else [c for c in a.codes.split(',') if c]
    if not codes:
        print('nothing to do'); return
    print('目标 %d 只 → %s' % (len(codes), OUT), flush=True)
    ok, fail, skip = 0, [], 0
    for i, code in enumerate(codes, 1):
        if a.resume and os.path.exists(os.path.join(OUT, code + '.csv')):
            skip += 1; continue
        df = None
        for attempt in range(4):
            try:
                df = ak.stock_zh_a_daily(symbol=sym(code), start_date='19900101',
                                         end_date='20261231', adjust='hfq')
                break
            except Exception as e:
                wait = 10 + 15 * attempt
                print('   retry %d %s: %s → 等 %ds' % (attempt + 1, code, str(e)[:60], wait), flush=True)
                time.sleep(wait)
        if df is None or len(df) == 0:
            print('%2d/%d %-7s FAIL' % (i, len(codes), code), flush=True)
            fail.append(code); continue
        save(code, df)
        ok += 1
        print('%2d/%d %-7s %-6s bars=%-5d %s ~ %s' % (
            i, len(codes), code, NAME.get(code, ''), len(df),
            str(df.iloc[0]['date'])[:10], str(df.iloc[-1]['date'])[:10]), flush=True)
        time.sleep(1.2)
    print('DONE ok=%d skip=%d fail=%d %s' % (ok, skip, len(fail), fail))


if __name__ == '__main__':
    main()
