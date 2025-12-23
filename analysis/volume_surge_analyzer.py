"""
爆量分歧转一致形态分析器

形态定义：
- 强势连板股在某日出现爆量（当日量能较近期明显放大）
- 但当日仍然上涨（今收 > 昨收，不要求涨停）
- 这种形态代表分歧后资金选择继续做多

核心目的：
- 寻找这类形态的规律
- 观察后续走势
- 分析什么时段什么形态的股票资金最愿意买入

作者：AI Assistant
版本：v1.1
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


@dataclass
class VolumeSurgeConfig(PatternAnalysisConfig):
    """
    爆量分歧转一致分析配置
    
    Attributes:
        volume_surge_ratio: 爆量阈值（当日量/前N日均量），默认2.0表示量能翻倍
        volume_avg_days: 计算均量的天数，默认5天
        min_lianban_count: 最小连板数，只分析达到此连板数的股票，默认2
    """
    volume_surge_ratio: float = 2.0
    volume_avg_days: int = 5
    min_lianban_count: int = 2


class VolumeSurgeAnalyzer(PatternAnalyzerBase):
    """
    爆量分歧转一致形态分析器
    
    筛选逻辑：
    1. 从复盘数据中筛选达到min_lianban_count连板的股票
    2. 检测这些股票在指定日期范围内是否出现爆量日
    3. 爆量日需满足：当日量能 >= 前N日均量 * volume_surge_ratio
    4. 爆量日需满足：当日上涨（收盘价 > 前一日收盘价）
    """

    def __init__(self, config: VolumeSurgeConfig):
        """
        初始化分析器
        
        Args:
            config: 爆量分歧分析配置
        """
        super().__init__(config, "爆量分歧转一致")
        self.config: VolumeSurgeConfig = config
        self.lianban_data = None
        self.shouban_data = None
        self.date_columns = []
        # 存储连板股候选池：{stock_code: {name, first_board_date, max_board}}
        self.lianban_candidates: Dict[str, Dict] = {}
        # 存储每个信号的详细数据，用于多信号场景
        self._signal_details: Dict[str, Dict[str, Dict]] = {}  # {code: {date: surge_info}}

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

    def _build_lianban_candidates(self):
        """
        构建连板股候选池
        筛选在日期范围内达到min_lianban_count连板的股票
        """
        logging.info("构建连板股候选池...")

        for date_col in self.date_columns:
            for idx, cell_value in self.lianban_data[date_col].items():
                parsed = self._parse_lianban_cell(cell_value)
                if not parsed:
                    continue

                code = parsed['code']
                board_count = self._extract_board_count(parsed['jitian_jiban'])

                # 只收集达到最小连板数的股票
                if board_count >= self.config.min_lianban_count:
                    if code not in self.lianban_candidates:
                        self.lianban_candidates[code] = {
                            'name': parsed['name'],
                            'max_board': board_count,
                            'lianban_dates': []
                        }
                    else:
                        self.lianban_candidates[code]['max_board'] = max(
                            self.lianban_candidates[code]['max_board'],
                            board_count
                        )

                    # 记录连板日期
                    date_str = self._parse_column_date(date_col).strftime('%Y%m%d')
                    if date_str not in self.lianban_candidates[code]['lianban_dates']:
                        self.lianban_candidates[code]['lianban_dates'].append(date_str)

        logging.info(f"候选池中共有 {len(self.lianban_candidates)} 只连板股")

    def _get_volume_surge_info(self, code_6digit: str, date_str: str) -> Optional[Dict]:
        """
        检测指定日期是否为爆量日
        
        Args:
            code_6digit: 6位股票代码
            date_str: 日期字符串 YYYYMMDD
            
        Returns:
            爆量信息字典，如果不是爆量日返回None
        """
        from utils.backtrade.visualizer import read_stock_data

        stock_data = read_stock_data(code_6digit, self.config.data_dir)
        if stock_data is None or stock_data.empty:
            return None

        try:
            target_date = datetime.strptime(date_str, '%Y%m%d')

            # 确保目标日期在数据范围内
            if target_date not in stock_data.index:
                # 尝试查找最接近的日期
                idx = stock_data.index.searchsorted(target_date, side='right') - 1
                if idx < 0 or idx >= len(stock_data):
                    return None
                target_date = stock_data.index[idx]
                # 如果日期差距太大，放弃
                if abs((target_date - datetime.strptime(date_str, '%Y%m%d')).days) > 3:
                    return None

            idx = stock_data.index.get_loc(target_date)

            # 需要足够的历史数据计算均量
            if idx < self.config.volume_avg_days:
                return None

            # 获取当日数据
            current_row = stock_data.iloc[idx]
            current_volume = current_row['Volume']
            current_close = current_row['Close']

            # 获取前一日收盘价
            prev_close = stock_data.iloc[idx - 1]['Close']

            # 条件1：当日上涨（今收 > 昨收）
            if current_close <= prev_close:
                return None

            # 计算前N日均量
            prev_volumes = stock_data.iloc[idx - self.config.volume_avg_days:idx]['Volume']
            avg_volume = prev_volumes.mean()

            if avg_volume <= 0:
                return None

            # 计算量比
            volume_ratio = current_volume / avg_volume

            # 条件2：爆量（量比 >= 阈值）
            if volume_ratio < self.config.volume_surge_ratio:
                return None

            # 计算涨幅
            pct_change = (current_close - prev_close) / prev_close * 100

            return {
                'date': target_date.strftime('%Y%m%d'),
                'volume_ratio': round(volume_ratio, 2),
                'pct_change': round(pct_change, 2),
                'current_volume': current_volume,
                'avg_volume': round(avg_volume, 0),
                'current_close': current_close,
                'prev_close': prev_close
            }

        except Exception as e:
            logging.debug(f"检测股票 {code_6digit} 在 {date_str} 的爆量信息时出错: {e}")
            return None

    def filter_stocks(self):
        """筛选符合爆量分歧转一致形态的股票"""
        logging.info("开始筛选爆量分歧转一致形态...")

        # 先构建连板股候选池
        self._build_lianban_candidates()

        if not self.lianban_candidates:
            logging.warning("未找到符合条件的连板股")
            return

        # 遍历候选池，检测爆量日
        for code, info in tqdm(self.lianban_candidates.items(), desc="检测爆量日"):
            code_6digit = code.split('.')[0] if '.' in code else code

            # 初始化信号详情存储
            if code not in self._signal_details:
                self._signal_details[code] = {}

            # 遍历该股票的所有连板日期，检测是否有爆量
            for lianban_date in info['lianban_dates']:
                surge_info = self._get_volume_surge_info(code_6digit, lianban_date)

                if surge_info:
                    # 存储信号详情，便于后续多信号场景使用
                    self._signal_details[code][surge_info['date']] = surge_info

                    pattern_info = PatternInfo(
                        code=code,
                        name=info['name'],
                        pattern_date=surge_info['date'],
                        pattern_type="爆量分歧转一致",
                        extra_data={
                            'max_board': info['max_board'],
                            'volume_ratio': surge_info['volume_ratio'],
                            'pct_change': surge_info['pct_change'],
                            'current_volume': surge_info['current_volume'],
                            'avg_volume': surge_info['avg_volume']
                        }
                    )
                    self.filtered_stocks.append(pattern_info)

        logging.info(f"筛选完成，符合条件的形态: {len(self.filtered_stocks)} 个")

    def get_chart_markers(self, pattern_info: PatternInfo, chart_df: pd.DataFrame) -> List:
        """获取图表标记配置（支持多个信号日期）"""
        addplots = []

        # 为每个信号日期添加标记
        surge_markers = [float('nan')] * len(chart_df)
        volume_markers = [float('nan')] * len(chart_df)

        for date_str in pattern_info.pattern_dates:
            pattern_date_dt = datetime.strptime(date_str, '%Y%m%d')

            try:
                idx = chart_df.index.searchsorted(pattern_date_dt, side='right') - 1
                if 0 <= idx < len(chart_df):
                    surge_markers[idx] = chart_df.iloc[idx]['Low'] * 0.97
                    volume_markers[idx] = chart_df.iloc[idx]['Volume']
            except:
                pass

        # 爆量日标记（蓝色向上三角）
        addplots.append(mpf.make_addplot(
            surge_markers,
            type='scatter',
            marker='^',
            color='blue',
            markersize=150,
            label=f'爆量日({len(pattern_info.pattern_dates)}个)'
        ))

        # 成交量面板标记
        addplots.append(mpf.make_addplot(
            volume_markers,
            type='scatter',
            marker='*',
            color='magenta',
            markersize=100,
            panel=1,
            label='爆量'
        ))

        return addplots

    def get_chart_title(self, pattern_info: PatternInfo) -> str:
        """获取图表标题"""
        extra = pattern_info.extra_data
        code_6digit = self._extract_stock_code(pattern_info.code)

        signal_count = extra.get('signal_count', 1)

        if signal_count > 1:
            # 多信号情况
            all_signals = extra.get('all_signals', [])
            avg_volume_ratio = sum(s.get('volume_ratio', 0) for s in all_signals) / len(all_signals)
            dates_str = ', '.join(pattern_info.pattern_dates)
            title = (
                f"{code_6digit} {pattern_info.name} - 爆量分歧转一致 ({signal_count}次)\n"
                f"信号日期: {dates_str}\n"
                f"平均量比: {avg_volume_ratio:.1f}倍 | 最高连板: {extra.get('max_board', 'N/A')}板"
            )
        else:
            # 单信号情况
            title = (
                f"{code_6digit} {pattern_info.name} - 爆量分歧转一致\n"
                f"形态日期: {pattern_info.pattern_date} | "
                f"量比: {extra.get('volume_ratio', 'N/A')}倍 | "
                f"涨幅: {extra.get('pct_change', 'N/A')}% | "
                f"最高连板: {extra.get('max_board', 'N/A')}板"
            )
        return title

    def get_summary_columns(self) -> List[str]:
        """获取汇总报告的列名列表"""
        return [
            '股票代码', '股票名称', '信号次数', '形态日期', '量比',
            '当日涨幅%', '最高连板数', '图表路径'
        ]

    def build_summary_row(self, pattern_info: PatternInfo) -> Dict[str, Any]:
        """构建汇总报告的单行数据"""
        extra = pattern_info.extra_data
        signal_count = extra.get('signal_count', 1)

        # 文件名：日期在前便于排序
        filename = f"{pattern_info.pattern_date}_{pattern_info.name}.png"

        # 量比和涨幅（多信号时显示范围）
        if signal_count > 1:
            all_signals = extra.get('all_signals', [])
            volume_ratios = [s.get('volume_ratio', 0) for s in all_signals]
            pct_changes = [s.get('pct_change', 0) for s in all_signals]
            volume_ratio_str = f"{min(volume_ratios):.1f}-{max(volume_ratios):.1f}"
            pct_change_str = f"{min(pct_changes):.1f}-{max(pct_changes):.1f}"
        else:
            volume_ratio_str = str(extra.get('volume_ratio', ''))
            pct_change_str = str(extra.get('pct_change', ''))

        return {
            '股票代码': pattern_info.code,
            '股票名称': pattern_info.name,
            '信号次数': signal_count,
            '形态日期': ', '.join(pattern_info.pattern_dates),
            '量比': volume_ratio_str,
            '当日涨幅%': pct_change_str,
            '最高连板数': extra.get('max_board', ''),
            '图表路径': f"./{filename}"
        }


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    config = VolumeSurgeConfig(
        start_date='20251101',
        end_date='20251220',
        volume_surge_ratio=2.0,
        volume_avg_days=5,
        min_lianban_count=2,
        before_days=30,
        after_days=10
    )

    analyzer = VolumeSurgeAnalyzer(config)
    analyzer.run()
