#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
评估历史日线数据源：Baostock / 腾讯 / 新浪 / 东财(对照)。
对比字段能否映射到 astock_data 标准 12 列。

用法:
  conda activate trading
  python tests/eval_hist_sources.py
  python tests/eval_hist_sources.py --code 300787 --start 20250930
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGET_COLS = ['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
               '振幅', '涨跌幅', '涨跌额', '换手率']


def _fmt_date(s: str) -> str:
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _calc_amplitude(row) -> float:
    low, high = float(row['最低']), float(row['最高'])
    if low == 0:
        return 0.0
    return round((high - low) / low * 100, 2)


def _to_standard(df: pd.DataFrame, stock_code: str, source: str) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    out = pd.DataFrame()
    if source == 'baostock':
        out['日期'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        out['股票代码'] = stock_code
        out['开盘'] = pd.to_numeric(df['open'], errors='coerce')
        out['收盘'] = pd.to_numeric(df['close'], errors='coerce')
        out['最高'] = pd.to_numeric(df['high'], errors='coerce')
        out['最低'] = pd.to_numeric(df['low'], errors='coerce')
        out['成交量'] = pd.to_numeric(df['volume'], errors='coerce')
        out['成交额'] = pd.to_numeric(df['amount'], errors='coerce')
        out['涨跌幅'] = pd.to_numeric(df['pctChg'], errors='coerce')
        out['涨跌额'] = out['收盘'].diff()
        out.loc[out.index[0], '涨跌额'] = 0
        out['换手率'] = pd.to_numeric(df['turn'], errors='coerce')
        out['振幅'] = out.apply(_calc_amplitude, axis=1)
    elif source == 'tencent':
        # 腾讯列 amount 实际为成交量(手)，无成交额/换手率
        out['日期'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        out['股票代码'] = stock_code
        for src, dst in [('open', '开盘'), ('close', '收盘'), ('high', '最高'), ('low', '最低')]:
            out[dst] = pd.to_numeric(df[src], errors='coerce')
        out['成交量'] = pd.to_numeric(df['amount'], errors='coerce')
        out['成交额'] = 0  # 腾讯源不提供，需估算或留空
        if '涨跌幅' in df.columns:
            out['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
        else:
            out['涨跌幅'] = out['收盘'].pct_change() * 100
        out['涨跌额'] = out['收盘'].diff().fillna(0)
        out['换手率'] = pd.to_numeric(df['turnover'], errors='coerce') if 'turnover' in df.columns else 0
        if '振幅' in df.columns:
            out['振幅'] = pd.to_numeric(df['振幅'], errors='coerce')
        else:
            out['振幅'] = out.apply(_calc_amplitude, axis=1)
    elif source == 'sina':
        out['日期'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        out['股票代码'] = stock_code
        for src, dst in [('open', '开盘'), ('close', '收盘'), ('high', '最高'), ('low', '最低'),
                         ('amount', '成交额')]:
            out[dst] = pd.to_numeric(df[src], errors='coerce')
        # 新浪 volume 单位为股，本地 CSV 为手
        out['成交量'] = pd.to_numeric(df['volume'], errors='coerce') / 100
        out['涨跌幅'] = out['收盘'].pct_change() * 100
        out['涨跌额'] = out['收盘'].diff().fillna(0)
        if 'turnover' in df.columns:
            out['换手率'] = pd.to_numeric(df['turnover'], errors='coerce') * 100
        else:
            out['换手率'] = 0
        out['振幅'] = out.apply(_calc_amplitude, axis=1)
    elif source == 'eastmoney':
        out = df.copy()
        out['日期'] = pd.to_datetime(out['日期']).dt.strftime('%Y-%m-%d')
        out['股票代码'] = stock_code
    else:
        raise ValueError(source)
    return out[TARGET_COLS]


def fetch_baostock(code: str, start: str, end: str | None) -> tuple[str, pd.DataFrame | None, str]:
    prefix = 'sh' if code.startswith('6') else 'sz'
    if code.startswith('92'):
        prefix = 'bj'  # 北交所尝试
    bs_code = f"{prefix}.{code}"
    end_date = end or time.strftime('%Y-%m-%d')
    start_date = _fmt_date(start)
    lg = bs.login()
    if lg.error_code != '0':
        return 'baostock', None, f"login失败: {lg.error_msg}"
    try:
        fields = "date,code,open,high,low,close,volume,amount,turn,pctChg"
        rs = bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=start_date, end_date=end_date,
            frequency='d', adjustflag='2',  # 前复权
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        if rs.error_code != '0':
            return 'baostock', None, f"query失败: {rs.error_msg}"
        if not rows:
            return 'baostock', None, '返回空数据'
        df = pd.DataFrame(rows, columns=rs.fields)
        return 'baostock', df, 'ok(证券宝官方API,前复权adjustflag=2)'
    finally:
        bs.logout()


def fetch_tencent(code: str, start: str, end: str | None) -> tuple[str, pd.DataFrame | None, str]:
    sym = f"sh{code}" if code.startswith('6') else f"sz{code}"
    end_date = end or time.strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date=end_date, adjust='qfq')
        if df is None or df.empty:
            return 'tencent', None, '返回空'
        return 'tencent', df, 'ok(akshare→腾讯财经HTTP)'
    except Exception as e:
        return 'tencent', None, str(e)


def _sina_symbol(code: str) -> str:
    if code.startswith('6'):
        return f"sh{code}"
    if code.startswith('92'):
        return f"bj{code}"
    return f"sz{code}"


def fetch_sina(code: str, start: str, end: str | None) -> tuple[str, pd.DataFrame | None, str]:
    sym = _sina_symbol(code)
    end_date = end or time.strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end_date, adjust='qfq')
        if df is None or df.empty:
            return 'sina', None, '返回空'
        return 'sina', df, str(e) if False else 'ok(akshare→新浪财经HTTP)'
    except Exception as e:
        return 'sina', None, str(e)


def fetch_eastmoney(code: str, start: str, end: str | None) -> tuple[str, pd.DataFrame | None, str]:
    end_date = end or time.strftime('%Y%m%d')
    try:
        df = ak.stock_zh_a_hist(symbol=code, start_date=start, end_date=end_date, adjust='qfq')
        if df is None or df.empty:
            return 'eastmoney', None, '返回空'
        return 'eastmoney', df, 'ok(akshare→东财push2his,当前可能被限流)'
    except Exception as e:
        return 'eastmoney', None, str(e)


def load_local_tail(code: str) -> dict | None:
    astocks = ROOT / 'data' / 'astocks'
    for fp in astocks.glob(f'{code}_*.csv'):
        try:
            raw = fp.read_bytes()[:4096]
            if raw and all(b == 0 for b in raw[:min(len(raw), 512)]):
                continue
            df = pd.read_csv(fp, header=None, names=TARGET_COLS, dtype={'股票代码': str})
            valid = df.dropna(subset=['日期'])
            if len(valid) >= 2:
                row = valid.iloc[-2]
                return {c: row[c] for c in TARGET_COLS}
        except Exception:
            continue
    return None


def eval_one(code: str, start: str, end: str | None) -> None:
    print('=' * 70)
    print(f'股票 {code}  start={start}  end={end or "today"}')
    print('=' * 70)

    ref = load_local_tail(code)
    if ref:
        print(f'本地参考(损坏文件邻居/同板块正常文件最后一行前一日): {ref}')
    else:
        print('本地无可用参考行(可能该代码文件已损坏)')

    fetchers = [
        ('Baostock', fetch_baostock),
        ('腾讯', fetch_tencent),
        ('新浪', fetch_sina),
        ('东财(对照)', fetch_eastmoney),
    ]

    for label, fn in fetchers:
        t0 = time.time()
        source_key, raw, msg = fn(code, start, end)
        elapsed = time.time() - t0
        print(f'\n--- {label} [{elapsed:.1f}s] ---')
        print(f'状态: {msg}')
        if raw is None:
            continue
        print(f'原始列: {list(raw.columns)}')
        print(f'原始行数: {len(raw)}')
        std = _to_standard(raw, code, source_key)
        if std is None or std.empty:
            print('标准化失败')
            continue
        print(f'标准化后末3行:\n{std.tail(3).to_string(index=False)}')
        missing = [c for c in TARGET_COLS if std[c].isna().all()]
        if missing:
            print(f'警告: 以下列全空 {missing}')
        if ref and len(std) >= 1:
            # 找 ref 日期附近对比
            ref_date = str(ref['日期'])[:10]
            match = std[std['日期'] == ref_date]
            if not match.empty:
                m = match.iloc[0]
                diffs = []
                for c in ['开盘', '收盘', '最高', '最低', '涨跌幅']:
                    try:
                        lv, rv = float(ref[c]), float(m[c])
                        if abs(lv - rv) > max(0.02, abs(lv) * 0.001):
                            diffs.append(f'{c}: local={lv} vs {label}={rv}')
                    except (TypeError, ValueError):
                        pass
                if diffs:
                    print('与本地参考差异:', '; '.join(diffs))
                else:
                    print(f'与本地 {ref_date} 收盘价等核心字段基本一致')
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--code', default='300787', help='6位股票代码')
    parser.add_argument('--start', default='20250930')
    parser.add_argument('--end', default=None, help='YYYYMMDD，默认今天')
    parser.add_argument('--codes', default=None, help='逗号分隔批量 smoke test')
    args = parser.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
        ok, fail = [], []
        for i, code in enumerate(codes):
            print(f'\n>>> smoke {i+1}/{len(codes)} {code}')
            _, raw, msg = fetch_baostock(code, args.start, args.end)
            status = 'OK' if raw is not None and not raw.empty else f'FAIL:{msg}'
            print(f'  baostock: {status} rows={0 if raw is None else len(raw)}')
            (ok if raw is not None and not raw.empty else fail).append(code)
            time.sleep(0.3)
        print(f'\nBaostock batch: ok={len(ok)} fail={len(fail)}')
        if fail:
            print('failed:', fail)
        return

    eval_one(args.code, args.start, args.end)


if __name__ == '__main__':
    main()
