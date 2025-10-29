"""
连板股分析工具

功能：分析指定时间段内的连板股票，生成K线图便于找出共性特征
作者：AI Assistant
版本：v1.0
日期：2025-10-29
"""

import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from tqdm import tqdm

from utils.backtrade.visualizer import read_stock_data, _setup_mpf_style, _get_font_properties
from utils.date_util import (
    get_trading_days, get_n_trading_days_before, 
    get_next_trading_day, format_date
)


@dataclass
class LianbanAnalysisConfig:
    """连板分析配置"""
    
    # 必填参数
    start_date: str  # 开始日期，格式: YYYYMMDD
    end_date: str    # 结束日期，格式: YYYYMMDD
    
    # 筛选条件
    min_lianban_count: int = 3  # 最小连板数，默认3
    lianban_type: int = 1        # 连板类型：1=连续板，2=最高板，3=非连续板
    
    # 绘图范围（可配置的全局变量）
    before_days: int = 30    # 首板前显示的交易日数
    after_days: int = 10     # 终止后显示的交易日数
    end_threshold_days: int = 7  # 判断连板终止的阈值天数
    
    # 路径配置
    fupan_file: str = './excel/fupan_stocks.xlsx'
    data_dir: str = './data/astocks'
    output_dir: str = './analysis/lianban_charts'


@dataclass
class StockBoardInfo:
    """连板股信息"""
    code: str              # 股票代码（如 300502.SZ）
    name: str              # 股票简称
    first_board_date: str  # 首板日期（YYYYMMDD）
    end_date: str          # 终止日期（YYYYMMDD）
    max_board_count: int   # 最高板数
    continuous_days: int   # 连续涨停天数
    board_type: str        # 连板类型描述
    all_dates: List[str] = field(default_factory=list)  # 所有出现的日期列表


class LianbanAnalyzer:
    """连板股分析器"""
    
    def __init__(self, config: LianbanAnalysisConfig):
        """
        初始化分析器
        
        Args:
            config: 分析配置
        """
        self.config = config
        self.lianban_data = None  # 连板数据DataFrame
        self.shouban_data = None  # 首板数据DataFrame
        self.filtered_stocks = []  # 筛选后的股票列表
        self.date_columns = []     # 日期列列表
        
        # 创建输出目录
        date_range = f"{config.start_date}_{config.end_date}"
        self.output_dir = os.path.join(config.output_dir, date_range)
        os.makedirs(self.output_dir, exist_ok=True)
        
        logging.info(f"连板分析器初始化完成，输出目录: {self.output_dir}")
    
    def load_lianban_data(self):
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
        """
        将Excel列名日期转为datetime
        
        Args:
            column_date: 列名，格式为 "2025年01月15日"
            
        Returns:
            datetime对象
        """
        # 使用正则提取年月日
        match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', column_date)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return datetime(year, month, day)
        else:
            raise ValueError(f"无法解析日期列: {column_date}")
    
    def _format_to_column_date(self, dt: datetime) -> str:
        """
        将datetime转为Excel列名格式
        
        Args:
            dt: datetime对象
            
        Returns:
            格式为 "2025年01月15日" 的字符串
        """
        return dt.strftime('%Y年%m月%d日')
    
    def _parse_lianban_cell(self, cell_value: str) -> Optional[Dict]:
        """
        解析连板数据单元格
        
        Args:
            cell_value: 单元格内容，分号分隔
            
        Returns:
            解析后的字典，如果解析失败返回None
        """
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
        """
        从"几天几板"中提取板数
        
        Args:
            jitian_jiban: 如 "3天3板"、"5天3板"
            
        Returns:
            板数（整数）
        """
        if not jitian_jiban:
            return 0
        
        # 匹配 "X天Y板" 格式
        match = re.search(r'(\d+)天(\d+)板', str(jitian_jiban))
        if match:
            return int(match.group(2))  # 返回"Y板"的数值
        
        return 0
    
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
    
    def filter_stocks(self):
        """根据条件筛选股票"""
        logging.info("开始筛选股票...")
        
        # 收集所有股票代码及其在各日期的数据
        stock_records = {}  # {stock_code: {date: parsed_data}}
        
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
        
        # 对每只股票应用筛选条件
        for code, date_records in tqdm(stock_records.items(), desc="筛选股票"):
            if self._meets_criteria(code, date_records):
                stock_info = self._build_stock_info(code, date_records)
                if stock_info:
                    self.filtered_stocks.append(stock_info)
        
        logging.info(f"筛选完成，符合条件的股票: {len(self.filtered_stocks)} 只")
    
    def _meets_criteria(self, code: str, date_records: Dict) -> bool:
        """
        判断股票是否符合筛选条件
        
        Args:
            code: 股票代码
            date_records: 该股票在各日期的数据
            
        Returns:
            是否符合条件
        """
        # 获取所有日期的最高板数和连续天数
        max_board = 0
        max_continuous = 0
        
        for date_col, parsed in date_records.items():
            board_count = self._extract_board_count(parsed['jitian_jiban'])
            continuous_days = parsed['continuous_days']
            
            max_board = max(max_board, board_count)
            max_continuous = max(max_continuous, continuous_days)
        
        # 根据连板类型判断
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
    
    def _build_stock_info(self, code: str, date_records: Dict) -> Optional[StockBoardInfo]:
        """
        构建股票信息对象
        
        Args:
            code: 股票代码
            date_records: 该股票在各日期的数据
            
        Returns:
            StockBoardInfo对象，如果构建失败返回None
        """
        try:
            # 获取股票名称
            first_record = list(date_records.values())[0]
            stock_name = first_record['name']
            
            # 获取首板日期（从首板数据中查找）
            first_board_date = self._find_first_board_date(code)
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
                
                # 转换日期格式为YYYYMMDD
                date_dt = self._parse_column_date(date_col)
                all_dates.append(date_dt.strftime('%Y%m%d'))
            
            # 确定连板类型描述
            if max_board == max_continuous:
                board_type = f"连续{max_board}板"
            else:
                board_type = f"最高{max_board}板（有断板）"
            
            return StockBoardInfo(
                code=code,
                name=stock_name,
                first_board_date=first_board_date,
                end_date=end_date,
                max_board_count=max_board,
                continuous_days=max_continuous,
                board_type=board_type,
                all_dates=sorted(all_dates)
            )
            
        except Exception as e:
            logging.error(f"构建股票信息失败: {code}, 错误: {e}")
            return None
    
    def _find_first_board_date(self, code: str) -> Optional[str]:
        """
        从首板数据中查找首板日期
        
        Args:
            code: 股票代码
            
        Returns:
            首板日期（YYYYMMDD格式），未找到返回None
        """
        # 遍历首板数据的所有日期列
        all_shouban_cols = self.shouban_data.columns.tolist()
        
        for date_col in sorted(all_shouban_cols, key=lambda x: self._parse_column_date(x)):
            for idx, cell_value in self.shouban_data[date_col].items():
                parsed = self._parse_lianban_cell(cell_value)
                if parsed and parsed['code'] == code:
                    # 找到了，转换为YYYYMMDD格式
                    date_dt = self._parse_column_date(date_col)
                    return date_dt.strftime('%Y%m%d')
        
        return None
    
    def _find_end_date(self, code: str, date_records: Dict) -> str:
        """
        查找连板终止日期
        
        Args:
            code: 股票代码
            date_records: 该股票在各日期的数据
            
        Returns:
            终止日期（YYYYMMDD格式）
        """
        # 找到最后一次出现的日期
        sorted_dates = sorted(date_records.keys(), 
                            key=lambda x: self._parse_column_date(x),
                            reverse=True)
        
        last_date_col = sorted_dates[0]
        last_date_dt = self._parse_column_date(last_date_col)
        
        # 验证：之后threshold_days个交易日内不再出现
        try:
            current_check_date = last_date_dt.strftime('%Y%m%d')
            for _ in range(self.config.end_threshold_days):
                next_date = get_next_trading_day(current_check_date)
                if not next_date:
                    break
                
                next_col = self._format_to_column_date(
                    datetime.strptime(next_date, '%Y%m%d')
                )
                
                # 检查是否在后续日期中还出现
                if next_col in date_records:
                    # 还有出现，更新终止日期
                    last_date_dt = self._parse_column_date(next_col)
                    current_check_date = next_date
                else:
                    current_check_date = next_date
        except:
            pass
        
        return last_date_dt.strftime('%Y%m%d')
    
    def analyze_single_stock(self, stock_info: StockBoardInfo):
        """
        分析单只股票并生成K线图
        
        Args:
            stock_info: 股票信息
        """
        try:
            # 提取6位代码
            code_6digit = self._extract_stock_code(stock_info.code)
            
            # 计算绘图范围
            first_date_dt = datetime.strptime(stock_info.first_board_date, '%Y%m%d')
            end_date_dt = datetime.strptime(stock_info.end_date, '%Y%m%d')
            
            # 首板前before_days个交易日
            chart_start = get_n_trading_days_before(
                stock_info.first_board_date, 
                self.config.before_days
            )
            
            # 终止后after_days个交易日
            chart_end_str = stock_info.end_date
            for _ in range(self.config.after_days):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break
            
            # 读取股票数据
            stock_data = read_stock_data(code_6digit, self.config.data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {code_6digit} {stock_info.name} 的数据文件")
                return
            
            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')
            
            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()
            
            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {stock_info.name} 在指定日期范围内无数据")
                return
            
            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            
            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {stock_info.name} 清理停牌数据后无有效数据")
                return
            
            # 生成K线图
            self._plot_stock_chart(stock_info, chart_df, code_6digit)
            
        except Exception as e:
            logging.error(f"分析股票 {stock_info.code} {stock_info.name} 失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
    
    def _plot_stock_chart(self, stock_info: StockBoardInfo, chart_df: pd.DataFrame, code_6digit: str):
        """
        绘制K线图
        
        Args:
            stock_info: 股票信息
            chart_df: K线数据
            code_6digit: 6位股票代码
        """
        # 准备标记
        addplots = []
        
        # 首板标记（绿色向上三角）
        first_board_markers = [float('nan')] * len(chart_df)
        first_date_dt = datetime.strptime(stock_info.first_board_date, '%Y%m%d')
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
        end_date_dt = datetime.strptime(stock_info.end_date, '%Y%m%d')
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
        
        # 生成标题
        title = (
            f"{code_6digit} {stock_info.name} - 连板分析\n"
            f"首板: {stock_info.first_board_date} | "
            f"终止: {stock_info.end_date} | "
            f"最高: {stock_info.max_board_count}板 | "
            f"连续: {stock_info.continuous_days}天 | "
            f"类型: {stock_info.board_type}"
        )
        
        # 文件名
        filename = f"{stock_info.name}_{stock_info.first_board_date}_{stock_info.end_date}.png"
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
            addplot=addplots,
            figsize=(16, 9),
            returnfig=True,
            tight_layout=True
        )
        
        axes[0].set_title(title, loc='left', fontweight='bold', fontsize=11)
        axes[0].legend(loc='upper left', fontsize=10)
        
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        logging.debug(f"已生成图表: {filename}")
    
    def generate_summary_report(self):
        """生成汇总报告CSV"""
        summary_data = []
        
        for stock in self.filtered_stocks:
            summary_data.append({
                '股票代码': stock.code,
                '股票名称': stock.name,
                '首板日期': stock.first_board_date,
                '终止日期': stock.end_date,
                '最高板数': stock.max_board_count,
                '连续天数': stock.continuous_days,
                '连板类型': stock.board_type,
                '图表路径': f"./{stock.name}_{stock.first_board_date}_{stock.end_date}.png"
            })
        
        summary_df = pd.DataFrame(summary_data)
        summary_path = os.path.join(self.output_dir, 'summary.csv')
        summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
        
        logging.info(f"汇总报告已生成: {summary_path}")
        return summary_path
    
    def run(self):
        """执行完整分析流程"""
        logging.info("=" * 60)
        logging.info("开始连板股分析")
        logging.info(f"日期范围: {self.config.start_date} - {self.config.end_date}")
        logging.info(f"最小连板数: {self.config.min_lianban_count}")
        logging.info(f"连板类型: {self.config.lianban_type}")
        logging.info("=" * 60)
        
        # Phase 1: 加载数据
        self.load_lianban_data()
        
        # Phase 2: 筛选股票
        self.filter_stocks()
        
        if not self.filtered_stocks:
            logging.warning("未找到符合条件的股票！")
            return
        
        # Phase 3: 批量生成图表
        logging.info(f"开始生成 {len(self.filtered_stocks)} 只股票的K线图...")
        for stock_info in tqdm(self.filtered_stocks, desc="生成图表"):
            self.analyze_single_stock(stock_info)
        
        # Phase 4: 生成汇总报告
        summary_path = self.generate_summary_report()
        
        logging.info("=" * 60)
        logging.info("连板股分析完成！")
        logging.info(f"共分析 {len(self.filtered_stocks)} 只股票")
        logging.info(f"图表保存在: {self.output_dir}")
        logging.info(f"汇总报告: {summary_path}")
        logging.info("=" * 60)


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    config = LianbanAnalysisConfig(
        start_date='20250901',
        end_date='20251027',
        min_lianban_count=3,
        lianban_type=1,  # 连续板
        before_days=30,
        after_days=10
    )
    
    analyzer = LianbanAnalyzer(config)
    analyzer.run() 