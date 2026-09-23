"""
腾讯行情链路引入的两类脏数据修复（2026-09-21 起）：

A. 成交量放大 100 倍
   腾讯对科创板 688/689 返回的成交量单位是「股」，其余板块是「手」；
   直接落库使科创板成交量放大 100 倍，导致作图比例失调。
   实测 2026-09-23 全量 5556 只有效行情：617 只科创板 100% 为「股」，其余 100% 为「手」。

B. 占位行（垃圾行）
   腾讯对已停更/退市/长期停牌的代码返回占位行情：价=昨收，开/高/低/量/额全 0，
   行情时间固定 09:00:00。实测北交所旧代码段 43/83/87/81（已迁至 920 段）全部如此。
   这类行写入 CSV 后既污染数据又拉平图表。

判定方式（不依赖日期、不依赖代码前缀硬编码）：
    成交额 / 成交量 落在当日 [最低, 最高] 区间内 -> 该列存的是股数，需 /100 折算；
    反之 成交额 / (成交量*100) 落在区间内 -> 已是手，保持不动。
    两者都不成立记为 anomaly（历史前复权数据即属此类），只报告不修改。

用法：
    python dev/fix_tencent_bad_data.py                 # dry-run
    python dev/fix_tencent_bad_data.py --apply         # 备份后写入（折算 + 删占位行）
    python dev/fix_tencent_bad_data.py --no-prune      # 只折算、不删占位行
"""

import argparse
import glob
import io
import os
import shutil
import sys
import time
from collections import Counter

ASTOCK_DIR = r'D:\Trading\data\astocks'
BACKUP_DIR = r'D:\Trading\data\astocks_backup_20260923'

# CSV 列序（无表头）：日期,代码,今开,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
IDX = {'date': 0, 'code': 1, 'open': 2, 'close': 3, 'high': 4, 'low': 5,
       'volume': 6, 'amount': 7}


def classify(parts):
    """返回 ('share'|'lot'|'anomaly', info)；share 表示该行成交量存的是股数。"""
    try:
        high = float(parts[IDX['high']])
        low = float(parts[IDX['low']])
        vol = float(parts[IDX['volume']])
        amount = float(parts[IDX['amount']])
    except (ValueError, IndexError):
        return 'anomaly', None
    if vol <= 0 or amount <= 0 or low <= 0 or high <= 0:
        return 'anomaly', None
    if low <= amount / vol <= high:
        return 'share', (vol, amount)
    if low <= amount / (vol * 100.0) <= high:
        return 'lot', (vol, amount)
    return 'anomaly', (vol, amount)


def is_placeholder(parts):
    """腾讯占位行：价=昨收，开/高/低/量/额全 0。"""
    try:
        o, c = float(parts[IDX['open']]), float(parts[IDX['close']])
        h, lo = float(parts[IDX['high']]), float(parts[IDX['low']])
        v, a = float(parts[IDX['volume']]), float(parts[IDX['amount']])
    except (ValueError, IndexError):
        return False
    return c > 0 and o == 0 and h == 0 and lo == 0 and v == 0 and a == 0


def fmt_volume(v):
    half = v / 100.0
    return str(int(half)) + '.0' if abs(half - int(half)) < 1e-9 else repr(half)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='备份后实际写入')
    ap.add_argument('--no-prune', action='store_true', help='只做成交量折算，不删占位行')
    ap.add_argument('--only-date-prefix', default='2026-09-',
                    help='仅处理该日期前缀之后的行，默认 2026-09-')
    args = ap.parse_args()

    if args.apply and not os.path.isdir(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    t0 = time.time()
    files = sorted(glob.glob(os.path.join(ASTOCK_DIR, '*.csv')))
    fix_files, prune_files = set(), set()
    fix_rows = 0
    prune_rows = 0
    anomalies = []
    scanned = 0

    for fp in files:
        name = os.path.basename(fp)
        text = io.open(fp, encoding='utf-8', errors='replace', newline='').read()
        out, dirty = [], False
        for line in text.split('\n'):
            if not line.strip():
                out.append(line)
                continue
            parts = line.split(',')
            if len(parts) < 12:
                out.append(line)
                continue
            scanned += 1
            if parts[IDX['date']] < args.only_date_prefix:
                out.append(line)
                continue
            if not args.no_prune and is_placeholder(parts):
                prune_rows += 1
                prune_files.add(name)
                dirty = True
                continue
            kind, info = classify(parts)
            if kind == 'share':
                parts[IDX['volume']] = fmt_volume(info[0])
                line = ','.join(parts)
                fix_rows += 1
                fix_files.add(name)
                dirty = True
            elif kind == 'anomaly':
                anomalies.append((name, parts[IDX['date']], parts[IDX['volume']]))
            out.append(line)

        if dirty:
            if args.apply:
                shutil.copy2(fp, os.path.join(BACKUP_DIR, name))
                with io.open(fp, 'w', encoding='utf-8', newline='') as fh:
                    fh.write('\n'.join(out))

    print('扫描文件 %d / 数据行 %d，耗时 %.1fs' % (len(files), scanned, time.time() - t0))
    print('A 成交量 股->手 : 文件 %d / 行 %d' % (len(fix_files), fix_rows))
    print('B 占位行删除    : 文件 %d / 行 %d' % (len(prune_files), prune_rows))
    print('anomaly(未改动) : 行 %d' % len(anomalies))
    for a in anomalies[:10]:
        print('    ', a)
    if args.apply:
        print('已写入；原文件备份于 %s' % BACKUP_DIR)
    else:
        print('dry-run 结束（未写入），加 --apply 执行。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
