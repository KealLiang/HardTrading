"""
连板股形态分析器（基于通用基类）

功能：分析指定时间段内的连板股票，生成K线图便于找出共性特征

支持的连板类型：
- 1: 连续板（无断板）- 连续涨停天数 >= min_lianban
- 2: 最高板 - 最高板数 >= min_lianban（可以有断板）
- 3: 非连续板 - 最高板数 >= min_lianban 且有断板

作者：AI Assistant
版本：v2.0（基于 PatternAnalyzerBase 重构）
日期：2025-12-23
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Any

import mplfinance as mpf
import pandas as pd
from tqdm import tqdm

from analysis.pattern_analyzer_base import (
    PatternAnalyzerBase, PatternAnalysisConfig, PatternInfo
)
from utils.date_util import get_trading_days, get_next_trading_day


@dataclass
class LianbanPatternConfig(PatternAnalysisConfig):
    """
    连板分析配置
    
    Attributes:
        min_lianban_count: 最小连板数，默认3
        lianban_type: 连板类型
            - 1: 连续板（无断板）
            - 2: 最高板（可以有断板）
            - 3: 非连续板（有断板）
        end_threshold_days: 判断连板终止的阈值天数，默认7
    """
    min_lianban_count: int = 3
    lianban_type: int = 1
    end_threshold_days: int = 7


class LianbanPatternAnalyzer(PatternAnalyzerBase):
    """
    连板股形态分析器
    
    筛选逻辑：
    1. 从复盘数据中筛选指定时间段内的连板股
    2. 根据 lianban_type 应用不同的筛选条件
    3. 为每只股票生成K线图，标记首板和终止日期
    """

    def __init__(self, config: LianbanPatternConfig):
        """
        初始化分析器
        
        Args:
            config: 连板分析配置
        """
        # 根据连板类型设置形态名称
        type_names = {
            1: "连续板分析",
            2: "最高板分析",
            3: "非连续板分析"
        }
        pattern_name = type_names.get(config.lianban_type, "连板分析")

        super().__init__(config, pattern_name)
        self.config: LianbanPatternConfig = config
        self.lianban_data = None
        self.shouban_data = None
        self.date_columns = []

    def load_data(self):
        """加载连板数据和首板数据"""
        logging.info(f"正在加载连板数据: {self.config.fupan_file}")

        try:
            # 读取连板数据
            self.lianban_data = pd.read_excel(
                self.config.fupan_file,
                sheet_name="连板数据",
                index_col=0
            )

            # 读取首板数据
            self.shouban_data = pd.read_excel(
                self.config.fupan_file,
                sheet_name="首板数据",
                index_col=0
            )

            logging.info(f"连板数据加载成功，共 {len(self.lianban_data)} 行")
            logging.info(f"首板数据加载成功，共 {len(self.shouban_data)} 行")

            # 提取并过滤日期列
            self._filter_date_columns()

        except FileNotFoundError:
            raise FileNotFoundError(f"未找到复盘数据文件: {self.config.fupan_file}")
        except Exception as e:
            raise Exception(f"加载连板数据失败: {e}")

    def _filter_date_columns(self):
        """过滤出指定日期范围内的列"""
        all_columns = self.lianban_data.columns.tolist()

        start_dt = datetime.strptime(self.config.start_date, '%Y%m%d')
        end_dt = datetime.strptime(self.config.end_date, '%Y%m%d')

        self.date_columns = []
        for col in all_columns:
            try:
                col_date = self._parse_column_date(col)
                if start_dt <= col_date <= end_dt:
                    self.date_columns.append(col)
            except:
                continue

        self.date_columns.sort(key=lambda x: self._parse_column_date(x))
        logging.info(f"筛选出 {len(self.date_columns)} 个日期列")

    def _parse_column_date(self, column_date: str) -> datetime:
        """将Excel列名日期转为datetime"""
        match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', column_date)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return datetime(year, month, day)
        else:
            raise ValueError(f"无法解析日期列: {column_date}")

    def _format_to_column_date(self, dt: datetime) -> str:
        """将datetime转为Excel列名格式"""
        return dt.strftime('%Y年%m月%d日')

    def _parse_lianban_cell(self, cell_value: str) -> Optional[Dict]:
        """解析连板数据单元格"""
        if pd.isna(cell_value) or not cell_value:
            return None

        try:
            parts = [p.strip() for p in str(cell_value).split(';')]
            if len(parts) < 10:
                return None

            return {
                'code': parts[0],
                'name': parts[1],
                'kai_ban': parts[2],
                'final_zt_time': parts[3],
                'jitian_jiban': parts[4],
                'price': parts[5],
                'first_zt_time': parts[6],
                'pct_chg': parts[7],
                'continuous_days': int(parts[8]) if parts[8] and parts[8].isdigit() else 0,
                'reason': parts[9]
            }
        except Exception as e:
            logging.warning(f"解析单元格失败: {cell_value}, 错误: {e}")
            return None

    def _extract_board_count(self, jitian_jiban: str) -> int:
        """从"几天几板"中提取板数"""
        if not jitian_jiban:
            return 0

        match = re.search(r'(\d+)天(\d+)板', str(jitian_jiban))
        if match:
            return int(match.group(2))

        return 0

    def _split_lianban_periods(self, code: str, date_records: Dict) -> List[Dict]:
        """
        将股票的连板日期分割成多个独立的连板周期
        
        判断标准：如果两个连板日期之间间隔超过5个交易日，则认为是不同周期
        """
        sorted_dates = sorted(date_records.keys(), key=lambda x: self._parse_column_date(x))

        if not sorted_dates:
            return []

        periods = []
        current_period = {}
        prev_date_str = None

        for date_col in sorted_dates:
            current_date_dt = self._parse_column_date(date_col)
            current_date_str = current_date_dt.strftime('%Y%m%d')

            if prev_date_str is None:
                current_period[date_col] = date_records[date_col]
                prev_date_str = current_date_str
            else:
                try:
                    trading_days = get_trading_days(prev_date_str, current_date_str)
                    gap = len(trading_days) - 1

                    if gap > 5:
                        if current_period:
                            periods.append(current_period)
                        current_period = {date_col: date_records[date_col]}
                    else:
                        current_period[date_col] = date_records[date_col]

                    prev_date_str = current_date_str
                except:
                    current_period[date_col] = date_records[date_col]
                    prev_date_str = current_date_str

        if current_period:
            periods.append(current_period)

        return periods

    def _meets_criteria(self, code: str, date_records: Dict) -> bool:
        """判断股票是否符合筛选条件"""
        max_board = 0
        max_continuous = 0

        for date_col, parsed in date_records.items():
            board_count = self._extract_board_count(parsed['jitian_jiban'])
            continuous_days = parsed['continuous_days']

            max_board = max(max_board, board_count)
            max_continuous = max(max_continuous, continuous_days)

        if self.config.lianban_type == 1:
            # 类型1: 连续板（无断板）
            return max_continuous >= self.config.min_lianban_count

        elif self.config.lianban_type == 2:
            # 类型2: 最高板
            return max_board >= self.config.min_lianban_count

        elif self.config.lianban_type == 3:
            # 类型3: 非连续板（有断板）
            has_enough_boards = max_board >= self.config.min_lianban_count
            has_break = max_board != max_continuous
            return has_enough_boards and has_break

        return False

    def _find_first_board_date(self, code: str, period_start_date: str) -> Optional[str]:
        """从首板数据中查找该连板周期对应的首板日期"""
        all_shouban_cols = self.shouban_data.columns.tolist()
        period_start_dt = datetime.strptime(period_start_date, '%Y%m%d')
        found_dates = []

        for date_col in all_shouban_cols:
            try:
                date_dt = self._parse_column_date(date_col)
            except:
                continue

            if date_dt <= period_start_dt:
                for idx, cell_value in self.shouban_data[date_col].items():
                    parsed = self._parse_lianban_cell(cell_value)
                    if parsed and parsed['code'] == code:
                        found_dates.append(date_dt.strftime('%Y%m%d'))
                        break

        if not found_dates:
            return None

        found_dates.sort(reverse=True)
        return found_dates[0]

    def _find_end_date(self, code: str, date_records: Dict) -> str:
        """查找连板终止日期"""
        sorted_dates = sorted(date_records.keys(),
                              key=lambda x: self._parse_column_date(x),
                              reverse=True)

        last_date_col = sorted_dates[0]
        last_date_dt = self._parse_column_date(last_date_col)

        try:
            current_check_date = last_date_dt.strftime('%Y%m%d')
            for _ in range(self.config.end_threshold_days):
                next_date = get_next_trading_day(current_check_date)
                if not next_date:
                    break

                next_col = self._format_to_column_date(
                    datetime.strptime(next_date, '%Y%m%d')
                )

                if next_col in date_records:
                    last_date_dt = self._parse_column_date(next_col)
                    current_check_date = next_date
                else:
                    current_check_date = next_date
        except:
            pass

        return last_date_dt.strftime('%Y%m%d')

    def _build_pattern_info(self, code: str, date_records: Dict) -> Optional[PatternInfo]:
        """构建形态信息对象"""
        try:
            first_record = list(date_records.values())[0]
            stock_name = first_record['name']

            # 获取周期开始日期
            sorted_dates = sorted(date_records.keys(), key=lambda x: self._parse_column_date(x))
            period_start_col = sorted_dates[0]
            period_start_dt = self._parse_column_date(period_start_col)
            period_start_date = period_start_dt.strftime('%Y%m%d')

            # 获取首板日期
            first_board_date = self._find_first_board_date(code, period_start_date)
            if not first_board_date:
                logging.warning(f"股票 {code} {stock_name} 未找到首板日期，跳过")
                return None

            # 获取终止日期
            end_date = self._find_end_date(code, date_records)

            # 计算最高板数和最大连续天数
            max_board = 0
            max_continuous = 0
            all_dates = []

            for date_col, parsed in date_records.items():
                board_count = self._extract_board_count(parsed['jitian_jiban'])
                continuous_days = parsed['continuous_days']

                max_board = max(max_board, board_count)
                max_continuous = max(max_continuous, continuous_days)

                date_dt = self._parse_column_date(date_col)
                all_dates.append(date_dt.strftime('%Y%m%d'))

            # 确定连板类型描述
            if max_board == max_continuous:
                board_type = f"连续{max_board}板"
            else:
                board_type = f"最高{max_board}板（有断板）"

            return PatternInfo(
                code=code,
                name=stock_name,
                pattern_date=first_board_date,  # 以首板日期为主日期
                pattern_dates=[first_board_date, end_date],  # 首板和终止日期
                pattern_type=board_type,
                extra_data={
                    'first_board_date': first_board_date,
                    'end_date': end_date,
                    'max_board_count': max_board,
                    'continuous_days': max_continuous,
                    'board_type': board_type,
                    'all_lianban_dates': sorted(all_dates)
                }
            )

        except Exception as e:
            logging.error(f"构建股票信息失败: {code}, 错误: {e}")
            return None

    def filter_stocks(self):
        """根据条件筛选股票"""
        logging.info("开始筛选股票...")
        logging.info(f"连板类型: {self.config.lianban_type}, 最小连板数: {self.config.min_lianban_count}")

        # 收集所有股票代码及其在各日期的数据
        stock_records = {}

        for date_col in self.date_columns:
            for idx, cell_value in self.lianban_data[date_col].items():
                parsed = self._parse_lianban_cell(cell_value)
                if not parsed:
                    continue

                code = parsed['code']
                if code not in stock_records:
                    stock_records[code] = {}
                stock_records[code][date_col] = parsed

        logging.info(f"共找到 {len(stock_records)} 只不同的股票")

        # 对每只股票，先分组为多个连板周期，再应用筛选条件
        for code, date_records in tqdm(stock_records.items(), desc="筛选股票"):
            lianban_periods = self._split_lianban_periods(code, date_records)

            for period_records in lianban_periods:
                if self._meets_criteria(code, period_records):
                    pattern_info = self._build_pattern_info(code, period_records)
                    if pattern_info:
                        self.filtered_stocks.append(pattern_info)

        logging.info(f"筛选完成，符合条件的股票: {len(self.filtered_stocks)} 只")

    def merge_patterns_by_stock(self):
        """
        重写合并逻辑：连板分析不合并，每个周期单独一张图
        """
        # 连板分析的每个周期是独立的，不需要合并
        pass

    def get_chart_markers(self, pattern_info: PatternInfo, chart_df: pd.DataFrame) -> List:
        """获取图表标记配置"""
        addplots = []
        extra = pattern_info.extra_data

        # 首板标记（绿色向上三角）
        first_board_markers = [float('nan')] * len(chart_df)
        first_date_str = extra.get('first_board_date', pattern_info.pattern_date)
        first_date_dt = datetime.strptime(first_date_str, '%Y%m%d')

        try:
            first_idx = chart_df.index.searchsorted(first_date_dt, side='right') - 1
            if 0 <= first_idx < len(chart_df):
                first_board_markers[first_idx] = chart_df.iloc[first_idx]['Low'] * 0.97
        except:
            pass

        addplots.append(mpf.make_addplot(
            first_board_markers,
            type='scatter',
            marker='^',
            color='lime',
            markersize=120,
            label='首板'
        ))

        # 终止标记（红色向下三角）
        end_markers = [float('nan')] * len(chart_df)
        end_date_str = extra.get('end_date', pattern_info.pattern_dates[-1] if len(
            pattern_info.pattern_dates) > 1 else pattern_info.pattern_date)
        end_date_dt = datetime.strptime(end_date_str, '%Y%m%d')

        try:
            end_idx = chart_df.index.searchsorted(end_date_dt, side='right') - 1
            if 0 <= end_idx < len(chart_df):
                end_markers[end_idx] = chart_df.iloc[end_idx]['High'] * 1.03
        except:
            pass

        addplots.append(mpf.make_addplot(
            end_markers,
            type='scatter',
            marker='v',
            color='magenta',
            markersize=120,
            label='终止'
        ))

        return addplots

    def get_chart_title(self, pattern_info: PatternInfo) -> str:
        """获取图表标题"""
        extra = pattern_info.extra_data
        code_6digit = self._extract_stock_code(pattern_info.code)

        title = (
            f"{code_6digit} {pattern_info.name} - 连板分析\n"
            f"首板: {extra.get('first_board_date', 'N/A')} | "
            f"终止: {extra.get('end_date', 'N/A')} | "
            f"最高: {extra.get('max_board_count', 'N/A')}板 | "
            f"连续: {extra.get('continuous_days', 'N/A')}天 | "
            f"类型: {extra.get('board_type', 'N/A')}"
        )
        return title

    def get_summary_columns(self) -> List[str]:
        """获取汇总报告的列名列表"""
        return [
            '股票代码', '股票名称', '首板日期', '终止日期',
            '最高板数', '连续天数', '连板类型', '图表路径'
        ]

    def build_summary_row(self, pattern_info: PatternInfo) -> Dict[str, Any]:
        """构建汇总报告的单行数据"""
        extra = pattern_info.extra_data
        first_date = extra.get('first_board_date', pattern_info.pattern_date)
        end_date = extra.get('end_date', '')
        # 文件名：日期在前便于排序
        filename = f"{first_date}_{pattern_info.name}.png"

        return {
            '股票代码': pattern_info.code,
            '股票名称': pattern_info.name,
            '首板日期': first_date,
            '终止日期': end_date,
            '最高板数': extra.get('max_board_count', ''),
            '连续天数': extra.get('continuous_days', ''),
            '连板类型': extra.get('board_type', ''),
            '图表路径': f"./{filename}"
        }

    def _calculate_chart_range(self, pattern_info: PatternInfo) -> tuple:
        """
        重写计算图表范围：使用首板和终止日期
        """
        from utils.date_util import get_n_trading_days_before, get_next_trading_day

        extra = pattern_info.extra_data
        first_board_date = extra.get('first_board_date', pattern_info.pattern_date)
        end_date = extra.get('end_date', first_board_date)

        # 首板前 before_days 个交易日
        chart_start = get_n_trading_days_before(first_board_date, self.config.before_days)

        # 终止后 after_days 个交易日
        chart_end_str = end_date
        for _ in range(self.config.after_days):
            next_day = get_next_trading_day(chart_end_str)
            if next_day:
                chart_end_str = next_day
            else:
                break

        return chart_start, chart_end_str


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    config = LianbanPatternConfig(
        start_date='20250901',
        end_date='20251027',
        min_lianban_count=3,
        lianban_type=1,  # 连续板
        before_days=30,
        after_days=10
    )

    analyzer = LianbanPatternAnalyzer(config)
    analyzer.run()
