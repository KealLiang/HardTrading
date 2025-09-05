import logging
import os
import warnings

from bin import simulator
from bin.resilience_scanner import run_filter
from bin.scanner_analyzer import scan_and_visualize_analyzer
from strategy.breakout_strategy import BreakoutStrategy
from strategy.breakout_strategy_v2 import BreakoutStrategyV2
from strategy.scannable_strategy import ScannableBreakoutStrategy
from strategy.hybrid_strategy import HybridStrategy
from strategy.market_regime import MarketRegimeStrategy
from strategy.origin_breakout_strategy import OriginBreakoutStrategy
from strategy.panic_rebound_strategy import PanicReboundStrategy
from strategy.regime_classifier_strategy import RegimeClassifierStrategy

from utils.logging_util import redirect_print_to_logger

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
from analysis.whimsical import process_zt_data
from analysis.ladder_chart import build_ladder_chart
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
from utils.synonym_manager import SynonymManager
from bin.experiment_runner import run_comparison_experiment
from bin.psq_analyzer import run_psq_analysis_report
from bin.parameter_optimizer import ParameterOptimizer

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(threadName)s] %(levelname)s - %(message)s')


def run_psq_analysis():
    """
    一键化PSQ综合分析报告的新入口
    """
    run_psq_analysis_report()


def run_parameter_optimization(config_name=None):
    """
    运行参数优化

    Args:
        config_name: 配置文件名称，如果为None则使用默认配置
    """
    optimizer = ParameterOptimizer()

    if config_name is None:
        # 生成默认配置模板
        print("未指定配置文件，生成默认配置模板...")
        template_path = optimizer.generate_config_template("default")
        print(f"默认配置模板已生成: {template_path}")
        print("请编辑配置文件后重新运行")
        return template_path
    else:
        # 运行优化
        config_path = f"bin/optimization_configs/{config_name}"
        if not config_name.endswith('.yaml'):
            config_path += '.yaml'

        if not os.path.exists(config_path):
            print(f"配置文件不存在: {config_path}")
            return None

        print(f"开始运行参数优化，配置文件: {config_path}")
        report_path = optimizer.run_optimization(config_path)
        print(f"参数优化完成！报告保存在: {report_path}")
        return report_path


def generate_optimization_templates():
    """
    生成各种类型的优化配置模板
    """
    optimizer = ParameterOptimizer()

    templates = {
        "default": "默认配置模板",
        "quick": "快速测试模板",
        "grid": "网格搜索模板",
        "compare": "参数文件对比模板"
    }

    generated_files = []
    for template_type, description in templates.items():
        if template_type == "compare":
            # compare模板不需要额外参数
            template_path = optimizer.generate_config_template(template_type=template_type)
        else:
            template_path = optimizer.generate_config_template(template_type=template_type,
                                                               strategy_class=BreakoutStrategy,
                                                               test_params=['consolidation_lookback',
                                                                            'consolidation_ma_proximity_pct',
                                                                            'consolidation_ma_max_slope'])
        generated_files.append(template_path)
        print(f"{description}已生成: {template_path}")

    print(f"\n总共生成了 {len(generated_files)} 个配置模板")
    print("请根据需要编辑配置文件，然后运行参数优化")

    return generated_files


# 回溯交易
def backtrade_simulate():
    # 批量回测并对比
    # run_comparison_experiment()

    # 单个回测
    stock_code = '300059'
    simulator.go_trade(
        code=stock_code,
        amount=100000,
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 8, 22),
        strategy=BreakoutStrategyV2,
        strategy_params={'debug': True},  # 开启详细日志
        log_trades=True,
        visualize=True,
        interactive_plot=True,  # 弹出交互图
    )


def strategy_scan(candidate_model='a'):
    # 使用更精确的信号模式列表
    signal_patterns = [
        # '*** 触发【突破观察哨】',
        # '突破信号',
        '*** 二次确认信号',
    ]

    start_date = '20250630'
    end_date = None
    stock_pool = ['300581', '600475']
    details_after_date = '20250815'  # 只看这个日期之后的

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
    import matplotlib

    # 设置matplotlib使用非交互式后端，避免Tkinter线程问题
    matplotlib.use('Agg')

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

    # 创建print输出重定向的logger
    # 设置propagate=False防止日志向上传播到root logger，避免重复记录
    print_logger = logging.getLogger('print_capture')
    print_logger.propagate = False
    print_logger.addHandler(file_handler)

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

            # 使用上下文管理器重定向print到日志文件（只在步骤执行期间）
            with redirect_print_to_logger(print_logger):
                # 执行步骤
                func()

            step_duration = time.time() - step_start_time
            logging.info(f"=== 步骤{i}: {description}完成 (耗时: {step_duration:.2f}秒) ===")
            logging.info(f"步骤完成后活跃线程数: {threading.active_count()}")
            print(f"✓ {description}完成 (耗时: {step_duration:.2f}秒)")

        total_duration = time.time() - start_time
        print(
            f"\n=== 所有步骤执行完成！总耗时: {total_duration:.2f}秒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
        logging.info(f"=== {routine_name}全部完成 (总耗时: {total_duration:.2f}秒) ===")

    except Exception as e:
        error_msg = f"执行过程中发生错误: {str(e)}"
        print(f"\n❌ {error_msg}")
        logging.error(error_msg, exc_info=True)
        raise
    finally:
        # 移除文件处理器，避免重复添加
        root_logger.removeHandler(file_handler)
        print_logger.removeHandler(file_handler)
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
        (generate_ladder_chart, "生成热门股天梯"),
        (draw_ths_fupan, "绘制涨跌高度图"),
        (fupan_statistics_to_excel, "生成统计数据"),
        (fupan_statistics_excel_plot, "生成统计图表"),
    ]

    execute_routine(daily_steps, "daily_routine")


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
    start_date = "20250830"
    # end_date = '20250512'
    end_date = None
    # all_fupan(start_date, end_date)
    all_fupan(start_date, end_date, types='all,else')


def draw_ths_fupan():
    start_date = '20250620'  # 开始日期
    # end_date = '20250115'  # 结束日期
    end_date = None
    draw_fupan_lb(start_date, end_date)


def fupan_statistics_to_excel():
    # 指定时段的复盘总体复盘数据
    start_date = '20250810'
    # end_date = '20250228'
    end_date = None
    # 在daily_routine中强制使用单线程，避免多线程冲突
    fupan_all_statistics(start_date, end_date, max_workers=1)


def fupan_statistics_excel_plot():
    start_date = '20250810'
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
    start_date = "20250720"
    end_date = None

    process_zt_data(start_date, end_date, clean_output=True)
    # add_vba_for_excel()

    # 为【未分类原因】归类1
    # consolidate_unclassified_reasons()


def generate_ladder_chart():
    start_date = '20250715'  # 调整为Excel中有数据的日期范围
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
                       sheet_name=sheet_name, create_leader_sheet=True)


def generate_comparison_charts():
    """
    生成股票信号对比图 - 根据信号日期分组，便于对比查看
    """
    from bin.comparison_chart_generator import ComparisonChartGenerator

    # 自动查找最新的scan_summary文件
    base_dir = 'bin/candidate_stocks_result'
    summary_files = [f for f in os.listdir(base_dir) if f.startswith('scan_summary_') and f.endswith('.txt')]

    if not summary_files:
        print("没有找到scan_summary文件，请先运行strategy_scan()生成扫描结果")
        return

    # 选择最新的summary文件
    latest_summary = sorted(summary_files)[-1]
    summary_path = os.path.join(base_dir, latest_summary)

    print(f"使用summary文件: {summary_path}")

    # 创建生成器并生成对比图
    generator = ComparisonChartGenerator(base_dir)
    generated_files = generator.generate_recent_comparisons(summary_path, recent_days=10)

    if generated_files:
        print(f"\n✅ 成功生成 {len(generated_files)} 张对比图")
        print(f"📁 对比图保存位置: {generator.comparison_dir}")
        print("\n生成的对比图:")
        for file in generated_files:
            print(f"  📊 {os.path.basename(file)}")
    else:
        print("❌ 没有生成任何对比图，请检查数据完整性")


if __name__ == '__main__':
    # === 参数优化功能 ===
    # 1. 生成配置模板
    # generate_optimization_templates()
    # 2. 运行参数优化（需要先生成并编辑配置文件）
    # run_parameter_optimization("compare_config.yaml")

    # === 原有功能 ===
    # daily_routine()
    # backtrade_simulate()
    # run_psq_analysis()
    # find_candidate_stocks()
    # strategy_scan('a')
    # generate_comparison_charts()
    # get_stock_datas()
    fetch_ths_fupan()
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
