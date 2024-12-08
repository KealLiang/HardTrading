import os
from datetime import datetime, timedelta

import akshare as ak

from decorators.practical import timer


class AStockDataFetcher:
    def __init__(self, start_date, end_date=None, save_path='./'):
        """
        初始化A股数据获取类。
        表头-> 日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']

        :param start_date: 数据的起始时间，格式为'YYYYMMDD'。
        :param end_date: 数据的结束时间，格式为'YYYYMMDD'，默认为当前日期。
        :param save_path: 数据保存的路径，默认为当前目录。
        """
        self.start_date = start_date
        if end_date is None:
            self.end_date = datetime.now().strftime('%Y%m%d')
        else:
            self.end_date = end_date
        self.save_path = save_path
        # 确保保存路径存在
        os.makedirs(self.save_path, exist_ok=True)

    @timer
    def fetch_and_save_data(self):
        """
        获取所有A股股票的每日数据，并保存到CSV文件。
        """
        # 获取所有A股股票代码和名称
        stock_real_time = ak.stock_zh_a_spot_em()
        stock_list = stock_real_time[['代码', '名称']].values.tolist()

        # 遍历每只股票，获取数据并保存到CSV文件
        for stock_code, stock_name in stock_list:
            try:
                # 获取股票历史行情数据
                stock_data = ak.stock_zh_a_hist(symbol=stock_code, start_date=self.start_date, end_date=self.end_date,
                                                adjust="qfq")
                # 替换文件名中的特殊字符
                safe_stock_name = stock_name.replace('*ST', 'xST')
                # 保存数据到CSV文件
                file_name = f"{stock_code}_{safe_stock_name}.csv"
                file_path = os.path.join(self.save_path, file_name)
                stock_data.to_csv(file_path, index=False, header=False)
                print(f"Saved {file_path}")
            except Exception as e:
                print(f"Error processing {stock_code}: {e}")


# 使用示例
if __name__ == "__main__":
    # 创建A股数据获取对象，指定数据的起始时间、结束时间和保存路径
    data_fetcher = AStockDataFetcher(start_date='20241206', end_date='20241207', save_path='./stock_data')
    # 执行数据获取和保存操作
    data_fetcher.fetch_and_save_data()
