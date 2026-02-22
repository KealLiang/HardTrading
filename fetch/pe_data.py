"""
沪深300 PE 数据获取与本地存储

数据来源：乐咕乐股（通过 akshare.stock_index_pe_lg）
覆盖范围：2005-04-08 至今，每日更新
"""

import os
import logging
import pandas as pd
import akshare as ak

# 默认存储路径
PE_DATA_DIR = './data/pe'
PE_FILE_PATH = os.path.join(PE_DATA_DIR, '000300_pe.csv')


def fetch_and_save_csi300_pe(
    save_path: str = PE_FILE_PATH,
    force_update: bool = False,
) -> pd.DataFrame:
    """
    获取沪深300历史PE数据并保存到本地 CSV。
    支持增量更新：若本地已有数据则只补充缺失日期。

    数据字段：
      - 日期：交易日
      - PE：动态市盈率（TTM，等权市值加权）
      - PE_等权：等权动态市盈率

    :param save_path: 本地保存路径（CSV）
    :param force_update: True=强制全量重新下载，False=增量更新
    :return: 完整 PE DataFrame（日期为索引）
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # ── 从 akshare 获取全量数据 ──
    logging.info("从乐咕乐股获取沪深300 PE 历史数据...")
    raw = ak.stock_index_pe_lg(symbol="沪深300")

    # 整理字段：保留日期、滚动PE（TTM）、等权滚动PE
    # akshare 实际返回列：日期, 指数, 等权静态市盈率, 静态市盈率, 静态市盈率中位数,
    #                     等权滚动市盈率, 滚动市盈率, 滚动市盈率中位数
    pe_df = (
        raw[['日期', '滚动市盈率', '等权滚动市盈率']]
        .rename(columns={'滚动市盈率': 'PE', '等权滚动市盈率': 'PE_等权'})
        .copy()
    )
    pe_df['日期'] = pd.to_datetime(pe_df['日期'])
    pe_df = pe_df.dropna(subset=['PE']).sort_values('日期').reset_index(drop=True)

    # ── 增量合并（如本地已有数据且非强制更新）──
    if not force_update and os.path.exists(save_path):
        existing = pd.read_csv(save_path, parse_dates=['日期'])
        existing_dates = set(existing['日期'].dt.strftime('%Y-%m-%d'))
        new_rows = pe_df[~pe_df['日期'].dt.strftime('%Y-%m-%d').isin(existing_dates)]
        if new_rows.empty:
            logging.info(f"PE 数据已是最新，无需更新（共 {len(existing)} 条）")
            return existing.set_index('日期')
        combined = pd.concat([existing, new_rows]).sort_values('日期').reset_index(drop=True)
        added = len(new_rows)
    else:
        combined = pe_df
        added = len(pe_df)

    combined.to_csv(save_path, index=False, encoding='utf-8-sig')
    logging.info(f"PE 数据已保存至 {save_path}，新增 {added} 条，共 {len(combined)} 条")
    print(f"[OK] 沪深300 PE 数据已更新：{len(combined)} 条 "
          f"（{combined['日期'].iloc[0].strftime('%Y-%m-%d')} ~ "
          f"{combined['日期'].iloc[-1].strftime('%Y-%m-%d')}）")

    return combined.set_index('日期')


def load_csi300_pe(save_path: str = PE_FILE_PATH) -> pd.DataFrame:
    """
    从本地 CSV 加载沪深300 PE 数据。

    :return: DataFrame，日期为索引，列 PE / PE_等权
    :raises FileNotFoundError: 若本地文件不存在
    """
    if not os.path.exists(save_path):
        raise FileNotFoundError(
            f"PE 数据文件不存在: {save_path}\n"
            "请先调用 fetch_and_save_csi300_pe() 下载数据，或在 main.py 中运行 get_pe_data()"
        )
    df = pd.read_csv(save_path, parse_dates=['日期']).set_index('日期').sort_index()
    return df

