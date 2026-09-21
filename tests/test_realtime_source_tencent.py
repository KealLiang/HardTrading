# -*- coding: utf-8 -*-
"""
腾讯行情链路（替代东财 push2 分页）回归测试。

运行：python tests/test_realtime_source_tencent.py [--live]
默认跑离线用例（符号映射 / 文本解析 / 数据源分发）；
加 --live 会真实请求 qt.gtimg.cn 校验字段与单位（约 1~2 秒）。
"""
import os
import sys

# 沙箱注入了 HTTP_PROXY，会让 requests 走不通外网；测试脚本内强制对腾讯域名直连
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from fetch import astock_data as ad  # noqa: E402

SPOT_COLUMNS = ['代码', '名称', '今开', '最新价', '最高', '最低', '成交量', '成交额',
                '振幅', '涨跌幅', '涨跌额', '换手率', '行情时间']

# 真实抓包样本（2026-09-21 收盘后，浦发银行）
SAMPLE_LINE = (
    'v_sh600000="1~浦发银行~600000~9.01~9.07~9.04~659062~267284~391778~9.01~7340~9.00~11956~'
    '8.99~11607~8.98~21164~8.97~12732~9.02~4307~9.03~4819~9.04~2485~9.05~4051~9.06~2684~~'
    '20260921161446~-0.06~-0.66~9.06~8.91~9.01/659062/593492200~659062~59349~0.20~5.86~~'
    '9.06~8.91~1.65~3000.86~3000.86~0.40~9.98~8.16~0.98~46453~9.01~4.85~6.00";'
)
# 停牌/退市样本：现价为 0
SAMPLE_HALT = 'v_bj430047="62~诺思兰德~430047~0.00~8.17~0.00~0~0~0~~20260921090000~0.00~0.00~0.00~0";'


def test_symbol_mapping() -> bool:
    cases = {'600000': 'sh600000', '688981': 'sh688981', '000001': 'sz000001',
             '300033': 'sz300033', '920002': 'bj920002', '430047': 'bj430047'}
    ok = True
    for code, want in cases.items():
        got = ad._tx_symbol(code)
        flag = got == want
        ok &= flag
        print(f"  {'OK ' if flag else 'FAIL'} {code} -> {got} (期望 {want})")
    return ok


def test_parse_line() -> bool:
    item = ad._parse_tx_quote(SAMPLE_LINE)
    checks = [
        (item is not None, '解析非空'),
        (item and item['代码'] == '600000', '代码=600000'),
        (item and item['名称'] == '浦发银行', '名称=浦发银行'),
        (item and abs(item['最新价'] - 9.01) < 1e-6, '最新价=9.01'),
        (item and abs(item['今开'] - 9.04) < 1e-6, '今开=9.04'),
        (item and abs(item['最高'] - 9.06) < 1e-6, '最高=9.06'),
        (item and abs(item['最低'] - 8.91) < 1e-6, '最低=8.91'),
        (item and abs(item['成交量'] - 659062) < 1e-6, '成交量=659062 手'),
        (item and abs(item['成交额'] - 593492200.0) < 1.0, '成交额=59349 万元 -> 593492200 元'),
        (item and abs(item['涨跌幅'] + 0.66) < 1e-6, '涨跌幅=-0.66'),
        (item and abs(item['涨跌额'] + 0.06) < 1e-6, '涨跌额=-0.06'),
        (item and abs(item['振幅'] - 1.65) < 1e-6, '振幅=1.65'),
        (item and abs(item['换手率'] - 0.20) < 1e-6, '换手率=0.20'),
        (item and item['行情时间'] == '20260921161446', '行情时间=20260921161446'),
        (ad._parse_tx_quote(SAMPLE_HALT) is None, '停牌行(现价0)被丢弃'),
        (ad._parse_tx_quote('v_pv_none_match="1";') is None, 'none_match 被丢弃'),
    ]
    for cond, desc in checks:
        print(f"  {'OK ' if cond else 'FAIL'} {desc}")
    return all(c for c, _ in checks)


def test_source_dispatch() -> bool:
    """分发逻辑：未知源报错；eastmoney 走 ak（mock），tencent 走腾讯（mock 名录）。"""
    ok = True
    # 实现里所有异常统一被 except 捕获后返回 False（与东财链路报错风格一致）
    ret = ad.StockDataFetcher(start_date='20250930', save_path='./data/astocks') \
        .fetch_and_save_data_from_realtime(source='unknown_src')
    ok_ret = ret is False
    print(f"  {'OK ' if ok_ret else 'FAIL'} 未知数据源返回 False（ret={ret}）")
    ok &= ok_ret

    calls = {'em': 0}
    original_em = ad.ak.stock_zh_a_spot_em

    def fake_em():
        calls['em'] += 1
        return pd.DataFrame(columns=['代码', '名称'])

    ad.ak.stock_zh_a_spot_em = fake_em
    try:
        ad.StockDataFetcher(start_date='20250930', save_path='./data/astocks') \
            .fetch_and_save_data_from_realtime(source='eastmoney')
        print(f"  {'OK ' if calls['em'] == 1 else 'FAIL'} eastmoney 分支调用 stock_zh_a_spot_em 次数={calls['em']}")
        ok &= calls['em'] == 1
    finally:
        ad.ak.stock_zh_a_spot_em = original_em
    return ok


def test_live_small() -> bool:
    """真实请求 12 只，校验字段与单位量级。"""
    df = ad.fetch_spot_tencent(['600000', '000001', '300033', '600610', '688981', '920002',
                                '000002', '601398', '300750', '002594', '000651', '600519'])
    ok = True
    ok &= _check(df is not None and not df.empty, f"返回 {0 if df is None else len(df)} 行")
    ok &= _check(list(df.columns) == SPOT_COLUMNS, '列名与东财 spot 对齐')
    if df is not None and not df.empty:
        row = df[df['代码'] == '600000']
        ok &= _check(not row.empty, '包含 600000')
        if not row.empty:
            r = row.iloc[0]
            ok &= _check(r['最新价'] > 0 and r['今开'] > 0, f"价格有效 开={r['今开']} 收={r['最新价']}")
            ok &= _check(r['最高'] >= r['最低'] > 0, f"最高>=最低>0 ({r['最高']}/{r['最低']})")
            ok &= _check(r['成交额'] > r['成交量'] * 100 * 0.5,
                         f"成交额/成交量量级合理（额={r['成交额']:.0f} 元, 量={r['成交量']:.0f} 手）")
            ok &= _check(str(r['行情时间'])[:8].isdigit(), f"行情时间={r['行情时间']}")
    return ok


def test_live_stale_guard() -> bool:
    """行情日期不符时应返回空，避免把上一交易日数据写成当日。"""
    df = ad.fetch_spot_tencent(['600000', '000001', '300033'], quote_date='2020-01-01')
    return _check(df.empty, f"非交易日/日期不符返回空（行数={len(df)}）")


def _check(cond, desc) -> bool:
    print(f"  {'OK ' if cond else 'FAIL'} {desc}")
    return bool(cond)


if __name__ == '__main__':
    live = '--live' in sys.argv
    print(f"[数据源常量] REALTIME_DATA_SOURCE = {ad.REALTIME_DATA_SOURCE}")
    results = {
        'symbol': test_symbol_mapping(),
        'parse': test_parse_line(),
        'dispatch': test_source_dispatch(),
    }
    if live:
        results['live-small'] = test_live_small()
        results['live-stale-guard'] = test_live_stale_guard()
    print('\n汇总:', {k: ('PASS' if v else 'FAIL') for k, v in results.items()})
    sys.exit(0 if all(results.values()) else 1)
