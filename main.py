from datetime import datetime

from analysis.seek_historical_similar import find_other_similar_trends
from bin import simulator
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import StockDataFetcher
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.converter import backtrade_form
from fetch.indexes_data import fetch_indexes_data
from fetch.lhb_data import fetch_and_merge_stock_lhb_detail, fetch_and_filter_yybph_lhb_data, fetch_yyb_lhb_data, \
    find_top_yyb_trades
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
    data_fetcher = StockDataFetcher(start_date='20241209', save_path='./data/astocks')
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


def fetch_and_filter_top_yybph():
    # 使用示例
    symbol = "近三月"
    file_path = "./data/lhb/top_yybph.csv"  # 保存的 CSV 文件路径，请根据需要修改

    fetch_and_filter_yybph_lhb_data(symbol, file_path)


def get_lhb_datas():
    start_date = "2024-08-01"
    end_date = None
    first_file_path = './data/lhb/yyb_lhb_data.csv'
    second_file_path = './data/lhb/stock_lhb_details.csv'
    trader_name = "中国银河证券股份有限公司大连黄河路证券营业部"
    # 1. 拉取营业部龙虎榜数据
    fetch_yyb_lhb_data(start_date, end_date, first_file_path)
    # 2. 遍历营业部数据，拉取个股龙虎榜合并
    fetch_and_merge_stock_lhb_detail(first_file_path, second_file_path, trader_name)


def get_top_yyb_trades():
    # 找最顶级游资的交易数据
    # 需先运行fetch_and_filter_top_yybph()获取"top_yybph_lhb_data.csv"
    find_top_yyb_trades('./data/lhb/')


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
    target_stock_code = "603960"  # 目标股票代码
    start_date = datetime.strptime("2024-02-01", "%Y-%m-%d")
    end_date = datetime.strptime("2024-03-08", "%Y-%m-%d")

    # 1.寻找自身相似时期
    # find_self_similar_windows(target_stock_code, start_date, end_date, data_dir, method="weighted")

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
    # fetch_and_filter_top_yybph()
    get_top_yyb_trades()
    # get_lhb_datas()
    # get_index_data()
    # find_similar_trends()
    # get_stock_datas()
    # get_stock_minute_datas()
    # get_hot_clouds()
    # find_dragon()
    # get_stock_concept_and_industry()
