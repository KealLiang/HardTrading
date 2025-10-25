import logging
import re
from datetime import datetime, timedelta

import pandas as pd

try:
    import pandas_market_calendars as mcal

    # 预先初始化A股交易所日历对象
    SSE_CALENDAR = mcal.get_calendar('SSE')
except ImportError:
    print("警告: pandas_market_calendars 未安装，使用简化的日期处理")
    mcal = None
    SSE_CALENDAR = None

# 交易日缓存
_TRADING_DAYS_CACHE = None
_CACHE_START_DATE = None
_CACHE_END_DATE = None

# 通用搜索窗口与上限
_MAX_LOOKBACK_DAYS = 365  # 回溯上限（天）
_MIN_INITIAL_WINDOW_DAYS = 30  # 初始窗口下限，覆盖常见长假


def _init_trading_days_cache(start_date, end_date):
    """
    初始化交易日缓存
    
    Args:
        start_date: 开始日期 (datetime对象)
        end_date: 结束日期 (datetime对象)
    """
    global _TRADING_DAYS_CACHE, _CACHE_START_DATE, _CACHE_END_DATE

    # 扩大缓存范围，确保有足够的日期可用
    cache_start = start_date - timedelta(days=30)
    cache_end = end_date + timedelta(days=30)

    # 获取A股市场日历
    trading_days = SSE_CALENDAR.valid_days(start_date=cache_start, end_date=cache_end)
    trading_days = remove_holidays(trading_days)

    # 转换为不带时区的日期列表
    _TRADING_DAYS_CACHE = [pd.Timestamp(day).replace(tzinfo=None).date() for day in trading_days]
    _CACHE_START_DATE = cache_start.date()
    _CACHE_END_DATE = cache_end.date()


def remove_holidays(prev_days):
    custom_holidays = [pd.Timestamp('2025-02-04', tz='UTC'), pd.Timestamp('2025-05-05', tz='UTC')]
    prev_days = [day for day in prev_days if day not in custom_holidays]
    return prev_days


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
    if SSE_CALENDAR is None:
        # 简化版本：生成所有工作日（排除周末）
        start_date_dt = datetime.strptime(start_date, '%Y%m%d')
        end_date_dt = datetime.strptime(end_date, '%Y%m%d')

        trading_days = []
        current_date = start_date_dt
        while current_date <= end_date_dt:
            # 排除周末（周六=5，周日=6）
            if current_date.weekday() < 5:
                trading_days.append(current_date)
            current_date += timedelta(days=1)

        return pd.DatetimeIndex(trading_days)

    # 将日期字符串转换为datetime对象
    start_date_dt = datetime.strptime(start_date, '%Y%m%d')
    end_date_dt = datetime.strptime(end_date, '%Y%m%d')

    # 获取交易日历
    trading_days = SSE_CALENDAR.valid_days(start_date=start_date_dt, end_date=end_date_dt)
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

        # 获取从输入日期开始的15个交易日（足够找到下一个交易日）
        next_days = SSE_CALENDAR.valid_days(start_date=date_dt, end_date=date_dt + timedelta(days=15))
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

        # 获取从输入日期前15天到输入日期的交易日
        prev_days = SSE_CALENDAR.valid_days(start_date=date_dt - timedelta(days=15), end_date=date_dt)

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

    # 日历不可用时的简化回退：仅按工作日回溯
    if SSE_CALENDAR is None:
        collected_days = []
        current_dt = date_dt
        looked = 0
        while len(collected_days) < n + 1 and looked <= _MAX_LOOKBACK_DAYS:
            if current_dt.weekday() < 5:  # 周一到周五
                collected_days.append(current_dt)
            current_dt -= timedelta(days=1)
            looked += 1
        if len(collected_days) < n + 1:
            raise ValueError(f"历史交易日数量不足: len={len(collected_days)}, n+1={n + 1}")
        return collected_days[-(n + 1)].strftime('%Y-%m-%d')

    # 使用交易所日历，采用自适应回溯窗口，保证跨长假也能取到足够交易日
    date_dt_tz = pd.Timestamp(date_dt, tz='UTC')
    window_days = max(2 * n + 1, _MIN_INITIAL_WINDOW_DAYS)
    prev_days = []

    while window_days <= _MAX_LOOKBACK_DAYS:
        start_dt = date_dt - timedelta(days=window_days)
        prev_days = SSE_CALENDAR.valid_days(start_date=start_dt, end_date=date_dt)
        prev_days = remove_holidays(prev_days)
        prev_days = [d for d in prev_days if d <= date_dt_tz]
        if len(prev_days) >= n + 1:
            return prev_days[-(n + 1)].strftime('%Y-%m-%d')
        window_days *= 2

    raise ValueError(f"历史交易日数量不足: len={len(prev_days)}, n+1={n + 1}")


def is_trading_day(date: str) -> bool:
    """
    判断指定日期是否为交易日
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'
    Returns:
        bool: 如果是交易日返回True，否则返回False
    """
    try:
        # 将输入日期转换为datetime对象
        date_dt = datetime.strptime(date, '%Y%m%d')

        # 检查输入日期是否为交易日
        check_days = SSE_CALENDAR.valid_days(start_date=date_dt, end_date=date_dt)
        check_days = remove_holidays(check_days)

        return len(check_days) > 0

    except Exception as e:
        logging.error(f"判断是否为交易日时出错: {str(e)}")
        return False


def get_current_or_prev_trading_day(date: str) -> str:
    """
    获取指定日期，如果是交易日则直接返回，否则返回最近的交易日（向前查找）
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'
    Returns:
        str: 交易日，格式为 'YYYYMMDD'，如果没有找到则返回None
    """
    try:
        # 如果是交易日，直接返回
        if is_trading_day(date):
            return date

        # 如果不是交易日，获取最近的交易日（向前查找）
        # 将输入日期转换为datetime对象
        date_dt = datetime.strptime(date, '%Y%m%d')
        
        # 获取从输入日期前15天到输入日期的所有交易日
        prev_days = SSE_CALENDAR.valid_days(start_date=date_dt - timedelta(days=15), end_date=date_dt)
        prev_days = remove_holidays(prev_days)
        
        # 如果没有找到交易日，返回None
        if len(prev_days) < 1:
            return None
        
        # 返回最近的一个交易日（列表最后一个）
        return prev_days[-1].strftime('%Y%m%d')

    except Exception as e:
        logging.error(f"获取当前或最近交易日时出错: {str(e)}")
        return None


def count_trading_days_between(start_date, end_date):
    """
    计算两个日期之间的交易日数量（不包括开始日期，包括结束日期）
    
    Args:
        start_date: 开始日期，格式为 'YYYYMMDD' 或 datetime 对象
        end_date: 结束日期，格式为 'YYYYMMDD' 或 datetime 对象
        
    Returns:
        int: 交易日数量
    """
    global _TRADING_DAYS_CACHE, _CACHE_START_DATE, _CACHE_END_DATE

    try:
        # 确保日期是datetime格式
        if isinstance(start_date, str):
            if '-' in start_date:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            else:
                start_dt = datetime.strptime(start_date, '%Y%m%d')
        else:
            start_dt = start_date

        if isinstance(end_date, str):
            if '-' in end_date:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            else:
                end_dt = datetime.strptime(end_date, '%Y%m%d')
        else:
            end_dt = end_date

        # 如果开始日期晚于结束日期，返回0
        if start_dt >= end_dt:
            return 0

        # 转换为date对象
        start_date = start_dt.date()
        end_date = end_dt.date()

        # 检查是否需要初始化或更新缓存
        if (_TRADING_DAYS_CACHE is None or
                start_date < _CACHE_START_DATE or
                end_date > _CACHE_END_DATE):
            _init_trading_days_cache(start_dt, end_dt)

        # 使用缓存计算交易日数量
        trading_days_between = [day for day in _TRADING_DAYS_CACHE
                                if start_date < day <= end_date]

        return len(trading_days_between)

    except Exception as e:
        print(f"计算交易日数量时出错: {str(e)}")
        return 0


def get_valid_trading_date_pair(end_date: str, n_days: int, stock_df=None, max_shift_days: int = 5) -> tuple:
    """
    获取有效的交易日期对，确保起点和终点都有数据
    
    Args:
        end_date: 结束日期，格式为 'YYYYMMDD'
        n_days: 向前推的交易日数量
        stock_df: 股票数据DataFrame，用于验证数据有效性
        max_shift_days: 最大向前调整的天数，默认为5
        
    Returns:
        tuple: (起点日期, 终点日期) 都是 'YYYYMMDD' 格式，如果找不到则返回 (None, None)
    """
    try:
        # 从基础日期开始，逐步向前调整，寻找有效的日期对
        for shift in range(max_shift_days + 1):
            # 计算调整后的终点日期
            if shift == 0:
                current_end_date = end_date
            else:
                # 向前调整终点日期
                current_end_date = get_n_trading_days_before(end_date, shift)
                if '-' in current_end_date:
                    current_end_date = current_end_date.replace('-', '')

            # 计算对应的起点日期，保持间隔不变
            current_start_date = get_n_trading_days_before(current_end_date, n_days)
            if '-' in current_start_date:
                current_start_date = current_start_date.replace('-', '')

            # 如果没有提供股票数据，直接返回日期对
            if stock_df is None:
                return current_start_date, current_end_date

            # 验证这对日期的数据是否有效
            if _validate_date_pair_data(stock_df, current_start_date, current_end_date):
                return current_start_date, current_end_date

        # 如果所有调整都无效，返回None
        return None, None

    except Exception as e:
        print(f"获取有效交易日期对时出错: {str(e)}")
        return None, None


def _validate_date_pair_data(stock_df, start_date_str, end_date_str):
    """
    验证指定日期对的股票数据是否有效
    
    Args:
        stock_df: 股票数据DataFrame
        start_date_str: 开始日期 (YYYYMMDD)
        end_date_str: 结束日期 (YYYYMMDD)
        
    Returns:
        bool: 数据是否有效
    """
    try:
        # 格式化日期
        start_date_fmt = f"{start_date_str[:4]}-{start_date_str[4:6]}-{start_date_str[6:8]}"
        end_date_fmt = f"{end_date_str[:4]}-{end_date_str[4:6]}-{end_date_str[6:8]}"

        # 查找开始日期和结束日期的数据
        start_row = stock_df[stock_df['日期'] == start_date_fmt]
        end_row = stock_df[stock_df['日期'] == end_date_fmt]

        # 如果没有找到对应日期的数据，尝试查找最接近的日期
        if start_row.empty or end_row.empty:
            all_dates = pd.to_datetime(stock_df['日期'])
            start_date_dt = pd.to_datetime(start_date_fmt)
            end_date_dt = pd.to_datetime(end_date_fmt)

            # 找到不晚于开始日期的最近日期
            if start_row.empty:
                valid_dates = all_dates[all_dates <= start_date_dt]
                if not valid_dates.empty:
                    closest_start_date = valid_dates.max()
                    start_row = stock_df[stock_df['日期'] == closest_start_date.strftime('%Y-%m-%d')]

            # 找到不早于结束日期的最近日期
            if end_row.empty:
                valid_dates = all_dates[all_dates >= end_date_dt]
                if not valid_dates.empty:
                    closest_end_date = valid_dates.min()
                    end_row = stock_df[stock_df['日期'] == closest_end_date.strftime('%Y-%m-%d')]

        # 检查是否找到了数据
        if start_row.empty or end_row.empty:
            return False

        # 获取价格数据
        start_price = start_row['开盘'].values[0]
        end_price = end_row['收盘'].values[0]

        # 检查价格数据是否有效
        if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0 or end_price <= 0:
            return False

        return True

    except Exception:
        return False
