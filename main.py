from bin import simulator
from fetch.astock_data import AStockDataFetcher
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
    concept_words_cloud(3)


# 拉a股历史数据
def get_a_datas():
    # 创建A股数据获取对象，指定拉取的天数和保存路径
    data_fetcher = AStockDataFetcher(start_date='20120101', save_path='./data/astocks')
    # 执行数据获取和保存操作
    data_fetcher.fetch_and_save_data()


# 找龙头
def find_dragon():
    start_date = '2024-05-10'
    end_date = '2024-06-01'
    find_dragon_stocks(start_date)


if __name__ == '__main__':
    # find_dragon()
    get_hot_concept_clouds()
