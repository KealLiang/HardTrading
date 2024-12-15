from datetime import datetime, date

import akshare as ak
import pandas as pd

from fetch.astock_data import StockDataBroker

encodings = 'utf-8-sig'  # 添加BOM头的UTF-8，为了excel能识别


def fetch_yyb_lhb_data(start_date, end_date=None, file_path='lhb_data.csv'):
    """
    按起始和结束日期拉取龙虎榜数据，并保存到本地 CSV 文件中。
    如果文件已存在，则从最新日期处追加，避免重复和遗漏。

    :param start_date: 起始日期，格式为 'YYYY-MM-DD'
    :param end_date: 结束日期，格式为 'YYYY-MM-DD'，默认为当前日期
    :param file_path: 保存 CSV 文件的路径
    """
    # 如果未指定结束日期，则默认为当前日期
    if end_date is None:
        end_date = date.today().strftime('%Y-%m-%d')

    # 格式化日期为 'YYYYMMDD' 格式
    start_date_formatted = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y%m%d')
    end_date_formatted = datetime.strptime(end_date, '%Y-%m-%d').strftime('%Y%m%d')

    # 获取龙虎榜-每日活跃营业部数据
    lhb_data = ak.stock_lhb_hyyyb_em(start_date=start_date_formatted, end_date=end_date_formatted)

    # 如果文件已存在，则从最新日期处追加
    if os.path.exists(file_path):
        existing_data = pd.read_csv(file_path)
        existing_data['上榜日'] = pd.to_datetime(existing_data['上榜日'])
        last_date = existing_data['上榜日'].max().strftime('%Y-%m-%d')

        # 筛选出新的数据
        new_data = lhb_data[lhb_data['上榜日'] > last_date]
        if not new_data.empty:
            combined_data = pd.concat([existing_data, new_data], ignore_index=True)
            combined_data.to_csv(file_path, index=False, encoding=encodings)
            print(f"Data updated to {file_path}")
        else:
            print("No new data to append.")
    else:
        lhb_data.to_csv(file_path, index=False, encoding=encodings)
        print(f"Data saved to {file_path}")


# 读取 CSV 文件
def read_lhb_data(file_path):
    return pd.read_csv(file_path, encoding=encodings)


# 获取股票代码
def get_stock_code(stock_name):
    broker = StockDataBroker()
    code = broker.get_code_by_name(stock_name)
    # 处理掉前缀
    return code if code[0].isdigit() else code[2:]


# 查询个股龙虎榜详情
def fetch_stock_lhb_details(lhb_data, trader_name):
    trader_data = lhb_data[lhb_data['营业部名称'] == trader_name]
    details_list = []

    for index, row in trader_data.iterrows():
        # 分割字符串以获取单独的股票名称
        stock_names = row['买入股票'].split()
        lhb_date = row['上榜日'].replace('-', '')  # 将日期格式转换为 'YYYYMMDD'

        print(f"将要拉取{lhb_date} [{stock_names}]的龙虎榜明细")

        for stock_name in stock_names:
            stock_code = get_stock_code(stock_name)  # 需要实现 get_stock_code 函数

            # 查询个股龙虎榜买入详情
            stock_lhb_buy_details = ak.stock_lhb_stock_detail_em(symbol=stock_code, date=lhb_date, flag="买入")
            # 查询个股龙虎榜卖出详情
            stock_lhb_sell_details = ak.stock_lhb_stock_detail_em(symbol=stock_code, date=lhb_date, flag="卖出")

            # 合并买入和卖出数据
            stock_lhb_details = pd.concat([stock_lhb_buy_details, stock_lhb_sell_details], ignore_index=True)

            # 在 DataFrame 前面添加
            stock_lhb_details.insert(0, '上榜日', row['上榜日'])
            stock_lhb_details.insert(1, '股票code', stock_code)
            stock_lhb_details.insert(2, '股票名称', stock_name)

            details_list.append(stock_lhb_details)

    # 合并所有详情数据
    all_details = pd.concat(details_list, ignore_index=True)

    # 按“上榜日”,“股票code”排序
    all_details_sorted = all_details.sort_values(by=['上榜日', '股票code'])

    return all_details_sorted


# 保存到 CSV 文件
def save_to_csv(data, file_path):
    data.to_csv(file_path, index=False, encoding=encodings)


def fetch_and_save_yyb_lhb_data(start_date="2024-12-01", end_date=None, file_path='yyb_lhb_data.csv'):
    """
    保存营业部龙虎榜数据
    :return:
    """
    fetch_yyb_lhb_data(start_date, end_date, file_path)


def fetch_and_merge_stock_lhb_detail(file_path='yyb_lhb_data.csv', output_file_path='stock_lhb_details.csv',
                                     trader_name="中国银河证券股份有限公司大连黄河路证券营业部"):
    """
    根据保存的营业部龙虎榜数据，拉取龙虎榜明细合并
    :return:
    """
    # 读取数据
    lhb_data = read_lhb_data(file_path)

    # 查询个股龙虎榜详情
    stock_lhb_details = fetch_stock_lhb_details(lhb_data, trader_name)

    # 保存到 CSV 文件
    save_to_csv(stock_lhb_details, output_file_path)


if __name__ == '__main__':
    # 先拉取
    fetch_and_save_yyb_lhb_data()
    # 再合并
    fetch_and_merge_stock_lhb_detail()
