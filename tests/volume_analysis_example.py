#!/usr/bin/env python3
"""
成交量涨跌幅分析功能使用示例
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.ladder_chart import build_ladder_chart


def example_with_volume_analysis():
    """
    示例：生成包含成交量分析的涨停梯队图
    """
    print("生成包含成交量分析的涨停梯队图...")
    
    # 基本参数设置
    start_date = '20250905'  # 开始日期
    end_date = '20250910'    # 结束日期
    
    # 调用build_ladder_chart函数，启用成交量分析
    build_ladder_chart(
        start_date=start_date,
        end_date=end_date,
        min_board_level=2,                    # 最小连板数
        non_main_board_level=2,               # 非主板最小连板数
        show_period_change=True,              # 显示周期涨跌幅
        priority_reasons=[],                  # 优先概念列表
        enable_attention_criteria=True,       # 启用关注度榜入选条件
        sheet_name="成交量分析示例",           # 自定义工作表名称
        create_leader_sheet=False,            # 不创建龙头股工作表
        enable_momo_shangzhang=False,         # 不启用默默上涨
        create_volume_sheet=True              # 🔥 启用成交量涨跌幅分析
    )
    
    print("✅ 成交量分析示例生成完成！")
    print("📊 请查看Excel文件中的以下工作表：")
    print("   1. 成交量分析示例_按概念分组 - 原版股价涨跌幅分析")
    print("   2. 成交量分析示例_按概念分组_成交量分析 - 新增成交量涨跌幅分析")


def example_compare_price_and_volume():
    """
    示例：对比股价和成交量的变化
    """
    print("\n📈 分析建议：")
    print("1. 同时查看两个工作表，对比股价和成交量的变化")
    print("2. 关注以下几种情况：")
    print("   - 价涨量增：健康的上涨趋势")
    print("   - 价涨量缩：可能存在分歧，需要谨慎")
    print("   - 价跌量增：可能有恐慌性抛售")
    print("   - 价跌量缩：可能接近底部区域")
    print("3. 观察概念板块的成交量轮动情况")
    print("4. 识别异常放量或缩量的个股")


if __name__ == "__main__":
    # 运行示例
    example_with_volume_analysis()
    example_compare_price_and_volume()
    
    print("\n💡 提示：")
    print("- 要启用成交量分析，请在main.py中设置 create_volume_sheet=True")
    print("- 成交量分析工作表会自动添加'_成交量分析'后缀")
    print("- 颜色梯度已针对成交量变化特点进行优化")
    print("- 详细说明请参考 docs/VOLUME_ANALYSIS_DOC.md")
