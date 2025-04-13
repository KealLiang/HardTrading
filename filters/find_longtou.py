import os
from datetime import datetime, timedelta

import a_trade_calendar
import pandas as pd

from decorators.practical import timer
from utils.file_util import save_list_to_file


# 定义龙头股对象
# 修改LongTou类的状态注释
class LongTou:
    def __init__(self, stock_code, stock_name, start_date):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.start_date = start_date
        self.start_price = 0.0
        self.end_price = 0.0
        self.end_date = None
        self.gain = 100.0
        self.status = '初始'  # 状态: [初始, 候选, 存疑, 真龙, 龙破, 龙灭, 高度, 高破]

    def set_gain(self, gain):
        self.gain = gain

    def set_status(self, status):
        self.status = status

    def set_start_date(self, start_date):
        self.start_date = start_date.strftime('%Y-%m-%d')

    def set_end_date(self, end_date):
        self.end_date = end_date.strftime('%Y-%m-%d')

    def set_start_price(self, start_price):
        self.start_price = start_price

    def set_end_price(self, end_price):
        self.end_price = end_price

    def __str__(self):
        return (
            f'[{self.stock_code} {self.stock_name}] - {self.status} - 涨幅:{self.gain:.2f}% - '
            f'价格:[{self.start_price} - {self.end_price}] - 期间:[{self.start_date} - {self.end_date}]')


@timer
def find_dragon_stocks(start_date, end_date=None, threshold=200, height_ratio=0.5, data_path='./data/astocks'):
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    else:
        end_date = end_date
    end_date = get_previous_trading_date(end_date)  # 取交易日

    # 龙头股列表
    long_tou_list = []

    # 遍历数据目录下的所有股票数据文件
    for filename in os.listdir(data_path):
        if filename.endswith('.csv'):
            # 获取股票代码和名称
            stock_code, stock_name = filename.split('_')
            stock_name = stock_name.replace('.csv', '')  # 去掉后缀

            # 读取股票的交易数据
            stock_data = pd.read_csv(os.path.join(data_path, filename), header=None,
                                     names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                            '振幅', '涨跌幅', '涨跌额', '换手率'])
            stock_data['日期'] = pd.to_datetime(stock_data['日期'])
            stock_data = stock_data.sort_values(by='日期')  # 按日期排序

            # 跳过ST股
            if 'ST' in stock_name:
                continue

            print(stock_code, stock_name)
            # 查找涨停点，更新龙头股状态
            find_in_stock(long_tou_list, start_date, end_date, stock_code, stock_name, stock_data,
                          threshold, height_ratio)

    # 优化高度股筛选逻辑
    height_threshold = threshold * height_ratio
    height_list = [stock for stock in long_tou_list 
                  if stock.status == '高度' and stock.gain >= height_threshold]
    # 真龙股和高度股合并去重
    result_list = list({stock.stock_code: stock for stock in long_tou_list + height_list}.values())
    
    result_list.sort(key=lambda x: (x.start_date, x.status, x.gain), reverse=True)
    
    # 保存
    save_list_to_file(result_list, f'./data/long_{start_date}_{end_date}.txt')
    
    # 输出
    for stock in result_list:
        print(stock)


def find_in_stock(long_tou_list, start_date, end_date, stock_code, stock_name, stock_data, threshold, height_ratio):
    # 创建龙头股对象
    global cur_date
    dragon_stock = LongTou(stock_code, stock_name, start_date)
    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date)
    # 使用searchsorted找到开始处理的索引
    start_index = stock_data['日期'].searchsorted(start_date)
    for index, row in stock_data.iloc[start_index:].iterrows():
        # 当股票的日期大于等于开始日期时开始处理
        if row['日期'] < start_datetime:
            continue
        if row['日期'] > end_datetime:
            break
        # 当天的涨幅
        gain = row['涨跌幅']
        cur_date = row['日期']

        # 第一次涨停加入候选龙头
        if is_zhangting(stock_code, stock_name, gain) and dragon_stock.status == '初始':
            dragon_stock.set_status('候选')
            dragon_stock.set_start_date(row['日期'])
            dragon_stock.set_start_price(row['开盘'])
            dragon_stock.set_gain(calc_all_gain(dragon_stock, row))
            long_tou_list.append(dragon_stock)
            continue

        if dragon_stock.status != '初始':
            dragon_stock.set_gain(calc_all_gain(dragon_stock, row))

        # 修改状态判断部分，持续更新结束日期和价格
        if dragon_stock.status in ['候选', '存疑']:
            if dragon_stock.gain >= threshold:
                dragon_stock.set_status('真龙')
            elif dragon_stock.gain >= threshold * height_ratio:
                dragon_stock.set_status('高度')
        
        # 对于已经达到高度或真龙状态的股票，持续更新结束日期和价格
        if dragon_stock.status in ['高度', '真龙']:
            dragon_stock.set_end_price(row['收盘'])
            dragon_stock.set_end_date(row['日期'])
        
        # 修改下跌判断部分
        if gain < 0 and dragon_stock.status in ['存疑', '候选', '真龙', '龙破', '高度']:
            if dragon_stock.status == '存疑':
                long_tou_list.remove(dragon_stock)
                break
            elif dragon_stock.status == '龙破':
                dragon_stock.set_status('龙灭')
                dragon_stock.set_end_date(row['日期'])
                dragon_stock.set_end_price(row['收盘'])
                break
            elif dragon_stock.status == '高度':
                dragon_stock.set_status('高破')
                dragon_stock.set_end_date(row['日期'])
                dragon_stock.set_end_price(row['收盘'])
                break
            elif dragon_stock.status == '真龙':
                dragon_stock.set_status('龙破')
            elif dragon_stock.status == '候选':
                dragon_stock.set_status('存疑')
        
        # 对于活跃状态的股票才更新价格和日期
        if dragon_stock.status in ['候选', '存疑', '高度', '真龙']:
            dragon_stock.set_end_price(row['收盘'])
            dragon_stock.set_end_date(row['日期'])
    if cur_date < end_datetime and end_datetime in stock_data['日期'].values:
        try:
            find_in_stock(long_tou_list, cur_date, end_date, stock_code, stock_name, stock_data, threshold, height_ratio)  # 补全参数
        except Exception as e:
            print(stock_name, stock_code, cur_date, end_date, e)
    else:
        return long_tou_list


def calc_all_gain(dragon_stock, row):
    return (row['收盘'] - dragon_stock.start_price) / dragon_stock.start_price * 100.0


def is_zhangting(code, name, gain):
    """
    判断股票是否涨停。

    :param name:
    :param code: 股票代码
    :param gain: 今日涨幅
    :return: 如果涨停返回True，否则返回False
    """
    if code.startswith('30') or code.startswith('68'):
        # 创业板和科创板股票涨停幅度为20%
        high_limit = 19.9
    elif 'ST' in name:
        # ST股票涨停幅度为5%
        high_limit = 4.9
    else:
        # 其他情况默认为10%
        high_limit = 9.9
    return gain >= high_limit


def get_previous_trading_date(end_date):
    """
    获取end_date的上一个交易日，如果end_date是交易日，则返回自身。

    :param end_date: 结束日期，格式为'YYYY-MM-DD'。
    :return: 上一个交易日的日期，格式为'YYYY-MM-DD'。
    """
    # 检查end_date是否为交易日
    if a_trade_calendar.is_trade_date(end_date):
        return end_date

    # 如果end_date不是交易日，则找到end_date之前的最近一个交易日
    date_dt = datetime.strptime(end_date, '%Y-%m-%d')
    previous_date = date_dt - timedelta(days=1)
    while not a_trade_calendar.is_trade_date(previous_date.strftime('%Y-%m-%d')):
        previous_date -= timedelta(days=1)

    return previous_date.strftime('%Y-%m-%d')
