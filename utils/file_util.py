import logging
import os

import pandas as pd


def save_list_to_file(data_list, filename='./data/result.txt'):
    """
    将list的内容保存到一个文本文件中。

    :param data_list: 包含LongTou对象的列表。
    :param filename: 要保存的文件名。
    """
    with open(filename, 'w', encoding='utf-8') as file:
        for stock in data_list:
            file.write(str(stock) + '\n')


def get_stock_file_path(stock_code, data_path='./data/astocks', stock_name=None):
    """
    根据股票代码查找对应的数据文件路径，如果找到多个文件则返回第一个
    
    :param stock_code: 股票代码
    :param data_path: 股票数据目录
    :param stock_name: 股票名称
    :return: 找到的文件完整路径，如果未找到则返回None
    """
    try:
        # 处理股票代码格式，去除可能的后缀如 .SH
        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

        # 确保使用绝对路径
        abs_data_path = os.path.abspath(data_path)
        if not os.path.exists(abs_data_path):
            logging.warning(f"数据路径不存在: {abs_data_path}")
            return None

        # 如果提供了股票名称，直接尝试使用
        if stock_name:
            safe_name = stock_name.replace('*ST', 'xST').replace('/', '_')
            possible_file = f"{clean_code}_{safe_name}.csv"
            full_path = os.path.join(abs_data_path, possible_file)
            if os.path.exists(full_path):
                return full_path

        # 遍历目录，找到第一个匹配的文件就返回
        prefix = f"{clean_code}_"
        for file in os.listdir(abs_data_path):
            if file.startswith(prefix) and file.endswith('.csv'):
                return os.path.join(abs_data_path, file)

        # 如果没有找到文件，记录日志
        logging.info(f"未找到股票 {stock_code} 的数据文件")
        return None

    except Exception as e:
        logging.error(f"查找股票 {stock_code} 数据文件时出错: {e}")
        return None


def read_stock_data(stock_code, data_path='./data/astocks'):
    """
    读取股票数据文件，返回DataFrame
    
    :param stock_code: 股票代码
    :param data_path: 股票数据目录
    :return: 包含股票数据的DataFrame，如果读取失败则返回None
    """
    try:
        file_path = get_stock_file_path(stock_code, data_path)
        if not file_path:
            logging.warning(f"未找到股票 {stock_code} 的数据文件")
            return None

        # 读取CSV文件
        df = pd.read_csv(file_path, header=None,
                         names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                '振幅', '涨跌幅', '涨跌额', '换手率'],
                         dtype={'股票代码': str})

        # 转换日期列为datetime类型
        df['日期'] = pd.to_datetime(df['日期'])

        return df

    except Exception as e:
        logging.error(f"读取股票 {stock_code} 数据时出错: {e}")
        return None


def find_all_stock_files(stock_code, data_path='./data/astocks'):
    """
    根据股票代码查找所有对应的数据文件路径
    
    :param stock_code: 股票代码
    :param data_path: 股票数据目录
    :return: 包含所有匹配文件路径的列表，如果未找到则返回空列表
    """
    try:
        # 处理股票代码格式，去除可能的后缀如 .SH
        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

        # 确保使用绝对路径
        abs_data_path = os.path.abspath(data_path)
        if not os.path.exists(abs_data_path):
            logging.warning(f"数据路径不存在: {abs_data_path}")
            return []

        # 查找所有匹配股票代码的文件
        matching_files = [f for f in os.listdir(abs_data_path) if f.startswith(f"{clean_code}_") and f.endswith('.csv')]

        # 如果没有找到文件，可能需要处理前导零的情况
        if not matching_files and clean_code.startswith('0'):
            # 尝试去掉前导零
            stripped_code = clean_code.lstrip('0')
            if stripped_code:  # 确保不是全零
                matching_files = [f for f in os.listdir(abs_data_path)
                                  if f.startswith(f"{stripped_code}_") and f.endswith('.csv')]

        # 返回所有匹配文件的完整路径
        return [os.path.join(abs_data_path, f) for f in matching_files]

    except Exception as e:
        logging.error(f"查找股票 {stock_code} 的所有数据文件时出错: {e}")
        return []


def read_stock_data_for_date(stock_code, target_date, data_path='./data/astocks'):
    """
    读取股票特定日期的数据
    
    :param stock_code: 股票代码
    :param target_date: 目标日期，格式为'YYYY-MM-DD'
    :param data_path: 股票数据目录
    :return: 该日期的数据行，如果找不到则返回None
    """
    try:
        df = read_stock_data(stock_code, data_path)
        if df is None:
            return None

        # 筛选目标日期的数据
        target_row = df[df['日期'] == pd.to_datetime(target_date)]

        if target_row.empty:
            return None

        return target_row.iloc[0]

    except Exception as e:
        logging.error(f"读取股票 {stock_code} 在 {target_date} 的数据时出错: {e}")
        return None
