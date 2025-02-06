from datetime import datetime, timedelta

import pandas_market_calendars as mcal
import pandas as pd


def get_trading_days(start_date: str, end_date: str):
    """
    获取开始日期和结束日期之间的所有A股交易日。

    :param start_date: 查询开始日期，格式为'YYYYMMDD'。
    :param end_date: 查询结束日期，格式为'YYYYMMDD'。
    :return: A股交易日列表。
    """
    # 获取A股市场日历，这里以上海证券交易所为例
    sse = mcal.get_calendar('SSE')

    # 将日期字符串转换为datetime对象
    start_date_dt = datetime.strptime(start_date, '%Y%m%d')
    end_date_dt = datetime.strptime(end_date, '%Y%m%d')

    # 获取交易日历
    trading_days = sse.valid_days(start_date=start_date_dt, end_date=end_date_dt)

    # 将交易日转换为字符串列表
    trading_days_list = trading_days.strftime('%Y%m%d').tolist()

    return trading_days_list


def get_next_trading_day(date: str) -> str:
    """
    获取指定日期的下一个交易日
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'
    Returns:
        str: 下一个交易日，格式为 'YYYYMMDD'，如果没有找到则返回None
    """
    try:
        # 将输入日期转换为datetime对象
        date_dt = datetime.strptime(date, '%Y%m%d')
        
        # 获取A股市场日历
        sse = mcal.get_calendar('SSE')
        
        # 获取从输入日期开始的5个交易日（足够找到下一个交易日）
        next_days = sse.valid_days(start_date=date_dt, end_date=date_dt + timedelta(days=5))
        
        # 如果没有找到交易日，返回None
        if len(next_days) < 2:
            return None
            
        # 返回下一个交易日
        return next_days[1].strftime('%Y%m%d')
        
    except Exception as e:
        print(f"获取下一个交易日时出错: {str(e)}")
        return None


def get_prev_trading_day(date: str) -> str:
    """
    获取指定日期的前一个交易日
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'
    Returns:
        str: 前一个交易日，格式为 'YYYYMMDD'，如果没有找到则返回None
    """
    try:
        # 将输入日期转换为datetime对象
        date_dt = datetime.strptime(date, '%Y%m%d')
        
        # 获取A股市场日历
        sse = mcal.get_calendar('SSE')
        
        # 获取从输入日期前15天到输入日期的交易日
        prev_days = sse.valid_days(start_date=date_dt - timedelta(days=15), end_date=date_dt)
        
        # 手动排除特定的节假日日期
        print(prev_days)
        custom_holidays = [pd.Timestamp('2025-02-04', tz='UTC')]
        prev_days = [day for day in prev_days if day not in custom_holidays]
        print(prev_days)
        
        # 如果没有找到足够的交易日，返回None
        if len(prev_days) < 2:
            return None
            
        # 返回前一个交易日
        return prev_days[-2].strftime('%Y%m%d')
        
    except Exception as e:
        print(f"获取前一个交易日时出错: {str(e)}")
        return None