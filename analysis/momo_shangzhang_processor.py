#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
【默默上涨】数据处理模块

处理【默默上涨】数据的入选、跟踪和格式化逻辑
"""

import re
from datetime import datetime, timedelta

import pandas as pd

from utils.date_util import get_trading_days, get_n_trading_days_before

# 【默默上涨】相关参数
# 入选前跟踪的最大天数（独立于连板数据的参数）
MAX_TRACKING_DAYS_BEFORE_ENTRY_MOMO = 20

# 【默默上涨】持续跟踪的跌幅阈值（%），跌幅小于此值则停止跟踪
MOMO_DECLINE_THRESHOLD = -25.0

# 【默默上涨】入选的月数范围
MOMO_ENTRY_MONTHS = 3

# 输入文件路径
FUPAN_FILE = "./excel/fupan_stocks.xlsx"


def load_momo_shangzhang_data(start_date, end_date):
    """
    从Excel中加载【默默上涨】数据
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        
    Returns:
        pandas.DataFrame: 处理后的【默默上涨】数据
    """
    try:
        # 读取【默默上涨】数据sheet
        try:
            df = pd.read_excel(FUPAN_FILE, sheet_name="默默上涨")
            print(f"成功读取【默默上涨】数据sheet，共有{len(df)}行，{len(df.columns)}列")
        except Exception as e:
            print(f"读取【默默上涨】数据sheet失败: {e}")
            return pd.DataFrame()

        # 将日期列转换为datetime格式
        date_columns = []

        # 检查两种可能的日期格式：YYYY/MM/DD和YYYY年MM月DD日
        for col in df.columns:
            if isinstance(col, str):
                if re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', col):
                    date_columns.append(col)
                elif re.match(r'^\d{4}年\d{1,2}月\d{1,2}日$', col):
                    date_columns.append(col)

        if not date_columns:
            print("【默默上涨】数据中未找到有效的日期列")
            return pd.DataFrame()

        # 过滤日期范围 - 【默默上涨】的特殊逻辑：3个月以内的都入选
        end_date_obj = datetime.strptime(end_date, '%Y%m%d')
        start_date_obj = end_date_obj - timedelta(days=MOMO_ENTRY_MONTHS * 30)  # 大约3个月
        start_date_filter = start_date_obj.strftime('%Y%m%d')

        filtered_date_columns = []
        for col in date_columns:
            # 将两种格式的日期都转换为datetime
            if '年' in col:
                # 中文格式: YYYY年MM月DD日
                date_parts = re.findall(r'\d+', col)
                if len(date_parts) == 3:
                    date_obj = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                else:
                    continue
            else:
                # 标准格式: YYYY/MM/DD
                date_obj = pd.to_datetime(col)

            date_str = date_obj.strftime('%Y%m%d')
            # 【默默上涨】入选逻辑：3个月以内的都入选
            if date_str >= start_date_filter and date_str <= end_date:
                filtered_date_columns.append(col)

        if not filtered_date_columns:
            print(f"【默默上涨】数据中未找到{start_date_filter}到{end_date}范围内的数据")
            return pd.DataFrame()

        print(f"【默默上涨】数据过滤后的日期列: {filtered_date_columns}")

        # 创建一个新的DataFrame来存储处理后的数据
        processed_data = []

        # 遍历每个日期列，提取股票信息
        for date_col in filtered_date_columns:
            date_obj = datetime.strptime(date_col, '%Y年%m月%d日') if '年' in date_col else pd.to_datetime(date_col)
            date_str = date_obj.strftime('%Y%m%d')

            # 遍历该日期列中的每个单元格
            for _, cell_value in df[date_col].items():
                if pd.isna(cell_value):
                    continue

                # 解析单元格内容，格式: "股票代码; 股票简称; 最新价; 最新涨跌幅; 区间涨跌幅; 区间成交额; 区间振幅; 上市交易日天数"
                cell_text = str(cell_value)
                parts = cell_text.split(';')

                if len(parts) < 8:
                    continue

                stock_code = parts[0].strip()
                stock_name = parts[1].strip()
                latest_price = parts[2].strip()
                latest_change = parts[3].strip()
                period_change = parts[4].strip()
                period_volume = parts[5].strip()
                period_amplitude = parts[6].strip()
                listing_days = parts[7].strip()

                # 处理股票代码，去除可能的市场前缀
                if stock_code.startswith(('sh', 'sz', 'bj')):
                    stock_code = stock_code[2:]

                # 构建概念信息：使用区间成交额和区间涨跌幅
                concept_info = f"成交额:{period_volume} 涨幅:{period_change}"

                processed_data.append({
                    '股票代码': f"{stock_code}_{stock_name}",
                    '纯代码': stock_code,
                    '股票名称': stock_name,
                    '日期': date_col,
                    '最新价': latest_price,
                    '最新涨跌幅': latest_change,
                    '区间涨跌幅': period_change,
                    '区间成交额': period_volume,
                    '区间振幅': period_amplitude,
                    '上市交易日天数': listing_days,
                    '概念': concept_info,
                    '入选类型': 'momo_shangzhang'  # 标记为【默默上涨】类型
                })

        # 转换为DataFrame
        result_df = pd.DataFrame(processed_data)

        if result_df.empty:
            print("未能从【默默上涨】数据中提取有效的数据")
            return pd.DataFrame()

        print(f"处理后的【默默上涨】数据: {len(result_df)}行，包含{len(filtered_date_columns)}个日期列")

        # 去重：同一只股票在多个日期出现时，只保留最新的记录
        result_df = result_df.sort_values('日期').drop_duplicates(subset=['纯代码'], keep='last')
        print(f"去重后的【默默上涨】数据: {len(result_df)}行")

        return result_df

    except Exception as e:
        print(f"加载【默默上涨】数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def identify_momo_shangzhang_stocks(momo_df, start_date, end_date):
    """
    识别【默默上涨】股票的入选和跟踪逻辑
    
    Args:
        momo_df: 【默默上涨】原始数据DataFrame
        start_date: 分析开始日期 (YYYYMMDD)
        end_date: 分析结束日期 (YYYYMMDD)
        
    Returns:
        pandas.DataFrame: 处理后的【默默上涨】股票数据，格式与连板数据兼容
    """
    if momo_df.empty:
        return pd.DataFrame()

    result = []

    # 获取分析周期内的所有交易日
    trading_days = get_trading_days(start_date, end_date)

    for _, stock in momo_df.iterrows():
        stock_code = stock['纯代码']
        stock_name = stock['股票名称']
        entry_date_str = stock['日期']

        # 将入选日期转换为datetime对象
        if '年' in entry_date_str:
            entry_date = datetime.strptime(entry_date_str, '%Y年%m月%d日')
        else:
            entry_date = pd.to_datetime(entry_date_str)

        entry_date_yyyymmdd = entry_date.strftime('%Y%m%d')

        # 检查入选日期是否在分析周期内
        if entry_date_yyyymmdd < start_date or entry_date_yyyymmdd > end_date:
            continue

        # 【默默上涨】的跟踪逻辑：检查从入选日起的跌幅是否超过阈值
        should_track = check_momo_tracking_condition(stock_code, entry_date_yyyymmdd, end_date)

        if should_track:
            # 构建跟踪期间的数据字典
            all_board_data = {}

            # 计算跟踪开始日期：入选日期前MAX_TRACKING_DAYS_BEFORE_ENTRY_MOMO天
            entry_date_yyyymmdd = entry_date.strftime('%Y%m%d')
            tracking_start_date = get_n_trading_days_before(entry_date_yyyymmdd, MAX_TRACKING_DAYS_BEFORE_ENTRY_MOMO)
            if '-' in tracking_start_date:
                tracking_start_date = tracking_start_date.replace('-', '')

            # 重新构建交易日列表，只包含从tracking_start_date到end_date的交易日
            limited_trading_days = get_trading_days(tracking_start_date, end_date)

            # 只跟踪限定范围内的交易日
            for trading_day in limited_trading_days:
                # 【默默上涨】在天梯图中不显示连板信息，而是显示涨跌幅或特殊标记
                all_board_data[datetime.strptime(trading_day, '%Y%m%d').strftime('%Y年%m月%d日')] = None

            # 添加到结果列表
            entry = {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'first_significant_date': entry_date,
                'board_level_at_first': 0,  # 【默默上涨】不是连板，设为0
                'all_board_data': all_board_data,
                'concept': stock['概念'],
                'entry_type': 'momo_shangzhang',
                'momo_data': {
                    '区间涨跌幅': stock['区间涨跌幅'],
                    '区间成交额': stock['区间成交额'],
                    '区间振幅': stock['区间振幅'],
                    '最新价': stock['最新价'],
                    '最新涨跌幅': stock['最新涨跌幅']
                }
            }

            result.append(entry)
            print(f"【默默上涨】股票入选: {stock_name} ({stock_code}) 入选日期: {entry_date_str}")

    # 转换为DataFrame
    result_df = pd.DataFrame(result)

    if not result_df.empty:
        # 添加概念组信息
        result_df['concept_group'] = "默默上涨"
        result_df['concept_priority'] = 999  # 设置较低的优先级，排在最后

        print(f"【默默上涨】最终入选股票数量: {len(result_df)}")

    return result_df


def check_momo_tracking_condition(stock_code, entry_date, end_date):
    """
    检查【默默上涨】股票是否满足持续跟踪条件

    从入选日起计算，如果跌幅达到MOMO_DECLINE_THRESHOLD则停止跟踪

    Args:
        stock_code: 股票代码
        entry_date: 入选日期 (YYYYMMDD格式)
        end_date: 结束日期 (YYYYMMDD格式)

    Returns:
        bool: True表示继续跟踪，False表示停止跟踪
    """
    try:
        from utils.file_util import read_stock_data

        # 获取股票的历史数据
        stock_data = read_stock_data(stock_code)
        if stock_data is None or stock_data.empty:
            return True  # 如果获取不到数据，继续跟踪

        # 转换日期格式进行比较
        entry_date_formatted = f"{entry_date[:4]}-{entry_date[4:6]}-{entry_date[6:8]}"
        end_date_formatted = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        # 筛选从入选日到结束日的数据
        mask = (stock_data['日期'] >= entry_date_formatted) & (stock_data['日期'] <= end_date_formatted)
        period_data = stock_data[mask]

        if period_data.empty:
            return True  # 如果没有期间数据，继续跟踪

        # 获取入选日的收盘价
        entry_row = period_data[period_data['日期'] == entry_date_formatted]
        if entry_row.empty:
            return True  # 如果没有入选日数据，继续跟踪

        entry_close = entry_row.iloc[0]['收盘']

        # 计算从入选日起的最大跌幅
        min_close = period_data['收盘'].min()
        max_decline_pct = ((min_close - entry_close) / entry_close) * 100

        # 如果跌幅超过阈值，停止跟踪
        if max_decline_pct <= MOMO_DECLINE_THRESHOLD:
            print(f"【默默上涨】{stock_code}: 跌幅{max_decline_pct:.2f}%超过阈值{MOMO_DECLINE_THRESHOLD}%，停止跟踪")
            return False

        return True

    except Exception as e:
        print(f"【默默上涨】{stock_code}: 检查跌幅条件时出错: {e}")
        return True  # 出错时继续跟踪


def format_momo_concept_info(momo_data):
    """
    格式化【默默上涨】的概念信息
    
    Args:
        momo_data: 【默默上涨】数据字典
        
    Returns:
        str: 格式化后的概念信息
    """
    if not momo_data:
        return "默默上涨"

    period_change = momo_data.get('区间涨跌幅', '')
    period_volume = momo_data.get('区间成交额', '')

    return f"默默上涨 [{period_change} {period_volume}]"
