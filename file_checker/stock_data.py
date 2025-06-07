import concurrent.futures
import logging
import os
import time

import pandas as pd


class StockDateChecker:
    """股票数据日期排序检查器"""

    def __init__(self, folder_path):
        """
        初始化检查器
        
        Args:
            folder_path: 股票数据文件夹路径
        """
        self.folder_path = folder_path
        self.column_names = ['日期', '股票代码', '开盘', '收盘', '最高', '最低',
                             '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']
        self.results = {'ordered': [], 'disordered': [], 'error': []}

    def get_stock_files(self):
        """获取所有股票数据文件路径"""
        try:
            files = [f for f in os.listdir(self.folder_path)
                     if os.path.isfile(os.path.join(self.folder_path, f))
                     and f.endswith('.csv')]
            logging.info(f"找到 {len(files)} 个股票数据文件")
            return files
        except Exception as e:
            logging.error(f"获取文件列表时出错: {e}")
            return []

    def check_file(self, file_name):
        """
        检查单个文件的日期是否按升序排序
        
        Args:
            file_name: 文件名
            
        Returns:
            tuple: (文件名, 是否有序, 错误信息)
        """
        file_path = os.path.join(self.folder_path, file_name)
        try:
            # 读取CSV文件，不使用表头
            df = pd.read_csv(file_path, header=None, names=self.column_names)

            # 转换日期列为datetime格式
            df['日期'] = pd.to_datetime(df['日期'])

            # 检查日期是否按升序排序
            is_sorted = df['日期'].is_monotonic_increasing

            if not is_sorted:
                # 找出不按顺序的位置
                unsorted_indices = []
                for i in range(1, len(df)):
                    if df['日期'].iloc[i] < df['日期'].iloc[i - 1]:
                        unsorted_indices.append((i - 1, i))
                        if len(unsorted_indices) >= 3:  # 只记录前3个不排序的位置
                            break

                error_msg = f"发现日期不按升序排序的位置: {unsorted_indices}"
                return (file_name, False, error_msg)

            return (file_name, True, "")

        except Exception as e:
            error_msg = f"处理文件时出错: {str(e)}"
            return (file_name, None, error_msg)

    def process_files(self, max_workers=None):
        """
        多线程处理所有文件
        
        Args:
            max_workers: 最大线程数，默认为None（使用系统默认值）
        """
        start_time = time.time()
        files = self.get_stock_files()

        if not files:
            logging.warning("没有找到股票数据文件")
            return

        # 使用线程池处理文件
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.check_file, file_name): file_name for file_name in files}

            for future in concurrent.futures.as_completed(futures):
                file_name = futures[future]
                try:
                    file_name, is_sorted, error_msg = future.result()

                    if is_sorted is None:  # 处理出错
                        self.results['error'].append((file_name, error_msg))
                        logging.error(f"文件 {file_name} 处理出错: {error_msg}")
                    elif is_sorted:  # 有序
                        self.results['ordered'].append(file_name)
                    else:  # 无序
                        self.results['disordered'].append((file_name, error_msg))
                        logging.warning(f"文件 {file_name} 日期无序: {error_msg}")

                except Exception as e:
                    logging.error(f"处理文件 {file_name} 的结果时出错: {str(e)}")

        end_time = time.time()
        self.log_results(end_time - start_time)

    def log_results(self, elapsed_time):
        """记录检查结果"""
        logging.info(f"检查完成，耗时: {elapsed_time:.2f} 秒")
        logging.info(f"有序文件数: {len(self.results['ordered'])}")
        logging.info(f"无序文件数: {len(self.results['disordered'])}")
        logging.info(f"处理出错文件数: {len(self.results['error'])}")

        if self.results['disordered']:
            logging.info("以下文件日期无序:")
            for file_name, error_msg in self.results['disordered']:
                logging.info(f"  - {file_name}: {error_msg}")

        if self.results['error']:
            logging.info("以下文件处理出错:")
            for file_name, error_msg in self.results['error']:
                logging.info(f"  - {file_name}: {error_msg}")


def check_stock_datas(folder_path="./data/astocks"):
    """主函数"""
    # 创建检查器实例
    checker = StockDateChecker(folder_path)

    # 设置线程数为CPU核心数的x倍
    max_workers = os.cpu_count() * 0.5
    logging.info(f"使用 {max_workers} 个线程进行检查")

    # 执行检查
    checker.process_files(max_workers=max_workers)


if __name__ == "__main__":
    check_stock_datas()
