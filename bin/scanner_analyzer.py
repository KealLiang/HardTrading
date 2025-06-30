"""
基于Analyzer的股票扫描器
通过自定义Analyzer捕获策略信号，无需修改策略代码
"""

import logging
import os
import re
from datetime import datetime

import backtrader as bt
import pandas as pd
from tqdm import tqdm

import bin.simulator as simulator
from bin.simulator import read_stock_data, ExtendedPandasData
from strategy.breakout_strategy import BreakoutStrategy
from utils.date_util import get_current_or_prev_trading_day

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')


class SignalCaptureAnalyzer(bt.Analyzer):
    """
    通用信号捕获分析器
    可以捕获策略产生的买入信号，无需修改原始策略代码
    适用于backtrader的任何策略
    """
    
    params = (
        ('signal_patterns', ['突破信号']),  # 要捕获的信号模式列表
        ('score_threshold', 0),           # 最低信号评分要求（0表示所有信号）
        ('position_change', True),        # 是否检测仓位变化
        ('order_monitor', True),          # 是否监控订单创建
        ('log_monitor', True),            # 是否监控日志输出
        ('direct_log_capture', True),     # 是否直接从日志捕获信号，不等待订单创建
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
        dt = dt or self.strategy.datas[0].datetime.date(0)
        
        # 捕获符合条件的信号
        for pattern in self.p.signal_patterns:
            if pattern in txt:
                # 从日志中提取重要信息
                score = self._extract_score(txt)
                if score >= self.p.score_threshold:
                    signal_info = {
                        'datetime': dt,
                        'code': self.strategy.datas[0]._name,
                        'signal_type': 'BUY_SIGNAL',
                        'close': self.strategy.datas[0].close[0],
                        'details': txt,
                        'score': score
                    }
                    
                    # 记录信号日期和详情，用于后续next中的订单监控
                    self.signal_date = dt
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
                dt = self.strategy.datas[0].datetime.date(0)
                details = f"买入信号 @ {dt}"
                
            self.signals.append({
                'datetime': self.strategy.datas[0].datetime.date(0),
                'code': self.strategy.datas[0]._name,
                'signal_type': 'BUY_SIGNAL',
                'close': self.strategy.datas[0].close[0],
                'details': details,
                'score': score
            })
            
            # 重置信号临时数据
            self.signal_date = None
            self.signal_details = {}
        
        # 检测仓位变化
        elif self.p.position_change and not self.position_size_prev and self.strategy.position and self.strategy.position.size > 0:
            self.signals.append({
                'datetime': self.strategy.datas[0].datetime.date(0),
                'code': self.strategy.datas[0]._name,
                'signal_type': 'BUY_SIGNAL',
                'close': self.strategy.datas[0].close[0],
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


def get_stock_pool(source=None, data_dir='./data/astocks'):
    """
    获取股票池列表。
    :param source: 股票来源。可以是列表, 'all', 或文件路径 (默认: 'bin/candidate_stocks.txt')。
    :param data_dir: 股票数据目录, 当 source='all' 时使用。
    :return: 股票代码列表。
    """
    if isinstance(source, list):
        return [str(s).zfill(6) for s in source]

    if source is None:
        source = 'bin/candidate_stocks.txt'

    if os.path.exists(source):
        try:
            with open(source, 'r', encoding='utf-8') as f:
                stocks = [line.strip() for line in f if line.strip() and not line.startswith("股票代码")]
            return [s.zfill(6) for s in stocks]
        except Exception as e:
            logging.error(f"读取股票池文件 {source} 失败: {e}")
            return []

    if source == 'all':
        try:
            return [f.split('_')[0] for f in os.listdir(data_dir) if f.endswith('.csv')]
        except FileNotFoundError:
            logging.error(f"数据目录 {data_dir} 不存在。")
            return []

    logging.warning(f"无法识别的股票池来源: {source}")
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

        # 确保有足够的数据用于指标预热
        required_start = pd.to_datetime(scan_start_date) - pd.Timedelta(days=100)
        if dataframe.index[0] > required_start:
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


def _run_scan_analyzer(strategy_class, start_date, end_date,
                      stock_pool_source=None, data_path='./data/astocks',
                      strategy_params=None, signal_patterns=None):
    """
    使用Analyzer方式运行股票扫描器。
    
    参数:
        strategy_class: 策略类
        start_date: 扫描开始日期
        end_date: 扫描结束日期
        stock_pool_source: 股票池来源
        data_path: 数据路径
        strategy_params: 策略参数
        signal_patterns: 要捕获的信号模式列表
    
    返回:
        捕获的信号列表
    """
    stock_list = get_stock_pool(stock_pool_source, data_path)
    if not stock_list:
        logging.error("股票池为空，扫描终止。")
        return []

    logging.info(f"开始扫描 {len(stock_list)} 只股票，策略: {strategy_class.__name__}, "
                 f"日期范围: [{start_date}, {end_date}]")

    all_signals = []

    with tqdm(total=len(stock_list), desc="扫描进度") as pbar:
        for code in stock_list:
            signals = _scan_single_stock_analyzer(code, strategy_class, strategy_params, data_path,
                                               start_date, end_date, signal_patterns)
            if signals:
                all_signals.extend(signals)
            pbar.update(1)

    logging.info(f"扫描完成。共在 {len(set(s['code'] for s in all_signals))} 只股票中找到 {len(all_signals)} 个买入信号。")
    return all_signals


def scan_and_visualize_analyzer(scan_strategy, scan_start_date, scan_end_date=None,
                               stock_pool=None, strategy_params=None, signal_patterns=None):
    """
    使用Analyzer方式执行股票扫描并可视化结果
    
    参数:
        scan_strategy: 用于扫描的策略类
        scan_start_date: 扫描开始日期 (格式: 'YYYYMMDD')
        scan_end_date: 扫描结束日期 (格式: 'YYYYMMDD')，若为None则为最近交易日
        stock_pool: 股票池来源 (None, 'all', list, or file path)
        strategy_params: 策略参数字典
        signal_patterns: 要捕获的信号模式列表
    """
    # --- 1. 日期处理 ---
    start_date_fmt = f"{scan_start_date[:4]}-{scan_start_date[4:6]}-{scan_start_date[6:8]}"
    if scan_end_date is None:
        today_str = datetime.now().strftime('%Y%m%d')
        end_date_str = get_current_or_prev_trading_day(today_str)
        end_date_fmt = f"{end_date_str[:4]}-{end_date_str[4:6]}-{end_date_str[6:8]}"
    else:
        end_date_str = scan_end_date
        end_date_fmt = f"{scan_end_date[:4]}-{scan_end_date[4:6]}-{scan_end_date[6:8]}"

    # --- 2. 执行扫描 ---
    signals = _run_scan_analyzer(
        strategy_class=scan_strategy,
        start_date=start_date_fmt,
        end_date=end_date_fmt,
        stock_pool_source=stock_pool,
        strategy_params=strategy_params,
        signal_patterns=signal_patterns
    )

    if not signals:
        print("扫描完成，没有发现符合条件的信号。")
        return

    # --- 3. 创建输出目录和日志文件 ---
    output_dir = os.path.join('bin', 'candidate_stocks_result')
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, f"scan_summary_{scan_start_date}-{end_date_str}.txt")

    # 按信号日期倒序排列
    signals.sort(key=lambda x: x['datetime'], reverse=True)

    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"扫描策略: {scan_strategy.__name__}\n")
        f.write(f"扫描范围: {start_date_fmt} to {end_date_fmt}\n")
        f.write(f"总计发现 {len(signals)} 个信号，涉及 {len(set(s['code'] for s in signals))} 只股票。\n")
        f.write("-" * 50 + "\n")
        for signal in signals:
            score_info = f"评分: {signal.get('score', '未评分')}，" if 'score' in signal else ""
            f.write(f"股票: {signal['code']}, "
                    f"信号日期: {signal['datetime'].strftime('%Y-%m-%d')}, "
                    f"价格: {signal['close']:.2f}, "
                    f"{score_info}"
                    f"详情: {signal.get('details', '')}\n")

    print(f"\n扫描结果摘要已保存到: {summary_path}")
    print(f"开始对 {len(signals)} 个信号逐一进行可视化分析...")

    # --- 4. 对每个信号进行可视化 ---
    for signal in signals:
        code = signal['code']
        signal_date = signal['datetime']
        
        vis_start_date = pd.to_datetime(signal_date) - pd.Timedelta(days=90)
        vis_end_date = pd.to_datetime(signal_date) + pd.Timedelta(days=90)

        print("-" * 70)
        print(f"正在分析股票: {code}, 信号日期: {signal_date.strftime('%Y-%m-%d')}")

        simulator.go_trade(
            code=code,
            startdate=vis_start_date,
            enddate=vis_end_date,
            strategy=scan_strategy,
            strategy_params=strategy_params,
            log_trades=True,
            visualize=True,
            signal_dates=[signal_date],
            interactive_plot=False  # 禁用弹出图表
        )

    return signals


if __name__ == '__main__':
    # --- 设置日志级别为DEBUG ---
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - [%(levelname)s] - %(message)s')
    
    # --- 根据不同策略设置不同的信号模式 ---
    from strategy.breakout_strategy import BreakoutStrategy
    
    # 更精确的信号模式列表
    signal_patterns = [
        '突破信号:', 
        '突破信号：',
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
        stock_pool=['600610'],  # 先指定一只确定有信号的股票
        signal_patterns=signal_patterns
    ) 