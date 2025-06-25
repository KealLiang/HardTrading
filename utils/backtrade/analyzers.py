import csv
import os

import backtrader as bt


class OrderLogger(bt.analyzers.Analyzer):
    """
    一个用于记录已完成订单到CSV文件的分析器。
    它会在指定路径下创建一个 trade_log.csv 文件，并记录每一笔成交的订单。
    """

    def __init__(self, log_path='trade_log.csv'):
        """
        初始化分析器。
        参数:
        - log_path: CSV日志文件的完整路径。
        """
        self.log_path = log_path
        # 确保目录存在
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        self.log_file = open(self.log_path, 'w', newline='')
        self.log_writer = csv.writer(self.log_file)
        # 写入表头
        self.log_writer.writerow(['datetime', 'type', 'size', 'price', 'symbol'])

    def notify_order(self, order):
        """在订单状态改变时被调用"""
        if order.status == order.Completed:
            order_type = 'BUY' if order.isbuy() else 'SELL'
            dt = order.data.datetime.datetime(0).isoformat()
            symbol = order.data._name
            size = order.executed.size
            price = order.executed.price
            self.log_writer.writerow([dt, order_type, size, price, symbol])

    def stop(self):
        """在回测结束时被调用"""
        self.log_file.close()
        print(f"交易日志已保存到: {self.log_path}")

    def get_analysis(self):
        """这个分析器直接写文件，不返回分析结果"""
        pass
