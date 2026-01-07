"""
通用策略回测分析器

根据选股策略的信号数据（如summary.csv），回测分析策略的胜率、盈亏比等指标。

使用场景：
1. 信号日(a日)运行选股
2. 次日(a+1日)开盘买入
3. 持有条件：股票走强（收盘价>前日收盘价 或 收盘价>开盘价）
4. 卖出条件：不再走强时以收盘价卖出
5. T+1规则：最早a+2日可卖出

作者：AI Assistant
版本：v1.0
日期：2025-12-24
"""

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

import pandas as pd
from tqdm import tqdm

from utils.date_util import get_next_trading_day
from utils.file_util import read_stock_data
from utils.stock_util import stock_limit_ratio


@dataclass
class TradeRecord:
    """单笔交易记录"""
    stock_code: str
    stock_name: str
    signal_date: str  # 信号日期 (YYYYMMDD)
    reason: str  # 涨停原因/信号原因

    # 买入信息
    buy_date: str = ''  # 买入日期 (a+1日)
    buy_price: float = 0.0  # 买入价（开盘价）

    # 卖出信息
    sell_date: str = ''  # 卖出日期
    sell_price: float = 0.0  # 卖出价（收盘价）

    # 交易结果
    hold_days: int = 0  # 持有天数（交易日）
    profit_pct: float = 0.0  # 收益率%
    is_win: bool = False  # 是否盈利

    # 辅助数据
    open_gap_pct: float = 0.0  # 买入日开盘涨幅（相对信号日收盘）
    max_profit_pct: float = 0.0  # 持有期间最大收益%
    max_loss_pct: float = 0.0  # 持有期间最大亏损%
    sell_reason: str = ''  # 卖出原因

    # 持有期间统计
    avg_open_gap_pct: float = 0.0  # 持有期间平均开盘涨幅（每日开盘相对前日收盘的平均值）
    avg_close_change_pct: float = 0.0  # 持有期间平均收盘涨幅（每日收盘相对前日收盘的平均值）

    # 信号日数据
    signal_open: float = 0.0  # 信号日开盘价
    signal_close: float = 0.0  # 信号日收盘价
    signal_high: float = 0.0  # 信号日最高价
    signal_low: float = 0.0  # 信号日最低价
    signal_volume: float = 0.0  # 信号日成交量
    signal_volume_ratio: float = 0.0  # 信号日量比（当日量/前N日均量）
    signal_change_pct: float = 0.0  # 信号日涨幅%
    signal_amplitude: float = 0.0  # 信号日振幅%
    max_lianban: int = 0  # 最高连板数

    # a+1日（建仓日）详细数据
    day1_close: float = 0.0  # a+1日收盘价
    day1_high: float = 0.0  # a+1日最高价
    day1_low: float = 0.0  # a+1日最低价
    day1_volume: float = 0.0  # a+1日成交量
    day1_change_pct: float = 0.0  # a+1日涨幅%（收盘/昨收-1）
    day1_body_pct: float = 0.0  # a+1日实体涨幅%（(收盘-开盘)/开盘）
    day1_volume_ratio: float = 0.0  # a+1日量比（成交量/信号日成交量）
    day1_amplitude: float = 0.0  # a+1日振幅%

    # 是否有效交易
    is_valid: bool = False  # 是否有完整的交易数据

    # K线序列模式（从首次涨停到信号日）
    kline_sequence: str = ''  # K线序列，例如："大阳线-长下影阳线-大阳线"
    first_board_date: str = ''  # 首次涨停日期


@dataclass
class BacktestConfig:
    """回测配置"""
    # 持有规则
    hold_if_strong: bool = True  # 走强时持有
    strong_definition: str = 'close_gt_prev_close_or_open'  # 走强定义
    # close_gt_prev_close: 收盘价>前日收盘价
    # close_gt_open: 收盘价>开盘价
    # close_gt_prev_close_or_open: 上述任一条件满足
    # close_gt_prev_close_and_open: 上述两个条件都满足

    # T+1规则
    min_hold_days: int = 1  # 最少持有天数（T+1规则为1）
    max_hold_days: int = 30  # 最大持有天数，防止无限持有

    # 买入控制
    buy_price_range: tuple = None  # 买入价格范围（开盘涨幅%），例如(-5, 6)表示-5%到6%
    # None表示不限制，总是买入
    # (min_pct, max_pct)表示只有次日开盘涨幅在此范围内才买入

    buy_mode: str = 'open'  # 买入模式
    # 'open': 使用开盘价买入（默认，原有逻辑）
    # 'limit_up': 使用涨停价买入，要求建仓日最高价必须等于涨停价，否则放弃建仓

    # 走强控制
    strong_price_range: tuple = None  # 走强价格范围（收盘涨幅%），例如(-2, 10)表示-2%到10%
    # None表示不限制，只要满足走强定义即视为走强
    # (min_pct, max_pct)表示即使满足走强定义，收盘涨幅也必须在此范围内才算走强
    # 如果收盘涨幅不在范围内，视为"不再走强"，触发卖出

    # 数据路径
    data_path: str = './data/astocks'

    # 输出配置
    output_dir: str = None  # 报告输出目录，None则与输入文件同目录


@dataclass
class BacktestResult:
    """回测结果"""
    # 基础统计
    total_signals: int = 0  # 总信号数
    valid_trades: int = 0  # 有效交易数
    win_trades: int = 0  # 盈利交易数
    loss_trades: int = 0  # 亏损交易数

    # 胜率
    win_rate: float = 0.0  # 胜率%

    # 收益统计
    avg_profit: float = 0.0  # 平均盈利%
    avg_loss: float = 0.0  # 平均亏损%
    total_profit: float = 0.0  # 总盈利%
    total_loss: float = 0.0  # 总亏损%
    net_profit: float = 0.0  # 净收益%

    # 盈亏比
    profit_loss_ratio: float = 0.0  # 盈亏比

    # 期望值
    expected_value: float = 0.0  # 期望值% = 胜率*平均盈利 - (1-胜率)*平均亏损

    # 持有天数
    avg_hold_days: float = 0.0  # 平均持有天数
    max_hold_days: int = 0  # 最大持有天数
    min_hold_days: int = 0  # 最小持有天数

    # 最大回撤
    max_drawdown: float = 0.0  # 单笔最大亏损%
    max_profit_single: float = 0.0  # 单笔最大盈利%

    # 年化收益率
    annualized_return: float = 0.0  # 年化收益率%（复利）
    total_trading_days: int = 0  # 总交易日数（累计持有天数）

    # 交易明细
    trades: List[TradeRecord] = field(default_factory=list)


class StrategyBacktestAnalyzer:
    """
    通用策略回测分析器
    
    输入：选股策略的信号CSV文件（如summary.csv）
    输出：Markdown格式的分析报告
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.trades: List[TradeRecord] = []
        self.result: BacktestResult = None
        self.input_file: str = ''
        self.output_dir: str = ''

    def run(self, summary_csv_path: str) -> BacktestResult:
        """
        执行回测分析
        
        Args:
            summary_csv_path: 信号汇总CSV文件路径
            
        Returns:
            BacktestResult: 回测结果
        """
        self.input_file = summary_csv_path
        self.output_dir = self.config.output_dir or os.path.dirname(summary_csv_path)

        print(f"\n{'=' * 60}")
        print(f"策略回测分析")
        print(f"信号文件: {summary_csv_path}")
        print(f"{'=' * 60}\n")

        # 1. 加载信号数据
        print("[1/4] 加载信号数据...")
        signals = self._load_signals(summary_csv_path)
        if signals.empty:
            print("❌ 未找到有效信号数据")
            return None
        print(f"✅ 共加载 {len(signals)} 条信号")

        # 2. 模拟交易
        print("\n[2/4] 模拟交易...")
        self._simulate_trades(signals)
        print(f"✅ 有效交易 {len([t for t in self.trades if t.is_valid])} 笔")

        # 3. 计算统计
        print("\n[3/4] 计算统计指标...")
        self.result = self._calculate_statistics()

        # 3.5. 统计K线序列模式（仅在控制台打印）
        print("\n[3.5/4] 统计K线序列模式...")
        self._print_kline_sequence_stats()

        # 4. 生成报告
        print("\n[4/4] 生成分析报告...")
        report_path = self._generate_report()
        print(f"✅ 报告已保存至: {report_path}")

        return self.result

    def _load_signals(self, csv_path: str) -> pd.DataFrame:
        """加载信号CSV文件"""
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')

            # 标准化列名映射
            column_mapping = {
                '股票代码': 'code',
                '股票名称': 'name',
                '形态日期': 'signal_date',
                '涨停原因': 'reason',
                '量比': 'volume_ratio',
                '最高连板数': 'max_lianban',
                '当日涨幅%': 'pct_change',
                '信号次数': 'signal_count'
            }

            df = df.rename(columns=column_mapping)

            # 确保必要列存在
            required_cols = ['code', 'name', 'signal_date']
            for col in required_cols:
                if col not in df.columns:
                    logging.error(f"缺少必要列: {col}")
                    return pd.DataFrame()

            return df

        except Exception as e:
            logging.error(f"加载信号文件失败: {e}")
            return pd.DataFrame()

    def _simulate_trades(self, signals: pd.DataFrame):
        """
        模拟交易
        
        注意：同一只股票在持仓期间不会重复买入，避免重复计算
        """
        self.trades = []

        # 持仓状态跟踪：{stock_code: {'buy_date': 'YYYYMMDD', 'sell_date': 'YYYYMMDD' or None}}
        holdings: Dict[str, Dict] = {}

        for _, row in tqdm(signals.iterrows(), total=len(signals), desc="模拟交易"):
            # 处理多个信号日期的情况（如 "20251216, 20251217"）
            signal_dates = self._parse_signal_dates(row.get('signal_date', ''))

            code = row.get('code', '')
            clean_code = code.split('.')[0] if '.' in code else code

            for signal_date in signal_dates:
                # 获取买入日期（信号日次日）
                buy_date = get_next_trading_day(signal_date)
                if not buy_date:
                    continue

                # 检查是否已持仓
                if clean_code in holdings:
                    holding = holdings[clean_code]
                    # 如果仍在持仓中（未卖出或买入日期 <= 卖出日期），跳过该信号
                    if holding['sell_date'] is None:
                        # 仍在持仓中且未卖出，跳过
                        continue
                    elif buy_date <= holding['sell_date']:
                        # 买入日期在持仓期间或等于卖出日期，跳过
                        # 注意：卖出日期是T日，T+1日才能买入，所以用 <=
                        continue
                    # 如果已卖出且买入日期 > 卖出日期，可以买入（新的一笔交易）

                # 执行交易
                trade = self._execute_single_trade(row, signal_date)
                self.trades.append(trade)

                # 更新持仓状态
                if trade.is_valid and trade.buy_date:
                    holdings[clean_code] = {
                        'buy_date': trade.buy_date,
                        'sell_date': trade.sell_date if trade.sell_date else None
                    }

    def _parse_signal_dates(self, date_str) -> List[str]:
        """解析信号日期（可能是多个）"""
        if pd.isna(date_str):
            return []

        date_str = str(date_str).strip()

        # 处理多个日期的情况
        if ',' in date_str:
            dates = [d.strip() for d in date_str.split(',')]
        else:
            dates = [date_str]

        # 清理日期格式
        cleaned = []
        for d in dates:
            # 移除可能的空格
            d = d.replace(' ', '')
            if len(d) == 8 and d.isdigit():
                cleaned.append(d)

        return cleaned

    def _execute_single_trade(self, row, signal_date: str) -> TradeRecord:
        """执行单笔交易模拟"""
        code = row.get('code', '')
        name = row.get('name', '')

        # 创建交易记录
        trade = TradeRecord(
            stock_code=code,
            stock_name=name,
            signal_date=signal_date,
            reason=row.get('reason', ''),
            signal_volume_ratio=self._parse_numeric_range(row.get('volume_ratio', 0)),
            max_lianban=self._parse_int(row.get('max_lianban', 0))
        )

        # 获取股票代码（去除后缀）
        clean_code = code.split('.')[0] if '.' in code else code

        # 读取股票数据
        stock_data = read_stock_data(clean_code, self.config.data_path)
        if stock_data is None or stock_data.empty:
            return trade

        # 确保数据按日期排序
        stock_data = stock_data.sort_values('日期').reset_index(drop=True)
        stock_data['日期_str'] = stock_data['日期'].dt.strftime('%Y%m%d')

        # 获取买入日期（信号日次日）
        buy_date = get_next_trading_day(signal_date)
        if not buy_date:
            return trade

        # 查找信号日和买入日的数据
        signal_data = stock_data[stock_data['日期_str'] == signal_date]
        buy_data = stock_data[stock_data['日期_str'] == buy_date]

        if signal_data.empty or buy_data.empty:
            return trade

        signal_row = signal_data.iloc[0]
        buy_row = buy_data.iloc[0]

        # 记录信号日数据
        trade.signal_open = signal_row['开盘']
        trade.signal_close = signal_row['收盘']
        trade.signal_high = signal_row['最高']
        trade.signal_low = signal_row['最低']
        trade.signal_volume = signal_row['成交量']
        trade.signal_change_pct = signal_row['涨跌幅']
        trade.signal_amplitude = signal_row['振幅']

        # 记录买入信息（a+1日）
        trade.buy_date = buy_date

        # a+1日详细数据
        trade.day1_close = buy_row['收盘']
        trade.day1_high = buy_row['最高']
        trade.day1_low = buy_row['最低']
        trade.day1_volume = buy_row['成交量']

        # 计算涨停价（基于信号日收盘价，即前日收盘价），供所有买入模式使用
        limit_up_price = None
        if trade.signal_close > 0:
            try:
                limit_ratio = stock_limit_ratio(clean_code)
                # 计算涨停价（四舍五入到2位小数，符合A股规则）
                limit_up_price = round(trade.signal_close * (1.0 + limit_ratio), 2)
            except Exception as e:
                logging.warning(f"无法确定股票 {clean_code} 的涨跌停限制: {e}")

        # 一字涨停过滤：若建仓日最低价等于涨停价，则视为一字板，无法建仓（所有模式通用）
        if limit_up_price is not None and abs(trade.day1_low - limit_up_price) <= 0.01:
            return trade

        # 根据买入模式确定买入价
        if self.config.buy_mode == 'limit_up':
            # 涨停价买入模式：要求建仓日最高价必须等于涨停价
            if limit_up_price is None:
                # 无法计算涨停价，放弃建仓
                return trade

            # 检查建仓日最高价是否等于涨停价（允许约等，考虑浮点误差）
            # 使用0.01的容差，因为价格是2位小数
            if abs(trade.day1_high - limit_up_price) > 0.01:
                # 最高价不等于涨停价，放弃建仓
                return trade

            # 满足条件，使用最高价（即涨停价）建仓
            trade.buy_price = trade.day1_high
        else:
            # 默认模式：使用开盘价买入
            trade.buy_price = buy_row['开盘']

        # 计算开盘涨幅（a+1日开盘价相对信号日收盘价）
        if trade.signal_close > 0:
            trade.open_gap_pct = (trade.buy_price - trade.signal_close) / trade.signal_close * 100
            # a+1日涨幅（收盘价相对信号日收盘价）
            trade.day1_change_pct = (trade.day1_close - trade.signal_close) / trade.signal_close * 100

        # 检查买入价格范围限制
        if self.config.buy_price_range is not None:
            min_pct, max_pct = self.config.buy_price_range
            if not (min_pct <= trade.open_gap_pct <= max_pct):
                # 开盘涨幅不在允许范围内，不执行买入
                return trade

        # a+1日实体涨幅（收盘-开盘/开盘）
        if trade.buy_price > 0:
            trade.day1_body_pct = (trade.day1_close - trade.buy_price) / trade.buy_price * 100

        # a+1日量比（相对信号日）
        if trade.signal_volume > 0:
            trade.day1_volume_ratio = trade.day1_volume / trade.signal_volume

        # a+1日振幅
        if trade.day1_low > 0:
            trade.day1_amplitude = (trade.day1_high - trade.day1_low) / trade.signal_close * 100

        # 获取买入日的索引位置
        buy_idx = buy_data.index[0]

        # 获取信号日在stock_data中的位置索引
        signal_idx = stock_data[stock_data['日期_str'] == signal_date].index[0]

        # 分析K线序列（从首次涨停到信号日）
        trade = self._analyze_kline_sequence(trade, stock_data, signal_idx=signal_idx)

        # 模拟持有过程
        trade = self._simulate_holding(trade, stock_data, buy_idx)

        return trade

    def _simulate_holding(self, trade: TradeRecord, stock_data: pd.DataFrame,
                          buy_idx: int) -> TradeRecord:
        """
        模拟持有过程
        
        规则：
        1. 买入日为a+1日（已经买入）
        2. 从a+2日开始检查是否卖出（T+1规则）
        3. 走强条件：收盘价>前日收盘价 或 收盘价>开盘价
        4. 不满足走强条件时，以当日收盘价卖出
        """
        max_idx = len(stock_data) - 1

        # 初始化追踪变量
        prev_close = trade.buy_price  # 第一天的"前日收盘"用买入价代替
        hold_days = 0
        max_profit_pct = 0.0
        max_loss_pct = 0.0

        # 持有期间统计
        open_gaps = []  # 每日开盘涨幅（相对前日收盘）
        close_changes = []  # 每日收盘涨幅（相对前日收盘）

        # 从买入日开始遍历
        current_idx = buy_idx

        while current_idx <= max_idx:
            current_row = stock_data.iloc[current_idx]
            current_close = current_row['收盘']
            current_open = current_row['开盘']
            current_high = current_row['最高']
            current_low = current_row['最低']

            hold_days += 1

            # 计算当前收益
            current_profit_pct = (current_close - trade.buy_price) / trade.buy_price * 100
            intraday_max_profit = (current_high - trade.buy_price) / trade.buy_price * 100
            intraday_max_loss = (current_low - trade.buy_price) / trade.buy_price * 100

            max_profit_pct = max(max_profit_pct, intraday_max_profit)
            max_loss_pct = min(max_loss_pct, intraday_max_loss)

            # 统计每日开盘涨幅和收盘涨幅
            if prev_close > 0:
                open_gap = (current_open - prev_close) / prev_close * 100
                close_change = (current_close - prev_close) / prev_close * 100
                open_gaps.append(open_gap)
                close_changes.append(close_change)

            # T+1规则：至少持有min_hold_days天后才能卖出
            if hold_days > self.config.min_hold_days:
                # 检查是否仍然走强
                is_strong = self._check_strong(current_close, current_open, prev_close)

                if not is_strong:
                    # 不再走强，卖出
                    trade.sell_date = current_row['日期'].strftime('%Y%m%d')
                    trade.sell_price = current_close
                    trade.hold_days = hold_days
                    trade.sell_reason = "转弱卖出"
                    break

            # 更新前日收盘价
            prev_close = current_close

            # 检查是否达到最大持有天数
            if hold_days >= self.config.max_hold_days:
                trade.sell_date = current_row['日期'].strftime('%Y%m%d')
                trade.sell_price = current_close
                trade.hold_days = hold_days
                trade.sell_reason = "达到最大持有天数"
                break

            current_idx += 1

        # 如果循环结束仍未卖出（数据不足）
        if not trade.sell_date and current_idx > buy_idx:
            last_row = stock_data.iloc[min(current_idx, max_idx)]
            trade.sell_date = last_row['日期'].strftime('%Y%m%d')
            trade.sell_price = last_row['收盘']
            trade.hold_days = hold_days
            trade.sell_reason = "数据截止"

        # 计算最终收益
        if trade.buy_price > 0 and trade.sell_price > 0:
            trade.profit_pct = (trade.sell_price - trade.buy_price) / trade.buy_price * 100
            trade.is_win = trade.profit_pct > 0
            trade.is_valid = True

        trade.max_profit_pct = max_profit_pct
        trade.max_loss_pct = max_loss_pct

        # 计算平均开盘涨幅和平均收盘涨幅
        if open_gaps:
            trade.avg_open_gap_pct = sum(open_gaps) / len(open_gaps)
        if close_changes:
            trade.avg_close_change_pct = sum(close_changes) / len(close_changes)

        return trade

    def _check_strong(self, close: float, open_price: float, prev_close: float) -> bool:
        """
        检查是否走强
        
        逻辑：
        1. 先检查是否满足走强定义（收盘>前日收盘 或 收盘>开盘等）
        2. 如果配置了strong_price_range，还需要检查收盘涨幅是否在范围内
        """
        # 先检查走强定义
        if self.config.strong_definition == 'close_gt_prev_close':
            is_strong_by_definition = close > prev_close
        elif self.config.strong_definition == 'close_gt_open':
            is_strong_by_definition = close > open_price
        elif self.config.strong_definition == 'close_gt_prev_close_and_open':
            is_strong_by_definition = close > prev_close and close > open_price
        else:  # close_gt_prev_close_or_open (默认)
            is_strong_by_definition = close > prev_close or close > open_price

        # 如果不满足走强定义，直接返回False
        if not is_strong_by_definition:
            return False

        # 如果配置了走强价格范围，需要检查收盘涨幅是否在范围内
        if self.config.strong_price_range is not None and prev_close > 0:
            min_pct, max_pct = self.config.strong_price_range
            close_change_pct = (close - prev_close) / prev_close * 100
            if not (min_pct <= close_change_pct <= max_pct):
                # 收盘涨幅不在允许范围内，视为不再走强
                return False

        return True

    def _parse_numeric_range(self, value) -> float:
        """解析可能是范围的数值（如 '3.5-4.2'），返回平均值"""
        if pd.isna(value):
            return 0.0

        value_str = str(value).strip()

        if '-' in value_str and not value_str.startswith('-'):
            parts = value_str.split('-')
            try:
                nums = [float(p) for p in parts if p]
                return sum(nums) / len(nums) if nums else 0.0
            except:
                return 0.0

        try:
            return float(value_str)
        except:
            return 0.0

    def _parse_int(self, value) -> int:
        """解析整数"""
        try:
            return int(value)
        except:
            return 0

    def _analyze_kline_sequence(self, trade: TradeRecord, stock_data: pd.DataFrame, signal_idx: int) -> TradeRecord:
        """
        分析从首次涨停到信号日的K线序列
        
        逻辑：
        1. 信号日（t日）是爆量分歧转一致日，不是涨停日
        2. 涨停日是信号日的前一天（t-1日）
        3. 先从信号日往前找第一个涨停日（t-1日）
        4. 再从t-1日往前找首次涨停日
        5. 序列：首次涨停日 -> ... -> t-1日（涨停日）-> t日（信号日）
        
        Args:
            trade: 交易记录
            stock_data: 股票数据
            signal_idx: 信号日在stock_data中的索引
            
        Returns:
            更新后的交易记录（包含kline_sequence和first_board_date）
        """
        try:
            # 第一步：从信号日往前找第一个涨停日（应该是t-1日）
            prev_board_idx = None
            max_lookback = min(5, signal_idx)  # 最多回溯5天找t-1日的涨停

            for i in range(signal_idx - 1, max(0, signal_idx - max_lookback) - 1, -1):
                row = stock_data.iloc[i]
                change_pct = row.get('涨跌幅', 0)

                # 判断是否涨停（涨幅 >= 9.5%）
                if change_pct >= 9.5:
                    prev_board_idx = i
                    break

            # 如果没找到t-1日的涨停，说明数据可能有问题，尝试从信号日往前找
            if prev_board_idx is None:
                for i in range(signal_idx, max(0, signal_idx - max_lookback) - 1, -1):
                    row = stock_data.iloc[i]
                    change_pct = row.get('涨跌幅', 0)
                    if change_pct >= 9.5:
                        prev_board_idx = i
                        break

            if prev_board_idx is None:
                # 如果还是没找到，返回空序列
                return trade

            # 第二步：从t-1日（涨停日）往前找首次涨停日
            first_board_idx = prev_board_idx
            max_lookback_from_board = min(20, prev_board_idx)  # 最多回溯20天找首板

            for i in range(prev_board_idx - 1, max(0, prev_board_idx - max_lookback_from_board) - 1, -1):
                row = stock_data.iloc[i]
                change_pct = row.get('涨跌幅', 0)

                # 判断是否涨停（涨幅 >= 9.5%）
                if change_pct >= 9.5:
                    first_board_idx = i
                else:
                    # 如果遇到非涨停日，说明已经找到首次涨停日了
                    break

            # 记录首次涨停日期
            first_board_row = stock_data.iloc[first_board_idx]
            trade.first_board_date = first_board_row['日期'].strftime('%Y%m%d')

            # 第三步：分析从首次涨停到信号日的K线序列（包括信号日）
            # 使用实体K识别（只基于最高价和最低价）
            kline_patterns = []
            for i in range(first_board_idx, signal_idx + 1):
                row = stock_data.iloc[i]
                high = row['最高']
                low = row['最低']

                # 获取前一日收盘价作为参考（用于计算实体大小）
                if i > 0:
                    prev_row = stock_data.iloc[i - 1]
                    prev_close = prev_row['收盘']
                else:
                    prev_close = low  # 如果没有前一日数据，使用最低价

                # 识别实体K形态（只基于最高价和最低价）
                kline_type = self._identify_entity_kline(high, low, prev_close)
                kline_patterns.append(kline_type)

            # 组合成序列字符串
            trade.kline_sequence = '-'.join(kline_patterns)

        except Exception as e:
            logging.warning(f"分析K线序列失败 {trade.stock_code} {trade.signal_date}: {e}")

        return trade

    def _calculate_statistics(self) -> BacktestResult:
        """计算统计指标"""
        result = BacktestResult()
        result.total_signals = len(self.trades)

        # 筛选有效交易
        valid_trades = [t for t in self.trades if t.is_valid]
        result.valid_trades = len(valid_trades)
        result.trades = valid_trades

        if not valid_trades:
            return result

        # 盈亏分类
        win_trades = [t for t in valid_trades if t.is_win]
        loss_trades = [t for t in valid_trades if not t.is_win]

        result.win_trades = len(win_trades)
        result.loss_trades = len(loss_trades)

        # 胜率
        result.win_rate = len(win_trades) / len(valid_trades) * 100

        # 收益统计
        profits = [t.profit_pct for t in win_trades]
        losses = [t.profit_pct for t in loss_trades]

        result.total_profit = sum(profits) if profits else 0.0
        result.total_loss = sum(losses) if losses else 0.0
        result.net_profit = result.total_profit + result.total_loss

        result.avg_profit = result.total_profit / len(profits) if profits else 0.0
        result.avg_loss = abs(result.total_loss / len(losses)) if losses else 0.0

        # 盈亏比
        if result.avg_loss > 0:
            result.profit_loss_ratio = result.avg_profit / result.avg_loss

        # 期望值
        win_rate_decimal = result.win_rate / 100
        result.expected_value = (win_rate_decimal * result.avg_profit -
                                 (1 - win_rate_decimal) * result.avg_loss)

        # 持有天数统计
        hold_days_list = [t.hold_days for t in valid_trades]
        result.avg_hold_days = sum(hold_days_list) / len(hold_days_list)
        result.max_hold_days = max(hold_days_list)
        result.min_hold_days = min(hold_days_list)
        result.total_trading_days = sum(hold_days_list)

        # 单笔极值
        all_profits = [t.profit_pct for t in valid_trades]
        result.max_profit_single = max(all_profits)
        result.max_drawdown = min(all_profits)

        # 年化收益率计算（复利）
        # 假设每笔交易依次进行，计算复利累积收益
        cumulative_return = 1.0
        for t in valid_trades:
            cumulative_return *= (1 + t.profit_pct / 100)

        # 总收益率
        total_return = (cumulative_return - 1) * 100

        # 年化收益率 = ((1 + 总收益率)^(252/总交易日) - 1) * 100
        # 252是一年的交易日数
        if result.total_trading_days > 0:
            annualized_factor = 252 / result.total_trading_days
            result.annualized_return = (pow(cumulative_return, annualized_factor) - 1) * 100

        return result

    def _generate_report(self) -> str:
        """生成Markdown报告"""
        if not self.result:
            return ""

        report_path = os.path.join(self.output_dir, 'backtest_report.md')

        lines = []

        # 标题
        lines.append("# 📊 策略回测分析报告\n")
        lines.append(f"**信号来源**: `{os.path.basename(self.input_file)}`\n")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**持有规则**: 走强持有（{self._get_strong_rule_desc()}），转弱卖出\n")

        # 核心指标
        lines.append("\n## 💰 核心指标概览\n")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|------|------|------|")
        lines.append(f"| 总信号数 | {self.result.total_signals} | CSV中的信号总数 |")
        lines.append(f"| 有效交易数 | {self.result.valid_trades} | 有完整买卖数据的交易 |")
        lines.append(f"| **胜率** | **{self.result.win_rate:.1f}%** | 盈利交易占比 |")
        lines.append(f"| **盈亏比** | **{self.result.profit_loss_ratio:.2f}** | 平均盈利/平均亏损 |")
        lines.append(f"| **期望值** | **{self.result.expected_value:.2f}%** | 每笔交易期望收益 |")
        lines.append(
            f"| **年化收益率** | **{self.result.annualized_return:.1f}%** | 复利计算，基于{self.result.total_trading_days}个交易日 |")

        # 收益统计
        lines.append("\n## 📈 收益统计\n")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 盈利交易 | {self.result.win_trades} 笔 |")
        lines.append(f"| 亏损交易 | {self.result.loss_trades} 笔 |")
        lines.append(f"| 平均盈利 | +{self.result.avg_profit:.2f}% |")
        lines.append(f"| 平均亏损 | -{self.result.avg_loss:.2f}% |")
        lines.append(f"| 累计盈利 | +{self.result.total_profit:.2f}% |")
        lines.append(f"| 累计亏损 | {self.result.total_loss:.2f}% |")
        lines.append(f"| **净收益** | **{self.result.net_profit:+.2f}%** |")
        lines.append(f"| 单笔最大盈利 | +{self.result.max_profit_single:.2f}% |")
        lines.append(f"| 单笔最大亏损 | {self.result.max_drawdown:.2f}% |")

        # 持有天数统计
        lines.append("\n## ⏱️ 持有天数统计\n")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 平均持有 | {self.result.avg_hold_days:.1f} 天 |")
        lines.append(f"| 最短持有 | {self.result.min_hold_days} 天 |")
        lines.append(f"| 最长持有 | {self.result.max_hold_days} 天 |")

        # a+1日详细分析（建仓日）
        lines.append(self._generate_day1_analysis())

        # 信号日质量分析（量比+K线形态）
        lines.append(self._generate_signal_day_quality_analysis())

        # 连板数分组分析
        lines.append(self._generate_lianban_analysis())

        # 持有天数分组分析
        lines.append(self._generate_hold_days_analysis())

        # 每日信号统计
        lines.append(self._generate_daily_stats())

        # 交易明细
        lines.append(self._generate_trade_details())

        # 分析结论
        lines.append("\n## 💡 分析结论\n")
        lines.append(self._generate_conclusions())

        # 写入文件
        content = '\n'.join(lines)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return report_path

    def _get_strong_rule_desc(self) -> str:
        """获取走强规则描述"""
        rules = {
            'close_gt_prev_close': '收盘>前日收盘',
            'close_gt_open': '收盘>开盘',
            'close_gt_prev_close_or_open': '收盘>前日收盘 或 收盘>开盘',
            'close_gt_prev_close_and_open': '收盘>前日收盘 且 收盘>开盘'
        }
        return rules.get(self.config.strong_definition, '收盘>前日收盘 或 收盘>开盘')

    def _generate_day1_analysis(self) -> str:
        """生成a+1日（建仓日）详细分析"""
        lines = ["\n## 📅 建仓日(a+1日)详细分析\n"]
        lines.append("分析建仓当天的各项指标与最终收益的关系：\n")

        valid_trades = [t for t in self.trades if t.is_valid]

        if not valid_trades:
            lines.append("*无有效交易数据*\n")
            return '\n'.join(lines)

        # === 1. 开盘价位分析（使用重叠范围） ===
        lines.append("### 1. 建仓日开盘涨幅（开盘相对信号日收盘）\n")
        lines.append("使用重叠范围统计，避免严格区分导致的误差：\n")

        # 定义重叠范围
        open_gap_ranges = [
            # 负数范围
            (-float('inf'), -6, '<-6%'),
            (-6, -4, '-6%~-4%'),
            (-4, -2, '-4%~-2%'),
            (-2, 0, '-2%~0%'),
            # 正数范围
            (0, 1, '0%~1%'),
            (1, 2, '1%~2%'),
            (2, 3, '2%~3%'),
            (3, 4, '3%~4%'),
            (4, 5, '4%~5%'),
            (5, 6, '5%~6%'),
            (6, float('inf'), '\>6%'),
        ]

        lines.append("| 开盘涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|--------|")

        for low, high, label in open_gap_ranges:
            trades_in_range = [t for t in valid_trades if low <= t.open_gap_pct < high]
            if trades_in_range:
                stats = self._calc_group_stats(trades_in_range)
                lines.append(
                    f"| {label} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")

        # === 2. 建仓日K线形态分析 ===
        lines.append("\n### 2. 建仓日K线形态\n")
        lines.append("根据开盘、收盘、最高、最低价识别K线形态：\n")

        # 识别每只股票的K线形态
        kline_groups = defaultdict(list)
        for trade in valid_trades:
            kline_type = self._identify_kline_pattern(
                trade.buy_price, trade.day1_close, trade.day1_high, trade.day1_low
            )
            kline_groups[kline_type].append(trade)

        lines.append("| K线形态 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|--------|")

        # 按胜率排序
        sorted_kline = sorted(kline_groups.items(),
                              key=lambda x: self._calc_group_stats(x[1])['win_rate'],
                              reverse=True)

        for kline_type, trades in sorted_kline:
            stats = self._calc_group_stats(trades)
            lines.append(
                f"| {kline_type} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")

        # === 3. a+1日涨幅分析 ===
        lines.append("\n### 3. 建仓日涨幅（收盘相对信号日收盘）\n")
        day1_change_groups = {
            '大跌(<-5%)': {'range': (-float('inf'), -5), 'trades': []},
            '下跌(-5~0%)': {'range': (-5, 0), 'trades': []},
            '小涨(0~5%)': {'range': (0, 5), 'trades': []},
            '中涨(5~10%)': {'range': (5, 10), 'trades': []},
            '大涨(>10%)': {'range': (10, float('inf')), 'trades': []},
        }

        for trade in valid_trades:
            for group_name, group_data in day1_change_groups.items():
                low, high = group_data['range']
                if low <= trade.day1_change_pct < high:
                    group_data['trades'].append(trade)
                    break

        lines.append("| 建仓日涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|------------|--------|------|----------|--------|")

        for group_name, group_data in day1_change_groups.items():
            trades = group_data['trades']
            if trades:
                stats = self._calc_group_stats(trades)
                lines.append(
                    f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")

        # === 4. a+1日量比分析（相对信号日） ===
        lines.append("\n### 4. 建仓日量比（成交量/信号日成交量）\n")
        vol_ratio_groups = {
            '缩量(<0.6)': {'range': (0, 0.6), 'trades': []},
            '略缩(0.6~0.8)': {'range': (0.6, 0.8), 'trades': []},
            '平量(0.8~1.2)': {'range': (0.8, 1.2), 'trades': []},
            '放量(1.2~1.5)': {'range': (1.2, 1.5), 'trades': []},
            '大放量(>1.5)': {'range': (1.5, float('inf')), 'trades': []},
        }

        trades_with_vol = [t for t in valid_trades if t.day1_volume_ratio > 0]

        if trades_with_vol:
            for trade in trades_with_vol:
                for group_name, group_data in vol_ratio_groups.items():
                    low, high = group_data['range']
                    if low <= trade.day1_volume_ratio < high:
                        group_data['trades'].append(trade)
                        break

            lines.append("| 量比区间 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
            lines.append("|----------|--------|------|----------|--------|")

            for group_name, group_data in vol_ratio_groups.items():
                trades = group_data['trades']
                if trades:
                    stats = self._calc_group_stats(trades)
                    lines.append(
                        f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        else:
            lines.append("*无有效量比数据*\n")

        return '\n'.join(lines)

    def _identify_entity_kline(self, high: float, low: float, prev_close: float) -> str:
        """
        识别实体K线形态（只基于最高价和最低价）
        
        分类：
        - 一字板：最高价 == 最低价
        - 大实体：实体大小（最高-最低）相对前日收盘 >= 7%
        - 中实体：实体大小 3-7%
        - 小实体：实体大小 < 3%
        
        Args:
            high: 最高价
            low: 最低价
            prev_close: 前一日收盘价（用于计算实体大小）
            
        Returns:
            实体K形态名称
        """
        if high <= 0 or low <= 0 or prev_close <= 0:
            return "数据异常"

        # 一字板：最高价等于最低价
        if abs(high - low) < 0.01:  # 考虑浮点数误差
            return "一字板"

        # 计算实体大小（最高-最低）相对前日收盘的比例
        entity_size = (high - low) / prev_close * 100

        # 根据实体大小分类
        if entity_size >= 7:
            return "大实体"
        elif entity_size >= 3:
            return "中实体"
        else:
            return "小实体"

    def _identify_kline_pattern(self, open_price: float, close: float,
                                high: float, low: float) -> str:
        """
        识别K线形态
        
        Args:
            open_price: 开盘价
            close: 收盘价
            high: 最高价
            low: 最低价
            
        Returns:
            K线形态名称
        """
        if open_price <= 0 or close <= 0 or high <= 0 or low <= 0:
            return "数据异常"

        # 计算实体、上影线、下影线
        body = abs(close - open_price)
        upper_shadow = high - max(open_price, close)
        lower_shadow = min(open_price, close) - low
        total_range = high - low

        if total_range <= 0:
            return "一字板"

        # 实体占比
        body_ratio = body / total_range if total_range > 0 else 0
        upper_ratio = upper_shadow / total_range if total_range > 0 else 0
        lower_ratio = lower_shadow / total_range if total_range > 0 else 0

        # 实体涨幅
        body_pct = (close - open_price) / open_price * 100

        # 判断是阳线还是阴线
        is_yang = close > open_price

        # 识别形态
        if body_ratio < 0.1:
            # 实体很小，可能是十字星
            if upper_ratio > 0.3 and lower_ratio > 0.3:
                return "长上下影十字星"
            elif upper_ratio > 0.3:
                return "长上影十字星"
            elif lower_ratio > 0.3:
                return "长下影十字星"
            else:
                return "十字星"
        elif is_yang:
            # 阳线
            if lower_ratio > 0.4:
                return "长下影阳线"
            elif upper_ratio > 0.4:
                return "长上影阳线"
            elif body_pct > 9:
                return "大阳线"
            elif body_pct > 5:
                return "中阳线"
            else:
                return "小阳线"
        else:
            # 阴线
            if lower_ratio > 0.4:
                return "长下影阴线"
            elif upper_ratio > 0.4:
                return "长上影阴线"
            elif body_pct < -9:
                return "大阴线"
            elif body_pct < -5:
                return "中阴线"
            else:
                return "小阴线"

    def _calc_group_stats(self, trades: List[TradeRecord]) -> Dict:
        """计算分组统计数据"""
        count = len(trades)
        win_count = len([t for t in trades if t.is_win])
        win_rate = win_count / count * 100 if count > 0 else 0
        avg_profit = sum(t.profit_pct for t in trades) / count if count > 0 else 0

        profits = [t.profit_pct for t in trades if t.profit_pct > 0]
        losses = [t.profit_pct for t in trades if t.profit_pct < 0]
        avg_win = sum(profits) / len(profits) if profits else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        return {
            'count': count,
            'win_count': win_count,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'pl_ratio': pl_ratio
        }

    def _generate_signal_day_quality_analysis(self) -> str:
        """生成信号日质量分析（量比+K线形态）"""
        lines = ["\n## 📊 信号日质量分析\n"]
        lines.append("分析信号日（a日）的各项指标对最终交易成败的影响：\n")

        valid_trades = [t for t in self.trades if t.is_valid]

        if not valid_trades:
            lines.append("*无有效交易数据*\n")
            return '\n'.join(lines)

        # === 1. 信号日量比分析 ===
        lines.append("### 1. 信号日量比（当日成交量/前N日均量）\n")
        lines.append("分析信号日量比对胜率的影响：\n")

        groups = {
            '低量比(<3)': {'range': (0, 3), 'trades': []},
            '中量比(3-5)': {'range': (3, 5), 'trades': []},
            '高量比(5-10)': {'range': (5, 10), 'trades': []},
            '超高量比(>10)': {'range': (10, float('inf')), 'trades': []},
        }

        trades_with_vol = [t for t in valid_trades if t.signal_volume_ratio > 0]

        if trades_with_vol:
            for trade in trades_with_vol:
                for group_name, group_data in groups.items():
                    low, high = group_data['range']
                    if low <= trade.signal_volume_ratio < high:
                        group_data['trades'].append(trade)
                        break

            lines.append("| 量比区间 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
            lines.append("|----------|--------|------|----------|--------|")

            for group_name, group_data in groups.items():
                trades = group_data['trades']
                if trades:
                    stats = self._calc_group_stats(trades)
                    lines.append(
                        f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        else:
            lines.append("*无有效量比数据*\n")

        # === 2. 信号日K线形态分析 ===
        lines.append("\n### 2. 信号日K线形态\n")
        lines.append("分析信号日K线形态对胜率的影响（关注长K线和长影线的影响）：\n")

        # 识别每只股票信号日的K线形态
        kline_groups = defaultdict(list)
        for trade in valid_trades:
            if trade.signal_open > 0 and trade.signal_close > 0 and trade.signal_high > 0 and trade.signal_low > 0:
                kline_type = self._identify_kline_pattern(
                    trade.signal_open, trade.signal_close, trade.signal_high, trade.signal_low
                )
                kline_groups[kline_type].append(trade)

        if kline_groups:
            lines.append("| K线形态 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
            lines.append("|----------|--------|------|----------|--------|")

            # 按胜率排序
            sorted_kline = sorted(kline_groups.items(),
                                  key=lambda x: self._calc_group_stats(x[1])['win_rate'],
                                  reverse=True)

            for kline_type, trades in sorted_kline:
                stats = self._calc_group_stats(trades)
                lines.append(
                    f"| {kline_type} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        else:
            lines.append("*无有效K线数据*\n")

        # === 3. 信号日振幅分析 ===
        lines.append("\n### 3. 信号日振幅\n")
        lines.append("分析信号日振幅（反映K线长度）对胜率的影响：\n")

        amplitude_groups = {
            '小振幅(<5%)': {'range': (0, 5), 'trades': []},
            '中振幅(5~8%)': {'range': (5, 8), 'trades': []},
            '大振幅(8~12%)': {'range': (8, 12), 'trades': []},
            '超大振幅(>12%)': {'range': (12, float('inf')), 'trades': []},
        }

        trades_with_amp = [t for t in valid_trades if t.signal_amplitude > 0]

        if trades_with_amp:
            for trade in trades_with_amp:
                for group_name, group_data in amplitude_groups.items():
                    low, high = group_data['range']
                    if low <= trade.signal_amplitude < high:
                        group_data['trades'].append(trade)
                        break

            lines.append("| 振幅区间 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
            lines.append("|----------|--------|------|----------|--------|")

            for group_name, group_data in amplitude_groups.items():
                trades = group_data['trades']
                if trades:
                    stats = self._calc_group_stats(trades)
                    lines.append(
                        f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        else:
            lines.append("*无有效振幅数据*\n")

        return '\n'.join(lines)

    def _generate_lianban_analysis(self) -> str:
        """生成连板数分析"""
        lines = ["\n## 🔢 连板数分析\n"]
        lines.append("分析信号日最高连板数对胜率的影响：\n")

        valid_trades = [t for t in self.trades if t.is_valid and t.max_lianban > 0]

        if not valid_trades:
            lines.append("*无有效连板数据*\n")
            return '\n'.join(lines)

        # 按连板数分组
        lianban_groups = defaultdict(list)
        for trade in valid_trades:
            lianban_groups[trade.max_lianban].append(trade)

        lines.append("| 连板数 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|--------|--------|------|----------|--------|")

        for lianban in sorted(lianban_groups.keys()):
            trades = lianban_groups[lianban]
            stats = self._calc_group_stats(trades)
            lines.append(
                f"| {lianban}板 | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")

        return '\n'.join(lines)

    def _generate_hold_days_analysis(self) -> str:
        """生成持有天数分析"""
        lines = ["\n## ⏱️ 持有天数分析\n"]
        lines.append("分析不同持有天数的收益分布：\n")

        valid_trades = [t for t in self.trades if t.is_valid]

        # 按持有天数分组
        hold_groups = defaultdict(list)
        for trade in valid_trades:
            hold_groups[trade.hold_days].append(trade)

        lines.append("| 持有天数 | 交易数 | 胜率 | 平均收益 |")
        lines.append("|----------|--------|------|----------|")

        for days in sorted(hold_groups.keys()):
            trades = hold_groups[days]
            count = len(trades)
            win_count = len([t for t in trades if t.is_win])
            win_rate = win_count / count * 100
            avg_profit = sum(t.profit_pct for t in trades) / count

            lines.append(f"| {days}天 | {count} | {win_rate:.1f}% | {avg_profit:+.2f}% |")

        return '\n'.join(lines)

    def _generate_daily_stats(self) -> str:
        """生成每日信号统计"""
        lines = ["\n## 📅 每日信号统计\n"]

        valid_trades = [t for t in self.trades if t.is_valid]

        # 按信号日分组
        daily_groups = defaultdict(list)
        for trade in valid_trades:
            daily_groups[trade.signal_date].append(trade)

        lines.append("| 信号日期 | 交易数 | 胜率 | 平均收益 |")
        lines.append("|----------|--------|------|----------|")

        for date in sorted(daily_groups.keys()):
            trades = daily_groups[date]
            count = len(trades)
            win_count = len([t for t in trades if t.is_win])
            win_rate = win_count / count * 100
            avg_profit = sum(t.profit_pct for t in trades) / count

            # 格式化日期
            formatted_date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            lines.append(f"| {formatted_date} | {count} | {win_rate:.1f}% | {avg_profit:+.2f}% |")

        return '\n'.join(lines)

    def _generate_trade_details(self) -> str:
        """生成交易明细"""
        lines = ["\n## 📋 交易明细\n"]

        valid_trades = [t for t in self.trades if t.is_valid]

        # 按收益排序
        sorted_trades = sorted(valid_trades, key=lambda x: x.profit_pct, reverse=True)

        lines.append(
            "| 股票 | 信号日 | 买入日 | 卖出日 | 持有 | 买入价 | 卖出价 | 收益率 | 平均开盘涨幅 | 平均收盘涨幅 |")
        lines.append(
            "|------|--------|--------|--------|------|--------|--------|--------|--------------|--------------|")

        for trade in sorted_trades:
            signal_date = f"{trade.signal_date[4:6]}/{trade.signal_date[6:]}"
            buy_date = f"{trade.buy_date[4:6]}/{trade.buy_date[6:]}" if trade.buy_date else '-'
            sell_date = f"{trade.sell_date[4:6]}/{trade.sell_date[6:]}" if trade.sell_date else '-'

            profit_str = f"+{trade.profit_pct:.2f}%" if trade.profit_pct >= 0 else f"{trade.profit_pct:.2f}%"
            avg_open_gap_str = f"{trade.avg_open_gap_pct:+.2f}%" if trade.avg_open_gap_pct != 0 else "-"
            avg_close_change_str = f"{trade.avg_close_change_pct:+.2f}%" if trade.avg_close_change_pct != 0 else "-"

            lines.append(
                f"| {trade.stock_name} | {signal_date} | {buy_date} | {sell_date} | "
                f"{trade.hold_days}天 | {trade.buy_price:.2f} | {trade.sell_price:.2f} | "
                f"{profit_str} | {avg_open_gap_str} | {avg_close_change_str} |"
            )

        return '\n'.join(lines)

    def _generate_conclusions(self) -> str:
        """生成分析结论"""
        conclusions = []

        r = self.result

        # 整体评价
        if r.expected_value > 1:
            conclusions.append(
                f"1. **策略有效性**: 期望值 {r.expected_value:.2f}% > 0，该策略具有正期望，可以作为交易参考。")
        elif r.expected_value > 0:
            conclusions.append(
                f"1. **策略有效性**: 期望值 {r.expected_value:.2f}% > 0，该策略略有正期望，但优势不明显，需谨慎使用。")
        else:
            conclusions.append(f"1. **策略有效性**: ⚠️ 期望值 {r.expected_value:.2f}% < 0，该策略为负期望，不建议使用。")

        # 胜率评价
        if r.win_rate >= 50:
            conclusions.append(f"2. **胜率表现**: 胜率 {r.win_rate:.1f}% 超过50%，在心理层面较容易执行。")
        else:
            conclusions.append(
                f"2. **胜率表现**: 胜率 {r.win_rate:.1f}% 低于50%，需要较强的心理承受能力，依赖盈亏比获利。")

        # 盈亏比评价
        if r.profit_loss_ratio >= 2:
            conclusions.append(f"3. **盈亏比**: 盈亏比 {r.profit_loss_ratio:.2f} >= 2，风险收益比良好。")
        elif r.profit_loss_ratio >= 1:
            conclusions.append(f"3. **盈亏比**: 盈亏比 {r.profit_loss_ratio:.2f}，需要较高胜率配合。")
        else:
            conclusions.append(f"3. **盈亏比**: ⚠️ 盈亏比 {r.profit_loss_ratio:.2f} < 1，平均亏损大于平均盈利，风险较高。")

        # 持有周期
        conclusions.append(
            f"4. **持有周期**: 平均持有 {r.avg_hold_days:.1f} 天，资金周转效率{'较高' if r.avg_hold_days <= 3 else '一般' if r.avg_hold_days <= 5 else '较低'}。")

        # 最大回撤提醒
        conclusions.append(f"5. **风险控制**: 单笔最大亏损 {r.max_drawdown:.2f}%，需注意仓位控制。")

        # 样本量提醒
        if r.valid_trades < 30:
            conclusions.append(
                f"6. **样本量提醒**: ⚠️ 有效交易仅 {r.valid_trades} 笔，统计结果可能存在偏差，建议增加样本后再做结论。")

        return '\n\n'.join(conclusions)

    def _print_kline_sequence_stats(self):
        """统计并打印K线序列模式（仅在控制台输出）"""
        valid_trades = [t for t in self.trades if t.is_valid and t.kline_sequence]

        if not valid_trades:
            print("⚠️  未找到有效的K线序列数据")
            return

        # 按K线序列分组统计
        from collections import defaultdict
        sequence_groups = defaultdict(list)

        for trade in valid_trades:
            sequence_groups[trade.kline_sequence].append(trade)

        print(f"\n{'=' * 80}")
        print(f"K线序列模式统计（从首次涨停到信号日）")
        print(f"共 {len(valid_trades)} 笔有效交易，{len(sequence_groups)} 种不同模式")
        print(f"{'=' * 80}\n")

        # 计算每个模式的统计指标
        stats_list = []
        for sequence, trades in sequence_groups.items():
            count = len(trades)
            win_count = len([t for t in trades if t.is_win])
            win_rate = win_count / count * 100 if count > 0 else 0

            profits = [t.profit_pct for t in trades if t.profit_pct > 0]
            losses = [t.profit_pct for t in trades if t.profit_pct < 0]

            avg_profit = sum(profits) / len(profits) if profits else 0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0
            avg_return = sum(t.profit_pct for t in trades) / count

            pl_ratio = avg_profit / avg_loss if avg_loss > 0 else 0

            win_rate_decimal = win_rate / 100
            expected_value = (win_rate_decimal * avg_profit - (1 - win_rate_decimal) * avg_loss)

            stats_list.append({
                'sequence': sequence,
                'count': count,
                'win_rate': win_rate,
                'avg_return': avg_return,
                'avg_profit': avg_profit,
                'avg_loss': avg_loss,
                'pl_ratio': pl_ratio,
                'expected_value': expected_value
            })

        # 按样本数降序排序，然后按期望值降序排序
        stats_list.sort(key=lambda x: (-x['count'], -x['expected_value']))

        # 打印表格
        print(f"{'K线序列':<50} {'样本数':<8} {'胜率':<8} {'平均收益':<10} {'盈亏比':<8} {'期望值':<10}")
        print(f"{'-' * 50} {'-' * 8} {'-' * 8} {'-' * 10} {'-' * 8} {'-' * 10}")

        for stats in stats_list:
            sequence = stats['sequence']
            # 如果序列太长，截断显示
            if len(sequence) > 48:
                sequence = sequence[:45] + "..."

            print(f"{sequence:<50} {stats['count']:<8} {stats['win_rate']:>6.1f}%  "
                  f"{stats['avg_return']:>+8.2f}%  {stats['pl_ratio']:>6.2f}  "
                  f"{stats['expected_value']:>+8.2f}%")

        print(f"\n{'=' * 80}")
        print(f"统计说明：")
        print(f"  - K线序列：从首次涨停日到信号日的每日K线形态，用'-'连接")
        print(f"  - 样本数：该序列模式出现的交易次数")
        print(f"  - 胜率：该序列模式下的盈利交易占比")
        print(f"  - 平均收益：该序列模式下的平均收益率")
        print(f"  - 盈亏比：平均盈利/平均亏损")
        print(f"  - 期望值：胜率×平均盈利 - (1-胜率)×平均亏损")
        print(f"{'=' * 80}\n")


def run_backtest(summary_csv_path: str,
                 strong_definition: str = 'close_gt_prev_close_or_open',
                 min_hold_days: int = 1,
                 max_hold_days: int = 30,
                 buy_price_range: tuple = None,
                 strong_price_range: tuple = None,
                 buy_mode: str = 'open',
                 data_path: str = './data/astocks') -> BacktestResult:
    """
    便捷函数：执行策略回测
    
    Args:
        summary_csv_path: 信号汇总CSV文件路径
        strong_definition: 走强定义
            - 'close_gt_prev_close': 收盘>前日收盘
            - 'close_gt_open': 收盘>开盘
            - 'close_gt_prev_close_or_open': 收盘>前日收盘 或 收盘>开盘（默认）
            - 'close_gt_prev_close_and_open': 收盘>前日收盘 且 收盘>开盘
        min_hold_days: 最少持有天数（T+1规则为1）
        max_hold_days: 最大持有天数
        buy_price_range: 买入价格范围（开盘涨幅%），例如(-5, 6)表示-5%到6%
            None表示不限制，总是买入
        strong_price_range: 走强价格范围（收盘涨幅%），例如(-2, 10)表示-2%到10%
            None表示不限制，只要满足走强定义即视为走强
            (min_pct, max_pct)表示即使满足走强定义，收盘涨幅也必须在此范围内才算走强
        buy_mode: 买入模式
            'open': 使用开盘价买入（默认，原有逻辑）
            'limit_up': 使用涨停价买入，要求建仓日最高价必须等于涨停价，否则放弃建仓
        data_path: 股票数据目录
        
    Returns:
        BacktestResult: 回测结果
    """
    config = BacktestConfig(
        strong_definition=strong_definition,
        min_hold_days=min_hold_days,
        max_hold_days=max_hold_days,
        buy_price_range=buy_price_range,
        strong_price_range=strong_price_range,
        buy_mode=buy_mode,
        data_path=data_path
    )

    analyzer = StrategyBacktestAnalyzer(config)
    return analyzer.run(summary_csv_path)


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 示例用法
    csv_path = 'analysis/pattern_charts/爆量分歧转一致/20251130_20251223/summary.csv'

    if os.path.exists(csv_path):
        result = run_backtest(csv_path)

        if result:
            print(f"\n{'=' * 40}")
            print(f"回测结果摘要")
            print(f"{'=' * 40}")
            print(f"胜率: {result.win_rate:.1f}%")
            print(f"盈亏比: {result.profit_loss_ratio:.2f}")
            print(f"期望值: {result.expected_value:.2f}%")
    else:
        print(f"测试文件不存在: {csv_path}")
