import logging
import os
from datetime import datetime

import akshare as ak
import pandas as pd

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def sanitize_filename(name):
    """清理文件名中的非法字符，如替换 * 为 x"""
    return name.replace("*", "x")


def fetch_and_save_stock_data(interval="15", start_date=None, end_date=None, stock_list=None, output_dir="stock_data"):
    """
    拉取 A 股指定级别的交易数据，并按时间范围保存为 CSV 文件。
    表头 -> 时间,开盘,收盘,最高,最低,涨跌幅,涨跌额,成交量,成交额,振幅,换手率

    :param interval: 数据级别，默认 "15" 表示 15 分钟，可以是 ["1", "5", "15", "30", "60", "D", "W", "M"]。
    :param start_date: 起始日期（必传），格式为 "YYYYMMDD"。
    :param end_date: 终止日期（可选，默认为今天），格式为 "YYYYMMDD"。
    :param stock_list: 股票代码列表（默认 None，表示拉取全部股票数据）。
    :param output_dir: 数据保存的目录，默认 "stock_data"。
    """
    if not start_date:
        raise ValueError("必须指定起始日期（start_date），格式为 'YYYYMMDD'。")

    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 步骤 1: 获取所有股票代码和名称
    logging.info("开始获取股票列表...")
    stock_info_df = ak.stock_info_a_code_name()
    if stock_list:
        stock_info_df = stock_info_df[stock_info_df['code'].isin(stock_list)]

    logging.info(f"共找到 {len(stock_info_df)} 支股票。")

    # 步骤 2: 遍历每只股票，拉取交易数据并保存为 CSV
    for _, row in stock_info_df.iterrows():
        start = start_date
        end = end_date
        stock_code = row['code']
        stock_name = sanitize_filename(row['name'])  # 清理文件名中的非法字符
        output_file = os.path.join(output_dir, f"{stock_code}_{stock_name}.csv")

        try:
            if os.path.exists(output_file):
                logging.info(f"文件 {output_file} 已存在，将从最新的数据开始追加...")
                existing_data = pd.read_csv(output_file, usecols=[0], names=["时间"], header=None)
                last_date = existing_data["时间"].iloc[-1]
                # 更新起始日期为最后日期之后的下一天，避免重复保存
                start = (datetime.strptime(last_date, "%Y-%m-%d %H:%M:%S") + pd.Timedelta(days=1)).strftime(
                    "%Y%m%d")

            logging.info(
                f"开始拉取 {stock_code}_{stock_name} 的 {interval} 分钟级别交易数据，时间范围：{start} 至 {end}...")
            # 拉取数据
            stock_data = ak.stock_zh_a_hist_min_em(
                symbol=stock_code,
                period=interval,
                adjust="qfq",
                start_date=start,
                end_date=end
            )

            if stock_data.empty:
                logging.warning(f"{stock_code}_{stock_name} 在时间范围内没有新数据，跳过...")
                continue

            # 如果文件已存在，追加数据；否则保存新文件
            if os.path.exists(output_file):
                stock_data.to_csv(output_file, mode='a', header=False, index=False)
                logging.info(f"{stock_code}_{stock_name} 的数据已追加保存到 {output_file}")
            else:
                stock_data.to_csv(output_file, index=False, header=False)
                logging.info(f"{stock_code}_{stock_name} 的数据已保存到 {output_file}")

        except Exception as e:
            logging.error(f"拉取 {stock_code}_{stock_name} 数据时出错：{e}")

    logging.info("全部数据处理完成！")


# 示例用法
if __name__ == "__main__":
    # 示例：拉取指定股票的 15 分钟数据，指定时间范围
    fetch_and_save_stock_data(
        interval="15",  # 拉取 15 分钟级别数据
        start_date="20241101",  # 起始日期
        end_date="20241210",  # 终止日期（可选）
        stock_list=["000717", "603776"],  # 只拉取这两个股票的数据
        output_dir="a_stock_15min_data"  # 保存到指定目录
    )
