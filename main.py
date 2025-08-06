import logging
import warnings
import os
import sys
import io
from datetime import datetime
from contextlib import redirect_stdout

from bin.resilience_scanner import run_filter
from bin.scanner_analyzer import scan_and_visualize_analyzer
from bin.simulator import batch_backtrade_simulate
from strategy.breakout_strategy import BreakoutStrategy
from strategy.scannable_strategy import ScannableBreakoutStrategy
from strategy.hybrid_strategy import HybridStrategy
from strategy.market_regime import MarketRegimeStrategy
from strategy.origin_breakout_strategy import OriginBreakoutStrategy
from strategy.panic_rebound_strategy import PanicReboundStrategy
from strategy.regime_classifier_strategy import RegimeClassifierStrategy

# 忽略jieba库中的pkg_resources警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

from datetime import datetime
from analysis.calculate_limit_up_success_rate import analyze_rate
from analysis.daily_group import find_stocks_by_hot_themes
from analysis.dejavu import process_dejavu_data
from analysis.fupan_statistics import fupan_all_statistics
from analysis.fupan_statistics_plot import plot_all
from analysis.seek_historical_similar import find_other_similar_trends
from analysis.stock_price_plotter import plot_multiple_stocks
from analysis.time_price_sharing import analyze_abnormal_stocks_time_sharing
from analysis.whimsical import process_zt_data, add_vba_for_excel
from analysis.ladder_chart import build_ladder_chart
from bin import simulator
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import StockDataFetcher, StockDataBroker
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.indexes_data import fetch_indexes_data
from fetch.lhb_data import fetch_and_merge_stock_lhb_detail, fetch_and_filter_yybph_lhb_data, fetch_yyb_lhb_data, \
    find_top_yyb_trades
from fetch.tonghuashun.fupan import all_fupan
from fetch.tonghuashun.fupan_plot import draw_fupan_lb
from fetch.tonghuashun.hotpoint_analyze import hot_words_cloud
from filters.find_abnormal import find_serious_abnormal_stocks_range
from filters.find_longtou import find_dragon_stocks
from utils.synonym_manager import SynonymManager
from bin.scanner import scan_and_visualize

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(threadName)s] %(levelname)s - %(message)s')


# 回溯交易
def backtrade_simulate():
    # 批量回测
    batch_backtrade_simulate()

    # 单个回测
    # stock_code = '002104'
    # simulator.go_trade(
    #     code=stock_code,
    #     amount=100000,
    #     startdate=datetime(2022, 1, 1),
    #     enddate=datetime(2025, 7, 4),
    #     strategy=BreakoutStrategy,
    #     strategy_params={'debug': True},  # 开启详细日志
    #     log_trades=True,
    #     visualize=True,
    #     interactive_plot=True,  # 弹出交互图
    # )


def strategy_scan(candidate_model='a'):
    # 使用更精确的信号模式列表
    signal_patterns = [
        # '*** 触发【突破观察哨】',
        # '突破信号',
        '*** 二次确认信号',
    ]

    start_date = '20250530'
    end_date = '20250704'
    stock_pool = ['300581', '600475']
    details_after_date = '20250620'  # 只看这个日期之后的

    # 扫描与可视化
    scan_and_visualize_analyzer(
        scan_strategy=BreakoutStrategy,
        scan_start_date=start_date,
        scan_end_date=end_date,
        stock_pool=None,
        signal_patterns=signal_patterns,
        details_after_date=details_after_date,  # 只有此日期后信号才输出详情
        candidate_model=candidate_model
    )


def find_candidate_stocks():
    run_filter()


# 获取热点概念词云
def get_hot_clouds():
    hot_words_cloud(0)


def get_index_data():
    # 指定保存目录
    save_directory = "data/indexes"
    fetch_indexes_data(save_directory)


def execute_routine(steps, routine_name="自定义流程"):
    """
    通用的流程执行器
    
    Args:
        steps: 步骤列表，每个元素是 (function, description) 或 function
        routine_name: 流程名称，用于日志文件命名
    """
    import time
    import threading
    
    # 获取当前日期用于日志文件命名
    current_date = datetime.now().strftime('%Y%m%d')
    routine_name_safe = routine_name.replace(" ", "_")
    log_filename = f"logs/{routine_name_safe}_{current_date}_{datetime.now().strftime('%H%M%S')}.log"
    
    # 确保logs目录存在
    os.makedirs("logs", exist_ok=True)
    
    # 创建日志文件处理器
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - [%(threadName)s] %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # 获取根日志记录器并添加文件处理器
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    
    # 同时在控制台显示简化信息
    print(f"=== 开始{routine_name} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"详细日志保存到: {log_filename}")
    print(f"总共 {len(steps)} 个步骤")
    
    start_time = time.time()
    
    try:
        for i, step in enumerate(steps, 1):
            # 解析步骤配置
            if isinstance(step, tuple):
                func, description = step
            else:
                func = step
                description = func.__name__
            
            step_start_time = time.time()
            
            print(f"\n[步骤{i}/{len(steps)}] 开始{description}...")
            logging.info(f"=== 步骤{i}: 开始{description} ===")
            logging.info(f"当前主线程: {threading.current_thread().name}")
            logging.info(f"当前活跃线程数: {threading.active_count()}")
            
            # 执行步骤
            func()
            
            step_duration = time.time() - step_start_time
            logging.info(f"=== 步骤{i}: {description}完成 (耗时: {step_duration:.2f}秒) ===")
            logging.info(f"步骤完成后活跃线程数: {threading.active_count()}")
            print(f"✓ {description}完成 (耗时: {step_duration:.2f}秒)")
        
        total_duration = time.time() - start_time
        print(f"\n=== 所有步骤执行完成！总耗时: {total_duration:.2f}秒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
        logging.info(f"=== {routine_name}全部完成 (总耗时: {total_duration:.2f}秒) ===")
        
    except Exception as e:
        error_msg = f"执行过程中发生错误: {str(e)}"
        print(f"\n❌ {error_msg}")
        logging.error(error_msg, exc_info=True)
        raise
    finally:
        # 移除文件处理器，避免重复添加
        root_logger.removeHandler(file_handler)
        file_handler.close()
        print(f"\n详细日志已保存到: {log_filename}")


def daily_routine():
    """
    日常量化交易数据处理流程
    """
    # 定义日常流程步骤
    daily_steps = [
        (get_stock_datas, "拉取A股交易数据"),
        (fetch_ths_fupan, "拉取热门个股数据"), 
        (whimsical_fupan_analyze, "执行题材分析"),
        (generate_ladder_chart, "生成热门股天梯")
    ]
    
    execute_routine(daily_steps, "日常量化交易数据处理")


# 拉a股历史数据
def get_stock_datas():
    stock_list = ["600610", "300033"]
    use_realtime = True

    # 创建A股数据获取对象，指定拉取的天数和保存路径
    data_fetcher = StockDataFetcher(start_date='20250630', end_date=None, save_path='./data/astocks',
                                    max_workers=8, stock_list=None, force_update=False, max_sleep_time=2000)

    # 根据参数选择不同的数据获取方式
    if use_realtime:
        # 使用实时数据接口更新当天数据
        data_fetcher.fetch_and_save_data_from_realtime()
    else:
        # 使用历史数据接口获取数据（原有逻辑）
        data_fetcher.fetch_and_save_data()

    # 获取指数数据
    get_index_data()


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

    start_date = '2025-05-06'
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
    target_stock_code = "601068"  # 目标股票代码
    start_date = datetime.strptime('20250407', formatter)
    end_date = datetime.strptime('20250416', formatter)
    trend_end_date = datetime.strptime('20250618', formatter)  # 被查找个股的趋势结束日期

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
    start_date = "20250630"
    # end_date = '20250512'
    end_date = None
    # all_fupan(start_date, end_date)
    all_fupan(start_date, end_date, types='all,else')


def draw_ths_fupan():
    start_date = '20250610'  # 开始日期
    # end_date = '20250115'  # 结束日期
    end_date = None
    draw_fupan_lb(start_date, end_date)


def fupan_statistics_to_excel():
    # 指定时段的复盘总体复盘数据
    start_date = '20250530'
    # end_date = '20250228'
    end_date = None
    fupan_all_statistics(start_date, end_date, max_workers=4)


def fupan_statistics_excel_plot():
    start_date = '20250525'
    end_date = None
    plot_all(start_date, end_date)
    # plot_all()


def stocks_time_sharing_price():
    start_date = "20250512"
    end_date = "20250515"

    # 手动指定
    # stock_codes = ["600610", "601086", "302132", "002190", "002809"]
    stock_codes = ["603535", "002640", "600794", "603967", "603569"]
    # analyze_stocks_time_sharing(stock_codes, start_date, end_date)
    # 读取异动文件
    analyze_abnormal_stocks_time_sharing(start_date, end_date)


def plot_stock_daily_prices():
    # 指定股票代码列表和日期范围
    stock_codes = ["603399", "600036", "601318", "000001", "600000"]
    start_date = "20250430"
    end_date = "20250523"

    # 画出日对比图
    plot_multiple_stocks(stock_codes, start_date, end_date, equal_spacing=True)


def analyze_advanced_on():
    start_date = '2025-05-06'
    end_date = None
    analyze_rate(start_date, end_date)


def daily_group_analyze():
    start_date = "20250506"
    end_date = None
    find_stocks_by_hot_themes(start_date, end_date, top_n=5, weight_factor=3)
    # highlight_repeated_stocks()


def dejavu_fupan_analyze():
    # 示例用法
    start_date = "20250421"
    end_date = "20250516"

    # 处理连板数据
    process_dejavu_data(start_date, end_date)


def update_synonym_groups():
    """
    更新同义词分组，基于已有的涨停原因数据文件
    可用于自动更新theme_color_util.py中的synonym_groups
    """
    # 创建同义词分组管理器
    manager = SynonymManager(threshold=0.8, min_group_size=3)

    # 自动处理同义词分组更新
    manager.update_from_latest_file(debug_phrases=["一体化压铸"])


def whimsical_fupan_analyze():
    # 执行归类分析
    start_date = "20250630"
    end_date = None

    process_zt_data(start_date, end_date, clean_output=True)
    # add_vba_for_excel()

    # 为【未分类原因】归类1
    # consolidate_unclassified_reasons()


def generate_ladder_chart():
    start_date = '20250501'  # 调整为Excel中有数据的日期范围
    end_date = None  # 过了0点需指定日期
    min_board_level = 2
    non_main_board_level = 2
    show_period_change = True  # 是否计算周期涨跌幅
    sheet_name = None

    # 定义优先原因列表
    priority_reasons = [
        # "创新药"
    ]

    # 构建梯队图
    build_ladder_chart(start_date, end_date, min_board_level=min_board_level,
                       non_main_board_level=non_main_board_level, show_period_change=show_period_change,
                       priority_reasons=priority_reasons, enable_attention_criteria=True,
                       sheet_name=sheet_name)


if __name__ == '__main__':
    daily_routine()
    # backtrade_simulate()
    # find_candidate_stocks()
    # strategy_scan('a')
    # get_stock_datas()
    # fetch_ths_fupan()
    # draw_ths_fupan()
    # whimsical_fupan_analyze()
    # generate_ladder_chart()
    # update_synonym_groups()
    # fupan_statistics_to_excel()
    # fupan_statistics_excel_plot()
    # find_yidong()
    # daily_group_analyze()
    # analyze_advanced_on()
    # stocks_time_sharing_price()
    # plot_stock_daily_prices()
    # get_hot_clouds()
    # find_dragon()
    # find_similar_trends()
    # get_stock_concept_and_industry()
    # fetch_and_filter_top_yybph()
    # get_top_yyb_trades()
    # get_lhb_datas()
    # get_stock_minute_datas()
    # get_index_data()
    # check_stock_datas()
