"""
形态分析器基类

提供通用的形态分析框架，包括：
- K线图绘制（支持同一股票多个信号合并到一张图）
- CSV报告生成
- 数据加载和处理

子类需实现特定的股票筛选逻辑和标记生成逻辑。

作者：AI Assistant
版本：v1.1
日期：2025-12-23
"""

import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from tqdm import tqdm

from utils.backtrade.visualizer import read_stock_data, _setup_mpf_style
from utils.date_util import (
    get_n_trading_days_before,
    get_next_trading_day,
    get_current_or_prev_trading_day
)


@dataclass
class PatternInfo:
    """
    通用形态信息数据类
    
    Attributes:
        code: 股票代码（如 300502.SZ）
        name: 股票简称
        pattern_date: 主形态日期（YYYYMMDD），用于单信号场景
        pattern_dates: 所有形态日期列表，用于多信号合并场景
        pattern_type: 形态类型描述
        extra_data: 额外数据字典，用于存储形态特有的信息
    """
    code: str
    name: str
    pattern_date: str  # 主形态日期（首个或唯一）
    pattern_type: str  # 形态类型描述
    pattern_dates: List[str] = field(default_factory=list)  # 所有形态日期
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理：确保 pattern_dates 包含 pattern_date"""
        if not self.pattern_dates:
            self.pattern_dates = [self.pattern_date]
        elif self.pattern_date not in self.pattern_dates:
            self.pattern_dates.insert(0, self.pattern_date)


@dataclass
class PatternAnalysisConfig:
    """
    形态分析配置基类
    
    Attributes:
        start_date: 开始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD（可为None，自动取最近交易日）
        before_days: 形态日期前显示的交易日数
        after_days: 形态日期后显示的交易日数
        data_dir: 股票数据目录
        output_dir: 输出目录
        fupan_file: 复盘数据文件路径
    """
    start_date: str
    end_date: Optional[str] = None
    before_days: int = 30
    after_days: int = 10
    data_dir: str = './data/astocks'
    output_dir: str = './analysis/pattern_charts'
    fupan_file: str = './excel/fupan_stocks.xlsx'

    def __post_init__(self):
        """初始化后处理：如果 end_date 为 None，自动设为最近交易日"""
        if self.end_date is None:
            today_str = datetime.now().strftime('%Y%m%d')
            self.end_date = get_current_or_prev_trading_day(today_str)
            logging.info(f"end_date 未指定，自动设为最近交易日: {self.end_date}")


class PatternAnalyzerBase(ABC):
    """
    形态分析器基类
    
    提供通用的分析流程框架，子类需实现：
    - load_data(): 加载数据
    - filter_stocks(): 筛选符合条件的股票
    - get_chart_markers(): 获取图表标记配置
    - get_chart_title(): 获取图表标题
    - get_summary_columns(): 获取汇总报告列定义
    - build_summary_row(): 构建汇总报告行数据
    """

    def __init__(self, config: PatternAnalysisConfig, pattern_name: str):
        """
        初始化分析器
        
        Args:
            config: 分析配置
            pattern_name: 形态名称（用于日志和输出目录）
        """
        self.config = config
        self.pattern_name = pattern_name
        self.filtered_stocks: List[PatternInfo] = []

        # 构建输出目录路径
        date_range = f"{config.start_date}_{config.end_date}"
        self.output_dir = os.path.join(config.output_dir, pattern_name, date_range)

        # 清空已有目录（避免新旧数据混杂）
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
            logging.info(f"已清空旧目录: {self.output_dir}")

        # 重新创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)

        logging.info(f"{pattern_name}分析器初始化完成，输出目录: {self.output_dir}")

    @abstractmethod
    def load_data(self):
        """加载分析所需的数据（由子类实现）"""
        pass

    @abstractmethod
    def filter_stocks(self):
        """筛选符合条件的股票（由子类实现）"""
        pass

    @abstractmethod
    def get_chart_markers(self, pattern_info: PatternInfo, chart_df: pd.DataFrame) -> List:
        """
        获取图表标记配置（由子类实现）
        
        Args:
            pattern_info: 形态信息（包含所有信号日期）
            chart_df: K线数据
            
        Returns:
            mpf.make_addplot 对象列表
        """
        pass

    @abstractmethod
    def get_chart_title(self, pattern_info: PatternInfo) -> str:
        """
        获取图表标题（由子类实现）
        
        Args:
            pattern_info: 形态信息
            
        Returns:
            图表标题字符串
        """
        pass

    @abstractmethod
    def get_summary_columns(self) -> List[str]:
        """
        获取汇总报告的列名列表（由子类实现）
        
        Returns:
            列名列表
        """
        pass

    @abstractmethod
    def build_summary_row(self, pattern_info: PatternInfo) -> Dict[str, Any]:
        """
        构建汇总报告的单行数据（由子类实现）
        
        Args:
            pattern_info: 形态信息
            
        Returns:
            包含列名和值的字典
        """
        pass

    def _extract_stock_code(self, full_code: str) -> str:
        """
        从完整代码中提取6位数字代码
        
        Args:
            full_code: 如 "300502.SZ"
            
        Returns:
            6位代码，如 "300502"
        """
        if '.' in full_code:
            return full_code.split('.')[0]
        return full_code

    def _format_stock_header(self, pattern_info: PatternInfo) -> str:
        """
        生成带涨停原因的股票标题头（供子类 get_chart_title 使用）
        
        格式：{6位代码} {股票名} 【{涨停原因}】
        
        Args:
            pattern_info: 形态信息
            
        Returns:
            格式化的标题头字符串
        """
        code_6digit = self._extract_stock_code(pattern_info.code)
        reason = pattern_info.extra_data.get('reason', '')

        if reason:
            return f"{code_6digit} {pattern_info.name} 【{reason}】"
        else:
            return f"{code_6digit} {pattern_info.name}"

    def merge_patterns_by_stock(self):
        """
        合并同一股票在日期范围内重叠的信号
        
        如果同一股票的多个信号在 before_days + after_days 范围内重叠，
        则合并为一个 PatternInfo，在同一张图上标记所有信号点。
        """
        if not self.filtered_stocks:
            return

        # 按股票代码分组
        stock_patterns: Dict[str, List[PatternInfo]] = {}
        for pattern in self.filtered_stocks:
            code = pattern.code
            if code not in stock_patterns:
                stock_patterns[code] = []
            stock_patterns[code].append(pattern)

        merged_stocks = []
        total_range = self.config.before_days + self.config.after_days

        for code, patterns in stock_patterns.items():
            if len(patterns) == 1:
                # 只有一个信号，无需合并
                merged_stocks.append(patterns[0])
                continue

            # 按日期排序
            patterns.sort(key=lambda p: p.pattern_date)

            # 合并重叠的信号
            merged_groups = []
            current_group = [patterns[0]]

            for i in range(1, len(patterns)):
                current_pattern = patterns[i]
                last_pattern = current_group[-1]

                # 计算两个信号之间的天数差
                try:
                    last_date = datetime.strptime(last_pattern.pattern_date, '%Y%m%d')
                    curr_date = datetime.strptime(current_pattern.pattern_date, '%Y%m%d')
                    days_diff = (curr_date - last_date).days

                    # 如果两个信号在 total_range 天内，认为重叠，合并
                    if days_diff <= total_range:
                        current_group.append(current_pattern)
                    else:
                        # 不重叠，开始新组
                        merged_groups.append(current_group)
                        current_group = [current_pattern]
                except:
                    # 解析失败，作为新组
                    merged_groups.append(current_group)
                    current_group = [current_pattern]

            # 添加最后一组
            merged_groups.append(current_group)

            # 将每组合并为单个 PatternInfo
            for group in merged_groups:
                if len(group) == 1:
                    merged_stocks.append(group[0])
                else:
                    # 合并多个信号
                    all_dates = [p.pattern_date for p in group]
                    # 合并 extra_data（保留所有信号的数据）
                    merged_extra = {
                        'signal_count': len(group),
                        'all_signals': [p.extra_data for p in group]
                    }
                    # 保留第一个信号的主要信息
                    merged_extra.update(group[0].extra_data)

                    merged_pattern = PatternInfo(
                        code=code,
                        name=group[0].name,
                        pattern_date=all_dates[0],  # 首个日期作为主日期
                        pattern_dates=all_dates,
                        pattern_type=group[0].pattern_type,
                        extra_data=merged_extra
                    )
                    merged_stocks.append(merged_pattern)

        original_count = len(self.filtered_stocks)
        self.filtered_stocks = merged_stocks
        merged_count = len(self.filtered_stocks)

        if original_count != merged_count:
            logging.info(f"合并重叠信号: {original_count} -> {merged_count} 个图表")

    def _calculate_chart_range(self, pattern_info: PatternInfo) -> tuple:
        """
        计算图表的日期范围
        
        Args:
            pattern_info: 形态信息
            
        Returns:
            (chart_start_str, chart_end_str) 元组
        """
        # 获取所有信号日期
        all_dates = pattern_info.pattern_dates
        first_date = min(all_dates)
        last_date = max(all_dates)

        # 首个信号前 before_days 个交易日
        chart_start = get_n_trading_days_before(first_date, self.config.before_days)

        # 最后一个信号后 after_days 个交易日
        chart_end_str = last_date
        for _ in range(self.config.after_days):
            next_day = get_next_trading_day(chart_end_str)
            if next_day:
                chart_end_str = next_day
            else:
                break

        return chart_start, chart_end_str

    def analyze_single_stock(self, pattern_info: PatternInfo):
        """
        分析单只股票并生成K线图
        
        Args:
            pattern_info: 形态信息（可能包含多个信号日期）
        """
        try:
            code_6digit = self._extract_stock_code(pattern_info.code)

            # 计算绘图范围（考虑多个信号日期）
            chart_start, chart_end_str = self._calculate_chart_range(pattern_info)

            # 读取股票数据
            stock_data = read_stock_data(code_6digit, self.config.data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {code_6digit} {pattern_info.name} 的数据文件")
                return

            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')

            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {pattern_info.name} 在指定日期范围内无数据")
                return

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {pattern_info.name} 清理停牌数据后无有效数据")
                return

            # 生成K线图
            self._plot_stock_chart(pattern_info, chart_df, code_6digit)

        except Exception as e:
            logging.error(f"分析股票 {pattern_info.code} {pattern_info.name} 失败: {e}")
            import traceback
            logging.error(traceback.format_exc())

    def _plot_stock_chart(self, pattern_info: PatternInfo, chart_df: pd.DataFrame, code_6digit: str):
        """
        绘制K线图
        
        Args:
            pattern_info: 形态信息
            chart_df: K线数据
            code_6digit: 6位股票代码
        """
        # 获取子类定义的标记
        addplots = self.get_chart_markers(pattern_info, chart_df)

        # 获取子类定义的标题
        title = self.get_chart_title(pattern_info)

        # 文件名：日期在前便于排序，多信号只保留首日期
        filename = f"{pattern_info.pattern_date}_{pattern_info.name}.png"
        output_path = os.path.join(self.output_dir, filename)

        # 设置样式
        style = _setup_mpf_style()

        # 绘制图表
        fig, axes = mpf.plot(
            chart_df,
            type='candle',
            style=style,
            ylabel='价格',
            volume=True,
            ylabel_lower='成交量',
            addplot=addplots if addplots else None,
            figsize=(16, 9),
            returnfig=True,
            tight_layout=True
        )

        axes[0].set_title(title, loc='left', fontweight='bold', fontsize=11)
        if addplots:
            axes[0].legend(loc='upper left', fontsize=10)

        # 调整y轴范围，确保标记完全显示
        y_min, y_max = axes[0].get_ylim()
        y_range = y_max - y_min
        axes[0].set_ylim(y_min - y_range * 0.05, y_max + y_range * 0.05)

        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        logging.debug(f"已生成图表: {filename}")

    def get_sort_date_column(self) -> str:
        """
        获取用于排序的日期列名（子类可重写）
        
        Returns:
            日期列名，默认为 '形态日期'
        """
        return '形态日期'

    def get_simple_summary_columns(self) -> List[str]:
        """
        获取简要报告需要的列名（子类可重写）
        
        Returns:
            列名列表，默认为 ['股票代码', '股票名称', '涨停原因', '信号日']
        """
        return ['股票代码', '股票名称', '涨停原因', '信号日']

    def build_simple_summary_row(self, pattern_info: PatternInfo) -> Dict[str, Any]:
        """
        构建简要报告的单行数据（子类可重写）
        
        Args:
            pattern_info: 形态信息
            
        Returns:
            单行数据字典
        """
        # 获取信号日期并格式化为 yyyy年mm月dd日
        pattern_date = pattern_info.pattern_date
        formatted_date = f"{pattern_date[:4]}年{pattern_date[4:6]}月{pattern_date[6:8]}日"

        return {
            '股票代码': self._extract_stock_code(pattern_info.code),
            '股票名称': pattern_info.name,
            '涨停原因': pattern_info.extra_data.get('reason', ''),
            '信号日': formatted_date
        }

    def generate_summary_report(self) -> str:
        """
        生成汇总报告CSV
        
        - 自动移除"图表路径"列
        - 按日期倒序排序
        
        Returns:
            报告文件路径
        """
        columns = self.get_summary_columns()
        # 移除"图表路径"列
        columns = [c for c in columns if c != '图表路径']

        summary_data = []

        for pattern_info in self.filtered_stocks:
            row = self.build_summary_row(pattern_info)
            # 移除"图表路径"字段
            row.pop('图表路径', None)
            summary_data.append(row)

        summary_df = pd.DataFrame(summary_data, columns=columns)

        # 按日期列倒序排序
        sort_col = self.get_sort_date_column()
        if sort_col in summary_df.columns:
            summary_df = summary_df.sort_values(by=sort_col, ascending=False)

        summary_path = os.path.join(self.output_dir, 'summary.csv')
        summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')

        logging.info(f"汇总报告已生成: {summary_path}")
        return summary_path

    def generate_simple_summary(self) -> str:
        """
        生成简要汇总报告TXT
        
        格式：按日期分组，每行一只股票（代码 名称），不同日期用分隔线区分
        按信号日倒序，方便复制使用
        
        Returns:
            报告文件路径
        """
        simple_data = []

        for pattern_info in self.filtered_stocks:
            row = self.build_simple_summary_row(pattern_info)
            simple_data.append(row)

        columns = self.get_simple_summary_columns()
        simple_df = pd.DataFrame(simple_data, columns=columns)

        # 按信号日倒序
        if '信号日' in simple_df.columns:
            simple_df = simple_df.sort_values(by='信号日', ascending=False)

        # 生成 TXT 文件，按日期分组
        simple_path = os.path.join(self.output_dir, 'summary_simple.txt')

        with open(simple_path, 'w', encoding='utf-8') as f:
            current_date = None
            first_group = True

            for _, row in simple_df.iterrows():
                signal_date = row.get('信号日', '')
                # 将 yyyy年mm月dd日 转为 yyyy-mm-dd
                if '年' in signal_date:
                    date_formatted = signal_date.replace('年', '-').replace('月', '-').replace('日', '')
                else:
                    date_formatted = signal_date

                # 日期变化时写入分隔符和新日期
                if date_formatted != current_date:
                    if not first_group:
                        f.write('=' * 50 + '\n')
                    f.write(f"{date_formatted}\n")
                    current_date = date_formatted
                    first_group = False

                # 写入股票信息：代码 名称
                code = row.get('股票代码', '')
                name = row.get('股票名称', '')
                f.write(f"{code} {name}\n")

        logging.info(f"简要报告已生成: {simple_path}")
        return simple_path

    def run(self):
        """执行完整分析流程"""
        logging.info("=" * 60)
        logging.info(f"开始{self.pattern_name}分析")
        logging.info(f"日期范围: {self.config.start_date} - {self.config.end_date}")
        logging.info("=" * 60)

        # Phase 1: 加载数据
        self.load_data()

        # Phase 2: 筛选股票
        self.filter_stocks()

        if not self.filtered_stocks:
            logging.warning("未找到符合条件的股票！")
            return

        # Phase 3: 合并同一股票的重叠信号
        self.merge_patterns_by_stock()

        # Phase 4: 批量生成图表
        logging.info(f"开始生成 {len(self.filtered_stocks)} 只股票的K线图...")
        for pattern_info in tqdm(self.filtered_stocks, desc="生成图表"):
            self.analyze_single_stock(pattern_info)

        # Phase 5: 生成汇总报告
        summary_path = self.generate_summary_report()

        # Phase 6: 生成简要报告
        simple_path = self.generate_simple_summary()

        logging.info("=" * 60)
        logging.info(f"{self.pattern_name}分析完成！")
        logging.info(f"共分析 {len(self.filtered_stocks)} 只股票")
        logging.info(f"图表保存在: {self.output_dir}")
        logging.info(f"汇总报告: {summary_path}")
        logging.info(f"简要报告: {simple_path}")
        logging.info("=" * 60)
