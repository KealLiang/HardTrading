#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
每日盈亏计算工具

计算股票的隔日平均盈亏
计算公式：t日的盈亏 = (t日的收盘价 - t-1日开盘价) / t-1日开盘价
"""

import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional

from utils.date_util import get_prev_trading_day
from utils.file_util import read_stock_data

logger = logging.getLogger(__name__)


def calculate_daily_profit(stock_codes_by_date: Dict[str, List[str]],
                           data_path: str = './data/astocks') -> List[Tuple[str, Optional[float], int]]:
    """
    计算每日默默上涨股票的平均隔日盈亏
    
    Args:
        stock_codes_by_date: 字典，键为日期字符串（格式：YYYY年MM月DD日），值为该日期的股票代码列表
        data_path: 股票数据目录路径，默认为'./data/astocks'
        
    Returns:
        List[Tuple[str, Optional[float], int]]: 
            - 日期字符串（格式：YYYY年MM月DD日）
            - 平均盈亏（百分比，None表示无法计算）
            - 有效样本数量（成功计算盈亏的股票数量）
    """
    results = []

    # 按日期排序处理
    sorted_dates = sorted(stock_codes_by_date.keys(),
                          key=lambda x: datetime.strptime(x, "%Y年%m月%d日"))

    for date_str in sorted_dates:
        stock_codes = stock_codes_by_date[date_str]

        if not stock_codes:
            results.append((date_str, None, 0))
            continue

        # 将日期格式转换为YYYYMMDD
        date_obj = datetime.strptime(date_str, "%Y年%m月%d日")
        date_yyyymmdd = date_obj.strftime("%Y%m%d")

        # 获取前一个交易日
        prev_date_yyyymmdd = get_prev_trading_day(date_yyyymmdd)
        if not prev_date_yyyymmdd:
            logger.warning(f"日期 {date_str} 无法获取前一个交易日，跳过")
            results.append((date_str, None, 0))
            continue

        # 计算每只股票的盈亏
        profits = []
        valid_count = 0

        for stock_code in stock_codes:
            # 清理股票代码（去除市场后缀）
            clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
            clean_code = clean_code.split('_')[0] if '_' in clean_code else clean_code

            try:
                # 读取股票数据
                stock_data = read_stock_data(clean_code, data_path)
                if stock_data is None or stock_data.empty:
                    continue

                # 确保数据按日期排序
                stock_data = stock_data.sort_values('日期').reset_index(drop=True)
                stock_data['日期_str'] = stock_data['日期'].dt.strftime('%Y%m%d')

                # 查找前一个交易日和当前交易日的数据
                prev_data = stock_data[stock_data['日期_str'] == prev_date_yyyymmdd]
                current_data = stock_data[stock_data['日期_str'] == date_yyyymmdd]

                if prev_data.empty or current_data.empty:
                    continue

                prev_row = prev_data.iloc[0]
                current_row = current_data.iloc[0]

                # 计算盈亏：t日的盈亏 = (t日的收盘价 - t-1日开盘价) / t-1日开盘价
                prev_open = prev_row['开盘']
                current_close = current_row['收盘']

                if prev_open is None or current_close is None or prev_open == 0:
                    continue

                profit_pct = ((current_close - prev_open) / prev_open) * 100
                profits.append(profit_pct)
                valid_count += 1

            except Exception as e:
                logger.debug(f"计算股票 {clean_code} 在日期 {date_str} 的盈亏时出错: {e}")
                continue

        # 计算平均盈亏
        if profits:
            avg_profit = sum(profits) / len(profits)
            results.append((date_str, avg_profit, valid_count))
        else:
            results.append((date_str, None, valid_count))

    return results


def calculate_daily_profit_with_details(stock_codes_by_date: Dict[str, List[str]],
                                        data_path: str = './data/astocks') -> Tuple[
    List[Tuple[str, Optional[float], int]], Dict[str, Dict[str, Optional[float]]]]:
    """
    计算每日默默上涨股票的平均隔日盈亏，并返回每只股票的详细盈亏数据
    
    Args:
        stock_codes_by_date: 字典，键为日期字符串（格式：YYYY年MM月DD日），值为该日期的股票代码列表
        data_path: 股票数据目录路径，默认为'./data/astocks'
        
    Returns:
        Tuple:
            - List[Tuple[str, Optional[float], int]]: 平均盈亏结果
                - 日期字符串（格式：YYYY年MM月DD日）
                - 平均盈亏（百分比，None表示无法计算）
                - 有效样本数量
            - Dict[str, Dict[str, Optional[float]]]: 每只股票的盈亏详情
                - 外层键：日期字符串（格式：YYYY年MM月DD日）
                - 内层键：股票代码（清理后的）
                - 值：盈亏百分比（None表示无法计算）
    
    说明：
        计算公式：t日的盈亏 = (t日的收盘价 - t-1日开盘价) / t-1日开盘价 × 100%
        含义：在t-1日开盘买入，在t日收盘卖出所得的盈亏
        例如：2025-12-03的盈亏 = (2025-12-03收盘价 - 2025-12-02开盘价) / 2025-12-02开盘价 × 100%
    """
    results = []
    stock_profits_detail = {}  # {日期: {股票代码: 盈亏}}

    # 按日期排序处理
    sorted_dates = sorted(stock_codes_by_date.keys(),
                          key=lambda x: datetime.strptime(x, "%Y年%m月%d日"))

    for date_str in sorted_dates:
        stock_codes = stock_codes_by_date[date_str]
        stock_profits_detail[date_str] = {}

        if not stock_codes:
            results.append((date_str, None, 0))
            continue

        # 将日期格式转换为YYYYMMDD
        date_obj = datetime.strptime(date_str, "%Y年%m月%d日")
        date_yyyymmdd = date_obj.strftime("%Y%m%d")

        # 获取前一个交易日
        prev_date_yyyymmdd = get_prev_trading_day(date_yyyymmdd)
        if not prev_date_yyyymmdd:
            logger.warning(f"日期 {date_str} 无法获取前一个交易日，跳过")
            results.append((date_str, None, 0))
            continue

        # 计算每只股票的盈亏
        profits = []
        valid_count = 0

        for stock_code in stock_codes:
            # 清理股票代码（去除市场后缀）
            clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
            clean_code = clean_code.split('_')[0] if '_' in clean_code else clean_code

            try:
                # 读取股票数据
                stock_data = read_stock_data(clean_code, data_path)
                if stock_data is None or stock_data.empty:
                    stock_profits_detail[date_str][clean_code] = None
                    continue

                # 确保数据按日期排序
                stock_data = stock_data.sort_values('日期').reset_index(drop=True)
                stock_data['日期_str'] = stock_data['日期'].dt.strftime('%Y%m%d')

                # 查找前一个交易日和当前交易日的数据
                prev_data = stock_data[stock_data['日期_str'] == prev_date_yyyymmdd]
                current_data = stock_data[stock_data['日期_str'] == date_yyyymmdd]

                if prev_data.empty or current_data.empty:
                    stock_profits_detail[date_str][clean_code] = None
                    continue

                prev_row = prev_data.iloc[0]
                current_row = current_data.iloc[0]

                # 计算盈亏：t日的盈亏 = (t日的收盘价 - t-1日开盘价) / t-1日开盘价
                prev_open = prev_row['开盘']
                current_close = current_row['收盘']

                if prev_open is None or current_close is None or prev_open == 0:
                    stock_profits_detail[date_str][clean_code] = None
                    continue

                profit_pct = ((current_close - prev_open) / prev_open) * 100
                profits.append(profit_pct)
                stock_profits_detail[date_str][clean_code] = profit_pct
                valid_count += 1

            except Exception as e:
                logger.debug(f"计算股票 {clean_code} 在日期 {date_str} 的盈亏时出错: {e}")
                stock_profits_detail[date_str][clean_code] = None
                continue

        # 计算平均盈亏
        if profits:
            avg_profit = sum(profits) / len(profits)
            results.append((date_str, avg_profit, valid_count))
        else:
            results.append((date_str, None, valid_count))

    return results, stock_profits_detail


def calculate_daily_profit_from_momo_results(momo_results: List[Tuple],
                                             data_path: str = './data/astocks') -> List[
    Tuple[str, Optional[float], int]]:
    """
    从默默上涨结果中提取股票代码并计算每日盈亏
    
    Args:
        momo_results: 默默上涨结果列表，格式与 fupan_plot_html.py 中的 momo_results 一致
            [(date, avg_zhangfu, momo_stocks_data, top_3_stocks, sample_count, codes_str), ...]
        data_path: 股票数据目录路径，默认为'./data/astocks'
        
    Returns:
        List[Tuple[str, Optional[float], int]]: 
            - 日期字符串（格式：YYYY年MM月DD日）
            - 平均盈亏（百分比，None表示无法计算）
            - 有效样本数量
    """
    # 从momo_results中提取股票代码
    stock_codes_by_date = {}

    for item in momo_results:
        date_str = item[0]
        codes_str = item[5]  # 股票代码字符串（换行符分隔）

        if codes_str and codes_str.strip():
            stock_codes = [code.strip() for code in codes_str.split('\n') if code.strip()]
            stock_codes_by_date[date_str] = stock_codes
        else:
            stock_codes_by_date[date_str] = []

    results, _ = calculate_daily_profit_with_details(stock_codes_by_date, data_path)
    return results


def calculate_daily_profit_with_stock_details_from_momo_results(momo_results: List[Tuple],
                                                                data_path: str = './data/astocks',
                                                                buy_days_before: int = 1) -> Tuple[
    List[Tuple[str, Optional[float], int]], Dict[str, Dict[str, Optional[float]]]]:
    """
    从默默上涨结果中提取股票代码并计算每日盈亏，返回平均值和每只股票的详细盈亏
    
    重要：使用前N日选出的股票计算盈亏（正确逻辑）
    - 对于日期t，使用t-N日选出的股票列表（N = buy_days_before）
    - 买入日：t-N+1日开盘价（选出的第二天）
    - 卖出日：t-N+2日收盘价（选出的第三天）
    - 计算这些股票的盈亏 = (t-N+2日收盘价 - t-N+1日开盘价) / t-N+1日开盘价
    
    说明：
    - t-N日选出的股票，不能在t-N日开盘买入（因为选股结果在t-N日收盘后才出来）
    - 应该在t-N+1日开盘买入，t-N+2日收盘卖出
    - 只有当卖出日 <= 当前日期t时，才能计算盈亏
    
    Args:
        momo_results: 默默上涨结果列表，格式与 fupan_plot_html.py 中的 momo_results 一致
            [(date, avg_zhangfu, momo_stocks_data, top_3_stocks, sample_count, codes_str), ...]
        data_path: 股票数据目录路径，默认为'./data/astocks'
        buy_days_before: 选股日相对于当前日的前N个交易日，默认为1（表示t-1日选出）
            - 1: t-1日选出，t-1+1=t日开盘买入，t-1+2=t+1日收盘卖出（隔日盈亏）
            - 2: t-2日选出，t-2+1=t-1日开盘买入，t-2+2=t日收盘卖出
            - 3: t-3日选出，t-3+1=t-2日开盘买入，t-3+2=t-1日收盘卖出
            - 以此类推
        
    Returns:
        Tuple:
            - List[Tuple[str, Optional[float], int]]: 平均盈亏结果
            - Dict[str, Dict[str, Optional[float]]]: 每只股票的盈亏详情 {日期: {股票代码: 盈亏}}
    """
    from utils.date_util import get_n_trading_days_before, get_next_trading_day

    # 从momo_results中提取股票代码（按日期索引）
    stock_codes_by_date = {}
    date_list = []

    for item in momo_results:
        date_str = item[0]
        date_list.append(date_str)
        codes_str = item[5]  # 股票代码字符串（换行符分隔）

        if codes_str and codes_str.strip():
            stock_codes = [code.strip() for code in codes_str.split('\n') if code.strip()]
            stock_codes_by_date[date_str] = stock_codes
        else:
            stock_codes_by_date[date_str] = []

    # 重新组织：对于每个日期t，计算盈亏
    # 正确逻辑：t-N日选出 → t-N+1日买入 → t-N+2日卖出
    # 在日期t，我们需要找到卖出日为t的股票组合
    # 即：卖出日 = t-N+2 = t，所以选股日 = t-(N+1)
    # 对于buy_days_before=1：选股日 = t-2，买入日 = t-1，卖出日 = t
    # 这样在日期t，我们可以显示t-2日选出的股票，在t-1日买入，t日卖出的盈亏
    # 但用户要求的是：t-1日选出，t日买入，t+1日卖出的盈亏
    # 这个盈亏只有在t+1日才能计算，所以在日期t+1显示
    results = []
    stock_profits_detail = {}  # {日期: {股票代码: 盈亏}}

    for i, date_str in enumerate(date_list):
        # 当前日期t
        date_obj = datetime.strptime(date_str, "%Y年%m月%d日")
        date_yyyymmdd = date_obj.strftime("%Y%m%d")

        # 计算卖出日为t的选股日：t-N+2 = t，所以选股日 = t-(N+1)
        # 对于buy_days_before=1：选股日 = t-2，买入日 = t-1，卖出日 = t
        select_date_offset = buy_days_before + 1
        select_date_str_formatted = get_n_trading_days_before(date_yyyymmdd, select_date_offset)

        if not select_date_str_formatted:
            results.append((date_str, None, 0))
            stock_profits_detail[date_str] = {}
            continue

        # 将选股日转换为日期字符串格式（get_n_trading_days_before返回YYYY-MM-DD格式）
        select_date_obj = datetime.strptime(select_date_str_formatted, "%Y-%m-%d")
        select_date_str = select_date_obj.strftime("%Y年%m月%d日")
        select_date_yyyymmdd = select_date_obj.strftime("%Y%m%d")

        # 获取选股日选出的股票列表
        selected_stock_codes = stock_codes_by_date.get(select_date_str, [])

        if not selected_stock_codes:
            results.append((date_str, None, 0))
            stock_profits_detail[date_str] = {}
            continue

        # 买入日：选股日的第二天
        buy_date_yyyymmdd = get_next_trading_day(select_date_yyyymmdd)
        if not buy_date_yyyymmdd:
            results.append((date_str, None, 0))
            stock_profits_detail[date_str] = {}
            continue

        # 卖出日：买入日的第二天 = t日（当前日期）
        sell_date_yyyymmdd = get_next_trading_day(buy_date_yyyymmdd)
        if not sell_date_yyyymmdd or sell_date_yyyymmdd != date_yyyymmdd:
            # 卖出日必须是当前日期t
            results.append((date_str, None, 0))
            stock_profits_detail[date_str] = {}
            continue

        # 计算这些股票的盈亏（t-N+1日开盘买入，t-N+2日收盘卖出）
        # 重要：将盈亏存储到选股日（select_date_str），而不是卖出日（date_str）
        # 这样即使股票后续被移除，盈亏信息也会保留在选股日
        profits = []
        valid_count = 0

        # 确保选股日的字典已初始化
        if select_date_str not in stock_profits_detail:
            stock_profits_detail[select_date_str] = {}

        for stock_code in selected_stock_codes:
            # 清理股票代码（去除市场后缀）
            clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
            clean_code = clean_code.split('_')[0] if '_' in clean_code else clean_code

            try:
                # 读取股票数据
                stock_data = read_stock_data(clean_code, data_path)
                if stock_data is None or stock_data.empty:
                    stock_profits_detail[select_date_str][clean_code] = None
                    continue

                # 确保数据按日期排序
                stock_data = stock_data.sort_values('日期').reset_index(drop=True)
                stock_data['日期_str'] = stock_data['日期'].dt.strftime('%Y%m%d')

                # 查找买入日（t-N+1日）和卖出日（t-N+2日）的数据
                buy_data = stock_data[stock_data['日期_str'] == buy_date_yyyymmdd]
                sell_data = stock_data[stock_data['日期_str'] == sell_date_yyyymmdd]

                if buy_data.empty or sell_data.empty:
                    stock_profits_detail[select_date_str][clean_code] = None
                    continue

                buy_row = buy_data.iloc[0]
                sell_row = sell_data.iloc[0]

                # 计算盈亏：(t-N+2日收盘价 - t-N+1日开盘价) / t-N+1日开盘价
                buy_open = buy_row['开盘']
                sell_close = sell_row['收盘']

                if buy_open is None or sell_close is None or buy_open == 0:
                    stock_profits_detail[select_date_str][clean_code] = None
                    continue

                profit_pct = ((sell_close - buy_open) / buy_open) * 100
                profits.append(profit_pct)
                # 存储到选股日，而不是卖出日
                stock_profits_detail[select_date_str][clean_code] = profit_pct
                valid_count += 1

            except Exception as e:
                logger.debug(f"计算股票 {clean_code} 在日期 {date_str} 的盈亏时出错: {e}")
                stock_profits_detail[select_date_str][clean_code] = None
                continue

        # 计算平均盈亏
        if profits:
            avg_profit = sum(profits) / len(profits)
            results.append((date_str, avg_profit, valid_count))
        else:
            results.append((date_str, None, valid_count))

    return results, stock_profits_detail
