"""
题材概念分析模块

用于分析涨停梯队数据中的题材概念，统计概念出现频次和识别新概念
"""

from collections import defaultdict

import pandas as pd

from utils.theme_color_util import extract_reasons

# 配置参数
TOP_CONCEPTS_COUNT = 30  # 展示前N个热门原因
NEW_CONCEPT_DAYS = 5  # 新原因的天数阈值（最近N天才出现的原因）
NEW_REASON_MIN_COUNT = 2  # 新原因的最小出现次数阈值
ENABLE_REASON_ANALYSIS = True  # 是否启用原因分析功能


def extract_concepts_from_reason_text(reason_text):
    """
    从涨停原因类别文本中提取概念列表
    
    Args:
        reason_text: 涨停原因类别文本，如"[甲骨文+阿里云+智能运维]"
        
    Returns:
        list: 概念列表
    """
    if not reason_text or pd.isna(reason_text):
        return []

    # 转换为字符串并去除空格
    reason_text = str(reason_text).strip()

    # 去除方括号
    reason_text = reason_text.strip('[]')

    # 如果为空，返回空列表
    if not reason_text:
        return []

    # 使用extract_reasons函数处理，它会按+分割并标准化
    concepts = extract_reasons(reason_text)

    return concepts


def analyze_concept_data(stock_data_dict, trading_days):
    """
    分析股票数据中的涨停原因信息（细粒度分析）

    Args:
        stock_data_dict: 股票数据字典，key为日期，value为当日股票数据
        trading_days: 交易日列表，按时间排序

    Returns:
        tuple: (reason_stats, new_reasons)
            - reason_stats: 原因统计信息 {reason: {'count': int, 'first_date': str, 'last_date': str, 'stocks': list}}
            - new_reasons: 新原因信息 {reason: {'first_date': str, 'count': int, 'stocks': list}}
    """
    reason_stats = defaultdict(lambda: {
        'count': 0,
        'first_date': None,
        'last_date': None,
        'stocks': set()
    })

    # 按日期顺序处理数据
    for date in sorted(trading_days):
        if date not in stock_data_dict:
            continue

        daily_data = stock_data_dict[date]

        # 处理当日的每只股票
        for _, stock_row in daily_data.iterrows():
            reason = stock_row.get('涨停原因', '')  # 获取单个原因
            stock_name = stock_row.get('股票简称', '')

            # 直接使用单个原因（已经在数据准备阶段分割过了）
            if not reason or pd.isna(reason) or not reason.strip():
                continue

            # 更新统计信息
            reason_stats[reason]['count'] += 1
            reason_stats[reason]['stocks'].add(stock_name)

            # 更新首次和最后出现日期
            if reason_stats[reason]['first_date'] is None:
                reason_stats[reason]['first_date'] = date
            reason_stats[reason]['last_date'] = date

    # 转换stocks set为list
    for reason in reason_stats:
        reason_stats[reason]['stocks'] = list(reason_stats[reason]['stocks'])

    # 识别新原因
    new_reasons = find_new_concepts(reason_stats, trading_days)

    return dict(reason_stats), new_reasons


def analyze_concept_data_with_history(stock_data_dict, analysis_date_columns, all_date_columns, lianban_df, shouban_df):
    """
    分析股票数据中的涨停原因信息，使用全部历史数据来准确识别新原因

    Args:
        stock_data_dict: 分析范围内的股票数据字典
        analysis_date_columns: 分析范围内的日期列表
        all_date_columns: 所有历史日期列表
        lianban_df: 连板数据DataFrame
        shouban_df: 首板数据DataFrame

    Returns:
        tuple: (reason_stats, new_reasons)
    """
    import pandas as pd

    # 首先从分析范围内的数据统计原因出现次数
    reason_stats = defaultdict(lambda: {
        'count': 0,
        'first_date': None,
        'last_date': None,
        'stocks': set()
    })

    # 统计分析范围内的原因出现次数
    for date in sorted(analysis_date_columns):
        if date not in stock_data_dict:
            continue

        daily_data = stock_data_dict[date]

        # 处理当日的每只股票
        for _, stock_row in daily_data.iterrows():
            reason = stock_row.get('涨停原因', '')
            stock_name = stock_row.get('股票简称', '')

            if not reason or pd.isna(reason) or not reason.strip():
                continue

            # 更新统计信息
            reason_stats[reason]['count'] += 1
            reason_stats[reason]['stocks'].add(stock_name)

            # 更新在分析范围内的首次和最后出现日期
            if reason_stats[reason]['first_date'] is None:
                reason_stats[reason]['first_date'] = date
            reason_stats[reason]['last_date'] = date

    # 转换stocks set为list
    for reason in reason_stats:
        reason_stats[reason]['stocks'] = list(reason_stats[reason]['stocks'])

    # 现在从全部历史数据中查找每个原因的真实首次出现日期
    reason_first_date_in_history = {}

    # 处理连板数据的所有历史日期
    for _, row in lianban_df.iterrows():
        for date_col in all_date_columns:
            cell_value = row.get(date_col)
            if pd.notna(cell_value) and cell_value:
                parts = str(cell_value).split(';')
                if len(parts) >= 10:
                    concept = parts[-1].strip()
                    if concept and concept != 'nan':
                        reasons = [reason.strip() for reason in concept.split('+') if reason.strip()]
                        for reason in reasons:
                            # 记录所有原因的历史首次出现日期（不仅限于分析范围内的原因）
                            if reason not in reason_first_date_in_history:
                                reason_first_date_in_history[reason] = date_col
                            else:
                                # 如果已经记录过，检查是否更早
                                current_first = reason_first_date_in_history[reason]
                                if all_date_columns.index(date_col) < all_date_columns.index(current_first):
                                    reason_first_date_in_history[reason] = date_col

    # 处理首板数据的所有历史日期
    for _, row in shouban_df.iterrows():
        for date_col in all_date_columns:
            cell_value = row.get(date_col)
            if pd.notna(cell_value) and cell_value:
                parts = str(cell_value).split(';')
                if len(parts) >= 10:
                    concept = parts[-1].strip()
                    if concept and concept != 'nan':
                        reasons = [reason.strip() for reason in concept.split('+') if reason.strip()]
                        for reason in reasons:
                            # 记录所有原因的历史首次出现日期
                            if reason not in reason_first_date_in_history:
                                reason_first_date_in_history[reason] = date_col
                            else:
                                # 如果已经记录过，检查是否更早
                                current_first = reason_first_date_in_history[reason]
                                if all_date_columns.index(date_col) < all_date_columns.index(current_first):
                                    reason_first_date_in_history[reason] = date_col

    # 为分析范围内的原因添加历史首次出现日期
    for reason in reason_stats:
        if reason in reason_first_date_in_history:
            reason_stats[reason]['historical_first_date'] = reason_first_date_in_history[reason]
        else:
            # 如果在历史中没找到，使用分析范围内的首次出现日期
            reason_stats[reason]['historical_first_date'] = reason_stats[reason]['first_date']

    # 使用历史首次出现日期来识别新原因
    new_reasons = find_new_concepts_with_history(reason_stats, reason_first_date_in_history, all_date_columns)

    return dict(reason_stats), new_reasons


def find_new_concepts_with_history(reason_stats, reason_first_date_in_history, all_date_columns):
    """
    基于历史首次出现日期识别新原因

    Args:
        reason_stats: 原因统计信息
        reason_first_date_in_history: 原因在历史中的首次出现日期
        all_date_columns: 所有历史日期列表

    Returns:
        dict: 新原因信息
    """
    if len(all_date_columns) < NEW_CONCEPT_DAYS:
        return {}

    # 获取最近N个交易日
    recent_days = all_date_columns[-NEW_CONCEPT_DAYS:]

    new_reasons = {}

    for reason, stats in reason_stats.items():
        # 应用最小出现次数阈值
        if stats['count'] < NEW_REASON_MIN_COUNT:
            continue

        # 获取该原因在历史中的真实首次出现日期
        historical_first_date = reason_first_date_in_history.get(reason)

        # 如果原因在历史中的首次出现在最近N天内，则认为是新原因
        if historical_first_date and historical_first_date in recent_days:
            new_reasons[reason] = {
                'first_date': historical_first_date,
                'count': stats['count'],
                'stocks': stats['stocks']
            }

    return new_reasons


def find_new_concepts(concept_stats, trading_days):
    """
    识别新概念（最近N天才出现的概念）

    Args:
        concept_stats: 概念统计信息
        trading_days: 交易日列表或日期列列表

    Returns:
        dict: 新概念信息
    """
    # 如果trading_days是列表，直接使用；如果是其他类型，转换为列表
    if isinstance(trading_days, list):
        days_list = trading_days
    else:
        # 如果是日期列列表，转换为日期字符串列表
        days_list = [day.replace('年', '-').replace('月', '-').replace('日', '') for day in trading_days]

    if len(days_list) < NEW_CONCEPT_DAYS:
        return {}

    # 获取最近N个交易日
    recent_days = days_list[-NEW_CONCEPT_DAYS:]

    new_concepts = {}

    for concept, stats in concept_stats.items():
        first_date = stats['first_date']

        # 如果概念首次出现在最近N天内，则认为是新概念
        if first_date and first_date in recent_days:
            new_concepts[concept] = {
                'first_date': first_date,
                'count': stats['count'],
                'stocks': stats['stocks']
            }

    return new_concepts


def get_top_concepts(concept_stats, top_n=TOP_CONCEPTS_COUNT):
    """
    获取出现频次最高的前N个概念
    
    Args:
        concept_stats: 概念统计信息
        top_n: 返回的概念数量
        
    Returns:
        list: 按出现次数排序的概念列表 [(concept, stats), ...]
    """
    # 按出现次数排序
    sorted_concepts = sorted(
        concept_stats.items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )

    return sorted_concepts[:top_n]


def analyze_concepts_from_ladder_data(ladder_data, date_columns, start_date=None, end_date=None):
    """
    从原始fupan_stocks.xlsx文件中分析热门原因（细粒度分析）

    Args:
        ladder_data: 涨停梯队DataFrame数据（用于获取日期范围）
        date_columns: 日期列列表（分析范围内的日期）
        start_date: 分析开始日期 (YYYYMMDD格式)，None表示不限制
        end_date: 分析结束日期 (YYYYMMDD格式)，None表示不限制

    Returns:
        tuple: (top_reasons, new_reasons) - 热门原因和新原因
    """
    import pandas as pd
    import os

    # 读取原始Excel文件
    excel_file = './excel/fupan_stocks.xlsx'
    if not os.path.exists(excel_file):
        print(f"警告: 找不到文件 {excel_file}")
        return {}, {}

    try:
        # 读取连板数据和首板数据
        lianban_df = pd.read_excel(excel_file, sheet_name='连板数据')
        shouban_df = pd.read_excel(excel_file, sheet_name='首板数据')

        print(f"成功读取原始数据: 连板数据{lianban_df.shape}, 首板数据{shouban_df.shape}")

        # 获取所有历史日期列（用于准确识别新原因）
        all_date_columns = [col for col in lianban_df.columns if
                            col != 'Unnamed: 0' and '年' in col and '月' in col and '日' in col]
        all_date_columns = sorted(all_date_columns)

        # 如果指定了日期范围，则过滤历史日期列
        if start_date or end_date:
            filtered_all_date_columns = []
            for date_col in all_date_columns:
                # 将日期列名转换为YYYYMMDD格式进行比较
                try:
                    # 从"2025年09月05日"格式提取日期
                    import re
                    match = re.search(r'(\d{4})年(\d{2})月(\d{2})日', date_col)
                    if match:
                        year, month, day = match.groups()
                        date_str = f"{year}{month}{day}"

                        # 检查是否在指定范围内
                        if start_date and date_str < start_date:
                            continue
                        if end_date and date_str > end_date:
                            continue

                        filtered_all_date_columns.append(date_col)
                except:
                    # 如果解析失败，保留该日期列
                    filtered_all_date_columns.append(date_col)

            all_date_columns = filtered_all_date_columns
            print(f"应用日期范围过滤 ({start_date} 到 {end_date})，历史日期列: {len(all_date_columns)}个")
        else:
            print(f"找到历史日期列: {len(all_date_columns)}个，范围: {all_date_columns[0]} 到 {all_date_columns[-1]}")

        if not all_date_columns:
            print("警告: 没有找到符合日期范围的历史数据")
            return [], {}

        # 构建股票数据字典（使用分析范围内的日期）
        stock_data_dict = {}

        # 如果指定了日期范围，需要过滤日期列
        if start_date or end_date:
            # 从所有日期列中过滤出符合范围的日期列
            filtered_date_columns = []
            for date_col in all_date_columns:
                # 将日期列名转换为YYYYMMDD格式进行比较
                try:
                    # 从"2025年09月05日"格式提取日期
                    import re
                    match = re.search(r'(\d{4})年(\d{2})月(\d{2})日', date_col)
                    if match:
                        year, month, day = match.groups()
                        date_str = f"{year}{month}{day}"

                        # 检查是否在指定范围内
                        if start_date and date_str < start_date:
                            continue
                        if end_date and date_str > end_date:
                            continue

                        filtered_date_columns.append(date_col)
                except:
                    # 如果解析失败，保留该日期列
                    filtered_date_columns.append(date_col)

            # 使用过滤后的日期列作为分析范围
            analysis_date_columns = filtered_date_columns
            print(f"应用日期范围过滤，分析日期列: {len(analysis_date_columns)}个")
        else:
            # 如果没有指定日期范围，使用传入的date_columns
            analysis_date_columns = date_columns
            print(f"使用传入的日期列: {len(analysis_date_columns)}个")

        # 初始化分析范围内日期的股票列表
        for date_col in analysis_date_columns:
            stock_data_dict[date_col] = []

        # 处理连板数据（使用分析范围内的日期）
        for _, row in lianban_df.iterrows():
            # 检查每个分析范围内的日期列
            for date_col in analysis_date_columns:
                cell_value = row.get(date_col)

                # 如果该日期有数据
                if pd.notna(cell_value) and cell_value:
                    # 解析单元格数据格式: "股票代码; 股票简称; ...; 涨停原因类别"
                    parts = str(cell_value).split(';')
                    if len(parts) >= 10:  # 确保有足够的字段
                        stock_code = parts[0].strip()
                        stock_name = parts[1].strip()
                        concept = parts[-1].strip()  # 最后一个字段是涨停原因类别

                        # 如果有涨停原因信息
                        if concept and concept != 'nan':
                            # 将涨停原因按'+'分割成独立的原因
                            reasons = [reason.strip() for reason in concept.split('+') if reason.strip()]

                            # 为每个原因创建记录
                            for reason in reasons:
                                stock_info = {
                                    '股票代码': stock_code,
                                    '股票简称': stock_name,
                                    '涨停原因': reason,  # 单个原因
                                    '原始涨停原因类别': concept,  # 保留原始完整信息
                                }
                                stock_data_dict[date_col].append(stock_info)

        # 处理首板数据（使用分析范围内的日期）
        for _, row in shouban_df.iterrows():
            # 检查每个分析范围内的日期列
            for date_col in analysis_date_columns:
                cell_value = row.get(date_col)

                # 如果该日期有数据
                if pd.notna(cell_value) and cell_value:
                    # 解析单元格数据格式: "股票代码; 股票简称; ...; 涨停原因类别"
                    parts = str(cell_value).split(';')
                    if len(parts) >= 10:  # 确保有足够的字段
                        stock_code = parts[0].strip()
                        stock_name = parts[1].strip()
                        concept = parts[-1].strip()  # 最后一个字段是涨停原因类别

                        # 如果有涨停原因信息
                        if concept and concept != 'nan':
                            # 将涨停原因按'+'分割成独立的原因
                            reasons = [reason.strip() for reason in concept.split('+') if reason.strip()]

                            # 为每个原因创建记录
                            for reason in reasons:
                                stock_info = {
                                    '股票代码': stock_code,
                                    '股票简称': stock_name,
                                    '涨停原因': reason,  # 单个原因
                                    '原始涨停原因类别': concept,  # 保留原始完整信息
                                }
                                stock_data_dict[date_col].append(stock_info)

        # 转换为DataFrame格式，只保留有数据的日期，并去重
        filtered_stock_data_dict = {}

        for date_col in analysis_date_columns:  # 使用analysis_date_columns而不是date_columns
            if stock_data_dict[date_col]:  # 如果列表不为空
                df = pd.DataFrame(stock_data_dict[date_col])

                # 去重：同一只股票在同一天的同一个原因只保留一次
                # 基于股票代码、股票简称、涨停原因进行去重
                df = df.drop_duplicates(subset=['股票代码', '股票简称', '涨停原因'], keep='first')

                filtered_stock_data_dict[date_col] = df

        stock_data_dict = filtered_stock_data_dict

        print(f"原因数据处理完成，共处理{len(stock_data_dict)}个日期的数据")

        # 分析原因数据（需要从所有历史数据中分析原因的首次出现日期）
        reason_stats, new_reasons = analyze_concept_data_with_history(
            stock_data_dict, analysis_date_columns, all_date_columns, lianban_df, shouban_df)

        # 获取热门原因
        top_reasons = get_top_concepts(reason_stats)

        return top_reasons, new_reasons

    except Exception as e:
        print(f"概念分析过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        return {}, {}


def format_concept_analysis_summary(top_concepts, new_concepts):
    """
    格式化概念分析结果摘要
    
    Args:
        top_concepts: 热门概念列表
        new_concepts: 新概念字典
        
    Returns:
        str: 格式化的摘要文本
    """
    summary = []

    summary.append("=== 题材概念分析结果 ===")

    # 热门概念
    summary.append(f"\n热门概念 Top {len(top_concepts)}:")
    for i, (concept, stats) in enumerate(top_concepts, 1):
        summary.append(f"{i:2d}. {concept}: {stats['count']}次")

    # 新概念
    if new_concepts:
        summary.append(f"\n新概念 (最近{NEW_CONCEPT_DAYS}天出现):")
        # 排序：出现次数（倒序），首次出现（倒序）
        # 注意：first_date是字符串，需要用reverse=True来实现倒序
        sorted_new = sorted(new_concepts.items(), key=lambda x: (x[1]['count'], x[1]['first_date']), reverse=True)
        for concept, stats in sorted_new:
            summary.append(f"  - {concept}: {stats['count']}次 (首次: {stats['first_date']})")
    else:
        summary.append(f"\n新概念: 无 (最近{NEW_CONCEPT_DAYS}天)")

    return "\n".join(summary)
