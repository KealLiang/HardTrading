"""从东方财富拉取真实行情，生成 chanlens 插件的离线测试用 fixture。

用法:
    python tools/fetch_testdata.py 600519
    python tools/fetch_testdata.py 000001 300750

输出到 tools/testdata/<code>_<period>.json,供 Node 引擎直接加载验证。
"""
import json
import os
import sys
import urllib.request
import urllib.parse

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'testdata')

HOST = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'

PERIODS = {
    'daily': '101',
    '60m': '60',
    '30m': '30',
    '15m': '15',
    '5m': '5',
    'weekly': '102',
    'monthly': '103',
}


def to_secid(code):
    code = code.strip()
    if code.startswith(('60', '68', '11', '5', '9')):
        return '1.' + code
    return '0.' + code


def fetch(code, period='daily', limit=800, adjust=1):
    """adjust: 0=不复权 1=前复权 2=后复权"""
    params = {
        'secid': to_secid(code),
        'klt': PERIODS[period],
        'fqt': str(adjust),
        'lmt': str(limit),
        'end': '20500101',
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
    }
    url = HOST + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) chanlens-dev/1.0',
        'Referer': 'https://quote.eastmoney.com/',
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode('utf-8'))
    data = payload.get('data') or {}
    klines = data.get('klines') or []
    out = []
    for line in klines:
        p = line.split(',')
        # f51 时间, f52 开, f53 收, f54 高, f55 低, f56 量, f57 额, f58 振幅, f59 涨跌幅, f60 涨跌额, f61 换手
        out.append({
            't': p[0],
            'o': float(p[1]), 'c': float(p[2]), 'h': float(p[3]), 'l': float(p[4]),
            'v': float(p[5]), 'a': float(p[6]) if p[6] else 0.0,
            'pct': float(p[8]) if p[8] else 0.0,
            'turn': float(p[10]) if len(p) > 10 and p[10] else 0.0,
        })
    return {
        'code': code,
        'name': data.get('name', ''),
        'secid': to_secid(code),
        'period': period,
        'adjust': adjust,
        'klines': out,
    }


def main():
    codes = sys.argv[1:] or ['600519']
    os.makedirs(OUT_DIR, exist_ok=True)
    for raw in codes:
        # 支持 600519:daily 写法
        if ':' in raw:
            code, period = raw.split(':', 1)
        else:
            code, period = raw, 'daily'
        try:
            res = fetch(code, period)
            name = '%s_%s.json' % (code, period)
            path = os.path.join(OUT_DIR, name)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
            print('OK  %-10s %-6s %4d 根 → %s' % (res['name'] or code, period, len(res['klines']), path))
        except Exception as e:
            print('FAIL %s: %s' % (raw, e))


if __name__ == '__main__':
    main()
