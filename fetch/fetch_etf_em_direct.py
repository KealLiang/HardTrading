# -*- coding: utf-8 -*-
"""绕过 akshare，直连东财 push2his kline 接口：
   日线(klt=101) → D:/Trading/data/etfs/<code>.csv（全量重写，qfq 统一基准）
   30分(klt=30)  → D:/Trading/data/etfs30/<code>.csv
"""
import os, sys, time, random, json, logging

sys.path.insert(0, 'D:/Trading/fetch')
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ[k] = ''
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import requests

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://quote.eastmoney.com/',
    'Connection': 'keep-alive',
}

CODES = ['512880', '512800', '512480', '513260', '159995', '159857',
         '512980', '159819', '515880', '513050', '562500', '159869',
         '515700', '159928', '159992', '512660', '159825', '512200',
         '515220', '159949', '510300', '159353', '512890', '159207',
         '518880', '511010']

OUT_DAILY = 'D:/Trading/data/etfs'
OUT_M30 = 'D:/Trading/data/etfs30'
os.makedirs(OUT_DAILY, exist_ok=True)
os.makedirs(OUT_M30, exist_ok=True)

URL = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?'
       'fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&'
       'ut=7eea3edcaed734bea9cbfc24409ed989&klt={klt}&fqt=1&secid={secid}'
       '&beg=1979-09-01%2009%3A32%3A00&end=2222-01-01%2009%3A32%3A00')

HDRS = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']

def secid(code):
    return ('1.' if code.startswith(('5', '6')) else '0.') + code

def fetch(code, klt, retries=4):
    u = URL.format(klt=klt, secid=secid(code))
    for i in range(retries):
        try:
            r = requests.get(u, headers=H, timeout=20)
            j = r.json()
            data = j.get('data') or {}
            ks = data.get('klines') or []
            if ks:
                return ks
            logging.warning('%s klt=%s 空数据(code=%s)', code, klt, j.get('error_code') or j.get('rc'))
            return None if not ks else ks
        except Exception as e:
            logging.warning('%s klt=%s 第%d次失败: %s', code, klt, i + 1, str(e)[:80])
            time.sleep(1 + i)
    return None

def save(path, ks):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(HDRS) + '\n')
        for line in ks:
            f.write(line + '\n')   # 东财字段顺序即 HDRS 顺序

for code in CODES:
    m = fetch(code, 30) if os.environ.get('M30_ONLY') else None
    d = None if os.environ.get('M30_ONLY') else fetch(code, 101)
    ok_d = ok_m = False
    if d:
        save(os.path.join(OUT_DAILY, code + '.csv'), d); ok_d = True
    if m:
        save(os.path.join(OUT_M30, code + '.csv'), m); ok_m = True
    rng = (m[0].split(',')[0] + '~' + m[-1].split(',')[0]) if m else '-'
    logging.info('%s daily=%s(%d) m30=%s(%d) %s', code, 'OK' if ok_d else 'SKIP', len(d or []), 'OK' if ok_m else 'FAIL', len(m or []), rng)
    time.sleep(random.uniform(1.5, 2.5))
print('EM DIRECT DONE')
