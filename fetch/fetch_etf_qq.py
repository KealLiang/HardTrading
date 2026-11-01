# -*- coding: utf-8 -*-
"""腾讯 ifzq 日线抓取（前复权），用于补充 ETF 池。

东财 push2his 已被 WAF 封锁（RemoteDisconnected / 空 data），腾讯可用：
  https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh510050,day,,,640,qfq
  单次上限 640 根 → 按 end 日向前滚分页，拼接去重。
已验证：腾讯 qfq 与本地 akshare/东财 qfq 同日期价格完全一致（510300 2026-09-28~30），
       相邻分页边界日价格也完全一致。

输出列：日期,开盘,收盘,最高,最低,成交量  （lib.js parseCsv 只要求前五列）
用法：
  python fetch_etf_qq.py --verify            # 只验证 510300 与本地一致性
  python fetch_etf_qq.py --codes 510050,...  # 拉指定代码
  python fetch_etf_qq.py --all               # 拉 EXT 清单全部
"""
import os, sys, json, time, ssl, argparse, datetime

for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ[k] = ''
os.environ['NO_PROXY'] = '*'

import urllib.request

OUT = 'D:/Trading/data/etfs'
HDRS = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Referer': 'https://gu.qq.com/',
}

# 新增候选（行业/概念代表性，与现有 26 只不重复）
EXT = [
    '510050',  # 上证50        —— 大盘价值
    '510500',  # 中证500        —— 中盘
    '512100',  # 中证1000       —— 小盘
    '588000',  # 科创50         —— 科创板
    '512010',  # 医药           —— 医药生物
    '512170',  # 医疗           —— 医疗器械/服务
    '512400',  # 有色           —— 有色/锂/铜
    '512070',  # 非银           —— 保险+券商
    '512690',  # 酒             —— 白酒
    '159920',  # 恒生           —— 港股宽基
    '513100',  # 纳指           —— 美股科技
    '513500',  # 标普500        —— 美股宽基
    '515210',  # 钢铁           —— 钢铁周期
    '159996',  # 家电           —— 家电
    '516160',  # 新能源         —— 光伏/风电/储能
    '159611',  # 电力           —— 公用事业
    '516970',  # 基建           —— 建筑/基建
    '159865',  # 养殖           —— 农业养殖
]

SSL = ssl.create_default_context()
SSL.check_hostname = False
SSL.verify_mode = ssl.CERT_NONE


def sym(code):
    return ('sh' if code[0] in '56' else 'sz') + code


def qq(code, end=None, n=640, retries=4):
    s = sym(code)
    if end:
        param = '%s,day,1990-01-01,%s,%d,qfq' % (s, end, n)
    else:
        param = '%s,day,,,%d,qfq' % (s, n)
    url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + param
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=H)
            with urllib.request.urlopen(req, timeout=25, context=SSL) as r:
                j = json.loads(r.read().decode('utf-8'))
            d = (j.get('data') or {}).get(s) or {}
            rows = d.get('qfqday') or d.get('day') or []
            return rows
        except Exception as e:
            print('   retry %d %s: %s' % (i + 1, code, str(e)[:60]), flush=True)
            time.sleep(2 + 2 * i)
    return []


def fetch_all(code, max_page=20):
    rows = []
    end = None
    for page in range(max_page):
        seg = qq(code, end)
        if not seg:
            break
        rows = seg + rows
        if len(seg) < 640:
            break                      # 已到上市首日
        earliest = seg[0][0]
        d = datetime.date.fromisoformat(earliest) - datetime.timedelta(days=1)
        newend = d.isoformat()
        if end and newend >= end:
            break
        end = newend
        time.sleep(0.8)
    # 去重 + 升序
    seen, uniq = set(), []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        uniq.append(r)
    uniq.sort(key=lambda r: r[0])
    return uniq


def save(code, rows):
    p = os.path.join(OUT, code + '.csv')
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(HDRS) + '\n')
        for r in rows:
            f.write('%s,%s,%s,%s,%s,%s\n' % (r[0], r[1], r[2], r[3], r[4], r[5]))
    return p


def verify():
    rows = fetch_all('510300')
    print('腾讯 510300 根数', len(rows), rows[0][0], '~', rows[-1][0])
    loc = {}
    with open(os.path.join(OUT, '510300.csv'), encoding='utf-8') as f:
        next(f)
        for line in f:
            c = line.strip().split(',')
            if c and c[0]:
                loc[c[0]] = c
    common = [r for r in rows if r[0] in loc]
    print('重叠交易日', len(common))
    diff = 0
    worst = 0.0
    for r in common:
        tq = [float(r[1]), float(r[2]), float(r[3]), float(r[4])]
        lo = [float(loc[r[0]][1]), float(loc[r[0]][2]), float(loc[r[0]][3]), float(loc[r[0]][4])]
        for a, b in zip(tq, lo):
            if abs(a - b) > 1e-6:
                diff += 1
                worst = max(worst, abs(a - b) / max(b, 1e-9))
                break
    print('价格不一致天数 %d / %d，最大相对偏差 %.4f%%' % (diff, len(common), worst * 100))
    only_local = sorted(set(loc) - set(r[0] for r in rows))
    print('本地有腾讯无:', len(only_local), only_local[:3], only_local[-3:] if only_local else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--codes', default='')
    a = ap.parse_args()
    if a.verify:
        verify()
        return
    codes = EXT if a.all else [c for c in a.codes.split(',') if c]
    if not codes:
        print('nothing to do')
        return
    for code in codes:
        rows = fetch_all(code)
        if not rows:
            print('%-7s FAIL' % code, flush=True)
            continue
        save(code, rows)
        print('%-7s bars=%-5d %s ~ %s' % (code, len(rows), rows[0][0], rows[-1][0]), flush=True)
        time.sleep(1.0)
    print('DONE', len(codes))


if __name__ == '__main__':
    main()
