import logging
import os
import random
import time
import threading
import winsound
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import akshare as ak
import pandas as pd

from decorators.practical import timer
from utils.date_util import get_trading_days, format_date

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class StockDataFetcher:
    def __init__(self, start_date, end_date=None, save_path='./', max_workers=10, force_update=False, max_sleep_time=2):
        """
        初始化A股数据获取类。
        表头-> 日期,股票代码,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']

        :param start_date: 数据的起始时间，格式为'YYYYMMDD'。
        :param end_date: 数据的结束时间，格式为'YYYYMMDD'，默认为当前日期。
        :param save_path: 数据保存的路径，默认为当前目录。
        :param max_workers: 最大线程数，默认为10。
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
        
        # 添加暂停标志，用于在遇到验证码时暂停所有线程
        self.pause_flag = threading.Event()
        self.pause_flag.set()  # 初始状态为不暂停
        
        # 添加锁，确保只有一个线程会触发验证处理
        self.verification_lock = threading.Lock()
        
        # 标记是否正在处理验证，使用类变量确保全局可见
        self._verification_in_progress = False
        
        # 添加一个计数器，跟踪已完成的任务数量
        self.completed_tasks = 0
        self.total_tasks = 0
        self.task_lock = threading.Lock()
        
        if self.force_update:
            logging.info("强制更新模式已启用，将覆盖指定日期范围内的所有数据")

    @timer
    def fetch_and_save_data(self):
        """
        获取所有A股股票的每日数据，并保存到CSV文件。
        """
        # 获取所有A股股票代码和名称
        try:
            stock_real_time = ak.stock_zh_a_spot_em()
            stock_list = stock_real_time[['代码', '名称']].values.tolist()
        except Exception as e:
            logging.error(f"获取股票列表失败: {str(e)}")
            self._handle_verification_needed("获取股票列表时可能需要验证")
            # 重新尝试获取股票列表
            stock_real_time = ak.stock_zh_a_spot_em()
            stock_list = stock_real_time[['代码', '名称']].values.tolist()
        
        # 设置总任务数
        self.total_tasks = len(stock_list)
        logging.info(f"开始处理 {self.total_tasks} 只股票数据")
        
        # 在开始处理前暂停，等待用户确认
        self._pause_for_confirmation("按回车键开始处理...", use_beep=False)

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
                    # 更新完成任务计数
                    with self.task_lock:
                        self.completed_tasks += 1
                        if self.completed_tasks % 50 == 0:
                            logging.info(f"已完成 {self.completed_tasks}/{self.total_tasks} 只股票数据处理")
                except Exception as e:
                    error_msg = str(e)
                    print(f"Error processing {stock_code}: {error_msg}")
                    
                    # 检查是否是连接中断错误，这可能是由于需要验证码
                    if "Connection aborted" in error_msg or "RemoteDisconnected" in error_msg:
                        self._trigger_verification(f"处理股票 {stock_code}({stock_name}) 时连接中断")
        
        logging.info(f"所有股票数据处理完成，共 {self.completed_tasks}/{self.total_tasks} 只")

    def _trigger_verification(self, message):
        """
        触发验证处理，使用全局锁确保只有一个线程能触发
        """
        # 使用锁确保只有一个线程会触发验证处理
        if not self._verification_in_progress:  # 先检查一次，避免不必要的锁竞争
            with self.verification_lock:
                # 双重检查，确保在获取锁的过程中状态没有被改变
                if not self._verification_in_progress:
                    self._verification_in_progress = True
                    self._handle_verification_needed(message)

    def _pause_for_confirmation(self, message, use_beep=True):
        """
        暂停并等待用户确认
        
        :param message: 显示给用户的消息
        :param use_beep: 是否发出声音提醒
        """
        if use_beep:
            self._play_beep()
        
        logging.info(message)
        input(message)
        logging.info("继续执行...")

    def _play_beep(self):
        """
        发出声音提醒
        """
        try:
            winsound.Beep(1000, 500)  # 1000Hz, 持续500毫秒
            winsound.Beep(1500, 500)  # 1500Hz, 持续500毫秒
        except:
            # 如果不支持声音，则忽略错误
            pass

    def _handle_verification_needed(self, message):
        """
        处理需要验证的情况：暂停所有线程，发出声音提醒，等待用户处理
        """
        # 设置暂停标志，所有线程将在检查点等待
        self.pause_flag.clear()
        
        # 发出声音提醒
        self._play_beep()
        
        logging.warning(f"检测到可能需要验证码: {message}")
        logging.warning("请打开浏览器访问东方财富网（如：https://quote.eastmoney.com/concept/sh603777.html?from=classic）完成验证操作")
        
        self._pause_for_confirmation("完成验证后请按回车键继续...", use_beep=False)
        
        # 恢复运行
        self.pause_flag.set()
        self._verification_in_progress = False
        
        logging.info("已恢复数据获取")

    def _process_single_stock(self, stock_code, stock_name):
        """
        处理单只股票的数据获取和保存（线程安全）
        """
        try:
            # 检查是否需要获取数据
            if not self._need_update(stock_code, stock_name):
                logging.info(f"股票 {stock_code}({stock_name}) 不需要更新数据")
                return
            
            # 检查是否为退市股票，如果是则直接跳过
            if '退' in stock_name:
                logging.info(f"股票 {stock_code}({stock_name}) 为退市股票，跳过数据获取")
                return
                
            # 在每次请求前检查是否需要暂停
            self._wait_if_paused()
                
            # 添加随机休眠以避免请求过于频繁被限制
            sleep_time = random.uniform(0, self.max_sleep_time)
            time.sleep(sleep_time / 1000.0)
            
            stock_data = self._fetch_stock_data(stock_code)
            
            # 检查返回的数据是否为空
            if stock_data.empty:
                logging.info(f"股票 {stock_code}({stock_name}) 没有返回数据，可能是新股或已退市，跳过")
                return
                
            self._save_stock_data(stock_code, stock_name, stock_data)
        except Exception as e:
            raise RuntimeError(f"Failed to process {stock_code}: {str(e)}")
    
    def _fetch_stock_data(self, stock_code):
        """
        获取股票数据，封装为单独方法便于后续扩展或修改
        
        :param stock_code: 股票代码
        :return: 股票数据DataFrame
        """
        return ak.stock_zh_a_hist(
            symbol=stock_code,
            start_date=self.start_date,
            end_date=self.end_date,
            adjust="qfq"
        )
    
    def _wait_if_paused(self):
        """
        检查是否需要暂停，如果需要则等待
        """
        self.pause_flag.wait()
            
    def _need_update(self, stock_code, stock_name):
        """
        判断是否需要更新数据
        
        :param stock_code: 股票代码
        :param stock_name: 股票名称
        :return: 是否需要更新数据
        """
        # 在每次检查前检查是否需要暂停
        self._wait_if_paused()
        
        # 强制更新模式下始终返回True
        if self.force_update:
            return True
            
        safe_name = self._get_safe_file_name(stock_name)
        file_name = f"{stock_code}_{safe_name}.csv"
        file_path = os.path.join(self.save_path, file_name)
        
        # 如果文件不存在，需要更新
        if not os.path.exists(file_path):
            return True
            
        try:
            # 读取现有文件的所有数据
            existing_data = pd.read_csv(file_path, header=None,
                                    names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                           '振幅', '涨跌幅', '涨跌额', '换手率'])

            # 确保日期列是日期类型
            existing_data['日期'] = pd.to_datetime(existing_data['日期'])
            
            # 获取现有数据的日期范围
            existing_dates = set(existing_data['日期'].dt.strftime('%Y-%m-%d'))
            
            # 检查交易日是否都已存在
            formatted_trading_days = [format_date(day) for day in self.trading_days]
            missing_days = [day for day in formatted_trading_days if day not in existing_dates]
            
            # 如果有缺失的交易日，需要更新
            return len(missing_days) > 0
            
        except Exception as e:
            logging.warning(f"检查 {file_path} 是否需要更新时出错: {str(e)}")
            # 出错时保守处理，返回需要更新
            return True

    def _get_safe_file_name(self, stock_name):
        """
        获取安全的文件名，替换特殊字符
        
        :param stock_name: 股票名称
        :return: 安全的文件名
        """
        return stock_name.replace('*ST', 'xST').replace('/', '_')

    def _save_stock_data(self, stock_code, stock_name, stock_data):
        """
        线程安全的股票数据保存方法
        """
        # 在保存前检查是否需要暂停
        self._wait_if_paused()
        
        safe_name = self._get_safe_file_name(stock_name)
        file_name = f"{stock_code}_{safe_name}.csv"
        file_path = os.path.join(self.save_path, file_name)

        if os.path.exists(file_path):
            self._append_new_data(file_path, stock_data)
        else:
            self._create_new_file(file_path, stock_data)

    def _append_new_data(self, file_path, new_data):
        """
        追加新数据到现有文件，并处理缺失的日期数据
        """
        try:
            # 读取现有文件的所有数据
            existing_data = pd.read_csv(file_path, header=None,
                                        names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                               '振幅', '涨跌幅', '涨跌额', '换手率'])

            # 确保日期列是日期类型
            existing_data['日期'] = pd.to_datetime(existing_data['日期'])
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
                combined_data.to_csv(file_path, index=False, header=False)
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
        max_workers=2,  # 可根据网络环境和硬件配置调整
        force_update=False,  # 是否强制更新已有日期的数据
        max_sleep_time=2  # 随机休眠的最大毫秒数
    )
    data_fetcher.fetch_and_save_data()
