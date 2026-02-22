"""
测试ETF数据获取功能
"""
import sys
import os

# 添加项目根目录到系统路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fetch.etf_data import ETFDataFetcher
import pandas as pd

def test_etf_data_fetch():
    """测试ETF数据获取功能"""
    print("=== 测试ETF数据获取功能 ===\n")
    
    # 创建ETF数据获取对象
    etf_fetcher = ETFDataFetcher(
        start_date='20260120',
        end_date='20260210',
        save_path='./data/etfs',
        max_workers=4,
        force_update=False,
        max_sleep_time=2000
    )
    
    # 指定要获取的ETF代码列表
    etf_codes = ['510300', '518880']  # 沪深300ETF、黄金ETF
    
    print(f"开始获取ETF数据: {etf_codes}")
    print(f"日期范围: 20260120 - 20260210\n")
    
    # 获取并保存数据
    etf_fetcher.fetch_and_save_data(etf_codes)
    
    print("\n=== 验证保存的数据 ===\n")
    
    # 验证保存的文件
    for etf_code in etf_codes:
        file_path = f'./data/etfs/{etf_code}.csv'
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            print(f"✓ ETF {etf_code} 数据已保存")
            print(f"  - 文件路径: {file_path}")
            print(f"  - 数据行数: {len(df)}")
            print(f"  - 数据列: {list(df.columns)}")
            print(f"  - 最新数据:")
            print(df.tail(1))
            print()
        else:
            print(f"✗ ETF {etf_code} 数据文件未找到")

if __name__ == "__main__":
    test_etf_data_fetch()

