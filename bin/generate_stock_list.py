"""
股票列表生成工具

从已下载的股票数据中提取股票代码列表，保存为TXT或CSV文件
支持从复盘数据文件中提取热门股候选
"""

import os
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

import pandas as pd


def extract_stock_codes_from_data_dir(data_dir: str = './data/astocks') -> List[Tuple[str, str]]:
    """
    从数据目录提取股票代码和名称
    
    Args:
        data_dir: 股票数据目录
        
    Returns:
        [(股票代码, 股票名称), ...]
    """
    data_path = Path(data_dir)

    if not data_path.exists():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    stock_list = []

    # 遍历数据文件
    for filename in os.listdir(data_dir):
        if filename.endswith('.csv'):
            # 文件名格式：代码_名称.csv，如 "000001_平安银行.csv"
            parts = filename.rsplit('.csv', 1)[0].split('_', 1)
            if len(parts) == 2:
                code, name = parts
                stock_list.append((code, name))
            elif len(parts) == 1:
                # 只有代码没有名称
                code = parts[0]
                stock_list.append((code, ''))

    # 按代码排序
    stock_list.sort(key=lambda x: x[0])

    return stock_list


def save_stock_list_txt(stock_list: List[Tuple[str, str]], output_file: str):
    """
    保存为TXT格式（只保存代码）
    
    Args:
        stock_list: 股票列表
        output_file: 输出文件路径
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        for code, _ in stock_list:
            f.write(f"{code}\n")

    print(f"已保存 {len(stock_list)} 只股票代码到: {output_file}")


def save_stock_list_csv(stock_list: List[Tuple[str, str]], output_file: str):
    """
    保存为CSV格式（包含代码和名称）
    
    Args:
        stock_list: 股票列表
        output_file: 输出文件路径
    """
    df = pd.DataFrame(stock_list, columns=['股票代码', '股票名称'])
    df.to_csv(output_file, index=False, encoding='utf-8-sig')

    print(f"已保存 {len(stock_list)} 只股票（含名称）到: {output_file}")


def generate_all_stock_list(data_dir: str = './data/astocks',
                            output_dir: str = 'data/batch_backtest',
                            prefix: str = 'all_astocks'):
    """
    生成全部A股列表文件（同时生成TXT和CSV两种格式）
    
    Args:
        data_dir: 股票数据目录
        output_dir: 输出目录
        prefix: 文件名前缀
    """
    print(f"正在从 {data_dir} 提取股票列表...")

    # 提取股票列表
    stock_list = extract_stock_codes_from_data_dir(data_dir)

    if not stock_list:
        print("未找到任何股票数据文件！")
        return

    print(f"找到 {len(stock_list)} 只股票")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 保存为TXT格式
    txt_file = os.path.join(output_dir, f'{prefix}.txt')
    save_stock_list_txt(stock_list, txt_file)

    # 保存为CSV格式
    csv_file = os.path.join(output_dir, f'{prefix}.csv')
    save_stock_list_csv(stock_list, csv_file)

    print("\n生成完成！可以使用以下文件进行批量回测：")
    print(f"  - TXT格式: {txt_file}")
    print(f"  - CSV格式: {csv_file}")


def filter_by_market(stock_list: List[Tuple[str, str]], market: str) -> List[Tuple[str, str]]:
    """
    按市场筛选股票
    
    Args:
        stock_list: 股票列表
        market: 市场类型 ('sh'=沪市, 'sz'=深市, 'bj'=北交所)
        
    Returns:
        筛选后的股票列表
    """
    market_prefixes = {
        'sh': ['600', '601', '603', '605', '688'],  # 沪市：主板6开头，科创板688
        'sz': ['000', '001', '002', '003', '300'],  # 深市：主板0开头，创业板3开头
        'bj': ['430', '830'],  # 北交所
    }

    if market not in market_prefixes:
        raise ValueError(f"不支持的市场类型: {market}，可选: sh, sz, bj")

    prefixes = market_prefixes[market]
    return [(code, name) for code, name in stock_list
            if any(code.startswith(p) for p in prefixes)]


def generate_market_stock_lists(data_dir: str = './data/astocks', output_dir: str = 'data/batch_backtest'):
    """
    生成分市场的股票列表（沪市、深市、北交所）
    
    Args:
        data_dir: 股票数据目录
        output_dir: 输出目录
    """
    print(f"正在从 {data_dir} 提取股票列表...")

    # 提取全部股票
    all_stocks = extract_stock_codes_from_data_dir(data_dir)

    if not all_stocks:
        print("未找到任何股票数据文件！")
        return

    print(f"找到 {len(all_stocks)} 只股票\n")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 按市场分类
    markets = {
        'sh': '沪市',
        'sz': '深市',
        'bj': '北交所'
    }

    for market_code, market_name in markets.items():
        stocks = filter_by_market(all_stocks, market_code)

        if stocks:
            print(f"{market_name}: {len(stocks)} 只")

            # 保存TXT
            txt_file = os.path.join(output_dir, f'{market_code}_stocks.txt')
            save_stock_list_txt(stocks, txt_file)

            # 保存CSV
            csv_file = os.path.join(output_dir, f'{market_code}_stocks.csv')
            save_stock_list_csv(stocks, csv_file)

            print()


def generate_board_stock_lists(data_dir: str = './data/astocks', output_dir: str = 'data/batch_backtest'):
    """
    生成分板块的股票列表（主板、创业板、科创板、北交所）
    
    Args:
        data_dir: 股票数据目录
        output_dir: 输出目录
    """
    print(f"正在从 {data_dir} 提取股票列表...")

    # 提取全部股票
    all_stocks = extract_stock_codes_from_data_dir(data_dir)

    if not all_stocks:
        print("未找到任何股票数据文件！")
        return

    print(f"找到 {len(all_stocks)} 只股票\n")

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 按板块分类
    boards = {
        'main': ('主板', ['600', '601', '603', '605', '000', '001']),
        'chinext': ('创业板', ['300']),
        'star': ('科创板', ['688']),
        'bse': ('北交所', ['430', '830']),
    }

    for board_code, (board_name, prefixes) in boards.items():
        stocks = [(code, name) for code, name in all_stocks
                  if any(code.startswith(p) for p in prefixes)]

        if stocks:
            print(f"{board_name}: {len(stocks)} 只")

            # 保存TXT
            txt_file = os.path.join(output_dir, f'{board_code}_stocks.txt')
            save_stock_list_txt(stocks, txt_file)

            # 保存CSV
            csv_file = os.path.join(output_dir, f'{board_code}_stocks.csv')
            save_stock_list_csv(stocks, csv_file)

            print()


def extract_stocks_from_fupan(
    fupan_file: str = 'excel/fupan_stocks.xlsx',
    sheet_names: List[str] = None,
    start_date: str = None,
    end_date: str = None
) -> List[Tuple[str, str]]:
    """
    从复盘数据文件中提取股票代码
    
    Args:
        fupan_file: 复盘数据文件路径
        sheet_names: 要提取的sheet名称列表，如 ['连板数据', '首板数据']
                    None表示提取所有sheet
        start_date: 开始日期，格式'YYYYMMDD'，None表示从最早日期开始
        end_date: 结束日期，格式'YYYYMMDD'，None表示到最晚日期
        
    Returns:
        [(股票代码, 股票名称), ...]
    """
    if not os.path.exists(fupan_file):
        print(f"复盘文件不存在: {fupan_file}")
        return []
    
    # 转换日期格式 YYYYMMDD -> YYYY年MM月DD日
    def format_date(date_str):
        if date_str:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.strftime('%Y年%m月%d日')
        return None
    
    start_date_formatted = format_date(start_date) if start_date else None
    end_date_formatted = format_date(end_date) if end_date else None
    
    # 读取Excel文件
    excel_file = pd.ExcelFile(fupan_file)
    
    # 确定要处理的sheet
    if sheet_names is None:
        sheets_to_process = excel_file.sheet_names
    else:
        sheets_to_process = [s for s in sheet_names if s in excel_file.sheet_names]
        missing_sheets = [s for s in sheet_names if s not in excel_file.sheet_names]
        if missing_sheets:
            print(f"警告: 以下sheet不存在: {missing_sheets}")
    
    print(f"从 {fupan_file} 提取股票...")
    print(f"Sheet: {sheets_to_process}")
    print(f"日期范围: {start_date_formatted or '最早'} 至 {end_date_formatted or '最晚'}")
    
    # 用于存储所有股票代码和名称
    stock_dict = {}  # {代码: 名称}
    
    # 遍历每个sheet
    for sheet_name in sheets_to_process:
        print(f"\n处理 {sheet_name}...")
        
        try:
            df = pd.read_excel(fupan_file, sheet_name=sheet_name, index_col=0)
            
            if df.empty:
                print(f"  {sheet_name} 为空，跳过")
                continue
            
            # 筛选日期范围内的列
            selected_columns = []
            for col in df.columns:
                # 日期列格式：'YYYY年MM月DD日'
                if start_date_formatted and col < start_date_formatted:
                    continue
                if end_date_formatted and col > end_date_formatted:
                    continue
                selected_columns.append(col)
            
            if not selected_columns:
                print(f"  {sheet_name} 中没有符合日期范围的数据")
                continue
            
            print(f"  找到 {len(selected_columns)} 个日期列")
            
            # 从选中的列中提取股票代码
            for col in selected_columns:
                for cell_value in df[col].dropna():
                    if pd.isna(cell_value) or cell_value == '':
                        continue
                    
                    # 单元格内容格式：'股票代码; 股票名称; 其他字段...'
                    parts = str(cell_value).split(';')
                    if len(parts) >= 2:
                        code_raw = parts[0].strip()
                        name = parts[1].strip()
                        
                        # 处理股票代码：去掉市场后缀（如 .SH, .SZ）
                        # 格式可能是：605255.SH, 002195.SZ, 300308.SZ, 688261.SH
                        if '.' in code_raw:
                            code = code_raw.split('.')[0]
                        else:
                            code = code_raw
                        
                        # 验证股票代码格式（6位数字）
                        if code.isdigit() and len(code) == 6:
                            if code not in stock_dict:
                                stock_dict[code] = name
            
            print(f"  提取到 {len(stock_dict)} 只股票（累计去重后）")
        
        except Exception as e:
            print(f"  处理 {sheet_name} 时出错: {e}")
            continue
    
    # 转换为列表并排序
    stock_list = [(code, name) for code, name in stock_dict.items()]
    stock_list.sort(key=lambda x: x[0])
    
    print(f"\n总计提取到 {len(stock_list)} 只唯一股票")
    
    return stock_list


def generate_fupan_stock_list(
    fupan_file: str = 'excel/fupan_stocks.xlsx',
    sheet_names: List[str] = None,
    start_date: str = None,
    end_date: str = None,
    output_dir: str = 'data/batch_backtest',
    output_prefix: str = 'fupan_stocks'
):
    """
    从复盘数据文件提取股票并生成列表文件
    
    Args:
        fupan_file: 复盘数据文件路径
        sheet_names: 要提取的sheet名称列表
        start_date: 开始日期，格式'YYYYMMDD'
        end_date: 结束日期，格式'YYYYMMDD'
        output_dir: 输出目录
        output_prefix: 输出文件名前缀
    
    Examples:
        # 提取连板数据中的股票
        generate_fupan_stock_list(
            sheet_names=['连板数据'],
            start_date='20250101',
            end_date='20250131',
            output_prefix='lianban_202501'
        )
        
        # 提取多个类型的股票
        generate_fupan_stock_list(
            sheet_names=['连板数据', '首板数据', '大涨数据'],
            start_date='20250101',
            output_prefix='hot_stocks'
        )
    """
    # 提取股票列表
    stock_list = extract_stocks_from_fupan(fupan_file, sheet_names, start_date, end_date)
    
    if not stock_list:
        print("未提取到任何股票！")
        return
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成文件名
    date_suffix = ''
    if start_date and end_date:
        date_suffix = f'_{start_date}_{end_date}'
    elif start_date:
        date_suffix = f'_{start_date}_latest'
    elif end_date:
        date_suffix = f'_earliest_{end_date}'
    
    # 保存为TXT
    txt_file = os.path.join(output_dir, f'{output_prefix}{date_suffix}.txt')
    save_stock_list_txt(stock_list, txt_file)
    
    # 保存为CSV
    csv_file = os.path.join(output_dir, f'{output_prefix}{date_suffix}.csv')
    save_stock_list_csv(stock_list, csv_file)
    
    print(f"\n已生成复盘股票列表:")
    print(f"  TXT: {txt_file}")
    print(f"  CSV: {csv_file}")


def generate_all():
    print("=" * 60)
    print("生成批量回测股票列表文件")
    print("=" * 60)

    # 生成全部A股列表
    print("\n1. 生成全部A股列表...")
    generate_all_stock_list()

    # 按市场分类
    print("\n2. 按市场分类生成列表...")
    generate_market_stock_lists()

    # 按板块分类
    print("\n3. 按板块分类生成列表...")
    generate_board_stock_lists()

    print("\n" + "=" * 60)
    print("所有列表文件已生成到: data/batch_backtest/")
    print("=" * 60)


if __name__ == '__main__':
    # 示例1: 生成全部A股列表
    print("=" * 60)
    print("生成全部A股列表")
    print("=" * 60)
    generate_all_stock_list()

    print("\n" + "=" * 60)
    print("按市场分类生成股票列表")
    print("=" * 60)
    generate_market_stock_lists()

    print("\n" + "=" * 60)
    print("按板块分类生成股票列表")
    print("=" * 60)
    generate_board_stock_lists()
