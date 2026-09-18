# -*- coding: utf-8 -*-
"""Python 引擎的未来函数检测（与 tools/walkforward.js 同一口径）。

回测用的是 python/chan_engine.py，光验证 JS 版没有意义。
本脚本做两件事：
  1. 滚动推进比对：截止 T 算出的第 j 个结构，必须与全量算出的第 j 个完全一致
     （每层最后一个元素属于待确认区，豁免）
  2. 与 JS 引擎交叉核对：同一份数据、同一参数，两边结构数量必须相同
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
import chan_engine as ce

DIR = os.path.join(os.path.dirname(__file__), 'testdata')
DATASETS = ['600519_daily.json', '000001_daily.json', '300750_daily.json', '600519_30m.json']


def load(fn):
    with open(os.path.join(DIR, fn), 'r', encoding='utf-8') as f:
        j = json.load(f)
    return j.get('klines', j)


def r(v):
    return ('%.6f' % v) if isinstance(v, (int, float)) else str(v)


def key_bi(b):
    return '|'.join([str(b.start_k), str(b.end_k), str(b.direction), r(b.start_price), r(b.end_price)])


def key_seg(s):
    return '|'.join([str(s.start_k), str(s.end_k), str(s.direction), r(s.start_price), r(s.end_price)])


def key_zs(z):
    return '|'.join([str(z.start_part), str(z.end_part), r(z.zd), r(z.zg), str(z.part_count)])


def cmp_layer(name, cut_list, full_list, kf, keep_tail=1):
    limit = len(cut_list) - keep_tail
    bad = []
    for j in range(max(0, limit)):
        a = kf(cut_list[j])
        b = kf(full_list[j]) if j < len(full_list) else '<MISSING>'
        if a != b and len(bad) < 3:
            bad.append('%s[%d] cut=%s full=%s' % (name, j, a, b))
    return bad


print('=' * 66)
print(' Python 引擎 未来函数检测（chan_engine.analyze_df）')
print('=' * 66)

total_bad = 0
for fn in DATASETS:
    try:
        klines = load(fn)
    except Exception as e:
        print('  %s 读取失败: %s' % (fn, e))
        continue

    res_full = ce.analyze_klines(klines, {})

    bad_cnt, cases = 0, []
    cuts = list(range(120, len(klines) + 1, 10)) + [len(klines) - 1, len(klines) - 2]
    for cut in cuts:
        if cut < 60 or cut > len(klines):
            continue
        try:
            res_cut = ce.analyze_klines(klines[:cut], {})
        except Exception as e:
            cases.append('cut=%d 抛出异常 %s' % (cut, e))
            bad_cnt += 1
            continue
        local_bad = []
        local_bad += cmp_layer('笔', res_cut['bis'], res_full['bis'], key_bi)
        local_bad += cmp_layer('线段', res_cut['segs'], res_full['segs'], key_seg)
        local_bad += cmp_layer('中枢', res_cut['zhongshus'], res_full['zhongshus'], key_zs)
        if local_bad:
            bad_cnt += len(local_bad)
            if len(cases) < 4:
                cases.append('  cut=%d %s' % (cut, local_bad[0]))

    total_bad += bad_cnt
    stat = res_full.get('stats', {})
    print('  %-20s n=%4d 切点%3d个  %s   全量: 笔%s 段%s 中枢%s 背驰%s'
          % (fn, len(klines), len(cuts),
             ('✅ 无重绘' if bad_cnt == 0 else '❌ %d 处重绘' % bad_cnt),
             stat.get('bi'), stat.get('seg'),
             stat.get('zs'), stat.get('div')))
    for c in cases:
        print('     ' + c)

print('=' * 66)
# —— 交叉核对：Python 必须和 JS 给出完全相同的结构数 ——
print(' 与 JS 引擎交叉核对（笔/线段/中枢/背驰数量必须一致）：')
node = os.environ.get('NODE_EXE')
if node:
    import subprocess
    for fn in DATASETS:
        klines = load(fn)
        with_ = subprocess.run([node, '-e', '''
const Chan=require("%s");
const fs=require("fs");
const j=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));
const k=j.klines||j;
const r=Chan.analyze(k,{});
console.log(JSON.stringify({bi:r.bis.length,seg:r.segs.length,zs:r.zhongshus.length,div:r.divergences.length,pt:r.points.length}));
''' % os.path.join(os.path.dirname(__file__), '..', 'core', 'chan.js').replace('\\', '/'),
            os.path.join(DIR, fn)], capture_output=True, text=True)
        if with_.returncode != 0:
            print('     %s JS 执行失败' % fn)
            continue
        js = json.loads(with_.stdout.strip())
        py = ce.analyze_klines(klines, {})
        same = (js['bi'] == len(py['bis']) and js['seg'] == len(py['segs'])
                and js['zs'] == len(py['zhongshus']) and js['div'] == len(py['divergences']))
        print('     %-20s JS=%s  PY=笔%s 段%s 中枢%s 背驰%s  %s'
              % (fn, '笔%d 段%d 中枢%d 背驰%d' % (js['bi'], js['seg'], js['zs'], js['div']),
                 len(py['bis']), len(py['segs']), len(py['zhongshus']), len(py['divergences']),
                 '✅ 一致' if same else '❌ 不一致'))
else:
    print('     （未设置 NODE_EXE，跳过交叉核对）')

print('=' * 66)
print('结论：' + ('Python 引擎同样无未来函数。' if total_bad == 0 else 'Python 引擎发现 %d 处重绘。' % total_bad))
print('=' * 66)
