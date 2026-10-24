# -*- coding: utf-8 -*-
"""回测用：拉取 30 分钟 K 线（前复权），存 D:/Trading/data/etfs30/<code>.csv"""
import os, time, random, logging
import sys
sys.path.insert(0, 'D:/Trading/fetch')
import _em_headers_patch  # noqa: F401  浏览器头补丁（WAF 绕行）+ 禁代理
import akshare as ak

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
OUT = 'D:/Trading/data/etfs30'
os.makedirs(OUT, exist_ok=True)

CODES = ['512880', '512800', '512480', '513260', '159995', '159857',
         '512980', '159819', '515880', '513050', '562500', '159869',
         '515700', '159928', '159992', '512660', '159825', '512200',
         '515220', '159949', '510300', '159353', '512890', '159207',
         '518880', '511010']

for c in CODES:
    try:
        df = ak.fund_etf_hist_min_em(symbol=c, period='30', adjust='qfq')
        if df is None or df.empty:
            logging.warning('%s 无 30 分钟数据', c)
            continue
        df.to_csv(os.path.join(OUT, c + '.csv'), index=False)
        logging.info('%s rows=%d %s ~ %s', c, len(df), df.iloc[0, 0], df.iloc[-1, 0])
    except Exception as e:
        logging.error('%s 失败: %s', c, e)
    time.sleep(random.uniform(0.5, 1.5))
print('MIN30 DONE')
