import logging
from typing import Optional

import pandas as pd

from utils.file_util import read_stock_data


def format_stock_code(code) -> str:
    """
    格式化股票代码为6位字符串，补全前导零
    
    Args:
        code: 股票代码，可以是字符串或数字
    
    Returns:
        str: 6位股票代码字符串，如 '000001', '600000'
    
    Examples:
        >>> format_stock_code(1)
        '000001'
        >>> format_stock_code('1')
        '000001'
        >>> format_stock_code('600000')
        '600000'
        >>> format_stock_code(2424)
        '002424'
    """
    return str(code).zfill(6)


def stock_limit_ratio(stock_code: str) -> float:
    """
    根据股票代码确定其涨跌停限制比例。
    注意：此函数返回常规交易日的涨跌幅限制，不考虑新股上市首日、ST/*ST股等特殊情况。
    :param stock_code: 6位数字的股票代码字符串。
    :return: 涨跌停比例 (例如 0.1 表示 ±10%)。
    """
    if not isinstance(stock_code, str):
        stock_code = str(stock_code)

    market = get_stock_market(stock_code)

    market_ratios = {
        'main': 0.1,
        'star': 0.2,
        'gem': 0.2,
        'bse': 0.3,
    }

    if market in market_ratios:
        return market_ratios[market]
    elif market == 'neeq':
        print(f"【警告】新三板股票({stock_code})不适用常规涨跌停限制。")
        return 1
    else:
        # 对于债券等未明确分类的，默认按主板的10%处理或抛出异常，这里选择抛出异常以更严谨
        raise ValueError(f"无法确定股票代码 {stock_code} 的涨跌停限制。")


def convert_stock_code(code: str) -> str:
    """
    将6位股票代码转换为交易所代码格式。
    :param code: 6位数字的股票代码字符串, 如 '600000'。
    :return: 带交易所前缀的股票代码, 如 'sh600000'。
    """
    if not isinstance(code, str):
        code = str(code)

    # 沪市
    if code.startswith(('60', '68')) or \
            code.startswith(('110', '113', '118')):  # 沪市股票、科创板、部分沪市可转债
        return f"sh{code}"
    # 深市
    elif code.startswith(('00', '30')) or \
            code.startswith(('12', '11', '13')):  # 深市股票、创业板、部分深市可转债/债券
        return f"sz{code}"
    # 北交所 & 新三板
    elif code.startswith(('8', '92', '43', '87')):
        return f"bj{code}"
    else:
        # 尝试根据市场进行二次判断（适用于一些未明确列出的债券等）
        market = get_stock_market(code)
        if market in ['main', 'star']:
            return f"sh{code}"
        elif market == 'gem':
            return f"sz{code}"
        elif market in ['bse', 'neeq']:
            return f"bj{code}"
        raise ValueError(f"无法识别的股票代码格式: {code}")


def get_stock_market(code: str) -> str:
    """
    确定股票所处的市场。
    :param code: 6位数字的股票代码字符串, 如 '600000'。
    :return: 市场类型: 'main'(主板), 'gem'(创业板), 'star'(科创板), 'bse'(北交所), 'neeq'(新三板)。
    """
    if not isinstance(code, str):
        code = str(code)

    # 优先判断特殊板块
    if code.startswith('68'):  # 科创板
        return 'star'
    elif code.startswith('30'):  # 创业板
        return 'gem'
    elif code.startswith(('8', '92')):  # 北交所
        return 'bse'
    elif code.startswith(('43', '83', '87')):  # 新三板
        return 'neeq'
    # 主板
    elif code.startswith('60'):  # 上交所主板
        return 'main'
    elif code.startswith('00'):  # 深交所主板
        return 'main'
    # 债券等其他情况，简单归类为主板处理
    elif code.startswith(('11', '12', '13')):
        return 'main'
    else:
        raise ValueError(f"无法识别的股票代码市场: {code}")


def calculate_period_change_from_date(stock_code: str, end_date_yyyymmdd: str, trading_days: int,
                                      data_path: str = './data/astocks') -> Optional[float]:
    """
    从指定日期往前数N个交易日，计算涨跌幅
    
    基于该股票实际的K线数据条数，排除停牌日（开盘价为空或为0的行视为停牌）
    使用开始日的开盘价和结束日的收盘价计算涨跌幅
    
    Args:
        stock_code: 股票代码（6位数字字符串）
        end_date_yyyymmdd: 结束日期 (YYYYMMDD)，即入选日
        trading_days: 往前数的交易日数量（如60、120）
        data_path: 股票数据目录，默认'./data/astocks'
        
    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
        
    Examples:
        >>> # 计算从20250101往前60个交易日的涨跌幅
        >>> change = calculate_period_change_from_date('000001', '20250101', 60)
        >>> print(f"60日涨跌幅: {change:.2f}%")
    """
    try:
        if not stock_code:
            return None

        # 获取股票数据
        df = read_stock_data(stock_code, data_path)

        if df is None or df.empty:
            logging.debug(f"股票 {stock_code} 无数据文件")
            return None

        # 过滤掉停牌的行（开盘价为空或为0的行视为停牌）
        valid_df = df[df['开盘'].notna() & (df['开盘'] > 0)].copy()

        if valid_df.empty:
            logging.debug(f"股票 {stock_code} 过滤停牌后无有效数据")
            return None

        # 按日期排序（从早到晚）
        valid_df = valid_df.sort_values('日期').reset_index(drop=True)

        # 格式化结束日期
        end_date_fmt = f"{end_date_yyyymmdd[:4]}-{end_date_yyyymmdd[4:6]}-{end_date_yyyymmdd[6:8]}"
        end_date_dt = pd.to_datetime(end_date_fmt)

        # 在有效数据中找到结束日期对应的行索引
        # 确保日期列是datetime类型
        valid_df['日期'] = pd.to_datetime(valid_df['日期'])

        end_matches = valid_df[valid_df['日期'] == end_date_dt]
        if end_matches.empty:
            # 如果结束日期没有数据，找最接近的之前的有效日期
            valid_dates_before = valid_df[valid_df['日期'] <= end_date_dt]['日期']
            if valid_dates_before.empty:
                logging.debug(f"股票 {stock_code} 在 {end_date_fmt} 之前无有效交易数据")
                return None
            closest_end_date = valid_dates_before.max()
            end_matches = valid_df[valid_df['日期'] == closest_end_date]
            logging.debug(
                f"股票 {stock_code} 结束日期 {end_date_fmt} 停牌，使用 {closest_end_date.strftime('%Y-%m-%d')}")

        if end_matches.empty:
            return None

        end_idx = end_matches.index[0]

        # 基于该股票实际的有效K线数据，往前数 trading_days 条
        start_idx = end_idx - trading_days
        if start_idx < 0:
            # 如果数据不足，使用最早的数据
            logging.debug(f"股票 {stock_code} 数据不足{trading_days}个交易日，使用最早的数据")
            start_idx = 0

        # 获取起点和终点的价格数据
        start_price = valid_df.loc[start_idx, '开盘']
        end_price = valid_df.loc[end_idx, '收盘']

        # 检查价格数据是否有效
        if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0 or end_price <= 0:
            logging.debug(f"股票 {stock_code} 价格数据无效: 开盘={start_price}, 收盘={end_price}")
            return None

        # 计算涨跌幅
        period_change = ((end_price / start_price) - 1) * 100

        return period_change

    except Exception as e:
        logging.error(f"计算股票 {stock_code} 从 {end_date_yyyymmdd} 往前{trading_days}个交易日的涨跌幅时出错: {e}")
        return None
