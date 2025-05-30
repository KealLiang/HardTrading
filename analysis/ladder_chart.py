import os
import re
import pandas as pd
import numpy as np
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Alignment, Font, Border, Side
from openpyxl.utils import get_column_letter

from utils.date_util import get_trading_days, format_date
from analysis.whimsical import get_color_by_pct_change, normalize_reason

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

# 涨停板颜色映射（根据连板数）
BOARD_COLORS = {
    1: "FFB3B3",  # 首板 (淡红色)
    2: "FF9999",  # 2板 (红色)
    3: "FF8080",  # 3板 (深红色)
    4: "FF6666",  # 4板 (大红色)
    5: "FF4D4D",  # 5板 (深红色)
    6: "FF3333",  # 6板 (暗红色)
    7: "FF1A1A",  # 7板 (更暗红色)
    8: "FF0000",  # 8板 (非常暗红色)
    9: "E60000",  # 9板 (极暗红色)
    10: "CC0000", # 10板及以上 (近黑红色)
}

# 断板后跟踪的最大天数，超过这个天数后不再显示涨跌幅
# 设置为None表示一直跟踪到分析周期结束
MAX_TRACKING_DAYS_AFTER_BREAK = 5

# 涨跌幅颜色映射函数
def get_color_for_pct_change(pct_change):
    """
    根据涨跌幅返回颜色代码
    
    Args:
        pct_change: 涨跌幅百分比
        
    Returns:
        str: 16进制颜色代码
    """
    if pct_change is None:
        return "CCCCCC"  # 浅灰色，表示数据缺失
        
    # 将涨跌幅转换为浮点数
    try:
        pct = float(pct_change)
    except:
        return "CCCCCC"  # 无法转换时返回浅灰色
    
    # 涨跌停板情况
    if pct >= 9.5:
        return "FF0000"  # 涨停 - 大红色
    if pct <= -9.5:
        return "00CC00"  # 跌停 - 深绿色
    
    # 普通涨跌幅
    if pct > 0:
        # 上涨 - 红色系
        intensity = min(255, int(200 * pct / 10) + 55)  # 根据涨幅计算红色强度
        red = hex(intensity)[2:].zfill(2).upper()
        return f"FF{red}{red}"
    elif pct < 0:
        # 下跌 - 绿色系
        intensity = min(255, int(200 * abs(pct) / 10) + 55)  # 根据跌幅计算绿色强度
        green = hex(intensity)[2:].zfill(2).upper()
        return f"{green}FF{green}"
    else:
        # 平盘 - 浅灰色
        return "E6E6E6"


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
            
        # 处理股票代码格式
        # 移除可能的市场后缀（如.SH、.SZ等）
        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
        
        # 处理股票名称中的特殊字符
        if stock_name:
            safe_name = stock_name.replace('*ST', 'xST').replace('/', '_')
            file_name = f"{clean_code}_{safe_name}.csv"
        else:
            # 如果未提供名称，尝试查找匹配的文件
            file_found = False
            for file in os.listdir(save_path):
                if file.startswith(f"{clean_code}_"):
                    file_name = file
                    file_found = True
                    break
            if not file_found:
                # print(f"未找到股票代码 {stock_code} 的数据文件")
                return None
        
        # 构建文件路径
        file_path = os.path.join(save_path, file_name)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            # print(f"数据文件不存在: {file_path}")
            return None
        
        # 读取CSV文件
        df = pd.read_csv(file_path, header=None,
                         names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                               '振幅', '涨跌幅', '涨跌额', '换手率'])
        
        # 格式化目标日期为 YYYY-MM-DD 格式
        target_date = f"{date_str_yyyymmdd[:4]}-{date_str_yyyymmdd[4:6]}-{date_str_yyyymmdd[6:8]}"
        
        # 查找目标日期的数据
        target_row = df[df['日期'] == target_date]
        
        # 如果找到数据，返回涨跌幅
        if not target_row.empty:
            return target_row['涨跌幅'].values[0]
        else:
            # 如果没有找到数据，可能是停牌
            # print(f"未找到股票 {stock_code} 在 {target_date} 的数据，可能停牌")
            return None
        
    except Exception as e:
        # print(f"获取股票 {stock_code} 的涨跌幅时出错: {e}")
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
                    
                stock_code = parts[0].strip()
                stock_name = parts[1].strip()
                
                # 查找板块信息
                board_info = None
                concept = "其他"
                
                for i, part in enumerate(parts):
                    part = part.strip()
                    if '天' in part and '板' in part:
                        board_info = part
                    # 通常最后一个部分是概念信息，以+分隔
                    if i == len(parts) - 1:
                        concept = part
                
                # 如果找到连板信息
                if board_info:
                    board_days, _ = extract_board_info(board_info)
                    
                    if board_days:
                        processed_data.append({
                            '股票代码': f"{stock_code}_{stock_name}",
                            '纯代码': stock_code,
                            '股票名称': stock_name,
                            '日期': date_col,
                            '连板天数': board_days,
                            '连板信息': board_info,
                            '概念': concept
                        })
        
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
        
        # 添加一个概念列
        concept_mapping = result_df.groupby('纯代码')['概念'].first().to_dict()
        pivot_df['概念'] = pivot_df['纯代码'].map(concept_mapping)
        
        # 添加标准格式的股票代码列
        pivot_df['股票代码'] = pivot_df['纯代码'] + '_' + pivot_df['股票名称']
        
        return pivot_df
    
    except Exception as e:
        print(f"加载连板数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def identify_first_significant_board(df, min_board_level=2):
    """
    识别每只股票首次达到显著连板（例如2板或以上）的日期
    
    Args:
        df: 连板数据DataFrame，已透视处理，每行一只股票，每列一个日期
        min_board_level: 最小显著连板天数，默认为2
        
    Returns:
        pandas.DataFrame: 添加了首次显著连板信息的DataFrame
    """
    # 创建结果DataFrame，包含股票代码、名称、首次显著连板日期和当日连板天数
    result = []
    
    print(f"开始分析连板数据，共有{len(df)}只股票")
    print(f"数据结构: \n{df.head(2)}")
    
    # 找出日期列
    date_columns = [col for col in df.columns if col not in ['纯代码', '股票名称', '股票代码', '概念']]
    
    if not date_columns:
        print("无法找到日期列")
        return pd.DataFrame()
        
    # 将日期列按时间排序
    date_columns.sort()
    
    # 遍历每行（每只股票）
    for idx, row in df.iterrows():
        stock_code = row['纯代码']
        stock_name = row['股票名称']
        
        # 跳过代码或名称为空的行
        if not stock_code or not stock_name:
            continue
            
        print(f"\n分析股票: {stock_code}_{stock_name}")
        
        # 检查每一个日期列
        first_significant_date = None
        board_level_at_first = None
        
        for col in date_columns:
            board_days = row[col]
            
            if pd.notna(board_days):  # 只处理非空单元格
                print(f"  日期 {col}: {board_days}")
                
                # 如果连板天数大于等于最小显著连板天数
                if board_days and board_days >= min_board_level:
                    print(f"    找到显著连板: {board_days}板")
                    # 记录首次达到显著连板的日期和当日连板天数
                    if not first_significant_date:
                        first_significant_date = col
                        board_level_at_first = board_days
                        
                        # 构建一个板块数据字典
                        all_board_data = {}
                        for date_col in date_columns:
                            all_board_data[date_col] = row[date_col]
                        
                        # 添加到结果列表
                        result.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'first_significant_date': first_significant_date,
                            'board_level_at_first': board_level_at_first,
                            'all_board_data': all_board_data,
                            'concept': row.get('概念', '其他')
                        })
                        
                        print(f"    记录首次显著连板: {stock_name} 在 {first_significant_date} 达到 {board_level_at_first}板")
                        
                        # 找到第一次显著连板后，可以结束此股票的循环
                        break
    
    # 转换为DataFrame
    result_df = pd.DataFrame(result)
    
    # 如果没有符合条件的数据，返回空DataFrame
    if result_df.empty:
        print("未找到符合条件的连板数据")
        return result_df
    
    print(f"找到{len(result_df)}只达到显著连板的股票")
        
    # 转换日期格式
    try:
        # 将日期列名转换为datetime对象
        result_df['first_significant_date'] = result_df['first_significant_date'].apply(
            lambda x: datetime.strptime(x, '%Y年%m月%d日') if '年' in x else pd.to_datetime(x)
        )
    except Exception as e:
        print(f"日期转换出错: {e}")
        print("日期示例:", result_df['first_significant_date'].iloc[0] if not result_df.empty else "无数据")
    
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
        # 使用normalize_reason对概念进行规范化
        try:
            normalized_concept = normalize_reason(concept)
            return normalized_concept if not normalized_concept.startswith("未分类") else concept
        except:
            return concept
    
    # 如果没有找到括号内的概念，返回默认值
    return "其他"


def build_ladder_chart(start_date, end_date, output_file=OUTPUT_FILE, min_board_level=2, max_tracking_days=MAX_TRACKING_DAYS_AFTER_BREAK):
    """
    构建梯队形态的涨停复盘图
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        output_file: 输出文件路径
        min_board_level: 最小显著连板天数，默认为2
        max_tracking_days: 断板后跟踪的最大天数，默认取全局配置
    """
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
    
    # 调试输出连板数据
    print("\n检查连板数据：")
    for i, row in lianban_df.iterrows():
        if i < 10:  # 只打印前10行作为示例
            print(f"股票: {row['股票名称']} ({row['纯代码']})")
            for col in lianban_df.columns:
                if col not in ['纯代码', '股票名称', '股票代码', '概念'] and pd.notna(row[col]):
                    print(f"  {col}: {row[col]}")
                    
    # 识别每只股票首次达到显著连板的日期
    result_df = identify_first_significant_board(lianban_df, min_board_level)
    if result_df.empty:
        print(f"未找到在{start_date}至{end_date}期间有连板{min_board_level}次及以上的股票")
        return
    
    # 加载股票代码映射（用于获取涨跌幅数据）
    stock_mapping = load_stock_mapping()
    
    # 创建Excel工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = f"涨停梯队{start_date[:6]}"
    
    # 设置日期表头（第1行）
    ws.cell(row=1, column=1, value="题材概念")
    ws.cell(row=1, column=2, value="股票简称")
    
    # 设置日期列标题
    for i, formatted_day in enumerate(formatted_trading_days):
        date_obj = datetime.strptime(formatted_day, '%Y年%m月%d日')
        col = i + 3  # 前两列是概念和股票名称
        
        # 添加日期标题和星期几
        weekday = date_obj.weekday()
        weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
        date_with_weekday = f"{date_obj.strftime('%Y-%m-%d')}\n{weekday_map[weekday]}"
        
        ws.cell(row=1, column=col, value=date_with_weekday)
        
        # 设置日期单元格样式：居中、自动换行、边框
        date_cell = ws.cell(row=1, column=col)
        date_cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        date_cell.border = BORDER_STYLE
    
    # 设置前两列的格式
    ws.cell(row=1, column=1).alignment = Alignment(horizontal='center')
    ws.cell(row=1, column=2).alignment = Alignment(horizontal='center')
    ws.cell(row=1, column=1).border = BORDER_STYLE
    ws.cell(row=1, column=2).border = BORDER_STYLE
    
    # 填充数据行
    for i, (_, stock) in enumerate(result_df.iterrows()):
        row_idx = i + 2  # 行索引，从第2行开始（第1行是日期标题）
        
        stock_code = stock['stock_code']
        stock_name = stock['stock_name']
        all_board_data = stock['all_board_data']
        
        # 获取概念
        concept = stock.get('concept', '其他')
        if pd.isna(concept) or not concept:
            concept = "其他"
        
        # 设置概念列（第一列）
        ws.cell(row=row_idx, column=1, value=f"[{concept}]")
        ws.cell(row=row_idx, column=1).alignment = Alignment(horizontal='left')
        ws.cell(row=row_idx, column=1).border = BORDER_STYLE
        
        # 设置股票简称列（第二列）
        ws.cell(row=row_idx, column=2, value=stock_name)
        ws.cell(row=row_idx, column=2).alignment = Alignment(horizontal='left')
        ws.cell(row=row_idx, column=2).border = BORDER_STYLE
        
        # 填充每个交易日的数据
        for j, formatted_day in enumerate(formatted_trading_days):
            col_idx = j + 3  # 列索引，从第3列开始
            
            # 获取当日的连板信息
            board_days = all_board_data.get(formatted_day)
            
            cell = ws.cell(row=row_idx, column=col_idx)
            
            # 解析当前日期对象
            current_date_obj = datetime.strptime(formatted_day, '%Y年%m月%d日') if '年' in formatted_day else datetime.strptime(formatted_day, '%Y/%m/%d')
            
            if pd.notna(board_days) and board_days:
                # 显示为"N板"
                board_text = f"{int(board_days)}板" 
                cell.value = board_text
                # 设置连板颜色
                board_level = int(board_days)
                color = BOARD_COLORS.get(board_level, BOARD_COLORS[10] if board_level > 10 else BOARD_COLORS[1])
                cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                # 文字颜色设为白色以增强可读性
                cell.font = Font(color="FFFFFF", bold=True)
                
                # 记录当前日期为最后一次连板的日期
                stock['last_board_date'] = current_date_obj
            else:
                # 检查当日日期是否在首次显著连板日期之后
                try:
                    if current_date_obj >= stock['first_significant_date']:
                        # 如果有最后连板日期记录，判断是否超过跟踪期限
                        last_board_date = stock.get('last_board_date')
                        
                        if last_board_date and max_tracking_days is not None:
                            # 计算当前日期与最后连板日期的天数差
                            days_after_break = (current_date_obj - last_board_date).days
                            
                            # 如果超过跟踪天数，不显示涨跌幅
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
                except Exception as e:
                    print(f"处理日期时出错: {e}, 日期: {formatted_day}")
            
            # 设置单元格格式
            cell.alignment = Alignment(horizontal='center')
            cell.border = BORDER_STYLE
    
    # 调整列宽
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 15
    for i in range(len(formatted_trading_days)):
        col_letter = get_column_letter(i + 3)
        ws.column_dimensions[col_letter].width = 12
    
    # 调整行高，确保日期和星期能完整显示
    ws.row_dimensions[1].height = 30
    
    # 冻结前两列和第一行
    ws.freeze_panes = 'C2'
    
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
                        help='最小显著连板天数 (默认: 2)')
    parser.add_argument('--max_tracking', type=int, default=MAX_TRACKING_DAYS_AFTER_BREAK,
                        help=f'断板后跟踪的最大天数 (默认: {MAX_TRACKING_DAYS_AFTER_BREAK}，设为-1表示一直跟踪)')
    
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
    
    # 构建梯队图
    build_ladder_chart(args.start_date, args.end_date, args.output, args.min_board, max_tracking) 