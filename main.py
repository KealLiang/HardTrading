from bin import simulator
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import AStockDataFetcher
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.converter import backtrade_form
from filters.find_longtou import find_dragon_stocks
from tonghuashun.concept_analyze import concept_words_cloud


# 回溯交易
def backtrade_simulate():
    code = '159949'
    # fetch_fund_data(code + '.SZ')
    backtrade_form(code)
    simulator.go_trade(code)


# 获取热点概念词云
def get_hot_concept_clouds():
    concept_words_cloud(1)


# 拉a股历史数据
def get_a_stock_datas():
    # 创建A股数据获取对象，指定拉取的天数和保存路径
    data_fetcher = AStockDataFetcher(start_date='20120101', save_path='./data/astocks')
    # 执行数据获取和保存操作
    data_fetcher.fetch_and_save_data()


def get_a_stock_minute_datas():
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


def get_a_concept_and_industry():
    fetch_and_save_stock_concept(
        concept_list=["云游戏", "新能源车"],
        industry_list=["银行", "房地产"],
        output_path="./data/concepts_data/筛选的概念与行业数据.xlsx"
    )


if __name__ == '__main__':
    get_a_stock_minute_datas()
    # get_hot_concept_clouds()
    # find_dragon()
    # get_a_concept_and_industry()
