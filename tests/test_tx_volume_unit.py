# -*- coding: utf-8 -*-
"""
腾讯链路成交量单位回归测试（2026-09-23 bug：科创板成交量放大 100 倍）。

背景：
  腾讯 qt.gtimg.cn 对**科创板 688/689** 返回的成交量单位是「股」，其余板块是「手」。
  落库口径要求与东财一致（手），因此科创板需 /100 折算。
  另外腾讯对已停更代码返回「占位行」（价=昨收，OHLCV 全 0），必须丢弃。

运行：python tests/test_tx_volume_unit.py [--live]
默认跑离线用例（构造真实抓包样本）；
加 --live 会真实请求 qt.gtimg.cn 交叉校验单位。
"""
import os
import sys

os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetch import astock_data as ad  # noqa: E402

FAILED = []


def check(name, got, want, tol=1e-6):
    ok = (got is None and want is None) or (
        got is not None and want is not None and abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
    )
    print('  %s %-42s got=%s want=%s' % ('OK  ' if ok else 'FAIL', name, got, want))
    if not ok:
        FAILED.append(name)
    return ok


def build_line(code, name, close, prev_close, open_, high, low, vol, amount, prefix=None):
    """按腾讯格式（88 字段）拼一行行情；vol 按该板块的真实单位填。"""
    f = [''] * 88
    f[0] = '62'
    f[1] = name
    f[2] = code
    f[3] = str(close)
    f[4] = str(prev_close)
    f[5] = str(open_)
    f[30] = '20260923150000'
    f[31], f[32] = '0.00', '0.00'
    f[33] = str(high)
    f[34] = str(low)
    f[35] = '%s/%d/%d' % (close, int(vol), int(amount))
    f[36] = str(int(vol))
    f[37] = '%.2f' % (amount / 10000.0)
    f[38], f[43] = '1.00', '1.00'
    sym = prefix or ad._tx_symbol(code)
    return 'v_%s="%s";' % (sym, '~'.join(f))


# ---- 真实抓包样本（2026-09-23 收盘后实测）----
CASES = [
    # (说明, 代码, 名称, 收, 昨收, 开, 高, 低, 腾讯成交量, 成交额, 期望落库成交量)
    ('科创板-长盈通(腾讯给股)', '688143', '长盈通', 193.59, 193.98, 195.05, 197.85, 189.03, 8785949, 1695307699, 87859.49),
    ('科创板-中芯国际(腾讯给股)', '688981', '中芯国际', 121.39, 122.41, 122.40, 122.41, 120.80, 18342178, 2229438568, 183421.78),
    ('沪主板-浦发银行(腾讯给手)', '600000', '浦发银行', 8.98, 9.04, 9.02, 9.05, 8.95, 511244, 458952162, 511244.0),
    ('深主板-平安银行(腾讯给手)', '000001', '平安银行', 11.60, 11.71, 11.68, 11.71, 11.55, 906726, 1052015092, 906726.0),
    ('创业板-同花顺(腾讯给手)', '300033', '同花顺', 208.64, 210.17, 211.00, 211.63, 207.80, 52012, 1086653771, 52012.0),
    ('北交所-万达轴承(腾讯给手)', '920002', '万达轴承', 50.06, 49.93, 49.80, 50.81, 49.77, 7407, 37214539, 7407.0),
    # 科创板一字板：high == low，无法用 VWAP 自检，只能靠前缀判定
    ('科创板一字板(需前缀兜底)', '688001', '华兴源创', 10.00, 9.09, 10.00, 10.00, 10.00, 1000000, 10000000, 10000.0),
]


def test_volume_unit_offline():
    print('[1] 成交量单位折算（离线样本）')
    for desc, code, name, c, pc, o, h, l, vol, amt, want in CASES:
        line = build_line(code, name, c, pc, o, h, l, vol, amt)
        row = ad._parse_tx_quote(line)
        check(desc, None if row is None else row['成交量'], want, tol=1e-9)


def test_placeholders_dropped():
    print('[2] 占位行 / 无行情行必须丢弃')
    # 北交所旧代码 43/83/87 段（已停更）：价=昨收，开/高/低/量/额全 0
    ph = build_line('430017', '星昊医药', 14.55, 14.55, 0.0, 0.0, 0.0, 0, 0, prefix='bj430017')
    check('北交所旧代码占位行 -> None', ad._parse_tx_quote(ph), None)
    # 现价为 0（退市）
    dead = build_line('600849', '退市股', 0.0, 8.17, 0.0, 0.0, 0.0, 0, 0, prefix='sh600849')
    check('现价为 0 -> None', ad._parse_tx_quote(dead), None)
    # 真停牌但 OHLC 有效（如全天只有集合竞价）不应被误杀
    ok_line = build_line('600000', '浦发银行', 9.02, 9.02, 9.02, 9.02, 9.02, 1000, 902000)
    row = ad._parse_tx_quote(ok_line)
    check('一字/窄幅正常行保留 成交量', None if row is None else row['成交量'], 1000.0)


def test_other_fields_intact():
    print('[3] 其余字段不受折算影响')
    line = build_line('688143', '长盈通', 193.59, 193.98, 195.05, 197.85, 189.03, 8785949, 1695307699)
    row = ad._parse_tx_quote(line)
    check('最新价', row['最新价'], 193.59)
    check('今开', row['今开'], 195.05)
    check('最高', row['最高'], 197.85)
    check('最低', row['最低'], 189.03)
    check('成交额', row['成交额'], 1695307699.0)
    check('换手率', row['换手率'], 1.0)


def test_live():
    print('[4] 真实请求交叉校验（--live）')
    df = ad.fetch_spot_tencent(['688143', '600000', '920002', '300033'], batch_size=50)
    if df.empty:
        print('  FAIL 未取到任何行情（网络/接口异常）')
        FAILED.append('live-empty')
        return
    by = {r['代码']: r for _, r in df.iterrows()}
    for code, label in (('688143', '科创板'), ('600000', '沪主板'), ('920002', '北交所'), ('300033', '创业板')):
        r = by.get(code)
        if r is None:
            print('  SKIP %s 未返回（可能停牌）' % code)
            continue
        price = float(r['最新价'])
        vol = float(r['成交量'])
        amt = float(r['成交额'])
        low, high = float(r['最低']), float(r['最高'])
        # 落库口径为「手」：成交额 / (成交量*100) 必须落在当日价格区间内
        vwap = amt / (vol * 100.0)
        ok = low <= vwap <= high
        print('  %s %s %-8s 成交量=%.0f手 VWAP=%.4f 区间=[%.2f,%.2f]' %
              ('OK  ' if ok else 'FAIL', label, code, vol, vwap, low, high))
        if not ok:
            FAILED.append('live-' + code)


def main():
    print('=' * 78)
    test_volume_unit_offline()
    test_placeholders_dropped()
    test_other_fields_intact()
    if '--live' in sys.argv:
        test_live()
    print('=' * 78)
    if FAILED:
        print('FAILED %d: %s' % (len(FAILED), FAILED))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
