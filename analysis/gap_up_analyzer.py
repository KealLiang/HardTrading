"""
跳空高开股票分析工具

功能：扫描指定时间段内跳空高开的股票，生成K线图便于分析
作者：AI Assistant
版本：v1.1
日期：2025-10-30
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from tqdm import tqdm

from analysis.ladder_chart import calculate_stock_period_change
from utils.backtrade.visualizer import read_stock_data, _setup_mpf_style
from utils.date_util import get_trading_days, get_n_trading_days_before, get_next_trading_day


@dataclass
class GapUpAnalysisConfig:
    """跳空高开分析配置"""
    
    # 必填参数
    start_date: str  # 开始日期，格式: YYYYMMDD
    end_date: str  # 结束日期，格式: YYYYMMDD
    
    # 跳空幅度范围
    min_gap_percent: float = 2.0  # 最小高开幅度（%）
    max_gap_percent: float = 100.0  # 最大高开幅度（%）
    
    # 前期涨幅过滤（可选）
    filter_enabled: bool = False  # 是否启用前期涨幅过滤
    filter_days: int = 5  # 前x个交易日
    filter_min_change: float = 10.0  # 前期最小涨幅（%）
    filter_max_change: float = 100.0  # 前期最大涨幅（%）
    
    # 路径配置
    data_dir: str = './data/astocks'
    output_dir: str = './analysis/gap_up_charts'


# 全局配置：绘图时间范围（不常变动）
CHART_BEFORE_DAYS = 30  # 最早跳空日前显示的交易日数
CHART_AFTER_DAYS = 10   # 最晚跳空日后显示的交易日数


# ==================== 工具函数 ====================

def scan_stock_files(data_dir: str) -> List[Tuple[str, str]]:
    """
    扫描股票数据文件
    
    Args:
        data_dir: 数据目录
        
    Returns:
        股票代码和名称的列表，格式为 [(code, name), ...]
    """
    stock_list = []
    
    try:
        files = os.listdir(data_dir)
        for filename in files:
            if filename.endswith('.csv'):
                # 文件名格式：000001_平安银行.csv
                parts = filename.replace('.csv', '').split('_', 1)
                if len(parts) == 2:
                    code, name = parts
                    stock_list.append((code, name))
        
        logging.info(f"扫描到 {len(stock_list)} 个股票数据文件")
        
    except Exception as e:
        logging.error(f"扫描股票文件失败: {e}")
    
    return stock_list


def add_marker(
    chart_df: pd.DataFrame,
    date_str: str,
    marker_type: str = '^',
    color: str = 'lime',
    label: str = '标记',
    position: str = 'below'
) -> mpf.make_addplot:
    """
    创建日期标记
    
    Args:
        chart_df: K线数据
        date_str: 标记日期（YYYYMMDD格式）
        marker_type: 标记类型（'^'向上三角，'v'向下三角，'o'圆圈等）
        color: 标记颜色
        label: 标记标签
        position: 标记位置（'below'在下方，'above'在上方）
        
    Returns:
        mplfinance addplot对象
    """
    markers = [float('nan')] * len(chart_df)
    date_dt = datetime.strptime(date_str, '%Y%m%d')
    
    try:
        idx = chart_df.index.searchsorted(date_dt, side='right') - 1
        if 0 <= idx < len(chart_df):
            if position == 'below':
                markers[idx] = chart_df.iloc[idx]['Low'] * 0.97
            else:
                markers[idx] = chart_df.iloc[idx]['High'] * 1.03
    except:
        pass
    
    return mpf.make_addplot(
        markers,
        type='scatter',
        marker=marker_type,
        color=color,
        markersize=120,
        label=label
    )


def plot_stock_kline(
    chart_df: pd.DataFrame,
    title: str,
    output_path: str,
    markers: Optional[List[mpf.make_addplot]] = None,
    figsize: Tuple[int, int] = (16, 9),
    dpi: int = 150
):
    """
    绘制K线图
    
    Args:
        chart_df: K线数据
        title: 图表标题
        output_path: 输出路径
        markers: 标记列表
        figsize: 图表尺寸
        dpi: 图片分辨率
    """
    try:
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
            addplot=markers if markers else [],
            figsize=figsize,
            returnfig=True,
            tight_layout=True
        )
        
        axes[0].set_title(title, loc='left', fontweight='bold', fontsize=11)
        
        if markers:
            axes[0].legend(loc='upper left', fontsize=10)
        
        # 调整y轴范围，确保标记完全显示
        y_min, y_max = axes[0].get_ylim()
        y_range = y_max - y_min
        axes[0].set_ylim(y_min - y_range * 0.05, y_max + y_range * 0.05)
        
        plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
        plt.close(fig)
        
        logging.debug(f"已生成图表: {output_path}")
        
    except Exception as e:
        logging.error(f"绘制K线图失败: {e}")
        raise


# ==================== 数据类 ====================

@dataclass
class GapUpStockInfo:
    """跳空高开股票信息"""
    code: str  # 股票代码（6位）
    name: str  # 股票名称
    gap_date: str  # 跳空日期（YYYYMMDD）
    gap_percent: float  # 跳空幅度（%）
    prev_close: float  # 前一日收盘价
    gap_open: float  # 跳空日开盘价
    prev_period_change: Optional[float] = None  # 前期涨幅（如果启用过滤）


class GapUpAnalyzer:
    """跳空高开分析器"""
    
    def __init__(self, config: GapUpAnalysisConfig):
        """
        初始化分析器
        
        Args:
            config: 分析配置
        """
        self.config = config
        self.filtered_stocks = []  # 筛选后的股票列表
        
        # 创建输出目录
        date_range = f"{config.start_date}_{config.end_date}"
        self.output_dir = os.path.join(config.output_dir, date_range)
        os.makedirs(self.output_dir, exist_ok=True)
        
        logging.info(f"跳空高开分析器初始化完成，输出目录: {self.output_dir}")
    
    def scan_and_filter_stocks(self):
        """扫描并筛选符合条件的股票"""
        logging.info("开始扫描股票数据...")
        
        # 扫描所有股票文件
        stock_list = scan_stock_files(self.config.data_dir)
        
        if not stock_list:
            logging.warning("未找到任何股票数据文件！")
            return
        
        # 获取日期范围内的交易日
        trading_days = get_trading_days(self.config.start_date, self.config.end_date)
        if not trading_days:
            logging.warning("指定日期范围内无交易日！")
            return
        
        logging.info(f"扫描 {len(stock_list)} 只股票，日期范围内共 {len(trading_days)} 个交易日")
        
        # 统计信息
        processed_stocks = 0
        error_stocks = 0
        
        # 遍历每只股票
        for stock_code, stock_name in tqdm(stock_list, desc="扫描股票"):
            try:
                # 读取股票数据
                stock_data = read_stock_data(stock_code, self.config.data_dir)
                if stock_data is None or stock_data.empty:
                    error_stocks += 1
                    continue
                
                processed_stocks += 1
                
                # 检查该股票在日期范围内的每一天
                for trade_date in trading_days:
                    gap_info = self._check_gap_up(
                        stock_data, stock_code, stock_name, trade_date
                    )
                    
                    if gap_info:
                        self.filtered_stocks.append(gap_info)
                        
            except Exception as e:
                error_stocks += 1
                logging.debug(f"处理股票 {stock_code} {stock_name} 失败: {e}")
                continue
        
        # 按股票代码分组统计
        stock_gap_count = {}
        for stock_info in self.filtered_stocks:
            key = (stock_info.code, stock_info.name)
            stock_gap_count[key] = stock_gap_count.get(key, 0) + 1
        
        logging.info(f"扫描完成：处理 {processed_stocks} 只股票，{error_stocks} 只出错")
        logging.info(f"筛选结果：共 {len(stock_gap_count)} 只股票符合条件，产生 {len(self.filtered_stocks)} 次跳空记录")
        
        # 显示跳空次数最多的前10只股票
        if stock_gap_count:
            top_stocks = sorted(stock_gap_count.items(), key=lambda x: x[1], reverse=True)[:10]
            logging.info("跳空次数最多的股票（前10）：")
            for (code, name), count in top_stocks:
                logging.info(f"  {code} {name}: {count}次跳空")
    
    def _check_gap_up(
        self,
        stock_data: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        trade_date: str
    ) -> Optional[GapUpStockInfo]:
        """
        检查指定日期是否跳空高开
        
        Args:
            stock_data: 股票数据
            stock_code: 股票代码
            stock_name: 股票名称
            trade_date: 交易日期（YYYYMMDD）
            
        Returns:
            如果符合条件返回GapUpStockInfo，否则返回None
        """
        try:
            # 转换日期格式
            trade_date_dt = datetime.strptime(trade_date, '%Y%m%d')
            
            # 检查当日数据是否存在
            if trade_date_dt not in stock_data.index:
                return None
            
            current_row = stock_data.loc[trade_date_dt]
            
            # 检查数据有效性
            if pd.isna(current_row['Open']) or pd.isna(current_row['Close']):
                return None
            
            # 获取前一交易日数据
            prev_rows = stock_data.loc[:trade_date_dt].iloc[:-1]
            if prev_rows.empty:
                return None
            
            prev_row = prev_rows.iloc[-1]
            if pd.isna(prev_row['Close']):
                return None
            
            prev_close = prev_row['Close']
            gap_open = current_row['Open']
            
            # 计算跳空幅度
            gap_percent = ((gap_open / prev_close) - 1) * 100
            
            # 判断是否在跳空范围内
            if gap_percent < self.config.min_gap_percent or gap_percent > self.config.max_gap_percent:
                return None
            
            # 如果启用前期涨幅过滤
            prev_period_change = None
            if self.config.filter_enabled:
                # 获取前x个交易日的日期
                start_date = get_n_trading_days_before(trade_date, self.config.filter_days)
                if not start_date:
                    return None
                
                # 计算前期涨幅
                prev_period_change = calculate_stock_period_change(
                    stock_code, start_date.replace('-', ''), trade_date, stock_name
                )
                
                if prev_period_change is None:
                    return None
                
                # 判断是否在涨幅范围内
                if (prev_period_change < self.config.filter_min_change or 
                    prev_period_change > self.config.filter_max_change):
                    return None
            
            # 创建股票信息
            return GapUpStockInfo(
                code=stock_code,
                name=stock_name,
                gap_date=trade_date,
                gap_percent=round(gap_percent, 2),
                prev_close=round(prev_close, 2),
                gap_open=round(gap_open, 2),
                prev_period_change=round(prev_period_change, 2) if prev_period_change else None
            )
            
        except Exception as e:
            logging.debug(f"检查跳空失败: {stock_code} {trade_date}, {e}")
            return None
    
    def analyze_single_stock(self, stock_code: str, stock_name: str, gap_infos: List[GapUpStockInfo]):
        """
        分析单只股票并生成K线图（合并该股票的所有跳空记录）
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            gap_infos: 该股票的所有跳空记录列表
        """
        try:
            if not gap_infos:
                return
            
            # 获取最早和最晚的跳空日期
            gap_dates = sorted([info.gap_date for info in gap_infos])
            earliest_gap = gap_dates[0]
            latest_gap = gap_dates[-1]
            
            # 计算图表范围
            chart_start = get_n_trading_days_before(earliest_gap, CHART_BEFORE_DAYS)
            
            # 计算终止日期
            chart_end_str = latest_gap
            for _ in range(CHART_AFTER_DAYS):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break
            
            # 读取股票数据
            stock_data = read_stock_data(stock_code, self.config.data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {stock_code} {stock_name} 的数据文件")
                return
            
            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')
            
            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()
            
            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 在指定日期范围内无数据")
                return
            
            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])
            
            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 清理停牌数据后无有效数据")
                return
            
            # 创建标记（为每个跳空日期添加标记）
            markers = []
            for gap_info in gap_infos:
                gap_marker = add_marker(
                    chart_df,
                    gap_info.gap_date,
                    marker_type='^',
                    color='gold',
                    label=f'跳空{gap_info.gap_percent}%',
                    position='below'
                )
                markers.append(gap_marker)
            
            # 生成标题
            gap_count = len(gap_infos)
            gap_summary = f"{gap_count}次跳空: " + ", ".join([
                f"{info.gap_date}({info.gap_percent}%)" for info in gap_infos[:3]
            ])
            if gap_count > 3:
                gap_summary += f" 等{gap_count}次"
            
            title_parts = [
                f"{stock_code} {stock_name} - 跳空高开分析",
                gap_summary
            ]
            
            title = "\n".join(title_parts)
            
            # 文件名（使用日期范围）
            filename = f"{stock_name}_{earliest_gap}至{latest_gap}_{gap_count}次跳空.png"
            output_path = os.path.join(self.output_dir, filename)
            
            # 绘制图表
            plot_stock_kline(
                chart_df,
                title,
                output_path,
                markers=markers
            )
            
        except Exception as e:
            logging.error(f"分析股票 {stock_code} {stock_name} 失败: {e}")
            import traceback
            logging.debug(traceback.format_exc())
    
    def generate_summary_report(self):
        """生成汇总报告CSV"""
        summary_data = []
        
        for stock in self.filtered_stocks:
            record = {
                '股票代码': stock.code,
                '股票名称': stock.name,
                '跳空日期': stock.gap_date,
                '跳空幅度(%)': stock.gap_percent,
                '前收盘价': stock.prev_close,
                '跳空开盘价': stock.gap_open,
            }
            
            if stock.prev_period_change is not None:
                record[f'前{self.config.filter_days}日涨幅(%)'] = stock.prev_period_change
            
            record['图表路径'] = f"./{stock.name}_{stock.gap_date}_gap{stock.gap_percent}%.png"
            
            summary_data.append(record)
        
        # 按跳空日期和跳空幅度排序
        summary_df = pd.DataFrame(summary_data)
        summary_df = summary_df.sort_values(
            by=['跳空日期', '跳空幅度(%)'],
            ascending=[True, False]
        )
        
        summary_path = os.path.join(self.output_dir, 'summary.csv')
        summary_df.to_csv(summary_path, index=False, encoding='utf-8-sig')
        
        logging.info(f"汇总报告已生成: {summary_path}")
        return summary_path
    
    def run(self):
        """执行完整分析流程"""
        logging.info("=" * 60)
        logging.info("开始跳空高开股票分析")
        logging.info(f"日期范围: {self.config.start_date} - {self.config.end_date}")
        logging.info(f"跳空幅度范围: {self.config.min_gap_percent}% - {self.config.max_gap_percent}%")
        
        if self.config.filter_enabled:
            logging.info(
                f"前期涨幅过滤: 前{self.config.filter_days}日涨幅 "
                f"{self.config.filter_min_change}% - {self.config.filter_max_change}%"
            )
        
        logging.info("=" * 60)
        
        # Phase 1: 扫描并筛选股票
        self.scan_and_filter_stocks()
        
        if not self.filtered_stocks:
            logging.warning("未找到符合条件的股票！")
            return
        
        # Phase 2: 按股票分组
        from collections import defaultdict
        stock_groups = defaultdict(list)
        for stock_info in self.filtered_stocks:
            key = (stock_info.code, stock_info.name)
            stock_groups[key].append(stock_info)
        
        # Phase 3: 批量生成图表（每只股票一张图）
        logging.info(f"开始生成 {len(stock_groups)} 只股票的K线图...")
        for (stock_code, stock_name), gap_infos in tqdm(stock_groups.items(), desc="生成图表"):
            self.analyze_single_stock(stock_code, stock_name, gap_infos)
        
        # Phase 4: 生成汇总报告
        summary_path = self.generate_summary_report()
        
        logging.info("=" * 60)
        logging.info("跳空高开股票分析完成！")
        logging.info(f"共分析 {len(stock_groups)} 只股票，{len(self.filtered_stocks)} 次跳空记录")
        logging.info(f"图表保存在: {self.output_dir}")
        logging.info(f"汇总报告: {summary_path}")
        logging.info("=" * 60)


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 示例1: 基本使用 - 寻找跳空3%以上的股票
    config = GapUpAnalysisConfig(
        start_date='20250901',
        end_date='20251027',
        min_gap_percent=3.0,
        max_gap_percent=10.0
    )
    
    analyzer = GapUpAnalyzer(config)
    analyzer.run()
    
    # 示例2: 启用前期涨幅过滤 - 寻找前5日涨幅超过10%且当日跳空3%以上的股票
    # config = GapUpAnalysisConfig(
    #     start_date='20250901',
    #     end_date='20251027',
    #     min_gap_percent=3.0,
    #     max_gap_percent=10.0,
    #     filter_enabled=True,
    #     filter_days=5,
    #     filter_min_change=10.0,
    #     filter_max_change=50.0
    # )
    # 
    # analyzer = GapUpAnalyzer(config)
    # analyzer.run() 