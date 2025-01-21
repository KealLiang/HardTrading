import os
from datetime import datetime

import pandas as pd
import pywencai

import sys
from utils.date_util import get_trading_days

fupan_file = "./excel/fupan_stocks.xlsx"
# 涨停缓存
zt_cache = {}


def query_wencai(param):
    df = pywencai.get(query=param, sort_key='股票代码', sort_order='desc', loop=True)
    return df


def get_fanbao_stocks(date):
    param = f"{date}低开，实体涨幅大于12%，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
    df = query_wencai(param)
    if df is None:
        return pd.DataFrame()

    selected_columns = [
        '股票代码', '股票简称', f'低开[{date}]', f'实体涨跌幅[{date}]',
        '最新价', '最新涨跌幅', f'技术形态[{date}]'
    ]

    correction_df = df[selected_columns]
    sorted_correction_df = correction_df.sort_values(by=[f'低开[{date}]', f'实体涨跌幅[{date}]'],
                                                     ascending=[False, False],
                                                     key=lambda x: pd.to_numeric(x, errors='coerce')).reset_index(
        drop=True)
    sorted_correction_df[f'低开[{date}]'] = sorted_correction_df[f'低开[{date}]'].apply(lambda x: f"{float(x):.1f}%")
    sorted_correction_df[f'实体涨跌幅[{date}]'] = sorted_correction_df[f'实体涨跌幅[{date}]'].apply(
        lambda x: f"{float(x):.1f}%")
    sorted_correction_df['最新涨跌幅'] = sorted_correction_df['最新涨跌幅'].apply(lambda x: f"{float(x):.1f}%")

    return sorted_correction_df


def get_zt_stocks(date):
    # 检查缓存中是否有数据
    if date in zt_cache:
        print(f"使用缓存数据：{date}")
        jj_df = zt_cache[date]
    else:
        # 设置查询参数
        param = f"{date}涨停，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
        df = query_wencai(param)
        if df is None:
            df = pd.DataFrame()
        # 选择需要的列
        selected_columns = [
            '股票代码', '股票简称', f'涨停开板次数[{date}]', f'最终涨停时间[{date}]',
            f'几天几板[{date}]', '最新价', f'首次涨停时间[{date}]', '最新涨跌幅',
            f'连续涨停天数[{date}]', f'涨停原因类别[{date}]'
        ]
        jj_df = df[selected_columns]
        # 将数据添加到缓存
        zt_cache[date] = jj_df
    return jj_df


def get_lianban_stocks(date):
    """
    获取指定日期的连板个股数据。

    :param date: 查询日期，格式为'YYYYMMDD'。
    :return: 连板个股的DataFrame。
    """

    jj_df = get_zt_stocks(date)

    # 筛选出连续涨停天数大于1的股票
    lianban_df = jj_df[jj_df[f'几天几板[{date}]'] != '首板涨停']

    # 数据处理
    sorted_lianban_df = lianban_df.sort_values(by=f'最终涨停时间[{date}]').reset_index(drop=True)
    sorted_lianban_df['最新涨跌幅'] = sorted_lianban_df['最新涨跌幅'].apply(lambda x: f"{float(x):.1f}%")
    return sorted_lianban_df


def get_shouban_stocks(date):
    """
    获取指定日期的首板个股数据。

    :param date: 查询日期，格式为'YYYYMMDD'。
    :return: 连板个股的DataFrame。
    """

    jj_df = get_zt_stocks(date)

    # 筛选出连续涨停天数大于1的股票
    lianban_df = jj_df[jj_df[f'几天几板[{date}]'] == '首板涨停']

    # 数据处理
    sorted_lianban_df = lianban_df.sort_values(by=f'最终涨停时间[{date}]').reset_index(drop=True)
    sorted_lianban_df['最新涨跌幅'] = sorted_lianban_df['最新涨跌幅'].apply(lambda x: f"{float(x):.1f}%")
    return sorted_lianban_df


def get_dieting_stocks(date):
    """
    获取指定日期的跌停个股数据。

    :param date: 查询日期，格式为'YYYYMMDD'。
    :return: 跌停个股的DataFrame。
    """
    # 设置查询参数
    param = f"{date}跌停，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
    df = query_wencai(param)
    if df is None:
        return pd.DataFrame()

    # 选择需要的列
    selected_columns = [
        '股票代码', '股票简称', f'跌停开板次数[{date}]', f'首次跌停时间[{date}]',
        f'跌停类型[{date}]', '最新价', '最新涨跌幅',
        f'连续跌停天数[{date}]', f'跌停原因类型[{date}]'
    ]
    luoban_df = df[selected_columns]

    # 数据处理
    sorted_luoban_df = luoban_df.sort_values(by=f'首次跌停时间[{date}]').reset_index(drop=True)
    sorted_luoban_df['最新涨跌幅'] = sorted_luoban_df['最新涨跌幅'].apply(lambda x: f"{float(x):.1f}%")
    return sorted_luoban_df


def get_open_dieting_stocks(date):
    """
    获取指定日期的开盘跌停个股数据。

    :param date: 查询日期，格式为'YYYYMMDD'。
    :return: 跌停个股的DataFrame。
    """
    # 设置查询参数
    param = f"{date}开盘跌停，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
    df = query_wencai(param)
    if df is None:
        return pd.DataFrame()

    now_date = datetime.now().strftime('%Y%m%d')
    # 选择需要的列
    selected_columns = [
        '股票代码', '股票简称', '最新价', f'跌停价[{date}]', f'跌停价[{now_date}]'
    ]
    dt_df = df[selected_columns]

    # 数据处理
    sorted_dt_df = dt_df.sort_values(by='最新价').reset_index(drop=True)
    return sorted_dt_df


def get_zaban_stocks(date):
    """
    获取指定日期的炸板个股数据。

    :param date: 查询日期，格式为'YYYYMMDD'。
    :return: 炸板个股的DataFrame。
    """
    # 设置查询参数
    param = f"{date}炸板，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
    df = query_wencai(param)
    if df is None:
        return pd.DataFrame()

    # 选择需要的列
    selected_columns = [
        '股票代码', '股票简称', f'涨停开板次数[{date}]', f'首次涨停时间[{date}]',
        '上市板块', '最新价', f'曾涨停[{date}]', '最新涨跌幅',
        f'涨停封板时长[{date}]', f'涨停时间明细[{date}]'
    ]
    zaban_df = df[selected_columns]

    # 数据处理
    sorted_zaban_df = zaban_df.sort_values(by=f'首次涨停时间[{date}]').reset_index(drop=True)
    sorted_zaban_df['最新涨跌幅'] = sorted_zaban_df['最新涨跌幅'].apply(lambda x: f"{float(x):.1f}%")
    sorted_zaban_df[f'涨停封板时长[{date}]'] = sorted_zaban_df[f'涨停封板时长[{date}]'].apply(
        lambda x: f"{float(x):.2f}H")
    return sorted_zaban_df


def save_to_excel(dataframes, dates, fupan_type):
    """
    将多个日期的DataFrame保存到一个Excel文件中，日期作为列名。

    :param fupan_type: 复盘类型（对应 Excel 的 sheet 名）。
    :param dataframes: 包含所有日期 DataFrame 的字典，键为日期。
    :param dates: 日期列表。
    """
    # 如果文件存在且包含该 sheet，读取已有数据；否则创建新数据
    if sheet_exists(fupan_file, fupan_type):
        existing_data = pd.read_excel(fupan_file, sheet_name=fupan_type, index_col=0)
    else:
        existing_data = pd.DataFrame()

    # 整合新数据到已有数据
    new_data = existing_data.copy()
    for date in dates:
        date_formatted = datetime.strptime(date, '%Y%m%d').strftime('%Y年%m月%d日')
        save_data = dataframes[date].apply(lambda row: '; '.join(row.astype(str)), axis=1)
        save_data.name = date_formatted

        # 如果该日期已经存在，则跳过
        if date_formatted in new_data.columns:
            print(f"数据 {date_formatted} 已存在，跳过追加。")
            continue

        # 合并数据
        new_data = pd.concat([new_data, save_data], axis=1)

    # 按序号排序
    new_data = new_data.sort_index()

    # 写入 Excel 文件
    with pd.ExcelWriter(fupan_file, engine="openpyxl", mode="a" if os.path.exists(fupan_file) else "w") as writer:
        if os.path.exists(fupan_file) and fupan_type in writer.book.sheetnames:
            # 如果 sheet 存在，删除旧的 sheet 再写入
            del writer.book[fupan_type]
        new_data.to_excel(writer, sheet_name=fupan_type, index=True)
    print(f"Data saved to {fupan_file}, sheet: {fupan_type}")


def sheet_exists(file_path, sheet_name):
    """
    检查指定的Excel文件中是否存在特定的工作表。

    :param file_path: Excel文件的路径。
    :param sheet_name: 工作表的名称。
    :return: 如果工作表存在返回True，否则返回False。
    """
    try:
        # 尝试读取Excel文件中的工作表
        with pd.ExcelFile(file_path) as xls:
            if sheet_name in xls.sheet_names:
                return True
            else:
                return False
    except FileNotFoundError:
        return False


def daily_fupan(fupan_type, start_date, end_date):
    fupan_functions = {
        '连板数据': get_lianban_stocks,
        '跌停数据': get_dieting_stocks,
        '炸板数据': get_zaban_stocks,
        '首板数据': get_shouban_stocks,
        '反包数据': get_fanbao_stocks
    }
    # 获取交易日列表
    trading_days = get_trading_days(start_date, end_date)
    print(f"交易日列表：{trading_days}")

    # 对每个交易日获取连板个股数据并保存
    dataframes = {}
    exclude_days = []
    for trade_date in trading_days:
        date_formatted = datetime.strptime(trade_date, '%Y%m%d').strftime('%Y年%m月%d日')

        if sheet_exists(fupan_file, fupan_type) and pd.read_excel(fupan_file, sheet_name=fupan_type,
                                                                  index_col=0).columns.isin(
            [date_formatted]).any():
            print(f"数据 {date_formatted} 已存在，跳过获取。")
            exclude_days.append(trade_date)
            continue

        # 动态调用方法
        lianban_stocks_df = fupan_functions.get(fupan_type, lambda x: None)(trade_date)
        dataframes[trade_date] = lianban_stocks_df

    # 保存所有日期数据到一个Excel文件
    dates = [d for d in trading_days if d not in exclude_days]
    if dataframes:
        save_to_excel(dataframes, dates, fupan_type)


def all_fupan(start_date=None, end_date=None):
    # end_date = "20241201"
    end_date = datetime.now().strftime('%Y%m%d')
    for fupan_type in ['连板数据', '跌停数据', '炸板数据', '首板数据', '反包数据']:
        daily_fupan(fupan_type, start_date, end_date)


if __name__ == "__main__":
    # 设置当前工作目录为脚本所在目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # 添加 utils 模块所在的目录到 sys.path
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

    start_date = "20250101"
    all_fupan(start_date)
