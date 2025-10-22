"""
测试从复盘数据提取股票列表功能

快速验证从 excel/fupan_stocks.xlsx 提取股票是否正常工作
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bin.generate_stock_list import generate_fupan_stock_list


def test_extract_lianban():
    """测试提取连板数据"""
    print("=" * 60)
    print("测试: 提取连板股票")
    print("=" * 60)
    
    generate_fupan_stock_list(
        fupan_file='excel/fupan_stocks.xlsx',
        sheet_names=['连板数据'],
        start_date='20250101',
        end_date='20250131',
        output_dir='tests/test_fupan_results',
        output_prefix='test_lianban'
    )
    
    print("\n✅ 测试完成！")


def test_extract_multiple_sheets():
    """测试提取多个sheet的数据"""
    print("\n" + "=" * 60)
    print("测试: 提取多种类型热门股")
    print("=" * 60)
    
    generate_fupan_stock_list(
        fupan_file='excel/fupan_stocks.xlsx',
        sheet_names=['连板数据', '首板数据', '大涨数据'],
        start_date='20250101',
        end_date='20250131',
        output_dir='tests/test_fupan_results',
        output_prefix='test_hot_stocks'
    )
    
    print("\n✅ 测试完成！")


def test_extract_all():
    """测试提取所有sheet的数据（不限日期）"""
    print("\n" + "=" * 60)
    print("测试: 提取所有类型股票（最近10天）")
    print("=" * 60)
    
    # 获取最近的日期范围
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
    
    generate_fupan_stock_list(
        fupan_file='excel/fupan_stocks.xlsx',
        sheet_names=None,  # 所有sheet
        start_date=start_date,
        end_date=end_date,
        output_dir='tests/test_fupan_results',
        output_prefix='test_all_recent'
    )
    
    print("\n✅ 测试完成！")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='测试复盘数据提取功能')
    parser.add_argument('--test', choices=['lianban', 'multiple', 'all', 'full'], 
                       default='lianban',
                       help='测试类型')
    
    args = parser.parse_args()
    
    if args.test == 'lianban':
        test_extract_lianban()
    elif args.test == 'multiple':
        test_extract_multiple_sheets()
    elif args.test == 'all':
        test_extract_all()
    elif args.test == 'full':
        test_extract_lianban()
        test_extract_multiple_sheets()
        test_extract_all()
    
    print("\n" + "=" * 60)
    print("所有测试完成！查看 tests/test_fupan_results/ 目录")
    print("=" * 60) 