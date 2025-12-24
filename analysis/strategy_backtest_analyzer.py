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

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import pandas as pd
from tqdm import tqdm

from utils.file_util import read_stock_data
from utils.date_util import get_next_trading_day


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
    
    # 信号日数据
    signal_close: float = 0.0  # 信号日收盘价
    signal_volume: float = 0.0  # 信号日成交量
    signal_volume_ratio: float = 0.0  # 信号日量比（当日量/前N日均量）
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
        """模拟交易"""
        self.trades = []
        
        for _, row in tqdm(signals.iterrows(), total=len(signals), desc="模拟交易"):
            # 处理多个信号日期的情况（如 "20251216, 20251217"）
            signal_dates = self._parse_signal_dates(row.get('signal_date', ''))
            
            for signal_date in signal_dates:
                trade = self._execute_single_trade(row, signal_date)
                self.trades.append(trade)
    
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
        trade.signal_close = signal_row['收盘']
        trade.signal_volume = signal_row['成交量']
        
        # 记录买入信息（a+1日）
        trade.buy_date = buy_date
        trade.buy_price = buy_row['开盘']
        
        # a+1日详细数据
        trade.day1_close = buy_row['收盘']
        trade.day1_high = buy_row['最高']
        trade.day1_low = buy_row['最低']
        trade.day1_volume = buy_row['成交量']
        
        # 计算开盘涨幅（a+1日开盘价相对信号日收盘价）
        if trade.signal_close > 0:
            trade.open_gap_pct = (trade.buy_price - trade.signal_close) / trade.signal_close * 100
            # a+1日涨幅（收盘价相对信号日收盘价）
            trade.day1_change_pct = (trade.day1_close - trade.signal_close) / trade.signal_close * 100
        
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
        
        return trade
    
    def _check_strong(self, close: float, open_price: float, prev_close: float) -> bool:
        """检查是否走强"""
        if self.config.strong_definition == 'close_gt_prev_close':
            return close > prev_close
        elif self.config.strong_definition == 'close_gt_open':
            return close > open_price
        elif self.config.strong_definition == 'close_gt_prev_close_and_open':
            return close > prev_close and close > open_price
        else:  # close_gt_prev_close_or_open (默认)
            return close > prev_close or close > open_price
    
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
        lines.append(f"| **年化收益率** | **{self.result.annualized_return:.1f}%** | 复利计算，基于{self.result.total_trading_days}个交易日 |")
        
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
        
        # 开盘价位分析
        lines.append(self._generate_open_gap_analysis())
        
        # a+1日详细分析（建仓日）
        lines.append(self._generate_day1_analysis())
        
        # 量比分组分析
        lines.append(self._generate_volume_ratio_analysis())
        
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
    
    def _generate_open_gap_analysis(self) -> str:
        """生成开盘价位分析"""
        lines = ["\n## 🔍 开盘价位分析\n"]
        lines.append("分析买入日（a+1日）开盘涨幅对胜率的影响：\n")
        
        # 分组
        groups = {
            '低开(<0%)': {'range': (-float('inf'), 0), 'trades': []},
            '平开(0-3%)': {'range': (0, 3), 'trades': []},
            '高开(3-6%)': {'range': (3, 6), 'trades': []},
            '大幅高开(6-9%)': {'range': (6, 9), 'trades': []},
            '一字(>9%)': {'range': (9, float('inf')), 'trades': []},
        }
        
        valid_trades = [t for t in self.trades if t.is_valid]
        
        for trade in valid_trades:
            for group_name, group_data in groups.items():
                low, high = group_data['range']
                if low <= trade.open_gap_pct < high:
                    group_data['trades'].append(trade)
                    break
        
        lines.append("| 开盘涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|--------|")
        
        for group_name, group_data in groups.items():
            trades = group_data['trades']
            if trades:
                count = len(trades)
                win_count = len([t for t in trades if t.is_win])
                win_rate = win_count / count * 100
                avg_profit = sum(t.profit_pct for t in trades) / count
                
                profits = [t.profit_pct for t in trades if t.profit_pct > 0]
                losses = [t.profit_pct for t in trades if t.profit_pct < 0]
                avg_win = sum(profits) / len(profits) if profits else 0
                avg_loss = abs(sum(losses) / len(losses)) if losses else 0
                pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                
                lines.append(f"| {group_name} | {count} | {win_rate:.1f}% | {avg_profit:+.2f}% | {pl_ratio:.2f} |")
        
        return '\n'.join(lines)
    
    def _generate_day1_analysis(self) -> str:
        """生成a+1日（建仓日）详细分析"""
        lines = ["\n## 📅 建仓日(a+1日)详细分析\n"]
        lines.append("分析建仓当天的各项指标与最终收益的关系：\n")
        
        valid_trades = [t for t in self.trades if t.is_valid]
        
        if not valid_trades:
            lines.append("*无有效交易数据*\n")
            return '\n'.join(lines)
        
        # === 1. a+1日涨幅分析 ===
        lines.append("### 1. 建仓日涨幅（收盘相对信号日收盘）\n")
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
                lines.append(f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        
        # === 2. a+1日实体涨幅分析 ===
        lines.append("\n### 2. 建仓日实体涨幅（(收盘-开盘)/开盘）\n")
        body_groups = {
            '长下影(<-3%)': {'range': (-float('inf'), -3), 'trades': []},
            '小阴线(-3~0%)': {'range': (-3, 0), 'trades': []},
            '十字星(0~1%)': {'range': (0, 1), 'trades': []},
            '小阳线(1~3%)': {'range': (1, 3), 'trades': []},
            '中阳线(3~6%)': {'range': (3, 6), 'trades': []},
            '大阳线(>6%)': {'range': (6, float('inf')), 'trades': []},
        }
        
        for trade in valid_trades:
            for group_name, group_data in body_groups.items():
                low, high = group_data['range']
                if low <= trade.day1_body_pct < high:
                    group_data['trades'].append(trade)
                    break
        
        lines.append("| 实体涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|--------|")
        
        for group_name, group_data in body_groups.items():
            trades = group_data['trades']
            if trades:
                stats = self._calc_group_stats(trades)
                lines.append(f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        
        # === 3. a+1日量比分析（相对信号日） ===
        lines.append("\n### 3. 建仓日量比（成交量/信号日成交量）\n")
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
                    lines.append(f"| {group_name} | {stats['count']} | {stats['win_rate']:.1f}% | {stats['avg_profit']:+.2f}% | {stats['pl_ratio']:.2f} |")
        else:
            lines.append("*无有效量比数据*\n")
        
        # === 4. 综合数据表格 ===
        lines.append("\n### 4. 建仓日数据汇总\n")
        lines.append("| 股票 | 开盘涨幅 | 收盘涨幅 | 实体涨幅 | 量比 | 最终收益 | 结果 |")
        lines.append("|------|----------|----------|----------|------|----------|------|")
        
        # 按最终收益排序
        sorted_trades = sorted(valid_trades, key=lambda x: x.profit_pct, reverse=True)
        
        for trade in sorted_trades:
            result_icon = "✅" if trade.is_win else "❌"
            vol_ratio_str = f"{trade.day1_volume_ratio:.2f}" if trade.day1_volume_ratio > 0 else "-"
            lines.append(
                f"| {trade.stock_name} | {trade.open_gap_pct:+.1f}% | {trade.day1_change_pct:+.1f}% | "
                f"{trade.day1_body_pct:+.1f}% | {vol_ratio_str} | {trade.profit_pct:+.2f}% | {result_icon} |"
            )
        
        return '\n'.join(lines)
    
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
    
    def _generate_volume_ratio_analysis(self) -> str:
        """生成量比分析"""
        lines = ["\n## 📊 信号日量比分析\n"]
        lines.append("分析信号日量比（当日成交量/前N日均量）对胜率的影响：\n")
        
        groups = {
            '低量比(<3)': {'range': (0, 3), 'trades': []},
            '中量比(3-5)': {'range': (3, 5), 'trades': []},
            '高量比(5-10)': {'range': (5, 10), 'trades': []},
            '超高量比(>10)': {'range': (10, float('inf')), 'trades': []},
        }
        
        valid_trades = [t for t in self.trades if t.is_valid and t.signal_volume_ratio > 0]
        
        if not valid_trades:
            lines.append("*无有效量比数据*\n")
            return '\n'.join(lines)
        
        for trade in valid_trades:
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
                count = len(trades)
                win_count = len([t for t in trades if t.is_win])
                win_rate = win_count / count * 100
                avg_profit = sum(t.profit_pct for t in trades) / count
                
                profits = [t.profit_pct for t in trades if t.profit_pct > 0]
                losses = [t.profit_pct for t in trades if t.profit_pct < 0]
                avg_win = sum(profits) / len(profits) if profits else 0
                avg_loss = abs(sum(losses) / len(losses)) if losses else 0
                pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                
                lines.append(f"| {group_name} | {count} | {win_rate:.1f}% | {avg_profit:+.2f}% | {pl_ratio:.2f} |")
        
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
            count = len(trades)
            win_count = len([t for t in trades if t.is_win])
            win_rate = win_count / count * 100
            avg_profit = sum(t.profit_pct for t in trades) / count
            
            profits = [t.profit_pct for t in trades if t.profit_pct > 0]
            losses = [t.profit_pct for t in trades if t.profit_pct < 0]
            avg_win = sum(profits) / len(profits) if profits else 0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0
            pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            
            lines.append(f"| {lianban}板 | {count} | {win_rate:.1f}% | {avg_profit:+.2f}% | {pl_ratio:.2f} |")
        
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
        
        lines.append("| 股票 | 信号日 | 买入日 | 卖出日 | 持有 | 买入价 | 卖出价 | 收益率 | 卖出原因 |")
        lines.append("|------|--------|--------|--------|------|--------|--------|--------|----------|")
        
        for trade in sorted_trades:
            signal_date = f"{trade.signal_date[4:6]}/{trade.signal_date[6:]}"
            buy_date = f"{trade.buy_date[4:6]}/{trade.buy_date[6:]}" if trade.buy_date else '-'
            sell_date = f"{trade.sell_date[4:6]}/{trade.sell_date[6:]}" if trade.sell_date else '-'
            
            profit_str = f"+{trade.profit_pct:.2f}%" if trade.profit_pct >= 0 else f"{trade.profit_pct:.2f}%"
            
            lines.append(
                f"| {trade.stock_name} | {signal_date} | {buy_date} | {sell_date} | "
                f"{trade.hold_days}天 | {trade.buy_price:.2f} | {trade.sell_price:.2f} | "
                f"{profit_str} | {trade.sell_reason} |"
            )
        
        return '\n'.join(lines)
    
    def _generate_conclusions(self) -> str:
        """生成分析结论"""
        conclusions = []
        
        r = self.result
        
        # 整体评价
        if r.expected_value > 1:
            conclusions.append(f"1. **策略有效性**: 期望值 {r.expected_value:.2f}% > 0，该策略具有正期望，可以作为交易参考。")
        elif r.expected_value > 0:
            conclusions.append(f"1. **策略有效性**: 期望值 {r.expected_value:.2f}% > 0，该策略略有正期望，但优势不明显，需谨慎使用。")
        else:
            conclusions.append(f"1. **策略有效性**: ⚠️ 期望值 {r.expected_value:.2f}% < 0，该策略为负期望，不建议使用。")
        
        # 胜率评价
        if r.win_rate >= 50:
            conclusions.append(f"2. **胜率表现**: 胜率 {r.win_rate:.1f}% 超过50%，在心理层面较容易执行。")
        else:
            conclusions.append(f"2. **胜率表现**: 胜率 {r.win_rate:.1f}% 低于50%，需要较强的心理承受能力，依赖盈亏比获利。")
        
        # 盈亏比评价
        if r.profit_loss_ratio >= 2:
            conclusions.append(f"3. **盈亏比**: 盈亏比 {r.profit_loss_ratio:.2f} >= 2，风险收益比良好。")
        elif r.profit_loss_ratio >= 1:
            conclusions.append(f"3. **盈亏比**: 盈亏比 {r.profit_loss_ratio:.2f}，需要较高胜率配合。")
        else:
            conclusions.append(f"3. **盈亏比**: ⚠️ 盈亏比 {r.profit_loss_ratio:.2f} < 1，平均亏损大于平均盈利，风险较高。")
        
        # 持有周期
        conclusions.append(f"4. **持有周期**: 平均持有 {r.avg_hold_days:.1f} 天，资金周转效率{'较高' if r.avg_hold_days <= 3 else '一般' if r.avg_hold_days <= 5 else '较低'}。")
        
        # 最大回撤提醒
        conclusions.append(f"5. **风险控制**: 单笔最大亏损 {r.max_drawdown:.2f}%，需注意仓位控制。")
        
        # 样本量提醒
        if r.valid_trades < 30:
            conclusions.append(f"6. **样本量提醒**: ⚠️ 有效交易仅 {r.valid_trades} 笔，统计结果可能存在偏差，建议增加样本后再做结论。")
        
        return '\n\n'.join(conclusions)


def run_backtest(summary_csv_path: str, 
                 strong_definition: str = 'close_gt_prev_close_or_open',
                 min_hold_days: int = 1,
                 max_hold_days: int = 30,
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
        data_path: 股票数据目录
        
    Returns:
        BacktestResult: 回测结果
    """
    config = BacktestConfig(
        strong_definition=strong_definition,
        min_hold_days=min_hold_days,
        max_hold_days=max_hold_days,
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

