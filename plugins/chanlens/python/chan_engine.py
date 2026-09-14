"""chan_engine.py —— 缠论结构识别引擎（Python 版）

与 chanlens 插件里的 core/chan.js 逐行对应，方便把浏览器里看到的结构
直接搬到 D:/Trading 的回测/选股体系里复现。

用法::

    from plugins.chanlens.python.chan_engine import analyze, analyze_df
    result = analyze_df(df, min_fx_gap=1, seg_algo='simple')
    result['zhongshus']   # 中枢
    result['divergences'] # 背驰
    result['points']      # 一二三类买卖点

输入 df 需要包含列：开盘/收盘/最高/最低（中文列名，与 fetch.astock_data 一致），
或英文列 open/close/high/low 均可。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    'merge': True,
    'min_fx_gap': 1,
    'bi_require_break': True,
    'seg_algo': 'simple',            # 'simple' | 'feature'
    'feature_merge': True,
    'seg_min_pens': 3,
    'zs_source': 'bi',               # 'bi' | 'seg'
    'zs_min_parts': 3,
    'zs_extend_update': False,
    'div_mode': 'pen',               # 'pen' | 'zs'
    'div_min_force_ratio': 0.85,
    'div_fallback_amplitude': True,
    'force_mode': 'same',            # 'same' | 'abs' | 'per_bar'
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
    'show_buy': True,
    'show_sell': True,
    'points_on_segs': True,
}


# --------------------------------------------------------------------- 工具
def _opts(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    o = dict(DEFAULTS)
    if user:
        for k, v in user.items():
            if k in o:
                o[k] = v
    return o


def ema(values: List[float], n: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if not closes:
        return {'dif': [], 'dea': [], 'hist': []}
    ef, es = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, signal)
    hist = [a - b for a, b in zip(dif, dea)]
    return {'dif': dif, 'dea': dea, 'hist': hist}


def force_range(hist: List[float], start: int, end: int, direction: int,
                mode: str = 'same') -> float:
    """区间力度：MACD 柱面积。same=同号柱面积（教科书口径），abs=绝对值和，
    per_bar=面积/K线根数。"""
    a, b = max(0, min(start, end)), min(len(hist) - 1, max(start, end))
    if b <= a:
        return 0.0
    if mode == 'abs':
        return sum(abs(x) for x in hist[a:b + 1])
    total = 0.0
    for x in hist[a:b + 1]:
        if direction > 0 and x > 0:
            total += x
        elif direction < 0 and x < 0:
            total += -x
    return total / (b - a + 1) if mode == 'per_bar' else total


# ------------------------------------------------------------------ 数据结构
@dataclass
class Fractal:
    type: int            # 1=顶 -1=底
    mi: int              # 处理后 K 线索引
    k: int               # 原始 K 线索引
    high: float
    low: float

    @property
    def price(self) -> float:
        return self.high if self.type > 0 else self.low


@dataclass
class Bi:
    direction: int
    start_k: int
    end_k: int
    start_price: float
    end_price: float
    high: float
    low: float
    confirmed: bool = True


@dataclass
class Seg:
    direction: int
    start_bi: int
    end_bi: int
    pen_count: int
    start_k: int
    end_k: int
    start_price: float
    end_price: float
    high: float
    low: float
    confirmed: bool = True


@dataclass
class Zhongshu:
    zd: float
    zg: float
    start_part: int
    end_part: int
    part_count: int
    start_k: int
    end_k: int


# ------------------------------------------------------------ 1. 包含处理
def merge_klines(klines: List[Dict[str, float]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, k in enumerate(klines):
        h, l = float(k['h']), float(k['l'])
        if not (math.isfinite(h) and math.isfinite(l)):
            continue
        cur = {'high': h, 'low': l, 'si': i, 'ei': i}
        if not out:
            out.append(cur)
            continue
        prev = out[-1]
        contained = (cur['high'] <= prev['high'] and cur['low'] >= prev['low']) or \
                    (cur['high'] >= prev['high'] and cur['low'] <= prev['low'])
        if not contained:
            out.append(cur)
            continue
        if len(out) >= 2:
            if out[-1]['high'] > out[-2]['high']:
                d = 1
            elif out[-1]['high'] < out[-2]['high']:
                d = -1
            else:
                d = 1 if out[-1]['low'] > out[-2]['low'] else -1
        else:
            d = -1 if prev['high'] >= cur['high'] else 1
        if d > 0:
            prev['high'] = max(prev['high'], cur['high'])
            prev['low'] = max(prev['low'], cur['low'])
        else:
            prev['high'] = min(prev['high'], cur['high'])
            prev['low'] = min(prev['low'], cur['low'])
        prev['ei'] = i
    return out


# ------------------------------------------------------------------ 2. 分型
def find_fractals(merged: List[Dict[str, Any]]) -> List[Fractal]:
    fxs: List[Fractal] = []
    for i in range(1, len(merged) - 1):
        p, c, n = merged[i - 1], merged[i], merged[i + 1]
        if c['high'] > p['high'] and c['high'] > n['high'] and \
           c['low'] > p['low'] and c['low'] > n['low']:
            fxs.append(Fractal(1, i, merged[i]['ei'], c['high'], c['low']))
        elif c['low'] < p['low'] and c['low'] < n['low'] and \
                c['high'] < p['high'] and c['high'] < n['high']:
            fxs.append(Fractal(-1, i, merged[i]['ei'], c['high'], c['low']))
    return fxs


def dedup_fractals(fxs: List[Fractal]) -> List[Fractal]:
    res: List[Fractal] = []
    for fx in fxs:
        if not res or res[-1].type != fx.type:
            res.append(fx)
            continue
        last = res[-1]
        if fx.type == 1 and fx.high >= last.high:
            res[-1] = fx
        elif fx.type == -1 and fx.low <= last.low:
            res[-1] = fx
    return res


# -------------------------------------------------------------------- 3. 笔
def build_bi(fxs: List[Fractal], opts: Dict[str, Any]) -> List[Bi]:
    bis: List[Bi] = []
    i, guard = 0, 0
    while i < len(fxs) - 1 and guard < 100000:
        guard += 1
        anchor = fxs[i]
        target, moved = -1, False
        j = i + 1
        while j < len(fxs):
            fx = fxs[j]
            if fx.type == anchor.type:
                better = fx.high > anchor.high if fx.type == 1 else fx.low < anchor.low
                if better:
                    _extend_last_pen(bis, anchor, fx)
                    i = j
                    moved = True
                    break
                j += 1
                continue
            gap = fx.mi - anchor.mi - 1
            up = anchor.type == -1 and fx.type == 1
            ok = gap >= opts['min_fx_gap']
            if ok and opts['bi_require_break']:
                ok = fx.high > anchor.high if up else fx.low < anchor.low
            if ok:
                target = j
                break
            j += 1
        if moved:
            continue
        if target < 0:
            break
        a, b = fxs[i], fxs[target]
        up = a.type == -1 and b.type == 1
        bis.append(Bi(
            direction=1 if up else -1,
            start_k=a.k, end_k=b.k,
            start_price=a.low if up else a.high,
            end_price=b.high if up else b.low,
            high=max(a.high, b.high), low=min(a.low, b.low)))
        i = target
    if bis:
        bis[-1].confirmed = False
    return bis


def _extend_last_pen(bis: List[Bi], old: Fractal, new: Fractal) -> None:
    if not bis:
        return
    last = bis[-1]
    if last.end_k != old.k:
        return
    last.end_k = new.k
    last.end_price = new.high if last.direction > 0 else new.low
    last.high = max(last.high, new.high)
    last.low = min(last.low, new.low)


# ------------------------------------------------------------------ 4. 线段
def build_segments(bis: List[Bi], opts: Dict[str, Any]) -> List[Seg]:
    segs: List[Seg] = []
    n = len(bis)
    s, guard = 0, 0
    while s < n and guard < 20000:
        guard += 1
        if n - s < opts['seg_min_pens']:
            segs.append(_make_seg(bis, s, n - 1, False))
            break
        end = (_find_seg_end_simple(bis, s) if opts['seg_algo'] == 'simple'
               else _find_seg_end_feature(bis, s, opts))
        if end < 0:
            segs.append(_make_seg(bis, s, n - 1, False))
            break
        segs.append(_make_seg(bis, s, end, True))
        s = end + 1
    return segs


def _make_seg(bis: List[Bi], s: int, e: int, confirmed: bool) -> Seg:
    hi = max(b.high for b in bis[s:e + 1])
    lo = min(b.low for b in bis[s:e + 1])
    return Seg(
        direction=bis[s].direction, start_bi=s, end_bi=e,
        pen_count=e - s + 1,
        start_k=bis[s].start_k, end_k=bis[e].end_k,
        start_price=bis[s].start_price, end_price=bis[e].end_price,
        high=hi, low=lo, confirmed=confirmed)


def _find_seg_end_feature(bis: List[Bi], s: int, opts: Dict[str, Any]) -> int:
    n = len(bis)
    direction = bis[s].direction
    k = s + 2
    while k < n:
        if k + 3 >= n:
            break
        p_top, p_bot = bis[k - 2].end_price, bis[k - 1].end_price
        c_top, c_bot = bis[k].end_price, bis[k + 1].end_price
        n_top, n_bot = bis[k + 2].end_price, bis[k + 3].end_price
        if opts['feature_merge']:
            p_top, p_bot, c_top, c_bot, n_top, n_bot = _merge_triple(
                p_top, p_bot, c_top, c_bot, n_top, n_bot, -direction)
        if direction > 0:
            if c_top > p_top and c_top > n_top and c_bot > p_bot and c_bot > n_bot:
                return k
        else:
            if c_top < p_top and c_top < n_top and c_bot < p_bot and c_bot < n_bot:
                return k
        k += 2
    return -1


def _merge_triple(h1, l1, h2, l2, h3, l3, direction):
    def contains(ah, al, bh, bl):
        return (bh <= ah and bl >= al) or (bh >= ah and bl <= al)
    if contains(h1, l1, h2, l2):
        if direction < 0:
            h2, l2 = min(h1, h2), min(l1, l2)
        else:
            h2, l2 = max(h1, h2), max(l1, l2)
    if contains(h2, l2, h3, l3):
        if direction < 0:
            h3, l3 = min(h2, h3), min(l2, l3)
        else:
            h3, l3 = max(h2, h3), max(l2, l3)
    return h1, l1, h2, l2, h3, l3


def _find_seg_end_simple(bis: List[Bi], s: int) -> int:
    n = len(bis)
    direction = bis[s].direction
    k = s + 2
    while k < n:
        if k + 1 >= n:
            break
        if direction > 0:
            prev_low = bis[k - 1].end_price if k - 2 >= s else -math.inf
            if bis[k + 1].end_price < prev_low:
                return k
        else:
            prev_high = bis[k - 1].end_price if k - 2 >= s else math.inf
            if bis[k + 1].end_price > prev_high:
                return k
        k += 2
    return -1


# ------------------------------------------------------------------ 5. 中枢
def build_zhongshu(parts: List[Dict[str, float]], opts: Dict[str, Any]) -> List[Zhongshu]:
    zss: List[Zhongshu] = []
    need = max(2, opts['zs_min_parts'])
    i = 0
    while i + need - 1 < len(parts):
        window = parts[i:i + need]
        zd = max(p['low'] for p in window)
        zg = min(p['high'] for p in window)
        if zd >= zg:
            i += 1
            continue
        right = i + need - 1
        for k in range(right + 1, len(parts)):
            p = parts[k]
            if p['low'] < zg and p['high'] > zd:
                if opts['zs_extend_update']:
                    zg = min(zg, p['high'])
                    zd = max(zd, p['low'])
                right = k
            else:
                break
        zss.append(Zhongshu(zd, zg, i, right, right - i + 1,
                            parts[i]['start_k'], parts[right]['end_k']))
        # 关键：产生「离开中枢」动作的那个 part 不能算进下一个中枢，
        # 否则相邻中枢首尾相接，中间没有过渡走势。
        i = right + 2
    return zss


# ------------------------------------------------------------------ 6. 背驰
def extreme_k_index(klines: List[Dict[str, float]], a: int, b: int, field: str) -> int:
    if not klines:
        return b
    a, b = max(0, a), min(len(klines) - 1, b)
    key = (lambda k: k['h']) if field == 'high' else (lambda k: -k['l'])
    best_i, best_v = b, -math.inf
    for i in range(a, b + 1):
        v = key(klines[i])
        if math.isfinite(v) and v > best_v:
            best_v, best_i = v, i
    return best_i


def detect_divergence(parts: List[Dict[str, float]], zss: List[Zhongshu],
                      hist: List[float], klines: List[Dict[str, float]],
                      opts: Dict[str, Any]) -> List[Dict[str, Any]]:
    divs: List[Dict[str, Any]] = []
    if opts['div_mode'] == 'zs':
        return _div_by_zs(parts, zss, hist, klines, opts)
    # 默认：滚动三笔比较。中间那笔就是笔级别中枢。
    for i in range(len(parts) - 2):
        a, mid, c = parts[i], parts[i + 1], parts[i + 2]
        if a['dir'] != c['dir']:
            continue
        zd = max(a['low'], mid['low'], c['low'])
        zg = min(a['high'], mid['high'], c['high'])
        if zd >= zg:
            continue
        d = a['dir']
        made_new = c['high'] > a['high'] if d > 0 else c['low'] < a['low']
        if not made_new:
            continue
        fa = force_range(hist, a['start_k'], a['end_k'], d, opts['force_mode'])
        fc = force_range(hist, c['start_k'], c['end_k'], d, opts['force_mode'])
        ra = abs(a['end_price'] - a['start_price'])
        rc = abs(c['end_price'] - c['start_price'])
        if fa > 0 and fc > 0:
            ratio, basis = fc / fa, 'macd'
        elif opts['div_fallback_amplitude'] and ra > 0:
            ratio, basis = rc / ra, 'amplitude'
        else:
            continue
        if ratio < opts['div_min_force_ratio']:
            is_top = d > 0
            divs.append({
                'type': -1 if is_top else 1,
                'kind': 'top' if is_top else 'bottom',
                'target_k': extreme_k_index(klines, c['start_k'], c['end_k'],
                                            'high' if is_top else 'low'),
                'target_price': c['high'] if is_top else c['low'],
                'f_enter': fa if basis == 'macd' else ra,
                'f_leave': fc if basis == 'macd' else rc,
                'ratio': ratio, 'basis': basis})
    return divs


def _div_by_zs(parts, zss, hist, klines, opts):
    """严格趋势背驰：比较被同一个中枢隔开的前后两段连接走势。"""
    divs: List[Dict[str, Any]] = []
    bounds = []          # (conn_from, conn_to, zs) 三元组序列
    from_idx = 0
    for zs in zss:
        if zs.start_part > from_idx:
            bounds.append((from_idx, zs.start_part - 1, None))
        bounds.append((None, None, zs))
        from_idx = zs.end_part + 1
    if from_idx <= len(parts) - 1:
        bounds.append((from_idx, len(parts) - 1, None))

    for i in range(1, len(bounds) - 1):
        if bounds[i][2] is None:
            continue
        b0, b1 = bounds[i - 1], bounds[i + 1]
        if b0[0] is None or b1[0] is None:
            continue
        enter = _wave(parts, b0[0], b0[1])
        leave = _wave(parts, b1[0], b1[1])
        if not enter or not leave:
            continue
        d = 1 if enter['end_price'] > enter['start_price'] else -1
        if d != (1 if leave['end_price'] > leave['start_price'] else -1):
            continue
        made_new = leave['high'] > enter['high'] if d > 0 else leave['low'] < enter['low']
        if not made_new:
            continue
        fa = force_range(hist, enter['start_k'], enter['end_k'], d, opts['force_mode'])
        fc = force_range(hist, leave['start_k'], leave['end_k'], d, opts['force_mode'])
        ra = abs(enter['end_price'] - enter['start_price'])
        rc = abs(leave['end_price'] - leave['start_price'])
        if fa > 0 and fc > 0:
            ratio, basis = fc / fa, 'macd'
        elif opts['div_fallback_amplitude'] and ra > 0:
            ratio, basis = rc / ra, 'amplitude'
        else:
            continue
        if ratio < opts['div_min_force_ratio']:
            is_top = d > 0
            divs.append({
                'type': -1 if is_top else 1,
                'kind': 'top' if is_top else 'bottom',
                'target_k': extreme_k_index(klines, leave['start_k'], leave['end_k'],
                                            'high' if is_top else 'low'),
                'target_price': leave['high'] if is_top else leave['low'],
                'f_enter': fa if basis == 'macd' else ra,
                'f_leave': fc if basis == 'macd' else rc,
                'ratio': ratio, 'basis': basis})
    return divs


def _wave(parts, a, b):
    if a is None or b is None or b < a:
        return None
    return {
        'start_k': parts[a]['start_k'], 'end_k': parts[b]['end_k'],
        'start_price': parts[a]['start_price'], 'end_price': parts[b]['end_price'],
        'high': max(p['high'] for p in parts[a:b + 1]),
        'low': min(p['low'] for p in parts[a:b + 1]),
    }


# -------------------------------------------------------------- 7. 买卖点
def detect_points(parts, zss, divs, opts) -> List[Dict[str, Any]]:
    pts: List[Dict[str, Any]] = []

    def first_part_after(k):
        for i, p in enumerate(parts):
            if p['end_k'] >= k:
                return i
        return -1

    # 一类
    for d in divs:
        is_buy = d['type'] > 0
        if is_buy and not opts['show_buy']:
            continue
        if not is_buy and not opts['show_sell']:
            continue
        pts.append({'level': 1, 'type': d['type'], '_k': d['target_k'],
                    'price': d['target_price'],
                    'note': '一买·底背驰' if is_buy else '一卖·顶背驰'})

    # 三类：离开中枢后的第一次回抽不入中枢
    for z, zs in enumerate(zss):
        li = zs.end_part + 1
        if li >= len(parts):
            continue
        direction = parts[li]['dir']
        for j in range(li + 1, len(parts)):
            if parts[j]['dir'] == direction:
                continue
            p = parts[j]
            if direction > 0 and opts['show_buy'] and p['low'] > zs.zg:
                pts.append({'level': 3, 'type': 1, '_k': p['end_k'], 'price': p['low'],
                            'note': '三买·回抽不入中枢'})
            elif direction < 0 and opts['show_sell'] and p['high'] < zs.zd:
                pts.append({'level': 3, 'type': -1, '_k': p['end_k'], 'price': p['high'],
                            'note': '三卖·反抽不入中枢'})
            break

    # 二类：一类之后跳过反弹笔，看真正的回抽笔
    for d in divs:
        is_buy = d['type'] > 0
        if is_buy and not opts['show_buy']:
            continue
        if not is_buy and not opts['show_sell']:
            continue
        ri = first_part_after(d['target_k'])
        if ri < 0:
            continue
        ref_dir = parts[ri]['dir']
        for t in range(ri + 1, len(parts)):
            if parts[t]['dir'] != ref_dir:
                continue
            c = parts[t]
            if is_buy and c['low'] > d['target_price']:
                pts.append({'level': 2, 'type': 1, '_k': c['end_k'], 'price': c['low'],
                            'note': '二买·回抽不破前低'})
            elif not is_buy and c['high'] < d['target_price']:
                pts.append({'level': 2, 'type': -1, '_k': c['end_k'], 'price': c['high'],
                            'note': '二卖·反抽不破前高'})
            break
    return pts


# ------------------------------------------------------------------ 顶层入口
def analyze_klines(klines: List[Dict[str, float]],
                   user_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """klines: [{'t','o','h','l','c','v'}, ...]"""
    opts = _opts(user_opts)
    if not klines or len(klines) < 5:
        return {'klines': klines or [], 'merged': [], 'fractals': [], 'bis': [],
                'segs': [], 'zhongshus': [], 'divergences': [], 'points': [],
                'macd': None, 'opts': opts, 'stats': {}}

    merged = merge_klines(klines) if opts['merge'] else [
        {'high': float(k['h']), 'low': float(k['l']), 'si': i, 'ei': i}
        for i, k in enumerate(klines)]

    fractals = dedup_fractals(find_fractals(merged))
    bis = build_bi(fractals, opts)
    segs = build_segments(bis, opts)

    def to_part(x):
        return {'dir': x.direction, 'start_k': x.start_k, 'end_k': x.end_k,
                'high': x.high, 'low': x.low,
                'start_price': x.start_price, 'end_price': x.end_price}

    parts = ([to_part(b) for b in bis] if opts['zs_source'] == 'bi'
             else [to_part(s) for s in segs])
    zss = build_zhongshu(parts, opts)

    closes = [float(k['c']) for k in klines]
    mac = macd(closes, opts['macd_fast'], opts['macd_slow'], opts['macd_signal'])
    point_parts = parts if opts['points_on_segs'] else [
        {'dir': b.direction, 'start_k': b.start_k, 'end_k': b.end_k,
         'high': b.high, 'low': b.low,
         'start_price': b.start_price, 'end_price': b.end_price} for b in bis]
    divs = detect_divergence(point_parts, zss, mac['hist'], klines, opts)
    pts = detect_points(parts, zss, divs, opts)
    last_k = len(klines) - 1
    for p in pts:
        p['confirmed'] = (last_k - p['_k']) >= 3

    return {
        'klines': klines, 'merged': merged, 'fractals': fractals,
        'bis': bis, 'segs': segs, 'parts': parts, 'zhongshus': zss,
        'divergences': divs, 'points': pts, 'macd': mac, 'opts': opts,
        'stats': {
            'n': len(klines), 'merged': len(merged), 'fx': len(fractals),
            'bi': len(bis), 'seg': len(segs), 'zs': len(zss),
            'div': len(divs), 'point': len(pts),
            'last_close': closes[-1],
        },
    }


# ------------------------------------------------------------- DataFrame 入口
_COL_MAPS = [
    {'o': '开盘', 'c': '收盘', 'h': '最高', 'l': '最低', 't': '日期', 'v': '成交量'},
    {'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'date', 'v': 'volume'},
]


def analyze_df(df, user_opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """接受 pandas.DataFrame（fetch.astock_data 的中文列名或英文列名均可）。"""
    cols = None
    for m in _COL_MAPS:
        if m['o'] in df.columns and m['c'] in df.columns:
            cols = m
            break
    if cols is None:
        raise ValueError('DataFrame 缺少 开盘/收盘/最高/最低 列: %s' % list(df.columns))

    klines = []
    for _, row in df.iterrows():
        klines.append({
            't': str(row[cols['t']]) if cols['t'] in df.columns else '',
            'o': float(row[cols['o']]), 'c': float(row[cols['c']]),
            'h': float(row[cols['h']]), 'l': float(row[cols['l']]),
            'v': float(row[cols['v']]) if cols['v'] in df.columns else 0.0,
        })
    return analyze_klines(klines, user_opts)
