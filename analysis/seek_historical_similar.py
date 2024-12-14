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


def load_zhishu_data(file_path):
    """
    加载指数数据
    """
    try:
        data = pd.read_csv(file_path, header=None, names=[
            'date', 'open', 'high', 'low', 'close', 'volume'
        ])
        data['date'] = pd.to_datetime(data['date'])
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


def plot_kline(dataframes, stock_labels, output_dir="kline_charts"):
    """
    绘制K线图并保存到本地

    参数:
    dataframes: list - 包含每只股票数据的DataFrame列表
    stock_labels: list - 每只股票的标签列表
    output_dir: str - 图表保存路径
    """
    # 设置中文字体防止乱码
    plt.rcParams['font.family'] = font_prop.get_name()
    plt.rcParams['axes.unicode_minus'] = False

    # 定义列名对应的英文名称
    col_mapping = {
        '日期': 'date',
        '开盘': 'open',
        '最高': 'high',
        '最低': 'low',
        '收盘': 'close',
        '成交量': 'volume'
    }

    # 创建保存目录
    os.makedirs(output_dir, exist_ok=True)

    for df, label in zip(dataframes, stock_labels):
        # 转换为适合 mplfinance 的格式
        df_mpf = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']].rename(columns=col_mapping).copy()
        df_mpf.set_index('date', inplace=True)

        # 配置样式
        custom_colors = mpf.make_marketcolors(
            up='red',  # 上涨的颜色
            down='green',  # 下跌的颜色
            edge='black',  # K线边缘颜色
            wick='black',  # K线上下影线颜色
            volume='orange'  # 成交量条颜色
        )
        mpf_style = mpf.make_mpf_style(base_mpf_style="charles",
                                       rc={"font.sans-serif": font_prop.get_name() if font_prop else "SimHei"},
                                       marketcolors=custom_colors)

        # 保存图表
        output_file = os.path.join(output_dir, f"{label}_kline.png")
        mpf.plot(
            df_mpf,
            type="candle",
            title=f"{label} K线图",
            style=mpf_style,
            volume=True,
            savefig=dict(fname=output_file, dpi=300, bbox_inches="tight")
        )
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


def find_self_similar_windows(target_stock_code, start_date, end_date, data_dir=".", method="close_price"):
    """
    找出某只个股与自身不同时期的相似度，根据给定的起止日期确定时间窗口（以交易日计算），找出最相似的5个时间窗口，打印日期，并画图保存

    参数:
    target_stock_code: str - 目标股票代码
    start_date: datetime - 起始日期
    end_date: datetime - 结束日期
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法（"close_price" 或 "weighted"）
    """
    logging.info("开始加载目标股票数据...")
    target_file = next(
        (os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith(f"{target_stock_code}_")), None)
    if not target_file:
        logging.error(f"未找到目标股票 {target_stock_code} 的数据文件！")
        return

    target_data = load_stock_data(target_file)
    if target_data.empty:
        logging.error("目标股票数据为空！")
        return

    # 计算时间窗口大小（以交易日为准）
    cal = mcal.get_calendar('SSE')
    trading_sessions = cal.schedule(start_date=start_date, end_date=end_date)
    trading_days = trading_sessions.index
    window_size = len(trading_days)

    similarity_results = []
    total_days = len(target_data)
    for start_idx in range(0, total_days - window_size):
        window_start_date = target_data['日期'].iloc[start_idx]
        window_end_date = target_data['日期'].iloc[start_idx + window_size - 1]
        window_data = target_data[(target_data['日期'] >= window_start_date) & (target_data['日期'] <= window_end_date)]

        # 与原数据中传入的起止日期范围内数据进行对比（这里修改为与整个目标数据中对应起止日期范围对比）
        compare_data = target_data[(target_data['日期'] >= start_date) & (target_data['日期'] <= end_date)]
        if method == "close_price":
            correlation = compute_correlation(window_data, compare_data)
        elif method == "weighted":
            correlation = compute_weighted_correlation(window_data, compare_data)
        else:
            logging.error(f"不支持的相似度计算方法: {method}")
            return

        similarity_results.append((window_start_date, window_end_date, correlation))

    similarity_results.sort(key=lambda x: x[2], reverse=True)
    top_num = 5
    top_similar_windows = similarity_results[:top_num]

    logging.info(f"最相似的{top_num}个时间窗口如下：")
    for window_start, window_end, correlation in top_similar_windows:
        logging.info(f"开始日期: {window_start}, 结束日期: {window_end}, 相似度: {correlation:.4f}")

    # 绘制并保存这5个时间窗口的K线图
    dataframes = []
    labels = []
    for window_start, window_end, _ in top_similar_windows:
        window_data = target_data[(target_data['日期'] >= window_start) & (target_data['日期'] <= window_end)]
        dataframes.append(window_data)
        labels.append(f"窗口_{window_start.strftime('%Y%m%d')}_{window_end.strftime('%Y%m%d')}")
    plot_kline(dataframes, labels, output_dir="./kline_charts/self_similar")


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
