import logging
import os
import warnings

from bin import simulator
from bin.resilience_scanner import run_filter
from bin.scanner_analyzer import scan_and_visualize_analyzer
from strategy.breakout_strategy import BreakoutStrategy
from strategy.breakout_strategy_v2 import BreakoutStrategyV2
from strategy.pullback_rebound_strategy import PullbackReboundStrategy
from strategy.scannable_pullback_rebound_strategy import ScannablePullbackReboundStrategy
from strategy.weekly_volume_momentum_strategy import WeeklyVolumeMomentumStrategy

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
from analysis.erban_longtou_analyzer import analyze_erban_longtou
from fetch.astock_concept import fetch_and_save_stock_concept
from fetch.astock_data import StockDataFetcher
from fetch.astock_data_minutes import fetch_and_save_stock_data
from fetch.indexes_data import fetch_indexes_data
from fetch.lhb_data import fetch_and_merge_stock_lhb_detail, fetch_and_filter_yybph_lhb_data, fetch_yyb_lhb_data, \
    find_top_yyb_trades
from fetch.tonghuashun.fupan import all_fupan
from fetch.tonghuashun.fupan_cleaner import clean_all_fupan_files, clean_fupan_excel
from fetch.tonghuashun.fupan_plot import draw_fupan_lb
from fetch.tonghuashun.fupan_plot_html import draw_fupan_lb_html
from fetch.tonghuashun.hotpoint_analyze import hot_words_cloud
from analysis.html_gen.momo_shangzhang_html_chart import generate_momo_html_charts

from filters.find_abnormal import find_serious_abnormal_stocks_range
from filters.find_longtou import find_dragon_stocks
from utils.synonym_manager import SynonymManager
from bin.psq_analyzer import run_psq_analysis_report
from bin.parameter_optimizer import ParameterOptimizer
from bin.batch_backtester import batch_backtest_from_file, batch_backtest_from_list
from bin.selection_history_tracker import record_from_directory
from utils.backtrade.selection_review_visualizer import review_historical_selections

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
    # stock_code = '300128'
    # stock_code = '301217'
    stock_code = '603232'
    simulator.go_trade(
        code=stock_code,
        amount=100000,
        startdate=datetime(2025, 1, 1),
        enddate=datetime(2025, 10, 31),
        strategy=BreakoutStrategy,
        strategy_params={'debug': True, 'enable_prior_high_score': True},  # 开启详细日志
        log_trades=True,
        visualize=True,
        interactive_plot=True,  # 弹出交互图
    )


# 大批量回测（从文件读取股票列表）
def batch_backtest_from_stock_list():
    """
    大批量股票回测 - 从文件读取股票列表
    
    特点：
    1. 支持从CSV/TXT文件读取股票列表
    2. 多进程并行回测，大幅提升性能
    3. 只输出汇总统计，不生成详细图表
    4. 生成Excel汇总报告，包含统计分析
    
    使用场景：
    - 全市场扫描（如5000只A股）
    - 板块批量回测
    - 策略批量验证
    """
    # 股票列表文件路径（支持CSV或TXT格式）
    stock_list_file = 'data/batch_backtest/all_astocks.txt'  # 可以替换为你的文件路径

    # 如果没有现成文件，也可以直接使用代码列表（见下面的batch_backtest_from_codes函数）

    report_path = batch_backtest_from_file(
        stock_list_file=stock_list_file,
        strategy_class=BreakoutStrategyV2,
        strategy_params={
            'debug': False,  # 批量回测建议关闭详细日志
        },
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 10, 21),
        amount=100000,
        data_dir='./data/astocks',
        output_dir='bin/batch_backtest_results',
        max_workers=None,  # None表示自动使用CPU核心数-1，也可手动指定如4、8等
        resume=False  # 是否断点续传（跳过已完成的股票）
    )

    print(f"\n批量回测完成！报告路径: {report_path}")


# 大批量回测（直接使用代码列表）
def batch_backtest_from_codes():
    """
    大批量股票回测 - 直接提供股票代码列表
    
    适合代码不多的场景，或者动态生成股票池的场景
    """
    # 方式1: 手动指定股票列表
    stock_codes = ['300033', '300059', '000062', '300204', '600610', '002693', '301357', '600744', '002173', '002640',
                   '002104', '002658']

    # 方式2: 从其他来源获取（示例：读取某个板块的所有股票）
    # from fetch.astock_concept import get_concept_stocks
    # stock_codes = get_concept_stocks('新能源车')

    report_path = batch_backtest_from_list(
        stock_codes=stock_codes,
        strategy_class=BreakoutStrategyV2,
        strategy_params={'debug': False},
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 10, 27),
        amount=100000,
        data_dir='./data/astocks',
        output_dir='bin/batch_backtest_results',
        max_workers=4  # 可根据CPU核心数调整
    )

    print(f"\n批量回测完成！报告路径: {report_path}")


# 生成批量回测用的股票列表
def generate_stock_lists():
    """
    从数据目录生成股票列表文件，为批量回测做准备
    
    功能：
    - 生成全部A股列表
    - 按市场分类（沪市、深市、北交所）
    - 按板块分类（主板、创业板、科创板）
    
    输出目录：data/batch_backtest/
    """
    from bin.generate_stock_list import generate_all
    generate_all()


# 从复盘数据生成批量回测候选股
def generate_fupan_candidates():
    """
    从复盘数据文件提取热门股作为批量回测候选
    
    功能：
    - 从 excel/fupan_stocks.xlsx 提取指定类型的股票
    - 支持按日期范围筛选
    - 支持多个sheet组合（如连板+首板+大涨）
    
    使用场景：
    - 回测特定时期的热门股表现
    - 验证策略在强势股上的效果
    - 缩小回测范围提高效率
    """
    from bin.generate_stock_list import generate_fupan_stock_list

    # 示例1: 提取多种类型的热门股
    generate_fupan_stock_list(
        sheet_names=['连板数据', '默默上涨', '关注度榜', '非主关注度榜'],
        start_date='20250901',
        end_date='20251020',
        output_prefix='hot_stocks_202509'
    )

    # 示例2: 提取所有类型的股票（不限日期）
    # generate_fupan_stock_list(
    #     sheet_names=None,  # None表示所有sheet
    #     start_date=None,   # None表示从最早开始
    #     end_date=None,     # None表示到最晚
    #     output_prefix='all_fupan_stocks'
    # )


# 止跌反弹策略回测
def pullback_rebound_simulate():
    """
    止跌反弹策略回测示例
    
    策略说明：
    - 识别主升浪后的回调企稳机会
    - 通过量价背离、量窒息、企稳K线三个信号判断反弹时机
    - 止盈12%、止损5%、最大持有10天
    """
    stock_code = '002554'  # 可以替换为其他股票代码
    simulator.go_trade(
        code=stock_code,
        amount=100000,
        startdate=datetime(2025, 9, 1),
        enddate=datetime(2025, 10, 31),
        strategy=PullbackReboundStrategy,
        strategy_params={
            # -- 调试参数 --
            'debug': True,  # 是否开启详细日志

            # -- 主升浪识别参数（可调整）--
            'uptrend_min_gain': 0.30,  # 主升浪最小涨幅30%，越大越严格
            'volume_surge_ratio': 1.5,  # 主升浪放量倍数，越大要求越高

            # -- 回调识别参数（可调整）--
            # 'pullback_max_ratio': 0.5,  # 最大回调幅度50%
            # 'pullback_max_days': 15,    # 最大回调天数15天

            # -- 交易参数（可调整）--
            # 'initial_stake_pct': 0.8,   # 初始仓位80%
            # 'profit_target': 0.12,      # 止盈目标12%
            # 'stop_loss': 0.05,          # 止损比例5%
            # 'max_hold_days': 10,        # 最大持有天数10天
        },
        log_trades=True,
        visualize=True,
        interactive_plot=True,  # 弹出交互图
    )


# 周量能放大策略回测
def weekly_volume_momentum_simulate():
    """周量能放大 + 短期温和上行 策略回测示例"""
    stock_code = '000009'  # 可替换标的
    simulator.go_trade(
        code=stock_code,
        amount=100000,
        startdate=datetime(2021, 1, 1),
        enddate=datetime(2025, 10, 13),
        strategy=WeeklyVolumeMomentumStrategy,
        strategy_params={
            'debug': True,
            'week_window': 5,
            'week_growth_ratio': 2.0,
            'three_month_lookback_days': 60,
            'three_month_max_change': 0.401,
            'gap_open_exclude_pct': 0.05,
            'daily_gain_upper_pct': 0.045,
            'initial_stake_pct': 1.0,
            'base_hold_days': 2,
            'stop_loss_pct': 0.05,
            'trigger_trailing_profit_pct': 0.09,
            'trailing_drawdown_pct': 0.01,
        },
        log_trades=True,
        visualize=True,
        interactive_plot=True,
    )


def strategy_scan(candidate_model='a'):
    # 使用更精确的信号模式列表
    signal_patterns = [
        # '*** 触发【突破观察哨】',
        # '突破信号',
        '*** 二次确认信号',  # 标准通道：观察期内二次确认
        '买入信号: 快速通道',  # 快速通道：信号日当天买入
        '买入信号: 回踩确认',  # 缓冲通道：回调后买入
        '买入信号: 止损纠错',  # 止损纠错：价格合适买入
    ]

    start_date = '20251215'
    end_date = None
    stock_pool = ['300581', '600475']
    details_after_date = '20251230'  # 只看这个日期之后的

    # 扫描与可视化
    scan_and_visualize_analyzer(
        scan_strategy=BreakoutStrategy,
        scan_start_date=start_date,
        scan_end_date=end_date,
        stock_pool=None,
        signal_patterns=signal_patterns,
        details_after_date=details_after_date,  # 只有此日期后信号才输出详情
        candidate_model=candidate_model,
        output_path=f'bin/candidate_stocks_breakout_{candidate_model}',  # 指定输出目录，按模型区分
        generate_images=False  # 默认False，跳过PNG图片生成以提升速度（已有HTML图表）
    )


def pullback_rebound_scan(candidate_model='a'):
    """止跌反弹策略扫描"""
    # 使用止跌反弹策略的信号模式
    signal_patterns = [
        '*** 止跌反弹买入信号触发',
        '止跌反弹信号',
    ]

    start_date = '20250910'
    end_date = None
    details_after_date = '20251015'  # 只看这个日期之后的

    # 扫描与可视化
    scan_and_visualize_analyzer(
        scan_strategy=ScannablePullbackReboundStrategy,
        scan_start_date=start_date,
        scan_end_date=end_date,
        stock_pool=None,
        signal_patterns=signal_patterns,
        details_after_date=details_after_date,  # 只有此日期后信号才输出详情
        candidate_model=candidate_model,
        output_path=f'bin/candidate_stocks_rebound_{candidate_model}'  # 指定输出目录，按模型区分
    )


def find_candidate_stocks():
    run_filter()


def find_candidate_stocks_weekly_growth(offset_days: int = 0):
    """
    周成交量增长策略选股
    
    Args:
        offset_days: 时间偏移量（天数），默认0
            - 0: 以T日为基准（今天）
            - 1: 以T-1日为基准（昨天）
            - N: 以T-N日为基准
    """
    # 使用新的"周量增+当日条件"筛选器
    from bin.weekly_growth_scanner import run_filter as run_weekly_filter
    run_weekly_filter(offset_days=offset_days)


def find_candidate_stocks_volume_surge(base_date: str = None):
    """
    成交量金叉策略选股
    
    策略条件：
    1. 最近30个交易日股价平稳（振幅小于股票涨跌幅限制的2倍）
    2. 成交量的5日均线和10日均线，30日内出现至少2次金叉，且最近一次金叉是5天内
    
    Args:
        base_date: 基准日期，格式为 'YYYYMMDD' 或 'YYYY-MM-DD'，如果为None则使用今天
            - 策略只使用基准日之前（含当日）的数据，避免使用未来数据
            - 例如：base_date='20251210' 表示以2025年12月10日为基准日进行筛选
    
    Returns:
        str: 输出文件路径
    """
    from bin.volume_surge_scanner import run_filter as run_volume_surge_filter
    run_volume_surge_filter(base_date=base_date)


def record_scan_to_history(base_dir: str, model: str):
    """
    记录扫描结果到历史文件
    
    Args:
        base_dir: 扫描结果目录
        model: 模式标识 (如 'breakout_a', 'rebound_a', 'breakout_b')
    """
    try:
        record_from_directory(base_dir, model)
        logging.info(f"已记录 {model} 模式的扫描结果到历史文件")
    except Exception as e:
        logging.error(f"记录扫描结果到历史文件失败: {e}")


def review_history(start_date: str, end_date: str, model: str = None, before_days: int = 90):
    """
    回顾历史候选股的后续走势
    
    Args:
        start_date: 开始日期 (信号日期)，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        end_date: 结束日期 (信号日期)，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        model: 模式筛选，如 'rebound_a', 'breakout_a', 'breakout_b'，None表示全部
        before_days: 信号日期之前显示的天数（默认90天）
    
    Returns:
        生成的对比图文件列表
    
    示例:
        # 回顾10月20日到10月24日所有模式的候选股
        review_history('2025-10-20', '2025-10-24')
        
        # 只回顾止跌反弹策略a的候选股
        review_history('2025-10-20', '2025-10-24', model='rebound_a')
    """
    try:
        files = review_historical_selections(start_date, end_date, model, before_days)

        if files:
            print(f"\n✅ 成功生成 {len(files)} 张回顾对比图")
            print(f"📁 回顾图保存在: bin/candidate_history/review_charts/")
            print("\n生成的回顾图:")
            for file in files:
                print(f"  📊 {os.path.basename(file)}")
        else:
            print("❌ 未找到符合条件的历史记录或生成失败")

        return files

    except Exception as e:
        logging.error(f"回顾历史记录失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return []


def analyze_weekly_growth_win_rate(scan_file: str = None, high_ratio: float = 0.25, close_ratio: float = 0.75):
    """
    分析周成交量增长策略的胜率
    
    Args:
        scan_file: 扫描文件路径（默认分析最新文件）
        high_ratio: T+2日高点卖出比例（默认0.25，即1/4）
        close_ratio: T+2日收盘卖出比例（默认0.75，即3/4）
    
    交易逻辑:
        - T日收盘后扫描
        - T+1日开盘价买入
        - T+2日高点卖出 high_ratio 仓位
        - T+2日收盘卖出 close_ratio 仓位
    """
    from bin.weekly_growth_win_rate_analyzer import analyze_latest_or_specified
    return analyze_latest_or_specified(scan_file, high_ratio, close_ratio)


def batch_analyze_weekly_growth_win_rate(directory: str = 'bin/candidate_temp',
                                         pattern: str = r'candidate_stocks_weekly_growth_\d{8}\.txt$',
                                         high_ratio: float = 0.25,
                                         close_ratio: float = 0.75):
    """
    批量分析目录下所有扫描文件的胜率，生成单一汇总报告
    
    Args:
        directory: 扫描文件目录（默认bin/candidate_temp）
        pattern: 文件名正则匹配模式（默认只匹配weekly_growth格式）
        high_ratio: T+2日高点卖出比例（默认0.25）
        close_ratio: T+2日收盘卖出比例（默认0.75）
    
    Returns:
        str: 生成的批量报告文件路径
    
    报告内容:
        - 整体汇总统计
        - 各日期统计数据
        - 附录：每个日期的盈利TOP3和亏损TOP3
    """
    from bin.weekly_growth_win_rate_analyzer import batch_analyze_with_pattern
    return batch_analyze_with_pattern(directory, pattern, high_ratio, close_ratio)


# 获取热点概念词云
def get_hot_clouds(date: str = None, concept_only: bool = True):
    """
    生成每日A股热门股的概念词云图
    
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'，默认为 None 表示最近一个交易日
        concept_only: 是否仅生成概念词云图，默认为 True。为 False 时生成概念+行业合并图
    """
    hot_words_cloud(date, concept_only)


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
        (get_index_data, "拉取各大指数数据"),
        (fetch_ths_fupan, "拉取热门个股数据"),
        (whimsical_fupan_analyze, "执行题材分析"),
        (generate_ladder_chart, "生成热门股天梯"),
        (draw_ths_fupan, "绘制涨跌高度图"),
        (draw_ths_fupan_html, "生成涨跌高度html"),
        (lambda: generate_momo_html_charts(days=20, columns=2, after_days=20), "默默上涨生成html走势图"),
        (fupan_statistics_to_excel, "生成统计数据"),
        (fupan_statistics_excel_plot, "生成统计图表"),
        (get_hot_clouds, "生成热门概念词云"),
        # (auction_fengdan_analyze, "复盘分析封单数据"),
        (lambda: analyze_volume_surge_pattern('20260110', min_lianban=2, continuous_surge_days=3, volume_surge_ratio=(1.8, 2.0, 3.0), volume_avg_days=5),
         "爆量分歧转一致筛选"),
    ]

    execute_routine(daily_steps, "daily_routine")


def full_scan_routine(candidate_model='a'):
    """
    一键执行完整的策略扫描和对比图生成流程
    """
    scan_steps = [
        (lambda: strategy_scan(candidate_model), "执行突破策略扫描"),
        (lambda: generate_comparison_charts(candidate_model), "生成突破策略对比图"),
        (lambda: record_scan_to_history(f'bin/candidate_stocks_breakout_{candidate_model}', f'breakout_{candidate_model}'),
         f"记录突破策略{candidate_model}扫描结果"),
        # (lambda: pullback_rebound_scan(candidate_model), "执行止跌反弹策略扫描"),
        # (lambda: generate_rebound_comparison_charts(candidate_model), "生成止跌反弹策略对比图"),
        # (lambda: record_scan_to_history(f'bin/candidate_stocks_rebound_{candidate_model}', f'rebound_{candidate_model}'),
        #  f"记录止跌反弹策略{candidate_model}扫描结果"),
        # (lambda: find_candidate_stocks_weekly_growth(), "筛选周增长的候选股"),
        # (lambda: strategy_scan('b'), "执行突破策略扫描b"),
        # (lambda: generate_comparison_charts('b'), "生成突破策略对比图b"),
        # (lambda: record_scan_to_history('bin/candidate_stocks_breakout_b', 'breakout_b'),
        #  "记录突破策略b扫描结果"),
    ]

    execute_routine(scan_steps, "full_scan_routine")


# 拉a股历史数据
def get_stock_datas():
    stock_list = ["600610", "300033"]
    use_realtime = True

    # 创建A股数据获取对象，指定拉取的天数和保存路径
    data_fetcher = StockDataFetcher(start_date='20250930', end_date=None, save_path='./data/astocks',
                                    max_workers=8, stock_list=None, force_update=False, max_sleep_time=2000)

    # 根据参数选择不同的数据获取方式
    if use_realtime:
        # 使用实时数据接口更新当天数据
        data_fetcher.fetch_and_save_data_from_realtime()
    else:
        # 使用历史数据接口获取数据（原有逻辑）
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
    data_dir = "./data/astocks"  # 数据文件所在目录
    target_stock_code = "300611"  # 目标股票代码
    start_date = '20250911'  # 目标股票的起始日期（字符串格式 YYYYMMDD）
    end_date = '20251023'  # 目标股票的结束日期

    # 1.寻找自身相似时期
    # target_index_code = "sz399001"  # 目标指数代码
    # find_self_similar_windows(target_index_code, '20250815', '20251014', "./data/indexes", method="weighted")

    # 2.寻找同时期相似个股
    # 可选股票代码列表
    # stock_codes = [
    #     "600928",
    #     "601319",
    #     "001227"
    # ]
    stock_codes = None

    # ============= 相似度计算方法说明 =============
    # method可选值：
    # - "close_price": 仅收盘价相关性（最快但最粗糙）
    # - "weighted": 原加权相关性（快速，适合粗略筛选）
    # - "enhanced_weighted": 增强版加权相关性（推荐！考虑量价配合和阶段性特征）
    # - "dtw": DTW动态时间规整（最精确但最慢）

    # ============= 执行相似趋势查找（先选择模式） =============
    # 模式1: 单一结束日期（适合确定某个时点的相似走势）
    trend_end_date = '20251023'  # 被查找股票的趋势结束日期
    trend_date_range = None  # 设为None表示使用单一日期模式
    search_step = None  # 单一日期无步长

    # 模式2: 时间段扫描（适合查找历史上任意时期的相似走势）⭐推荐
    # trend_end_date = None
    # trend_date_range = ('20250716', '20251015')  # 在这个时间段内滑动窗口查找
    # search_step = 5  # ⚠️ 步长设置影响结果，小步长极大影响性能：如果单一日期能找到高相似度，但时间段找不到，说明步长太大了！

    find_other_similar_trends(
        target_stock_code, start_date, end_date, stock_codes, data_dir,
        method="weighted",  # 使用增强版方法
        trend_end_date=trend_end_date,  # 模式1参数
        trend_date_range=trend_date_range,  # 模式2参数（优先级更高）
        search_step=search_step,  # 可选：自定义步长（仅模式2有效）
        same_market=True
    )


def fetch_ths_fupan():
    start_date = "20251201"
    # end_date = '20251230'
    end_date = None
    # all_fupan(start_date, end_date)
    all_fupan(start_date, end_date, types='all,else')


def clean_ths_fupan():
    """
    清理 fupan_stocks.xlsx 历史数据，控制文件大小
    
    - 保留最近 keep_days 天的数据
    - 删除前自动备份（备份文件名含起止日期）
    - dry_run=True 时只预览不实际删除
    """
    keep_days = 150  # 保留最近x天数据
    dry_run = False  # 设为 True 可先预览要删除的数据
    
    # 清理所有 fupan 文件（fupan_stocks.xlsx 和 fupan_stocks_non_main.xlsx）
    clean_all_fupan_files(keep_days=keep_days, dry_run=dry_run)
    
    # 或者只清理单个文件：
    # clean_fupan_excel('./excel/fupan_stocks.xlsx', keep_days=keep_days, dry_run=dry_run)


def draw_ths_fupan():
    start_date = '20251201'  # 开始日期
    # end_date = '20251230'  # 结束日期
    end_date = None
    draw_fupan_lb(start_date, end_date)


def draw_ths_fupan_html():
    """
    生成HTML交互式复盘图
    """
    start_date = '20250930'  # 开始日期
    # end_date = '20260108'  # 结束日期
    end_date = None
    draw_fupan_lb_html(start_date, end_date, buy_days_before=1)


def fupan_statistics_to_excel():
    # 指定时段的复盘总体复盘数据
    start_date = '20250930'
    # end_date = '20250228'
    end_date = None
    # 在daily_routine中强制使用单线程，避免多线程冲突
    fupan_all_statistics(start_date, end_date, max_workers=1)


def fupan_statistics_excel_plot():
    start_date = '20251101'
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


def clean_synonym_groups(lookback_days=60, dry_run=False):
    """
    清理synonym_groups中未使用的旧概念词
    """
    from utils.synonym_cleaner import SynonymCleaner

    cleaner = SynonymCleaner(lookback_days=lookback_days)
    cleaner.clean(dry_run=dry_run)


def whimsical_fupan_analyze():
    # 执行归类分析
    start_date = "20251030"
    end_date = None

    process_zt_data(start_date, end_date, clean_output=True)
    # add_vba_for_excel()

    # 为【未分类原因】归类1
    # consolidate_unclassified_reasons()


def generate_ladder_chart():
    start_date = '20251030'  # 调整为Excel中有数据的日期范围
    end_date = None  # 过了0点需指定日期
    min_board_level = 2
    non_main_board_level = 2
    show_period_change = True  # 是否计算周期涨跌幅
    sheet_name = None

    # 定义优先原因列表
    priority_reasons = [
        # "海峡两岸",
    ]
    # 定义低优先原因列表（只有在没有其他分组可匹配时才使用）
    low_priority_reasons = [
        "预期改善"
    ]

    # 构建梯队图
    build_ladder_chart(start_date, end_date, min_board_level=min_board_level,
                       non_main_board_level=non_main_board_level, show_period_change=show_period_change,
                       priority_reasons=priority_reasons, low_priority_reasons=low_priority_reasons,
                       enable_attention_criteria=True, sheet_name=sheet_name,
                       create_leader_sheet=True, create_volume_sheet=True)

    # 导出股票代码到候选股票txt文件
    from utils.export_stock_codes import extract_stock_codes_from_excel
    from analysis.loader.fupan_data_loader import OUTPUT_FILE

    excel_file = OUTPUT_FILE
    output_txt = "bin/candidate_temp/candidate_stocks.txt"
    print("\n" + "=" * 60)
    extract_stock_codes_from_excel(excel_file, output_txt)
    print("=" * 60 + "\n")


def erban_longtou_analysis():
    """
    二板定龙头分析
    
    分析指定时间段内二连板股票的晋级率、胜率、题材特征和量价关系，
    生成Markdown格式的分析报告，帮助理解市场热点和龙头股特征。
    """
    # 配置参数
    start_date = '20251001'  # 开始日期
    end_date = '20251201'  # 结束日期，None表示到今天
    min_concept_samples = 2  # 题材统计最小样本数
    output_path = None  # 输出路径，None表示自动生成

    # 执行分析
    report_path = analyze_erban_longtou(
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
        min_concept_samples=min_concept_samples
    )

    if report_path:
        print(f"\n🎉 分析完成！报告已保存至: {report_path}")
    else:
        print("\n❌ 分析失败，未生成报告")


def generate_comparison_charts(candidate_model: str = 'a', recent_days: int = 10):
    """
    生成股票信号对比图 - 根据信号日期分组，便于对比查看

    Args:
        candidate_model: 使用的候选集模型标识（如 'a'、'b'），用于区分输出目录
        recent_days: 生成最近几天的对比图，默认10天
    """
    from bin.comparison_chart_generator import run_auto_generation
    base_dir = f'bin/candidate_stocks_breakout_{candidate_model}'
    return run_auto_generation(base_dir=base_dir, recent_days=recent_days)


def generate_rebound_comparison_charts(candidate_model: str = 'a', recent_days: int = 10):
    """
    生成止跌反弹策略的股票信号对比图

    Args:
        candidate_model: 使用的候选集模型标识（如 'a'、'b'），用于区分输出目录
        recent_days: 生成最近几天的对比图，默认10天
    """
    from bin.comparison_chart_generator import run_auto_generation
    base_dir = f'bin/candidate_stocks_rebound_{candidate_model}'
    return run_auto_generation(base_dir=base_dir, recent_days=recent_days)


def generate_strategy_scan_html_charts(candidate_model: str = 'a', recent_days: int = 10, 
                                       columns: int = 2, before_days: int = 60, after_days: int = 30):
    """
    生成策略扫描结果的HTML交互式图表
    
    根据scan_summary文件生成策略扫描入选股的HTML交互式图表，按股票分组展示。
    每只股票一张图，可以显示多个信号日期。一次执行只生成一个HTML文件。

    Args:
        candidate_model: 使用的候选集模型标识（如 'a'、'b'），用于区分输出目录
        recent_days: 只处理最近几天的信号，默认10天
        columns: 横向并排显示的列数（1、2或3），默认2
        before_days: 信号日前显示的交易日数，默认60
        after_days: 信号日后显示的交易日数，默认30
    """
    from analysis.html_gen.strategy_scan_html_chart import generate_strategy_scan_html_charts as gen_html
    base_dir = f'bin/candidate_stocks_breakout_{candidate_model}'
    return gen_html(
        base_dir=base_dir,
        recent_days=recent_days,
        columns=columns,
        before_days=before_days,
        after_days=after_days
    )


def auction_fengdan_analyze(date_str: str = None, show_plot: bool = False):
    """
    集合竞价封单数据复盘分析

    Args:
        date_str: 指定分析日期，格式YYYYMMDD，默认为最近交易日
        show_plot: 是否显示图表，默认False（避免阻塞）
    """
    from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer

    analyzer = AuctionFengdanAnalyzer()
    result = analyzer.run_comprehensive_analysis(date_str=date_str, show_plot=show_plot)

    if result:
        print(f"\n✅ 分析完成！")
        print(f"📅 分析日期: {result['date']}")
        print(f"📊 涨停: {result['zt_count']} 只，跌停: {result['dt_count']} 只，竞价封板: {result['auction_count']} 只")
        if result.get('report_file'):
            print(f"📄 分析报告: {result['report_file']}")
        if result.get('chart_file'):
            print(f"📊 分析图表: {result['chart_file']}")
    else:
        print("❌ 分析失败或无数据")


def analyze_lianban_stocks(start_date='20250101', end_date=None,
                           min_lianban=3, lianban_type=1,
                           before_days=30, after_days=10):
    """
    分析连板股票并生成K线图
    
    功能说明：
    - 从复盘数据中筛选指定时间段内的连板股
    - 为每只股票生成独立的K线图，便于找出连板股的共性
    - 生成汇总报告CSV
    
    Args:
        start_date: 开始日期，格式YYYYMMDD，默认'20250101'
        end_date: 结束日期，格式YYYYMMDD，默认'20250131'
        min_lianban: 最小连板数，默认3
        lianban_type: 连板类型，默认1
            - 1: 连续板（无断板）- 连续涨停天数 >= min_lianban
            - 2: 最高板 - 最高板数 >= min_lianban（可以有断板）
            - 3: 非连续板 - 最高板数 >= min_lianban 且有断板
        before_days: 首板前显示的交易日数，默认30
        after_days: 终止后显示的交易日数，默认10
    
    输出：
        - K线图保存在: analysis/pattern_charts/{连续板分析|最高板分析|非连续板分析}/{start_date}_{end_date}/
        - 汇总报告: summary.csv
    """
    from analysis.lianban_pattern_analyzer import LianbanPatternAnalyzer, LianbanPatternConfig

    # 创建配置
    config = LianbanPatternConfig(
        start_date=start_date,
        end_date=end_date,
        min_lianban_count=min_lianban,
        lianban_type=lianban_type,
        before_days=before_days,
        after_days=after_days
    )

    # 执行分析
    analyzer = LianbanPatternAnalyzer(config)
    analyzer.run()

    print(f"\n✅ 分析完成！共生成 {len(analyzer.filtered_stocks)} 张图表")
    print(f"📁 图表保存在: {analyzer.output_dir}")

    return analyzer.output_dir


def analyze_volume_surge_pattern(start_date='20250101', end_date=None,
                                 continuous_surge_days=2, volume_surge_ratio=(2.0, 3.0), volume_avg_days=5,
                                 min_lianban=2, before_days=50, after_days=10,
                                 min_pct_change=4.0,
                                 enable_attention_criteria=False, generate_charts=False, generate_html=True):
    """
    分析"爆量分歧转一致"形态并生成K线图
    
    形态定义：
    - 强势连板股在某日出现爆量（当日量能较近期明显放大）
    - 但当日仍然上涨（今收 > 昨收，不要求涨停）
    - 这种形态代表分歧后资金选择继续做多
    
    核心目的：
    - 寻找这类形态的规律
    - 观察后续走势
    - 分析什么时段什么形态的股票资金最愿意买入
    
    检测逻辑：
    - 从最长连续天数开始尝试，找到最长的满足条件的连续爆量期间
    - 对于每个候选期间，计算连续爆量开始之前的均量作为基准
    - 检查连续爆量期间的每一天是否都满足：上涨 + 涨幅阈值 + 量能阈值
    
    Args:
        start_date: 开始日期，格式YYYYMMDD，默认'20250101'
        end_date: 结束日期，格式YYYYMMDD，默认'20250131'
        continuous_surge_days: 连续爆量检测天数，默认2。如果单日爆量检测失败，
            则会检查最近N日是否每日连续爆量上涨，使用连续爆量开始之前的均量作为基准
        volume_surge_ratio: 爆量阈值（当日量/前N日均量），可以是单个值或元组。
            如果是元组，数量必须等于continuous_surge_days，不同连续天数对应不同阈值：
            - 连续N天使用第1个阈值
            - 连续N-1天使用第2个阈值
            - ...
            - 单日使用第N个阈值
            例如：continuous_surge_days=2时，volume_surge_ratio=(2.0, 3.0)表示
            连续2天需要>=2.0，单日需要>=3.0。默认(2.0, 3.0)表示连续2天需要>=2.0，单日需要>=3.0
        volume_avg_days: 计算均量的天数，默认5天
        min_lianban: 最小连板数，只分析达到此连板数的股票，默认2
        before_days: 形态日期前显示的交易日数，默认30
        after_days: 形态日期后显示的交易日数，默认10
        min_pct_change: 信号日最小涨幅(%)，默认3.0，用于过滤大阴线
        enable_attention_criteria: 是否启用关注度榜入选条件，默认为False。
            启用时，对于在关注度榜中的股票，连板数要求减1（例如min_lianban=2时，关注度榜股票只需1板即可）
        generate_charts: 是否生成图片，默认False。设为False时跳过图片生成，仅生成汇总报告，用于快速回测
        generate_html: 是否生成html图，默认True
    
    输出：
        - K线图保存在: analysis/pattern_charts/爆量分歧转一致/{start_date}_{end_date}/
        - 汇总报告: analysis/pattern_charts/爆量分歧转一致/{start_date}_{end_date}/summary.csv
    """
    from analysis.volume_surge_analyzer import VolumeSurgeAnalyzer, VolumeSurgeConfig

    # 创建配置
    config = VolumeSurgeConfig(
        start_date=start_date,
        end_date=end_date,
        volume_surge_ratio=volume_surge_ratio,
        volume_avg_days=volume_avg_days,
        min_lianban_count=min_lianban,
        before_days=before_days,
        after_days=after_days,
        min_pct_change=min_pct_change,
        continuous_surge_days=continuous_surge_days,
        enable_attention_criteria=enable_attention_criteria,
        generate_charts=generate_charts
    )

    # 执行分析
    analyzer = VolumeSurgeAnalyzer(config)
    analyzer.run()

    if generate_charts:
        print(f"\n✅ 分析完成！共生成 {len(analyzer.filtered_stocks)} 张图表")
        print(f"📁 图表保存在: {analyzer.output_dir}")

    # 生成HTML交互式图表（单个文件，支持1/2/3列布局）
    if generate_html:
        print("\n📊 开始生成HTML交互式图表...")
        html_path = analyzer.generate_html_charts(columns=2)  # 默认2列，可改为1或3
        if html_path:
            print(f"✅ HTML图表生成完成！")
            print(f"📁 HTML图表保存在: {html_path}")
        else:
            print("⚠️  未生成HTML图表")

    return analyzer.output_dir


def backtest_strategy(summary_csv_path: str,
                      strong_rule: str = 'or',
                      min_hold_days: int = 1,
                      max_hold_days: int = 30,
                      buy_price_range: tuple = None,
                      strong_price_range: tuple = None,
                      buy_mode: str = 'open'):
    """
    策略回测分析
    
    根据选股策略的信号数据（如summary.csv），回测分析胜率、盈亏比等指标。
    
    使用场景：
    1. 信号日(a日)运行选股
    2. 次日(a+1日)买入（根据buy_mode选择开盘价或涨停价买入，可设置买入价格范围限制）
    3. 持有条件：股票走强（根据strong_rule定义，可设置走强价格范围限制）
    4. 卖出条件：不再走强时以收盘价卖出
    5. T+1规则：最早a+2日可卖出
    
    Args:
        summary_csv_path: 信号汇总CSV文件路径
            例如: 'analysis/pattern_charts/爆量分歧转一致/20251130_20251223/summary.csv'
        strong_rule: 走强规则定义
            - 'or': 收盘>前日收盘 或 收盘>开盘（默认，最宽松）
            - 'and': 收盘>前日收盘 且 收盘>开盘（最严格）
            - 'prev': 仅收盘>前日收盘
            - 'open': 仅收盘>开盘
        min_hold_days: 最少持有天数，默认1（T+1规则）
        max_hold_days: 最大持有天数，默认30
        buy_price_range: 买入价格范围（开盘涨幅%），例如(-5, 6)表示-5%到6%
            - None: 不限制，总是买入（默认）
            - (min_pct, max_pct): 只有次日开盘涨幅在此范围内才买入
        strong_price_range: 走强价格范围（收盘涨幅%），例如(-2, 10)表示-2%到10%
            - None: 不限制，只要满足走强定义即视为走强（默认）
            - (min_pct, max_pct): 即使满足走强定义，收盘涨幅也必须在此范围内才算走强
              如果收盘涨幅不在范围内，视为"不再走强"，触发卖出
        buy_mode: 买入模式
            - 'open': 使用开盘价买入（默认，原有逻辑）
            - 'limit_up': 使用涨停价买入，要求建仓日最高价必须等于涨停价，否则放弃建仓
    
    输出：
        - 在CSV同目录下生成 backtest_report.md 报告
    
    使用示例：
        # 分析爆量分歧转一致策略的胜率
        backtest_strategy('analysis/pattern_charts/爆量分歧转一致/20251130_20251223/summary.csv')
        
        # 使用更严格的走强定义
        backtest_strategy('...summary.csv', strong_rule='and')
        
        # 只买入开盘涨幅在-5%到6%之间的股票
        backtest_strategy('...summary.csv', buy_price_range=(-5, 6))
        
        # 只持有收盘涨幅在-2%到10%之间的股票（即使满足走强定义）
        backtest_strategy('...summary.csv', strong_price_range=(-2, 10))
        
        # 使用涨停价买入模式（要求建仓日涨停）
        backtest_strategy('...summary.csv', buy_mode='limit_up')
    """
    from analysis.strategy_backtest_analyzer import run_backtest

    # 转换走强规则
    rule_mapping = {
        'or': 'close_gt_prev_close_or_open',
        'and': 'close_gt_prev_close_and_open',
        'prev': 'close_gt_prev_close',
        'open': 'close_gt_open'
    }
    strong_definition = rule_mapping.get(strong_rule, 'close_gt_prev_close_or_open')

    result = run_backtest(
        summary_csv_path=summary_csv_path,
        strong_definition=strong_definition,
        min_hold_days=min_hold_days,
        max_hold_days=max_hold_days,
        buy_price_range=buy_price_range,
        strong_price_range=strong_price_range,
        buy_mode=buy_mode
    )

    if result:
        print(f"\n{'=' * 50}")
        print(f"📊 回测结果摘要")
        print(f"{'=' * 50}")
        print(f"有效交易: {result.valid_trades} 笔")
        print(f"胜率: {result.win_rate:.1f}%")
        print(f"盈亏比: {result.profit_loss_ratio:.2f}")
        print(f"期望值: {result.expected_value:.2f}%")
        print(f"平均持有: {result.avg_hold_days:.1f} 天")
        print(f"{'=' * 50}")
    else:
        print("❌ 回测失败")

    return result


def analyze_open_minutes_pattern(summary_csv_path: str,
                                  strong_rule: str = 'or',
                                  min_hold_days: int = 1,
                                  max_hold_days: int = 30,
                                  buy_price_range: tuple = None,
                                  strong_price_range: tuple = None):
    """
    分析建仓日开盘前15分钟走势对交易成功率和赔率的影响
    
    根据选股策略的信号数据，回测分析后，进一步分析建仓日（a+1日）开盘前15分钟
    （9:30-9:45）的走势模式，结合开盘涨幅和开盘后走势，统计不同模式下的胜率和赔率。
    
    使用场景：
    1. 信号日(a日)运行选股
    2. 次日(a+1日)开盘买入
    3. 分析建仓日开盘前15分钟的走势模式
    4. 统计不同模式（如：平开且直接拉升、高开且先跌后拉等）的成功率和赔率
    
    Args:
        summary_csv_path: 信号汇总CSV文件路径
            例如: 'analysis/pattern_charts/爆量分歧转一致/20251201_20251226/summary.csv'
        strong_rule: 走强规则定义
            - 'or': 收盘>前日收盘 或 收盘>开盘（默认，最宽松）
            - 'and': 收盘>前日收盘 且 收盘>开盘（最严格）
            - 'prev': 仅收盘>前日收盘
            - 'open': 仅收盘>开盘
        min_hold_days: 最少持有天数，默认1（T+1规则）
        max_hold_days: 最大持有天数，默认30
        buy_price_range: 买入价格范围（开盘涨幅%），例如(-5, 6)表示-5%到6%
            - None: 不限制，总是买入（默认）
            - (min_pct, max_pct): 只有次日开盘涨幅在此范围内才买入
        strong_price_range: 走强价格范围（收盘涨幅%），例如(-2, 10)表示-2%到10%
            - None: 不限制，只要满足走强定义即视为走强（默认）
            - (min_pct, max_pct): 即使满足走强定义，收盘涨幅也必须在此范围内才算走强
    """
    from analysis.open_minutes_analyzer import analyze_open_minutes
    
    # 映射strong_rule到strong_definition
    rule_mapping = {
        'or': 'close_gt_prev_close_or_open',
        'and': 'close_gt_prev_close_and_open',
        'prev': 'close_gt_prev_close',
        'open': 'close_gt_open'
    }
    strong_definition = rule_mapping.get(strong_rule, 'close_gt_prev_close_or_open')
    
    # 调用分析函数
    report_path = analyze_open_minutes(
        summary_csv_path=summary_csv_path,
        strong_definition=strong_definition,
        min_hold_days=min_hold_days,
        max_hold_days=max_hold_days,
        buy_price_range=buy_price_range,
        strong_price_range=strong_price_range
    )
    
    return report_path


def analyze_gap_up_stocks(start_date='20250101', end_date='20250131',
                          min_gap=1.0, max_gap=6.0,
                          filter_enabled=False,
                          filter_days=5, filter_min_change=10.0, filter_max_change=100.0):
    """
    分析跳空高开股票并生成K线图
    
    功能说明：
    - 扫描全市场股票，寻找跳空高开的股票
    - 支持前期涨幅过滤
    - 同一只股票的多次跳空合并在一张图上
    - 生成汇总报告CSV
    
    Args:
        start_date: 开始日期，格式YYYYMMDD，默认'20250101'
        end_date: 结束日期，格式YYYYMMDD，默认'20250131'
        min_gap: 最小跳空幅度（%），默认1.0
        max_gap: 最大跳空幅度（%），默认6.0
        filter_enabled: 是否启用前期涨幅过滤，默认False
        filter_days: 前x个交易日，默认5
        filter_min_change: 前期最小涨幅（%），默认10.0
        filter_max_change: 前期最大涨幅（%），默认100.0
    
    注意：
        - 图表时间范围由全局配置CHART_BEFORE_DAYS和CHART_AFTER_DAYS控制
        - 如需修改，请在gap_up_analyzer.py中调整这两个全局变量
    
    输出：
        - K线图保存在: analysis/gap_up_charts/{start_date}_{end_date}/
        - 汇总报告: analysis/gap_up_charts/{start_date}_{end_date}/summary.csv
    """
    from analysis.gap_up_analyzer import GapUpAnalyzer, GapUpAnalysisConfig

    # 创建配置
    config = GapUpAnalysisConfig(
        start_date=start_date,
        end_date=end_date,
        min_gap_percent=min_gap,
        max_gap_percent=max_gap,
        filter_enabled=filter_enabled,
        filter_days=filter_days,
        filter_min_change=filter_min_change,
        filter_max_change=filter_max_change
    )

    # 执行分析
    analyzer = GapUpAnalyzer(config)
    analyzer.run()

    # 统计结果
    from collections import defaultdict
    stock_groups = defaultdict(list)
    for stock_info in analyzer.filtered_stocks:
        key = (stock_info.code, stock_info.name)
        stock_groups[key].append(stock_info)

    print(f"\n✅ 分析完成！")
    print(f"📊 共 {len(stock_groups)} 只股票，{len(analyzer.filtered_stocks)} 次跳空记录")
    print(f"📁 图表保存在: {analyzer.output_dir}")

    return analyzer.output_dir


if __name__ == '__main__':
    # === 热门天梯 ===
    # whimsical_fupan_analyze()
    # generate_ladder_chart()

    # === 复盘相关 ===
    # get_stock_datas()
    daily_routine()
    # full_scan_routine()
    # get_index_data()
    # review_history('2025-10-24', '2025-10-27')  # 可视化candidate_history
    # fetch_ths_fupan()
    # clean_ths_fupan()  # 清理历史数据，控制文件大小

    # === 策略形态扫描 ===
    # find_candidate_stocks()
    # find_candidate_stocks_weekly_growth(offset_days=0)
    # find_candidate_stocks_volume_surge('20260114')
    # strategy_scan('a')
    # generate_strategy_scan_html_charts('a', recent_days=15, columns=2)
    # generate_comparison_charts('a')
    # batch_analyze_weekly_growth_win_rate()
    # pullback_rebound_scan('a')  # 止跌反弹策略扫描
    # generate_rebound_comparison_charts('a')

    # === 连板股分析图功能 ===
    # analyze_lianban_stocks('20251101', min_lianban=3, lianban_type=1)  # 连续板分析
    # analyze_volume_surge_pattern('20251220', '20260112', min_lianban=2, continuous_surge_days=3, volume_surge_ratio=(1.8, 2.0, 3.0), volume_avg_days=5)  # 爆量分歧分析
    # backtest_strategy('analysis/pattern_charts/爆量分歧转一致/20251210_20260106/summary.csv', buy_price_range=None, strong_price_range=(-3, 20), buy_mode='open')
    # analyze_open_minutes_pattern('analysis/pattern_charts/爆量分歧转一致/20251201_20251226/summary.csv', buy_price_range=None, strong_price_range=(-3, 20))  # 分析建仓日开盘前15分钟走势

    # === 二板定龙头分析 ===
    # erban_longtou_analysis()  # 分析二板股票的晋级率、胜率和特征

    # === 跳空高开股票分析功能 ===
    # analyze_gap_up_stocks('20250901', '20251029', min_gap=2.0, max_gap=6.0, filter_enabled=True,
    #                       filter_days=20, filter_min_change=-20.0, filter_max_change=20.0)  # 跳空分析

    # === 复盘图生成 ===
    # draw_ths_fupan()        # PNG静态图
    # draw_ths_fupan_html()     # HTML交互图
    
    # === 【默默上涨】HTML图表生成 ===
    # generate_momo_html_charts(days=20, columns=2, after_days=20)  # 最近20个交易日的【默默上涨】股票HTML图表

    # === 同义词管理 ===
    # update_synonym_groups()  # 添加新词
    # clean_synonym_groups()  # 清理旧词
    # fupan_statistics_to_excel()
    # fupan_statistics_excel_plot()
    # find_yidong()
    # daily_group_analyze()
    # analyze_advanced_on()
    # stocks_time_sharing_price()
    # plot_stock_daily_prices()
    # get_hot_clouds('20251201')
    # find_dragon()
    # find_similar_trends()
    # get_stock_concept_and_industry()
    # fetch_and_filter_top_yybph()
    # get_top_yyb_trades()
    # get_lhb_datas()
    # get_stock_minute_datas()
    # check_stock_datas()

    # === 策略回测 ===
    # backtrade_simulate()
    # pullback_rebound_simulate()  # 止跌反弹策略回测
    # weekly_volume_momentum_simulate()  # 扬帆起航策略回测
    # run_psq_analysis()

    # === 大批量回测（新功能）===
    # generate_stock_lists()  # 生成全部A股列表文件（首次使用前运行一次）
    # generate_fupan_candidates()  # 从复盘数据提取热门股候选（可反复运行）
    # batch_backtest_from_stock_list()  # 从文件读取股票列表进行批量回测
    # batch_backtest_from_codes()  # 直接使用代码列表进行批量回测

    # === 参数优化功能 ===
    # 1. 生成配置模板
    # generate_optimization_templates()
    # 2. 运行参数优化（需要先生成并编辑配置文件）
    # run_parameter_optimization("compare_config.yaml")

    # === 集合竞价封单数据功能 ===
    # auction_fengdan_analyze()  # 复盘分析封单数据
    # 定时采集请运行: python alerting/auction_scheduler.py start
