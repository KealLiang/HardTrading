import os
import logging
from datetime import datetime
from typing import List, Tuple

import pandas as pd
import akshare as ak


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _try_fetch_pre_minutes(code: str, date_str: str) -> pd.DataFrame:
    """
    优先使用 AkShare 盘前分钟接口；若不可用则回退到普通分钟接口并过滤 09:30 前数据。
    返回包含至少 ['时间','开盘','收盘','最高','最低','成交量','成交额'] 的 DataFrame。
    """
    df = None
    # 1) 优先尝试盘前分钟接口（包含 9:15-9:25）
    try:
        df = ak.stock_zh_a_hist_pre_min_em(symbol=code, start_date=date_str, end_date=date_str)
    except Exception:
        df = None
    # 2) 回退到普通分钟接口，某些版本也会返回 09:30 前数据（不保证）
    if df is None or df is pd.DataFrame() or (hasattr(df, 'empty') and df.empty):
        try:
            df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', start_date=date_str, end_date=date_str, adjust='')
            if df is not None and not df.empty:
                # 仅保留 09:30 之前的数据
                df = df[df['时间'].str.slice(11, 16) < '09:30']
        except Exception:
            df = None
    return df


def _pick_times_rows(df: pd.DataFrame, times: List[str]) -> pd.DataFrame:
    """从分钟DF中抽取指定时刻(精确分钟)的行，times 形如 ['09:15', '09:20', '09:25']"""
    if df is None or df.empty:
        return pd.DataFrame()
    # 兼容列名
    time_col = '时间' if '时间' in df.columns else ('datetime' if 'datetime' in df.columns else None)
    amount_col = '成交额' if '成交额' in df.columns else ('amount' if 'amount' in df.columns else None)
    if time_col is None:
        return pd.DataFrame()
    out = []
    for t in times:
        # 精确匹配到分钟
        sel = df[df[time_col].astype(str).str.contains(f" {t}:")]
        if not sel.empty:
            # 取该分钟最后一条（保险起见）
            row = sel.iloc[-1].copy()
            row['__pick_time__'] = t
            if amount_col and amount_col not in row:
                # 兼容没有成交额列
                row[amount_col or '成交额'] = None
            out.append(row)
    if out:
        return pd.DataFrame(out)
    return pd.DataFrame()


def fetch_market_call_auction_snapshot(date_str: str = None,
                                       top_n: int = 200,
                                       output_dir: str = 'data/jjdatas') -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Demo：抓取全市场（前 top_n 只）9:15/9:20/9:25 的集合竞价分钟快照并做简单汇总。

    - 汇总指标（按分钟）:
      * 亿字以上家数: 成交额 >= 1e8 的股票数量（近似定义，仅为 Demo）
      * 最大成交额: 该分钟的最大成交额
      * 最大成交个股: 达到最大成交额的股票（代码-名称）
    - 明细: code,name,时间(分钟),成交量,成交额...

    返回: (summary_df, detail_df)，并各自保存为 CSV 到 output_dir。
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    _ensure_dir(output_dir)

    # 市场列表
    spot = ak.stock_zh_a_spot_em()
    codes = spot['代码'].tolist()[:top_n]
    name_map = dict(zip(spot['代码'], spot['名称']))

    want_times = ['09:15', '09:20', '09:25']
    detail_rows = []

    for code in codes:
        try:
            df = _try_fetch_pre_minutes(code, date_str)
            pick = _pick_times_rows(df, want_times)
            if pick is None or pick.empty:
                continue
            for _, r in pick.iterrows():
                detail_rows.append({
                    'code': code,
                    'name': name_map.get(code, ''),
                    'time': r.get('__pick_time__'),
                    '成交量': r.get('成交量') or r.get('vol') or None,
                    '成交额': r.get('成交额') or r.get('amount') or None,
                })
        except Exception as e:
            logging.debug(f"{code} 获取盘前分钟失败: {e}")
            continue

    if not detail_rows:
        logging.warning('未获取到任何集合竞价分钟数据（免费源可能不保留历史竞价或被风控）。')
        return pd.DataFrame(), pd.DataFrame()

    detail_df = pd.DataFrame(detail_rows)

    # 汇总（按分钟）
    def _agg(group: pd.DataFrame):
        group = group.copy()
        group['成交额'] = pd.to_numeric(group['成交额'], errors='coerce')
        yizhi_count = int((group['成交额'] >= 1e8).sum())
        max_amt = group['成交额'].max()
        max_row = group.loc[group['成交额'].idxmax()] if pd.notna(max_amt) else None
        return pd.Series({
            '亿字以上家数': yizhi_count,
            '最大成交额': float(max_amt) if pd.notna(max_amt) else None,
            '最大成交个股': f"{max_row['code']}-{max_row['name']}" if max_row is not None else None,
        })

    summary_df = detail_df.groupby('time', as_index=False).apply(_agg)

    # 保存
    base = os.path.join(output_dir, f"{date_str}")
    summary_path = f"{base}_auction_summary.csv"
    detail_path = f"{base}_auction_detail.csv"
    summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
    detail_df.to_csv(detail_path, index=False, encoding='utf-8-sig')

    logging.info(f"已保存: {summary_path}, {detail_path}")
    return summary_df, detail_df


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    fetch_market_call_auction_snapshot()

