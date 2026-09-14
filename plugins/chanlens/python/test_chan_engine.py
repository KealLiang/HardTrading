"""Python 引擎单元测试 —— 与 Node 版 tests/test_chan.js 互相印证。

运行： python python/test_chan_engine.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chan_engine import (analyze_klines, merge_klines, find_fractals,
                         dedup_fractals, build_bi, force_range, macd, DEFAULTS)

PASS = FAIL = 0


def check(name, cond, extra=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  ✓ ' + name)
    else:
        FAIL += 1
        print('  ✗ ' + name + ('  → ' + repr(extra) if extra is not None else ''))


def group(name):
    print('\n' + name)


def approx(a, b, tol=1e-9):
    return abs(a - b) < tol


# -------------------------------------------------------------- 1. 包含处理
group('[1] 包含处理')
m = merge_klines([{'h': 10, 'l': 8}, {'h': 12, 'l': 9}, {'h': 11, 'l': 9.5}])
check('包含后被合并', len(m) == 2, len(m))
check('向上合并 high 取 max', approx(m[1]['high'], 12), m[1])
check('向上合并 low 取 max', approx(m[1]['low'], 9.5), m[1])

# ------------------------------------------------------------------ 2. 分型
group('[2] 分型识别')
fx = find_fractals([
    {'high': 10, 'low': 9, 'si': 0, 'ei': 0},
    {'high': 12, 'low': 10.5, 'si': 1, 'ei': 1},
    {'high': 11, 'low': 10, 'si': 2, 'ei': 2}])
check('识别一个顶分型', len(fx) == 1 and fx[0].type == 1, fx)
check('顶分型价格取高点', len(fx) and approx(fx[0].price, 12))

# ------------------------------------------------------ 3. 同类型分型归并
group('[3] 同类型分型归并')
r = dedup_fractals([
    __import__('chan_engine').Fractal(1, 1, 1, 12, 10),
    __import__('chan_engine').Fractal(1, 3, 3, 14, 11),
    __import__('chan_engine').Fractal(-1, 5, 5, 12, 9),
    __import__('chan_engine').Fractal(-1, 7, 7, 13, 8)])
check('归并后只剩 2 个', len(r) == 2, len(r))
check('保留更高的顶', r[0].type == 1 and r[0].high == 14)
check('保留更低的底', r[1].type == -1 and r[1].low == 8)

# -------------------------------------------------------------------- 4. 笔
group('[4] 笔的划分')
bis = build_bi([
    __import__('chan_engine').Fractal(-1, 1, 1, 10, 9),
    __import__('chan_engine').Fractal(1, 4, 4, 13, 11),
    __import__('chan_engine').Fractal(-1, 7, 7, 12, 8),
    __import__('chan_engine').Fractal(1, 10, 10, 15, 13)], DEFAULTS)
check('应形成 3 笔', len(bis) == 3, [(b.direction, b.start_k, b.end_k) for b in bis])
check('第1笔方向向上', bis and bis[0].direction == 1)
check('第1笔起点取底的低点', bis and approx(bis[0].start_price, 9))
check('第1笔终点取顶的高点', bis and approx(bis[0].end_price, 13))
check('笔首尾相接', all(bis[i].start_k == bis[i - 1].end_k for i in range(1, len(bis))))

# ------------------------------------------------- 5. 真实数据全链路
group('[5] 真实日线全链路')
fixture = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'tools', 'testdata', '600519_daily.json')
if os.path.exists(fixture):
    with open(fixture, encoding='utf-8') as f:
        klines = json.load(f)['klines']
    res = analyze_klines(klines)
    print('    统计:', res['stats'])
    check('识别出大量笔', res['stats']['bi'] > 50, res['stats']['bi'])
    check('识别出中枢', res['stats']['zs'] >= 5, res['stats']['zs'])
    check('所有中枢 ZD < ZG', all(z.zd < z.zg for z in res['zhongshus']))
    check('识别出背驰', res['stats']['div'] > 0, res['stats']['div'])
    check('所有背驰力度确实衰减',
          all(d['ratio'] < DEFAULTS['div_min_force_ratio'] for d in res['divergences']))
    levels = {}
    for p in res['points']:
        levels[p['level']] = levels.get(p['level'], 0) + 1
    print('    买卖点分级:', levels)
    check('产出一类买卖点', levels.get(1, 0) > 0, levels)
    check('产出二类买卖点', levels.get(2, 0) > 0, levels)

    # 与 JS 版结果交叉验证（两边算法逐行对应，数量应完全一致）
    js_stats_file = os.path.join(os.path.dirname(fixture), '_js_stats.json')
    if os.path.exists(js_stats_file):
        with open(js_stats_file, encoding='utf-8') as f:
            js = json.load(f)
        check('与 JS 引擎笔数一致', js.get('biCount') == res['stats']['bi'],
              {'js': js.get('biCount'), 'py': res['stats']['bi']})
        check('与 JS 引擎中枢数一致', js.get('zsCount') == res['stats']['zs'],
              {'js': js.get('zsCount'), 'py': res['stats']['zs']})
        check('与 JS 引擎背驰数一致', js.get('divCount') == res['stats']['div'],
              {'js': js.get('divCount'), 'py': res['stats']['div']})
else:
    print('    （跳过：缺少 fixture，先运行 tools/fetch_testdata.py）')

# -------------------------------------------------------------- 6. 健壮性
group('[6] 健壮性')
check('空数据不崩溃', analyze_klines([])['bis'] == [])
dirty = [dict(k={'t': '', 'o': float('nan'), 'h': float('nan'),
                 'l': float('nan'), 'c': float('nan'), 'v': 0}) for _ in range(10)]
check('含 NaN 不崩溃', isinstance(analyze_klines(
    [{'t': '', 'o': float('nan'), 'h': float('nan'), 'l': float('nan'), 'c': float('nan'), 'v': 0}
     if i % 3 == 0 else {'t': str(i), 'o': 1 + i, 'h': 2 + i, 'l': 0.5 + i, 'c': 1.5 + i, 'v': 1}
     for i in range(60)])['stats'], dict))

# -------------------------------------------------------------- 7. 指标
group('[7] 指标层')
if os.path.exists(fixture):
    closes = [float(k['c']) for k in klines]
    m = macd(closes)
    check('MACD 长度一致', len(m['hist']) == len(closes))
    check('存在正负柱', any(v > 0 for v in m['hist']) and any(v < 0 for v in m['hist']))
    fs = force_range(m['hist'], 0, 30, -1, 'same')
    fa = force_range(m['hist'], 0, 30, -1, 'abs')
    fp = force_range(m['hist'], 0, 30, -1, 'per_bar')
    check('abs ≥ same', fa >= fs - 1e-9, (fa, fs))
    check('per_bar = same/根数', abs(fp - fs / 31) < 1e-9, (fp, fs / 31))

print('\n' + '=' * 50)
print('结果：%d 通过，%d 失败' % (PASS, FAIL))
print('=' * 50)
sys.exit(1 if FAIL else 0)
