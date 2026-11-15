# -*- coding: utf-8 -*-
"""
拉申万一级行业指数日线 + 成分股，建立「个股 → 申万一级行业」映射。
输出：
  data/sw_industry/<code>.csv   日期,开盘,收盘,最高,最低,成交量,成交额
  data/sw_industry/meta.json    {code: name}
  data/sw_industry/stock2sw.json {stock_code: sw_code}
用法：
  python fetch_sw_industry.py            # 增量（已有文件跳过）
  python fetch_sw_industry.py --force    # 全量重拉
"""
import os
import sys
import json
import time

import akshare as ak

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sw_industry')
FORCE = '--force' in sys.argv


def main():
    os.makedirs(OUT, exist_ok=True)
    info = ak.sw_index_first_info()
    codes = [c.split('.')[0] for c in info['行业代码'].tolist()]
    names = info['行业名称'].tolist()
    meta = dict(zip(codes, names))

    for code, name in zip(codes, names):
        fp = os.path.join(OUT, code + '.csv')
        if os.path.exists(fp) and not FORCE:
            print('skip', code, name)
            continue
        for attempt in range(3):
            try:
                df = ak.index_hist_sw(symbol=code, period='day')
                break
            except Exception as e:
                print('retry', code, type(e).__name__, str(e)[:60])
                time.sleep(2)
        else:
            print('FAIL', code, name)
            continue
        df['日期'] = df['日期'].astype(str)
        df = df[df['日期'] >= '2003-01-01']
        df.to_csv(fp, index=False, encoding='utf-8-sig')
        print(code, name, len(df), df['日期'].iloc[0], '~', df['日期'].iloc[-1])

    json.dump(meta, open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    # 成分股映射（当前成分，用于个股行业归属）
    s2s = {}
    for code, name in zip(codes, names):
        for attempt in range(3):
            try:
                comp = ak.index_component_sw(symbol=code)
                break
            except Exception as e:
                print('retry comp', code, str(e)[:50])
                time.sleep(2)
        else:
            continue
        for sc in comp['证券代码'].tolist():
            s2s[str(sc)] = code
        print('comp', code, name, len(comp))
    json.dump(s2s, open(os.path.join(OUT, 'stock2sw.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0)
    print('done. industries=%d stocks=%d' % (len(meta), len(s2s)))


if __name__ == '__main__':
    main()
