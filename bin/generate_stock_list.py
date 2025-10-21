"""
股票列表生成工具

从已下载的股票数据中提取股票代码列表，保存为TXT或CSV文件
"""

import os
from pathlib import Path
from typing import List, Tuple

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
