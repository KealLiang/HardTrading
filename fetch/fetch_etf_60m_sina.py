# -*- coding: utf-8 -*-
"""
拉取 ETF 60 分钟 K 线（新浪源，替代被 WAF 限流的东财 push2his）

- 源: https://quotes.sina.cn/cn/api/jsonp_v2.php/.../CN_MarketDataService.getKLineData
- scale=60, datalen=1023（接口上限，约 1 年 / 256 个交易日）
- 输出与 data/etfs_bt_30m/ 完全同结构: [BOM]时间,开盘,收盘,最高,最低,成交量
- 落盘: D:/Trading/data/etfs_bt_60m/<code>.csv
"""
import os
import re
import csv
import sys
import json
import time
import random

import requests

for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
    os.environ[k] = ''

OUT_DIR = r'D:/Trading/data/etfs_bt_60m'
SRC_DIR = r'D:/Trading/data/etfs'
DAILY_30 = r'D:/Trading/data/etfs_bt_30m'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Referer': 'https://finance.sina.com.cn/',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
URL = ('https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/'
       'CN_MarketDataService.getKLineData'
       '?symbol={sym}&scale=60&ma=no&datalen=1023')


def to_sym(code):
    return ('sh' if code.startswith('5') else 'sz') + code


def parse_payload(text):
    """剥掉 jsonp 壳: /*<script>...</script>*/ var _=([...]);"""
    text = re.sub(r'^/\*.*?\*/', '', text, flags=re.S).strip()
    text = re.sub(r'^var\s*_\s*=\s*\(', '', text)
    text = re.sub(r'\)\s*;?\s*$', '', text)
    data = json.loads(text)
    if not data:
        raise ValueError('empty payload (可能被限流)')
    return data


def fetch(code, tries=4):
    sym = to_sym(code)
    last = None
    for i in range(tries):
        try:
            r = requests.get(URL.format(sym=sym), headers=HEADERS, timeout=25)
            r.encoding = 'utf-8'
            data = parse_payload(r.text)
            if len(data) < 100:
                raise ValueError('too few bars %d' % len(data))
            return data
        except Exception as e:
            last = e
            time.sleep(3 + i * 4 + random.uniform(0, 2))
    raise RuntimeError('fetch %s failed: %s' % (code, last))


def write_csv(code, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, code + '.csv')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['时间', '开盘', '收盘', '最高', '最低', '成交量'])
        for r in data:
            w.writerow([
                r['day'],
                '%.3f' % float(r['open']),
                '%.3f' % float(r['close']),
                '%.3f' % float(r['high']),
                '%.3f' % float(r['low']),
                '%d' % int(float(r['volume'])),
            ])
    return path


def check_scale(code, data):
    """与日线收盘比，检测份额折算/复权错配"""
    p = os.path.join(SRC_DIR, code + '.csv')
    if not os.path.exists(p):
        return None
    daily = {}
    with open(p, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            d = (row.get('日期') or '')[:10]
            if d:
                daily[d] = float(row['收盘'])
    bad = 0
    n = 0
    worst = 1.0
    last_of_day = {}
    for r in data:
        last_of_day[r['day'][:10]] = float(r['close'])
    for d, c in last_of_day.items():
        dc = daily.get(d)
        if not dc:
            continue
        n += 1
        ratio = c / dc
        if ratio < 0.9 or ratio > 1.1:
            bad += 1
        if abs(ratio - 1) > abs(worst - 1):
            worst = ratio
    return n, bad, worst


def main():
    codes = sorted(f[:-4] for f in os.listdir(SRC_DIR) if f.endswith('.csv'))
    ok = fail = 0
    print('目标 %d 只 → %s' % (len(codes), OUT_DIR))
    for i, code in enumerate(codes, 1):
        try:
            data = fetch(code)
            path = write_csv(code, data)
            chk = check_scale(code, data)
            span = '%s~%s' % (data[0]['day'][:10], data[-1]['day'][:10])
            msg = '[%d/%d] %s n=%d %s' % (i, len(codes), code, len(data), span)
            if chk:
                n, bad, worst = chk
                flag = '  ⚠刻度错配 %d/%d 天 (最差 ratio %.3f)' % (bad, n, worst) if bad else ''
                msg += '  日线对比 %d 天 最差 ratio %.4f%s' % (n, worst, flag)
            print(msg, flush=True)
            ok += 1
        except Exception as e:
            print('[%d/%d] %s FAIL %s' % (i, len(codes), code, e), flush=True)
            fail += 1
        time.sleep(1.2 + random.uniform(0, 0.8))
    print('完成 ok=%d fail=%d' % (ok, fail))


if __name__ == '__main__':
    main()
