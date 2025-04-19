from datetime import datetime, timedelta

import pandas as pd
import pandas_market_calendars as mcal


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
    trading_days = remove_holidays(trading_days)

    # 将交易日转换为字符串列表
    trading_days_list = [pd.to_datetime(date).strftime('%Y%m%d') for date in trading_days]

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

        # 获取从输入日期开始的15个交易日（足够找到下一个交易日）
        next_days = sse.valid_days(start_date=date_dt, end_date=date_dt + timedelta(days=15))
        next_days = remove_holidays(next_days)

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
        prev_days = remove_holidays(prev_days)

        # 如果没有找到足够的交易日，返回None
        if len(prev_days) < 2:
            return None

        # 返回前一个交易日
        return prev_days[-2].strftime('%Y%m%d')

    except Exception as e:
        print(f"获取前一个交易日时出错: {str(e)}")
        return None


def remove_holidays(prev_days):
    custom_holidays = [pd.Timestamp('2025-02-04', tz='UTC')]
    prev_days = [day for day in prev_days if day not in custom_holidays]
    return prev_days


def get_n_trading_days_before(date: str, n: int) -> str:
    """
    获取指定日期往前第n个交易日（含自身为第0个）。
    Args:
        date: 日期字符串，格式为 'YYYY-MM-DD' 或 'YYYYMMDD'
        n: 向前推的交易日数量（n=1表示前一个交易日）
    Returns:
        str: 推算得到的交易日，格式为 'YYYY-MM-DD'
    """
    import pandas_market_calendars as mcal
    import pandas as pd

    # 兼容两种日期格式
    if '-' in date:
        date_dt = datetime.strptime(date, '%Y-%m-%d')
    else:
        date_dt = datetime.strptime(date, '%Y%m%d')

    sse = mcal.get_calendar('SSE')
    prev_days = sse.valid_days(start_date=date_dt - timedelta(days=30), end_date=date_dt)
    # 统一为带时区的Timestamp
    date_dt_tz = pd.Timestamp(date_dt, tz='UTC')
    prev_days = [d for d in prev_days if d <= date_dt_tz]
    prev_days = sorted(prev_days)
    if len(prev_days) < n + 1:
        raise ValueError("历史交易日数量不足")
    return prev_days[-(n + 1)].strftime('%Y-%m-%d')