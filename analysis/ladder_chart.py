import os
import re
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill, Alignment, Font, Border, Side
from openpyxl.utils import get_column_letter

from analysis.loader.fupan_data_loader import (
    OUTPUT_FILE, load_stock_data
)
from decorators.practical import timer
from utils.date_util import get_trading_days, count_trading_days_between, get_n_trading_days_before
from utils.stock_util import get_stock_market
from utils.theme_color_util import (
    extract_reasons, get_reason_colors, get_stock_reason_group, normalize_reason,
    create_legend_sheet, get_color_for_pct_change, add_market_indicators,
    HIGH_BOARD_COLORS, REENTRY_COLORS, BOARD_COLORS
)

# 断板后跟踪的最大天数，超过这个天数后不再显示涨跌幅
# 例如设置为5，会显示断板后的第1、2、3、4、5个交易日，从第6个交易日开始不再显示
# 设置为None表示一直跟踪到分析周期结束
MAX_TRACKING_DAYS_AFTER_BREAK = 8

# 入选前跟踪的最大天数，显示入选前的第1、2、3、...个交易日的涨跌幅
# 例如设置为3，会显示入选前的第1、2、3个交易日的涨跌幅
# 设置为0表示不显示入选前的走势
MAX_TRACKING_DAYS_BEFORE_ENTRY = 5

# 断板后再次达到入选的交易日间隔阈值
# 例如设置为4，当股票断板后第5个交易日或之后再次达到入选时，会作为新的一行记录
# 如果一只股票断板后超过这个交易日天数又再次达到入选，则视为新的一行记录
REENTRY_DAYS_THRESHOLD = 4

# 计算入选日与之前X个交易日的涨跌幅
# 例如设置为20，会计算入选日与20个交易日之前的涨跌幅
PERIOD_DAYS_CHANGE = 10

# 成交量分析相关参数
# 计算成交量比的天数，当天成交量与前X天平均成交量的比值
VOLUME_DAYS = 4
# 成交量比阈值，超过该值则在单元格中显示成交量比
VOLUME_RATIO_THRESHOLD = 2.5

# 单元格边框样式
BORDER_STYLE = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)

# 周期涨跌幅颜色映射
PERIOD_CHANGE_COLORS = {
    "EXTREME_POSITIVE": "9933FF",  # 深紫色 - 极强势 (≥100%)
    "STRONG_POSITIVE": "AA66FF",  # 中深紫色 - 强势 (≥70%)
    "MODERATE_POSITIVE": "BB99FF",  # 中紫色 - 较强势 (≥40%)
    "MILD_POSITIVE": "CCCCFF",  # 浅紫色 - 偏强势 (≥20%)
    "SLIGHT_POSITIVE": "E6E6FF",  # 极浅紫色 - 微强势 (≥0%)
    "SLIGHT_NEGATIVE": "E6EBC9",  # 极浅橄榄绿 - 微弱势 (≥-20%)
    "MILD_NEGATIVE": "C9D58C",  # 浅橄榄绿 - 偏弱势 (≥-40%)
    "MODERATE_NEGATIVE": "A3B86C",  # 中橄榄绿 - 较弱势 (≥-60%)
    "STRONG_NEGATIVE": "7D994D",  # 深橄榄绿 - 弱势 (<-60%)
}

# 股票数据保存路径
STOCK_DATA_PATH = "./data/astocks/"

# 全局缓存存储交易日映射，show_period_change为True时才使用
TRADING_DAYS_LOOKUP = {}


@lru_cache(maxsize=1000)
def get_stock_file_path(stock_code, stock_name=None):
    """
    获取股票数据文件路径

    Args:
        stock_code: 股票代码
        stock_name: 股票名称，用于构建文件名

    Returns:
        str: 股票数据文件路径，如果找不到则返回None
    """
    # 处理股票代码格式
    clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

    # 查找对应的文件
    file_path = None

    if stock_name:
        # 如果提供了股票名称，直接尝试使用
        safe_name = stock_name.replace('*ST', 'xST').replace('/', '_')
        possible_file = f"{clean_code}_{safe_name}.csv"
        if os.path.exists(os.path.join(STOCK_DATA_PATH, possible_file)):
            file_path = os.path.join(STOCK_DATA_PATH, possible_file)

    # 如果没有找到文件，尝试查找匹配的文件
    if not file_path:
        for file in os.listdir(STOCK_DATA_PATH):
            # 匹配文件名前缀为股票代码的文件
            if file.startswith(f"{clean_code}_") and file.endswith(".csv"):
                file_path = os.path.join(STOCK_DATA_PATH, file)
                break

    if not file_path:
        # 如果还是没找到，可能需要处理前导零的情况
        if clean_code.startswith('0'):
            # 尝试去掉前导零
            stripped_code = clean_code.lstrip('0')
            if stripped_code:  # 确保不是全零
                for file in os.listdir(STOCK_DATA_PATH):
                    if file.startswith(f"{stripped_code}_") and file.endswith(".csv"):
                        file_path = os.path.join(STOCK_DATA_PATH, file)
                        break

        # 对于上交所股票，可能需要处理6开头的代码
        elif clean_code.startswith('6'):
            for file in os.listdir(STOCK_DATA_PATH):
                if file.startswith(f"{clean_code}_") and file.endswith(".csv"):
                    file_path = os.path.join(STOCK_DATA_PATH, file)
                    break

    return file_path


@lru_cache(maxsize=1000)
def get_stock_data(stock_code, date_str_yyyymmdd, stock_name=None):
    """
    获取指定股票在特定日期的数据，使用缓存避免重复读取文件
    
    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
    
    Returns:
        tuple: (DataFrame, 目标行, 目标索引) 如果数据不存在则返回(None, None, None)
    """
    try:
        if not stock_code:
            return None, None, None

        # 目标日期（YYYY-MM-DD格式）
        target_date = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"

        # 获取股票数据文件路径
        file_path = get_stock_file_path(stock_code, stock_name)

        # 如果没有找到文件
        if not file_path:
            return None, None, None

        # 读取CSV文件
        df = pd.read_csv(file_path, header=None,
                         names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                '振幅', '涨跌幅', '涨跌额', '换手率'])

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
        print(f"获取股票 {stock_code} ({stock_name}) 在 {date_str_yyyymmdd} 的数据时出错: {e}")
        return None, None, None


def get_stock_daily_pct_change(stock_code, date_str_yyyymmdd, stock_name=None):
    """
    获取指定股票在特定日期的涨跌幅
    
    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
    
    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
    """
    _, target_row, _ = get_stock_data(stock_code, date_str_yyyymmdd, stock_name)

    if target_row is not None and not target_row.empty:
        return target_row['涨跌幅'].values[0]

    return None


def get_volume_ratio(stock_code, date_str_yyyymmdd, stock_name=None):
    """
    获取指定股票在特定日期的成交量比(当天成交量/前N天平均成交量)
    
    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
    
    Returns:
        tuple: (成交量比, 是否超过阈值) 如果数据不存在则返回(None, False)
    """
    df, target_row, target_idx = get_stock_data(stock_code, date_str_yyyymmdd, stock_name)

    if df is None or target_row is None or target_row.empty:
        return None, False

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

                # 判断是否超过阈值
                is_high_volume = volume_ratio >= VOLUME_RATIO_THRESHOLD

                return volume_ratio, is_high_volume

    except Exception as e:
        print(f"计算股票 {stock_code} 在 {date_str_yyyymmdd} 的成交量比时出错: {e}")

    return None, False


def add_volume_ratio_to_text(text, stock_code, date_str_yyyymmdd, stock_name=None):
    """
    根据成交量比向文本添加成交量信息
    
    Args:
        text: 原始文本
        stock_code: 股票代码
        date_str_yyyymmdd: 日期字符串(YYYYMMDD格式)
        stock_name: 股票名称
        
    Returns:
        str: 添加成交量信息后的文本
    """
    volume_ratio, is_high_volume = get_volume_ratio(stock_code, date_str_yyyymmdd, stock_name)

    if is_high_volume and volume_ratio is not None:
        return f"{text}[{volume_ratio:.1f}]"

    return text


def get_loose_board_level(board_level):
    """
    获取宽松的连板数
    """
    return 1 if board_level == 1 else board_level - 1


def check_attention_criteria(stock_code, board_days, market, min_board_level, non_main_board_level,
                             current_date_col, attention_data_main, attention_data_non_main):
    """
    检查股票是否满足关注度榜入选条件
    
    Args:
        stock_code: 股票代码
        board_days: 连板天数
        market: 市场类型
        min_board_level: 主板股票最小显著连板天数
        non_main_board_level: 非主板股票最小显著连板天数
        current_date_col: 当前日期列名
        attention_data_main: 主板关注度榜数据
        attention_data_non_main: 非主板关注度榜数据
        
    Returns:
        tuple: (是否满足条件, 入选类型)
    """
    # 默认不满足条件，入选类型为normal
    is_significant = False
    entry_type = 'normal'

    # 清理股票代码，去除可能的市场前缀
    clean_stock_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

    # 解析当前日期
    current_date = datetime.strptime(current_date_col, '%Y年%m月%d日') if '年' in current_date_col else pd.to_datetime(
        current_date_col)

    # 根据市场类型选择不同的检查逻辑
    if market == 'main' and board_days == get_loose_board_level(min_board_level):
        # 检查主板股票
        if attention_data_main is not None and not attention_data_main.empty:
            is_significant, entry_type = check_stock_attention(
                clean_stock_code, current_date, attention_data_main,
                f"主板股票 {stock_code} 在(board_level-1)={get_loose_board_level(min_board_level)}板"
            )
    elif market in ['gem', 'star', 'bse'] and board_days == get_loose_board_level(non_main_board_level):
        # 检查非主板股票
        if attention_data_non_main is not None and not attention_data_non_main.empty:
            is_significant, entry_type = check_stock_attention(
                clean_stock_code, current_date, attention_data_non_main,
                f"非主板股票 {stock_code} 在(board_level-1)={get_loose_board_level(non_main_board_level)}板"
            )

    return is_significant, entry_type


def check_stock_attention(stock_code, current_date, attention_data, log_prefix):
    """
    检查股票在关注度榜中的出现情况
    
    Args:
        stock_code: 股票代码
        current_date: 当前日期
        attention_data: 关注度榜数据
        log_prefix: 日志前缀
        
    Returns:
        tuple: (是否满足条件, 入选类型)
    """
    # 过滤出当前股票的关注度数据
    stock_attention = attention_data[attention_data['股票代码'].str.contains(stock_code)]

    if stock_attention.empty:
        return False, 'normal'

    # 计算每个关注度日期与当前日期的交易日差
    attention_dates = []
    for _, att_row in stock_attention.iterrows():
        att_date_str = att_row['日期']
        att_date = datetime.strptime(att_date_str, '%Y年%m月%d日') if '年' in att_date_str else pd.to_datetime(
            att_date_str)
        days_diff = count_trading_days_between(current_date, att_date)
        if 0 <= days_diff <= 5:  # 在当天或之后的5个交易日内
            attention_dates.append(att_date)

    # 如果在5个交易日内出现了至少两次，则认为符合条件
    if len(attention_dates) >= 2:
        print(f"    {log_prefix}后5天内两次入选关注度榜前20，符合额外入选条件")
        return True, 'attention'

    return False, 'normal'


def is_stock_significant(board_days, market, min_board_level, non_main_board_level):
    """
    判断股票是否达到显著连板条件
    
    Args:
        board_days: 连板天数
        market: 市场类型
        min_board_level: 主板股票最小显著连板天数
        non_main_board_level: 非主板股票最小显著连板天数
        
    Returns:
        bool: 是否达到显著连板条件
    """
    if not board_days:
        return False

    if market == 'main':
        return board_days >= min_board_level
    elif market in ['gem', 'star', 'bse']:
        return board_days >= non_main_board_level
    else:
        # 其他情况，使用主板标准
        return board_days >= min_board_level


def check_reentry_condition(current_date, continuous_board_dates, reentry_days_threshold,
                            board_days, market, min_board_level, non_main_board_level,
                            enable_attention_criteria=False, attention_data_main=None,
                            attention_data_non_main=None, stock_code=None):
    """
    检查是否满足断板后再次入选条件
    
    Args:
        current_date: 当前日期
        continuous_board_dates: 连续连板日期列表
        reentry_days_threshold: 断板后再次上榜的天数阈值
        board_days: 连板天数
        market: 市场类型
        min_board_level: 主板股票最小显著连板天数
        non_main_board_level: 非主板股票最小显著连板天数
        enable_attention_criteria: 是否启用关注度榜入选条件
        attention_data_main: 主板关注度榜数据
        attention_data_non_main: 非主板关注度榜数据
        stock_code: 股票代码
        
    Returns:
        tuple: (是否满足再次入选条件, 是否需要清空连续连板日期)
    """
    # 获取之前的连板日期
    previous_board_dates = [d for d in continuous_board_dates if d < current_date]

    if not previous_board_dates:
        return False, False

    # 获取上一个连板区间的最后日期
    last_board_date = max(previous_board_dates)

    # 计算间隔交易日天数
    days_since_last_board = count_trading_days_between(last_board_date, current_date)

    print(f"    上一次连板日期: {last_board_date.strftime('%Y-%m-%d')}, "
          f"当前日期: {current_date.strftime('%Y-%m-%d')}, "
          f"交易日间隔: {days_since_last_board}天")

    # 判断是否满足再次入选条件
    if days_since_last_board > reentry_days_threshold:
        # 首先检查是否达到基本的显著连板条件
        is_significant_reentry = is_stock_significant(board_days, market, min_board_level, non_main_board_level)

        # 如果不满足基本条件，但启用了关注度榜入选条件，则检查是否满足关注度榜条件
        if not is_significant_reentry and enable_attention_criteria and stock_code:
            current_date_str = current_date.strftime('%Y年%m月%d日')
            is_significant_reentry, _ = check_attention_criteria(
                stock_code, board_days, market, min_board_level, non_main_board_level,
                current_date_str, attention_data_main, attention_data_non_main
            )

        if is_significant_reentry:
            print(f"    断板后{days_since_last_board}个交易日再次达到入选条件，作为新记录")
            return True, True

    return False, False


def identify_first_significant_board(df, shouban_df=None, min_board_level=2,
                                     reentry_days_threshold=REENTRY_DAYS_THRESHOLD, non_main_board_level=1,
                                     enable_attention_criteria=False, attention_data_main=None,
                                     attention_data_non_main=None):
    """
    识别每只股票首次达到显著连板（例如2板或以上）的日期，以及断板后再次达到的情况
    
    Args:
        df: 连板数据DataFrame，已透视处理，每行一只股票，每列一个日期
        shouban_df: 首板数据DataFrame，已透视处理，每行一只股票，每列一个日期
        min_board_level: 主板股票最小显著连板天数，默认为2
        reentry_days_threshold: 断板后再次上榜的天数阈值，超过这个天数再次达到入选条件会作为新记录
        non_main_board_level: 非主板股票最小显著连板天数，默认为1
        enable_attention_criteria: 是否启用关注度榜入选条件，默认为False
        attention_data_main: 主板关注度榜数据，当enable_attention_criteria=True时需要提供
        attention_data_non_main: 非主板关注度榜数据，当enable_attention_criteria=True时需要提供
        
    Returns:
        pandas.DataFrame: 添加了连板信息的DataFrame
    """
    # 创建结果列表
    result = []

    # 找出日期列
    date_columns = [col for col in df.columns if col not in ['纯代码', '股票名称', '股票代码', '概念']]
    if not date_columns:
        print("无法找到日期列")
        return pd.DataFrame()

    # 将日期列按时间排序
    date_columns.sort()

    # 获取所有股票数据
    all_stocks = get_all_stocks(df, date_columns, shouban_df)

    # 确定每只股票的市场类型
    determine_stock_markets(all_stocks)

    # 分析每只股票，确定是否入选显著连板
    analyze_stocks_for_significant_boards(
        all_stocks, date_columns, result, min_board_level,
        reentry_days_threshold, non_main_board_level,
        enable_attention_criteria, attention_data_main, attention_data_non_main
    )

    # 转换为DataFrame
    result_df = pd.DataFrame(result)

    # 如果没有符合条件的数据，返回空DataFrame
    if result_df.empty:
        print("未找到符合条件的连板数据")
        return result_df

    print(f"找到{len(result_df)}只达到显著连板的股票")

    # 按首次显著连板日期和连板天数排序
    result_df = result_df.sort_values(
        by=['first_significant_date', 'board_level_at_first'],
        ascending=[True, False]
    )

    return result_df


def get_all_stocks(df, date_columns, shouban_df=None):
    """
    合并连板数据和首板数据，创建完整的股票池
    
    Args:
        df: 连板数据DataFrame
        date_columns: 日期列列表
        shouban_df: 首板数据DataFrame
        
    Returns:
        dict: 股票池字典，键为股票代码，值为股票数据
    """
    all_stocks = {}

    # 1. 处理连板数据
    print(f"处理连板数据，共有{len(df)}只股票")
    for idx, row in df.iterrows():
        stock_code = row['纯代码']
        stock_name = row['股票名称']

        # 跳过代码或名称为空的行
        if not stock_code or not stock_name:
            continue

        # 创建股票数据字典
        stock_data = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'concept': row.get('概念', '其他'),
            'board_data': {},
            'market': None  # 将在后面填充
        }

        # 填充连板数据
        for col in date_columns:
            if pd.notna(row[col]):
                stock_data['board_data'][col] = row[col]

        all_stocks[stock_code] = stock_data

    # 2. 处理首板数据，合并到股票池中
    if shouban_df is not None and not shouban_df.empty:
        print(f"处理首板数据，共有{len(shouban_df)}只股票")
        shouban_date_columns = [col for col in shouban_df.columns if
                                col not in ['纯代码', '股票名称', '股票代码', '概念']]
        shouban_date_columns.sort()

        for idx, row in shouban_df.iterrows():
            stock_code = row['纯代码']
            stock_name = row['股票名称']

            # 跳过代码或名称为空的行
            if not stock_code or not stock_name:
                continue

            # 如果股票已在连板数据中，则合并首板数据
            if stock_code in all_stocks:
                for col in shouban_date_columns:
                    if pd.notna(row[col]) and col not in all_stocks[stock_code]['board_data']:
                        all_stocks[stock_code]['board_data'][col] = row[col]
            else:
                # 创建新的股票数据
                stock_data = {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'concept': row.get('概念', '其他'),
                    'board_data': {},
                    'market': None  # 将在后面填充
                }

                # 填充首板数据
                for col in shouban_date_columns:
                    if pd.notna(row[col]):
                        stock_data['board_data'][col] = row[col]

                all_stocks[stock_code] = stock_data

    return all_stocks


def determine_stock_markets(all_stocks):
    """
    确定每只股票的市场类型
    
    Args:
        all_stocks: 股票池字典
    """
    for stock_code, stock_data in all_stocks.items():
        try:
            market = get_stock_market(stock_code)
            stock_data['market'] = market
        except Exception as e:
            print(f"判断股票 {stock_code} 市场类型时出错: {e}")
            stock_data['market'] = 'unknown'


def analyze_stocks_for_significant_boards(all_stocks, date_columns, result, min_board_level,
                                          reentry_days_threshold, non_main_board_level,
                                          enable_attention_criteria, attention_data_main, attention_data_non_main):
    """
    分析每只股票，确定是否入选显著连板
    
    Args:
        all_stocks: 股票池字典
        date_columns: 日期列列表
        result: 结果列表，用于存储入选的股票记录
        min_board_level: 主板股票最小显著连板天数
        reentry_days_threshold: 断板后再次上榜的天数阈值
        non_main_board_level: 非主板股票最小显著连板天数
        enable_attention_criteria: 是否启用关注度榜入选条件
        attention_data_main: 主板关注度榜数据
        attention_data_non_main: 非主板关注度榜数据
    """
    print(f"分析股票池中的所有股票，共有{len(all_stocks)}只股票")
    for stock_code, stock_data in all_stocks.items():
        stock_name = stock_data['stock_name']
        market = stock_data['market']
        board_data = stock_data['board_data']

        print(f"\n分析股票: {stock_code}_{stock_name} (市场: {market})")

        # 按日期排序的板块数据
        sorted_dates = sorted(board_data.keys())

        # 存储所有板块出现的时间点
        significant_board_dates = []  # 存储显著连板日期
        continuous_board_dates = []  # 存储连续的连板日期，用于判断断板

        # 检查每一个日期
        for col in sorted_dates:
            board_days = board_data[col]
            print(f"  日期 {col}: {board_days}")

            # 判断是否为显著连板
            is_significant = False
            entry_type = 'normal'  # 默认入选类型

            # 首先检查是否满足基本的显著连板条件
            is_significant = is_stock_significant(board_days, market, min_board_level, non_main_board_level)

            # 如果不满足基本条件，但启用了关注度榜入选条件，则检查是否满足关注度榜条件
            if not is_significant and enable_attention_criteria:
                is_significant, entry_type = check_attention_criteria(
                    stock_code, board_days, market, min_board_level, non_main_board_level,
                    col, attention_data_main, attention_data_non_main
                )

            if is_significant:
                print(f"    找到显著连板: {board_days}板")

                # 记录为显著连板日期
                current_date = datetime.strptime(col, '%Y年%m月%d日') if '年' in col else pd.to_datetime(col)

                # 记录连续连板日期，用于确定最后一次连板的日期
                continuous_board_dates.append(current_date)

                # 判断是否为新的入选记录
                is_new_entry = False

                if not significant_board_dates:
                    # 第一次显著连板
                    is_new_entry = True
                elif continuous_board_dates:
                    # 检查是否是断板后间隔足够长再次达到入选条件
                    is_reentry, clear_dates = check_reentry_condition(
                        current_date, continuous_board_dates, reentry_days_threshold,
                        board_days, market, min_board_level, non_main_board_level,
                        enable_attention_criteria, attention_data_main, attention_data_non_main, stock_code
                    )

                    if is_reentry:
                        is_new_entry = True
                        # 清空连续连板日期列表，开始新的连板区间记录
                        if clear_dates:
                            continuous_board_dates = [current_date]

                # 添加到显著连板日期列表
                significant_board_dates.append(current_date)

                if is_new_entry:
                    # 构建完整的板块数据字典
                    all_board_data = {}
                    for date_col in date_columns:
                        all_board_data[date_col] = board_data.get(date_col)

                    # 确定入选类型
                    if entry_type == 'attention':
                        final_entry_type = 'attention'
                    elif len(significant_board_dates) > 1:
                        final_entry_type = 'reentry'
                    elif market in ['gem', 'star', 'bse'] and board_days == 1:
                        final_entry_type = 'non_main_first_board'
                    else:
                        final_entry_type = 'first'

                    # 添加到结果列表
                    entry = {
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'first_significant_date': current_date,
                        'board_level_at_first': board_days,
                        'all_board_data': all_board_data,
                        'concept': stock_data['concept'],
                        'entry_type': final_entry_type
                    }

                    result.append(entry)
                    print(f"    记录显著连板: {stock_name} 在 {col} 达到 {board_days}板")


def get_concept_from_board_text(board_text):
    """
    从连板文本中提取概念信息
    
    Args:
        board_text: 连板文本，可能包含概念信息
        
    Returns:
        str: 提取出的概念，如果没有则返回"其他"
    """
    if not board_text or pd.isna(board_text):
        return "其他"

    # 将连板文本转换为字符串并去除空格
    board_text = str(board_text).strip()

    # 尝试提取概念（假设概念位于连板天数之后的括号中）
    match = re.search(r'\(([^)]+)\)', board_text)
    if match:
        concept = match.group(1).strip()
        # 使用theme_color_util中的normalize_reason对概念进行规范化
        try:
            normalized_concept = normalize_reason(concept)
            return normalized_concept if not normalized_concept.startswith("未分类") else concept
        except:
            return concept

    # 如果没有找到括号内的概念，返回默认值
    return "其他"


def get_market_marker(stock_code):
    """
    根据股票代码获取市场标记
    
    Args:
        stock_code: 股票代码
        
    Returns:
        str: 市场标记，创业板或科创板返回"*"，北交所返回"**"，其他返回空字符串
    """
    try:
        market = get_stock_market(stock_code)
        if market == 'gem' or market == 'star':  # 创业板或科创板
            return "*"
        elif market == 'bse':  # 北交所
            return "**"
        return ""
    except Exception as e:
        print(f"获取股票 {stock_code} 市场类型出错: {e}")
        return ""


def get_color_for_period_change(pct_change):
    """
    根据周期涨跌幅获取背景色（紫色系为正，橄榄绿系为负）
    
    Args:
        pct_change: 涨跌幅百分比
        
    Returns:
        str: 颜色代码
    """
    if pct_change is None:
        return None

    # 正值使用紫色系配色
    if pct_change >= 100:
        return PERIOD_CHANGE_COLORS["EXTREME_POSITIVE"]
    elif pct_change >= 70:
        return PERIOD_CHANGE_COLORS["STRONG_POSITIVE"]
    elif pct_change >= 40:
        return PERIOD_CHANGE_COLORS["MODERATE_POSITIVE"]
    elif pct_change >= 20:
        return PERIOD_CHANGE_COLORS["MILD_POSITIVE"]
    elif pct_change >= 0:
        return PERIOD_CHANGE_COLORS["SLIGHT_POSITIVE"]
    # 负值使用橄榄绿系配色
    elif pct_change >= -20:
        return PERIOD_CHANGE_COLORS["SLIGHT_NEGATIVE"]
    elif pct_change >= -40:
        return PERIOD_CHANGE_COLORS["MILD_NEGATIVE"]
    elif pct_change >= -60:
        return PERIOD_CHANGE_COLORS["MODERATE_NEGATIVE"]
    else:
        return PERIOD_CHANGE_COLORS["STRONG_NEGATIVE"]


@lru_cache(maxsize=1000)
def calculate_stock_period_change(stock_code, start_date_yyyymmdd, end_date_yyyymmdd, stock_name=None):
    """
    计算股票在两个日期之间的涨跌幅
    
    Args:
        stock_code: 股票代码
        start_date_yyyymmdd: 开始日期 (YYYYMMDD)
        end_date_yyyymmdd: 结束日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
    
    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
    """
    try:
        if not stock_code:
            return None

        # 获取股票数据文件路径
        file_path = get_stock_file_path(stock_code, stock_name)

        # 如果没有找到文件
        if not file_path:
            return None

        # 读取CSV文件
        df = pd.read_csv(file_path, header=None,
                         names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                '振幅', '涨跌幅', '涨跌额', '换手率'])

        # 格式化日期
        start_date_fmt = f"{start_date_yyyymmdd[:4]}-{start_date_yyyymmdd[4:6]}-{start_date_yyyymmdd[6:8]}"
        end_date_fmt = f"{end_date_yyyymmdd[:4]}-{end_date_yyyymmdd[4:6]}-{end_date_yyyymmdd[6:8]}"

        # 查找开始日期和结束日期的收盘价
        start_row = df[df['日期'] == start_date_fmt]
        end_row = df[df['日期'] == end_date_fmt]

        if start_row.empty or end_row.empty:
            # 如果没有找到对应日期的数据，尝试查找最接近的日期
            all_dates = pd.to_datetime(df['日期'])
            start_date_dt = pd.to_datetime(start_date_fmt)
            end_date_dt = pd.to_datetime(end_date_fmt)

            # 找到不晚于开始日期的最近日期
            valid_dates = all_dates[all_dates <= start_date_dt]
            if not valid_dates.empty:
                closest_start_date = valid_dates.max()
                start_row = df[df['日期'] == closest_start_date.strftime('%Y-%m-%d')]

            # 找到不早于结束日期的最近日期
            valid_dates = all_dates[all_dates >= end_date_dt]
            if not valid_dates.empty:
                closest_end_date = valid_dates.min()
                end_row = df[df['日期'] == closest_end_date.strftime('%Y-%m-%d')]

        if start_row.empty or end_row.empty:
            return None

        # 获取区间首尾价
        start_price = start_row['开盘'].values[0]
        end_price = end_row['收盘'].values[0]

        # 计算涨跌幅
        period_change = ((end_price / start_price) - 1) * 100

        return period_change

    except Exception as e:
        print(
            f"计算股票 {stock_code} ({stock_name}) 在 {start_date_yyyymmdd} 至 {end_date_yyyymmdd} 的涨跌幅时出错: {e}")
        return None


def build_comment_text(details):
    """
    构建备注文本

    Args:
        details: 详细信息字典

    Returns:
        str: 备注文本
    """
    comment_text = ""

    if '连板信息' in details:
        comment_text += f"{details['连板信息']} "
    if '首次涨停时间' in details:
        comment_text += f"\n首次涨停: {details['首次涨停时间']} "
    if '最终涨停时间' in details:
        comment_text += f"\n最终涨停: {details['最终涨停时间']} "
    if '涨停开板次数' in details:
        comment_text += f"\n开板次数: {details['涨停开板次数']}"

    return comment_text


def format_header_cell(ws, row, col, value, is_center=True, is_bold=True, font_size=None):
    """
    格式化表头单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        value: 单元格值
        is_center: 是否居中对齐
        is_bold: 是否加粗
        font_size: 字体大小，None表示使用默认大小
    """
    cell = ws.cell(row=row, column=col, value=value)
    cell.border = BORDER_STYLE

    # 设置对齐方式
    if is_center:
        cell.alignment = Alignment(horizontal='center')

    # 设置字体
    font_args = {'bold': is_bold}
    if font_size:
        font_args['size'] = font_size
    cell.font = Font(**font_args)

    return cell


def format_stock_code_cell(ws, row, col, stock_code):
    """
    格式化股票代码单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        stock_code: 股票代码
    """
    # 使用Excel单元格格式设置为文本，而不是添加单引号前缀
    code_cell = ws.cell(row=row, column=col, value=f'{stock_code.split(".")[0]}')
    code_cell.alignment = Alignment(horizontal='center')
    code_cell.border = BORDER_STYLE
    code_cell.font = Font(size=8)  # 设置比正常小的字体
    code_cell.number_format = '@'  # 设置单元格格式为文本，保留前导零

    return code_cell


def format_concept_cell(ws, row, col, concept, stock_key, stock_reason_group, reason_colors):
    """
    格式化概念单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        concept: 概念文本
        stock_key: 股票键名
        stock_reason_group: 股票概念组映射
        reason_colors: 概念颜色映射
    """
    # 设置概念列
    concept_cell = ws.cell(row=row, column=col, value=f"[{concept}]")
    concept_cell.alignment = Alignment(horizontal='left')
    concept_cell.border = BORDER_STYLE
    concept_cell.font = Font(size=9)  # 设置小一号字体

    # 根据股票所属概念组设置颜色
    if stock_key in stock_reason_group:
        reason = stock_reason_group[stock_key]
        if reason in reason_colors:
            concept_cell.fill = PatternFill(start_color=reason_colors[reason], fill_type="solid")
            # 如果背景色较深，使用白色字体
            if reason_colors[reason] in ["FF5A5A", "FF8C42", "9966FF", "45B5FF"]:
                concept_cell.font = Font(color="FFFFFF", size=9)  # 保持小一号字体

    return concept_cell


def format_stock_name_cell(ws, row, col, stock_name, market_type, max_board_level, apply_high_board_color,
                           stock_code, stock_entry_count):
    """
    格式化股票名称单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        stock_name: 股票名称
        market_type: 市场类型标记
        max_board_level: 最高板数
        apply_high_board_color: 是否应用高板颜色
        stock_code: 股票代码
        stock_entry_count: 股票入选次数映射
    """
    # 设置股票简称列，添加市场标记
    stock_display_name = f"{stock_name}{market_type}"
    name_cell = ws.cell(row=row, column=col, value=stock_display_name)
    name_cell.alignment = Alignment(horizontal='left')
    name_cell.border = BORDER_STYLE

    # 为曾经到过4板及以上的个股，设置蓝色背景
    if max_board_level >= 4:
        # 找出最接近的颜色档位
        color_level = 4
        for level in sorted(HIGH_BOARD_COLORS.keys()):
            if max_board_level >= level:
                color_level = level

        # 设置背景色
        bg_color = HIGH_BOARD_COLORS[color_level]
        name_cell.fill = PatternFill(start_color=bg_color, fill_type="solid")
        apply_high_board_color = True

        # 对于深色背景，使用白色字体
        if color_level >= 12:
            name_cell.font = Font(color="FFFFFF")  # 保持默认字体大小
    # 如果没有应用高板数颜色，且该股票是重复入选，则应用灰色背景
    elif stock_code in stock_entry_count and stock_entry_count[stock_code] > 1:
        # 获取入选次数
        entry_count = stock_entry_count[stock_code]
        # 确定颜色深度，超过4次使用最深的灰色
        color_level = min(entry_count, 4)
        bg_color = REENTRY_COLORS.get(color_level, REENTRY_COLORS[4])
        name_cell.fill = PatternFill(start_color=bg_color, fill_type="solid")

        # 对于深色灰色背景，使用白色字体
        if color_level >= 4:
            name_cell.font = Font(color="FFFFFF")

    return name_cell, apply_high_board_color


def precompute_trading_days_lookup(start_date, end_date, period_days):
    """
    预计算交易日映射表缓存，用于快速查找前N个交易日

    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        period_days: 需要往前查找的交易日数量

    Returns:
        dict: 交易日映射表，键为YYYYMMDD格式日期，值为前N个交易日的YYYYMMDD格式
    """
    global TRADING_DAYS_LOOKUP
    # 清空旧的映射
    TRADING_DAYS_LOOKUP.clear()

    try:
        # 获取更大范围的交易日列表，确保能够覆盖到period_days天之前
        extended_start = datetime.strptime(start_date, '%Y%m%d') - timedelta(days=period_days + 10)
        extended_start_str = extended_start.strftime('%Y%m%d')
        extended_trading_days = get_trading_days(extended_start_str, end_date)

        print(f"预计算交易日映射表，共{len(extended_trading_days)}个交易日...")

        # 为每个交易日预计算前N个交易日
        for i, day in enumerate(extended_trading_days):
            if i >= period_days:  # 确保有足够的历史数据
                # 当前日期的YYYYMMDD格式
                current_day = day
                # 前N个交易日的索引
                prev_day_idx = i - period_days
                # 前N个交易日的YYYYMMDD格式
                prev_day = extended_trading_days[prev_day_idx]
                # 直接存储YYYYMMDD格式
                TRADING_DAYS_LOOKUP[current_day] = prev_day

        print(f"交易日映射表计算完成，共{len(TRADING_DAYS_LOOKUP)}个映射关系")
        return TRADING_DAYS_LOOKUP
    except Exception as e:
        print(f"预计算交易日映射表时出错: {e}")
        return {}


def get_prev_trading_day_fast(date_str, period_days):
    """
    快速获取指定日期往前第n个交易日

    Args:
        date_str: 日期字符串，格式为 'YYYYMMDD'
        period_days: 向前推的交易日数量

    Returns:
        str: 前N个交易日，格式为 'YYYYMMDD'
    """
    # 如果有预计算的映射表，直接查找
    if TRADING_DAYS_LOOKUP and date_str in TRADING_DAYS_LOOKUP:
        return TRADING_DAYS_LOOKUP[date_str]

    # 否则使用原始方法
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    prev_date = get_n_trading_days_before(date_fmt, period_days)
    return prev_date.replace('-', '')


def format_period_change_cell(ws, row, col, stock_code, stock_name, entry_date, period_days):
    """
    格式化周期涨跌幅单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        stock_code: 股票代码
        stock_name: 股票名称
        entry_date: 入选日期
        period_days: 周期天数
    """
    try:
        # 获取入选日期字符串
        entry_date_str = entry_date.strftime('%Y%m%d')

        # 使用快速函数获取前N个交易日
        prev_date = get_prev_trading_day_fast(entry_date_str, period_days)

        # 计算从入选前X日到入选日的涨跌幅
        period_change = calculate_stock_period_change(stock_code, prev_date, entry_date_str, stock_name)

        if period_change is not None:
            period_cell = ws.cell(row=row, column=col, value=f"{period_change:.2f}%")
            # 设置背景色 - 根据涨跌幅
            color = get_color_for_period_change(period_change)
            if color:
                period_cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        else:
            period_cell = ws.cell(row=row, column=col, value="--")
    except Exception as e:
        print(f"计算周期涨跌幅时出错: {e}, 股票: {stock_name}")
        period_cell = ws.cell(row=row, column=col, value="--")

    # 设置周期涨跌幅单元格格式
    period_cell.alignment = Alignment(horizontal='center')
    period_cell.border = BORDER_STYLE
    period_cell.font = Font(size=9)  # 设置小一号字体

    return period_cell


def format_board_cell(ws, row, col, board_days, pure_stock_code, stock_detail_key, stock_details, current_date_obj):
    """
    格式化连板单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        board_days: 连板天数
        pure_stock_code: 纯股票代码
        stock_detail_key: 股票详细信息键名
        stock_details: 股票详细信息映射
        current_date_obj: 当前日期对象
        
    Returns:
        tuple: (单元格对象, 最后连板日期)
    """
    cell = ws.cell(row=row, column=col)

    # 对于首板（board_days=1），显示为"首板"，否则显示为"N板"
    if board_days == 1:
        # 获取市场标记
        market_marker = get_market_marker(pure_stock_code)
        board_text = f"首板{market_marker}"
    else:
        board_text = f"{int(board_days)}板"

    # 获取当前日期的YYYYMMDD格式
    date_yyyymmdd = current_date_obj.strftime('%Y%m%d')

    # 添加成交量比信息
    board_text = add_volume_ratio_to_text(board_text, pure_stock_code, date_yyyymmdd)

    cell.value = board_text
    # 设置连板颜色
    board_level = int(board_days)
    color = BOARD_COLORS.get(board_level, BOARD_COLORS[10] if board_level > 10 else BOARD_COLORS[1])
    cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    # 文字颜色设为白色以增强可读性
    cell.font = Font(color="FFFFFF", bold=True)
    # 添加边框样式
    cell.border = BORDER_STYLE

    # 添加备注信息（仅对连板股票）
    if stock_detail_key in stock_details:
        details = stock_details[stock_detail_key]
        comment_text = build_comment_text(details)
        if comment_text:
            cell.comment = Comment(comment_text.strip(), "涨停信息")

    # 记录当前日期为最后一次连板的日期
    last_board_date = current_date_obj

    return cell, last_board_date


def format_shouban_cell(ws, row, col, pure_stock_code, current_date_obj):
    """
    格式化首板单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        pure_stock_code: 纯股票代码
        current_date_obj: 当前日期对象
        
    Returns:
        tuple: (单元格对象, 最后连板日期)
    """
    cell = ws.cell(row=row, column=col)

    # 获取市场标记
    market_marker = get_market_marker(pure_stock_code)
    # 显示为"首板"并使用特殊颜色
    board_text = f"首板{market_marker}"

    # 获取当前日期的YYYYMMDD格式
    date_yyyymmdd = current_date_obj.strftime('%Y%m%d')

    # 添加成交量比信息
    board_text = add_volume_ratio_to_text(board_text, pure_stock_code, date_yyyymmdd)

    cell.value = board_text
    cell.fill = PatternFill(start_color=BOARD_COLORS[1], fill_type="solid")
    # 文字颜色设为白色以增强可读性
    cell.font = Font(color="FFFFFF", bold=True)
    # 添加边框样式
    cell.border = BORDER_STYLE

    # 更新最后连板日期以便可以继续跟踪
    last_board_date = current_date_obj

    return cell, last_board_date


def format_daily_pct_change_cell(ws, row, col, current_date_obj, stock_code, stock_name):
    """
    格式化日涨跌幅单元格
    
    Args:
        ws: Excel工作表
        row: 行索引
        col: 列索引
        current_date_obj: 当前日期对象
        stock_code: 股票代码
        stock_name: 股票名称

    Returns:
        单元格对象
    """
    cell = ws.cell(row=row, column=col)

    # 获取当日涨跌幅
    date_yyyymmdd = current_date_obj.strftime('%Y%m%d')
    pct_change = get_stock_daily_pct_change(stock_code, date_yyyymmdd, stock_name)
    if pct_change is not None:
        # 基本涨跌幅显示
        cell_value = f"{pct_change:.2f}%"

        # 添加成交量比信息
        cell_value = add_volume_ratio_to_text(cell_value, stock_code, date_yyyymmdd, stock_name)

        cell.value = cell_value

        # 设置背景色 - 根据涨跌幅
        color = get_color_for_pct_change(pct_change)
        if color:
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    else:
        cell.value = "停牌"

    # 设置单元格格式
    cell.alignment = Alignment(horizontal='center')
    cell.border = BORDER_STYLE

    return cell


def process_daily_cell(ws, row_idx, col_idx, formatted_day, board_days, found_in_shouban,
                       pure_stock_code, stock_details, stock, date_mapping, max_tracking_days,
                       max_tracking_days_before):
    """
    处理每日单元格
    
    Args:
        ws: Excel工作表
        row_idx: 行索引
        col_idx: 列索引
        formatted_day: 格式化的日期
        board_days: 连板天数
        found_in_shouban: 是否在首板数据中找到
        pure_stock_code: 纯股票代码
        stock_details: 股票详细信息映射
        stock: 股票数据
        date_mapping: 日期映射
        max_tracking_days: 断板后跟踪的最大天数
        max_tracking_days_before: 入选前跟踪的最大天数
        
    Returns:
        更新后的股票数据
    """
    cell = ws.cell(row=row_idx, column=col_idx)

    # 解析当前日期对象
    current_date_obj = datetime.strptime(formatted_day, '%Y年%m月%d日') if '年' in formatted_day else datetime.strptime(
        formatted_day, '%Y/%m/%d')

    # 处理连板数据
    if pd.notna(board_days) and board_days:
        stock_detail_key = f"{pure_stock_code}_{formatted_day}"
        _, last_board_date = format_board_cell(ws, row_idx, col_idx, board_days, pure_stock_code,
                                               stock_detail_key, stock_details, current_date_obj)
        stock['last_board_date'] = last_board_date
    # 处理首板数据
    elif found_in_shouban:
        _, last_board_date = format_shouban_cell(ws, row_idx, col_idx, pure_stock_code, current_date_obj)
        stock['last_board_date'] = last_board_date
    # 处理其他情况
    else:
        try:
            # 检查当日日期是否在首次显著连板日期之后
            if current_date_obj >= stock['first_significant_date']:
                # 处理断板后的跟踪
                if should_track_after_break(stock, current_date_obj, max_tracking_days):
                    format_daily_pct_change_cell(ws, row_idx, col_idx, current_date_obj,
                                                 stock['stock_code'], stock['stock_name'])
            # 检查当日日期是否在首次显著连板日期之前，且在跟踪天数范围内
            elif should_track_before_entry(current_date_obj, stock['first_significant_date'], max_tracking_days_before):
                format_daily_pct_change_cell(ws, row_idx, col_idx, current_date_obj,
                                             stock['stock_code'], stock['stock_name'])
        except Exception as e:
            print(f"处理日期时出错: {e}, 日期: {formatted_day}")

    return stock


def should_track_after_break(stock, current_date_obj, max_tracking_days):
    """
    判断是否应该跟踪断板后的股票
    
    Args:
        stock: 股票数据
        current_date_obj: 当前日期对象
        max_tracking_days: 断板后跟踪的最大天数
        
    Returns:
        bool: 是否应该跟踪
    """
    # 如果没有设置最大跟踪天数，始终跟踪
    if max_tracking_days is None:
        return True

    # 如果有最后连板日期记录，判断是否超过跟踪期限
    last_board_date = stock.get('last_board_date')
    if last_board_date:
        # 计算当前日期与最后连板日期的交易日天数差
        days_after_break = count_trading_days_between(last_board_date, current_date_obj)
        # 如果断板后的交易日天数超过跟踪天数，不显示涨跌幅
        if days_after_break > max_tracking_days:
            return False

    return True


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

    # 查找在首板数据中是否有该股票在该日期的记录
    shouban_row = shouban_df[(shouban_df['纯代码'] == pure_stock_code)]
    if not shouban_row.empty and formatted_day in shouban_row.columns and pd.notna(
            shouban_row[formatted_day].values[0]):
        # 该股票在该日期有首板记录
        return True

    return False


def setup_excel_header(ws, formatted_trading_days, show_period_change, period_days, date_column_start):
    """
    设置Excel表头
    
    Args:
        ws: Excel工作表
        formatted_trading_days: 格式化的交易日列表
        show_period_change: 是否显示周期涨跌幅
        period_days: 周期天数
        date_column_start: 日期列开始位置
        
    Returns:
        dict: 日期到列索引的映射
    """
    # 设置日期表头（第1行）
    format_header_cell(ws, 1, 1, "股票代码")
    format_header_cell(ws, 1, 2, "题材概念")
    format_header_cell(ws, 1, 3, "股票简称")

    # 添加周期涨跌幅列（第4列）
    if show_period_change:
        period_header = f"{period_days}日"
        format_header_cell(ws, 1, 4, period_header, font_size=9)

    # 设置日期列标题
    date_columns = {}  # 用于保存日期到列索引的映射
    for i, formatted_day in enumerate(formatted_trading_days):
        date_obj = datetime.strptime(formatted_day, '%Y年%m月%d日')
        col = i + date_column_start  # 日期列的起始位置根据是否显示周期涨跌幅决定
        date_columns[formatted_day] = col

        # 添加日期标题和星期几
        weekday = date_obj.weekday()
        weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
        date_with_weekday = f"{date_obj.strftime('%Y-%m-%d')}\n{weekday_map[weekday]}"

        # 设置日期单元格样式：居中、自动换行、边框、字体加粗
        date_cell = ws.cell(row=1, column=col, value=date_with_weekday)
        date_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        date_cell.border = BORDER_STYLE
        date_cell.font = Font(bold=True)

    return date_columns


@timer
def build_ladder_chart(start_date, end_date, output_file=OUTPUT_FILE, min_board_level=2,
                       max_tracking_days=MAX_TRACKING_DAYS_AFTER_BREAK, reentry_days=REENTRY_DAYS_THRESHOLD,
                       non_main_board_level=1, max_tracking_days_before=MAX_TRACKING_DAYS_BEFORE_ENTRY,
                       period_days=PERIOD_DAYS_CHANGE, show_period_change=False, priority_reasons=None,
                       enable_attention_criteria=False):
    """
    构建梯队形态的涨停复盘图
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)，如果为None则使用当前日期
        output_file: 输出文件路径
        min_board_level: 主板股票最小显著连板天数，默认为2
        max_tracking_days: 断板后跟踪的最大天数，默认取全局配置
        reentry_days: 断板后再次上榜的天数阈值，默认取全局配置
        non_main_board_level: 非主板股票最小显著连板天数，默认为1
        max_tracking_days_before: 入选前跟踪的最大天数，默认取全局配置
        period_days: 计算入选日与之前X个交易日的涨跌幅，默认取全局配置
        show_period_change: 是否显示周期涨跌幅列，默认取全局配置
        priority_reasons: 优先选择的原因列表，默认为None
        enable_attention_criteria: 是否启用关注度榜入选条件，默认为False
    """
    # 清除缓存
    get_stock_data.cache_clear()

    # 设置结束日期，如果未指定则使用当前日期
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
        print(f"未指定结束日期，使用当前日期: {end_date}")

    print(f"开始构建梯队形态涨停复盘图 ({start_date} 至 {end_date})...")

    # 获取并处理交易日数据
    trading_days = get_trading_days(start_date, end_date)
    if not trading_days:
        print("未获取到交易日列表")
        return

    # 格式化交易日列表和映射
    formatted_trading_days, date_mapping = format_trading_days(trading_days)

    # 加载股票数据
    lianban_df, shouban_df, attention_data = load_stock_data(start_date, end_date, enable_attention_criteria)
    if lianban_df.empty:
        print("未获取到有效的连板数据")
        return

    # 获取股票详细信息映射
    stock_details = lianban_df.attrs.get('stock_details', {})

    # 识别显著连板股票
    result_df = identify_significant_boards(lianban_df, shouban_df, min_board_level, reentry_days,
                                            non_main_board_level, enable_attention_criteria, attention_data)
    if result_df.empty:
        print(f"未找到在{start_date}至{end_date}期间有符合条件的显著连板股票")
        return

    # 创建Excel工作簿和准备数据
    wb, ws, stock_data = prepare_excel_workbook(result_df, start_date, priority_reasons)

    # 如果需要显示周期涨跌幅，预计算交易日映射缓存用于提速
    if show_period_change:
        precompute_trading_days_lookup(start_date, end_date, period_days)

    # 设置Excel表头和日期列
    period_column = 4
    date_column_start = 4 if not show_period_change else 5
    date_columns = setup_excel_header(ws, formatted_trading_days, show_period_change, period_days, date_column_start)

    # 设置前三列的格式（已由setup_excel_header处理）

    # 添加大盘指标行
    add_market_indicators(ws, date_columns, label_col=2)

    # 统计股票入选情况
    stock_entry_count = count_stock_entries(result_df)

    # 填充数据行
    fill_data_rows(ws, result_df, shouban_df, stock_data['stock_reason_group'], stock_data['reason_colors'],
                   stock_entry_count, formatted_trading_days, date_column_start, show_period_change,
                   period_column, period_days, stock_details, date_mapping, max_tracking_days,
                   max_tracking_days_before)

    # 调整列宽
    adjust_column_widths(ws, formatted_trading_days, date_column_start, show_period_change)

    # 冻结前三列和前三行
    ws.freeze_panes = ws.cell(row=4, column=date_column_start)

    # 创建图例工作表
    create_legend_sheet(wb, stock_data['reason_counter'], stock_data['reason_colors'],
                        stock_data['top_reasons'], HIGH_BOARD_COLORS, REENTRY_COLORS)

    # 保存Excel文件
    try:
        save_excel_file(wb, output_file)
        return True
    except Exception as e:
        print(f"保存Excel文件时出错: {e}")
        return False


def format_trading_days(trading_days):
    """
    格式化交易日列表
    
    Args:
        trading_days: 交易日列表
        
    Returns:
        tuple: (格式化的交易日列表, 日期映射)
    """
    formatted_trading_days = []
    date_mapping = {}  # 用于将格式化日期映射回YYYYMMDD格式

    for day in trading_days:
        date_obj = datetime.strptime(day, '%Y%m%d')

        # 标准格式 YYYY/MM/DD
        formatted_day_slash = date_obj.strftime('%Y/%m/%d')
        # 中文格式 YYYY年MM月DD日
        formatted_day_cn = date_obj.strftime('%Y年%m月%d日')

        # 使用中文格式作为主要格式
        formatted_trading_days.append(formatted_day_cn)
        date_mapping[formatted_day_cn] = day
        date_mapping[formatted_day_slash] = day  # 同时保存标准格式的映射

    return formatted_trading_days, date_mapping


def identify_significant_boards(lianban_df, shouban_df, min_board_level, reentry_days,
                                non_main_board_level, enable_attention_criteria, attention_data):
    """
    识别显著连板股票
    
    Args:
        lianban_df: 连板数据DataFrame
        shouban_df: 首板数据DataFrame
        min_board_level: 主板股票最小显著连板天数
        reentry_days: 断板后再次上榜的天数阈值
        non_main_board_level: 非主板股票最小显著连板天数
        enable_attention_criteria: 是否启用关注度榜入选条件
        attention_data: 关注度榜数据
        
    Returns:
        pandas.DataFrame: 显著连板股票DataFrame
    """
    return identify_first_significant_board(
        lianban_df, shouban_df, min_board_level, reentry_days, non_main_board_level,
        enable_attention_criteria, attention_data['main'], attention_data['non_main']
    )


def prepare_excel_workbook(result_df, start_date, priority_reasons):
    """
    准备Excel工作簿和相关数据
    
    Args:
        result_df: 显著连板股票DataFrame
        start_date: 开始日期
        priority_reasons: 优先选择的原因列表
        
    Returns:
        tuple: (工作簿, 工作表, 股票数据)
    """
    # 创建Excel工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = f"涨停梯队{start_date[:6]}"

    # 收集所有概念信息，用于生成颜色映射
    all_concepts, stock_concepts = collect_stock_concepts(result_df)

    # 获取热门概念的颜色映射
    reason_colors, top_reasons = get_reason_colors(all_concepts, priority_reasons=priority_reasons)

    # 为每只股票确定主要概念组
    all_stocks = prepare_stock_concept_data(stock_concepts)

    # 获取每只股票的主要概念组
    stock_reason_group = get_stock_reason_group(all_stocks, top_reasons)

    # 创建理由计数器
    reason_counter = Counter(all_concepts)

    # 返回工作簿、工作表和股票数据
    stock_data = {
        'reason_colors': reason_colors,
        'top_reasons': top_reasons,
        'stock_reason_group': stock_reason_group,
        'reason_counter': reason_counter
    }

    return wb, ws, stock_data


def collect_stock_concepts(result_df):
    """
    收集股票概念信息
    
    Args:
        result_df: 显著连板股票DataFrame
        
    Returns:
        tuple: (所有概念列表, 股票概念映射)
    """
    all_concepts = []
    stock_concepts = {}

    # 从result_df中收集所有概念
    for _, row in result_df.iterrows():
        concept = row.get('concept', '其他')
        if pd.isna(concept) or not concept:
            concept = "其他"

        # 提取概念中的原因
        reasons = extract_reasons(concept)
        if reasons:
            all_concepts.extend(reasons)
            stock_concepts[f"{row['stock_code']}_{row['stock_name']}"] = reasons

    return all_concepts, stock_concepts


def prepare_stock_concept_data(stock_concepts):
    """
    准备股票概念数据
    
    Args:
        stock_concepts: 股票概念映射
        
    Returns:
        dict: 股票概念数据
    """
    all_stocks = {}
    for stock_key, reasons in stock_concepts.items():
        all_stocks[stock_key] = {
            'name': stock_key.split('_')[1],
            'reasons': reasons,
            'appearances': [1]  # 简化处理，只需要一个非空列表
        }

    return all_stocks


def count_stock_entries(result_df):
    """
    统计股票入选次数
    
    Args:
        result_df: 显著连板股票DataFrame
        
    Returns:
        dict: 股票入选次数映射
    """
    # 收集所有已入选连板梯队的股票代码
    lianban_stock_codes = set()
    # 统计每只股票入选次数
    stock_entry_count = {}

    for _, row in result_df.iterrows():
        # 纯代码作为标识
        pure_code = row['stock_code'].split('_')[0] if '_' in row['stock_code'] else row['stock_code']
        lianban_stock_codes.add(pure_code)

        # 统计入选次数
        if pure_code in stock_entry_count:
            stock_entry_count[pure_code] += 1
        else:
            stock_entry_count[pure_code] = 1

    return stock_entry_count


def fill_data_rows(ws, result_df, shouban_df, stock_reason_group, reason_colors, stock_entry_count,
                   formatted_trading_days, date_column_start, show_period_change, period_column,
                   period_days, stock_details, date_mapping, max_tracking_days, max_tracking_days_before):
    """
    填充数据行
    
    Args:
        ws: Excel工作表
        result_df: 显著连板股票DataFrame
        shouban_df: 首板数据DataFrame
        stock_reason_group: 股票概念组映射
        reason_colors: 概念颜色映射
        stock_entry_count: 股票入选次数映射
        formatted_trading_days: 格式化的交易日列表
        date_column_start: 日期列开始位置
        show_period_change: 是否显示周期涨跌幅
        period_column: 周期涨跌幅列索引
        period_days: 周期天数
        stock_details: 股票详细信息映射
        date_mapping: 日期映射
        max_tracking_days: 断板后跟踪的最大天数
        max_tracking_days_before: 入选前跟踪的最大天数
    """
    for i, (_, stock) in enumerate(result_df.iterrows()):
        row_idx = i + 4  # 行索引，从第4行开始（第1行是日期标题，第2-3行是大盘指标）

        # 提取基本股票信息
        stock_code = stock['stock_code']
        stock_name = stock['stock_name']
        all_board_data = stock['all_board_data']

        # 提取纯代码
        pure_stock_code = extract_pure_stock_code(stock_code)

        # 设置股票代码列（第一列）
        format_stock_code_cell(ws, row_idx, 1, pure_stock_code)

        # 获取概念
        concept = get_stock_concept(stock)

        # 设置概念列（第二列）
        stock_key = f"{stock_code}_{stock_name}"
        format_concept_cell(ws, row_idx, 2, concept, stock_key, stock_reason_group, reason_colors)

        # 计算股票的最高板数
        max_board_level = calculate_max_board_level(all_board_data)

        # 根据股票代码确定市场类型
        market_type = get_market_marker(pure_stock_code)

        # 设置股票简称列（第三列）
        apply_high_board_color = False
        _, apply_high_board_color = format_stock_name_cell(ws, row_idx, 3, stock_name, market_type,
                                                           max_board_level, apply_high_board_color,
                                                           pure_stock_code, stock_entry_count)

        # 填充周期涨跌幅列
        if show_period_change:
            format_period_change_cell(ws, row_idx, period_column, stock_code, stock_name,
                                      stock['first_significant_date'], period_days)

        # 填充每个交易日的数据
        fill_daily_data(ws, row_idx, formatted_trading_days, date_column_start, all_board_data,
                        shouban_df, pure_stock_code, stock_details, stock, date_mapping,
                        max_tracking_days, max_tracking_days_before)


def extract_pure_stock_code(stock_code):
    """
    提取纯股票代码
    
    Args:
        stock_code: 股票代码
        
    Returns:
        str: 纯股票代码
    """
    pure_stock_code = stock_code.split('_')[0] if '_' in stock_code else stock_code
    if pure_stock_code.startswith(('sh', 'sz', 'bj')):
        pure_stock_code = pure_stock_code[2:]

    return pure_stock_code


def get_stock_concept(stock):
    """
    获取股票概念
    
    Args:
        stock: 股票数据
        
    Returns:
        str: 概念文本
    """
    concept = stock.get('concept', '其他')
    if pd.isna(concept) or not concept:
        concept = "其他"

    return concept


def calculate_max_board_level(all_board_data):
    """
    计算股票的最高板数
    
    Args:
        all_board_data: 所有板块数据
        
    Returns:
        int: 最高板数
    """
    max_board_level = 0
    for day_data in all_board_data.values():
        if pd.notna(day_data) and day_data and day_data > max_board_level:
            max_board_level = int(day_data)

    return max_board_level


def fill_daily_data(ws, row_idx, formatted_trading_days, date_column_start, all_board_data,
                    shouban_df, pure_stock_code, stock_details, stock, date_mapping,
                    max_tracking_days, max_tracking_days_before):
    """
    填充每日数据
    
    Args:
        ws: Excel工作表
        row_idx: 行索引
        formatted_trading_days: 格式化的交易日列表
        date_column_start: 日期列开始位置
        all_board_data: 所有板块数据
        shouban_df: 首板数据DataFrame
        pure_stock_code: 纯股票代码
        stock_details: 股票详细信息映射
        stock: 股票数据
        date_mapping: 日期映射
        max_tracking_days: 断板后跟踪的最大天数
        max_tracking_days_before: 入选前跟踪的最大天数
    """
    for j, formatted_day in enumerate(formatted_trading_days):
        col_idx = j + date_column_start  # 列索引，从date_column_start开始

        # 获取当日的连板信息
        board_days = all_board_data.get(formatted_day)

        # 标记是否在首板数据中找到该股票
        found_in_shouban = check_stock_in_shouban(shouban_df, pure_stock_code, formatted_day)

        # 处理单元格
        stock = process_daily_cell(ws, row_idx, col_idx, formatted_day, board_days, found_in_shouban,
                                   pure_stock_code, stock_details, stock, date_mapping,
                                   max_tracking_days, max_tracking_days_before)


def adjust_column_widths(ws, formatted_trading_days, date_column_start, show_period_change):
    """
    调整列宽
    
    Args:
        ws: Excel工作表
        formatted_trading_days: 格式化的交易日列表
        date_column_start: 日期列开始位置
        show_period_change: 是否显示周期涨跌幅
    """
    # 调整列宽
    ws.column_dimensions['A'].width = 8  # 股票代码列宽度设置窄一些
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 15

    if show_period_change:
        ws.column_dimensions['D'].width = 8  # 周期涨跌幅列宽度减小

    for i in range(len(formatted_trading_days)):
        col_letter = get_column_letter(i + date_column_start)
        ws.column_dimensions[col_letter].width = 12

    # 调整行高，确保日期和星期能完整显示
    ws.row_dimensions[1].height = 30


def save_excel_file(wb, output_file):
    """
    保存Excel文件
    
    Args:
        wb: Excel工作簿
        output_file: 输出文件路径
    """
    output_dir = os.path.dirname(output_file)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    wb.save(output_file)
    print(f"梯队形态涨停复盘图已生成: {output_file}")


if __name__ == "__main__":
    import argparse

    # 命令行参数解析
    parser = argparse.ArgumentParser(description='生成梯队形态的涨停复盘图')
    parser.add_argument('--start_date', type=str, default="20230501",
                        help='开始日期 (格式: YYYYMMDD)')
    parser.add_argument('--end_date', type=str, default="20230531",
                        help='结束日期 (格式: YYYYMMDD)')
    parser.add_argument('--output', type=str, default=OUTPUT_FILE,
                        help=f'输出文件路径 (默认: {OUTPUT_FILE})')
    parser.add_argument('--min_board', type=int, default=2,
                        help='主板股票最小显著连板天数 (默认: 2)')
    parser.add_argument('--max_tracking', type=int, default=MAX_TRACKING_DAYS_AFTER_BREAK,
                        help=f'断板后跟踪的最大天数 (默认: {MAX_TRACKING_DAYS_AFTER_BREAK}，设为-1表示一直跟踪)')
    parser.add_argument('--reentry_days', type=int, default=REENTRY_DAYS_THRESHOLD,
                        help=f'断板后再次达到2板作为新行的天数阈值 (默认: {REENTRY_DAYS_THRESHOLD})')
    parser.add_argument('--non_main_board', type=int, default=1,
                        help='非主板股票最小显著连板天数 (默认: 1)')
    parser.add_argument('--max_tracking_before', type=int, default=MAX_TRACKING_DAYS_BEFORE_ENTRY,
                        help=f'入选前跟踪的最大天数 (默认: {MAX_TRACKING_DAYS_BEFORE_ENTRY}，设为0表示不显示入选前走势)')
    parser.add_argument('--period_days', type=int, default=PERIOD_DAYS_CHANGE,
                        help=f'计算入选日与之前X个交易日的涨跌幅 (默认: {PERIOD_DAYS_CHANGE})')
    parser.add_argument('--show_period_change', action='store_true',
                        help='是否显示周期涨跌幅列 (默认: 不显示)')
    parser.add_argument('--priority_reasons', type=str, default="",
                        help='优先选择的原因列表，使用逗号分隔 (例如: "旅游,房地产,AI")')
    parser.add_argument('--enable_attention_criteria', action='store_true',
                        help='是否启用关注度榜入选条件：(board_level-1)连板后5天内两次入选关注度榜前20 (默认: 不启用)')
    parser.add_argument('--volume_days', type=int, default=VOLUME_DAYS,
                        help=f'计算成交量比的天数，当天成交量与前X天平均成交量的比值 (默认: {VOLUME_DAYS})')
    parser.add_argument('--volume_ratio', type=float, default=VOLUME_RATIO_THRESHOLD,
                        help=f'成交量比阈值，超过该值则在单元格中显示成交量比 (默认: {VOLUME_RATIO_THRESHOLD})')

    args = parser.parse_args()

    # 处理max_tracking参数
    max_tracking = None if args.max_tracking == -1 else args.max_tracking

    # 处理优先原因列表
    priority_reasons = [reason.strip() for reason in
                        args.priority_reasons.split(',')] if args.priority_reasons else None

    # 更新全局成交量参数
    VOLUME_DAYS = args.volume_days
    VOLUME_RATIO_THRESHOLD = args.volume_ratio

    # 构建梯队图
    build_ladder_chart(args.start_date, args.end_date, args.output, args.min_board,
                       max_tracking, args.reentry_days, args.non_main_board,
                       args.max_tracking_before, args.period_days, args.show_period_change,
                       priority_reasons=priority_reasons, enable_attention_criteria=args.enable_attention_criteria)
