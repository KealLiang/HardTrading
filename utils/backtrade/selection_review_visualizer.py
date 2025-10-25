"""
历史候选股回顾可视化器
读取历史记录文件，生成包含后续走势的对比图
"""

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.gridspec import GridSpec

from bin.selection_history_tracker import SelectionHistoryTracker
from bin.simulator import read_stock_data
from utils.date_util import get_current_or_prev_trading_day
from utils.stock_util import format_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


class SelectionReviewVisualizer:
    """历史候选股回顾可视化器"""

    def __init__(self, data_dir: str = './data/astocks',
                 output_dir: str = 'bin/candidate_history/review_charts'):
        """
        初始化回顾可视化器
        
        Args:
            data_dir: 股票数据目录
            output_dir: 输出图表目录
        """
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.tracker = SelectionHistoryTracker()

        os.makedirs(output_dir, exist_ok=True)

    def _setup_mpf_style(self):
        """设置mplfinance样式（红涨绿跌，A股习惯）"""
        # 设置红涨绿跌的颜色
        mc = mpf.make_marketcolors(
            up='red', down='green',
            edge={'up': 'red', 'down': 'green'},
            wick={'up': 'red', 'down': 'green'},
            volume='inherit'
        )

        return mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mc,
            rc={'font.family': ['SimHei', 'Microsoft YaHei', 'DejaVu Sans'],
                'axes.unicode_minus': False}
        )

    def plot_stock_review(self, stock_code: str, stock_name: str,
                          signal_date: pd.Timestamp, signal_price: float,
                          before_days: int = 90, review_date: str = None,
                          model: str = None) -> str:
        """
        绘制单只股票的回顾图
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            signal_date: 信号日期
            signal_price: 信号价格
            before_days: 信号日期之前显示的天数
            review_date: 回顾日期（默认为最近交易日）
        
        Returns:
            生成的图表文件路径
        """
        try:
            # 读取股票数据
            stock_data = read_stock_data(stock_code, self.data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"无法加载股票 {stock_code} 的数据")
                return None

            # 确定回顾日期（最近交易日）
            if review_date is None:
                today_str = datetime.now().strftime('%Y%m%d')
                review_date_str = get_current_or_prev_trading_day(today_str)
                review_date = pd.to_datetime(f"{review_date_str[:4]}-{review_date_str[4:6]}-{review_date_str[6:8]}")
            else:
                review_date = pd.to_datetime(review_date)

            # 确定数据范围
            start_date = signal_date - timedelta(days=before_days)
            end_date = review_date

            # 截取数据
            chart_df = stock_data.loc[start_date:end_date].copy()

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} 在指定日期范围内无数据")
                return None

            # 列名转换：read_stock_data返回的是小写列名，mplfinance需要首字母大写
            chart_df = chart_df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} 清理后无有效数据")
                return None

            # 找到信号日期在数据中的位置
            signal_idx = None
            for idx, row_date in enumerate(chart_df.index):
                if row_date.date() == signal_date.date():
                    signal_idx = idx
                    break

            # 创建信号标记
            addplots = []

            if signal_idx is not None:
                # 获取模式对应的标记样式
                marker_style = self._get_model_marker_style(model) if model else \
                    {'marker': 'o', 'color': 'cyan', 'size': 150}

                # 创建入选信号标记（位于K线下方）
                signal_markers = [float('nan')] * len(chart_df)
                # 放在最低价下方2%的位置
                signal_markers[signal_idx] = chart_df.iloc[signal_idx]['Low'] * 0.98

                addplots.append(mpf.make_addplot(
                    signal_markers,
                    type='scatter',
                    markersize=marker_style['size'],
                    marker=marker_style['marker'],
                    color=marker_style['color'],
                    panel=0
                    # 不需要label，避免图例挡住图片
                ))

            # 计算收益率
            if signal_idx is not None and signal_idx < len(chart_df):
                latest_price = chart_df.iloc[-1]['Close']
                profit_pct = (latest_price - signal_price) / signal_price * 100
                profit_text = f"入选价: {signal_price:.2f}, 最新价: {latest_price:.2f}, 收益率: {profit_pct:+.2f}%"
            else:
                profit_text = f"入选价: {signal_price:.2f}"

            # 设置样式
            style = self._setup_mpf_style()

            # 生成标题
            title = f"{stock_code} {stock_name}\n入选日期: {signal_date.strftime('%Y-%m-%d')}, {profit_text}"

            # 生成输出文件名
            output_filename = f"review_{stock_code}_{signal_date.strftime('%Y%m%d')}.png"
            output_path = os.path.join(self.output_dir, output_filename)

            # 绘制K线图
            mpf.plot(
                chart_df,
                type='candle',
                style=style,
                title=title,
                ylabel='价格',
                ylabel_lower='成交量',
                volume=True,
                addplot=addplots if addplots else None,
                savefig=output_path,
                figsize=(10, 6),
                tight_layout=True
            )

            logging.debug(f"生成回顾图: {output_path}")
            return output_path

        except Exception as e:
            logging.error(f"绘制股票 {stock_code} 回顾图失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None

    def _get_model_marker_style(self, model: str) -> Dict:
        """
        根据模式获取标记样式
        
        Returns:
            dict: {'marker': 标记形状, 'color': 颜色, 'size': 大小}
        """
        model_styles = {
            'rebound_a': {'marker': 'o', 'color': 'cyan', 'size': 150},  # 蓝色圆形
            'breakout_a': {'marker': 'd', 'color': 'purple', 'size': 150},  # 紫色五角星
            'breakout_b': {'marker': '*', 'color': 'orange', 'size': 150},  # 橙色方形
        }
        return model_styles.get(model, {'marker': 'o', 'color': 'yellow', 'size': 150})

    def create_comparison_review_chart(self, signal_date: str,
                                       stocks_data: List[Dict],
                                       before_days: int = 90,
                                       review_date: str = None,
                                       max_cols: int = 2) -> str:
        """
        为指定日期的股票创建对比回顾图
        
        Args:
            signal_date: 信号日期字符串 'YYYY-MM-DD'
            stocks_data: 股票信息列表 [{'code': ..., 'name': ..., 'price': ..., 'model': ...}, ...]
            before_days: 信号日期之前显示的天数
            review_date: 回顾日期
            max_cols: 每行最大列数
        
        Returns:
            生成的对比图文件路径
        """
        if not stocks_data:
            logging.warning(f"日期 {signal_date} 没有股票数据")
            return None

        signal_date_dt = pd.to_datetime(signal_date)

        # 按模式分组
        stocks_by_model = defaultdict(list)
        for stock_info in stocks_data:
            stocks_by_model[stock_info.get('model', 'unknown')].append(stock_info)

        # 为每只股票生成子图数据（按模式分组）
        all_charts = []

        for model in sorted(stocks_by_model.keys()):
            model_stocks = stocks_by_model[model]

            for stock_info in model_stocks:
                chart_path = self.plot_stock_review(
                    stock_info['code'],
                    stock_info['name'],
                    signal_date_dt,
                    stock_info['price'],
                    before_days,
                    review_date,
                    model  # 传递模式参数，用于标记样式
                )

                if chart_path:
                    all_charts.append({
                        'path': chart_path,
                        'code': stock_info['code'],
                        'name': stock_info['name'],
                        'model': model
                    })

        if not all_charts:
            logging.warning(f"日期 {signal_date} 没有成功生成任何图表")
            return None

        # 创建对比图
        total_charts = len(all_charts)
        cols = min(max_cols, total_charts)
        rows = (total_charts + cols - 1) // cols

        fig_width = cols * 10
        fig_height = rows * 6

        fig = plt.figure(figsize=(fig_width, fig_height))

        # 确定回顾日期用于标题
        if review_date is None:
            today_str = datetime.now().strftime('%Y%m%d')
            review_date_str = get_current_or_prev_trading_day(today_str)
            review_date_display = f"{review_date_str[:4]}-{review_date_str[4:6]}-{review_date_str[6:8]}"
        else:
            review_date_display = review_date

        fig.suptitle(
            f'入选日期: {signal_date} 回顾对比图 ({len(stocks_data)}只股票)\n回顾日期: {review_date_display}',
            fontsize=16, fontweight='bold'
        )

        # 减少空白，让图片更大
        gs = GridSpec(rows, cols, figure=fig, hspace=0.25, wspace=0.15)

        for i, chart_info in enumerate(all_charts):
            try:
                row = i // cols
                col = i % cols

                ax = fig.add_subplot(gs[row, col])

                # 读取并显示子图
                img = plt.imread(chart_info['path'])
                ax.imshow(img)
                ax.axis('off')

                # 在左上角添加模式标签
                model = chart_info.get('model', 'unknown')
                model_display = {
                    'rebound_a': '止跌反弹A',
                    'breakout_a': '突破策略A',
                    'breakout_b': '突破策略B'
                }.get(model, model)

                ax.text(0.02, 0.98, model_display,
                        transform=ax.transAxes,
                        fontsize=10, fontweight='bold',
                        ha='left', va='top',
                        bbox=dict(boxstyle='round,pad=0.3',
                                  facecolor='white',
                                  edgecolor='gray',
                                  alpha=0.8))

            except Exception as e:
                logging.error(f"加载图表 {chart_info['path']} 失败: {e}")
                continue

        # 保存对比图
        output_filename = f"review_comparison_{signal_date.replace('-', '')}.png"
        output_path = os.path.join(self.output_dir, output_filename)

        plt.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        plt.close()

        # 清理临时子图文件
        for chart_info in all_charts:
            try:
                os.remove(chart_info['path'])
            except:
                pass

        logging.info(f"生成回顾对比图: {output_path}")
        return output_path

    def review_date_range(self, start_date: str, end_date: str,
                          model: str = None, before_days: int = 90,
                          review_date: str = None):
        """
        回顾指定日期范围内的所有入选股票
        
        Args:
            start_date: 开始日期 (信号日期)，格式 'YYYY-MM-DD'
            end_date: 结束日期 (信号日期)，格式 'YYYY-MM-DD'
            model: 模式筛选，如 'rebound_a'
            before_days: 信号日期之前显示的天数
            review_date: 回顾日期（默认为最近交易日）
        
        Returns:
            生成的对比图文件列表
        """
        logging.info(f"开始回顾日期范围: {start_date} ~ {end_date}, 模式: {model or '全部'}")

        # 加载历史记录
        df = self.tracker.load_history(start_date, end_date, model)

        if df.empty:
            logging.warning("未找到符合条件的历史记录")
            return []

        # 按信号日期分组
        date_stocks_map = defaultdict(list)

        for _, row in df.iterrows():
            signal_date_str = row['信号日期'].strftime('%Y-%m-%d')
            # 确保股票代码格式正确（补全前导零）
            stock_code = format_stock_code(row['股票代码'])
            date_stocks_map[signal_date_str].append({
                'code': stock_code,
                'name': row['股票名称'],
                'price': float(row['信号价格']),
                'model': row['模式']
            })

        # 为每个日期生成对比图
        generated_files = []

        for signal_date, stocks_data in sorted(date_stocks_map.items()):
            logging.info(f"处理日期 {signal_date}: {len(stocks_data)} 只股票")

            output_path = self.create_comparison_review_chart(
                signal_date,
                stocks_data,
                before_days,
                review_date
            )

            if output_path:
                generated_files.append(output_path)

        logging.info(f"回顾完成！共生成 {len(generated_files)} 张对比图")
        if generated_files:
            logging.info(f"回顾图保存在: {self.output_dir}")
        else:
            logging.warning("未生成任何回顾图，可能是数据不足或筛选条件过严")

        return generated_files


def review_historical_selections(start_date: str, end_date: str,
                                 model: str = None, before_days: int = 90):
    """
    回顾历史候选股的便捷函数
    
    Args:
        start_date: 开始日期 (信号日期)，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        end_date: 结束日期 (信号日期)，格式 'YYYY-MM-DD' 或 'YYYYMMDD'
        model: 模式筛选，如 'rebound_a', 'breakout_a', 'breakout_b'
        before_days: 信号日期之前显示的天数（默认90天）
    
    Returns:
        生成的对比图文件列表
    """
    # 格式化日期
    if '-' not in start_date and len(start_date) == 8:
        start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    if '-' not in end_date and len(end_date) == 8:
        end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    visualizer = SelectionReviewVisualizer()
    return visualizer.review_date_range(start_date, end_date, model, before_days)


if __name__ == '__main__':
    # 测试代码
    print("测试回顾可视化功能...")

    # 回顾最近几天的候选股
    files = review_historical_selections(
        start_date='2025-10-20',
        end_date='2025-10-25',
        model='rebound_a',
        before_days=90
    )

    print(f"\n生成了 {len(files)} 张回顾图")
    for file in files:
        print(f"  {file}")
