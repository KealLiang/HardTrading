"""
建仓日开盘前15分钟走势分析器

分析建仓日（a+1日）开盘前15分钟（9:30-9:45）的走势对交易成功率和赔率的影响。
结合开盘涨幅和开盘后走势模式进行综合分析。

作者：AI Assistant
版本：v1.0
日期：2025-12-29
"""

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd
from tqdm import tqdm

from analysis.strategy_backtest_analyzer import BacktestResult, TradeRecord

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== 走势模式识别阈值配置 ==========
# 横盘判断阈值：收盘价相对开盘价的涨跌幅在±此范围内视为横盘
PATTERN_HORIZONTAL_THRESHOLD = 1.0  # 1.0%

# 直接拉升/直接下跌判断阈值：最大跌幅/涨幅小于此值视为直接拉升/下跌
PATTERN_DIRECT_THRESHOLD = 2.0  # 2.0%


@dataclass
class OpenMinutesPattern:
    """开盘前15分钟走势模式"""
    # 基础信息
    stock_code: str
    stock_name: str
    buy_date: str  # 建仓日 YYYYMMDD
    open_price: float  # 开盘价
    signal_close: float  # 信号日收盘价（用于计算开盘涨幅）

    # 开盘涨幅（开盘价相对信号日收盘价）
    open_gap_pct: float = 0.0

    # 开盘后15分钟走势数据
    minutes_data: pd.DataFrame = None  # 9:30-9:45的1分钟K线数据

    # 走势特征
    first_minute_close: float = 0.0  # 9:30收盘价（通常是开盘价）
    last_minute_close: float = 0.0  # 9:45收盘价
    highest_price: float = 0.0  # 15分钟内最高价
    lowest_price: float = 0.0  # 15分钟内最低价

    # 走势模式
    pattern_type: str = ''  # 走势模式：直接拉升、先跌后拉、震荡、直接下跌等
    max_rise_pct: float = 0.0  # 相对开盘的最大涨幅%
    max_fall_pct: float = 0.0  # 相对开盘的最大跌幅%
    final_change_pct: float = 0.0  # 9:45相对开盘的涨幅%

    # 成交量特征
    total_volume: float = 0.0  # 总成交量
    avg_volume: float = 0.0  # 平均每根K线成交量

    # 数据级别
    data_type: str = ''  # 数据级别：'1分钟' 或 '5分钟'
    is_recent: bool = False  # 是否为一周内的数据

    # 关联的交易结果
    trade: TradeRecord = None  # 关联的交易记录


class OpenMinutesAnalyzer:
    """开盘前15分钟走势分析器"""

    def __init__(self, backtest_result: BacktestResult, output_dir: str = None):
        """
        初始化分析器
        
        Args:
            backtest_result: 回测结果对象
            output_dir: 输出目录，用于保存报告
        """
        self.backtest_result = backtest_result
        self.patterns: List[OpenMinutesPattern] = []
        self._output_dir = output_dir or '.'

    def analyze(self) -> List[OpenMinutesPattern]:
        """
        分析所有有效交易的开盘前15分钟走势
        
        Returns:
            走势模式列表
        """
        valid_trades = [t for t in self.backtest_result.trades if t.is_valid and t.buy_date]

        if not valid_trades:
            logging.warning("没有有效交易数据")
            return []

        print(f"\n{'=' * 60}")
        print(f"开盘前15分钟走势分析")
        print(f"共 {len(valid_trades)} 笔有效交易")
        print(f"{'=' * 60}\n")

        self.patterns = []
        self.patterns_1m = []  # 1分钟级别的模式（仅最近一周内）
        failed_count = 0

        for trade in tqdm(valid_trades, desc="分析开盘走势"):
            pattern = self._analyze_single_trade(trade)
            if pattern:
                self.patterns.append(pattern)
                # 如果有1分钟级别的分析结果，也添加到单独列表
                if hasattr(pattern, 'pattern_1m') and pattern.pattern_1m:
                    self.patterns_1m.append(pattern.pattern_1m)
            else:
                failed_count += 1

        print(f"\n✅ 成功分析 {len(self.patterns)} 笔交易的开盘走势（5分钟级别）")
        if self.patterns_1m:
            print(f"✅ 额外分析 {len(self.patterns_1m)} 笔交易的开盘走势（1分钟级别，最近一周内）")
        print(f"❌ 失败 {failed_count} 笔（可能原因：数据获取失败、日期为未来日期、股票停牌等）")
        print(
            f"📊 成功率: {len(self.patterns)}/{len(valid_trades)} ({len(self.patterns) / len(valid_trades) * 100:.1f}%)")

        return self.patterns

    def _analyze_single_trade(self, trade: TradeRecord) -> Optional[OpenMinutesPattern]:
        """
        分析单笔交易的开盘走势
        
        所有交易都使用5分钟级别分析（9:30-9:45，15分钟）
        最近一周内的交易额外再用1分钟级别分析（9:30-9:45，15分钟）
        
        Args:
            trade: 交易记录
            
        Returns:
            走势模式对象，如果获取数据失败则返回None
        """
        from datetime import datetime

        # 获取股票代码（去除后缀）
        clean_code = trade.stock_code.split('.')[0] if '.' in trade.stock_code else trade.stock_code

        # 格式化日期：YYYYMMDD -> YYYY-MM-DD
        buy_date_str = trade.buy_date
        if len(buy_date_str) == 8:
            formatted_date = f"{buy_date_str[:4]}-{buy_date_str[4:6]}-{buy_date_str[6:]}"
            buy_date_obj = datetime.strptime(buy_date_str, '%Y%m%d')
        else:
            return None

        # 判断是否在一周内
        today = datetime.now()
        days_diff = (today.date() - buy_date_obj.date()).days
        is_recent = days_diff <= 7

        try:
            # 所有交易都使用5分钟级别（9:30-9:45，15分钟，3根K线）
            start_time_5m = f"{formatted_date} 09:30:00"
            end_time_5m = f"{formatted_date} 09:45:00"

            df_minutes_5m = ak.stock_zh_a_hist_min_em(
                symbol=clean_code,
                period="5",
                start_date=start_time_5m,
                end_date=end_time_5m
            )

            if df_minutes_5m.empty:
                logging.warning(
                    f"⚠️ {trade.stock_name}({clean_code}) {buy_date_str} 5分钟级别数据为空（可能停牌或数据缺失）")
                return None

            # 创建走势模式对象（基于5分钟数据）
            pattern = OpenMinutesPattern(
                stock_code=clean_code,
                stock_name=trade.stock_name,
                buy_date=trade.buy_date,
                open_price=trade.buy_price,
                signal_close=trade.signal_close,
                minutes_data=df_minutes_5m,
                trade=trade
            )

            # 记录数据级别
            pattern.data_type = "5分钟"
            pattern.is_recent = is_recent

            # 计算开盘涨幅
            if trade.signal_close > 0:
                pattern.open_gap_pct = (trade.buy_price - trade.signal_close) / trade.signal_close * 100

            # 分析走势特征（基于5分钟数据）
            self._analyze_pattern_features(pattern, df_minutes_5m, trade.buy_price, is_recent=False)

            # 如果是最近一周内的交易，额外获取1分钟级别数据
            if is_recent:
                start_time_1m = f"{formatted_date} 09:30:00"
                end_time_1m = f"{formatted_date} 09:45:00"

                try:
                    df_minutes_1m = ak.stock_zh_a_hist_min_em(
                        symbol=clean_code,
                        period="1",
                        start_date=start_time_1m,
                        end_date=end_time_1m
                    )

                    if not df_minutes_1m.empty:
                        # 保存1分钟数据到额外字段
                        pattern.minutes_data_1m = df_minutes_1m
                        # 基于1分钟数据重新分析（用于单独统计）
                        pattern_1m = OpenMinutesPattern(
                            stock_code=clean_code,
                            stock_name=trade.stock_name,
                            buy_date=trade.buy_date,
                            open_price=trade.buy_price,
                            signal_close=trade.signal_close,
                            minutes_data=df_minutes_1m,
                            trade=trade,
                            data_type="1分钟",
                            is_recent=True
                        )
                        pattern_1m.open_gap_pct = pattern.open_gap_pct
                        self._analyze_pattern_features(pattern_1m, df_minutes_1m, trade.buy_price, is_recent=True)
                        # 将1分钟级别的分析结果保存到pattern中
                        pattern.pattern_1m = pattern_1m
                except Exception as e:
                    logging.debug(f"获取 {trade.stock_name}({clean_code}) {buy_date_str} 1分钟级别数据失败: {e}")

            return pattern

        except Exception as e:
            # 输出详细的错误信息
            error_type = type(e).__name__
            error_msg = str(e)
            logging.warning(f"❌ 分析 {trade.stock_name}({clean_code}) {buy_date_str} 失败")
            logging.warning(f"   错误类型: {error_type}")
            logging.warning(f"   错误信息: {error_msg}")
            if 'formatted_date' in locals():
                logging.warning(f"   请求参数: symbol={clean_code}, date={formatted_date}")
            return None

    def _analyze_pattern_features(self, pattern: OpenMinutesPattern,
                                  df_minutes: pd.DataFrame, open_price: float, is_recent: bool = True):
        """
        分析走势特征
        
        Args:
            pattern: 走势模式对象
            df_minutes: K线数据（1分钟或5分钟级别）
            open_price: 开盘价
            is_recent: 是否为一周内的数据（1分钟级别）
        """
        if df_minutes.empty:
            return

        # 确保数据按时间排序
        df_minutes = df_minutes.sort_values('时间').reset_index(drop=True)

        # 获取关键价格（转换为列表，避免numpy数组的布尔判断问题）
        closes = df_minutes['收盘'].tolist()
        highs = df_minutes['最高'].tolist()
        lows = df_minutes['最低'].tolist()
        volumes = df_minutes['成交量'].tolist()

        # 基础数据
        pattern.first_minute_close = closes[0] if len(closes) > 0 else open_price
        pattern.last_minute_close = closes[-1] if len(closes) > 0 else open_price
        pattern.highest_price = max(highs) if len(highs) > 0 else open_price
        pattern.lowest_price = min(lows) if len(lows) > 0 else open_price

        # 计算相对开盘的涨跌幅
        if open_price > 0:
            pattern.max_rise_pct = (pattern.highest_price - open_price) / open_price * 100
            pattern.max_fall_pct = (pattern.lowest_price - open_price) / open_price * 100
            pattern.final_change_pct = (pattern.last_minute_close - open_price) / open_price * 100

        # 成交量统计
        pattern.total_volume = sum(volumes) if len(volumes) > 0 else 0
        pattern.avg_volume = pattern.total_volume / len(volumes) if len(volumes) > 0 else 0

        # 识别走势模式（根据数据级别调整判断逻辑）
        pattern.pattern_type = self._identify_pattern_type(pattern, closes, open_price, is_recent)

    def _identify_pattern_type(self, pattern: OpenMinutesPattern,
                               closes: List[float], open_price: float, is_recent: bool = True) -> str:
        """
        识别走势模式
        
        模式定义：
        1. 直接拉升：开盘后持续上涨，收盘价 > 开盘价，且最大跌幅 < 阈值
        2. 先跌后拉：开盘后先下跌（最大跌幅 >= 阈值），然后上涨，收盘价 > 开盘价
        3. 直接下跌：开盘后持续下跌，收盘价 < 开盘价，且最大涨幅 < 阈值
        4. 先涨后跌：开盘后先上涨（最大涨幅 >= 阈值），然后下跌，收盘价 < 开盘价
        5. 横盘震荡：开盘后震荡，收盘价接近开盘价（±阈值以内）
        
        阈值配置：
        - PATTERN_HORIZONTAL_THRESHOLD: 横盘判断阈值（默认0.5%）
        - PATTERN_DIRECT_THRESHOLD: 直接拉升/下跌判断阈值（默认1.0%）
        
        Args:
            pattern: 走势模式对象
            closes: 收盘价列表
            open_price: 开盘价
            is_recent: 是否为一周内的数据（1分钟级别）
            
        Returns:
            走势模式名称
        """
        if not closes or open_price <= 0:
            return "数据不足"

        final_change = pattern.final_change_pct
        max_rise = pattern.max_rise_pct
        max_fall = pattern.max_fall_pct

        # 判断是否横盘（使用全局配置的阈值）
        if abs(final_change) <= PATTERN_HORIZONTAL_THRESHOLD:
            return "横盘震荡"

        # 判断上涨模式
        if final_change > 0:
            if max_fall >= -PATTERN_DIRECT_THRESHOLD:  # 最大跌幅小于阈值，视为直接拉升
                return "直接拉升"
            else:  # 有明显下跌后上涨
                return "先跌后拉"

        # 判断下跌模式
        else:  # final_change < 0
            if max_rise <= PATTERN_DIRECT_THRESHOLD:  # 最大涨幅小于阈值，视为直接下跌
                return "直接下跌"
            else:  # 有明显上涨后下跌
                return "先涨后跌"

    def generate_statistics(self) -> Dict:
        """
        生成统计分析
        
        Returns:
            统计结果字典
        """
        if not self.patterns:
            return {}

        stats = {
            'total_patterns': len(self.patterns),
            'by_open_gap': defaultdict(list),  # 按开盘涨幅分组
            'by_pattern_type': defaultdict(list),  # 按走势模式分组
            'by_combined': defaultdict(list),  # 按开盘涨幅+走势模式组合分组
        }

        # 按开盘涨幅分组
        for pattern in self.patterns:
            gap_range = self._get_open_gap_range(pattern.open_gap_pct)
            stats['by_open_gap'][gap_range].append(pattern)

        # 按走势模式分组
        for pattern in self.patterns:
            stats['by_pattern_type'][pattern.pattern_type].append(pattern)

        # 按开盘涨幅+走势模式组合分组
        for pattern in self.patterns:
            gap_range = self._get_open_gap_range(pattern.open_gap_pct)
            combined_key = f"{gap_range}+{pattern.pattern_type}"
            stats['by_combined'][combined_key].append(pattern)

        return stats

    def _get_open_gap_range(self, open_gap_pct: float) -> str:
        """
        获取开盘涨幅区间标签
        
        Args:
            open_gap_pct: 开盘涨幅%
            
        Returns:
            区间标签
        """
        if open_gap_pct < -6:
            return "<-6%"
        elif open_gap_pct < -3:
            return "-6%~-3%"
        elif open_gap_pct < 0:
            return "-3%~0%"
        elif open_gap_pct < 3:
            return "0%~3%"
        elif open_gap_pct < 6:
            return "3%~6%"
        else:
            return ">=6%"

    def _calc_group_stats(self, patterns: List[OpenMinutesPattern]) -> Dict:
        """
        计算分组统计数据
        
        Args:
            patterns: 走势模式列表
            
        Returns:
            统计字典
        """
        if not patterns:
            return {}

        trades = [p.trade for p in patterns if p.trade]
        if not trades:
            return {}

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

        return {
            'count': count,
            'win_count': win_count,
            'win_rate': win_rate,
            'avg_profit': avg_return,
            'avg_win': avg_profit,
            'avg_loss': avg_loss,
            'pl_ratio': pl_ratio,
            'expected_value': expected_value
        }

    def generate_report(self, output_path: str = None) -> str:
        """
        生成分析报告
        
        Args:
            output_path: 输出文件路径，如果为None则使用默认路径
            
        Returns:
            报告文件路径
        """
        if not self.patterns:
            logging.warning("没有走势数据，无法生成报告")
            return ""

        stats = self.generate_statistics()

        lines = []
        lines.append("# 📊 建仓日开盘走势分析报告\n")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**分析样本数**: {len(self.patterns)} 笔交易（全部基于5分钟级别，9:30-9:45，15分钟）\n")
        if self.patterns_1m:
            lines.append(f"**额外分析**: {len(self.patterns_1m)} 笔交易（1分钟级别，最近一周内，9:30-9:45，15分钟）\n")

        # 1. 按开盘涨幅分组统计
        lines.append("\n## 1. 按开盘涨幅分组统计\n")
        lines.append("分析不同开盘涨幅区间的交易表现：\n")
        lines.append("| 开盘涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 | 期望值 |")
        lines.append("|----------|--------|------|----------|--------|--------|")

        gap_ranges = ["<-6%", "-6%~-3%", "-3%~0%", "0%~3%", "3%~6%", ">=6%"]

        for gap_range in gap_ranges:
            patterns = stats['by_open_gap'].get(gap_range, [])
            if patterns:
                group_stats = self._calc_group_stats(patterns)
                lines.append(
                    f"| {gap_range} | {group_stats['count']} | {group_stats['win_rate']:.1f}% | "
                    f"{group_stats['avg_profit']:+.2f}% | {group_stats['pl_ratio']:.2f} | "
                    f"{group_stats['expected_value']:+.2f}% |"
                )
            else:
                # 即使没有数据也保留该行
                lines.append(
                    f"| {gap_range} | 0 | - | - | - | - |"
                )

        # 2. 按走势模式分组统计
        lines.append("\n## 2. 按走势模式分组统计\n")
        lines.append("分析不同开盘后走势模式的交易表现：\n")
        lines.append("| 走势模式 | 交易数 | 胜率 | 平均收益 | 盈亏比 | 期望值 |")
        lines.append("|----------|--------|------|----------|--------|--------|")

        pattern_types = ["直接拉升", "先跌后拉", "直接下跌", "先涨后跌", "横盘震荡", "数据不足"]

        for pattern_type in pattern_types:
            patterns = stats['by_pattern_type'].get(pattern_type, [])
            if patterns:
                group_stats = self._calc_group_stats(patterns)
                lines.append(
                    f"| {pattern_type} | {group_stats['count']} | {group_stats['win_rate']:.1f}% | "
                    f"{group_stats['avg_profit']:+.2f}% | {group_stats['pl_ratio']:.2f} | "
                    f"{group_stats['expected_value']:+.2f}% |"
                )

        # 3. 按开盘涨幅+走势模式组合分组统计
        lines.append("\n## 3. 按开盘涨幅+走势模式组合分组统计\n")
        lines.append("综合分析开盘涨幅和开盘后走势的组合效果（固定排序）：\n")
        lines.append("| 开盘涨幅+走势模式 | 交易数 | 胜率 | 平均收益 | 盈亏比 | 期望值 |")
        lines.append("|------------------|--------|------|----------|--------|--------|")

        # 固定排序：开盘涨幅顺序和走势模式顺序
        gap_ranges = ["<-6%", "-6%~-3%", "-3%~0%", "0%~3%", "3%~6%", ">=6%"]
        pattern_types = ["直接拉升", "先跌后拉", "直接下跌", "先涨后跌", "横盘震荡"]

        # 生成所有可能的组合（固定顺序）
        for gap_range in gap_ranges:
            for pattern_type in pattern_types:
                combined_key = f"{gap_range}+{pattern_type}"
                patterns = stats['by_combined'].get(combined_key, [])

                if patterns:
                    group_stats = self._calc_group_stats(patterns)
                    lines.append(
                        f"| {combined_key} | {group_stats['count']} | {group_stats['win_rate']:.1f}% | "
                        f"{group_stats['avg_profit']:+.2f}% | {group_stats['pl_ratio']:.2f} | "
                        f"{group_stats['expected_value']:+.2f}% |"
                    )
                else:
                    # 即使没有数据也保留该行
                    lines.append(
                        f"| {combined_key} | 0 | - | - | - | - |"
                    )

        # 4. 1分钟级别数据统计（最近一周内，单独统计）
        if self.patterns_1m:
            lines.append("\n## 4. 1分钟级别数据统计（最近一周内，9:30-9:45，15分钟）\n")
            lines.append("这部分是最近一周内交易的额外分析，使用1分钟级别数据：\n")
            recent_stats = self._generate_stats_for_patterns(self.patterns_1m)
            lines.extend(recent_stats)

        # 5. 详细数据（可选，如果样本数不太多）
        if len(self.patterns) <= 100:
            lines.append("\n## 5. 详细数据（基于5分钟级别）\n")
            lines.append("| 股票 | 建仓日 | 开盘涨幅 | 走势模式(5分钟) | 9:45涨幅 | 最终收益 |")
            lines.append("|------|--------|----------|----------------|----------|----------|")

            for pattern in sorted(self.patterns, key=lambda x: x.trade.profit_pct if x.trade else 0, reverse=True):
                trade = pattern.trade
                if trade:
                    buy_date_short = f"{pattern.buy_date[4:6]}/{pattern.buy_date[6:]}"
                    profit_str = f"+{trade.profit_pct:.2f}%" if trade.profit_pct >= 0 else f"{trade.profit_pct:.2f}%"
                    lines.append(
                        f"| {pattern.stock_name} | {buy_date_short} | "
                        f"{pattern.open_gap_pct:+.2f}% | {pattern.pattern_type} | "
                        f"{pattern.final_change_pct:+.2f}% | {profit_str} |"
                    )

            # 如果有1分钟级别数据，也显示
            if self.patterns_1m:
                lines.append("\n### 1分钟级别详细数据（最近一周内）\n")
                lines.append("| 股票 | 建仓日 | 开盘涨幅 | 走势模式(1分钟) | 9:45涨幅 | 最终收益 |")
                lines.append("|------|--------|----------|----------------|----------|----------|")

                for pattern in sorted(self.patterns_1m, key=lambda x: x.trade.profit_pct if x.trade else 0,
                                      reverse=True):
                    trade = pattern.trade
                    if trade:
                        buy_date_short = f"{pattern.buy_date[4:6]}/{pattern.buy_date[6:]}"
                        profit_str = f"+{trade.profit_pct:.2f}%" if trade.profit_pct >= 0 else f"{trade.profit_pct:.2f}%"
                        lines.append(
                            f"| {pattern.stock_name} | {buy_date_short} | "
                            f"{pattern.open_gap_pct:+.2f}% | {pattern.pattern_type} | "
                            f"{pattern.final_change_pct:+.2f}% | {profit_str} |"
                        )

        # 6. 分析结论
        lines.append("\n## 6. 分析结论\n")
        conclusions = self._generate_conclusions(stats)
        lines.extend(conclusions)

        # 写入文件
        if output_path is None:
            # 使用CSV文件所在目录（从analyzer的input_file获取）
            # 如果无法获取，则使用当前目录
            output_dir = getattr(self, '_output_dir', None) or '.'
            output_path = os.path.join(output_dir, 'open_minutes_analysis_report.md')

        content = '\n'.join(lines)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return output_path

    def _generate_stats_for_patterns(self, patterns: List[OpenMinutesPattern]) -> List[str]:
        """
        为指定的模式列表生成统计表格
        
        Args:
            patterns: 走势模式列表
            
        Returns:
            报告行列表
        """
        lines = []

        if not patterns:
            lines.append("*无数据*\n")
            return lines

        # 按开盘涨幅分组
        lines.append("### 按开盘涨幅分组\n")
        lines.append("| 开盘涨幅 | 交易数 | 胜率 | 平均收益 | 盈亏比 | 期望值 |")
        lines.append("|----------|--------|------|----------|--------|--------|")

        gap_ranges = ["<-6%", "-6%~-4%", "-4%~-2%", "-2%~0%", "0%~1%", "1%~2%",
                      "2%~3%", "3%~4%", "4%~5%", "5%~6%", ">=6%"]

        for gap_range in gap_ranges:
            patterns_in_range = [p for p in patterns if self._get_open_gap_range(p.open_gap_pct) == gap_range]
            if patterns_in_range:
                group_stats = self._calc_group_stats(patterns_in_range)
                lines.append(
                    f"| {gap_range} | {group_stats['count']} | {group_stats['win_rate']:.1f}% | "
                    f"{group_stats['avg_profit']:+.2f}% | {group_stats['pl_ratio']:.2f} | "
                    f"{group_stats['expected_value']:+.2f}% |"
                )

        # 按走势模式分组
        lines.append("\n### 按走势模式分组\n")
        lines.append("| 走势模式 | 交易数 | 胜率 | 平均收益 | 盈亏比 | 期望值 |")
        lines.append("|----------|--------|------|----------|--------|--------|")

        pattern_types = ["直接拉升", "先跌后拉", "直接下跌", "先涨后跌", "横盘震荡", "数据不足"]

        for pattern_type in pattern_types:
            patterns_of_type = [p for p in patterns if p.pattern_type == pattern_type]
            if patterns_of_type:
                group_stats = self._calc_group_stats(patterns_of_type)
                lines.append(
                    f"| {pattern_type} | {group_stats['count']} | {group_stats['win_rate']:.1f}% | "
                    f"{group_stats['avg_profit']:+.2f}% | {group_stats['pl_ratio']:.2f} | "
                    f"{group_stats['expected_value']:+.2f}% |"
                )

        return lines

    def _generate_conclusions(self, stats: Dict) -> List[str]:
        """
        生成分析结论
        
        Args:
            stats: 统计数据
            
        Returns:
            结论列表
        """
        conclusions = []

        # 找出表现最好的组合
        combined_stats_list = []
        for combined_key, patterns in stats['by_combined'].items():
            group_stats = self._calc_group_stats(patterns)
            if group_stats['count'] >= 3:  # 至少3个样本
                combined_stats_list.append({
                    'key': combined_key,
                    'stats': group_stats
                })

        if combined_stats_list:
            # 按期望值排序
            combined_stats_list.sort(key=lambda x: x['stats']['expected_value'], reverse=True)

            best = combined_stats_list[0]
            conclusions.append(
                f"1. **最佳组合**: {best['key']} - 期望值 {best['stats']['expected_value']:+.2f}%，"
                f"胜率 {best['stats']['win_rate']:.1f}%，样本数 {best['stats']['count']}"
            )

            # 找出表现最差的组合
            worst = combined_stats_list[-1]
            if worst['stats']['expected_value'] < 0:
                conclusions.append(
                    f"2. **最差组合**: {worst['key']} - 期望值 {worst['stats']['expected_value']:+.2f}%，"
                    f"应避免此类交易，样本数 {worst['stats']['count']}"
                )

        # 分析走势模式
        pattern_stats_list = []
        for pattern_type, patterns in stats['by_pattern_type'].items():
            group_stats = self._calc_group_stats(patterns)
            if group_stats['count'] >= 3:
                pattern_stats_list.append({
                    'type': pattern_type,
                    'stats': group_stats
                })

        if pattern_stats_list:
            pattern_stats_list.sort(key=lambda x: x['stats']['expected_value'], reverse=True)
            best_pattern = pattern_stats_list[0]
            conclusions.append(
                f"3. **最佳走势模式**: {best_pattern['type']} - 期望值 {best_pattern['stats']['expected_value']:+.2f}%，"
                f"胜率 {best_pattern['stats']['win_rate']:.1f}%"
            )

        return conclusions


def analyze_open_minutes(summary_csv_path: str,
                         strong_definition: str = 'close_gt_prev_close_or_open',
                         min_hold_days: int = 1,
                         max_hold_days: int = 30,
                         buy_price_range: tuple = None,
                         strong_price_range: tuple = None,
                         data_path: str = './data/astocks',
                         output_path: str = None) -> str:
    """
    便捷函数：分析建仓日开盘前15分钟走势
    
    Args:
        summary_csv_path: 信号汇总CSV文件路径
        strong_definition: 走强定义
        min_hold_days: 最少持有天数
        max_hold_days: 最大持有天数
        buy_price_range: 买入价格范围（开盘涨幅%）
        strong_price_range: 走强价格范围（收盘涨幅%）
        data_path: 股票数据目录
        output_path: 报告输出路径，None则使用默认路径
        
    Returns:
        报告文件路径
    """
    # 先运行回测获取交易记录
    from analysis.strategy_backtest_analyzer import run_backtest

    print("=" * 60)
    print("步骤1: 运行回测获取交易记录...")
    print("=" * 60)

    backtest_result = run_backtest(
        summary_csv_path=summary_csv_path,
        strong_definition=strong_definition,
        min_hold_days=min_hold_days,
        max_hold_days=max_hold_days,
        buy_price_range=buy_price_range,
        strong_price_range=strong_price_range,
        data_path=data_path
    )

    if not backtest_result or not backtest_result.trades:
        logging.error("回测失败或没有有效交易")
        return ""

    # 显示回测结果统计
    print(f"\n📊 回测结果统计:")
    print(f"   - 总信号数: {backtest_result.total_signals}")
    print(f"   - 有效交易数: {backtest_result.valid_trades}")
    print(f"   - 盈利交易: {backtest_result.win_trades} 笔")
    print(f"   - 亏损交易: {backtest_result.loss_trades} 笔")
    print(f"   - 胜率: {backtest_result.win_rate:.1f}%")

    # 分析开盘前15分钟走势
    print("\n" + "=" * 60)
    print("步骤2: 分析开盘前15分钟走势...")
    print("=" * 60)

    # 获取输出目录（CSV文件所在目录）
    output_dir = os.path.dirname(os.path.abspath(summary_csv_path))

    analyzer = OpenMinutesAnalyzer(backtest_result, output_dir=output_dir)
    patterns = analyzer.analyze()

    if not patterns:
        logging.warning("没有成功分析任何走势数据")
        return ""

    # 生成报告
    print("\n" + "=" * 60)
    print("步骤3: 生成分析报告...")
    print("=" * 60)

    report_path = analyzer.generate_report(output_path)

    if report_path:
        print(f"\n✅ 报告已保存至: {report_path}")

    return report_path


if __name__ == '__main__':
    # 测试代码
    import sys

    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # 默认测试路径
        csv_path = 'analysis/pattern_charts/爆量分歧转一致/20251201_20251226/summary.csv'

    if os.path.exists(csv_path):
        report_path = analyze_open_minutes(csv_path)
        if report_path:
            print(f"\n分析完成，报告路径: {report_path}")
    else:
        print(f"文件不存在: {csv_path}")
