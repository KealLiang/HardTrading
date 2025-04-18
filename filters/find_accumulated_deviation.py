import os
import pandas as pd
from datetime import datetime
from utils.date_util import get_n_trading_days_before

def find_accumulated_deviation_stocks(
    data_path='./data/astocks',
    window_days=5,
    deviation_threshold=20.0,
    end_date=None,
    output_path='./data/accumulated_deviation/result.txt'
):
    """
    筛选在连续n个交易日内，日收盘涨跌幅偏离值累计达到x%的个股。
    若x为正，查找累计涨跌幅大于等于x%的区间；
    若x为负，查找累计涨跌幅小于等于x%的区间。

    :param data_path: 股票数据文件夹
    :param window_days: 连续天数n
    :param deviation_threshold: 累计涨跌幅阈值x（百分比，正负方向决定查找方向）
    :param end_date: 结束日期（字符串'YYYY-MM-DD'，可选，默认今天）
    :param output_path: 结果输出路径
    """
    # 计算end_date和start_date
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = get_n_trading_days_before(end_date, window_days - 1)  # 向前推n-1个交易日

    results = []
    for filename in os.listdir(data_path):
        if not filename.endswith('.csv'):
            continue
        stock_code, stock_name = filename.split('_')
        stock_name = stock_name.replace('.csv', '')
        df = pd.read_csv(
            os.path.join(data_path, filename),
            header=None,
            names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                   '振幅', '涨跌幅', '涨跌额', '换手率']
        )
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        # 过滤日期
        if start_date:
            df = df[df['日期'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['日期'] <= pd.to_datetime(end_date)]
        # 计算滑动窗口累计涨跌幅
        df['累计涨跌幅'] = df['涨跌幅'].rolling(window=window_days).sum()
        # 根据x的正负决定查找方向
        if deviation_threshold > 0:
            match_rows = df[df['累计涨跌幅'] >= deviation_threshold]
        elif deviation_threshold < 0:
            match_rows = df[df['累计涨跌幅'] <= deviation_threshold]
        else:
            # x为0时，理论上没有意义，这里直接跳过
            continue
        if not match_rows.empty:
            for _, row in match_rows.iterrows():
                results.append({
                    '股票代码': stock_code,
                    '股票名称': stock_name,
                    '区间结束日期': row['日期'].strftime('%Y-%m-%d'),
                    '累计涨跌幅': row['累计涨跌幅']
                })
    # 输出结果
    if results:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result_df = pd.DataFrame(results)
        result_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"筛选结果已保存至: {output_path}")
    else:
        print("未发现符合条件的个股。")

if __name__ == '__main__':
    # 示例：查找5日内累计涨跌幅大于等于20%的个股
    find_accumulated_deviation_stocks(
        data_path='./data/astocks',
        window_days=10,
        deviation_threshold=100.0,  # 正数查找上涨，负数查找下跌
        end_date='2025-04-18',
        output_path='./data/accumulated_deviation/result.txt'
    )