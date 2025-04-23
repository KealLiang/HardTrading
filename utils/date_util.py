from datetime import datetime, timedelta
import re
import pandas as pd
import pandas_market_calendars as mcal
import logging

# 配置logging
logger = logging.getLogger('date_util')

def format_date(date_value):
    """
    将各种格式的日期统一转换为标准的'YYYY-MM-DD'格式。
    
    参数:
        date_value: 日期值，可以是字符串(多种格式)、datetime对象或数字
        
    返回:
        str: 格式化后的日期字符串 'YYYY-MM-DD'，如果无法解析则返回None
    """
    if date_value is None:
        return None
    
    # 处理datetime和pandas Timestamp对象
    if isinstance(date_value, (datetime, pd.Timestamp)):
        return date_value.strftime('%Y-%m-%d')
    
    # 处理整数类型 (如YYYYMMDD格式)
    if isinstance(date_value, (int, float)):
        date_str = str(int(date_value))
        if len(date_str) == 8:
            try:
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            except:
                pass
    
    # 确保是字符串类型
    try:
        date_str = str(date_value).strip() if not isinstance(date_value, str) else date_value.strip()
    except:
        return None
    
    # 已经是YYYY-MM-DD格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
    
    # 使用pandas的to_datetime更高效地解析多种格式
    try:
        return pd.to_datetime(date_str).strftime('%Y-%m-%d')
    except:
        # 如果pandas解析失败，尝试提取数字部分
        date_numbers = re.findall(r'\d+', date_str)
        if len(date_numbers) >= 3:
            try:
                year = int(date_numbers[0])
                month = int(date_numbers[1])
                day = int(date_numbers[2])
                
                # 确保年份格式正确（处理两位数年份）
                if year < 100:
                    year += 2000 if year < 50 else 1900
                
                # 验证日期有效性
                if 1 <= month <= 12 and 1 <= day <= 31:
                    # 使用pandas验证日期是否有效
                    date_obj = pd.Timestamp(year=year, month=month, day=day)
                    return date_obj.strftime('%Y-%m-%d')
            except:
                pass
    
    return None


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