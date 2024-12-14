import logging
import os
from datetime import datetime

import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from matplotlib import font_manager

font_path = 'fonts/微软雅黑.ttf'
font_prop = font_manager.FontProperties(fname=font_path)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 定义列名对应的英文名称
col_mapping = {
    '日期': 'date',
    '开盘': 'open',
    '最高': 'high',
    '最低': 'low',
    '收盘': 'close',
    '成交量': 'volume'
}


def load_stock_data(file_path):
    """
    加载单只股票数据
    """
    try:
        data = pd.read_csv(file_path, header=None, names=[
            '日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率'
        ])
        data['日期'] = pd.to_datetime(data['日期'])
        return data
    except Exception as e:
        logging.error(f"加载文件 {file_path} 时出错: {e}")
        return None


def load_index_data(file_path):
    """
    加载指数数据
    """
    try:
        data = pd.read_csv(file_path, header=None, names=[
            '日期', '开盘', '最高', '最低', '收盘', '成交量'
        ])
        data['日期'] = pd.to_datetime(data['日期'])
        return data
    except Exception as e:
        logging.error(f"加载文件 {file_path} 时出错: {e}")
        return None


def compute_correlation(target_data, stock_data):
    """
    计算目标股票与候选股票的收盘价相关系数

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_data: DataFrame - 候选股票的数据

    返回:
    float - 相关系数
    """
    return np.corrcoef(target_data['收盘'].values, stock_data['收盘'].values)[0, 1]


def compute_weighted_correlation(target_data, stock_data):
    """
    计算目标股票与候选股票的加权相关系数（开盘价与收盘价，权重1:3）

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_data: DataFrame - 候选股票的数据

    返回:
    float - 加权相关系数
    """
    open_corr = np.corrcoef(target_data['开盘'].values, stock_data['开盘'].values)[0, 1]
    close_corr = np.corrcoef(target_data['收盘'].values, stock_data['收盘'].values)[0, 1]
    return (1 * open_corr + 3 * close_corr) / 4


def calculate_similarity(target_data, stock_codes, start_date, end_date, data_dir, method="close_price"):
    """
    计算相似股票及其时间段

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_codes: list - 候选股票代码列表
    start_date: datetime - 起始日期
    end_date: datetime - 结束日期
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法（"close_price" 或 "weighted"）

    返回:
    list - 包含股票代码和相似度的元组列表
    """
    similarity_results = []

    for stock_code in stock_codes:
        file_path = next((os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith(f"{stock_code}_")),
                         None)
        if not file_path:
            logging.warning(f"未找到股票 {stock_code} 的数据文件，跳过。")
            continue

        stock_data = load_stock_data(file_path)
        if stock_data is None:
            continue

        stock_data = stock_data[(stock_data['日期'] >= start_date) & (stock_data['日期'] <= end_date)]
        if stock_data.empty or len(stock_data) != len(target_data):
            logging.warning(f"股票 {stock_code} 的数据不符合目标区间要求，跳过。")
            continue

        if method == "close_price":
            correlation = compute_correlation(target_data, stock_data)
        elif method == "weighted":
            correlation = compute_weighted_correlation(target_data, stock_data)
        else:
            logging.error(f"不支持的相似度计算方法: {method}")
            return []

        similarity_results.append((stock_code, correlation, stock_data))

    similarity_results.sort(key=lambda x: x[1], reverse=True)
    return similarity_results


def plot_kline(dataframes, stock_labels, split_dates=None, output_dir="kline_charts"):
    """
    绘制K线图并保存到本地

    参数:
    dataframes: list - 包含每只股票数据的DataFrame列表
    stock_labels: list - 每只股票的标签列表
    split_dates: list - 用于绘制分隔标记的日期列表（与dataframes长度相同）
    output_dir: str - 图表保存路径
    """
    # 设置中文字体防止乱码
    plt.rcParams['font.family'] = font_prop.get_name()
    plt.rcParams['axes.unicode_minus'] = False

    # 创建保存目录
    os.makedirs(output_dir, exist_ok=True)

    for df, label, split_date in zip(dataframes, stock_labels, split_dates or [None] * len(dataframes)):
        # 转换为适合 mplfinance 的格式
        df_mpf = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']].rename(columns=col_mapping).copy()
        df_mpf.set_index('date', inplace=True)

        # 配置样式
        custom_colors = mpf.make_marketcolors(
            up='red',
            down='green',
            edge='black',
            wick='black',
            volume='orange'
        )
        mpf_style = mpf.make_mpf_style(base_mpf_style="charles",
                                       rc={"font.sans-serif": font_prop.get_name() if font_prop else "SimHei"},
                                       marketcolors=custom_colors)

        # 保存图表
        output_file = os.path.join(output_dir, f"{label}_kline.png")

        # 根据 alines 是否为 None 来决定是否传递该参数
        plot_params = {
            'type': "candle",
            'title': f"{label} K线图",
            'style': mpf_style,
            'volume': True,
            'savefig': dict(fname=output_file, dpi=300, bbox_inches="tight")
        }

        # 添加竖线标记
        if split_date:
            plot_params['alines'] = [(split_date, df_mpf['low'].min()), (split_date, df_mpf['high'].max())]

        mpf.plot(df_mpf, **plot_params)

        logging.info(f"K线图已保存到 {output_file}")


def get_stock_info_dict(data_dir):
    # 获取代码名称字典
    stock_info_dict = {}
    for f in os.listdir(data_dir):
        if f.endswith('.csv'):
            parts = f.split('_')
            stock_code = parts[0]
            stock_name = '_'.join(parts[1:]).split('.')[0]  # 提取名称部分并去掉.csv后缀
            stock_info_dict[stock_code] = stock_name
    return stock_info_dict


def find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes=None, data_dir=".",
                              method="close_price"):
    """
    主函数：寻找历史相似走势

    参数:
    target_stock_code: str - 目标股票代码
    start_date: datetime - 起始日期
    end_date: datetime - 结束日期
    stock_codes: list - 候选股票代码列表（可选）
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法
    """
    logging.info("开始加载目标股票数据...")
    target_file = next(
        (os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith(f"{target_stock_code}_")), None)
    if not target_file:
        logging.error(f"未找到目标股票 {target_stock_code} 的数据文件！")
        return

    target_data = load_stock_data(target_file)
    target_data = target_data[(target_data['日期'] >= start_date) & (target_data['日期'] <= end_date)]
    if target_data.empty:
        logging.error("目标股票在指定区间内无数据！")
        return

    logging.info(f"目标股票 {target_stock_code} 的数据加载完成，开始寻找相似走势...")

    if stock_codes is None:
        stock_codes = [f.split('_')[0] for f in os.listdir(data_dir) if
                       f.endswith('.csv') and not f.startswith(f"{target_stock_code}_")]

    similarity_results = calculate_similarity(target_data, stock_codes, start_date, end_date, data_dir, method)

    logging.info("相似走势计算完成，结果如下：")
    top_similar = similarity_results[:10]
    for stock_code, correlation, _ in top_similar:
        logging.info(f"股票代码: {stock_code}, 相似度: {correlation:.4f}")

    stock_info_dict = get_stock_info_dict(data_dir)
    # 绘制并保存K线图
    dataframes = [target_data] + [result[2] for result in top_similar]
    labels = [f"A目标股票_{target_stock_code}"] + [f"{stock_info_dict[result[0]]}_{result[0]}_{result[1]:.4f}" for
                                                   result in
                                                   top_similar]
    plot_kline(dataframes, labels, output_dir="./kline_charts/other_similar")


def find_self_similar_windows(target_stock_code, start_date, end_date, data_dir=".", method="close_price",
                              future_days=10):
    """
    找出某只个股与自身不同时期的相似度，并画图包括“未来天数”的K线。

    参数:
    target_stock_code: str - 目标股票代码
    start_date: datetime - 起始日期
    end_date: datetime - 结束日期
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法（"close_price" 或 "weighted"）
    future_days: int - 未来天数，用于绘制相似区间后的预测数据
    """
    # 加载目标股票数据
    target_file = next(
        (os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith(f"{target_stock_code}_")), None)
    if not target_file:
        logging.error(f"未找到目标股票 {target_stock_code} 的数据文件！")
        return

    # 加载个股或指数
    if target_stock_code[0].isdigit():
        stock_data = load_stock_data(target_file)
    else:
        stock_data = load_index_data(target_file)

    # 确定目标时间段
    target_data = stock_data[(stock_data['日期'] >= start_date) & (stock_data['日期'] <= end_date)]
    if target_data.empty:
        logging.error("目标股票在指定区间内无数据！")
        return

    # 确定交易日窗口大小
    nyse = mcal.get_calendar('SSE')  # A股使用 'SSE' 日历
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)
    target_window_size = len(schedule)

    if target_window_size < 5:  # 防止窗口过小
        logging.error("指定时间范围内交易日不足以计算窗口！")
        return

    # 滑动窗口寻找相似时段
    similarity_results = []
    for i in range(len(stock_data) - target_window_size + 1):
        window_start = stock_data.iloc[i]['日期']
        window_end = stock_data.iloc[i + target_window_size - 1]['日期']

        # 跳过目标区间本身
        if window_start >= start_date and window_end <= end_date:
            continue

        window_data = stock_data.iloc[i:i + target_window_size]
        if method == "close_price":
            correlation = compute_correlation(target_data, window_data)
        elif method == "weighted":
            correlation = compute_weighted_correlation(target_data, window_data)
        else:
            logging.error(f"不支持的相似度计算方法: {method}")
            return

        # 提取未来天数数据
        future_data = stock_data.iloc[i + target_window_size:i + target_window_size + future_days]
        merged_data = pd.concat([window_data, future_data], ignore_index=True)
        similarity_results.append((window_start, window_end, correlation, merged_data))

    # 按相似度排序并获取前5个窗口
    similarity_results.sort(key=lambda x: x[2], reverse=True)
    top_windows = similarity_results[:5]

    logging.info("最相似的时间窗口:")
    for start, end, corr, _ in top_windows:
        logging.info(f"时间段: {start.date()} 至 {end.date()}, 相似度: {corr:.4f}")

    # 绘制并保存K线图
    dataframes = [target_data] + [result[3] for result in top_windows]
    labels = [f"目标区间_{start_date.date()}_{end_date.date()}"] + \
             [f"相似区间_{start.date()}_{end.date()}_{corr:.4f}" for start, end, corr, _ in top_windows]
    split_dates = [None] + [end for _, end, _, _ in top_windows]  # 分隔标记日期，目标区间无标记

    plot_kline(dataframes, labels, split_dates=split_dates, output_dir="./kline_charts/self_similar")


# 示例调用
if __name__ == "__main__":
    target_stock_code = "000001"  # 目标股票代码
    start_date = datetime.strptime("2024-11-01", "%Y-%m-%d")
    end_date = datetime.strptime("2024-12-12", "%Y-%m-%d")

    # 可选股票代码列表
    stock_codes = [
        "600928",
        "601319",
        "001227"
    ]
    # stock_codes = None

    data_dir = "./data/astocks"  # 数据文件所在目录

    # 1.寻找自身相似时期
    find_self_similar_windows(target_stock_code, start_date, end_date, data_dir, method="weighted")

    # 2.寻找同时期相似个股
    # find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes, data_dir, method="weighted")
