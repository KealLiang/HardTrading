"""
候选股历史记录追踪器
记录每次扫描的候选股票，用于长期跟踪和回顾分析
"""

import logging
import os
import re
from datetime import datetime
from typing import Dict

import pandas as pd

from utils.stock_util import format_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')


class SelectionHistoryTracker:
    """候选股历史记录追踪器"""

    def __init__(self, history_file: str = 'bin/candidate_history/selection_history.txt'):
        """
        初始化历史记录追踪器
        
        Args:
            history_file: 历史记录文件路径
        """
        self.history_file = history_file
        self._ensure_history_file()

    def _ensure_history_file(self):
        """确保历史记录文件和目录存在"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

        if not os.path.exists(self.history_file):
            # 创建带表头的CSV文件
            with open(self.history_file, 'w', encoding='utf-8') as f:
                f.write("执行时间|信号日期|模式|股票代码|股票名称|信号价格|评分|详情\n")
            logging.info(f"创建历史记录文件: {self.history_file}")

    def record_scan_results(self, summary_file: str, model: str):
        """
        记录一次扫描的结果到历史文件
        只记录扫描范围最后一日的候选股（因为是以那一天为截止日期的扫描）
        
        Args:
            summary_file: scan_summary文件路径
            model: 模式标识 (如 'rebound_a', 'breakout_a', 'breakout_b')
        """
        if not os.path.exists(summary_file):
            logging.warning(f"扫描摘要文件不存在: {summary_file}")
            return

        execution_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        records = []
        scan_end_date = None

        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 首先提取扫描范围的结束日期
            for line in lines:
                if line.startswith('扫描范围:'):
                    # 格式：扫描范围: 2025-07-30 to 2025-10-24
                    date_match = re.search(r'to\s+(\d{4}-\d{2}-\d{2})', line)
                    if date_match:
                        scan_end_date = date_match.group(1)
                        logging.info(f"识别扫描结束日期: {scan_end_date}")
                        break

            if not scan_end_date:
                logging.warning("未能从summary文件中提取扫描结束日期，将记录所有信号")

            for line in lines:
                # 跳过标题行和分隔线
                if line.strip() and not line.startswith('扫描策略') and \
                        not line.startswith('扫描范围') and not line.startswith('总计发现') and \
                        not line.startswith('-'):

                    # 解析格式：股票: 605289 罗曼股份, 信号日期: 2025-10-23, 价格: 70.06, 评分: 0，详情: ...
                    stock_match = re.search(r'股票:\s*(\d{6})\s*([^,]*)', line)
                    date_match = re.search(r'信号日期:\s*(\d{4}-\d{2}-\d{2})', line)
                    price_match = re.search(r'价格:\s*([\d.]+)', line)
                    score_match = re.search(r'评分:\s*([\d]+)', line)
                    details_match = re.search(r'详情:\s*(.+?)(?:\n|$)', line)

                    if stock_match and date_match and price_match:
                        code = stock_match.group(1)
                        name = stock_match.group(2).strip()
                        signal_date = date_match.group(1)

                        # 只记录扫描结束日期的信号（跳过其他日期的附带信号）
                        if scan_end_date and signal_date != scan_end_date:
                            continue

                        price = price_match.group(1)
                        score = score_match.group(1) if score_match else '0'
                        details = details_match.group(1).strip() if details_match else ''

                        # 去除详情中的分隔符，避免破坏CSV格式
                        details = details.replace('|', '｜')

                        records.append(
                            f"{execution_time}|{signal_date}|{model}|{code}|{name}|{price}|{score}|{details}\n")

            # 追加到历史文件
            if records:
                with open(self.history_file, 'a', encoding='utf-8') as f:
                    f.writelines(records)

                if scan_end_date:
                    logging.info(f"记录 {len(records)} 条候选股到历史文件 (模式: {model}, 信号日期: {scan_end_date})")
                else:
                    logging.info(f"记录 {len(records)} 条候选股到历史文件 (模式: {model})")
            else:
                if scan_end_date:
                    logging.warning(f"未从 {summary_file} 中解析到日期 {scan_end_date} 的有效记录")
                else:
                    logging.warning(f"未从 {summary_file} 中解析到有效记录")

        except Exception as e:
            logging.error(f"记录扫描结果失败: {e}")

    def load_history(self, start_date: str = None, end_date: str = None,
                     model: str = None) -> pd.DataFrame:
        """
        加载历史记录
        
        Args:
            start_date: 开始日期 (信号日期)，格式 'YYYY-MM-DD'
            end_date: 结束日期 (信号日期)，格式 'YYYY-MM-DD'
            model: 模式筛选，如 'rebound_a'
        
        Returns:
            DataFrame: 历史记录数据
        """
        if not os.path.exists(self.history_file):
            logging.warning("历史记录文件不存在")
            return pd.DataFrame()

        try:
            # 读取CSV文件，指定股票代码列为字符串类型
            df = pd.read_csv(self.history_file, sep='|', encoding='utf-8',
                             dtype={'股票代码': str})

            # 格式化股票代码，补全前导零
            df['股票代码'] = df['股票代码'].apply(format_stock_code)

            # 转换日期格式
            df['信号日期'] = pd.to_datetime(df['信号日期'])

            # 按日期筛选
            if start_date:
                df = df[df['信号日期'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['信号日期'] <= pd.to_datetime(end_date)]

            # 按模式筛选
            if model:
                df = df[df['模式'] == model]

            logging.info(f"加载历史记录: {len(df)} 条 (筛选条件: start={start_date}, end={end_date}, model={model})")

            return df

        except Exception as e:
            logging.error(f"加载历史记录失败: {e}")
            return pd.DataFrame()

    def get_statistics(self) -> Dict:
        """
        获取历史记录的统计信息
        
        Returns:
            统计信息字典
        """
        try:
            df = pd.read_csv(self.history_file, sep='|', encoding='utf-8',
                             dtype={'股票代码': str})
            df['股票代码'] = df['股票代码'].apply(format_stock_code)
            df['信号日期'] = pd.to_datetime(df['信号日期'])

            stats = {
                'total_records': len(df),
                'unique_stocks': df['股票代码'].nunique(),
                'models': df['模式'].value_counts().to_dict(),
                'date_range': (df['信号日期'].min().strftime('%Y-%m-%d'),
                               df['信号日期'].max().strftime('%Y-%m-%d')),
                'latest_execution': df['执行时间'].max()
            }

            return stats

        except Exception as e:
            logging.error(f"获取统计信息失败: {e}")
            return {}


def record_from_directory(base_dir: str, model: str):
    """
    从指定目录读取最新的scan_summary并记录
    
    Args:
        base_dir: 扫描结果目录
        model: 模式标识
    """
    tracker = SelectionHistoryTracker()

    # 查找最新的scan_summary文件
    try:
        summary_files = [f for f in os.listdir(base_dir)
                         if f.startswith('scan_summary_') and f.endswith('.txt')]

        if not summary_files:
            logging.warning(f"在 {base_dir} 中未找到scan_summary文件")
            return

        latest_summary = sorted(summary_files)[-1]
        summary_path = os.path.join(base_dir, latest_summary)

        tracker.record_scan_results(summary_path, model)

    except Exception as e:
        logging.error(f"从目录记录失败: {e}")


if __name__ == '__main__':
    # 测试代码
    tracker = SelectionHistoryTracker()

    # 测试记录
    print("测试记录功能...")
    record_from_directory('bin/candidate_stocks_rebound_a', 'rebound_a')

    # 测试加载
    print("\n测试加载功能...")
    df = tracker.load_history(start_date='2025-10-20')
    print(f"加载记录数: {len(df)}")
    if not df.empty:
        print(df.head())

    # 测试统计
    print("\n统计信息:")
    stats = tracker.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
