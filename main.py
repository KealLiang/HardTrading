from datetime import datetime

from analysis.calculate_limit_up_success_rate import analyze_rate
from analysis.daily_group import find_stocks_by_hot_themes, highlight_repeated_stocks
from analysis.fupan_statistics import fupan_all_statistics
from analysis.fupan_statistics_plot import plot_all
from analysis.seek_historical_similar import find_other_similar_trends
from analysis.time_price_sharing import analyze_abnormal_stocks_time_sharing
from analysis.whimsical import process_zt_data, consolidate_unclassified_reasons
from bin import simulator
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import StockDataFetcher
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.indexes_data import fetch_indexes_data
from fetch.lhb_data import fetch_and_merge_stock_lhb_detail, fetch_and_filter_yybph_lhb_data, fetch_yyb_lhb_data, \
    find_top_yyb_trades
from fetch.tonghuashun.fupan import all_fupan
from fetch.tonghuashun.fupan_plot import draw_fupan_lb
from fetch.tonghuashun.hotpoint_analyze import hot_words_cloud
from filters.find_abnormal import find_serious_abnormal_stocks_range
from filters.find_longtou import find_dragon_stocks


# 回溯交易
def backtrade_simulate():
    code = '601933'
    # simulator.go_trade(code)
    simulator.go_trade(code
                       , startdate=datetime(2024, 1, 1)
                       , enddate=datetime(2025, 3, 9)
                       )


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
    data_fetcher = StockDataFetcher(start_date='20250415', save_path='./data/astocks',
                                    max_workers=16)
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
    start_date = '2025-01-01'
    # end_date = '2025-02-28'
    end_date = None
    find_dragon_stocks(start_date, end_date, threshold=180)


def find_yidong():
    # date = '2025-04-28'
    # find_serious_abnormal_stocks(date, check_updown_fluctuation=False)

    start_date = '2025-04-15'
    end_date = None
    find_serious_abnormal_stocks_range(start_date, end_date)


def get_stock_concept_and_industry():
    fetch_and_save_stock_concept(
        concept_list=["云游戏", "新能源车"],
        industry_list=["银行", "房地产"],
        output_path="./excel/all_concepts.xlsx"
    )


def find_similar_trends():
    formatter = "%Y%m%d"
    data_dir = "./data/astocks"  # 数据文件所在目录
    target_stock_code = "601086"  # 目标股票代码
    start_date = datetime.strptime('20250407', formatter)
    end_date = datetime.strptime('20250416', formatter)
    trend_end_date = datetime.strptime('20250428', formatter)  # 被查找个股的趋势结束日期

    # 1.寻找自身相似时期
    # target_index_code = "sz399001"  # 目标指数代码
    # find_self_similar_windows(target_index_code, start_date, end_date, "./data/indexes", method="weighted")

    # 2.寻找同时期相似个股
    # 可选股票代码列表
    # stock_codes = [
    #     "600928",
    #     "601319",
    #     "001227"
    # ]
    stock_codes = None
    find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes, data_dir, method="weighted",
                              trend_end_date=trend_end_date, same_market=True)


def fetch_ths_fupan():
    start_date = "20250415"
    # end_date = '20250424'
    end_date = None
    all_fupan(start_date, end_date)


def draw_ths_fupan():
    start_date = '20250401'  # 开始日期
    # end_date = '20250115'  # 结束日期
    end_date = None
    draw_fupan_lb(start_date, end_date)


def fupan_statistics_to_excel():
    # 指定时段的复盘总体复盘数据
    start_date = '20250415'
    # end_date = '20250228'
    end_date = None
    fupan_all_statistics(start_date, end_date, max_workers=4)


def fupan_statistics_excel_plot():
    plot_all('20250401', '20250430')
    # plot_all()


def stocks_time_sharing_price():
    # 手动指定
    # stock_codes = ["002165", "002570", "600249", "001234", "601086"]
    # date_list = ["20250414", "20250415"]
    # analyze_stocks_time_sharing(stock_codes, date_list)

    # 读取异动文件
    dates_list = ["20250425", "20250428"]  # 可以指定多个日期
    analyze_abnormal_stocks_time_sharing(dates_list)


def analyze_advanced_on():
    start_date = '2025-04-20'
    end_date = None
    analyze_rate(start_date, end_date)


def daily_group_analyze():
    start_date = "20250423"
    end_date = None
    find_stocks_by_hot_themes(start_date, end_date, top_n=5, weight_factor=3)
    # highlight_repeated_stocks()


def whimsical_fupan_analyze():
    # 执行归类分析
    start_date = "20250414"
    end_date = "20250430"
    process_zt_data(start_date, end_date, clean_output=True)

    # 为【未分类原因】归类
    # consolidate_unclassified_reasons()



if __name__ == '__main__':
    # get_stock_datas()
    # fetch_ths_fupan()
    # draw_ths_fupan()
    whimsical_fupan_analyze()
    # analyze_advanced_on()
    # daily_group_analyze()
    # fupan_statistics_to_excel()
    # fupan_statistics_excel_plot()
    # get_hot_clouds()
    # find_yidong()
    # stocks_time_sharing_price()
    # find_dragon()
    # find_similar_trends()
    # get_stock_concept_and_industry()
    # fetch_and_filter_top_yybph()
    # get_top_yyb_trades()
    # get_lhb_datas()
    # get_stock_minute_datas()
    # backtrade_simulate()
    # get_index_data()
    # check_stock_datas()
