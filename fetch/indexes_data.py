import os
from datetime import datetime

import akshare as ak
import pandas as pd
import requests


def fetch_and_save_index_data(symbol, save_path):
    """
    获取指定指数的历史行情数据并保存为CSV文件。
    如果文件已存在，则从最新的日期处追加更新，不存储表头。

    :param symbol: 指数代码，如 'sh000001' 表示上证指数
    :param save_path: 保存CSV文件的路径
    """
    # 确保保存路径存在
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 检查文件是否存在
    if os.path.exists(save_path):
        # 如果文件存在，读取现有数据
        existing_data = pd.read_csv(save_path, header=None, names=['date', 'open', 'high', 'low', 'close', 'volume'])
        last_date = existing_data['date'].max()
        # 获取全部数据
        all_data = ak.stock_zh_index_daily(symbol=symbol)
        # 筛选出新的数据
        new_data = all_data[all_data['date'] > pd.to_datetime(last_date).date()]
        # 如果有新数据，则追加
        if not new_data.empty:
            updated_data = pd.concat([existing_data, new_data], ignore_index=True)
            # 保存更新后的数据，不包含表头
            updated_data.to_csv(save_path, index=False, header=False)
            print(f"Data for {symbol} updated to {save_path}")
        else:
            print(f"No new data for {symbol}.")
    else:
        # 如果文件不存在，获取全部数据
        index_data = ak.stock_zh_index_daily(symbol=symbol)
        # 保存数据到CSV文件，不包含表头
        index_data.to_csv(save_path, index=False, header=False)
        print(f"Data for {symbol} saved to {save_path}")


# 指数代码 → 6列行情CSV文件名（sina格式：date,open,high,low,close,volume，无表头）
INDEX_FILES = {
    "sh000001": "sh000001_上证指数.csv",
    "sz399001": "sz399001_深证成指.csv",
    "sz399006": "sz399006_创业板指.csv",
    "sh000688": "sh000688_科创50.csv",
    "bj899050": "bj899050_北证50.csv",
    "sh000905": "sh000905_中证500.csv",
    "sz399405": "sz399405_大盘高贝.csv",
    "sz399409": "sz399409_小盘高贝.csv",
    "sh000065": "sh000065_上证龙头.csv",
    "sz399653": "sz399653_深证龙头.csv",
}

# 由东财一次请求同时产出6列行情与成交额的指数（secid：沪市前缀1，深市前缀0）
AMOUNT_INDICES = {
    'sh000001': '1.000001',
    'sz399001': '0.399001',
}

AMOUNT_HISTORY_START = '20150101'  # 首次落地的历史起点

EM_KLINE_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
EM_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    'Referer': 'https://quote.eastmoney.com/',
}


def _fetch_em_klines(secid, beg, end):
    """
    调用东方财富K线API获取日线数据。
    不走 akshare：其同接口请求缺少浏览器UA，会被东财反爬直接断连。
    Returns:
        pd.DataFrame: 列为 date,open,close,high,low,volume,amount（东财原始顺序，volume单位为手）
    """
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57',
        'klt': '101', 'fqt': '1',
        'beg': beg, 'end': end,
    }
    r = requests.get(EM_KLINE_URL, params=params, headers=EM_HEADERS, timeout=15)
    r.raise_for_status()
    klines = (r.json().get('data') or {}).get('klines') or []
    rows = [k.split(',') for k in klines]
    return pd.DataFrame(
        rows, columns=['date', 'open', 'close', 'high', 'low', 'volume', 'amount'])


def fetch_and_save_index_data_em(symbol, secid, index_path, amount_path):
    """
    东财K线API一次请求，同时增量更新同一指数的两份CSV，避免重复拉取：
    - index_path: 与sina格式一致的6列无表头CSV，volume由"手"×100换算为"股"
    - amount_path: 含表头的 date,amount CSV（单位：元），供市场强弱分布图使用
    """
    os.makedirs(os.path.dirname(index_path), exist_ok=True)

    def _last_date(path, has_header):
        if not os.path.exists(path):
            return None
        col = pd.read_csv(path, header=0 if has_header else None, usecols=[0]).iloc[:, 0]
        return pd.to_datetime(col).max()

    last_index = _last_date(index_path, has_header=False)
    last_amount = _last_date(amount_path, has_header=True)

    starts = [(d + pd.Timedelta(days=1) if d is not None
               else pd.to_datetime(AMOUNT_HISTORY_START)) for d in (last_index, last_amount)]
    beg = min(starts).strftime('%Y%m%d')
    end = datetime.now().strftime('%Y%m%d')
    if beg > end:
        print(f"No new data/amount for {symbol}.")
        return

    em = _fetch_em_klines(secid, beg, end)
    if em.empty:
        print(f"No new data/amount for {symbol}.")
        return
    em['date'] = pd.to_datetime(em['date'])

    # 6列行情增量（date,open,high,low,close,volume），volume 手→股 与 sina 口径一致
    idx_new = em if last_index is None else em[em['date'] > last_index]
    if not idx_new.empty:
        out = pd.DataFrame({
            'date': idx_new['date'].dt.strftime('%Y-%m-%d'),
            'open': idx_new['open'], 'high': idx_new['high'],
            'low': idx_new['low'], 'close': idx_new['close'],
            'volume': idx_new['volume'].astype('int64') * 100,
        })
        if last_index is None:
            out.to_csv(index_path, index=False, header=False)
        else:
            old = pd.read_csv(index_path, header=None, names=out.columns)
            pd.concat([old, out], ignore_index=True).to_csv(index_path, index=False, header=False)
        print(f"Data for {symbol} updated to {index_path} (+{len(out)} rows, via 东财)")
    else:
        print(f"No new data for {symbol}.")

    # 成交额增量（date,amount）
    amt_new = em if last_amount is None else em[em['date'] > last_amount]
    if not amt_new.empty:
        out = amt_new[['date', 'amount']].copy()
        out['amount'] = out['amount'].astype(float)
        if last_amount is None:
            out.to_csv(amount_path, index=False, header=True)
        else:
            old = pd.read_csv(amount_path, dtype={'date': str})
            pd.concat([old, out], ignore_index=True).to_csv(amount_path, index=False)
        print(f"Amount for {symbol} updated to {amount_path} (+{len(out)} rows, via 东财)")
    else:
        print(f"No new amount for {symbol}.")


def fetch_and_save_index_amount(symbol, secid, save_path):
    """
    从东方财富K线API获取指数日成交额并保存为CSV文件（含表头：date,amount，单位：元）。
    如果文件已存在，则从最新的日期处增量追加。

    :param symbol: 指数代码简称，如 'sh000001'，仅用于日志
    :param secid: 东财证券ID，如 '1.000001'（上证指数）
    :param save_path: 保存CSV文件的路径
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    existing = None
    if os.path.exists(save_path):
        existing = pd.read_csv(save_path, dtype={'date': str})
        beg = (pd.to_datetime(existing['date']).max() + pd.Timedelta(days=1)).strftime('%Y%m%d')
    else:
        beg = AMOUNT_HISTORY_START

    end = datetime.now().strftime('%Y%m%d')
    if beg > end:
        print(f"No new amount for {symbol}.")
        return

    em = _fetch_em_klines(secid, beg, end)
    if em.empty:
        print(f"No new amount for {symbol}.")
        return

    new_data = em[['date', 'amount']].astype({'amount': float})
    result = pd.concat([existing, new_data], ignore_index=True) if existing is not None else new_data
    result.to_csv(save_path, index=False)
    print(f"Amount for {symbol} updated to {save_path} (+{len(new_data)} rows)")


def fetch_indexes_data(save_dir):
    """
    主函数，用于获取上证、深证和创业板指数数据并保存。

    :param save_dir: 保存CSV文件的目录
    """
    # sh000001/sz399001：东财一次请求同时更新6列行情与成交额，避免同一指数重复拉取
    for symbol, secid in AMOUNT_INDICES.items():
        index_path = os.path.join(save_dir, INDEX_FILES[symbol])
        amount_path = os.path.join(save_dir, f"{symbol}_amount.csv")
        try:
            fetch_and_save_index_data_em(symbol, secid, index_path, amount_path)
            continue
        except Exception as e:
            print(f"{symbol} 东财拉取失败，回退sina更新行情: {e}")
            try:
                fetch_and_save_index_data(symbol, index_path)
            except Exception as e2:
                print(f"{symbol} sina拉取也失败: {e2}")
            try:
                fetch_and_save_index_amount(symbol, secid, amount_path)
            except Exception as e3:
                print(f"获取 {symbol} 成交额失败: {e3}")

    # 其余指数走 sina
    for symbol, filename in INDEX_FILES.items():
        if symbol in AMOUNT_INDICES:
            continue
        fetch_and_save_index_data(symbol, os.path.join(save_dir, filename))


if __name__ == "__main__":
    # 指定保存目录
    save_directory = "path/to/your/directory"
    fetch_indexes_data(save_directory)
