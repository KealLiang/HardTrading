import csv
import logging
import os
from datetime import datetime

import backtrader as bt
import pandas as pd


class OrderLogger(bt.analyzers.Analyzer):
    """
    一个用于记录已完成订单到CSV文件的分析器。
    它会在指定路径下创建一个 trade_log.csv 文件，并记录每一笔成交的订单。
    """

    def __init__(self, log_path='trade_log.csv', signal_info=None):
        """
        初始化分析器。
        参数:
        - log_path: CSV日志文件的完整路径。
        - signal_info: 信号信息列表，每个元素包含date, type, details
        """
        self.log_path = log_path
        self.signal_info = signal_info or []
        # 确保目录存在
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        self.log_file = open(self.log_path, 'w', newline='')
        self.log_writer = csv.writer(self.log_file)
        # 写入表头，添加信号日期和交易编号
        self.log_writer.writerow(['datetime', 'type', 'size', 'price', 'symbol', 'signal_date', 'trade_num'])

        # 交易编号计数器
        self.trade_num = 0
        # 记录是否有交易发生
        self.has_trades = False

    def notify_order(self, order):
        """在订单状态改变时被调用"""
        if order.status == order.Completed:
            self.has_trades = True
            order_type = 'BUY' if order.isbuy() else 'SELL'
            dt = order.data.datetime.datetime(0).isoformat()
            symbol = order.data._name
            size = order.executed.size
            price = order.executed.price

            # 只有买入订单才增加交易编号（一对买卖算一次交易）
            if order.isbuy():
                self.trade_num += 1

            # 查找最近的信号日期
            signal_date = self._find_nearest_signal_date(order.data.datetime.datetime(0))

            self.log_writer.writerow([dt, order_type, size, price, symbol, signal_date, self.trade_num])

    def _find_nearest_signal_date(self, order_date):
        """找到离订单日期最近且在之前的信号日期"""
        if not self.signal_info:
            return ''

        order_date = pd.to_datetime(order_date).date()
        nearest_signal_date = ''
        min_diff = float('inf')

        for signal in self.signal_info:
            signal_date = pd.to_datetime(signal['date']).date()
            # 信号日期应该在订单日期之前或同一天
            if signal_date <= order_date:
                diff = (order_date - signal_date).days
                if diff < min_diff:
                    min_diff = diff
                    nearest_signal_date = signal_date.strftime('%Y-%m-%d')

        return nearest_signal_date

    def stop(self):
        """在回测结束时被调用"""
        # 记录signal_info中尚未记录到trade_log的信号
        if self.signal_info:
            # 先读取已有的trade_log记录，确定哪些信号已记录
            recorded_signals = set()
            try:
                # 先关闭当前文件，以便重新读取
                current_pos = self.log_file.tell()
                self.log_file.close()

                if os.path.exists(self.log_path):
                    existing_df = pd.read_csv(self.log_path)
                    if not existing_df.empty:
                        # 收集已记录的信号日期
                        for _, row in existing_df.iterrows():
                            if row.get('type') == 'SIGNAL' and not pd.isna(row.get('signal_date')):
                                recorded_signals.add(str(row['signal_date']))

                # 重新打开文件，追加模式
                self.log_file = open(self.log_path, 'a', newline='')
                self.log_writer = csv.writer(self.log_file)

            except Exception as e:
                logging.warning(f"读取已有交易日志失败: {e}，将记录所有信号")
                # 如果读取失败，重新打开文件继续
                try:
                    self.log_file = open(self.log_path, 'a', newline='')
                    self.log_writer = csv.writer(self.log_file)
                except:
                    pass

            # 记录尚未记录的信号
            for signal in self.signal_info:
                if signal.get('date'):
                    signal_date_str = pd.to_datetime(signal['date']).strftime('%Y-%m-%d')

                    # 只记录尚未记录过的信号
                    if signal_date_str not in recorded_signals:
                        # 获取symbol
                        symbol = ''
                        try:
                            strategy = self.strategy
                            if strategy and hasattr(strategy, 'datas') and strategy.datas:
                                symbol = strategy.datas[0]._name
                        except:
                            pass

                        self.log_writer.writerow([
                            pd.to_datetime(signal['date']).isoformat(),
                            'SIGNAL',
                            0,  # size
                            0,  # price
                            symbol,
                            signal_date_str,  # signal_date
                            0  # trade_num (信号不算交易)
                        ])
                        recorded_signals.add(signal_date_str)  # 避免重复记录

        self.log_file.close()
        print(f"交易日志已保存到: {self.log_path}")

    def get_analysis(self):
        """这个分析器直接写文件，不返回分析结果"""
        pass
