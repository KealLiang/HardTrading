"""
测试成交量梯队图功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.ladder_chart import build_ladder_chart

def test_volume_ladder_chart():
    """测试成交量梯队图生成"""
    print("=== 测试成交量梯队图生成 ===")
    
    try:
        # 使用较短的时间范围进行测试
        start_date = '20250910'
        end_date = '20250915'
        
        print(f"生成时间范围: {start_date} - {end_date}")
        print("启用成交量分析功能...")
        
        # 构建梯队图，启用成交量分析
        build_ladder_chart(
            start_date=start_date,
            end_date=end_date,
            min_board_level=2,
            non_main_board_level=2,
            show_period_change=True,
            priority_reasons=[],
            enable_attention_criteria=False,
            sheet_name="测试",
            create_leader_sheet=False,
            create_volume_sheet=True,  # 启用成交量分析
            output_file="output/test_volume_ladder_chart.xlsx"
        )
        
        print("✅ 成交量梯队图生成成功！")
        print("📁 输出文件: output/test_volume_ladder_chart.xlsx")
        print("📊 请检查文件中的成交量分析工作表")
        
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()

def main():
    """主测试函数"""
    print("开始测试成交量梯队图功能...\n")
    test_volume_ladder_chart()
    print("\n测试完成！")

if __name__ == "__main__":
    main()
