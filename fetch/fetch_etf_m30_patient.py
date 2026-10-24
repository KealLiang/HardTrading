# -*- coding: utf-8 -*-
"""东财限流应对：逐只耐心重试拉取 30 分钟数据，成功一个写一个。
已完成的（m30 行数 > 320）自动跳过。最长运行约 45 分钟。
"""
import os, sys, time, random, logging

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

OUT_M30 = 'D:/Trading/data/etfs30'
os.makedirs(OUT_M30, exist_ok=True)

URL = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?'
       'fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&'
       'ut=7eea3edcaed734bea9cbfc24409ed989&klt=30&fqt=1&secid={secid}'
       '&beg=1979-09-01%2009%3A32%3A00&end=2222-01-01%2009%3A32%3A00')

HDRS = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']

def secid(code):
    return ('1.' if code.startswith(('5', '6')) else '0.') + code

def done(code):
    p = os.path.join(OUT_M30, code + '.csv')
    if not os.path.exists(p):
        return False
    with open(p, encoding='utf-8') as f:
        return sum(1 for _ in f) > 321   # 表头+321行以上=不是那个248根的短数据

def fetch_once(code):
    r = requests.get(URL.format(secid=secid(code)), headers=H, timeout=25)
    ks = r.json()['data']['klines']
    with open(os.path.join(OUT_M30, code + '.csv'), 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(HDRS) + '\n')
        for line in ks:
            f.write(line + '\n')
    return len(ks)

t0 = time.time()
DEADLINE = 45 * 60
pending = [c for c in CODES if not done(c)]
logging.info('待拉取 %d 只: %s', len(pending), ','.join(pending))
while pending and time.time() - t0 < DEADLINE:
    code = pending[0]
    try:
        n = fetch_once(code)
        logging.info('OK %s rows=%d  first=%s', code, n, 'x')
        pending.pop(0)
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        logging.warning('fail %s: %s', code, str(e)[:70])
        pending = pending[1:] + pending[:1]   # 轮转，换下一只
        time.sleep(random.uniform(60, 110))
print('PATIENT DONE, remaining=%d: %s' % (len(pending), ','.join(pending)))
