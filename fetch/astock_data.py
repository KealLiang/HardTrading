import logging
import os
import random
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import akshare as ak
import pandas as pd
import winsound

from decorators.practical import timer
from utils.captcha_solver import solve_captcha  # 导入验证码解决函数
from utils.date_util import get_trading_days, format_date
from utils.file_util import find_all_stock_files
from utils.stock_util import convert_stock_code


def auto_captcha_solve(verification_url):
    """
    自动处理验证码

    :param verification_url: 验证页面URL
    :return: 是否成功解决验证码
    """
    logging.info(f"正在尝试自动解决验证码: {verification_url}")
    auto_success = False
    try:
        auto_success = solve_captcha(verification_url, max_retry=3, headless=False)
        if auto_success:
            logging.info("自动验证成功!")
        else:
            logging.warning("自动验证失败，需要手动验证")
    except Exception as e:
        logging.error(f"自动验证过程中出错: {str(e)}")
    return auto_success


class StockDataFetcher:
    def __init__(self, start_date, end_date=None, save_path='./', max_workers=10, force_update=False, max_sleep_time=2,
                 enable_auto_captcha=False, stock_list=None):
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
        :param enable_auto_captcha: 是否启用自动验证码解决功能，默认为False（使用人工解决）。
        :param stock_list: 指定要获取的股票列表，默认为None表示获取所有股票。
        """
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime('%Y%m%d')
        self.save_path = save_path
        self.max_workers = max_workers
        self.force_update = force_update
        self.max_sleep_time = max_sleep_time
        self.enable_auto_captcha = enable_auto_captcha
        self.stock_list = stock_list
        # 确保保存路径存在
        os.makedirs(self.save_path, exist_ok=True)

        # 获取交易日列表
        self.trading_days = get_trading_days(self.start_date, self.end_date)

        # 添加暂停标志，用于在遇到验证码时暂停所有线程
        self.pause_flag = threading.Event()
        self.pause_flag.set()  # 初始状态为不暂停

        # 添加一个计数器，跟踪已完成的任务数量
        self.completed_tasks = 0
        self.total_tasks = 0
        self.task_lock = threading.Lock()

        if self.force_update:
            logging.info("强制更新模式已启用，将覆盖指定日期范围内的所有数据")

        if self.enable_auto_captcha:
            logging.info("自动验证码解决功能已启用")

    @timer
    def fetch_and_save_data(self, stock_list=None):
        """
        获取A股股票的每日数据，并保存到CSV文件。
        
        :param stock_list: 指定要获取的股票列表，默认为None表示使用初始化时设置的列表
        """
        # 使用传入的stock_list或初始化时设置的列表
        target_stocks = stock_list or self.stock_list

        # 获取股票代码和名称
        try:
            stock_real_time = ak.stock_zh_a_spot_em()
            all_stocks = stock_real_time[['代码', '名称']].values.tolist()

            # 如果有指定股票列表，筛选出目标股票
            if target_stocks:
                stock_list = [stock for stock in all_stocks if stock[0] in target_stocks]
                if len(stock_list) < len(target_stocks):
                    missing = set(target_stocks) - set([s[0] for s in stock_list])
                    logging.warning(f"未找到以下股票: {missing}")
            else:
                stock_list = all_stocks
        except Exception as e:
            logging.error(f"获取股票列表失败: {str(e)}")
            self._handle_verification_needed("获取股票列表时可能需要验证")
            # 重新尝试获取股票列表
            stock_real_time = ak.stock_zh_a_spot_em()
            all_stocks = stock_real_time[['代码', '名称']].values.tolist()
            if target_stocks:
                stock_list = [stock for stock in all_stocks if stock[0] in target_stocks]
            else:
                stock_list = all_stocks

        # 设置总任务数
        self.total_tasks = len(stock_list)
        logging.info(f"开始处理 {self.total_tasks} 只股票数据")

        # 在开始处理前暂停，等待用户确认
        self._pause_for_confirmation("按回车键开始处理...")

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
                    logging.warning(f"Error processing {stock_code}: {error_msg}")

                    # 检查是否是连接中断错误，这可能是由于需要验证码
                    if "Connection aborted" in error_msg or "RemoteDisconnected" in error_msg:
                        self._trigger_verification(f"处理股票 {stock_code}({stock_name}) 时连接中断")

        logging.info(f"所有股票数据处理完成，共 {self.completed_tasks}/{self.total_tasks} 只")

    def _trigger_verification(self, message):
        """
        触发验证处理，无需加锁，此处为主线程串行处理
        """
        current_time = time.time()
        # 检查是否最近已经触发过验证
        if hasattr(self, '_last_verification_time') and (current_time - self._last_verification_time) < 30:
            logging.info(f"最近已经处理过验证，跳过重复验证: {message}")
            return
        # 处理验证
        self._handle_verification_needed(message)
        # 更新最后验证时间
        self._last_verification_time = current_time

    def _pause_for_confirmation(self, message):
        """
        暂停并等待用户确认
        
        :param message: 显示给用户的消息
        """
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
        处理需要验证的情况：暂停所有线程，尝试自动完成验证，如果失败则等待用户处理
        """
        # 设置暂停标志，所有线程将在检查点等待
        self.pause_flag.clear()

        # 发出声音提醒
        self._play_beep()

        logging.warning(f"检测到可能需要验证码: {message}")

        # 提取股票代码，用于生成验证URL
        verification_code = "sh603777"  # 默认代码

        # 从消息中提取股票代码 "处理股票 600519(贵州茅台) 时连接中断"
        code_match = re.search(r'股票\s+(\d{6})', message)
        if code_match:
            try:
                raw_code = code_match.group(1)
                verification_code = convert_stock_code(raw_code)
            except:
                pass

        verification_url = f"https://quote.eastmoney.com/concept/{verification_code}.html?from=classic"

        # 判断是否启用自动验证码解决
        auto_success = False
        if self.enable_auto_captcha:
            auto_success = auto_captcha_solve(verification_url)

        # 如果自动验证功能未启用或自动验证失败，回退到手动验证
        if not auto_success:
            logging.warning(f"请打开浏览器访问东方财富网: {verification_url} 完成验证操作")
            self._pause_for_confirmation("完成验证后请按回车键继续...")

        # 恢复运行
        self.pause_flag.set()

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

        # 查找匹配股票代码的所有文件
        existing_files = self._find_files_by_code(stock_code)

        # 如果没有匹配的文件，需要更新
        if not existing_files:
            return True

        # 检查所有匹配的文件，看是否有完整数据
        for filename in existing_files:
            file_path = os.path.join(self.save_path, filename)

            try:
                # 读取现有文件的所有数据
                existing_data = pd.read_csv(file_path, header=None,
                                            names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量',
                                                   '成交额',
                                                   '振幅', '涨跌幅', '涨跌额', '换手率'],
                                            dtype={'股票代码': str})

                # 确保日期列是日期类型
                existing_data['日期'] = pd.to_datetime(existing_data['日期'])

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
                # 单个文件检查出错，继续检查其他文件
                continue

        # 所有文件都检查完，仍需要更新
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
        股票代码相同的数据保存到同一文件，文件名使用最新的股票名称
        """
        # 在保存前检查是否需要暂停
        self._wait_if_paused()

        # 确保股票代码始终以字符串形式保存，防止前导零丢失
        if '股票代码' in stock_data.columns:
            stock_data['股票代码'] = stock_data['股票代码'].astype(str)

        # 检查是否已存在同代码的文件
        existing_files = self._find_files_by_code(stock_code)

        if existing_files:
            # 如果存在同代码文件，处理文件更新和可能的文件名更新
            self._handle_existing_files(existing_files, stock_code, stock_name, stock_data)
        else:
            # 不存在同代码文件，创建新文件
            safe_name = self._get_safe_file_name(stock_name)
            file_name = f"{stock_code}_{safe_name}.csv"
            file_path = os.path.join(self.save_path, file_name)
            self._create_new_file(file_path, stock_data)

    def _find_files_by_code(self, stock_code):
        """
        根据股票代码查找已存在的文件
        
        :param stock_code: 股票代码
        :return: 匹配的文件列表
        """
        # 使用file_util中的公共方法查找所有匹配的文件
        all_file_paths = find_all_stock_files(stock_code, self.save_path)

        # 只返回文件名而非完整路径
        return [os.path.basename(path) for path in all_file_paths]

    def _handle_existing_files(self, existing_files, stock_code, stock_name, new_data):
        """
        处理已存在的同代码文件
        
        :param existing_files: 同代码的现有文件列表
        :param stock_code: 股票代码
        :param stock_name: 最新的股票名称
        :param new_data: 新数据
        """
        # 获取安全的最新文件名
        safe_name = self._get_safe_file_name(stock_name)
        target_file_name = f"{stock_code}_{safe_name}.csv"
        target_file_path = os.path.join(self.save_path, target_file_name)

        # 检查目标文件名是否已存在
        target_exists = target_file_name in existing_files

        if len(existing_files) == 1:
            existing_file = existing_files[0]
            existing_path = os.path.join(self.save_path, existing_file)

            if existing_file == target_file_name:
                # 文件名未变化，直接追加新数据
                self._append_new_data(existing_path, new_data)
            else:
                # 文件名需要更新，先追加数据，再重命名
                self._append_new_data(existing_path, new_data)
                try:
                    # 确保目标文件不存在
                    if os.path.exists(target_file_path) and existing_path != target_file_path:
                        os.remove(target_file_path)
                    # 重命名文件
                    os.rename(existing_path, target_file_path)
                    logging.info(f"已将 {existing_file} 重命名为 {target_file_name}")
                except Exception as e:
                    logging.error(f"重命名 {existing_file} 至 {target_file_name} 时出错: {str(e)}")
        else:
            # 多个同代码文件，需要合并
            # 按文件大小排序，选择数据最多的文件作为主文件
            file_sizes = [(f, os.path.getsize(os.path.join(self.save_path, f))) for f in existing_files]
            main_file, _ = max(file_sizes, key=lambda x: x[1])
            main_path = os.path.join(self.save_path, main_file)

            # 先将新数据追加到主文件
            self._append_new_data(main_path, new_data)

            # 合并所有其他文件的数据到主文件
            for other_file in existing_files:
                if other_file != main_file:
                    other_path = os.path.join(self.save_path, other_file)
                    try:
                        # 读取其他文件数据
                        other_data = pd.read_csv(other_path, header=None,
                                                 names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量',
                                                        '成交额',
                                                        '振幅', '涨跌幅', '涨跌额', '换手率'],
                                                 dtype={'股票代码': str})
                        # 追加到主文件
                        self._append_new_data(main_path, other_data)
                        # 删除其他文件
                        os.remove(other_path)
                        logging.info(f"已合并并删除 {other_file}")
                    except Exception as e:
                        logging.error(f"合并 {other_file} 时出错: {str(e)}")

            # 如果主文件名与目标文件名不同，重命名
            if main_file != target_file_name:
                try:
                    # 确保目标文件不存在（如果与其他文件同名）
                    if os.path.exists(target_file_path) and main_path != target_file_path:
                        os.remove(target_file_path)
                    # 重命名主文件
                    os.rename(main_path, target_file_path)
                    logging.info(f"已将主文件 {main_file} 重命名为 {target_file_name}")
                except Exception as e:
                    logging.error(f"重命名主文件 {main_file} 至 {target_file_name} 时出错: {str(e)}")

    def _append_new_data(self, file_path, new_data):
        """
        追加新数据到现有文件，并处理缺失的日期数据
        """
        try:
            # 读取现有文件的所有数据
            existing_data = pd.read_csv(file_path, header=None,
                                        names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                               '振幅', '涨跌幅', '涨跌额', '换手率'],
                                        dtype={'股票代码': str})

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

    @timer
    def fetch_and_save_data_from_realtime(self, today=None):
        """
        从实时行情数据获取今日股票数据并保存
        
        :param today: 今天的日期
        :return: None
        """
        # 检查当前时间，如果早于15:30或晚于23:55，返回提示信息
        now = datetime.now()
        min_bound = now.hour < 15 or (now.hour == 15 and now.minute < 30)
        max_bound = now.hour > 23 or (now.hour == 23 and now.minute > 55)
        if min_bound or max_bound:
            logging.warning(f"当前时间 {now.strftime('%H:%M')} 不合适，不建议用实时接口更新数据")
            return False

        # 获取今天的日期
        if today is None:
            today = now.strftime("%Y-%m-%d")

        try:
            # 使用实时数据接口获取所有股票数据
            logging.info("开始从实时数据接口获取当日股票数据...")
            stock_real_time = ak.stock_zh_a_spot_em()

            if stock_real_time.empty:
                logging.error("获取实时数据失败，返回空数据")
                return False

            # 实时数据列和历史数据列的映射关系
            column_mapping = {
                '代码': '股票代码',
                '今开': '开盘',
                '最新价': '收盘',
                '最高': '最高',
                '最低': '最低',
                '成交量': '成交量',
                '成交额': '成交额',
                '振幅': '振幅',
                '涨跌幅': '涨跌幅',
                '涨跌额': '涨跌额',
                '换手率': '换手率'
            }

            # 为每只股票创建单独的DataFrame并保存
            processed_count = 0
            total_stocks = len(stock_real_time)
            logging.info(f"共有 {total_stocks} 只股票需要处理")

            for _, row in stock_real_time.iterrows():
                try:
                    # 获取股票代码和名称
                    stock_code = row['代码']
                    stock_name = row['名称']

                    # 跳过退市股票
                    if '退' in stock_name:
                        continue

                    # 创建单只股票的DataFrame
                    stock_data = pd.DataFrame([row])

                    # 转换为与历史数据相同的格式
                    new_data = pd.DataFrame()
                    new_data['日期'] = [today]
                    new_data['股票代码'] = [stock_code]

                    # 复制相应的列
                    for real_col, hist_col in column_mapping.items():
                        if real_col in stock_data.columns:
                            new_data[hist_col] = stock_data[real_col].values
                        else:
                            # 如果缺少某些列，设置为0
                            new_data[hist_col] = 0

                    # 保存当前股票数据，会自动处理同代码文件并使用最新名称
                    self._save_stock_data(stock_code, stock_name, new_data)

                    processed_count += 1
                    # 每处理100只股票输出一次进度信息
                    if processed_count % 100 == 0:
                        logging.info(f"已处理 {processed_count}/{total_stocks} 只股票")

                except Exception as e:
                    logging.error(f"处理股票 {stock_code}({stock_name}) 实时数据时出错: {str(e)}")

            logging.info(f"成功从实时数据更新了 {processed_count} 只股票的数据")
            return True

        except Exception as e:
            logging.error(f"从实时数据接口获取数据时出错: {str(e)}")
            traceback.print_exc()
            return False

    def map_code_to_file(self):
        """
        创建股票代码到文件名的映射
        
        :return: 字典，键为股票代码，值为对应的文件名列表
        """
        # 获取保存目录中的所有文件
        all_files = os.listdir(self.save_path) if os.path.exists(self.save_path) else []
        # 创建股票代码到文件名的映射
        code_to_files = {}
        for filename in all_files:
            if filename.endswith('.csv'):
                # 提取文件名中的股票代码（格式为"code_name.csv"）
                code_match = re.match(r'^(\d{6})_.*\.csv$', filename)
                if code_match:
                    code = code_match.group(1)
                    if code not in code_to_files:
                        code_to_files[code] = []
                    code_to_files[code].append(filename)
        return code_to_files

    def update_same_code_files(self, code_to_files, new_data, stock_code, stock_name):
        """
        处理同代码不同名称的文件
        现在调用新的_handle_existing_files方法实现功能
        
        :param code_to_files: 股票代码到文件名的映射
        :param new_data: 新数据
        :param stock_code: 股票代码
        :param stock_name: 股票名称
        """
        if stock_code in code_to_files:
            existing_files = code_to_files[stock_code]
            if existing_files:
                self._handle_existing_files(existing_files, stock_code, stock_name, new_data)


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
        max_sleep_time=2,  # 随机休眠的最大毫秒数
        enable_auto_captcha=False,  # 是否启用自动验证码解决功能
        stock_list=None  # 不指定特定股票
    )
    data_fetcher.fetch_and_save_data()
