"""
基于Analyzer的股票扫描器
通过自定义Analyzer捕获策略信号，无需修改策略代码
"""

import logging
import os
import re
import shutil
from contextlib import redirect_stdout
from datetime import datetime

import backtrader as bt
import pandas as pd
from tqdm import tqdm

import bin.simulator as simulator
from bin.simulator import read_stock_data, ExtendedPandasData
from strategy.constant.signal_constants import LOG_FRAGMENT_TO_SIGNAL_MAP, SIG_UNKNOWN
from utils import date_util
from utils.date_util import get_current_or_prev_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

# --- Constants ---
DEFAULT_DATA_PATH = './data/astocks'
# DEFAULT_CANDIDATE_FILE = 'bin/candidate_temp/candidate_stocks.txt'
DEFAULT_CANDIDATE_FILE = 'bin/candidate_temp/candidate_stocks_volume_surge.txt'
OTHER_CANDIDATE_FILE = 'bin/candidate_temp/candidate_stocks_weekly_growth.txt'
DEFAULT_OUTPUT_DIR = os.path.join('bin', 'candidate_stocks_result')

# 扫描最少需要的数据天数
MIN_REQUIRED_DAYS = simulator.warm_up_days

# 针对特定策略的最小数据要求（策略名称: 最小天数）
STRATEGY_MIN_DAYS = {
    'PullbackReboundStrategy': 120,  # 止跌反弹策略使用120日均量，需要至少120天数据
    'ScannablePullbackReboundStrategy': 120,  # 可扫描版本同样需要120天
}


# --- Analyzers ---
class SignalCaptureAnalyzer(bt.Analyzer):
    """
    通用信号捕获分析器
    可以捕获策略产生的买入信号，无需修改原始策略代码
    适用于backtrader的任何策略
    """

    params = (
        ('signal_patterns', ['突破信号']),  # 要捕获的信号模式列表
        ('score_threshold', 0),  # 最低信号评分要求（0表示所有信号）
        ('position_change', True),  # 是否检测仓位变化
        ('order_monitor', True),  # 是否监控订单创建
        ('log_monitor', True),  # 是否监控日志输出
        ('direct_log_capture', True),  # 是否直接从日志捕获信号，不等待订单创建
    )

    def __init__(self):
        self.signals = []
        self.position_size_prev = 0

        # 如果启用日志监控，保存并替换原始log函数
        if self.p.log_monitor and hasattr(self.strategy, 'log'):
            self.original_log = self.strategy.log
            self.strategy.log = self._log_wrapper

        # 如果启用订单监控，备份并替换原始next方法
        if self.p.order_monitor:
            self.original_next = self.strategy._next
            self.strategy._next = self._next_wrapper

        # 信号处理状态
        self.signal_date = None
        self.signal_details = {}

    def _log_wrapper(self, txt, dt=None):
        """包装策略的log函数，捕获信号信息"""
        # 先调用原始log函数
        self.original_log(txt, dt)
        # 关键修复 v2: 使用 .datetime(0) 获取纯 python datetime 对象，而不是一个代理对象
        dt_object = self.strategy.datas[0].datetime.datetime(0)

        # 捕获符合条件的信号
        for pattern in self.p.signal_patterns:
            if pattern in txt:
                # 从日志中提取重要信息
                score = self._extract_score(txt)
                if score >= self.p.score_threshold:
                    # 从datetime对象中获取纯date对象
                    safe_date = dt_object.date()
                    signal_info = {
                        'datetime': safe_date,
                        'code': self.strategy.datas[0]._name,
                        'signal_type': 'BUY_SIGNAL',
                        'close': float(self.strategy.datas[0].close[0]),
                        'details': txt,
                        'score': score
                    }

                    # 记录信号日期和详情，用于后续next中的订单监控
                    self.signal_date = safe_date
                    self.signal_details = {
                        'source': txt,
                        'score': score
                    }

                    # 如果不监控订单或启用直接日志捕获，则直接添加信号
                    if not self.p.order_monitor or self.p.direct_log_capture:
                        self.signals.append(signal_info)
                break

    def _next_wrapper(self):
        """包装策略的next方法，检测订单创建和仓位变化"""
        # 保存之前的仓位状态
        self.position_size_prev = self.strategy.position.size if self.strategy.position else 0

        # 执行原始next
        self.original_next()

        # 检测买入信号：通过订单创建
        if self.strategy.order and self.strategy.order.isbuy():
            # 检查是否有之前捕获的信号详情
            details = self.signal_details.get('source', '')
            score = self.signal_details.get('score', 0)

            # 如果没有通过日志捕获到信号但有买入操作，创建基本信号
            if not details:
                dt_object = self.strategy.datas[0].datetime.datetime(0)
                details = f"买入信号 @ {dt_object.date()}"

            # 同样应用日期快照修复
            dt_object = self.strategy.datas[0].datetime.datetime(0)
            safe_date = dt_object.date()

            self.signals.append({
                'datetime': safe_date,
                'code': self.strategy.datas[0]._name,
                'signal_type': 'BUY_SIGNAL',
                'close': float(self.strategy.datas[0].close[0]),
                'details': details,
                'score': score
            })

            # 重置信号临时数据
            self.signal_date = None
            self.signal_details = {}

        # 检测仓位变化
        elif self.p.position_change and not self.position_size_prev and self.strategy.position and self.strategy.position.size > 0:
            # 同样应用日期快照修复
            dt_object = self.strategy.datas[0].datetime.datetime(0)
            safe_date = dt_object.date()
            self.signals.append({
                'datetime': safe_date,
                'code': self.strategy.datas[0]._name,
                'signal_type': 'BUY_SIGNAL',
                'close': float(self.strategy.datas[0].close[0]),
                'details': "检测到仓位增加",
                'score': 0
            })

    def _extract_score(self, txt):
        """从信号文本中提取评分"""
        # 处理情况1：直接包含数字评分的情况
        score_match = re.search(r'评分[:：\s]*([\d]+)', txt)
        if score_match:
            return int(score_match.group(1))

        # 处理情况2：BreakoutStrategy中的评级
        if '【A+级】' in txt:
            return 9
        elif '【A级】' in txt:
            return 8
        elif '【B级】' in txt:
            return 6
        elif '【C级】' in txt:
            return 4

        # 处理情况3：其他信号强度表述
        if '强烈' in txt or '显著' in txt:
            return 7
        elif '中等' in txt:
            return 5

        # 默认评分
        return 0

    def stop(self):
        """还原被替换的方法"""
        if self.p.log_monitor and hasattr(self, 'original_log'):
            self.strategy.log = self.original_log

        if self.p.order_monitor and hasattr(self, 'original_next'):
            self.strategy._next = self.original_next

    def get_analysis(self):
        """返回分析结果"""
        return {
            'signals': self.signals,
            'count': len(self.signals)
        }


# --- Helper Functions ---
def _filter_signals_to_unique_opportunities(signals, strategy_class):
    """
    过滤信号，确保每个交易机会只处理一次。
    逻辑：将时间上接近的信号（在一个观察周期内）视为一个"簇"，并只选择每个簇中最新的一个信号。
    """
    if not signals:
        return []

    # 从策略类中获取默认观察周期
    strategy_params_dict = vars(strategy_class.params)
    observation_period_days = strategy_params_dict.get('observation_period', 15)
    logging.info(f"使用观察周期 {observation_period_days} 天对信号进行聚类...")

    signals_by_code = {}
    for s in signals:
        signals_by_code.setdefault(s['code'], []).append(s)

    final_signals = []
    for code, stock_signals in signals_by_code.items():
        stock_signals.sort(key=lambda x: x['datetime'])

        if not stock_signals:
            continue

        # 使用信号簇来处理
        opportunity_clusters = []
        current_cluster = [stock_signals[0]]

        for i in range(1, len(stock_signals)):
            current_signal = stock_signals[i]
            last_signal_in_cluster = current_cluster[-1]
            # 确保datetime是datetime对象
            current_dt = pd.to_datetime(current_signal['datetime'])
            last_dt = pd.to_datetime(last_signal_in_cluster['datetime'])

            if (current_dt - last_dt).days <= observation_period_days:
                current_cluster.append(current_signal)
            else:
                opportunity_clusters.append(current_cluster)
                current_cluster = [current_signal]

        opportunity_clusters.append(current_cluster)

        for cluster in opportunity_clusters:
            if cluster:
                # 选择簇中最新的一个信号加入最终列表
                final_signals.append(cluster[-1])

    return final_signals


def _parse_stock_directory(data_dir):
    """
    扫描数据目录一次，获取所有股票代码和名称映射。
    处理 '<code>_<name>.csv' 格式的文件名。
    """
    codes = []
    name_map = {}
    try:
        for filename in os.listdir(data_dir):
            if filename.endswith('.csv'):
                # 文件名格式: <code>_<name>.csv, 支持名称中包含"_"
                parts = filename[:-4].split('_')
                if len(parts) >= 2:
                    code, name = parts[0], '_'.join(parts[1:])
                    code = code.zfill(6)
                    codes.append(code)
                    name_map[code] = name
    except FileNotFoundError:
        logging.warning(f"数据目录 {data_dir} 未找到，无法加载股票代码和名称。")
    return sorted(codes), name_map


def get_stock_pool(source, all_codes_from_dir=None):
    """
    根据指定的源获取股票池列表。
    :param source: 股票来源。可以是列表, 'all', 或文件路径。
    :param all_codes_from_dir: 当 source='all' 时使用的预扫描代码列表。
    :return: 股票代码列表。
    """
    if isinstance(source, list):
        return [str(s).zfill(6) for s in source]

    if source == 'all':
        return all_codes_from_dir if all_codes_from_dir is not None else []

    # 如果不是列表也不是'all'，则假定为文件路径
    try:
        with open(source, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]

        # 使用正则表达式提取股票代码（6位数字）
        stock_code_pattern = re.compile(r'^\d{6}$')
        stocks = [line for line in lines if stock_code_pattern.match(line)]

        if not stocks:
            logging.warning(f"未在文件 {source} 中找到有效的股票代码（6位数字）")
        else:
            logging.info(f"从文件 {source} 中识别出 {len(stocks)} 只股票代码")

        return [s.zfill(6) for s in stocks]
    except Exception as e:
        logging.error(f"读取股票池文件 {source} 失败: {e}")
        return []


def _scan_single_stock_analyzer(code, strategy_class, strategy_params, data_path,
                                scan_start_date, scan_end_date, signal_patterns=None):
    """
    使用Analyzer方式对单个股票进行扫描

    参数:
        code: 股票代码
        strategy_class: 策略类
        strategy_params: 策略参数
        data_path: 数据路径
        scan_start_date: 扫描开始日期
        scan_end_date: 扫描结束日期
        signal_patterns: 要捕获的信号模式列表 (默认: ['突破信号'])

    返回:
        捕获的信号列表
    """
    try:
        dataframe = read_stock_data(code, data_path)
        if dataframe is None or dataframe.empty:
            return None

        # 根据策略类确定最小数据天数
        strategy_name = strategy_class.__name__
        min_days = STRATEGY_MIN_DAYS.get(strategy_name, MIN_REQUIRED_DAYS)

        # 截取所需的数据段，以减少不必要的计算，并防止日志中出现过旧的信息
        required_data_start = date_util.get_n_trading_days_before(scan_start_date, min_days)
        scan_end_date_obj = pd.to_datetime(scan_end_date)

        dataframe = dataframe.loc[required_data_start:scan_end_date_obj]

        # 清理停牌数据（包含NaN的行）
        # 保留原始行数用于日志
        original_len = len(dataframe)
        dataframe = dataframe.dropna(subset=['open', 'close', 'high', 'low'])
        cleaned_len = len(dataframe)

        if original_len != cleaned_len:
            logging.debug(f"股票 {code} 清理了 {original_len - cleaned_len} 行停牌数据")

        if dataframe.empty or len(dataframe) < min_days:  # 至少要有x天的数据才有分析意义
            logging.warning(f"股票 {code} 数据不足（有效数据 {len(dataframe)} 行，需要至少 {min_days} 行）")
            return None

        data_feed = ExtendedPandasData(dataname=dataframe)

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(data_feed, name=code)

        # 添加策略 (不需要修改策略参数)
        cerebro.addstrategy(strategy_class, **(strategy_params or {}))

        # 如果没有指定信号模式，默认使用突破信号
        if signal_patterns is None:
            signal_patterns = ['突破信号']

        # 添加信号捕获分析器
        cerebro.addanalyzer(SignalCaptureAnalyzer,
                            _name='signalcapture',
                            signal_patterns=signal_patterns)

        results = cerebro.run()

        # 获取捕获的信号
        strat = results[0]
        signals = strat.analyzers.signalcapture.get_analysis().get('signals', [])

        # 按日期过滤信号
        scan_start_date_obj = pd.to_datetime(scan_start_date).date()
        scan_end_date_obj = pd.to_datetime(scan_end_date).date()

        final_signals = [signal for signal in signals
                         if scan_start_date_obj <= signal['datetime'] <= scan_end_date_obj]

        return final_signals

    except Exception as e:
        logging.error(f"扫描股票 {code} 时出错: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def _run_scan_analyzer(stock_list, strategy_class, start_date, end_date,
                       data_path, strategy_params=None, signal_patterns=None):
    """
    使用Analyzer方式对给定的股票列表运行扫描器。
    """
    if not stock_list:
        logging.error("股票池为空，扫描终止。")
        return []

    logging.info(f"开始扫描 {len(stock_list)} 只股票，策略: {strategy_class.__name__}, "
                 f"日期范围: [{start_date}, {end_date}]")

    all_signals = []
    scanned_count = 0  # 成功扫描的股票数量
    error_count = 0  # 出错的股票数量
    no_signal_count = 0  # 无信号的股票数量

    # 记录每只股票的扫描状态
    scan_details = []

    with tqdm(total=len(stock_list), desc="扫描进度") as pbar:
        for code in stock_list:
            signals = _scan_single_stock_analyzer(code, strategy_class, strategy_params, data_path,
                                                  start_date, end_date, signal_patterns)
            if signals is None:
                # 扫描出错（数据不足或异常）
                error_count += 1
                scan_details.append({'code': code, 'status': 'ERROR', 'signal_count': 0})
                logging.debug(f"股票 {code} 扫描出错或数据不足")
            elif signals:
                # 找到信号
                all_signals.extend(signals)
                scanned_count += 1
                scan_details.append({'code': code, 'status': 'FOUND', 'signal_count': len(signals)})
                logging.debug(f"股票 {code} 找到 {len(signals)} 个信号")
            else:
                # 扫描成功但无信号
                no_signal_count += 1
                scan_details.append({'code': code, 'status': 'NO_SIGNAL', 'signal_count': 0})
                logging.debug(f"股票 {code} 扫描完成但无信号")

            pbar.update(1)

    logging.info(
        f"扫描完成。共扫描 {len(stock_list)} 只股票: "
        f"找到信号 {scanned_count} 只, 无信号 {no_signal_count} 只, 出错/数据不足 {error_count} 只。"
        f"共找到 {len(all_signals)} 个买入信号。")

    # 保存扫描明细报告（仅在有扫描数据时）
    if scan_details:
        from datetime import datetime
        detail_file = f'bin/scan_detail/scan_details_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        os.makedirs(os.path.dirname(detail_file), exist_ok=True)
        try:
            with open(detail_file, 'w', encoding='utf-8') as f:
                f.write(f"策略: {strategy_class.__name__}\n")
                f.write(f"扫描日期范围: {start_date} 到 {end_date}\n")
                f.write(f"信号模式: {signal_patterns}\n")
                f.write(f"总计: {len(stock_list)} 只股票\n")
                f.write(f"  - 找到信号: {scanned_count} 只\n")
                f.write(f"  - 无信号: {no_signal_count} 只\n")
                f.write(f"  - 出错/数据不足: {error_count} 只\n")
                f.write("\n" + "=" * 60 + "\n")
                f.write("详细扫描结果:\n")
                f.write("=" * 60 + "\n\n")

                # 按状态分组输出
                for status_label, status_code in [
                    ("找到信号的股票", "FOUND"),
                    ("无信号的股票", "NO_SIGNAL"),
                    ("出错/数据不足的股票", "ERROR")
                ]:
                    status_stocks = [d for d in scan_details if d['status'] == status_code]
                    if status_stocks:
                        f.write(f"\n{status_label} ({len(status_stocks)} 只):\n")
                        f.write("-" * 40 + "\n")
                        for detail in status_stocks:
                            if detail['signal_count'] > 0:
                                f.write(f"  {detail['code']} - 信号数: {detail['signal_count']}\n")
                            else:
                                f.write(f"  {detail['code']}\n")

            logging.info(f"扫描明细已保存到: {detail_file}")
        except Exception as e:
            logging.warning(f"保存扫描明细失败: {e}")

    return all_signals


# --- Main Orchestration Function ---
def scan_and_visualize_analyzer(scan_strategy, scan_start_date, scan_end_date=None,
                                stock_pool=None, strategy_params=None, signal_patterns=None,
                                data_path=DEFAULT_DATA_PATH, output_path=DEFAULT_OUTPUT_DIR,
                                details_after_date=None, candidate_model='a'):
    """
    执行股票扫描并可视化结果的总调度函数。

    :param details_after_date: str, 可选。格式如 'YYYYMMDD' 或 'YYYY-MM-DD'。
                               只有信号日期在此日期或之后的股票才会生成详细的可视化报告。
    """
    # --- 1. 日期与路径准备 ---
    start_date_fmt = f"{scan_start_date[:4]}-{scan_start_date[4:6]}-{scan_start_date[6:8]}"
    if scan_end_date is None:
        today_str = datetime.now().strftime('%Y%m%d')
        end_date_str = get_current_or_prev_trading_day(today_str)
        end_date_fmt = f"{end_date_str[:4]}-{end_date_str[4:6]}-{end_date_str[6:8]}"
    else:
        end_date_str = scan_end_date
        end_date_fmt = f"{scan_end_date[:4]}-{scan_end_date[4:6]}-{scan_end_date[6:8]}"

    os.makedirs(output_path, exist_ok=True)

    # --- 2. 获取股票代码和名称 ---
    all_codes, name_map = _parse_stock_directory(data_path)

    # 如果未指定股票池, 默认使用候选文件
    if stock_pool is None:
        if candidate_model == 'a':
            stock_pool = DEFAULT_CANDIDATE_FILE
        elif candidate_model == 'b':
            stock_pool = OTHER_CANDIDATE_FILE
        else:
            raise ValueError(f"无法识别的候选模式: {candidate_model}")

    target_stock_list = get_stock_pool(
        source=stock_pool,
        all_codes_from_dir=all_codes
    )

    # --- 3. 执行扫描，获取所有原始信号 ---
    raw_signals = _run_scan_analyzer(
        stock_list=target_stock_list,
        strategy_class=scan_strategy,
        start_date=start_date_fmt,
        end_date=end_date_fmt,
        data_path=data_path,
        strategy_params=strategy_params,
        signal_patterns=signal_patterns
    )

    if not raw_signals:
        print("扫描完成，没有发现符合条件的信号。")
        return

    # --- 4. 使用原始信号生成完整的摘要日志（先去重） ---
    summary_path = os.path.join(output_path, f"scan_summary_{scan_start_date}-{end_date_str}.txt")
    raw_signals.sort(key=lambda x: x['datetime'], reverse=True)

    # 对原始信号进行去重，确保同一只股票在同一天只出现一次
    unique_signals = []
    seen = set()
    for signal in raw_signals:
        key = (signal['code'], signal['datetime'].strftime('%Y-%m-%d'))
        if key not in seen:
            seen.add(key)
            unique_signals.append(signal)

    logging.info(f"去重后，信号数量从 {len(raw_signals)} 减少到 {len(unique_signals)}")

    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"扫描策略: {scan_strategy.__name__}\n")
        f.write(f"扫描范围: {start_date_fmt} to {end_date_fmt}\n")
        f.write(
            f"总计发现 {len(unique_signals)} 个去重后信号，涉及 {len(set(s['code'] for s in unique_signals))} 只股票。\n")
        f.write("-" * 50 + "\n")
        for signal in unique_signals:
            code = signal['code']
            name = name_map.get(code, '')
            stock_display = f"{code} {name}" if name else code
            score_info = f"评分: {signal.get('score', '未评分')}，" if 'score' in signal else ""
            f.write(f"股票: {stock_display}, "
                    f"信号日期: {signal['datetime'].strftime('%Y-%m-%d')}, "
                    f"价格: {signal['close']:.2f}, "
                    f"{score_info}"
                    f"详情: {signal.get('details', '')}\n")

    print(f"\n扫描结果摘要已保存到: {summary_path}")

    # --- 4.5. 生成简化版文件（按日期分组，方便复制到同花顺） ---
    simple_summary_path = os.path.join(output_path, f"scan_simple_{scan_start_date}-{end_date_str}.txt")

    # 按日期分组股票
    from collections import defaultdict
    date_grouped_signals = defaultdict(list)
    for signal in unique_signals:
        signal_date = signal['datetime'].strftime('%Y-%m-%d')
        code = signal['code']
        name = name_map.get(code, '')
        date_grouped_signals[signal_date].append((code, name))

    # 按日期降序排列
    sorted_dates = sorted(date_grouped_signals.keys(), reverse=True)

    with open(simple_summary_path, 'w', encoding='utf-8') as f:
        for i, date in enumerate(sorted_dates):
            f.write(f"{date}\n")
            for code, name in date_grouped_signals[date]:
                f.write(f"{code} {name}\n")
            # 在日期组之间添加分隔符，最后一组不加
            if i < len(sorted_dates) - 1:
                f.write("=" * 50 + "\n")

    print(f"简化版扫描结果已保存到: {simple_summary_path}")

    # --- 5. 过滤信号用于可视化 ---
    final_signals = _filter_signals_to_unique_opportunities(raw_signals, scan_strategy)
    logging.info(f"信号聚类后，得到 {len(final_signals)} 个独立的交易机会进行分析。")

    # 根据 `details_after_date` 参数进一步过滤用于可视化的信号
    if details_after_date:
        try:
            # 兼容 YYYY-MM-DD 和 YYYYMMDD 格式
            filter_date = pd.to_datetime(details_after_date).date()
            original_count = len(final_signals)
            final_signals = [
                s for s in final_signals if s['datetime'] >= filter_date
            ]
            logging.info(
                f"根据 'details_after_date' ({details_after_date}) 过滤后，"
                f"剩余 {len(final_signals)} 个交易机会需要生成详细报告 (原 {original_count} 个)。"
            )
        except Exception as e:
            logging.error(f"解析 details_after_date ('{details_after_date}') 时出错: {e}。将不进行过滤。")

    if not final_signals:
        print("根据过滤条件，没有需要进行可视化分析的信号。")
        return

    print(f"开始对 {len(final_signals)} 个独立的交易机会逐一进行可视化分析...")

    # --- 6. 对每个过滤后的信号进行可视化 ---
    # 优化：预先去重，只保留每只股票的第一个信号（通常是最新的）
    import time
    viz_start_time = time.time()
    
    seen_codes = set()
    deduplicated_signals = []
    for signal in final_signals:
        code = signal['code']
        if code not in seen_codes:
            seen_codes.add(code)
            deduplicated_signals.append(signal)
        else:
            logging.debug(f"股票 {code} 重复信号已在预处理阶段跳过")
    
    if len(deduplicated_signals) < len(final_signals):
        logging.info(f"去重优化：{len(final_signals)} 个信号去重后剩余 {len(deduplicated_signals)} 个")
    
    # 添加进度条，让用户了解可视化进展
    with tqdm(total=len(deduplicated_signals), desc="生成可视化") as pbar:
        for signal in deduplicated_signals:
            code = signal['code']

            signal_date = signal['datetime']

            vis_start_date = pd.to_datetime(signal_date) - pd.Timedelta(days=90)
            vis_end_date = pd.to_datetime(signal_date) + pd.Timedelta(days=90)

            logging.debug("-" * 70)
            logging.info(f"正在分析股票: {code} {name_map.get(code, '')}, 信号日期: {signal_date.strftime('%Y-%m-%d')}")

            # 使用新的配置来解析信号类型
            signal_details = signal.get('details', '')
            signal_type_found = SIG_UNKNOWN
            for fragment, signal_type in LOG_FRAGMENT_TO_SIGNAL_MAP.items():
                if fragment in signal_details:
                    signal_type_found = signal_type
                    break  # 匹配到最具体的规则后即退出

            primary_signal = {
                'date': signal_date,
                'type': signal_type_found,
                'details': signal_details
            }

            # 准备完整的信号信息列表，先添加主要信号
            signal_info = [primary_signal]

            # --- 优化：使用内存缓冲区替代临时文件，减少I/O开销 ---
            from io import StringIO
            
            # 第一次：快速运行回测提取完整信号（使用内存缓冲区）
            log_buffer = StringIO()
            
            try:
                with redirect_stdout(log_buffer):
                    simulator.go_trade(
                        code=code,
                        startdate=vis_start_date,
                        enddate=vis_end_date,
                        strategy=scan_strategy,
                        strategy_params=strategy_params,
                        log_trades=False,  # 第一次不需要交易日志
                        visualize=False,   # 第一次不生成可视化
                        signal_info=[],
                        interactive_plot=False
                    )
                
                # 从捕获的日志中提取所有信号
                log_content = log_buffer.getvalue()
                log_lines = log_content.split('\n')
                
                for line in log_lines:
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                    if not date_match:
                        continue

                    signal_date_str = date_match.group(1)

                    for fragment, signal_type in LOG_FRAGMENT_TO_SIGNAL_MAP.items():
                        if fragment in line:
                            signal_date_obj = pd.to_datetime(signal_date_str).date()
                            duplicate = any(
                                (s['date'] == signal_date_obj and s['type'] == signal_type)
                                for s in signal_info
                            )

                            if not duplicate:
                                signal_info.append({
                                    'date': signal_date_obj,
                                    'type': signal_type,
                                    'details': line.strip()
                                })
                                break
                                
            except Exception as e:
                logging.error(f"第一次回测提取信号时出错: {e}")
            finally:
                log_buffer.close()

            # 第二次：使用完整信号生成可视化
            simulator.go_trade(
                code=code,
                stock_name=name_map.get(code, ''),
                startdate=vis_start_date,
                enddate=vis_end_date,
                strategy=scan_strategy,
                strategy_params=strategy_params,
                log_trades=True,
                visualize=True,
                signal_info=signal_info,
                interactive_plot=False,
                output_path=output_path
            )
            
            # 更新进度条
            pbar.update(1)
    
    # 输出性能统计
    viz_duration = time.time() - viz_start_time
    avg_time_per_stock = viz_duration / len(deduplicated_signals) if deduplicated_signals else 0
    logging.info(f"可视化完成！总耗时: {viz_duration:.2f}秒，处理 {len(deduplicated_signals)} 只股票，平均 {avg_time_per_stock:.2f}秒/只")

    return final_signals


if __name__ == '__main__':
    # --- 设置日志级别为DEBUG ---
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - [%(levelname)s] - %(message)s')

    # --- 根据不同策略设置不同的信号模式 ---
    from strategy.breakout_strategy import BreakoutStrategy

    # 更精确的信号模式列表
    signal_patterns = [
        '突破信号',
        '*** 二次确认信号已',
        '*** 触发【突破观察哨】'
    ]

    print(f"开始使用以下信号模式扫描: {signal_patterns}")
    print("-" * 50)

    # 使用更合理的日期范围
    start_date = '20240101'
    end_date = '20250620'
    print(f"扫描时间范围: {start_date} 到 {end_date}")

    # 使用示例
    scan_and_visualize_analyzer(
        scan_strategy=BreakoutStrategy,
        scan_start_date=start_date,
        scan_end_date=end_date,
        stock_pool=['600610', '301357'],  # 扫描指定列表
        # stock_pool='all',  # 扫描数据文件夹下所有股票
        # stock_pool='bin/candidate_temp/candidate_stocks.txt', # 从文件加载
        signal_patterns=signal_patterns
    )
