# -*- coding: utf-8 -*-
"""回测用：全量重刷 26 只 ETF 日线（force_update 保证前复权基准与 30 分钟数据一致）"""
import sys, logging
sys.path.insert(0, 'D:/Trading')
sys.path.insert(0, 'D:/Trading/fetch')
import _em_headers_patch  # noqa: F401  浏览器头补丁（WAF 绕行）+ 禁代理
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
from etf_data import ETFDataFetcher

CODES = ['512880', '512800', '512480', '513260', '159995', '159857',
         '512980', '159819', '515880', '513050', '562500', '159869',
         '515700', '159928', '159992', '512660', '159825', '512200',
         '515220', '159949', '510300', '159353', '512890', '159207',
         '518880', '511010']

f = ETFDataFetcher(start_date='20120101', save_path='D:/Trading/data/etfs',
                   max_workers=4, force_update=True, max_sleep_time=1500)
f.fetch_and_save_data(CODES)
print('DAILY DONE')
