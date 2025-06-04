import os
import re
from collections import Counter
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill, Alignment, Font, Border, Side
from openpyxl.utils import get_column_letter

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

# 是否显示周期涨跌幅列
SHOW_PERIOD_CHANGE = False

# 计算入选日与之前X个交易日的涨跌幅
# 例如设置为20，会计算入选日与20个交易日之前的涨跌幅
PERIOD_DAYS_CHANGE = 10

# 输入和输出文件路径
FUPAN_FILE = "./excel/fupan_stocks.xlsx"
OUTPUT_FILE = "./excel/ladder_analysis.xlsx"

# 股票数据保存路径
STOCK_DATA_PATH = "./data/astocks/"

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

# 股票周期涨跌幅缓存
PERIOD_CHANGE_CACHE = {}

# 股票文件路径缓存
STOCK_FILE_PATH_CACHE = {}


def get_stock_file_path(stock_code, stock_name=None, save_path=STOCK_DATA_PATH):
    """
    获取股票数据文件路径
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称，用于构建文件名
        save_path: 股票数据存储路径
        
    Returns:
        str: 股票数据文件路径，如果找不到则返回None
    """
    # 检查缓存中是否已有结果
    if stock_code in STOCK_FILE_PATH_CACHE:
        return STOCK_FILE_PATH_CACHE[stock_code]

    # 处理股票代码格式
    clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code

    # 查找对应的文件
    file_path = None

    if stock_name:
        # 如果提供了股票名称，直接尝试使用
        safe_name = stock_name.replace('*ST', 'xST').replace('/', '_')
        possible_file = f"{clean_code}_{safe_name}.csv"
        if os.path.exists(os.path.join(save_path, possible_file)):
            file_path = os.path.join(save_path, possible_file)

    # 如果没有找到文件，尝试查找匹配的文件
    if not file_path:
        for file in os.listdir(save_path):
            # 匹配文件名前缀为股票代码的文件
            if file.startswith(f"{clean_code}_") and file.endswith(".csv"):
                file_path = os.path.join(save_path, file)
                break

    if not file_path:
        # 如果还是没找到，可能需要处理前导零的情况
        if clean_code.startswith('0'):
            # 尝试去掉前导零
            stripped_code = clean_code.lstrip('0')
            if stripped_code:  # 确保不是全零
                for file in os.listdir(save_path):
                    if file.startswith(f"{stripped_code}_") and file.endswith(".csv"):
                        file_path = os.path.join(save_path, file)
                        break

        # 对于上交所股票，可能需要处理6开头的代码
        elif clean_code.startswith('6'):
            for file in os.listdir(save_path):
                if file.startswith(f"{clean_code}_") and file.endswith(".csv"):
                    file_path = os.path.join(save_path, file)
                    break

    # 将结果存入缓存
    STOCK_FILE_PATH_CACHE[stock_code] = file_path

    return file_path


def get_stock_daily_pct_change(stock_code, date_str_yyyymmdd, stock_name=None, save_path=STOCK_DATA_PATH):
    """
    获取指定股票在特定日期的涨跌幅
    
    Args:
        stock_code: 股票代码
        date_str_yyyymmdd: 目标日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
        save_path: 股票数据存储路径
    
    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
    """
    try:
        if not stock_code:
            return None

        # 目标日期（YYYY-MM-DD格式）
        target_date = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"

        # 获取股票数据文件路径
        file_path = get_stock_file_path(stock_code, stock_name, save_path)

        # 如果没有找到文件
        if not file_path:
            return None

        # 读取CSV文件
        df = pd.read_csv(file_path, header=None,
                         names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                '振幅', '涨跌幅', '涨跌额', '换手率'])

        # 查找目标日期的数据
        target_row = df[df['日期'] == target_date]

        # 如果找到数据，返回涨跌幅
        if not target_row.empty:
            return target_row['涨跌幅'].values[0]

        # 如果没有找到对应日期的数据，可能是停牌或者数据不完整
        return None

    except Exception as e:
        print(f"获取股票 {stock_code} ({stock_name}) 在 {date_str_yyyymmdd} 的涨跌幅时出错: {e}")
        return None


def load_stock_mapping():
    """
    加载股票代码和名称的映射
    
    Returns:
        dict: 股票名称到代码的映射字典
    """
    try:
        mapping_file = "./data/stock_mapping.csv"
        if not os.path.exists(mapping_file):
            print(f"股票代码映射文件不存在: {mapping_file}")
            return {}

        mapping_df = pd.read_csv(mapping_file)
        mapping = {}
        for _, row in mapping_df.iterrows():
            # 股票名称去除所有空格
            name = row['name'].replace(' ', '')
            code = row['code']
            mapping[name] = code
        return mapping
    except Exception as e:
        print(f"加载股票代码映射失败: {e}")
        return {}


def extract_board_info(board_text):
    """
    从连板文本中提取连板天数和状态
    
    Args:
        board_text: 连板文本，如 "2板", "3板", "2晋级", "2天2板"
    
    Returns:
        tuple: (连板天数, 状态)，如 (2, "板"), (3, "晋级"), (None, "断板")
    """
    if not board_text or pd.isna(board_text):
        return None, None

    board_text = str(board_text).strip()

    # 检查特殊状态
    if board_text in ["断板", "炸板"]:
        return None, board_text

    # 处理"N天N板"格式
    days_board_match = re.search(r'(\d+)天(\d+)板', board_text)
    if days_board_match:
        # 使用第二个数字作为板数
        board_days = int(days_board_match.group(2))
        return board_days, "板"

    # 尝试提取连板天数 - 标准格式: "2板"
    match = re.search(r'(\d+)([板晋级]*)', board_text)
    if match:
        days = int(match.group(1))
        status = match.group(2) if match.group(2) else "板"
        return days, status

    # 如果是纯数字，可能直接表示连板天数
    if board_text.isdigit():
        days = int(board_text)
        return days, "板"

    # 可能包含股票名称+连板信息，尝试提取数字部分
    numbers = re.findall(r'\d+', board_text)
    if numbers:
        for num in numbers:
            # 假设最后一个数字是连板天数
            days = int(num)
            if days >= 2:  # 通常连板数至少是2
                return days, "板"

    # 如果包含"2板"、"3板"等特定字符串
    for pattern in ["2板", "3板", "4板", "5板", "6板", "7板", "8板", "9板", "10板"]:
        if pattern in board_text:
            days = int(pattern[0])
            return days, "板"

    return None, board_text


def load_lianban_data(start_date, end_date):
    """
    从Excel中加载连板数据
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        
    Returns:
        pandas.DataFrame: 处理后的连板数据
    """
    try:
        # 读取连板数据sheet
        try:
            df = pd.read_excel(FUPAN_FILE, sheet_name="连板数据")
            print(f"成功读取连板数据sheet，共有{len(df)}行，{len(df.columns)}列")
        except Exception as e:
            print(f"读取连板数据sheet失败: {e}")
            # 尝试查看所有sheet名称
            xl = pd.ExcelFile(FUPAN_FILE)
            print(f"Excel文件中的sheet: {xl.sheet_names}")

            # 如果没有"连板数据"sheet，尝试读取第一个sheet
            if len(xl.sheet_names) > 0:
                first_sheet = xl.sheet_names[0]
                print(f"尝试读取第一个sheet: {first_sheet}")
                df = pd.read_excel(FUPAN_FILE, sheet_name=first_sheet)
                print(f"读取成功，共有{len(df)}行，{len(df.columns)}列")
            else:
                return pd.DataFrame()

        # 打印列名，了解表结构
        print("列名: ", list(df.columns))

        # 打印前几行数据
        print("\n查看数据样本:")
        for i in range(min(5, len(df))):
            print(f"行 {i}:")
            first_col = df.columns[0]
            print(f"  {first_col}: {df.iloc[i][first_col]}")

            # 打印一些日期列的数据
            date_sample = [col for col in df.columns if '年' in str(col)][:3]
            for col in date_sample:
                print(f"  {col}: {df.iloc[i][col]}")

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
            print("连板数据中未找到有效的日期列")
            print("当前列名: ", list(df.columns))
            return pd.DataFrame()

        # 过滤日期范围
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
            if date_str >= start_date and date_str <= end_date:
                filtered_date_columns.append(col)

        if not filtered_date_columns:
            print(f"连板数据中未找到{start_date}到{end_date}范围内的数据")
            return pd.DataFrame()

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

                # 解析单元格内容，格式: "股票代码; 股票名称; ...; N天N板; ..."
                cell_text = str(cell_value)
                parts = cell_text.split(';')

                if len(parts) < 5:
                    continue

                # 根据fupan.py中get_zt_stocks方法的固定字段顺序提取信息
                # 字段顺序: 股票代码, 股票简称, 涨停开板次数, 最终涨停时间, 几天几板, 最新价, 首次涨停时间, 最新涨跌幅, 连续涨停天数, 涨停原因类别
                stock_code = parts[0].strip()
                stock_name = parts[1].strip()

                # 确保parts有足够的元素
                open_count = parts[2].strip() if len(parts) > 2 else None
                final_time = parts[3].strip() if len(parts) > 3 else None
                board_info = parts[4].strip() if len(parts) > 4 else None
                first_time = parts[6].strip() if len(parts) > 6 else None
                concept = parts[-1].strip() if parts else "其他"  # 最后一个元素通常是概念信息

                # 如果找到连板信息
                if board_info:
                    board_days, _ = extract_board_info(board_info)

                    if board_days:
                        stock_data = {
                            '股票代码': f"{stock_code}_{stock_name}",
                            '纯代码': stock_code,
                            '股票名称': stock_name,
                            '日期': date_col,
                            '连板天数': board_days,
                            '连板信息': board_info,
                            '概念': concept
                        }

                        # 添加额外的详细信息
                        if first_time:
                            stock_data['首次涨停时间'] = first_time
                        if final_time:
                            stock_data['最终涨停时间'] = final_time
                        if open_count:
                            stock_data['涨停开板次数'] = open_count

                        processed_data.append(stock_data)

        # 转换为DataFrame
        result_df = pd.DataFrame(processed_data)

        if result_df.empty:
            print("未能从日期单元格中提取有效的连板数据")
            return pd.DataFrame()

        print(f"处理后的数据: {len(result_df)}行，包含{len(filtered_date_columns)}个日期列")

        # 透视数据，以便每只股票占一行，每个日期占一列
        pivot_df = result_df.pivot(index=['纯代码', '股票名称'], columns='日期', values='连板天数')

        # 重置索引，将股票代码和名称变为普通列
        pivot_df = pivot_df.reset_index()

        # 添加一个概念列（使用最新的概念，而不是第一次出现的概念）
        concept_mapping = result_df.groupby('纯代码')['概念'].last().to_dict()
        pivot_df['概念'] = pivot_df['纯代码'].map(concept_mapping)

        # 添加标准格式的股票代码列
        pivot_df['股票代码'] = pivot_df['纯代码'] + '_' + pivot_df['股票名称']

        # 创建一个股票详细信息的映射，用于后续添加备注
        stock_details = {}
        for _, row in result_df.iterrows():
            stock_key = f"{row['纯代码']}_{row['日期']}"
            details = {}

            # 收集可能存在的详细信息
            for field in ['首次涨停时间', '最终涨停时间', '涨停开板次数', '连板信息']:
                if field in row and not pd.isna(row[field]):
                    details[field] = row[field]

            stock_details[stock_key] = details

        # 将详细信息添加到pivot_df的属性中，以便后续使用
        pivot_df.attrs['stock_details'] = stock_details

        return pivot_df

    except Exception as e:
        print(f"加载连板数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def load_shouban_data(start_date, end_date):
    """
    从Excel中加载首板数据
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        
    Returns:
        pandas.DataFrame: 处理后的首板数据
    """
    try:
        # 读取首板数据sheet
        try:
            df = pd.read_excel(FUPAN_FILE, sheet_name="首板数据")
            print(f"成功读取首板数据sheet，共有{len(df)}行，{len(df.columns)}列")
        except Exception as e:
            print(f"读取首板数据sheet失败: {e}")
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
            print("首板数据中未找到有效的日期列")
            print("当前列名: ", list(df.columns))
            return pd.DataFrame()

        # 过滤日期范围
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
            if date_str >= start_date and date_str <= end_date:
                filtered_date_columns.append(col)

        if not filtered_date_columns:
            print(f"首板数据中未找到{start_date}到{end_date}范围内的数据")
            return pd.DataFrame()

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

                # 解析单元格内容，格式: "股票代码; 股票名称; ...; 首板涨停; ..."
                cell_text = str(cell_value)
                parts = cell_text.split(';')

                if len(parts) < 5:
                    continue

                stock_code = parts[0].strip()
                stock_name = parts[1].strip()

                # 处理股票代码，去除可能的市场前缀
                if stock_code.startswith(('sh', 'sz', 'bj')):
                    stock_code = stock_code[2:]

                # 用于标记首板
                board_info = "首板涨停"
                concept = "其他"

                # 提取概念信息（通常是最后一个部分）
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        concept = part.strip()

                processed_data.append({
                    '股票代码': f"{stock_code}_{stock_name}",
                    '纯代码': stock_code,
                    '股票名称': stock_name,
                    '日期': date_col,
                    '连板天数': 1,  # 首板为1
                    '连板信息': board_info,
                    '概念': concept
                })

        # 转换为DataFrame
        result_df = pd.DataFrame(processed_data)

        if result_df.empty:
            print("未能从首板数据中提取有效的数据")
            return pd.DataFrame()

        print(f"处理后的首板数据: {len(result_df)}行，包含{len(filtered_date_columns)}个日期列")

        # 透视数据，以便每只股票占一行，每个日期占一列
        pivot_df = result_df.pivot(index=['纯代码', '股票名称'], columns='日期', values='连板天数')

        # 重置索引，将股票代码和名称变为普通列
        pivot_df = pivot_df.reset_index()

        # 添加一个概念列（使用最新的概念，而不是第一次出现的概念）
        concept_mapping = result_df.groupby('纯代码')['概念'].last().to_dict()
        pivot_df['概念'] = pivot_df['纯代码'].map(concept_mapping)

        # 添加标准格式的股票代码列
        pivot_df['股票代码'] = pivot_df['纯代码'] + '_' + pivot_df['股票名称']

        return pivot_df

    except Exception as e:
        print(f"加载首板数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def identify_first_significant_board(df, shouban_df=None, min_board_level=2,
                                     reentry_days_threshold=REENTRY_DAYS_THRESHOLD, non_main_board_level=1):
    """
    识别每只股票首次达到显著连板（例如2板或以上）的日期，以及断板后再次达到的情况
    
    Args:
        df: 连板数据DataFrame，已透视处理，每行一只股票，每列一个日期
        shouban_df: 首板数据DataFrame，已透视处理，每行一只股票，每列一个日期
        min_board_level: 主板股票最小显著连板天数，默认为2
        reentry_days_threshold: 断板后再次上榜的天数阈值，超过这个天数再次达到入选条件会作为新记录
        non_main_board_level: 非主板股票最小显著连板天数，默认为1
        
    Returns:
        pandas.DataFrame: 添加了连板信息的DataFrame
    """
    # 创建结果DataFrame，包含股票代码、名称、首次显著连板日期和当日连板天数
    result = []

    # 找出日期列
    date_columns = [col for col in df.columns if col not in ['纯代码', '股票名称', '股票代码', '概念']]
    if not date_columns:
        print("无法找到日期列")
        return pd.DataFrame()

    # 将日期列按时间排序
    date_columns.sort()

    # 首先合并所有股票数据，创建一个完整的股票池
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

    # 3. 确定每只股票的市场类型
    for stock_code, stock_data in all_stocks.items():
        try:
            market = get_stock_market(stock_code)
            stock_data['market'] = market
        except Exception as e:
            print(f"判断股票 {stock_code} 市场类型时出错: {e}")
            stock_data['market'] = 'unknown'

    # 4. 分析每只股票，确定是否入选显著连板
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

            # 根据市场类型和对应的最小显著连板天数判断
            if market == 'main':
                # 主板股票需要达到min_board_level才算显著连板
                if board_days and board_days >= min_board_level:
                    is_significant = True
            elif market in ['gem', 'star', 'bse']:
                # 非主板股票需要达到non_main_board_level才算显著连板
                if board_days and board_days >= non_main_board_level:
                    is_significant = True
            else:
                # 其他情况，使用主板标准
                if board_days and board_days >= min_board_level:
                    is_significant = True

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
                    previous_board_dates = [d for d in continuous_board_dates if d < current_date]

                    if previous_board_dates:
                        # 获取上一个连板区间的最后日期
                        last_board_date = max(previous_board_dates)

                        # 计算间隔交易日天数
                        days_since_last_board = count_trading_days_between(last_board_date, current_date)

                        print(
                            f"    上一次连板日期: {last_board_date.strftime('%Y-%m-%d')}, 当前日期: {current_date.strftime('%Y-%m-%d')}, 交易日间隔: {days_since_last_board}天")

                        # 判断是否满足再次入选条件
                        if days_since_last_board > reentry_days_threshold:
                            # 检查是否达到入选条件
                            is_significant_reentry = False

                            # 与首次入选逻辑保持一致
                            if market == 'main':
                                if board_days >= min_board_level:
                                    is_significant_reentry = True
                            elif market in ['gem', 'star', 'bse']:
                                if board_days >= non_main_board_level:
                                    is_significant_reentry = True
                            else:
                                if board_days >= min_board_level:
                                    is_significant_reentry = True

                            if is_significant_reentry:
                                print(f"    断板后{days_since_last_board}个交易日再次达到入选条件，作为新记录")
                                is_new_entry = True
                                # 清空连续连板日期列表，开始新的连板区间记录
                                continuous_board_dates = [current_date]

                # 添加到显著连板日期列表
                significant_board_dates.append(current_date)

                if is_new_entry:
                    # 构建完整的板块数据字典
                    all_board_data = {}
                    for date_col in date_columns:
                        all_board_data[date_col] = board_data.get(date_col)

                    # 添加到结果列表
                    entry = {
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'first_significant_date': current_date,
                        'board_level_at_first': board_days,
                        'all_board_data': all_board_data,
                        'concept': stock_data['concept'],
                        'entry_type': 'reentry' if len(significant_board_dates) > 1 else (
                            'non_main_first_board' if market in ['gem', 'star', 'bse'] and board_days == 1 else 'first'
                        )
                    }

                    result.append(entry)
                    print(f"    记录显著连板: {stock_name} 在 {col} 达到 {board_days}板")

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


def calculate_stock_period_change(stock_code, start_date_yyyymmdd, end_date_yyyymmdd, stock_name=None,
                                  save_path=STOCK_DATA_PATH):
    """
    计算股票在两个日期之间的涨跌幅
    
    Args:
        stock_code: 股票代码
        start_date_yyyymmdd: 开始日期 (YYYYMMDD)
        end_date_yyyymmdd: 结束日期 (YYYYMMDD)
        stock_name: 股票名称，用于构建文件名
        save_path: 股票数据存储路径
    
    Returns:
        float: 涨跌幅百分比，如果数据不存在则返回None
    """
    # 检查缓存中是否已有结果
    cache_key = f"{stock_code}_{start_date_yyyymmdd}_{end_date_yyyymmdd}"
    if cache_key in PERIOD_CHANGE_CACHE:
        return PERIOD_CHANGE_CACHE[cache_key]

    try:
        if not stock_code:
            return None

        # 获取股票数据文件路径
        file_path = get_stock_file_path(stock_code, stock_name, save_path)

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

        # 获取收盘价
        start_price = start_row['收盘'].values[0]
        end_price = end_row['收盘'].values[0]

        # 计算涨跌幅
        period_change = ((end_price / start_price) - 1) * 100

        # 将结果存入缓存
        PERIOD_CHANGE_CACHE[cache_key] = period_change

        return period_change

    except Exception as e:
        print(
            f"计算股票 {stock_code} ({stock_name}) 在 {start_date_yyyymmdd} 至 {end_date_yyyymmdd} 的涨跌幅时出错: {e}")
        return None


def build_ladder_chart(start_date, end_date, output_file=OUTPUT_FILE, min_board_level=2,
                       max_tracking_days=MAX_TRACKING_DAYS_AFTER_BREAK, reentry_days=REENTRY_DAYS_THRESHOLD,
                       non_main_board_level=1, max_tracking_days_before=MAX_TRACKING_DAYS_BEFORE_ENTRY,
                       period_days=PERIOD_DAYS_CHANGE, show_period_change=SHOW_PERIOD_CHANGE, priority_reasons=None):
    """
    构建梯队形态的涨停复盘图
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        output_file: 输出文件路径
        min_board_level: 主板股票最小显著连板天数，默认为2
        max_tracking_days: 断板后跟踪的最大天数，默认取全局配置
        reentry_days: 断板后再次上榜的天数阈值，默认取全局配置
        non_main_board_level: 非主板股票最小显著连板天数，默认为1
        max_tracking_days_before: 入选前跟踪的最大天数，默认取全局配置
        period_days: 计算入选日与之前X个交易日的涨跌幅，默认取全局配置
        show_period_change: 是否显示周期涨跌幅列，默认取全局配置
        priority_reasons: 优先选择的原因列表，默认为None
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    print(f"开始构建梯队形态涨停复盘图 ({start_date} 至 {end_date})...")

    # 获取交易日列表
    trading_days = get_trading_days(start_date, end_date)
    if not trading_days:
        print("未获取到交易日列表")
        return

    # 格式化交易日列表（保存两种格式，便于与Excel中的日期匹配）
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

    # 加载连板数据
    lianban_df = load_lianban_data(start_date, end_date)
    if lianban_df.empty:
        print("未获取到有效的连板数据")
        return

    # 获取股票详细信息映射
    stock_details = lianban_df.attrs.get('stock_details', {})

    # 加载首板数据
    shouban_df = load_shouban_data(start_date, end_date)
    print(f"加载首板数据完成，共有{len(shouban_df)}只股票")

    # 调试输出连板数据
    print("\n检查连板数据：")
    for i, row in lianban_df.iterrows():
        if i < 10:  # 只打印前10行作为示例
            print(f"股票: {row['股票名称']} ({row['纯代码']})")
            for col in lianban_df.columns:
                if col not in ['纯代码', '股票名称', '股票代码', '概念'] and pd.notna(row[col]):
                    print(f"  {col}: {row[col]}")

    # 识别每只股票首次达到显著连板的日期，以及断板后再次达到的情况
    result_df = identify_first_significant_board(lianban_df, shouban_df, min_board_level, reentry_days,
                                                 non_main_board_level)
    if result_df.empty:
        print(f"未找到在{start_date}至{end_date}期间有符合条件的显著连板股票")
        return

    # 加载股票代码映射（用于获取涨跌幅数据）
    stock_mapping = load_stock_mapping()

    # 创建Excel工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = f"涨停梯队{start_date[:6]}"

    # 收集所有概念信息，用于生成颜色映射
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

    # 获取热门概念的颜色映射
    reason_colors, top_reasons = get_reason_colors(all_concepts, priority_reasons=priority_reasons)

    # 为每只股票确定主要概念组
    all_stocks = {}
    for stock_key, reasons in stock_concepts.items():
        all_stocks[stock_key] = {
            'name': stock_key.split('_')[1],
            'reasons': reasons,
            'appearances': [1]  # 简化处理，只需要一个非空列表
        }

    # 获取每只股票的主要概念组
    stock_reason_group = get_stock_reason_group(all_stocks, top_reasons)

    # 设置日期表头（第1行）
    ws.cell(row=1, column=1, value="股票代码")
    ws.cell(row=1, column=2, value="题材概念")
    ws.cell(row=1, column=3, value="股票简称")

    # 添加周期涨跌幅列（第4列）
    period_column = 4
    date_column_start = 4  # 日期列开始位置，默认为第4列

    if show_period_change:
        period_header = f"{period_days}日"
        ws.cell(row=1, column=period_column, value=period_header)
        ws.cell(row=1, column=period_column).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=period_column).border = BORDER_STYLE
        ws.cell(row=1, column=period_column).font = Font(bold=True, size=9)  # 设置小一号字体
        date_column_start = 5  # 如果显示周期涨跌幅，日期列从第5列开始

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

        ws.cell(row=1, column=col, value=date_with_weekday)

        # 设置日期单元格样式：居中、自动换行、边框、字体加粗
        date_cell = ws.cell(row=1, column=col)
        date_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        date_cell.border = BORDER_STYLE
        date_cell.font = Font(bold=True)

    # 设置前三列的格式
    for col in range(1, 4):
        ws.cell(row=1, column=col).alignment = Alignment(horizontal='center')
        ws.cell(row=1, column=col).border = BORDER_STYLE
        ws.cell(row=1, column=col).font = Font(bold=True)

    # 添加大盘指标行（创业指和成交量）
    add_market_indicators(ws, date_columns, label_col=2)

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

    print(f"共有{len(lianban_stock_codes)}只股票已入选连板梯队")

    # 填充数据行
    for i, (_, stock) in enumerate(result_df.iterrows()):
        row_idx = i + 4  # 行索引，从第4行开始（第1行是日期标题，第2-3行是大盘指标）

        stock_code = stock['stock_code']
        stock_name = stock['stock_name']
        all_board_data = stock['all_board_data']

        # 提取纯代码
        pure_stock_code = stock_code.split('_')[0] if '_' in stock_code else stock_code
        if pure_stock_code.startswith(('sh', 'sz', 'bj')):
            pure_stock_code = pure_stock_code[2:]

        # 设置股票代码列（第一列）- 新增
        # 使用Excel单元格格式设置为文本，而不是添加单引号前缀
        code_cell = ws.cell(row=row_idx, column=1, value=f'{pure_stock_code.split(".")[0]}')
        code_cell.alignment = Alignment(horizontal='center')
        code_cell.border = BORDER_STYLE
        code_cell.font = Font(size=8)  # 设置比正常小的字体
        code_cell.number_format = '@'  # 设置单元格格式为文本，保留前导零

        # 获取概念
        concept = stock.get('concept', '其他')
        if pd.isna(concept) or not concept:
            concept = "其他"

        # 设置概念列（第二列）
        concept_cell = ws.cell(row=row_idx, column=2, value=f"[{concept}]")
        concept_cell.alignment = Alignment(horizontal='left')
        concept_cell.border = BORDER_STYLE
        concept_cell.font = Font(size=9)  # 设置小一号字体

        # 根据股票所属概念组设置颜色
        stock_key = f"{stock_code}_{stock_name}"
        if stock_key in stock_reason_group:
            reason = stock_reason_group[stock_key]
            if reason in reason_colors:
                concept_cell.fill = PatternFill(start_color=reason_colors[reason], fill_type="solid")
                # 如果背景色较深，使用白色字体
                if reason_colors[reason] in ["FF5A5A", "FF8C42", "9966FF", "45B5FF"]:
                    concept_cell.font = Font(color="FFFFFF", size=9)  # 保持小一号字体

        # 计算股票的最高板数
        max_board_level = 0
        for day_data in all_board_data.values():
            if pd.notna(day_data) and day_data and day_data > max_board_level:
                max_board_level = int(day_data)

        # 根据股票代码确定市场类型
        market_type = get_market_marker(pure_stock_code)

        # 设置股票简称列（第三列），添加市场标记
        stock_display_name = f"{stock_name}{market_type}"
        name_cell = ws.cell(row=row_idx, column=3, value=stock_display_name)
        name_cell.alignment = Alignment(horizontal='left')
        name_cell.border = BORDER_STYLE

        # 为曾经到过4板及以上的个股，设置蓝色背景
        apply_high_board_color = False
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
        elif pure_stock_code in stock_entry_count and stock_entry_count[pure_stock_code] > 1:
            # 获取入选次数
            entry_count = stock_entry_count[pure_stock_code]
            # 确定颜色深度，超过4次使用最深的灰色
            color_level = min(entry_count, 4)
            bg_color = REENTRY_COLORS.get(color_level, REENTRY_COLORS[4])
            name_cell.fill = PatternFill(start_color=bg_color, fill_type="solid")

            # 对于深色灰色背景，使用白色字体
            if color_level >= 4:
                name_cell.font = Font(color="FFFFFF")

        # 填充周期涨跌幅列
        if show_period_change:
            try:
                # 获取入选日期
                entry_date = stock['first_significant_date']
                entry_date_str = entry_date.strftime('%Y%m%d')

                # 获取入选前X个交易日的日期
                prev_date = get_n_trading_days_before(entry_date_str, period_days)
                if '-' in prev_date:
                    prev_date = prev_date.replace('-', '')

                # 计算从入选前X日到入选日的涨跌幅
                period_change = calculate_stock_period_change(stock_code, prev_date, entry_date_str, stock_name)

                if period_change is not None:
                    period_cell = ws.cell(row=row_idx, column=period_column, value=f"{period_change:.2f}%")
                    # 设置背景色 - 根据涨跌幅
                    color = get_color_for_period_change(period_change)
                    if color:
                        period_cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                else:
                    period_cell = ws.cell(row=row_idx, column=period_column, value="--")
            except Exception as e:
                print(f"计算周期涨跌幅时出错: {e}, 股票: {stock_name}")
                period_cell = ws.cell(row=row_idx, column=period_column, value="--")

            # 设置周期涨跌幅单元格格式
            period_cell.alignment = Alignment(horizontal='center')
            period_cell.border = BORDER_STYLE
            period_cell.font = Font(size=9)  # 设置小一号字体

        # 填充每个交易日的数据
        for j, formatted_day in enumerate(formatted_trading_days):
            col_idx = j + date_column_start  # 列索引，从第4列开始

            # 获取当日的连板信息
            board_days = all_board_data.get(formatted_day)

            # 标记是否在首板数据中找到该股票
            found_in_shouban = False

            # 如果该日期没有连板数据，检查首板数据
            if not pd.notna(board_days) and shouban_df is not None and not shouban_df.empty:
                # 查找在首板数据中是否有该股票在该日期的记录
                shouban_row = shouban_df[(shouban_df['纯代码'] == pure_stock_code)]
                if not shouban_row.empty and formatted_day in shouban_row.columns and pd.notna(
                        shouban_row[formatted_day].values[0]):
                    # 该股票在该日期有首板记录
                    found_in_shouban = True

            cell = ws.cell(row=row_idx, column=col_idx)

            # 解析当前日期对象
            current_date_obj = datetime.strptime(formatted_day,
                                                 '%Y年%m月%d日') if '年' in formatted_day else datetime.strptime(
                formatted_day, '%Y/%m/%d')

            if pd.notna(board_days) and board_days:
                # 对于首板（board_days=1），显示为"首板"，否则显示为"N板"
                if board_days == 1:
                    # 获取市场标记
                    market_marker = get_market_marker(pure_stock_code)
                    board_text = f"首板{market_marker}"
                else:
                    board_text = f"{int(board_days)}板"

                cell.value = board_text
                # 设置连板颜色
                board_level = int(board_days)
                color = BOARD_COLORS.get(board_level, BOARD_COLORS[10] if board_level > 10 else BOARD_COLORS[1])
                cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                # 文字颜色设为白色以增强可读性
                cell.font = Font(color="FFFFFF", bold=True)

                # 添加备注信息（仅对连板股票）
                stock_detail_key = f"{pure_stock_code}_{formatted_day}"
                if stock_detail_key in stock_details:
                    details = stock_details[stock_detail_key]
                    comment_text = ""

                    # 构建备注文本
                    if '连板信息' in details:
                        comment_text += f"{details['连板信息']} "
                    if '首次涨停时间' in details:
                        comment_text += f"\n首次涨停: {details['首次涨停时间']} "
                    if '最终涨停时间' in details:
                        comment_text += f"\n最终涨停: {details['最终涨停时间']} "
                    if '涨停开板次数' in details:
                        comment_text += f"\n开板次数: {details['涨停开板次数']}"

                    if comment_text:
                        cell.comment = Comment(comment_text.strip(), "涨停信息")

                # 记录当前日期为最后一次连板的日期
                stock['last_board_date'] = current_date_obj
            elif found_in_shouban:
                # 获取市场标记
                market_marker = get_market_marker(pure_stock_code)
                # 显示为"首板"并使用特殊颜色
                cell.value = f"首板{market_marker}"
                cell.fill = PatternFill(start_color=BOARD_COLORS[1], fill_type="solid")
                # 文字颜色设为白色以增强可读性
                cell.font = Font(color="FFFFFF", bold=True)

                # 更新最后连板日期以便可以继续跟踪
                stock['last_board_date'] = current_date_obj
            else:
                # 检查当日日期是否在首次显著连板日期之后
                try:
                    if current_date_obj >= stock['first_significant_date']:
                        # 如果有最后连板日期记录，判断是否超过跟踪期限
                        last_board_date = stock.get('last_board_date')

                        if last_board_date and max_tracking_days is not None:
                            # 计算当前日期与最后连板日期的交易日天数差
                            # 使用交易日计算替代日历日计算
                            days_after_break = count_trading_days_between(last_board_date, current_date_obj)

                            # 如果断板后的交易日天数超过跟踪天数，不显示涨跌幅
                            if days_after_break > max_tracking_days:
                                # 单元格留空
                                continue

                        # 获取当日涨跌幅
                        day_in_yyyymmdd = date_mapping.get(formatted_day)
                        if day_in_yyyymmdd:
                            pct_change = get_stock_daily_pct_change(stock_code, day_in_yyyymmdd, stock_name)
                            if pct_change is not None:
                                cell.value = f"{pct_change:.2f}%"
                                # 设置背景色 - 根据涨跌幅
                                color = get_color_for_pct_change(pct_change)
                                if color:
                                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                            else:
                                cell.value = "停牌"
                    # 检查当日日期是否在首次显著连板日期之前，且在跟踪天数范围内
                    elif max_tracking_days_before > 0:
                        # 计算当前日期与首次显著连板日期的交易日天数差
                        days_before_entry = count_trading_days_between(current_date_obj,
                                                                       stock['first_significant_date'])

                        # 如果在入选前跟踪天数范围内，显示涨跌幅
                        if 1 <= days_before_entry <= max_tracking_days_before:
                            day_in_yyyymmdd = date_mapping.get(formatted_day)
                            if day_in_yyyymmdd:
                                pct_change = get_stock_daily_pct_change(stock_code, day_in_yyyymmdd, stock_name)
                                if pct_change is not None:
                                    cell.value = f"{pct_change:.2f}%"
                                    # 设置背景色 - 根据涨跌幅
                                    color = get_color_for_pct_change(pct_change)
                                    if color:
                                        cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                                else:
                                    cell.value = "停牌"
                except Exception as e:
                    print(f"处理日期时出错: {e}, 日期: {formatted_day}")

            # 设置单元格格式
            cell.alignment = Alignment(horizontal='center')
            cell.border = BORDER_STYLE

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

    # 冻结前三列和前三行
    ws.freeze_panes = ws.cell(row=4, column=date_column_start)

    # 创建统计原因的计数器
    reason_counter = Counter(all_concepts)

    # 创建图例工作表
    create_legend_sheet(wb, reason_counter, reason_colors, top_reasons, HIGH_BOARD_COLORS, REENTRY_COLORS)

    # 保存Excel文件
    try:
        output_dir = os.path.dirname(output_file)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        wb.save(output_file)
        print(f"梯队形态涨停复盘图已生成: {output_file}")
        return True
    except Exception as e:
        print(f"保存Excel文件时出错: {e}")
        return False


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

    args = parser.parse_args()

    # 验证日期格式
    if not (args.start_date.isdigit() and len(args.start_date) == 8):
        print("错误: 开始日期格式应为YYYYMMDD")
        exit(1)

    if not (args.end_date.isdigit() and len(args.end_date) == 8):
        print("错误: 结束日期格式应为YYYYMMDD")
        exit(1)

    # 处理max_tracking参数
    max_tracking = None if args.max_tracking == -1 else args.max_tracking
    
    # 处理优先原因列表
    priority_reasons = [reason.strip() for reason in args.priority_reasons.split(',')] if args.priority_reasons else None

    # 构建梯队图
    build_ladder_chart(args.start_date, args.end_date, args.output, args.min_board,
                       max_tracking, args.reentry_days, args.non_main_board,
                       args.max_tracking_before, args.period_days, args.show_period_change,
                       priority_reasons=priority_reasons)
