"""问财(pywencai / wencai_client)连通性自检。

用法：
    python labs/pywencai_test.py

排查顺序：
1. Cookie 是否配置
2. 新问句解析接口是否可用（老接口 /customized/chart/get-robot-data 已于 2026-09 下线）
3. 数据接口 getDataList 是否可用
4. 业务侧 fetch.tonghuashun.fupan 取数是否正常
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

from config.holder import config  # noqa: E402
from fetch.tonghuashun.wencai_client import query_wencai  # noqa: E402


def mask(s):
    return f'len={len(s)}' if s else '<空>'


def main():
    print('=' * 70)
    print('[1] Cookie')
    cookie = config.ths_cookie
    print('   ', mask(cookie))
    if not cookie:
        print('    ❌ 未配置 THS.cookie，请先更新 config/local.ini')
        return

    print('=' * 70)
    print('[2] query_wencai 基础查询')
    df = query_wencai('20260910涨停，非ST')
    if df is None or df.empty:
        print('    ❌ 查询失败，返回为空')
        return
    print(f'    ✅ 返回 {len(df)} 行 / {len(df.columns)} 列')
    print('    列名:', list(df.columns)[:10])

    print('=' * 70)
    print('[3] 业务侧取数：涨停 / 连板 / 首板 / 跌停')
    from fetch.tonghuashun import fupan

    date = '20260910'
    for name, fn in (('涨停', fupan.get_zt_stocks),
                     ('连板', fupan.get_lianban_stocks),
                     ('首板', fupan.get_shouban_stocks),
                     ('跌停', fupan.get_dieting_stocks)):
        try:
            d = fn(date)
            print(f'    {name}: {"空" if d is None or d.empty else f"{len(d)} 行"}')
        except Exception as e:  # noqa: BLE001
            print(f'    {name}: 异常 {type(e).__name__}: {e}')

    print('=' * 70)
    print('全部检查完成')


if __name__ == '__main__':
    main()
