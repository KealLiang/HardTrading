"""
二板定龙头分析器

分析二连板股票的胜率、晋级率、题材概念分布及量价特征，
帮助理解市场热点和龙头股特征。

功能：
1. 统计指定时间段内二连板股票的各种数据
2. 分析晋级（继续连板）vs淘汰（断板）的特征差异
3. 统计题材概念的晋级率排名（拆分组合概念）
4. 分析量价关系与晋级的关联
5. 生成Markdown格式的分析报告

胜率定义：
- T日二板，T+1日开盘价买入
- 胜率(开盘卖)：T+2日开盘价卖出盈利的比率
- 胜率(收盘卖)：T+2日收盘价卖出盈利的比率
"""

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

import pandas as pd

from analysis.loader.fupan_data_loader import load_lianban_data, extract_board_info
from utils.file_util import read_stock_data


@dataclass
class ErbanStock:
    """二板股票数据类"""
    stock_code: str
    stock_name: str
    erban_date: str  # 二板日期 (YYYYMMDD)
    concept: str  # 题材概念

    # 二板当天数据 (T日)
    erban_open: float = 0.0  # 开盘价
    erban_close: float = 0.0  # 收盘价
    erban_high: float = 0.0  # 最高价
    erban_low: float = 0.0  # 最低价
    erban_volume: float = 0.0  # 成交量
    erban_amount: float = 0.0  # 成交额
    erban_change_pct: float = 0.0  # 涨跌幅
    erban_amplitude: float = 0.0  # 振幅
    erban_turnover: float = 0.0  # 换手率

    # 首板当天数据（T-1日）
    shouban_open: float = 0.0
    shouban_close: float = 0.0
    shouban_volume: float = 0.0
    shouban_change_pct: float = 0.0
    shouban_turnover: float = 0.0
    shouban_body_change: float = 0.0  # 首板实体涨幅 = (收盘-开盘)/开盘

    # T+1日数据（买入日）
    day1_open: float = 0.0  # 买入价
    day1_close: float = 0.0
    day1_high: float = 0.0
    day1_low: float = 0.0

    # T+2日数据（卖出日）
    day2_open: float = 0.0  # 开盘卖出价
    day2_close: float = 0.0  # 收盘卖出价
    day2_high: float = 0.0
    day2_low: float = 0.0

    # 结果标记
    is_promoted: bool = False  # 是否晋级到三板

    # 胜率相关（T+1开盘买入）
    profit_by_day2_open: float = 0.0  # T+2开盘卖出的收益率
    profit_by_day2_close: float = 0.0  # T+2收盘卖出的收益率
    is_win_by_day2_open: bool = False  # T+2开盘卖出是否盈利
    is_win_by_day2_close: bool = False  # T+2收盘卖出是否盈利
    has_valid_trade_data: bool = False  # 是否有有效的交易数据

    # 胜率相关（T日涨停价买入）
    profit_by_day1_open: float = 0.0  # T+1开盘卖出的收益率（T日涨停价买入）
    profit_by_day1_close: float = 0.0  # T+1收盘卖出的收益率（T日涨停价买入）
    is_win_by_day1_open: bool = False  # T+1开盘卖出是否盈利
    is_win_by_day1_close: bool = False  # T+1收盘卖出是否盈利
    has_valid_zt_trade_data: bool = False  # 是否有有效的涨停价买入交易数据

    # 计算指标
    volume_ratio: float = 0.0  # 二板相对首板的量比
    open_strength: float = 0.0  # 开盘强度（相对前一日收盘的跳空）


@dataclass
class ConceptStats:
    """题材概念统计数据类"""
    concept_name: str
    total_count: int = 0
    promoted_count: int = 0
    # 胜率统计
    win_by_open_count: int = 0  # T+2开盘卖盈利数量
    win_by_close_count: int = 0  # T+2收盘卖盈利数量
    valid_trade_count: int = 0  # 有效交易数据数量
    # 涨停价买入策略统计
    win_by_day1_open_count: int = 0  # T+1开盘卖盈利数量
    win_by_day1_close_count: int = 0  # T+1收盘卖盈利数量
    valid_zt_trade_count: int = 0  # 有效涨停价买入交易数据数量
    # 盈亏统计
    total_profit_by_open: float = 0.0
    total_profit_by_close: float = 0.0
    total_loss_by_open: float = 0.0
    total_loss_by_close: float = 0.0
    profit_count_by_open: int = 0
    loss_count_by_open: int = 0
    profit_count_by_close: int = 0
    loss_count_by_close: int = 0
    total_profit_by_day1_open: float = 0.0
    total_profit_by_day1_close: float = 0.0
    total_loss_by_day1_open: float = 0.0
    total_loss_by_day1_close: float = 0.0
    profit_count_by_day1_open: int = 0
    loss_count_by_day1_open: int = 0
    profit_count_by_day1_close: int = 0
    loss_count_by_day1_close: int = 0

    stocks: List[str] = field(default_factory=list)

    @property
    def promotion_rate(self) -> float:
        return self.promoted_count / self.total_count * 100 if self.total_count > 0 else 0

    @property
    def win_rate_by_open(self) -> float:
        """T+2开盘卖胜率"""
        return self.win_by_open_count / self.valid_trade_count * 100 if self.valid_trade_count > 0 else 0

    @property
    def win_rate_by_close(self) -> float:
        """T+2收盘卖胜率"""
        return self.win_by_close_count / self.valid_trade_count * 100 if self.valid_trade_count > 0 else 0

    @property
    def profit_loss_ratio_by_open(self) -> float:
        """T+2开盘卖盈亏比"""
        if self.loss_count_by_open == 0 or self.profit_count_by_open == 0:
            return 0
        avg_profit = self.total_profit_by_open / self.profit_count_by_open
        avg_loss = abs(self.total_loss_by_open / self.loss_count_by_open)
        return avg_profit / avg_loss if avg_loss > 0 else 0

    @property
    def profit_loss_ratio_by_close(self) -> float:
        """T+2收盘卖盈亏比"""
        if self.loss_count_by_close == 0 or self.profit_count_by_close == 0:
            return 0
        avg_profit = self.total_profit_by_close / self.profit_count_by_close
        avg_loss = abs(self.total_loss_by_close / self.loss_count_by_close)
        return avg_profit / avg_loss if avg_loss > 0 else 0

    @property
    def win_rate_by_day1_open(self) -> float:
        """T+1开盘卖胜率（涨停价买入）"""
        return self.win_by_day1_open_count / self.valid_zt_trade_count * 100 if self.valid_zt_trade_count > 0 else 0

    @property
    def win_rate_by_day1_close(self) -> float:
        """T+1收盘卖胜率（涨停价买入）"""
        return self.win_by_day1_close_count / self.valid_zt_trade_count * 100 if self.valid_zt_trade_count > 0 else 0

    @property
    def profit_loss_ratio_by_day1_open(self) -> float:
        """T+1开盘卖盈亏比（涨停价买入）"""
        if self.loss_count_by_day1_open == 0 or self.profit_count_by_day1_open == 0:
            return 0
        avg_profit = self.total_profit_by_day1_open / self.profit_count_by_day1_open
        avg_loss = abs(self.total_loss_by_day1_open / self.loss_count_by_day1_open)
        return avg_profit / avg_loss if avg_loss > 0 else 0

    @property
    def profit_loss_ratio_by_day1_close(self) -> float:
        """T+1收盘卖盈亏比（涨停价买入）"""
        if self.loss_count_by_day1_close == 0 or self.profit_count_by_day1_close == 0:
            return 0
        avg_profit = self.total_profit_by_day1_close / self.profit_count_by_day1_close
        avg_loss = abs(self.total_loss_by_day1_close / self.loss_count_by_day1_close)
        return avg_profit / avg_loss if avg_loss > 0 else 0


class ErbanLongtouAnalyzer:
    """二板定龙头分析器"""

    def __init__(self, data_path: str = './data/astocks'):
        self.data_path = data_path
        self.erban_stocks: List[ErbanStock] = []
        self.concept_stats: Dict[str, ConceptStats] = {}
        self.daily_stats: Dict[str, Dict] = {}  # 每日统计
        self.start_date: str = ''
        self.end_date: str = ''

    def analyze(self, start_date: str, end_date: str,
                min_samples: int = 2) -> Dict:
        """
        执行二板分析
        
        Args:
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            min_samples: 题材统计最小样本数
            
        Returns:
            分析结果字典
        """
        self.start_date = start_date
        self.end_date = end_date

        print(f"\n{'=' * 60}")
        print(f"二板定龙头分析")
        print(f"时间范围: {start_date} - {end_date}")
        print(f"{'=' * 60}\n")

        # 1. 加载连板数据
        print("[1/5] 加载连板数据...")
        lianban_df = load_lianban_data(start_date, end_date)
        if lianban_df.empty:
            print("❌ 未找到连板数据")
            return {}

        # 2. 提取二板股票
        print("\n[2/5] 提取二板股票...")
        self._extract_erban_stocks(lianban_df, start_date, end_date)
        if not self.erban_stocks:
            print("❌ 未找到二板股票")
            return {}
        print(f"✅ 找到 {len(self.erban_stocks)} 只二板股票")

        # 3. 获取交易数据
        print("\n[3/5] 获取交易数据...")
        self._fetch_trading_data()

        # 4. 判断晋级情况
        print("\n[4/5] 分析晋级情况...")
        self._analyze_promotion(lianban_df)

        # 5. 统计分析
        print("\n[5/5] 统计分析...")
        results = self._calculate_statistics(min_samples)

        return results

    def _extract_erban_stocks(self, lianban_df: pd.DataFrame,
                              start_date: str, end_date: str):
        """从连板数据中提取二板股票"""
        self.erban_stocks = []

        # 获取日期列
        date_columns = [col for col in lianban_df.columns
                        if '年' in str(col) or re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', str(col))]

        for _, row in lianban_df.iterrows():
            stock_code = row.get('纯代码', '')
            stock_name = row.get('股票名称', '')
            concept = row.get('概念', '其他')

            if not stock_code or not stock_name:
                continue

            # 检查每个日期
            for col in date_columns:
                if pd.isna(row[col]):
                    continue

                board_days, _ = extract_board_info(row[col])

                # 只关注二板
                if board_days == 2:
                    # 转换日期格式
                    if '年' in col:
                        date_parts = re.findall(r'\d+', col)
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}{int(date_parts[1]):02d}{int(date_parts[2]):02d}"
                        else:
                            continue
                    else:
                        date_obj = pd.to_datetime(col)
                        date_str = date_obj.strftime('%Y%m%d')

                    # 确保在分析范围内
                    if date_str < start_date or date_str > end_date:
                        continue

                    erban = ErbanStock(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        erban_date=date_str,
                        concept=concept
                    )
                    self.erban_stocks.append(erban)

    def _fetch_trading_data(self):
        """获取交易数据"""
        success_count = 0
        fail_count = 0

        for erban in self.erban_stocks:
            try:
                df = read_stock_data(erban.stock_code, self.data_path)
                if df is None or df.empty:
                    fail_count += 1
                    continue

                # 转换日期格式用于匹配
                df['日期_str'] = df['日期'].dt.strftime('%Y%m%d')

                # 获取二板当天数据 (T日)
                erban_data = df[df['日期_str'] == erban.erban_date]
                if not erban_data.empty:
                    row = erban_data.iloc[0]
                    erban.erban_open = row['开盘']
                    erban.erban_close = row['收盘']
                    erban.erban_high = row['最高']
                    erban.erban_low = row['最低']
                    erban.erban_volume = row['成交量']
                    erban.erban_amount = row['成交额']
                    erban.erban_change_pct = row['涨跌幅']
                    erban.erban_amplitude = row['振幅']
                    erban.erban_turnover = row['换手率']

                # 获取索引位置
                erban_idx_list = df[df['日期_str'] == erban.erban_date].index.tolist()
                if not erban_idx_list:
                    fail_count += 1
                    continue

                idx = erban_idx_list[0]

                # 获取首板数据 (T-1日)
                if idx > 0:
                    prev_row = df.iloc[idx - 1]
                    erban.shouban_open = prev_row['开盘']
                    erban.shouban_close = prev_row['收盘']
                    erban.shouban_volume = prev_row['成交量']
                    erban.shouban_change_pct = prev_row['涨跌幅']
                    erban.shouban_turnover = prev_row['换手率']

                    # 计算首板实体涨幅
                    if erban.shouban_open > 0:
                        erban.shouban_body_change = (
                                                            erban.shouban_close - erban.shouban_open) / erban.shouban_open * 100

                    # 计算量比
                    if erban.shouban_volume > 0:
                        erban.volume_ratio = erban.erban_volume / erban.shouban_volume

                    # 计算开盘强度（相对前收的跳空）
                    if erban.shouban_close > 0:
                        erban.open_strength = (erban.erban_open - erban.shouban_close) / erban.shouban_close * 100

                # 获取T+1日数据（买入日）
                if idx < len(df) - 1:
                    day1_row = df.iloc[idx + 1]
                    erban.day1_open = day1_row['开盘']
                    erban.day1_close = day1_row['收盘']
                    erban.day1_high = day1_row['最高']
                    erban.day1_low = day1_row['最低']

                # 获取T+2日数据（卖出日）
                if idx < len(df) - 2:
                    day2_row = df.iloc[idx + 2]
                    erban.day2_open = day2_row['开盘']
                    erban.day2_close = day2_row['收盘']
                    erban.day2_high = day2_row['最高']
                    erban.day2_low = day2_row['最低']

                    # 计算收益率和胜率（T+1开盘买入）
                    if erban.day1_open > 0:
                        erban.has_valid_trade_data = True

                        # T+2开盘卖出收益率
                        erban.profit_by_day2_open = (erban.day2_open - erban.day1_open) / erban.day1_open * 100
                        erban.is_win_by_day2_open = erban.profit_by_day2_open > 0

                        # T+2收盘卖出收益率
                        erban.profit_by_day2_close = (erban.day2_close - erban.day1_open) / erban.day1_open * 100
                        erban.is_win_by_day2_close = erban.profit_by_day2_close > 0

                # 计算收益率和胜率（T日涨停价买入，T+1卖出）
                if erban.erban_high > 0 and idx < len(df) - 1:
                    erban.has_valid_zt_trade_data = True
                    buy_price = erban.erban_high  # T日涨停价（最高价）

                    # T+1开盘卖出收益率
                    if erban.day1_open > 0:
                        erban.profit_by_day1_open = (erban.day1_open - buy_price) / buy_price * 100
                        erban.is_win_by_day1_open = erban.profit_by_day1_open > 0

                    # T+1收盘卖出收益率
                    if erban.day1_close > 0:
                        erban.profit_by_day1_close = (erban.day1_close - buy_price) / buy_price * 100
                        erban.is_win_by_day1_close = erban.profit_by_day1_close > 0

                success_count += 1

            except Exception as e:
                fail_count += 1
                continue

        print(f"  成功获取: {success_count} 只, 失败: {fail_count} 只")

    def _analyze_promotion(self, lianban_df: pd.DataFrame):
        """分析晋级情况（是否成为三板）"""
        # 获取日期列
        date_columns = [col for col in lianban_df.columns
                        if '年' in str(col) or re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', str(col))]

        # 构建股票-日期-板数映射
        board_map = {}  # {stock_code: {date_str: board_days}}

        for _, row in lianban_df.iterrows():
            stock_code = row.get('纯代码', '')
            if not stock_code:
                continue

            if stock_code not in board_map:
                board_map[stock_code] = {}

            for col in date_columns:
                if pd.isna(row[col]):
                    continue

                board_days, _ = extract_board_info(row[col])
                if board_days:
                    # 转换日期
                    if '年' in col:
                        date_parts = re.findall(r'\d+', col)
                        if len(date_parts) == 3:
                            date_str = f"{date_parts[0]}{int(date_parts[1]):02d}{int(date_parts[2]):02d}"
                        else:
                            continue
                    else:
                        date_obj = pd.to_datetime(col)
                        date_str = date_obj.strftime('%Y%m%d')

                    board_map[stock_code][date_str] = board_days

        # 判断每只二板股是否晋级
        promoted_count = 0
        for erban in self.erban_stocks:
            stock_boards = board_map.get(erban.stock_code, {})

            # 检查是否有三板或更高
            for date_str, board_days in stock_boards.items():
                if board_days >= 3 and date_str > erban.erban_date:
                    erban.is_promoted = True
                    promoted_count += 1
                    break

        print(f"  晋级（三板及以上）: {promoted_count} 只")
        print(f"  淘汰（断板）: {len(self.erban_stocks) - promoted_count} 只")

    def _split_concepts(self, concept_str: str) -> List[str]:
        """拆分组合概念为单独概念"""
        if not concept_str or pd.isna(concept_str):
            return ['其他']

        # 使用 + 号拆分
        concepts = [c.strip() for c in concept_str.split('+') if c.strip()]
        return concepts if concepts else ['其他']

    def _calculate_statistics(self, min_samples: int) -> Dict:
        """计算统计数据"""
        if not self.erban_stocks:
            return {}

        # 基础统计
        total = len(self.erban_stocks)
        promoted = sum(1 for s in self.erban_stocks if s.is_promoted)

        # 有效交易数据统计
        valid_trades = [s for s in self.erban_stocks if s.has_valid_trade_data]
        valid_count = len(valid_trades)

        win_by_open = sum(1 for s in valid_trades if s.is_win_by_day2_open)
        win_by_close = sum(1 for s in valid_trades if s.is_win_by_day2_close)

        # 盈亏比计算
        profits_by_open = [s.profit_by_day2_open for s in valid_trades if s.profit_by_day2_open > 0]
        losses_by_open = [s.profit_by_day2_open for s in valid_trades if s.profit_by_day2_open < 0]
        profits_by_close = [s.profit_by_day2_close for s in valid_trades if s.profit_by_day2_close > 0]
        losses_by_close = [s.profit_by_day2_close for s in valid_trades if s.profit_by_day2_close < 0]

        avg_profit_open = sum(profits_by_open) / len(profits_by_open) if profits_by_open else 0
        avg_loss_open = abs(sum(losses_by_open) / len(losses_by_open)) if losses_by_open else 0
        avg_profit_close = sum(profits_by_close) / len(profits_by_close) if profits_by_close else 0
        avg_loss_close = abs(sum(losses_by_close) / len(losses_by_close)) if losses_by_close else 0

        pl_ratio_open = avg_profit_open / avg_loss_open if avg_loss_open > 0 else 0
        pl_ratio_close = avg_profit_close / avg_loss_close if avg_loss_close > 0 else 0

        # 有效交易数据统计（涨停价买入策略）
        valid_zt_trades = [s for s in self.erban_stocks if s.has_valid_zt_trade_data]
        valid_zt_count = len(valid_zt_trades)

        win_by_day1_open = sum(1 for s in valid_zt_trades if s.is_win_by_day1_open)
        win_by_day1_close = sum(1 for s in valid_zt_trades if s.is_win_by_day1_close)

        # 盈亏比计算（涨停价买入）
        profits_by_day1_open = [s.profit_by_day1_open for s in valid_zt_trades if s.profit_by_day1_open > 0]
        losses_by_day1_open = [s.profit_by_day1_open for s in valid_zt_trades if s.profit_by_day1_open < 0]
        profits_by_day1_close = [s.profit_by_day1_close for s in valid_zt_trades if s.profit_by_day1_close > 0]
        losses_by_day1_close = [s.profit_by_day1_close for s in valid_zt_trades if s.profit_by_day1_close < 0]

        avg_profit_day1_open = sum(profits_by_day1_open) / len(profits_by_day1_open) if profits_by_day1_open else 0
        avg_loss_day1_open = abs(sum(losses_by_day1_open) / len(losses_by_day1_open)) if losses_by_day1_open else 0
        avg_profit_day1_close = sum(profits_by_day1_close) / len(profits_by_day1_close) if profits_by_day1_close else 0
        avg_loss_day1_close = abs(sum(losses_by_day1_close) / len(losses_by_day1_close)) if losses_by_day1_close else 0

        pl_ratio_day1_open = avg_profit_day1_open / avg_loss_day1_open if avg_loss_day1_open > 0 else 0
        pl_ratio_day1_close = avg_profit_day1_close / avg_loss_day1_close if avg_loss_day1_close > 0 else 0

        # 晋级组 vs 淘汰组的特征对比
        promoted_stocks = [s for s in self.erban_stocks if s.is_promoted]
        failed_stocks = [s for s in self.erban_stocks if not s.is_promoted]

        def calc_avg(stocks: List[ErbanStock], attr: str) -> float:
            values = [getattr(s, attr) for s in stocks if getattr(s, attr, 0) != 0]
            return sum(values) / len(values) if values else 0

        promoted_features = {
            'avg_volume_ratio': calc_avg(promoted_stocks, 'volume_ratio'),
            'avg_open_strength': calc_avg(promoted_stocks, 'open_strength'),
            'avg_erban_turnover': calc_avg(promoted_stocks, 'erban_turnover'),
            'avg_erban_amplitude': calc_avg(promoted_stocks, 'erban_amplitude'),
            'avg_shouban_turnover': calc_avg(promoted_stocks, 'shouban_turnover'),
            'avg_shouban_body_change': calc_avg(promoted_stocks, 'shouban_body_change'),
        }

        failed_features = {
            'avg_volume_ratio': calc_avg(failed_stocks, 'volume_ratio'),
            'avg_open_strength': calc_avg(failed_stocks, 'open_strength'),
            'avg_erban_turnover': calc_avg(failed_stocks, 'erban_turnover'),
            'avg_erban_amplitude': calc_avg(failed_stocks, 'erban_amplitude'),
            'avg_shouban_turnover': calc_avg(failed_stocks, 'shouban_turnover'),
            'avg_shouban_body_change': calc_avg(failed_stocks, 'shouban_body_change'),
        }

        # 题材概念统计（先拆分所有独立题材，再按完整概念匹配）
        # 第一步：收集所有独立题材
        all_concepts_set = set()
        for stock in self.erban_stocks:
            concepts = self._split_concepts(stock.concept)
            all_concepts_set.update(concepts)

        # 第二步：为每个独立题材初始化统计
        concept_counter = {}
        for concept in all_concepts_set:
            concept_counter[concept] = ConceptStats(concept_name=concept)

        # 第三步：对每只股票，如果其完整概念包含某个题材，则计入该题材统计
        for stock in self.erban_stocks:
            stock_concepts = self._split_concepts(stock.concept)  # 这只股票的所有题材

            # 遍历所有独立题材，如果股票概念中包含该题材，则统计
            for concept in all_concepts_set:
                if concept in stock_concepts:
                    stats = concept_counter[concept]
                    stats.total_count += 1
                    stats.stocks.append(f"{stock.stock_name}({stock.erban_date})")

                    if stock.is_promoted:
                        stats.promoted_count += 1

                    if stock.has_valid_trade_data:
                        stats.valid_trade_count += 1

                        if stock.is_win_by_day2_open:
                            stats.win_by_open_count += 1
                        if stock.is_win_by_day2_close:
                            stats.win_by_close_count += 1

                        # 盈亏统计
                        if stock.profit_by_day2_open > 0:
                            stats.total_profit_by_open += stock.profit_by_day2_open
                            stats.profit_count_by_open += 1
                        elif stock.profit_by_day2_open < 0:
                            stats.total_loss_by_open += stock.profit_by_day2_open
                            stats.loss_count_by_open += 1

                        if stock.profit_by_day2_close > 0:
                            stats.total_profit_by_close += stock.profit_by_day2_close
                            stats.profit_count_by_close += 1
                        elif stock.profit_by_day2_close < 0:
                            stats.total_loss_by_close += stock.profit_by_day2_close
                            stats.loss_count_by_close += 1

                    if stock.has_valid_zt_trade_data:
                        stats.valid_zt_trade_count += 1

                        if stock.is_win_by_day1_open:
                            stats.win_by_day1_open_count += 1
                        if stock.is_win_by_day1_close:
                            stats.win_by_day1_close_count += 1

                        # 盈亏统计（涨停价买入）
                        if stock.profit_by_day1_open > 0:
                            stats.total_profit_by_day1_open += stock.profit_by_day1_open
                            stats.profit_count_by_day1_open += 1
                        elif stock.profit_by_day1_open < 0:
                            stats.total_loss_by_day1_open += stock.profit_by_day1_open
                            stats.loss_count_by_day1_open += 1

                        if stock.profit_by_day1_close > 0:
                            stats.total_profit_by_day1_close += stock.profit_by_day1_close
                            stats.profit_count_by_day1_close += 1
                        elif stock.profit_by_day1_close < 0:
                            stats.total_loss_by_day1_close += stock.profit_by_day1_close
                            stats.loss_count_by_day1_close += 1

        # 过滤最小样本数
        self.concept_stats = {k: v for k, v in concept_counter.items() if v.total_count >= min_samples}

        # 每日统计
        daily_data = defaultdict(lambda: {
            'total': 0, 'promoted': 0,
            'valid_trades': 0, 'win_by_open': 0, 'win_by_close': 0,
            'profits_open': [], 'losses_open': [],
            'profits_close': [], 'losses_close': []
        })

        for stock in self.erban_stocks:
            daily_data[stock.erban_date]['total'] += 1
            if stock.is_promoted:
                daily_data[stock.erban_date]['promoted'] += 1
            if stock.has_valid_trade_data:
                daily_data[stock.erban_date]['valid_trades'] += 1
                if stock.is_win_by_day2_open:
                    daily_data[stock.erban_date]['win_by_open'] += 1
                if stock.is_win_by_day2_close:
                    daily_data[stock.erban_date]['win_by_close'] += 1

                if stock.profit_by_day2_open > 0:
                    daily_data[stock.erban_date]['profits_open'].append(stock.profit_by_day2_open)
                elif stock.profit_by_day2_open < 0:
                    daily_data[stock.erban_date]['losses_open'].append(stock.profit_by_day2_open)

                if stock.profit_by_day2_close > 0:
                    daily_data[stock.erban_date]['profits_close'].append(stock.profit_by_day2_close)
                elif stock.profit_by_day2_close < 0:
                    daily_data[stock.erban_date]['losses_close'].append(stock.profit_by_day2_close)

        self.daily_stats = dict(daily_data)

        # 量比分组统计
        volume_ratio_groups = self._group_by_volume_ratio()

        # 开盘强度分组统计
        open_strength_groups = self._group_by_open_strength()

        return {
            'summary': {
                'total': total,
                'promoted': promoted,
                'promotion_rate': promoted / total * 100 if total > 0 else 0,
                'valid_trade_count': valid_count,
                'win_by_open': win_by_open,
                'win_rate_by_open': win_by_open / valid_count * 100 if valid_count > 0 else 0,
                'win_by_close': win_by_close,
                'win_rate_by_close': win_by_close / valid_count * 100 if valid_count > 0 else 0,
                'avg_profit_open': avg_profit_open,
                'avg_loss_open': avg_loss_open,
                'pl_ratio_open': pl_ratio_open,
                'avg_profit_close': avg_profit_close,
                'avg_loss_close': avg_loss_close,
                'pl_ratio_close': pl_ratio_close,
                'valid_zt_trade_count': valid_zt_count,
                'win_by_day1_open': win_by_day1_open,
                'win_rate_by_day1_open': win_by_day1_open / valid_zt_count * 100 if valid_zt_count > 0 else 0,
                'win_by_day1_close': win_by_day1_close,
                'win_rate_by_day1_close': win_by_day1_close / valid_zt_count * 100 if valid_zt_count > 0 else 0,
                'avg_profit_day1_open': avg_profit_day1_open,
                'avg_loss_day1_open': avg_loss_day1_open,
                'pl_ratio_day1_open': pl_ratio_day1_open,
                'avg_profit_day1_close': avg_profit_day1_close,
                'avg_loss_day1_close': avg_loss_day1_close,
                'pl_ratio_day1_close': pl_ratio_day1_close,
            },
            'promoted_features': promoted_features,
            'failed_features': failed_features,
            'concept_stats': self.concept_stats,
            'daily_stats': self.daily_stats,
            'volume_ratio_groups': volume_ratio_groups,
            'open_strength_groups': open_strength_groups,
        }

    def _group_by_volume_ratio(self) -> Dict:
        """按量比分组统计"""
        groups = {
            '缩量(<0.8)': {'range': (0, 0.8), 'stocks': []},
            '平量(0.8-1.2)': {'range': (0.8, 1.2), 'stocks': []},
            '温和放量(1.2-1.5)': {'range': (1.2, 1.5), 'stocks': []},
            '明显放量(1.5-2.0)': {'range': (1.5, 2.0), 'stocks': []},
            '大幅放量(>2.0)': {'range': (2.0, float('inf')), 'stocks': []},
        }

        for stock in self.erban_stocks:
            if stock.volume_ratio <= 0:
                continue
            for group_name, group_data in groups.items():
                low, high = group_data['range']
                if low <= stock.volume_ratio < high:
                    group_data['stocks'].append(stock)
                    break

        result = {}
        for group_name, group_data in groups.items():
            stocks = group_data['stocks']
            if stocks:
                promoted = sum(1 for s in stocks if s.is_promoted)
                valid = [s for s in stocks if s.has_valid_trade_data]
                win_open = sum(1 for s in valid if s.is_win_by_day2_open)
                win_close = sum(1 for s in valid if s.is_win_by_day2_close)

                result[group_name] = {
                    'count': len(stocks),
                    'promoted': promoted,
                    'promotion_rate': promoted / len(stocks) * 100,
                    'valid_count': len(valid),
                    'win_rate_open': win_open / len(valid) * 100 if valid else 0,
                    'win_rate_close': win_close / len(valid) * 100 if valid else 0,
                }

        return result

    def _group_by_open_strength(self) -> Dict:
        """按开盘强度分组统计"""
        groups = {
            '低开(<3%)': {'range': (-float('inf'), 3), 'stocks': []},
            '平开(3-5%)': {'range': (3, 5), 'stocks': []},
            '强势(5-7%)': {'range': (5, 7), 'stocks': []},
            '一字(>7%)': {'range': (7, float('inf')), 'stocks': []},
        }

        for stock in self.erban_stocks:
            for group_name, group_data in groups.items():
                low, high = group_data['range']
                if low <= stock.open_strength < high:
                    group_data['stocks'].append(stock)
                    break

        result = {}
        for group_name, group_data in groups.items():
            stocks = group_data['stocks']
            if stocks:
                promoted = sum(1 for s in stocks if s.is_promoted)
                valid = [s for s in stocks if s.has_valid_trade_data]
                win_open = sum(1 for s in valid if s.is_win_by_day2_open)
                win_close = sum(1 for s in valid if s.is_win_by_day2_close)

                result[group_name] = {
                    'count': len(stocks),
                    'promoted': promoted,
                    'promotion_rate': promoted / len(stocks) * 100,
                    'valid_count': len(valid),
                    'win_rate_open': win_open / len(valid) * 100 if valid else 0,
                    'win_rate_close': win_close / len(valid) * 100 if valid else 0,
                }

        return result

    def generate_report(self, results: Dict, output_path: str = None) -> str:
        """
        生成Markdown分析报告
        
        Args:
            results: 分析结果
            output_path: 输出路径，如果为None则自动生成
            
        Returns:
            报告文件路径
        """
        if not results:
            return ""

        # 确定输出路径（使用分析日期范围命名）
        if output_path is None:
            os.makedirs('./reports', exist_ok=True)
            output_path = f'./reports/erban_analysis_{self.start_date}_{self.end_date}.md'

        summary = results['summary']
        promoted_features = results['promoted_features']
        failed_features = results['failed_features']

        lines = []

        # 标题
        lines.append("# 🏆 二板定龙头分析报告\n")
        lines.append(f"**分析时段**: {self.start_date} - {self.end_date}\n")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**分析样本**: {summary['total']} 只二板股票\n")

        # 概览
        lines.append("\n## 📊 核心指标概览\n")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|------|------|------|")
        lines.append(f"| 总二板数 | {summary['total']} | 分析期间出现的二板股票总数 |")
        lines.append(f"| 晋级数 | {summary['promoted']} | 成功晋级到三板及以上 |")
        lines.append(f"| **晋级率** | **{summary['promotion_rate']:.1f}%** | 二板→三板的成功率 |")
        lines.append(f"| 有效交易数 | {summary['valid_trade_count']} | 有T+2交易数据的样本 |")

        lines.append("\n### 胜率统计（T+1开盘买入）\n")
        lines.append("| 卖出方式 | 盈利数 | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|----------|--------|")
        lines.append(
            f"| T+2开盘卖 | {summary['win_by_open']} | **{summary['win_rate_by_open']:.1f}%** | {summary['avg_profit_open']:.2f}% | {summary['avg_loss_open']:.2f}% | {summary['pl_ratio_open']:.2f} |")
        lines.append(
            f"| T+2收盘卖 | {summary['win_by_close']} | **{summary['win_rate_by_close']:.1f}%** | {summary['avg_profit_close']:.2f}% | {summary['avg_loss_close']:.2f}% | {summary['pl_ratio_close']:.2f} |")

        lines.append("\n### 胜率统计（T日涨停价买入）\n")
        lines.append("| 卖出方式 | 盈利数 | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 |")
        lines.append("|----------|--------|------|----------|----------|--------|")
        lines.append(
            f"| T+1开盘卖 | {summary['win_by_day1_open']} | **{summary['win_rate_by_day1_open']:.1f}%** | {summary['avg_profit_day1_open']:.2f}% | {summary['avg_loss_day1_open']:.2f}% | {summary['pl_ratio_day1_open']:.2f} |")
        lines.append(
            f"| T+1收盘卖 | {summary['win_by_day1_close']} | **{summary['win_rate_by_day1_close']:.1f}%** | {summary['avg_profit_day1_close']:.2f}% | {summary['avg_loss_day1_close']:.2f}% | {summary['pl_ratio_day1_close']:.2f} |")

        # 晋级组 vs 淘汰组特征对比
        lines.append("\n## �� 晋级组 vs 淘汰组特征对比\n")
        lines.append("| 特征 | 晋级组均值 | 淘汰组均值 | 差异 | 解读 |")
        lines.append("|------|-----------|-----------|------|------|")

        feature_names = {
            'avg_volume_ratio': ('量比', '倍'),
            'avg_open_strength': ('二板开盘强度', '%'),
            'avg_erban_turnover': ('二板换手率', '%'),
            'avg_erban_amplitude': ('二板振幅', '%'),
            'avg_shouban_turnover': ('首板换手率', '%'),
            'avg_shouban_body_change': ('首板实体涨幅', '%'),
        }

        for key, (name, unit) in feature_names.items():
            promoted_val = promoted_features.get(key, 0)
            failed_val = failed_features.get(key, 0)
            diff = promoted_val - failed_val
            diff_str = f"+{diff:.2f}" if diff > 0 else f"{diff:.2f}"

            # 解读
            if abs(diff) < 0.5 and unit == '%':
                interpretation = "➖ 无明显差异"
            elif abs(diff) < 0.1 and unit == '倍':
                interpretation = "➖ 无明显差异"
            elif diff > 0:
                interpretation = "✅ 晋级组更高"
            else:
                interpretation = "⚠️ 淘汰组更高"

            lines.append(
                f"| {name} | {promoted_val:.2f}{unit} | {failed_val:.2f}{unit} | {diff_str}{unit} | {interpretation} |")

        # 量比分组分析
        if results.get('volume_ratio_groups'):
            lines.append("\n## 📈 量比分组分析\n")
            lines.append("分析二板当天相对首板的成交量变化与晋级率/胜率的关系：\n")
            lines.append("| 量比区间 | 数量 | 晋级率 | 胜率(开盘卖) | 胜率(收盘卖) |")
            lines.append("|----------|------|--------|-------------|-------------|")

            for group_name, data in results['volume_ratio_groups'].items():
                lines.append(
                    f"| {group_name} | {data['count']} | {data['promotion_rate']:.1f}% | {data['win_rate_open']:.1f}% | {data['win_rate_close']:.1f}% |")

        # 开盘强度分组分析
        if results.get('open_strength_groups'):
            lines.append("\n## 🚀 开盘强度分组分析\n")
            lines.append("分析二板当天开盘跳空幅度与晋级率/胜率的关系：\n")
            lines.append("| 开盘强度 | 数量 | 晋级率 | 胜率(开盘卖) | 胜率(收盘卖) |")
            lines.append("|----------|------|--------|-------------|-------------|")

            for group_name, data in results['open_strength_groups'].items():
                lines.append(
                    f"| {group_name} | {data['count']} | {data['promotion_rate']:.1f}% | {data['win_rate_open']:.1f}% | {data['win_rate_close']:.1f}% |")

        # 题材概念排名
        if results.get('concept_stats'):
            lines.append("\n## 🏷️ 题材概念统计（按晋级率排序）\n")

            # 按晋级率排序
            sorted_concepts = sorted(
                results['concept_stats'].values(),
                key=lambda x: (x.total_count, x.promotion_rate),  # 先按样本数，再按晋级率
                reverse=True
            )

            lines.append(
                "| 排名 | 题材概念 | 样本数 | 晋级率 | 胜率(开盘) | 胜率(收盘) | 盈亏比(开盘) | 盈亏比(收盘) |")
            lines.append(
                "|------|----------|--------|--------|------------|------------|--------------|--------------|")

            for i, stats in enumerate(sorted_concepts[:30], 1):
                lines.append(
                    f"| {i} | {stats.concept_name} | {stats.total_count} | {stats.promotion_rate:.1f}% | {stats.win_rate_by_open:.1f}% | {stats.win_rate_by_close:.1f}% | {stats.profit_loss_ratio_by_open:.2f} | {stats.profit_loss_ratio_by_close:.2f} |")

        # 每日统计
        if results.get('daily_stats'):
            lines.append("\n## 📅 每日统计\n")
            lines.append("| 日期 | 二板数 | 晋级率 | 胜率(开盘卖) | 胜率(收盘卖) |")
            lines.append("|------|--------|--------|-------------|-------------|")

            for date_str in sorted(results['daily_stats'].keys()):
                data = results['daily_stats'][date_str]
                total = data['total']
                promoted = data['promoted']
                valid = data['valid_trades']
                win_open = data['win_by_open']
                win_close = data['win_by_close']

                promotion_rate = promoted / total * 100 if total > 0 else 0
                win_rate_open = win_open / valid * 100 if valid > 0 else 0
                win_rate_close = win_close / valid * 100 if valid > 0 else 0

                # 格式化日期
                formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                lines.append(
                    f"| {formatted_date} | {total} | {promotion_rate:.1f}% | {win_rate_open:.1f}% | {win_rate_close:.1f}% |")

        # 分析结论
        lines.append("\n## 💡 分析结论\n")
        lines.append(self._generate_conclusions(results))

        # 写入文件
        content = '\n'.join(lines)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"\n✅ 报告已保存至: {os.path.abspath(output_path)}")
        return output_path

    def _generate_conclusions(self, results: Dict) -> str:
        """生成分析结论"""
        summary = results['summary']
        promoted_features = results['promoted_features']
        failed_features = results['failed_features']

        conclusions = []

        # 晋级率评价
        promotion_rate = summary['promotion_rate']
        if promotion_rate >= 40:
            conclusions.append(f"1. **市场环境偏强**: 晋级率 {promotion_rate:.1f}% 较高，二板晋级概率较大，可以适度积极。")
        elif promotion_rate >= 25:
            conclusions.append(f"1. **市场环境中性**: 晋级率 {promotion_rate:.1f}% 处于正常水平，需精选个股。")
        else:
            conclusions.append(f"1. **市场环境偏弱**: 晋级率 {promotion_rate:.1f}% 较低，二板追高风险大，建议谨慎。")

        # 胜率评价
        win_rate_open = summary['win_rate_by_open']
        win_rate_close = summary['win_rate_by_close']
        pl_ratio_open = summary['pl_ratio_open']
        pl_ratio_close = summary['pl_ratio_close']

        conclusions.append(
            f"2. **交易胜率**: T+1开盘买入后，T+2开盘卖胜率 {win_rate_open:.1f}%（盈亏比 {pl_ratio_open:.2f}），T+2收盘卖胜率 {win_rate_close:.1f}%（盈亏比 {pl_ratio_close:.2f}）。")

        # 量比特征
        vol_diff = promoted_features['avg_volume_ratio'] - failed_features['avg_volume_ratio']
        if vol_diff > 0.2:
            conclusions.append(
                f"3. **量能特征**: 晋级组量比更高（{promoted_features['avg_volume_ratio']:.2f} vs {failed_features['avg_volume_ratio']:.2f}），放量二板更易晋级。")
        elif vol_diff < -0.2:
            conclusions.append(f"3. **量能特征**: 淘汰组量比更高，说明过度放量可能是出货信号，需警惕。")
        else:
            conclusions.append(f"3. **量能特征**: 量比差异不明显，成交量不是本阶段的核心判断指标。")

        # 开盘强度
        open_diff = promoted_features['avg_open_strength'] - failed_features['avg_open_strength']
        if open_diff > 1:
            conclusions.append(f"4. **开盘形态**: 晋级组开盘更强势，高开强势股更易晋级，可关注竞价强度。")
        elif open_diff < -1:
            conclusions.append(f"4. **开盘形态**: 淘汰组开盘更强势，一字或高开反而不利于晋级，可能是主力出货。")
        else:
            conclusions.append(f"4. **开盘形态**: 开盘强度差异不大，需结合其他因素判断。")

        # 首板实体涨幅
        body_diff = promoted_features['avg_shouban_body_change'] - failed_features['avg_shouban_body_change']
        if body_diff > 1:
            conclusions.append(
                f"5. **首板形态**: 晋级组首板实体涨幅更大（{promoted_features['avg_shouban_body_change']:.2f}% vs {failed_features['avg_shouban_body_change']:.2f}%），首板强势封板的二板更易晋级。")
        elif body_diff < -1:
            conclusions.append(f"5. **首板形态**: 淘汰组首板实体涨幅更大，首板冲高回落后的二板需谨慎。")
        else:
            conclusions.append(f"5. **首板形态**: 首板实体涨幅差异不大。")

        # 涨停价买入策略胜率
        zt_win_rate_open = summary['win_rate_by_day1_open']
        zt_win_rate_close = summary['win_rate_by_day1_close']
        zt_pl_ratio_open = summary['pl_ratio_day1_open']
        zt_pl_ratio_close = summary['pl_ratio_day1_close']

        conclusions.append(
            f"6. **涨停价买入策略**: T日涨停价买入后，T+1开盘卖胜率 {zt_win_rate_open:.1f}%（盈亏比 {zt_pl_ratio_open:.2f}），T+1收盘卖胜率 {zt_win_rate_close:.1f}%（盈亏比 {zt_pl_ratio_close:.2f}）。")

        # 题材建议
        if results.get('concept_stats'):
            hot_concepts = sorted(
                results['concept_stats'].values(),
                key=lambda x: x.promotion_rate,
                reverse=True
            )[:5]

            if hot_concepts:
                concept_names = [c.concept_name for c in hot_concepts if c.promotion_rate > 30]
                if concept_names:
                    conclusions.append(
                        f"7. **热门题材**: 晋级率较高的题材包括「{', '.join(concept_names[:5])}」，可重点关注这些方向的二板股。")

        return '\n\n'.join(conclusions)


def analyze_erban_longtou(start_date: str, end_date: str = None,
                          output_path: str = None,
                          min_concept_samples: int = 2) -> str:
    """
    分析二板定龙头
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)，默认为当前日期
        output_path: 输出报告路径，默认自动生成
        min_concept_samples: 题材统计最小样本数，默认2
        
    Returns:
        报告文件路径
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    analyzer = ErbanLongtouAnalyzer()
    results = analyzer.analyze(start_date, end_date, min_concept_samples)

    if results:
        return analyzer.generate_report(results, output_path)

    return ""
