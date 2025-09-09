import re
from datetime import datetime

import pandas as pd

# 输入和输出文件路径
FUPAN_FILE = "./excel/fupan_stocks.xlsx"
OUTPUT_FILE = "./excel/ladder_analysis.xlsx"


def debug_print_lianban_data(lianban_df):
    """
    调试输出连板数据

    Args:
        lianban_df: 连板数据DataFrame
    """
    print("\n检查连板数据：")
    for i, row in lianban_df.iterrows():
        if i < 10:  # 只打印前10行作为示例
            print(f"股票: {row['股票名称']} ({row['纯代码']})")
            for col in lianban_df.columns:
                if col not in ['纯代码', '股票名称', '股票代码', '概念'] and pd.notna(row[col]):
                    print(f"  {col}: {row[col]}")


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


def load_zaban_data(start_date, end_date):
    """
    从Excel中加载炸板数据
    
    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        
    Returns:
        pandas.DataFrame: 处理后的炸板数据
    """
    try:
        # 读取炸板数据sheet
        try:
            df = pd.read_excel(FUPAN_FILE, sheet_name="炸板数据")
            print(f"成功读取炸板数据sheet，共有{len(df)}行，{len(df.columns)}列")
        except Exception as e:
            print(f"读取炸板数据sheet失败: {e}")
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
            print("炸板数据中未找到有效的日期列")
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
            print(f"炸板数据中未找到日期范围 {start_date} 至 {end_date} 内的数据")
            return pd.DataFrame()

        # 提取炸板股票信息
        zaban_stocks = []

        for date_col in filtered_date_columns:
            date_obj = datetime.strptime(date_col, '%Y年%m月%d日') if '年' in date_col else pd.to_datetime(date_col)
            date_str = date_obj.strftime('%Y%m%d')

            # 遍历该日期列中的每个单元格
            for _, cell_value in df[date_col].items():
                if pd.isna(cell_value):
                    continue

                # 解析单元格内容，格式通常是股票代码和股票简称
                cell_text = str(cell_value)
                parts = cell_text.split(';')

                if len(parts) < 2:
                    continue

                # 提取股票代码和股票简称
                stock_code = parts[0].strip()
                stock_name = parts[1].strip()

                # 记录炸板股票
                zaban_stocks.append({
                    'date': date_str,
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'formatted_date': date_col
                })

        # 转换为DataFrame
        result_df = pd.DataFrame(zaban_stocks)

        if not result_df.empty:
            print(f"成功加载炸板数据，共有{len(result_df)}条记录")
        else:
            print("未找到炸板数据记录")

        return result_df

    except Exception as e:
        print(f"加载炸板数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def load_attention_data(start_date, end_date, is_main_board=True):
    """
    从Excel中加载关注度榜数据

    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        is_main_board: 是否为主板数据，默认为True

    Returns:
        pandas.DataFrame: 处理后的关注度榜数据
    """
    try:
        # 读取关注度榜sheet
        sheet_name = '关注度榜' if is_main_board else '非主关注度榜'
        try:
            df = pd.read_excel(FUPAN_FILE, sheet_name=sheet_name)
            print(f"成功读取{sheet_name}sheet，共有{len(df)}行，{len(df.columns)}")
        except Exception as e:
            print(f"读取{sheet_name}sheet失败: {e}")
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
            print(f"{sheet_name}中未找到有效的日期列")
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
            if date_str >= start_date and (end_date is None or date_str <= end_date):
                filtered_date_columns.append(col)

        if not filtered_date_columns:
            print(f"{sheet_name}中未找到{start_date}到{end_date}范围内的数据")
            return pd.DataFrame()

        # 打印第一个日期列的前几条数据，帮助了解数据格式
        if filtered_date_columns:
            first_date_col = filtered_date_columns[0]
            print(f"\n{sheet_name}中{first_date_col}列的前5条数据:")
            for i, (idx, value) in enumerate(df[first_date_col].items()):
                if i >= 5:
                    break
                if pd.notna(value):
                    print(f"  {idx}: {value}")
                    # 打印分割后的每个部分
                    parts = str(value).split(';')
                    print(f"    分割后的部分({len(parts)}个): {parts}")

        # 创建一个新的DataFrame来存储处理后的数据
        processed_data = []

        # 遍历每个日期列，提取股票信息
        for date_col in filtered_date_columns:
            date_obj = datetime.strptime(date_col, '%Y年%m月%d日') if '年' in date_col else pd.to_datetime(date_col)
            date_str = date_obj.strftime('%Y%m%d')

            # 遍历该日期列中的每个单元格
            for idx, cell_value in df[date_col].items():
                if pd.isna(cell_value):
                    continue

                # 解析单元格内容，格式是通过分号连接的字符串
                cell_text = str(cell_value)
                parts = cell_text.split(';')

                # 确保至少有6个元素（股票代码、股票名称、最新价、最新涨跌幅、个股热度、个股热度排名）
                if len(parts) >= 6:
                    stock_code = parts[0].strip()
                    stock_name = parts[1].strip()

                    # 尝试提取热度排名（第6个元素）
                    try:
                        # 热度排名可能包含数字和其他字符，需要提取数字部分
                        rank_str = parts[5].strip()
                        # 提取数字部分
                        rank_match = re.search(r'\d+', rank_str)
                        if rank_match:
                            rank = int(rank_match.group())
                        else:
                            continue  # 如果无法提取数字，跳过此条记录
                    except (IndexError, ValueError):
                        continue  # 如果提取失败，跳过此条记录

                    processed_data.append({
                        '股票代码': stock_code,
                        '股票名称': stock_name,
                        '日期': date_col,
                        '热度排名': rank
                    })

        # 转换为DataFrame
        result_df = pd.DataFrame(processed_data)

        if result_df.empty:
            print(f"未能从{sheet_name}中提取有效的数据")
            return pd.DataFrame()

        print(f"处理后的{sheet_name}数据: {len(result_df)}行")
        return result_df

    except Exception as e:
        print(f"加载{sheet_name}数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def load_momo_shangzhang_data(start_date, end_date):
    """
    从Excel中加载【默默上涨】数据

    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)

    Returns:
        pandas.DataFrame: 处理后的【默默上涨】数据
    """
    try:
        # 导入【默默上涨】处理模块
        from analysis.momo_shangzhang_processor import load_momo_shangzhang_data as load_momo_data
        return load_momo_data(start_date, end_date)
    except Exception as e:
        print(f"加载【默默上涨】数据时出错: {e}")
        return pd.DataFrame()


def load_stock_data(start_date, end_date, enable_attention_criteria, enable_momo_shangzhang=False):
    """
    加载股票数据

    Args:
        start_date: 开始日期
        end_date: 结束日期
        enable_attention_criteria: 是否启用关注度榜入选条件
        enable_momo_shangzhang: 是否启用【默默上涨】数据

    Returns:
        tuple: (连板数据, 首板数据, 关注度数据, 炸板数据, 默默上涨数据)
    """
    # 加载连板数据
    lianban_df = load_lianban_data(start_date, end_date)

    # 加载首板数据
    shouban_df = load_shouban_data(start_date, end_date)
    print(f"加载首板数据完成，共有{len(shouban_df)}只股票")

    # 加载炸板数据
    zaban_df = load_zaban_data(start_date, end_date)
    print(f"加载炸板数据完成，共有{len(zaban_df)}条记录")

    # 如果启用关注度榜入选条件，加载关注度榜数据
    attention_data = {'main': None, 'non_main': None}
    if enable_attention_criteria:
        print("启用关注度榜入选条件，加载关注度榜数据...")
        attention_data['main'] = load_attention_data(start_date, end_date, is_main_board=True)
        attention_data['non_main'] = load_attention_data(start_date, end_date, is_main_board=False)

        if attention_data['main'].empty and attention_data['non_main'].empty:
            print("警告：未能加载任何关注度榜数据，关注度榜入选条件将不生效")
        else:
            print(
                f"成功加载关注度榜数据：主板 {len(attention_data['main'])}条，非主板 {len(attention_data['non_main'])}条")

    # 如果启用【默默上涨】，加载【默默上涨】数据
    momo_df = pd.DataFrame()
    if enable_momo_shangzhang:
        print("启用【默默上涨】数据，加载【默默上涨】数据...")
        momo_df = load_momo_shangzhang_data(start_date, end_date)
        print(f"加载【默默上涨】数据完成，共有{len(momo_df)}只股票")

    # 调试输出连板数据
    debug_print_lianban_data(lianban_df)

    return lianban_df, shouban_df, attention_data, zaban_df, momo_df
