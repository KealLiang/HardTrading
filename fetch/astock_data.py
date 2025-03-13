import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import akshare as ak
import pandas as pd

from decorators.practical import timer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class StockDataFetcher:
    def __init__(self, start_date, end_date=None, save_path='./', max_workers=10):
        """
        初始化A股数据获取类。
        表头-> 日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']

        :param start_date: 数据的起始时间，格式为'YYYYMMDD'。
        :param end_date: 数据的结束时间，格式为'YYYYMMDD'，默认为当前日期。
        :param save_path: 数据保存的路径，默认为当前目录。
        """
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime('%Y%m%d')
        self.save_path = save_path
        self.max_workers = max_workers
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

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_single_stock,
                    stock_code,
                    stock_name
                ): (stock_code, stock_name)
                for stock_code, stock_name in stock_list
            }

            for future in as_completed(futures):
                stock_code, stock_name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error processing {stock_code}: {str(e)}")

    def _process_single_stock(self, stock_code, stock_name):
        """
        处理单只股票的数据获取和保存（线程安全）
        """
        try:
            stock_data = ak.stock_zh_a_hist(
                symbol=stock_code,
                start_date=self.start_date,
                end_date=self.end_date,
                adjust="qfq"
            )
            self._save_stock_data(stock_code, stock_name, stock_data)
        except Exception as e:
            raise RuntimeError(f"Failed to process {stock_code}: {str(e)}")

    def _save_stock_data(self, stock_code, stock_name, stock_data):
        """
        线程安全的股票数据保存方法
        """
        safe_name = stock_name.replace('*ST', 'xST').replace('/', '_')
        file_name = f"{stock_code}_{safe_name}.csv"
        file_path = os.path.join(self.save_path, file_name)

        if os.path.exists(file_path):
            self._append_new_data(file_path, stock_data)
        else:
            self._create_new_file(file_path, stock_data)

    def _append_new_data(self, file_path, new_data):
        """
        追加新数据到现有文件
        """
        try:
            # 读取现有文件的最后一行的日期
            last_date_df = pd.read_csv(file_path, header=None, usecols=[0])
            last_date = last_date_df.iloc[-1][0]

            # 过滤新数据中日期大于最后日期的部分
            if not new_data.empty:
                filtered_data = new_data[new_data['日期'] > pd.to_datetime(last_date).date()]
            else:
                filtered_data = new_data

            if not filtered_data.empty:
                # 追加新数据
                filtered_data.to_csv(file_path, mode='a', header=False, index=False)
                logging.info(f"Appended {len(filtered_data)} rows to {os.path.basename(file_path)}")
        except pd.errors.EmptyDataError:
            logging.warning(f"Empty file detected, overwriting {file_path}")
            self._create_new_file(file_path, new_data)

    def _create_new_file(self, file_path, data):
        """
        创建新数据文件
        """
        data.to_csv(file_path, index=False, header=False)
        logging.info(f"Created new file: {os.path.basename(file_path)}")


class StockDataBroker:
    def __init__(self, save_path='./'):
        """
        股票数据经纪人
        用于拉取，保存，获取{code},{name}的股票数据
        """
        self.save_path = save_path

    @timer
    def get_a_stock_info(self):
        """
        获取A股所有股票的代码和名称，并保存到CSV文件中
        """
        stock_df = ak.stock_info_a_code_name()
        # 按照要求对股票代码格式进行转换
        for i in range(0, len(stock_df)):
            temp = stock_df.iloc[i, 0]
            if temp[0] == "6":
                temp = "sh" + temp
            elif temp[0] == "0" or temp[0] == "3":
                temp = "sz" + temp
            stock_df.iloc[i, 0] = temp

        # 去掉股票名称中间的空格
        stock_df["name"] = stock_df["name"].apply(lambda x: x.replace(" ", ""))
        stock_df.to_csv(f"{self.save_path}stock_mapping.csv", index=False, header=["code", "name"])
        return stock_df

    def get_name_by_code(self, seek_code):
        """
        通过股票代码获取股票名称
        股票代码 sh600519 对应的名称是: 贵州茅台
        """
        stock_df = pd.read_csv(f"{self.save_path}/stock_mapping.csv")
        result = stock_df.loc[stock_df["code"] == seek_code, "name"].values
        if len(result) > 0:
            return result[0]
        return None

    def get_code_by_name(self, seek_name):
        """
        通过股票名称获取股票代码
        股票名称 贵州茅台 对应的代码是: sh600519
        """
        stock_df = pd.read_csv(f"{self.save_path}stock_mapping.csv")
        result = stock_df.loc[stock_df["name"] == seek_name, "code"].values
        if len(result) > 0:
            return result[0]
        return None


# 使用示例
if __name__ == "__main__":
    # 获取A股股票信息并保存文件
    stock_broker = StockDataBroker()
    # stock_broker.get_a_stock_info()
    # 示例：通过代码获取名称
    code = "sh600519"
    name = stock_broker.get_name_by_code(code)
    print(f"股票代码 {code} 对应的名称是: {name}")
    # 示例：通过名称获取代码
    name = "贵州茅台"
    code = stock_broker.get_code_by_name(name)
    print(f"股票名称 {name} 对应的代码是: {code}")

    # 创建数据获取对象（设置线程数为2）
    data_fetcher = StockDataFetcher(
        start_date='20241206',
        end_date='20241207',
        save_path='./stock_data',
        max_workers=2  # 可根据网络环境和硬件配置调整
    )
    data_fetcher.fetch_and_save_data()
