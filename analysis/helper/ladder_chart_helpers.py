"""
ladder_chart_helpers.py
涨停梯队图计算辅助函数模块

包含以下功能：
- 股票数据获取和缓存
- 成交量比计算
- 新高标记计算
- 均线斜率计算
- 跟踪判断逻辑
- 炸板格式缓存
"""

from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd

from utils.date_util import count_trading_days_between, get_n_trading_days_before
from utils.file_util import read_stock_data

# ==================== 成交量分析相关参数 ====================
# 计算成交量比的天数，当天成交量与前X天平均成交量的比值
VOLUME_DAYS = 4
# 成交量比阈值，超过该值则在单元格中显示成交量比
VOLUME_RATIO_THRESHOLD = 2.2
# 成交量比低阈值，低于该值则在单元格中显示成交量比
VOLUME_RATIO_LOW_THRESHOLD = 0.4

# ==================== 新高分析相关参数 ====================
# 计算新高的天数，当天收盘价与前X天最高价的比较
NEW_HIGH_DAYS = 200
# 新高标记符号
NEW_HIGH_MARKER = '!!'

# ==================== 均线斜率分析相关参数 ====================
# 是否启用双均线趋势判断（同时考虑5日和10日均线）
ENABLE_DUAL_MA_TREND = True  # True=使用双均线判断（更严格），False=仅使用5日均线（原逻辑）
# 短周期均线的天数（趋势强度）
MA_SLOPE_DAYS = 5
# 长周期均线天数（趋势确认，用于双均线趋势判断）
MA_SLOPE_DAYS_LONG = 10
# 短周期均线斜率阈值（5日均线），只有相对变化超过此阈值才显示趋势标记，定量
MA_SLOPE_THRESHOLD_PCT = 2.0  # 单位：%，短周期均线日变化率阈值
# 长周期均线斜率阈值（10日均线），长周期变化相对较慢，定性
MA_SLOPE_THRESHOLD_PCT_LONG = 1.0  # 单位：%，长周期均线日变化率阈值
# 斜率计算使用的均线点数量（用于提高稳定性，避免单日波动影响）
MA_SLOPE_POINTS = 3  # 使用最近N个均线点计算斜率，建议3-5个点

# ==================== 高涨幅跟踪相关参数 ====================
# 持续跟踪的涨幅阈值，如果股票在PERIOD_DAYS_CHANGE天内涨幅超过此值，即便没有涨停也会继续跟踪
HIGH_GAIN_TRACKING_THRESHOLD = 15.0

# ==================== 日内涨跌幅标记相关参数 ====================
# 日内涨幅阈值，超过此值字体标深红色
INTRADAY_GAIN_THRESHOLD = 7.0
# 日内跌幅阈值，低于此值字体标深橄榄色（负数）
INTRADAY_DROP_THRESHOLD = -7.0

# ==================== 折叠相关参数 ====================
# 断板后折叠行的天数阈值，超过这个天数的股票会在Excel中自动折叠（隐藏）
# 设置为None表示不自动折叠任何行
COLLAPSE_DAYS_AFTER_BREAK = 12

# ==================== 缓存变量 ====================
# 高涨幅计算缓存，避免重复计算
_high_gain_cache = {}

# 新高标记缓存，避免重复计算
_new_high_markers_cache = None

# 均线斜率缓存
_ma_slope_cache = {}

# 斜率统计信息（用于分析和调试）
_slope_stats = {'min': float('inf'), 'max': float('-inf'), 'count': 0, 'sum': 0}

# 炸板格式缓存，用于在A和B sheet之间共享炸板格式信息
_zaban_format_cache = {}


# ==================== 缓存管理函数 ====================

def clear_helper_caches():
    """清理本模块的所有缓存"""
    global _high_gain_cache, _new_high_markers_cache, _ma_slope_cache, _slope_stats, _zaban_format_cache
    _high_gain_cache.clear()
    _new_high_markers_cache = None
    _ma_slope_cache.clear()
    _slope_stats = {'min': float('inf'), 'max': float('-inf'), 'count': 0, 'sum': 0}
    _zaban_format_cache.clear()


def cache_zaban_format(stock_code, formatted_day, is_zaban):
    """
    缓存炸板格式信息

    Args:
        stock_code: 股票代码
        formatted_day: 格式化的日期
        is_zaban: 是否为炸板
    """
    global _zaban_format_cache
    key = f"{stock_code}_{formatted_day}"
    _zaban_format_cache[key] = is_zaban


def get_cached_zaban_format(stock_code, formatted_day):
    """
    获取缓存的炸板格式信息

    Args:
        stock_code: 股票代码
        formatted_day: 格式化的日期

    Returns:
        bool: 是否为炸板，如果缓存中没有则返回None
    """
    global _zaban_format_cache
    key = f"{stock_code}_{formatted_day}"
    return _zaban_format_cache.get(key)


# ==================== 股票数据获取函数 ====================

@lru_cache(maxsize=1000)
def get_stock_data_df(stock_code):
    """缓存股票文件读取结果"""
    return read_stock_data(stock_code)


@lru_cache(maxsize=1000)
def get_stock_data(stock_code, date_str_yyyymmdd):
    """
    获取指定股票在特定日期的数据，使用缓存避免重复读取文件

    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)

    Returns:
        tuple: (DataFrame, 目标行, 目标索引) 如果数据不存在则返回(None, None, None)
    """
    try:
        if not stock_code:
            return None, None, None

        # 目标日期（YYYY-MM-DD格式）
        target_date = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"

        df = get_stock_data_df(stock_code)

        # 如果没有找到文件
        if df is None:
            return None, None, None

        # 查找目标日期的数据
        target_row = df[df['日期'] == target_date]

        # 如果找到数据
        if not target_row.empty:
            # 获取目标日期的索引
            target_idx = df[df['日期'] == target_date].index[0]
            return df, target_row, target_idx

        # 如果没有找到对应日期的数据
        return df, None, None

    except Exception as e:
        print(f"获取股票 {stock_code} 在 {date_str_yyyymmdd} 的数据时出错: {e}")
        return None, None, None


def get_stock_daily_pct_change(stock_code, date_str_yyyymmdd):
    """
    获取指定股票在特定日期的涨跌幅

    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)

    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
    """
    _, target_row, _ = get_stock_data(stock_code, date_str_yyyymmdd)

    if target_row is not None and not target_row.empty:
        return target_row['涨跌幅'].values[0]

    return None


def get_intraday_pct_change(stock_code, date_str_yyyymmdd):
    """
    获取指定股票在特定日期的日内涨跌幅
    日内涨跌幅 = (收盘价 - 开盘价) / 开盘价 × 100%

    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)

    Returns:
        float: 日内涨跌幅百分比，如果数据不存在则返回None
    """
    _, target_row, _ = get_stock_data(stock_code, date_str_yyyymmdd)

    if target_row is not None and not target_row.empty:
        try:
            open_price = target_row['开盘'].values[0]
            close_price = target_row['收盘'].values[0]
            if open_price > 0:
                return (close_price - open_price) / open_price * 100
        except (KeyError, IndexError):
            pass

    return None


# ==================== 成交量比相关函数 ====================

def get_volume_ratio(stock_code, date_str_yyyymmdd):
    """
    获取指定股票在特定日期的成交量比(当天成交量/前N天平均成交量)

    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)

    Returns:
        tuple: (成交量比, 是否超过高阈值, 是否低于低阈值) 如果数据不存在则返回(None, False, False)
    """
    df, target_row, target_idx = get_stock_data(stock_code, date_str_yyyymmdd)

    if df is None or target_row is None or target_row.empty:
        return None, False, False

    try:
        # 获取当天成交量
        current_volume = target_row['成交量'].values[0]

        # 确保有足够的历史数据来计算平均成交量
        if target_idx >= VOLUME_DAYS:
            # 获取前VOLUME_DAYS天的数据
            prev_volumes = df.iloc[target_idx - VOLUME_DAYS:target_idx]['成交量'].values

            # 计算平均成交量
            avg_volume = prev_volumes.mean()

            # 计算成交量比
            if avg_volume > 0:
                volume_ratio = current_volume / avg_volume

                # 判断是否超过高阈值或低于低阈值
                is_high_volume = volume_ratio >= VOLUME_RATIO_THRESHOLD
                is_low_volume = volume_ratio <= VOLUME_RATIO_LOW_THRESHOLD

                return volume_ratio, is_high_volume, is_low_volume

    except Exception as e:
        print(f"计算股票 {stock_code} 在 {date_str_yyyymmdd} 的成交量比时出错: {e}")

    return None, False, False


def add_volume_ratio_to_text(text, stock_code, date_str_yyyymmdd):
    """
    根据成交量比向文本添加成交量信息

    Args:
        text: 原始文本
        stock_code: 股票代码
        date_str_yyyymmdd: 日期字符串(YYYYMMDD格式)

    Returns:
        str: 添加成交量信息后的文本
    """
    volume_ratio, is_high_volume, is_low_volume = get_volume_ratio(stock_code, date_str_yyyymmdd)

    if volume_ratio is not None and (is_high_volume or is_low_volume):
        return f"{text}[{volume_ratio:.1f}]"

    return text


# ==================== 新高标记相关函数 ====================

def is_new_high(stock_code, date_str_yyyymmdd, days=NEW_HIGH_DAYS):
    """
    检查指定股票在特定日期是否突破新高

    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 日期字符串(YYYYMMDD格式)
        days: 检查新高的天数，默认为NEW_HIGH_DAYS

    Returns:
        bool: 是否突破新高
    """
    try:
        # 读取股票数据
        stock_data = get_stock_data_df(stock_code)
        if stock_data is None or stock_data.empty:
            return False

        # 将日期字符串转换为datetime格式，然后转为字符串格式匹配数据
        target_date_str = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"

        # 找到目标日期的数据
        target_row = stock_data[stock_data['日期'] == target_date_str]
        if target_row.empty:
            return False

        target_idx = target_row.index[0]
        current_close = target_row['收盘'].values[0]

        # 确保有足够的历史数据
        if target_idx < days:
            # 如果历史数据不足，使用所有可用的历史数据
            historical_data = stock_data.iloc[:target_idx]
        else:
            # 获取前days天的数据
            historical_data = stock_data.iloc[target_idx - days:target_idx]

        if historical_data.empty:
            return False

        # 获取历史最高价
        historical_high = historical_data['最高'].max()

        # 判断是否突破新高（当前收盘价大于历史最高价）
        return current_close > historical_high

    except Exception as e:
        print(f"检查股票 {stock_code} 在 {date_str_yyyymmdd} 是否突破新高时出错: {e}")
        return False


def is_new_high_cached(stock_data, date_str_yyyymmdd, days=NEW_HIGH_DAYS):
    """
    使用缓存的股票数据检查是否突破新高（性能优化版）

    Args:
        stock_data: 已缓存的股票数据DataFrame
        date_str_yyyymmdd: 日期字符串(YYYYMMDD格式)
        days: 检查新高的天数，默认为NEW_HIGH_DAYS

    Returns:
        bool: 是否突破新高
    """
    try:
        if stock_data is None or stock_data.empty:
            return False

        # 将日期字符串转换为匹配格式
        target_date_str = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"

        # 找到目标日期的数据
        target_row = stock_data[stock_data['日期'] == target_date_str]
        if target_row.empty:
            return False

        target_idx = target_row.index[0]
        current_close = target_row['收盘'].values[0]

        # 确保有足够的历史数据
        if target_idx < days:
            # 如果历史数据不足，使用所有可用的历史数据
            historical_data = stock_data.iloc[:target_idx]
        else:
            # 获取前days天的数据
            historical_data = stock_data.iloc[target_idx - days:target_idx]

        if historical_data.empty:
            return False

        # 获取历史最高价
        historical_high = historical_data['最高'].max()

        # 判断是否突破新高（当前收盘价大于历史最高价）
        return current_close > historical_high

    except Exception:
        # 静默处理错误，避免大量错误输出影响性能
        return False


def calculate_new_high_markers(result_df, formatted_trading_days, date_mapping):
    """
    计算每只股票的新高标记日期（优化版）

    Args:
        result_df: 显著连板股票DataFrame
        formatted_trading_days: 格式化的交易日列表
        date_mapping: 日期映射

    Returns:
        dict: 股票代码到新高标记日期的映射 {stock_code: formatted_date}
    """
    new_high_markers = {}
    stock_data_cache = {}  # 缓存股票数据，避免重复读取

    print(f"开始计算{len(result_df)}只股票的新高标记...")

    for idx, (_, stock) in enumerate(result_df.iterrows()):
        if idx % 50 == 0:  # 每50只股票打印一次进度
            print(f"新高标记计算进度: {idx}/{len(result_df)}")

        stock_code = stock['stock_code']
        pure_stock_code = stock_code.split('_')[0] if '_' in stock_code else stock_code
        if pure_stock_code.startswith(('sh', 'sz', 'bj')):
            pure_stock_code = pure_stock_code[2:]

        # 缓存股票数据
        if pure_stock_code not in stock_data_cache:
            stock_data_cache[pure_stock_code] = get_stock_data_df(pure_stock_code)

        stock_data = stock_data_cache[pure_stock_code]
        if stock_data is None or stock_data.empty:
            continue

        latest_new_high_date = None

        # 只检查跟踪期内的交易日，避免非跟踪日出现标记
        for formatted_day in formatted_trading_days:
            date_yyyymmdd = date_mapping.get(formatted_day)
            if date_yyyymmdd and is_new_high_cached(stock_data, date_yyyymmdd):
                latest_new_high_date = formatted_day

        if latest_new_high_date:
            new_high_markers[stock_code] = latest_new_high_date

    print(f"新高标记计算完成，共找到{len(new_high_markers)}只股票有新高标记")
    return new_high_markers


def calculate_new_high_markers_fast(result_df, formatted_trading_days, date_mapping):
    """
    快速计算新高标记（进一步优化版）

    Args:
        result_df: 显著连板股票DataFrame
        formatted_trading_days: 格式化的交易日列表
        date_mapping: 日期映射

    Returns:
        dict: 股票代码到新高标记日期的映射 {stock_code: formatted_date}
    """
    new_high_markers = {}

    # 预处理：提取所有需要的股票代码
    stock_codes = set()
    stock_code_mapping = {}  # 完整代码到纯代码的映射

    for _, stock in result_df.iterrows():
        stock_code = stock['stock_code']
        pure_stock_code = stock_code.split('_')[0] if '_' in stock_code else stock_code
        if pure_stock_code.startswith(('sh', 'sz', 'bj')):
            pure_stock_code = pure_stock_code[2:]

        stock_codes.add(pure_stock_code)
        stock_code_mapping[stock_code] = pure_stock_code

    print(f"开始批量加载{len(stock_codes)}只股票的数据...")

    # 批量加载股票数据
    stock_data_cache = {}
    loaded_count = 0
    for pure_code in stock_codes:
        stock_data_cache[pure_code] = get_stock_data_df(pure_code)
        loaded_count += 1
        if loaded_count % 100 == 0:
            print(f"数据加载进度: {loaded_count}/{len(stock_codes)}")

    print(f"开始计算{len(result_df)}只股票的新高标记...")

    # 批量计算新高标记
    for idx, (_, stock) in enumerate(result_df.iterrows()):
        if idx % 100 == 0:  # 每100只股票打印一次进度
            print(f"新高标记计算进度: {idx}/{len(result_df)}")

        stock_code = stock['stock_code']
        pure_stock_code = stock_code_mapping[stock_code]

        stock_data = stock_data_cache.get(pure_stock_code)
        if stock_data is None or stock_data.empty:
            continue

        latest_new_high_date = None

        # 只检查跟踪期内的交易日
        for formatted_day in formatted_trading_days:
            date_yyyymmdd = date_mapping.get(formatted_day)
            if date_yyyymmdd and is_new_high_cached(stock_data, date_yyyymmdd):
                latest_new_high_date = formatted_day

        if latest_new_high_date:
            new_high_markers[stock_code] = latest_new_high_date

    print(f"新高标记计算完成，共找到{len(new_high_markers)}只股票有新高标记")
    return new_high_markers


def get_new_high_markers_cached(result_df, formatted_trading_days, date_mapping):
    """
    获取缓存的新高标记，如果没有缓存则计算

    Args:
        result_df: 显著连板股票DataFrame
        formatted_trading_days: 格式化的交易日列表
        date_mapping: 日期映射

    Returns:
        dict: 股票代码到新高标记日期的映射
    """
    global _new_high_markers_cache

    if _new_high_markers_cache is None:
        _new_high_markers_cache = calculate_new_high_markers_fast(result_df, formatted_trading_days, date_mapping)

    return _new_high_markers_cache


# ==================== 均线斜率相关函数 ====================

def get_ma_value(stock_code, end_date_yyyymmdd, ma_days=MA_SLOPE_DAYS):
    """
    获取股票在指定日期的N日均线值
    
    Args:
        stock_code: 股票代码
        end_date_yyyymmdd: 结束日期 (YYYYMMDD格式)
        ma_days: 均线天数，默认为MA_SLOPE_DAYS
        
    Returns:
        float: 均线值，None表示数据不足
    """
    try:
        # 获取股票数据
        df = get_stock_data_df(stock_code)
        if df is None or df.empty:
            return None

        # 转换结束日期格式
        end_date_str = f"{end_date_yyyymmdd[:4]}-{end_date_yyyymmdd[4:6]}-{end_date_yyyymmdd[6:8]}"

        # 找到结束日期的位置
        end_row = df[df['日期'] == end_date_str]
        if end_row.empty:
            # 如果找不到确切日期，找最接近的日期
            all_dates = pd.to_datetime(df['日期'])
            end_date_dt = pd.to_datetime(end_date_str)
            valid_dates = all_dates[all_dates <= end_date_dt]
            if valid_dates.empty:
                return None
            closest_date = valid_dates.max()
            end_idx = df[df['日期'] == closest_date.strftime('%Y-%m-%d')].index[0]
        else:
            end_idx = end_row.index[0]

        # 确保有足够的数据计算均线
        if end_idx < ma_days - 1:
            return None

        # 获取用于计算的数据段
        data_segment = df.iloc[end_idx - ma_days + 1:end_idx + 1]

        # 计算均线
        ma_value = data_segment['收盘'].mean()
        return ma_value

    except Exception as e:
        return None


def calculate_ma_slope(stock_code, end_date_yyyymmdd, ma_days=MA_SLOPE_DAYS):
    """
    计算股票N日均线的斜率（百分比变化率）
    
    使用最近MA_SLOPE_POINTS个均线点（默认3个）进行线性回归计算斜率：
    - 使用numpy.polyfit进行线性回归，拟合最佳直线
    - 计算拟合直线的斜率，转换为百分比变化率
    - 这样可以减少单日波动的影响，更准确地反映整体趋势
    
    相比简单的两点比较，线性回归的优势：
    1. 考虑所有数据点，而非仅首尾两点
    2. 通过最小二乘法找到最佳拟合直线
    3. 对异常值有更好的鲁棒性
    
    如果线性回归失败（如数据点共线），会回退到简单方法。

    Args:
        stock_code: 股票代码
        end_date_yyyymmdd: 结束日期 (YYYYMMDD格式)
        ma_days: 均线天数，默认为MA_SLOPE_DAYS

    Returns:
        float: 均线日变化率（%），正数表示上升，负数表示下降，None表示数据不足
    """
    global _ma_slope_cache, _slope_stats

    try:
        # 创建缓存键
        cache_key = f"{stock_code}_{end_date_yyyymmdd}_{ma_days}"

        # 检查缓存
        if cache_key in _ma_slope_cache:
            return _ma_slope_cache[cache_key]

        # 获取股票数据
        df = get_stock_data_df(stock_code)
        if df is None or df.empty:
            _ma_slope_cache[cache_key] = None
            return None

        # 转换结束日期格式
        end_date_str = f"{end_date_yyyymmdd[:4]}-{end_date_yyyymmdd[4:6]}-{end_date_yyyymmdd[6:8]}"

        # 找到结束日期的位置
        end_row = df[df['日期'] == end_date_str]
        if end_row.empty:
            # 如果找不到确切日期，找最接近的日期
            all_dates = pd.to_datetime(df['日期'])
            end_date_dt = pd.to_datetime(end_date_str)
            valid_dates = all_dates[all_dates <= end_date_dt]
            if valid_dates.empty:
                _ma_slope_cache[cache_key] = None
                return None
            closest_date = valid_dates.max()
            end_idx = df[df['日期'] == closest_date.strftime('%Y-%m-%d')].index[0]
        else:
            end_idx = end_row.index[0]

        # 确保有足够的数据计算均线和斜率
        # 需要至少ma_days + 2天的数据来计算斜率（至少需要2个均线点）
        min_required_days = ma_days + 2
        if end_idx < min_required_days - 1:
            _ma_slope_cache[cache_key] = None
            return None

        # 获取用于计算的数据段
        data_segment = df.iloc[end_idx - min_required_days + 1:end_idx + 1]

        # 计算均线
        data_segment = data_segment.copy()
        data_segment['ma'] = data_segment['收盘'].rolling(window=ma_days).mean()

        # 获取有效的均线数据（去除NaN）
        ma_data = data_segment['ma'].dropna()
        if len(ma_data) < 2:
            _ma_slope_cache[cache_key] = None
            return None

        # 计算斜率：使用最近N个均线点进行线性回归，提高稳定性
        # 取最近MA_SLOPE_POINTS个均线值（如果不足则使用全部）
        recent_ma_points = ma_data.iloc[-min(MA_SLOPE_POINTS, len(ma_data)):].values

        if len(recent_ma_points) < 2:
            _ma_slope_cache[cache_key] = None
            return None

        # 使用numpy的线性回归计算斜率（更科学准确）
        # x轴：时间点索引 [0, 1, 2, ...]
        # y轴：均线值
        x = np.arange(len(recent_ma_points))
        y = recent_ma_points

        # 使用numpy.polyfit进行线性回归，返回[斜率, 截距]
        # 如果数据点较少或方差为0，使用简单方法作为备选
        try:
            # 计算线性回归
            coeffs = np.polyfit(x, y, 1)  # 1次多项式（线性）
            slope = coeffs[0]  # 斜率（绝对变化量）

            # 转换为百分比变化率（相对于第一个均线值）
            if recent_ma_points[0] != 0:
                slope_pct = (slope / recent_ma_points[0]) * 100
            else:
                # 如果第一个值为0，使用最后一个值作为基准
                if recent_ma_points[-1] != 0:
                    slope_pct = (slope / recent_ma_points[-1]) * 100
                else:
                    slope_pct = 0.0
        except (np.linalg.LinAlgError, ValueError):
            # 如果线性回归失败（如数据点共线或方差为0），回退到简单方法
            if len(recent_ma_points) == 2:
                current_ma = recent_ma_points[-1]
                previous_ma = recent_ma_points[-2]
                if previous_ma != 0:
                    slope_pct = ((current_ma - previous_ma) / previous_ma) * 100
                else:
                    slope_pct = 0.0
            else:
                # 多个点时，使用首尾两点的变化率
                first_ma = recent_ma_points[0]
                last_ma = recent_ma_points[-1]
                if first_ma != 0:
                    slope_pct = ((last_ma - first_ma) / first_ma) * 100 / (len(recent_ma_points) - 1)
                else:
                    slope_pct = 0.0

        # 更新斜率统计信息
        _slope_stats['min'] = min(_slope_stats['min'], slope_pct)
        _slope_stats['max'] = max(_slope_stats['max'], slope_pct)
        _slope_stats['count'] += 1
        _slope_stats['sum'] += slope_pct

        # 缓存结果
        _ma_slope_cache[cache_key] = slope_pct
        return slope_pct

    except Exception as e:
        print(f"计算股票 {stock_code} 在 {end_date_yyyymmdd} 的均线斜率时出错: {e}")
        _ma_slope_cache[cache_key] = None
        return None


def get_ma_slope_indicator(stock_code, end_date_yyyymmdd, ma_days=MA_SLOPE_DAYS):
    """
    获取均线斜率指示符

    Args:
        stock_code: 股票代码
        end_date_yyyymmdd: 结束日期 (YYYYMMDD格式)
        ma_days: 均线天数，默认为MA_SLOPE_DAYS

    Returns:
        str: '↑' 表示明显上升趋势，'↓' 表示明显下降趋势，'' 表示数据不足或趋势不明显
    """
    slope_pct = calculate_ma_slope(stock_code, end_date_yyyymmdd, ma_days)

    if slope_pct is None:
        return ''  # 数据不足时不显示标记

    # 只有当斜率的绝对值超过百分比阈值时才显示标记
    if abs(slope_pct) < MA_SLOPE_THRESHOLD_PCT:
        return ''  # 趋势不够明显，不显示标记
    elif slope_pct > 0:
        return '↑'  # 明显上升趋势
    else:
        return '↓'  # 明显下降趋势


def is_ma_trend_rising(stock_code, end_date_yyyymmdd, ma_days=MA_SLOPE_DAYS):
    """
    判断股票是否处于明显上升趋势（用于筛选逻辑）
    
    如果启用双均线判断（ENABLE_DUAL_MA_TREND=True），则同时考虑5日和10日均线：
    - 5日均线斜率向上（>=MA_SLOPE_THRESHOLD_PCT，默认2%）
    - 10日均线斜率向上（>=MA_SLOPE_THRESHOLD_PCT_LONG，默认1.2%）
    - 5日均线在10日均线上方（多头排列）
    
    如果未启用双均线判断，则仅使用5日均线斜率判断（原逻辑）

    Args:
        stock_code: 股票代码
        end_date_yyyymmdd: 结束日期 (YYYYMMDD格式)
        ma_days: 均线天数，默认为MA_SLOPE_DAYS（兼容旧接口）

    Returns:
        bool: True表示明显上升趋势，False表示非上升趋势（包括数据不足、趋势不明显或下降）
    """
    if not ENABLE_DUAL_MA_TREND:
        # 原逻辑：仅使用5日均线
        slope_pct = calculate_ma_slope(stock_code, end_date_yyyymmdd, ma_days)
        if slope_pct is None:
            return False
        return slope_pct >= MA_SLOPE_THRESHOLD_PCT

    # 双均线判断逻辑
    # 1. 5日均线斜率向上（使用短周期阈值）
    slope_5 = calculate_ma_slope(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS)
    if slope_5 is None or slope_5 < MA_SLOPE_THRESHOLD_PCT:
        return False

    # 2. 10日均线斜率向上（使用长周期阈值）
    slope_10 = calculate_ma_slope(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS_LONG)
    if slope_10 is None or slope_10 < MA_SLOPE_THRESHOLD_PCT_LONG:
        return False

    # 3. 多头排列：5日均线在10日均线上方
    ma_5 = get_ma_value(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS)
    ma_10 = get_ma_value(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS_LONG)
    if ma_5 is None or ma_10 is None:
        return False

    if ma_5 <= ma_10:
        return False  # 不是多头排列

    return True


def is_ma_trend_falling(stock_code, end_date_yyyymmdd, ma_days=MA_SLOPE_DAYS):
    """
    判断股票是否处于明显下降趋势（用于筛选逻辑）
    
    如果启用双均线判断（ENABLE_DUAL_MA_TREND=True），则同时考虑5日和10日均线：
    - 5日均线斜率向下（<=-MA_SLOPE_THRESHOLD_PCT，默认-2%）
    - 10日均线斜率向下（<=-MA_SLOPE_THRESHOLD_PCT_LONG，默认-1.2%）
    - 5日均线在10日均线下方（空头排列）
    
    如果未启用双均线判断，则仅使用5日均线斜率判断（原逻辑）

    Args:
        stock_code: 股票代码
        end_date_yyyymmdd: 结束日期 (YYYYMMDD格式)
        ma_days: 均线天数，默认为MA_SLOPE_DAYS（兼容旧接口）

    Returns:
        bool: True表示明显下降趋势，False表示非下降趋势（包括数据不足、趋势不明显或上升）
    """
    if not ENABLE_DUAL_MA_TREND:
        # 原逻辑：仅使用5日均线
        slope_pct = calculate_ma_slope(stock_code, end_date_yyyymmdd, ma_days)
        if slope_pct is None:
            return False
        return slope_pct <= -MA_SLOPE_THRESHOLD_PCT

    # 双均线判断逻辑
    # 1. 5日均线斜率向下（使用短周期阈值）
    slope_5 = calculate_ma_slope(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS)
    if slope_5 is None or slope_5 > -MA_SLOPE_THRESHOLD_PCT:
        return False

    # 2. 10日均线斜率向下（使用长周期阈值）
    slope_10 = calculate_ma_slope(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS_LONG)
    if slope_10 is None or slope_10 > -MA_SLOPE_THRESHOLD_PCT_LONG:
        return False

    # 3. 空头排列：5日均线在10日均线下方
    ma_5 = get_ma_value(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS)
    ma_10 = get_ma_value(stock_code, end_date_yyyymmdd, MA_SLOPE_DAYS_LONG)
    if ma_5 is None or ma_10 is None:
        return False

    if ma_5 >= ma_10:
        return False  # 不是空头排列

    return True


def clear_ma_slope_cache():
    """
    清理均线斜率计算缓存，释放内存
    """
    global _ma_slope_cache
    _ma_slope_cache.clear()


def print_slope_statistics():
    """
    打印均线斜率的统计信息，帮助分析合适的阈值
    """
    global _slope_stats

    if _slope_stats['count'] == 0:
        print("📊 均线斜率统计：无数据")
        return

    avg_slope = _slope_stats['sum'] / _slope_stats['count']

    print(f"📊 均线斜率统计信息 (基于{_slope_stats['count']}个样本):")
    print(f"   最小值: {_slope_stats['min']:.4f}%")
    print(f"   最大值: {_slope_stats['max']:.4f}%")
    print(f"   平均值: {avg_slope:.4f}%")
    print(f"   当前阈值: ±{MA_SLOPE_THRESHOLD_PCT:.2f}% (绝对值小于此值不显示标记)")

    # 计算在当前阈值下会显示标记的比例
    if _slope_stats['count'] > 0:
        # 这里只是估算，实际需要遍历所有计算过的斜率值
        range_width = _slope_stats['max'] - _slope_stats['min']
        threshold_range = 2 * MA_SLOPE_THRESHOLD_PCT  # 上下阈值范围
        estimated_filtered_ratio = max(0, (range_width - threshold_range) / range_width) if range_width > 0 else 0
        print(f"   预估显示标记比例: {estimated_filtered_ratio:.1%}")

    print(f"   💡 建议：如果希望过滤更多噪音，可增大MA_SLOPE_THRESHOLD_PCT值")


# ==================== 高涨幅跟踪相关函数 ====================

def should_track_high_gain_stock(stock_code, current_date_obj, period_days, calculate_period_change_func):
    """
    判断是否应该跟踪高涨幅股票（即便没有涨停）

    优化策略：
    1. 使用缓存避免重复计算
    2. 缓存键包含股票代码、日期和周期天数

    Args:
        stock_code: 股票代码
        current_date_obj: 当前日期对象
        period_days: 计算涨跌幅的周期天数
        calculate_period_change_func: 计算周期涨跌幅的函数

    Returns:
        bool: 是否应该跟踪
    """
    global _high_gain_cache

    try:
        current_date_str = current_date_obj.strftime('%Y%m%d')

        # 创建缓存键
        cache_key = f"{stock_code}_{current_date_str}_{period_days}"

        # 检查缓存
        if cache_key in _high_gain_cache:
            return _high_gain_cache[cache_key]

        # 计算当前日期前period_days个交易日的开始日期
        start_date = get_n_trading_days_before(current_date_str, period_days)

        if '-' in start_date:
            start_date = start_date.replace('-', '')

        # 计算期间涨跌幅
        period_change = calculate_period_change_func(stock_code, start_date, current_date_str)

        # 判断是否超过阈值
        result = period_change is not None and period_change >= HIGH_GAIN_TRACKING_THRESHOLD

        # 缓存结果
        _high_gain_cache[cache_key] = result

        return result

    except Exception:
        # 如果计算出错，缓存False结果，不影响正常跟踪逻辑
        _high_gain_cache[cache_key] = False
        return False


def clear_high_gain_cache():
    """
    清理高涨幅计算缓存，释放内存
    """
    global _high_gain_cache
    _high_gain_cache.clear()


def should_track_after_break(stock, current_date_obj, max_tracking_days, period_days, calculate_period_change_func):
    """
    判断是否应该跟踪断板后的股票

    现在不仅跟踪断板后的连板股，也跟踪持续高涨幅的非涨停股票

    Args:
        stock: 股票数据
        current_date_obj: 当前日期对象
        max_tracking_days: 断板后跟踪的最大天数
        period_days: 计算涨跌幅的周期天数
        calculate_period_change_func: 计算周期涨跌幅的函数

    Returns:
        bool: 是否应该跟踪
    """
    # 如果没有设置最大跟踪天数，始终跟踪
    if max_tracking_days is None:
        return True

    # 优先检查传统的连板跟踪逻辑
    last_board_date = stock.get('last_board_date')
    if last_board_date:
        # 计算当前日期与最后连板日期的交易日天数差
        days_after_break = count_trading_days_between(last_board_date, current_date_obj)
        # 如果在跟踪期限内，直接返回True，无需计算涨跌幅
        if days_after_break <= max_tracking_days:
            return True
        # 如果超过跟踪期限，检查是否为高涨幅股票
        elif should_track_high_gain_stock(stock['stock_code'], current_date_obj, period_days,
                                          calculate_period_change_func):
            return True
        else:
            return False

    # 如果没有连板记录，检查是否为高涨幅股票
    return should_track_high_gain_stock(stock['stock_code'], current_date_obj, period_days,
                                        calculate_period_change_func)


def should_track_before_entry(current_date_obj, entry_date, max_tracking_days_before):
    """
    判断是否应该跟踪入选前的股票

    Args:
        current_date_obj: 当前日期对象
        entry_date: 入选日期对象
        max_tracking_days_before: 入选前跟踪的最大天数

    Returns:
        bool: 是否应该跟踪
    """
    # 如果不跟踪入选前的走势
    if max_tracking_days_before <= 0:
        return False

    # 计算当前日期与首次显著连板日期的交易日天数差
    days_before_entry = count_trading_days_between(current_date_obj, entry_date)

    # 如果在入选前跟踪天数范围内，显示涨跌幅
    return 1 <= days_before_entry <= max_tracking_days_before


def calculate_last_board_date(stock, formatted_trading_days):
    """
    计算股票的最后连板日期（遍历所有交易日，找到最后一次有连板数据的日期）

    Args:
        stock: 股票数据（需包含all_board_data字段）
        formatted_trading_days: 格式化的交易日列表

    Returns:
        datetime: 最后连板日期，如果没有连板记录则返回None
    """
    all_board_data = stock.get('all_board_data', {})
    last_board_date = None

    for formatted_day in formatted_trading_days:
        board_days = all_board_data.get(formatted_day)
        if pd.notna(board_days) and board_days:
            # 解析日期
            try:
                if '年' in formatted_day:
                    current_date = datetime.strptime(formatted_day, '%Y年%m月%d日')
                else:
                    current_date = datetime.strptime(formatted_day, '%Y/%m/%d')
                last_board_date = current_date
            except:
                continue

    return last_board_date


def should_collapse_row(stock, formatted_trading_days, date_mapping, collapse_days=None):
    """
    判断是否应该折叠此行（在Excel中隐藏）

    Args:
        stock: 股票数据
        formatted_trading_days: 格式化的交易日列表
        date_mapping: 日期映射
        collapse_days: 折叠天数阈值，默认使用模块常量

    Returns:
        bool: 是否应该折叠此行
    """
    # 使用传入的参数或默认常量
    collapse_threshold = collapse_days if collapse_days is not None else COLLAPSE_DAYS_AFTER_BREAK

    # 如果未设置折叠天数，不折叠
    if collapse_threshold is None:
        return False

    # 获取最后一次连板的日期
    last_board_date = stock.get('last_board_date')
    if not last_board_date:
        return False

    # 获取分析周期的结束日期
    try:
        end_date_str = date_mapping.get(formatted_trading_days[-1])
        if not end_date_str:
            return False
        end_date = datetime.strptime(end_date_str, '%Y%m%d')
    except Exception as e:
        print(f"解析结束日期时出错: {e}")
        return False

    # 计算断板天数
    days_since_break = count_trading_days_between(last_board_date, end_date)

    # 如果断板天数超过阈值，则折叠此行
    return days_since_break > collapse_threshold


# ==================== 炸板检查相关函数 ====================

def check_stock_in_zaban(zaban_df, pure_stock_code, formatted_day):
    """
    检查股票在炸板数据中是否有记录

    Args:
        zaban_df: 炸板数据DataFrame
        pure_stock_code: 纯股票代码
        formatted_day: 格式化的日期

    Returns:
        bool: 是否在炸板数据中有记录
    """
    if zaban_df is None or zaban_df.empty:
        return False

    try:
        if '年' in formatted_day:
            date_obj = datetime.strptime(formatted_day, '%Y年%m月%d日')
        else:
            date_obj = datetime.strptime(formatted_day, '%Y/%m/%d')

        date_yyyymmdd = date_obj.strftime('%Y%m%d')

        # 优先使用预构建的O(1)查找字典（在load_zaban_data中构建）
        lookup = zaban_df.attrs.get('zaban_lookup')
        if lookup is not None:
            return pure_stock_code in lookup.get(date_yyyymmdd, frozenset())

        # 兜底：O(n)全表扫描（未构建lookup时使用）
        zaban_records = zaban_df[
            (zaban_df['date'] == date_yyyymmdd) &
            (zaban_df['stock_code'].str.contains(pure_stock_code, na=False))
            ]

        return not zaban_records.empty

    except Exception as e:
        print(f"检查炸板数据时出错: {e}")
        return False


def check_stock_in_shouban(shouban_df, pure_stock_code, formatted_day):
    """
    检查股票在首板数据中是否有记录

    Args:
        shouban_df: 首板数据DataFrame
        pure_stock_code: 纯股票代码
        formatted_day: 格式化的日期

    Returns:
        bool: 是否在首板数据中有记录
    """
    if shouban_df is None or shouban_df.empty:
        return False

    # 优先使用预构建的O(1)查找集合（在load_shouban_data中构建）
    lookup = shouban_df.attrs.get('shouban_lookup')
    if lookup is not None:
        return (pure_stock_code, formatted_day) in lookup

    # 兜底：O(n)逐行扫描（未构建lookup时使用）
    shouban_row = shouban_df[(shouban_df['纯代码'] == pure_stock_code)]
    if not shouban_row.empty and formatted_day in shouban_row.columns and pd.notna(
            shouban_row[formatted_day].values[0]):
        return True

    return False
