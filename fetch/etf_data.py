import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import akshare as ak
import pandas as pd

from decorators.practical import timer
from utils.date_util import get_trading_days, format_date


class ETFDataFetcher:
    def __init__(self, start_date, end_date=None, save_path='./data/etfs', max_workers=8, 
                 force_update=False, max_sleep_time=2000):
        """
        初始化ETF数据获取类。
        
        :param start_date: 数据的起始时间，格式为'YYYYMMDD'。
        :param end_date: 数据的结束时间，格式为'YYYYMMDD'，默认为当前日期。
        :param save_path: 数据保存的路径，默认为'./data/etfs'。
        :param max_workers: 最大线程数，默认为8。
        :param force_update: 是否强制更新已有日期的数据，默认为False。
        :param max_sleep_time: 随机休眠的最大毫秒数，用于避免请求过于频繁。
        """
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime('%Y%m%d')
        self.save_path = save_path
        self.max_workers = max_workers
        self.force_update = force_update
        self.max_sleep_time = max_sleep_time
        
        # 确保保存路径存在
        os.makedirs(self.save_path, exist_ok=True)
        
        # 获取交易日列表
        self.trading_days = get_trading_days(self.start_date, self.end_date)
        
        # 添加一个计数器，跟踪已完成的任务数量
        self.completed_tasks = 0
        self.total_tasks = 0
        
        if self.force_update:
            logging.info("强制更新模式已启用，将覆盖指定日期范围内的所有数据")
    
    @timer
    def fetch_and_save_data(self, etf_list):
        """
        获取ETF的每日数据，并保存到CSV文件。
        
        :param etf_list: ETF代码列表，必须提供
        """
        if not etf_list or len(etf_list) == 0:
            logging.error("ETF列表为空，请提供有效的ETF代码列表")
            return
        
        # 设置总任务数
        self.total_tasks = len(etf_list)
        logging.info(f"开始处理 {self.total_tasks} 只ETF数据")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_single_etf,
                    etf_code
                ): etf_code
                for etf_code in etf_list
            }
            
            for future in as_completed(futures):
                etf_code = futures[future]
                try:
                    future.result()
                    # 更新完成任务计数
                    self.completed_tasks += 1
                    if self.completed_tasks % 10 == 0:
                        logging.info(f"已完成 {self.completed_tasks}/{self.total_tasks} 只ETF数据处理")
                except Exception as e:
                    error_msg = str(e)
                    logging.warning(f"Error processing ETF {etf_code}: {error_msg}")
        
        logging.info(f"所有ETF数据处理完成，共 {self.completed_tasks}/{self.total_tasks} 只")
    
    def _process_single_etf(self, etf_code):
        """
        处理单只ETF的数据获取和保存
        
        :param etf_code: ETF代码
        """
        try:
            # 检查是否需要获取数据
            if not self._need_update(etf_code):
                logging.info(f"ETF {etf_code} 不需要更新数据")
                return
            
            # 添加随机休眠以避免请求过于频繁被限制
            sleep_time = random.uniform(0, self.max_sleep_time)
            time.sleep(sleep_time / 1000.0)
            
            etf_data = self._fetch_etf_data(etf_code)
            
            # 检查返回的数据是否为空
            if etf_data.empty:
                logging.info(f"ETF {etf_code} 没有返回数据，可能是新上市或已退市，跳过")
                return
            
            self._save_etf_data(etf_code, etf_data)
        except Exception as e:
            raise RuntimeError(f"Failed to process ETF {etf_code}: {str(e)}")
    
    def _fetch_etf_data(self, etf_code):
        """
        获取ETF数据
        
        :param etf_code: ETF代码
        :return: ETF数据DataFrame
        """
        return ak.fund_etf_hist_em(
            symbol=etf_code,
            period="daily",
            start_date=self.start_date,
            end_date=self.end_date,
            adjust="qfq"  # 前复权数据
        )
    
    def _need_update(self, etf_code):
        """
        判断是否需要更新数据
        
        :param etf_code: ETF代码
        :return: 是否需要更新数据
        """
        # 强制更新模式下始终返回True
        if self.force_update:
            return True
        
        # 查找匹配ETF代码的文件
        file_path = os.path.join(self.save_path, f"{etf_code}.csv")
        
        # 如果没有匹配的文件，需要更新
        if not os.path.exists(file_path):
            return True
        
        try:
            # 读取现有文件的所有数据
            existing_data = pd.read_csv(file_path, parse_dates=['日期'])
            
            # 获取现有数据的日期范围
            existing_dates = set(existing_data['日期'].dt.strftime('%Y-%m-%d'))
            
            # 检查交易日是否都已存在
            formatted_trading_days = [format_date(day) for day in self.trading_days]
            missing_days = [day for day in formatted_trading_days if day not in existing_dates]
            
            # 如果没有缺失的交易日，不需要更新
            if len(missing_days) == 0:
                return False
        
        except Exception as e:
            logging.warning(f"检查 {file_path} 是否需要更新时出错: {str(e)}")
        
        # 需要更新
        return True
    
    def _save_etf_data(self, etf_code, etf_data):
        """
        保存ETF数据
        
        :param etf_code: ETF代码
        :param etf_data: ETF数据DataFrame
        """
        file_path = os.path.join(self.save_path, f"{etf_code}.csv")
        
        # 检查是否已存在文件
        if os.path.exists(file_path):
            # 如果存在，追加新数据
            self._append_new_data(file_path, etf_data)
        else:
            # 不存在，创建新文件
            self._create_new_file(file_path, etf_data)
    
    def _append_new_data(self, file_path, new_data):
        """
        追加新数据到现有文件，并处理缺失的日期数据
        
        :param file_path: 文件路径
        :param new_data: 新数据DataFrame
        """
        try:
            # 读取现有文件的所有数据
            existing_data = pd.read_csv(file_path, parse_dates=['日期'])
            
            # 确保日期列是日期类型
            new_data['日期'] = pd.to_datetime(new_data['日期'])
            
            # 获取新数据的日期范围
            new_data_dates = set(new_data['日期'].dt.strftime('%Y-%m-%d'))
            
            if self.force_update:
                # 强制更新模式：删除现有数据中与新数据日期重叠的记录
                existing_data = existing_data[~existing_data['日期'].dt.strftime('%Y-%m-%d').isin(new_data_dates)]
                missing_data = new_data  # 所有新数据都将被添加
                update_message = f"强制更新了 {len(new_data_dates)} 个日期的数据"
            else:
                # 常规模式：只添加缺失的日期数据
                existing_dates = set(existing_data['日期'].dt.strftime('%Y-%m-%d'))
                # 筛选出新数据中不存在于现有数据的日期记录
                missing_data = new_data[~new_data['日期'].dt.strftime('%Y-%m-%d').isin(existing_dates)]
                update_message = f"更新了 {len(missing_data)} 条缺失的记录"
            
            if not missing_data.empty or (self.force_update and not new_data.empty):
                # 将现有数据和新数据合并
                combined_data = pd.concat([existing_data, missing_data])
                # 按日期排序
                combined_data = combined_data.sort_values(by='日期')
                # 重写整个文件
                combined_data.to_csv(file_path, index=False)
                logging.info(f"已更新 {os.path.basename(file_path)}: {update_message}")
            else:
                logging.info(f"没有新数据需要更新：{os.path.basename(file_path)}")
        
        except pd.errors.EmptyDataError:
            logging.warning(f"检测到空文件，重写 {file_path}")
            self._create_new_file(file_path, new_data)
        except Exception as e:
            logging.error(f"更新 {file_path} 时出错: {str(e)}")
            # 如果出错，尝试创建新文件
            self._create_new_file(file_path, new_data)
    
    def _create_new_file(self, file_path, data):
        """
        创建新数据文件
        
        :param file_path: 文件路径
        :param data: 数据DataFrame
        """
        data.to_csv(file_path, index=False)
        logging.info(f"Created new file: {os.path.basename(file_path)}")


# 使用示例
if __name__ == "__main__":
    # 创建ETF数据获取对象
    etf_fetcher = ETFDataFetcher(
        start_date='20260120',
        end_date='20260210',
        save_path='./data/etfs',
        max_workers=4,
        force_update=False,
        max_sleep_time=2000
    )
    
    # 指定要获取的ETF代码列表
    etf_codes = ['510300', '518880']
    
    # 获取并保存数据
    etf_fetcher.fetch_and_save_data(etf_codes)

