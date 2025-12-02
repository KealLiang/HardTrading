"""
股票信号对比图生成器
根据scan_summary的信号日期分组，生成同日期股票的对比图
"""

import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.gridspec import GridSpec

from analysis.ladder_chart import calculate_stock_period_change
from utils.date_util import get_current_or_prev_trading_day

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')


class ComparisonChartGenerator:
    """股票对比图生成器"""

    def __init__(self, base_dir='bin/candidate_stocks_result'):
        self.base_dir = base_dir
        self.comparison_dir = os.path.join(base_dir, 'comparison_charts')
        self.strategy_name = self._get_strategy_name_from_summary()

        # 创建对比图输出目录
        os.makedirs(self.comparison_dir, exist_ok=True)

    def _get_strategy_name_from_summary(self) -> str:
        """从最新的summary文件中解析策略名称"""
        try:
            summary_files = [f for f in os.listdir(self.base_dir) if
                             f.startswith('scan_summary_') and f.endswith('.txt')]
            if not summary_files:
                return 'BreakoutStrategy'  # 默认值

            latest_summary = sorted(summary_files)[-1]
            summary_path = os.path.join(self.base_dir, latest_summary)

            with open(summary_path, 'r', encoding='utf-8') as f:
                first_line = f.readline()

            match = re.search(r'扫描策略:\s*(\w+)', first_line)
            if match:
                strategy_name = match.group(1)
                logging.info(f"从summary文件自动识别策略: {strategy_name}")
                return strategy_name
        except Exception as e:
            logging.warning(f"自动识别策略名称失败: {e}, 将使用默认值")

        return 'BreakoutStrategy'

    def parse_scan_summary(self, summary_file_path: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        解析scan_summary文件，提取股票代码和信号日期的对应关系
        
        Args:
            summary_file_path: summary文件路径
            
        Returns:
            Dict[日期, List[Tuple[股票代码, 股票名称]]]
        """
        date_stocks_map = defaultdict(list)

        try:
            with open(summary_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line in lines:
                if line.strip() and not line.startswith('扫描策略') and not line.startswith(
                        '扫描范围') and not line.startswith('总计发现') and not line.startswith('-'):
                    # 解析格式：股票: 300732 设研院, 信号日期: 2025-08-11, 价格: 12.22, 评分: 0，详情: ...
                    stock_match = re.search(r'股票:\s*(\d{6})\s*([^,]*)', line)
                    date_match = re.search(r'信号日期:\s*(\d{4}-\d{2}-\d{2})', line)

                    if stock_match and date_match:
                        code = stock_match.group(1)
                        name = stock_match.group(2).strip()
                        signal_date = date_match.group(1)
                        date_stocks_map[signal_date].append((code, name))

            logging.info(f"解析完成，共找到 {len(date_stocks_map)} 个交易日的信号")
            for date, stocks in sorted(date_stocks_map.items(), reverse=True)[:5]:
                logging.info(f"  {date}: {len(stocks)} 只股票")

        except Exception as e:
            logging.error(f"解析scan_summary文件失败: {e}")

        return date_stocks_map

    def find_stock_trade_images_by_log(self, stock_code: str, signal_date: str) -> List[Tuple[str, str]]:
        """
        根据trade_log.csv精确查找指定股票和信号日期对应的图片
        
        Args:
            stock_code: 股票代码
            signal_date: 信号日期 (YYYY-MM-DD格式)
            
        Returns:
            List[Tuple[图片路径, 标签描述]]
        """
        # 转换日期格式 YYYY-MM-DD -> YYYYMMDD
        date_formatted = signal_date.replace('-', '')

        # 修复：文件夹按首次信号日期命名，需搜索所有匹配的文件夹
        folder_path = None
        try:
            for item in os.listdir(self.base_dir):
                if item.startswith(f"{stock_code}_") and os.path.isdir(os.path.join(self.base_dir, item)):
                    folder_path = os.path.join(self.base_dir, item)
                    break
        except Exception as e:
            logging.warning(f"扫描目录失败: {e}")
            return []

        if not folder_path:
            logging.debug(f"未找到文件夹: {stock_code} @ {signal_date}")
            return []

        # 读取trade_log.csv
        trade_log_path = os.path.join(folder_path, 'trade_log.csv')
        if not os.path.exists(trade_log_path):
            # 如果没有trade_log，使用旧逻辑
            return self._fallback_find_images(folder_path, stock_code)

        try:
            trade_log = pd.read_csv(trade_log_path)
            if trade_log.empty:
                return self._fallback_find_images(folder_path, stock_code)
        except:
            return self._fallback_find_images(folder_path, stock_code)

        results = []
        matched_trade_nums = set()

        # 查找与指定信号日期匹配的记录
        for _, row in trade_log.iterrows():
            if pd.isna(row.get('signal_date')):
                continue

            log_signal_date = str(row['signal_date'])
            if log_signal_date != signal_date:
                continue

            record_type = row.get('type', '').upper()
            trade_num = row.get('trade_num', 0)

            if record_type == 'SIGNAL':
                # 查找signal_chart图片
                signal_chart_file = f"signal_chart_{stock_code}_{date_formatted}.png"
                signal_chart_path = os.path.join(folder_path, signal_chart_file)
                if os.path.exists(signal_chart_path):
                    results.append((signal_chart_path, "Signal Only"))
                else:
                    # WAITING格式（回踩等待信号）
                    waiting_chart_file = f"signal_chart_{stock_code}_WAITING.png"
                    waiting_chart_path = os.path.join(folder_path, waiting_chart_file)
                    if os.path.exists(waiting_chart_path):
                        results.append((waiting_chart_path, "Signal Only"))

            elif record_type == 'BUY' and trade_num > 0 and trade_num not in matched_trade_nums:
                # TODO-c: 多信号匹配问题 - trade图片文件名需要包含signal_date以区分不同日期的信号
                # 当前：trade_1_300509.png，应改为：trade_1_300509_20251201.png
                trade_file = f"trade_{trade_num}_{stock_code}.png"
                trade_path = os.path.join(folder_path, trade_file)
                if os.path.exists(trade_path):
                    results.append((trade_path, f"Trade {trade_num}"))
                    matched_trade_nums.add(trade_num)

        if not results:
            logging.debug(f"未匹配到图片: {stock_code} @ {signal_date}")

        return results

    def _fallback_find_images(self, folder_path: str, stock_code: str) -> List[Tuple[str, str]]:
        """当没有trade_log时的后备方案"""
        results = []
        for file in os.listdir(folder_path):
            if file.endswith('.png'):
                file_path = os.path.join(folder_path, file)
                if file.startswith('trade_'):
                    try:
                        trade_num = int(file.split('_')[1].split('.')[0])
                        results.append((file_path, f"Trade {trade_num}"))
                    except:
                        results.append((file_path, "Trade"))
                elif file.startswith('signal_chart_'):
                    results.append((file_path, "Signal Only"))

        # 排序：trade优先，按数字排序
        def sort_key(item):
            path, label = item
            filename = os.path.basename(path)
            if filename.startswith('trade_'):
                try:
                    num = int(filename.split('_')[1].split('.')[0])
                    return (0, num)
                except:
                    return (0, 999)
            else:
                return (1, 0)

        return sorted(results, key=sort_key)

    def create_comparison_chart(self, signal_date: str, stocks_info: List[Tuple[str, str]],
                                max_cols: int = 3) -> str:
        """
        为指定日期的股票创建对比图
        
        Args:
            signal_date: 信号日期
            stocks_info: [(股票代码, 股票名称), ...]
            max_cols: 每行最大列数
            
        Returns:
            生成的对比图文件路径
        """
        # 按涨幅排序：从信号日期到当前日期的涨幅，从大到小排序
        # 1. 获取当前最新交易日
        current_date = get_current_or_prev_trading_day(datetime.now().strftime("%Y%m%d"))
        if not current_date:
            logging.warning("无法获取当前交易日，使用信号日期作为结束日期")
            current_date = signal_date.replace("-", "")
        else:
            # 确保格式为 YYYYMMDD
            if "-" in current_date:
                current_date = current_date.replace("-", "")

        # 2. 转换信号日期格式 YYYY-MM-DD -> YYYYMMDD
        signal_date_yyyymmdd = signal_date.replace("-", "")

        # 3. 计算每只股票的涨幅并排序
        def get_stock_change(stock_info):
            """获取股票涨幅，用于排序"""
            stock_code, stock_name = stock_info

            # 如果信号日期就是当前日期，使用当天的涨跌幅（收盘价相对于开盘价）
            if signal_date_yyyymmdd == current_date:
                from utils.file_util import read_stock_data
                df = read_stock_data(stock_code)
                if df is None or df.empty:
                    return -999

                # 查找当天的数据
                date_fmt = f"{signal_date[:4]}-{signal_date[5:7]}-{signal_date[8:10]}"
                day_row = df[df['日期'] == date_fmt]

                if day_row.empty:
                    return -999

                open_price = day_row['开盘'].values[0]
                close_price = day_row['收盘'].values[0]

                if pd.isna(open_price) or pd.isna(close_price) or open_price <= 0 or close_price <= 0:
                    return -999

                # 计算当天涨跌幅
                daily_change = ((close_price / open_price) - 1) * 100
                return daily_change
            else:
                # 信号日期不是当天，使用累计涨跌幅
                change = calculate_stock_period_change(
                    stock_code,
                    signal_date_yyyymmdd,
                    current_date
                )
                # 如果计算失败，返回一个很小的值，确保排在最后
                return change if change is not None else -999

        # 按涨幅从大到小排序（涨幅相同时保持原顺序）
        stocks_info = sorted(stocks_info, key=get_stock_change, reverse=True)

        all_images = []
        stock_labels = []

        # 根据trade_log精确收集对应日期的图片
        for stock_code, stock_name in stocks_info:
            image_info_list = self.find_stock_trade_images_by_log(stock_code, signal_date)
            for img_path, img_type in image_info_list:
                all_images.append(img_path)
                label = f"{stock_code} {stock_name}\n({img_type})"
                stock_labels.append(label)

        if not all_images:
            logging.warning(f"日期 {signal_date} 没有找到任何图片")
            return None

        # 计算网格布局
        total_images = len(all_images)
        cols = min(max_cols, total_images)
        rows = (total_images + cols - 1) // cols

        # 创建图表
        fig_width = cols * 6  # 每个子图6英寸宽
        fig_height = rows * 4  # 每个子图4英寸高

        fig = plt.figure(figsize=(fig_width, fig_height))
        fig.suptitle(f'信号日期: {signal_date} 股票对比图 ({len(stocks_info)}只股票, {total_images}张图)',
                     fontsize=16, fontweight='bold')

        gs = GridSpec(rows, cols, figure=fig, hspace=0.3, wspace=0.2)

        for i, (img_path, label) in enumerate(zip(all_images, stock_labels)):
            try:
                row = i // cols
                col = i % cols

                ax = fig.add_subplot(gs[row, col])

                # 读取并显示图片
                img = mpimg.imread(img_path)
                ax.imshow(img)
                ax.set_title(label, fontsize=10, fontweight='bold', pad=10)
                ax.axis('off')

            except Exception as e:
                logging.error(f"加载图片 {img_path} 失败: {e}")
                continue

        # 保存对比图
        output_filename = f"comparison_{signal_date.replace('-', '')}.png"
        output_path = os.path.join(self.comparison_dir, output_filename)

        plt.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        plt.close()

        logging.info(f"生成对比图: {output_path}")
        return output_path

    def generate_recent_comparisons(self, summary_file_path: str, recent_days: int = 10):
        """
        生成最近n个日期的对比图
        
        Args:
            summary_file_path: scan_summary文件路径
            recent_days: 处理最近的天数
        """
        logging.info(f"开始生成最近 {recent_days} 个交易日的对比图...")

        # 解析summary文件
        date_stocks_map = self.parse_scan_summary(summary_file_path)

        if not date_stocks_map:
            logging.error("没有找到有效的股票信号数据")
            return

        # 按日期排序，取最近的n个日期
        sorted_dates = sorted(date_stocks_map.keys(), reverse=True)[:recent_days]

        generated_files = []

        for signal_date in sorted_dates:
            stocks_info = date_stocks_map[signal_date]
            logging.info(f"处理日期 {signal_date}: {len(stocks_info)} 只股票")

            output_path = self.create_comparison_chart(signal_date, stocks_info)
            if output_path:
                generated_files.append(output_path)

        logging.info(f"生成完成！共生成 {len(generated_files)} 张对比图")
        logging.info(f"对比图保存在: {self.comparison_dir}")

        return generated_files


def main():
    """主函数 - 演示用法"""
    # 自动查找最新的scan_summary文件
    base_dir = 'bin/candidate_stocks_result'
    summary_files = [f for f in os.listdir(base_dir) if f.startswith('scan_summary_') and f.endswith('.txt')]

    if not summary_files:
        print("没有找到scan_summary文件")
        return

    # 选择最新的summary文件
    latest_summary = sorted(summary_files)[-1]
    summary_path = os.path.join(base_dir, latest_summary)

    print(f"使用summary文件: {summary_path}")

    # 创建生成器并生成对比图
    generator = ComparisonChartGenerator(base_dir)
    generator.generate_recent_comparisons(summary_path, recent_days=10)


def run_auto_generation(base_dir: str, recent_days: int = 10) -> List[str]:
    """
    自动查找最新summary文件并生成对比图

    Args:
        base_dir: 扫描结果的基础目录
        recent_days: 生成最近几天的对比图

    Returns:
        生成的文件列表
    """
    # 自动查找最新的scan_summary文件
    summary_files = [f for f in os.listdir(base_dir) if f.startswith('scan_summary_') and f.endswith('.txt')]

    if not summary_files:
        print(f"在目录 {base_dir} 中没有找到scan_summary文件，请先运行扫描生成结果")
        return []

    # 选择最新的summary文件
    latest_summary = sorted(summary_files)[-1]
    summary_path = os.path.join(base_dir, latest_summary)

    print(f"使用summary文件: {summary_path}")

    # 创建生成器并生成对比图
    generator = ComparisonChartGenerator(base_dir)
    generated_files = generator.generate_recent_comparisons(summary_path, recent_days=recent_days)

    if generated_files:
        print(f"\n✅ 成功生成 {len(generated_files)} 张对比图")
        print(f"📁 对比图保存位置: {generator.comparison_dir}")
        print("\n生成的对比图:")
        for file in generated_files:
            print(f"  📊 {os.path.basename(file)}")
    else:
        print("❌ 没有生成任何对比图，请检查数据完整性")

    return generated_files


if __name__ == '__main__':
    main()
