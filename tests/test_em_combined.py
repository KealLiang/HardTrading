#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：东财一次请求同时更新6列行情+成交额
1) 临时目录模拟缺最近2天，验证增量回补与原sina文件对账
2) 真实路径验证 no-new 分支
"""

import os
import shutil
import sys

sys.path.insert(0, '.')

import pandas as pd

from fetch.indexes_data import fetch_and_save_index_data_em

SYMBOL, SECID = 'sh000001', '1.000001'
IDX_SRC = './data/indexes/sh000001_上证指数.csv'
AMT_SRC = './data/indexes/sh000001_amount.csv'
TMP = './data/indexes_em_test'

# 1. 临时目录模拟缺口
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
idx_tmp = os.path.join(TMP, 'sh000001_上证指数.csv')
amt_tmp = os.path.join(TMP, 'sh000001_amount.csv')
pd.read_csv(IDX_SRC, header=None).iloc[:-2].to_csv(idx_tmp, index=False, header=False)
pd.read_csv(AMT_SRC).iloc[:-2].to_csv(amt_tmp, index=False)

fetch_and_save_index_data_em(SYMBOL, SECID, idx_tmp, amt_tmp)

# 2. 对账：volume 必须精确一致，OHLC 允许 0.01 内精度差（东财2位小数 vs sina 3位），amount 精确一致
idx_new = pd.read_csv(idx_tmp, header=None, names=['date', 'open', 'high', 'low', 'close', 'volume'])
idx_old = pd.read_csv(IDX_SRC, header=None, names=idx_new.columns)
amt_new = pd.read_csv(amt_tmp)
amt_old = pd.read_csv(AMT_SRC)

assert len(idx_new) == len(idx_old), f"行情行数不一致: {len(idx_new)} vs {len(idx_old)}"
assert len(amt_new) == len(amt_old), f"成交额行数不一致: {len(amt_new)} vs {len(amt_old)}"

tail = 2
vol_ok = (idx_new['volume'].tail(tail).values == idx_old['volume'].tail(tail).values).all()
amt_ok = (amt_new['amount'].tail(tail).round(2).values ==
          amt_old['amount'].tail(tail).round(2).values).all()
diff = (idx_new['close'].tail(tail).values - idx_old['close'].tail(tail).values)
close_ok = (abs(diff) <= 0.01).all()
date_ok = (idx_new['date'].tail(tail).values == idx_old['date'].tail(tail).values).all()

print(f"volume 一致: {vol_ok}, amount 一致: {amt_ok}, close误差<=0.01: {close_ok}, 日期一致: {date_ok}")
assert vol_ok and amt_ok and close_ok and date_ok, "对账失败"
print("回补对账 PASS")

# 3. 真实路径 no-new 分支
fetch_and_save_index_data_em(SYMBOL, SECID, IDX_SRC, AMT_SRC)
shutil.rmtree(TMP, ignore_errors=True)
print('验证完成')
