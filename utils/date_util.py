from datetime import datetime

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

    # 将交易日转换为字符串列表
    trading_days_list = trading_days.strftime('%Y%m%d').tolist()

    return trading_days_list
