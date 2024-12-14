from datetime import datetime

from analysis.seek_historical_similar import find_other_similar_trends, find_self_similar_windows
from bin import simulator
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import AStockDataFetcher
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.converter import backtrade_form
from fetch.indexes_data import fetch_indexes_data
from fetch.tonghuashun.hotpoint_analyze import hot_words_cloud
from filters.find_longtou import find_dragon_stocks


# 回溯交易
def backtrade_simulate():
    code = '159949'
    # fetch_fund_data(code + '.SZ')
    backtrade_form(code)
    simulator.go_trade(code)


# 获取热点概念词云
def get_hot_clouds():
    hot_words_cloud(0)


def get_index_data():
    # 指定保存目录
    save_directory = "data/indexes"
    fetch_indexes_data(save_directory)

# 拉a股历史数据
def get_stock_datas():
    # 创建A股数据获取对象，指定拉取的天数和保存路径
    data_fetcher = AStockDataFetcher(start_date='20241209', save_path='./data/astocks')
    # 执行数据获取和保存操作
    data_fetcher.fetch_and_save_data()


def get_stock_minute_datas():
    fetch_and_save_stock_data(
        interval="15",  # 拉取 15 分钟级别数据
        start_date="20241110",  # 起始日期
        end_date="20241210",  # 终止日期（可选）
        # stock_list=["000717", "603776"],  # 只拉取这两个股票的数据
        output_dir="./data/astocks_minute"  # 保存到指定目录
    )


# 找龙头
def find_dragon():
    start_date = '2024-05-10'
    end_date = '2024-06-01'
    find_dragon_stocks(start_date)


def get_stock_concept_and_industry():
    fetch_and_save_stock_concept(
        concept_list=["云游戏", "新能源车"],
        industry_list=["银行", "房地产"],
        output_path="./data/concepts_data/筛选的概念与行业数据.xlsx"
    )


def find_similar_trends():
    data_dir = "./data/astocks"  # 数据文件所在目录
    target_stock_code = "601933"  # 目标股票代码
    start_date = datetime.strptime("2024-11-01", "%Y-%m-%d")
    end_date = datetime.strptime("2024-12-13", "%Y-%m-%d")

    # 1.寻找自身相似时期
    find_self_similar_windows(target_stock_code, start_date, end_date, data_dir, method="weighted")

    # 2.寻找同时期相似个股
    # 可选股票代码列表
    # stock_codes = [
    #     "600928",
    #     "601319",
    #     "001227"
    # ]
    stock_codes = None
    find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes, data_dir, method="weighted")


if __name__ == '__main__':
    get_index_data()
    # find_similar_trends()
    # get_stock_datas()
    # get_stock_minute_datas()
    # get_hot_clouds()
    # find_dragon()
    # get_stock_concept_and_industry()
