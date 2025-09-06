#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例脚本：如何使用"默默上涨"功能

"默默上涨"功能说明：
- 查询条件：30天涨幅大于等于55%；30天无涨停；非ST；非近新股
- 数据特点：不能查历史数据，只能查当前数据
- 时间逻辑：如果当前时间是0点~9点30，则使用前一个交易日日期
- 数据格式：与其他复盘数据格式一致，单元格内容用分号分隔
"""

import os
import sys
from datetime import datetime

# 添加项目根目录到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from fetch.tonghuashun.fupan import daily_fupan, get_silently_increase_stocks, get_current_trading_date


def example_single_query():
    """
    示例1：单独查询"默默上涨"数据
    """
    print("=== 示例1：单独查询默默上涨数据 ===")

    # 获取默默上涨数据（不区分主板/非主板）
    print("查询默默上涨数据...")
    df = get_silently_increase_stocks()
    print(f"获取到数据：{len(df)} 条")
    if not df.empty:
        print("前3条数据:")
        print(df.head(3)[['股票代码', '股票简称', '最新价', '最新涨跌幅']].to_string())


def example_save_to_excel():
    """
    示例2：保存"默默上涨"数据到Excel
    """
    print("\n=== 示例2：保存默默上涨数据到Excel ===")

    # 获取当前交易日期
    current_date = get_current_trading_date()
    print(f"当前交易日期: {current_date}")

    # 保存默默上涨数据（只保存到主文件）
    print("保存默默上涨数据...")
    daily_fupan('默默上涨', None, None, "", "../excel/fupan_stocks.xlsx")

    print("数据已保存到Excel文件")


def example_check_saved_data():
    """
    示例3：检查保存的Excel数据
    """
    print("\n=== 示例3：检查保存的Excel数据 ===")

    import pandas as pd

    file_path = "../excel/fupan_stocks.xlsx"

    if os.path.exists(file_path):
        print(f"\n检查文件: {file_path}")
        try:
            excel_file = pd.ExcelFile(file_path)
            if '默默上涨' in excel_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name='默默上涨', index_col=0)
                print(f"  默默上涨sheet存在，数据形状: {df.shape}")
                print(f"  列名（日期）: {list(df.columns)}")
                if not df.empty:
                    print(f"  第一条数据示例: {df.iloc[0, 0] if df.shape[0] > 0 and df.shape[1] > 0 else '无数据'}")
            else:
                print(f"  文件中没有'默默上涨'sheet")
        except Exception as e:
            print(f"  读取文件时出错: {e}")
    else:
        print(f"\n文件不存在: {file_path}")


def example_integrated_usage():
    """
    示例4：集成到完整复盘流程
    """
    print("\n=== 示例4：集成到完整复盘流程 ===")
    print("如果要在完整复盘中包含'默默上涨'数据，可以使用以下方式：")
    print()
    print("方法1 - 使用all_fupan函数（会运行所有复盘类型，包括默默上涨）：")
    print("from fetch.tonghuashun.fupan import all_fupan")
    print("all_fupan(start_date='20250905', types=['all'])  # 主板（包含默默上涨）")
    print("all_fupan(start_date='20250905', types=['else'])  # 非主板（不包含默默上涨）")
    print()
    print("方法2 - 单独运行默默上涨：")
    print("from fetch.tonghuashun.fupan import daily_fupan")
    print("daily_fupan('默默上涨', None, None, '', './excel/fupan_stocks.xlsx')")


if __name__ == "__main__":
    # 切换到脚本目录
    os.chdir(script_dir)
    
    print("默默上涨功能使用示例")
    print("=" * 50)
    
    # 运行所有示例
    example_single_query()
    example_save_to_excel()
    example_check_saved_data()
    example_integrated_usage()
    
    print("\n" + "=" * 50)
    print("示例运行完成！")
    print("\n功能总结：")
    print("1. 新增了'默默上涨'复盘类型")
    print("2. 查询条件：30天涨幅≥55%，30天无涨停，非ST，非近新股")
    print("3. 数据会保存到Excel的'默默上涨'sheet中（只保存到主文件）")
    print("4. 数据格式与其他复盘数据一致（分号分隔）")
    print("5. 时间逻辑：0点~9点30或非交易日时使用前一交易日")
    print("6. 已集成到all_fupan函数中，只在主板配置中运行")
    print("7. 不区分主板/非主板，统一查询所有符合条件的股票")
