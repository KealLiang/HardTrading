import os
from datetime import datetime, timedelta

import a_trade_calendar
import pandas as pd
from tqdm import tqdm

from decorators.practical import timer
from utils.file_util import save_list_to_file


# 定义龙头股对象
class LongTou:
    def __init__(self, stock_code, stock_name, start_date):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.start_date = start_date
        self.start_price = 0.0
        self.high_price = 0.0  # 区间最高价
        self.end_price = 0.0
        self.end_date = None
        self.gain = 100.0
        self.status = '初始'  # 状态: [初始, 候选, 存疑, 高度, 高破, 真龙, 龙破, 龙灭]

    def set_status(self, status):
        self.status = status

    def set_start_date(self, start_date):
        self.start_date = start_date.strftime('%Y-%m-%d')

    def set_end_date(self, end_date):
        self.end_date = end_date.strftime('%Y-%m-%d')

    def __str__(self):
        return (
            f'[{self.stock_code} {self.stock_name}] - {self.status} - 振幅:{self.gain:.2f}% - '
            f'价格:[{self.start_price} - {self.high_price}] - 期间:[{self.start_date} - {self.end_date}]')  # 修改：显示最高价


@timer
def find_dragon_stocks(start_date, end_date=None, threshold=200, height_ratio=0.4, data_path='./data/astocks'):
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    else:
        end_date = end_date
    end_date = get_previous_trading_date(end_date)  # 取交易日

    # 龙头股列表
    long_tou_list = []
    second_threshold = threshold * height_ratio

    # 遍历数据目录下的所有股票数据文件
    for filename in tqdm(os.listdir(data_path)):
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

            # print(stock_code, stock_name)
            # 查找涨停点，更新龙头股状态
            find_in_stock(long_tou_list, start_date, end_date, stock_code, stock_name, stock_data,
                          threshold, second_threshold)

    # 优化高度股筛选逻辑
    height_list = [stock for stock in long_tou_list
                   if stock.status == '高度' and stock.gain >= second_threshold]
    # 真龙股和高度股合并去重
    result_list = list({stock.stock_code: stock for stock in long_tou_list + height_list}.values())

    result_list.sort(key=lambda x: (x.start_date, x.gain, x.status), reverse=True)

    output_path = f'./data/long/long_{start_date}_{end_date}'
    # 保存到txt文件
    # save_list_to_file(result_list, output_path + '.txt')
    # 保存为带颜色的Excel文件
    write_to_excel(result_list, output_path + '.xlsx')

    # 输出
    for stock in result_list:
        print(stock)


def find_in_stock(long_tou_list, start_date, end_date, stock_code, stock_name, stock_data,
                  threshold, second_threshold):
    # 创建龙头股对象
    global cur_date
    dragon_stock = LongTou(stock_code, stock_name, start_date)
    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date)
    # 使用searchsorted找到开始处理的索引
    start_index = stock_data['日期'].searchsorted(start_date)
    max_high = 0.0  # 记录区间最高价

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
            max_high = row['最高']
            # 获取前一天的交易数据
            prev_day_index = index - 1
            if prev_day_index >= 0:
                prev_row = stock_data.iloc[prev_day_index]
                dragon_stock.start_price = prev_row['开盘']  # 使用前一天开盘价
            else:
                tqdm.write(f"[{stock_code} {stock_name}]没有前一天的数据，使用当日开盘价作为起始")
                dragon_stock.start_price = row['开盘']  # 如果没有前一天数据，使用当天开盘价

            dragon_stock.set_status('候选')
            dragon_stock.set_start_date(row['日期'])
            dragon_stock.gain = calc_all_gain(dragon_stock, max_high)  # 统一使用max_high计算
            long_tou_list.append(dragon_stock)
            continue

        if dragon_stock.status != '初始':
            if row['最高'] > max_high:
                max_high = row['最高']
            dragon_stock.gain = calc_all_gain(dragon_stock, max_high)  # 统一使用max_high计算

        # 修改状态判断部分，持续更新结束日期和价格
        if dragon_stock.status in ['候选', '存疑', '高度', '高破']:
            if dragon_stock.gain >= threshold:
                dragon_stock.set_status('真龙')
            elif dragon_stock.gain >= second_threshold:
                dragon_stock.set_status('高度')

        # 对于已经达到高度或真龙状态的股票，持续更新结束日期和价格
        if dragon_stock.status in ['高度', '真龙']:
            dragon_stock.end_price = row['收盘']
            dragon_stock.set_end_date(row['日期'])

        # 修改下跌判断部分
        if gain < 0 and dragon_stock.status in ['存疑', '候选', '真龙', '龙破', '高度']:
            if dragon_stock.status == '存疑':
                long_tou_list.remove(dragon_stock)
                break
            elif dragon_stock.status == '龙破':
                dragon_stock.set_status('龙灭')
                dragon_stock.set_end_date(row['日期'])
                dragon_stock.end_price = row['收盘']
                break
            elif dragon_stock.status == '高度':
                dragon_stock.set_status('高破')
                dragon_stock.set_end_date(row['日期'])
                dragon_stock.end_price = row['收盘']
                break
            elif dragon_stock.status == '真龙':
                dragon_stock.set_status('龙破')
            elif dragon_stock.status == '候选':
                dragon_stock.set_status('存疑')

        # 对于活跃状态且不是刚刚进候选的股票才更新价格和日期
        if dragon_stock.status in ['候选', '存疑', '高度', '真龙']:
            dragon_stock.end_price = row['收盘']
            dragon_stock.set_end_date(row['日期'])

    if cur_date < end_datetime and end_datetime in stock_data['日期'].values:
        try:
            find_in_stock(long_tou_list, cur_date, end_date, stock_code, stock_name, stock_data, threshold,
                          second_threshold)
        except Exception as e:
            print(stock_name, stock_code, cur_date, end_date, e)
    else:
        return long_tou_list


def calc_all_gain(dragon_stock, high_price):
    """计算从起始价格到最高价的振幅
    :param dragon_stock: 龙头股对象
    :param high_price: 最高价(数值类型)
    :return: 振幅百分比
    """
    dragon_stock.high_price = high_price  # 更新最高价
    return (high_price - dragon_stock.start_price) / dragon_stock.start_price * 100.0


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


def write_to_excel(result_list, output_path):
    writer = pd.ExcelWriter(output_path, engine='xlsxwriter')
    df = pd.DataFrame([{
        '股票代码': stock.stock_code,
        '股票名称': stock.stock_name,
        '状态': stock.status,
        '振幅(%)': stock.gain,
        '起始价格': stock.start_price,
        '最高价格': stock.high_price,
        '结束价格': stock.end_price,
        '起始日期': stock.start_date,
        '结束日期': stock.end_date
    } for stock in result_list])
    df.to_excel(writer, index=False, sheet_name='龙头股')
    # 获取工作簿和工作表对象
    workbook = writer.book
    worksheet = writer.sheets['龙头股']
    # 定义状态颜色格式 (使用更直观的颜色名称变量)
    white = workbook.add_format({'bg_color': '#FFFFFF'})  # 白色
    light_yellow = workbook.add_format({'bg_color': '#FFFACD'})  # 淡黄
    light_orange = workbook.add_format({'bg_color': '#FFDAB9'})  # 淡橙
    light_green = workbook.add_format({'bg_color': '#90EE90'})  # 淡绿
    light_red = workbook.add_format({'bg_color': '#FFB6C1'})  # 淡红
    light_blue = workbook.add_format({'bg_color': '#ADD8E6'})  # 淡蓝
    light_gray = workbook.add_format({'bg_color': '#D3D3D3'})  # 淡灰
    light_purple = workbook.add_format({'bg_color': '#E6E6FA'})  # 淡紫
    light_cyan = workbook.add_format({'bg_color': '#E0FFFF'})  # 淡青色
    light_pink = workbook.add_format({'bg_color': '#FFC0CB'})  # 淡粉色
    light_lime = workbook.add_format({'bg_color': '#F0FFF0'})  # 淡青柠色
    light_brown = workbook.add_format({'bg_color': '#F5DEB3'})  # 淡棕色
    # 应用条件格式 (使用新颜色变量)
    for row in range(1, len(df) + 1):
        status = df.iloc[row - 1]['状态']
        if status == '初始':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_green})
        elif status == '候选':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_yellow})
        elif status == '存疑':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_orange})
        elif status == '真龙':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_red})
        elif status == '龙破':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_pink})
        elif status == '龙灭':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_purple})
        elif status == '高度':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_blue})
        elif status == '高破':
            worksheet.conditional_format(row, 2, row, 2, {'type': 'no_blanks', 'format': light_cyan})
    # 调整列宽
    worksheet.set_column('A:I', 15)
    writer.close()
