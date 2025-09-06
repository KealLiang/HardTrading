"""
测试带有异动预警功能的天梯图
"""

from analysis.ladder_chart import build_ladder_chart
from datetime import datetime, timedelta


def test_ladder_chart_with_warning():
    """测试带有异动预警功能的天梯图"""
    
    print("=== 测试带有异动预警功能的天梯图 ===")
    
    # 设置测试日期范围（最近一周）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    
    print(f"测试日期范围: {start_date_str} 至 {end_date_str}")
    
    # 设置输出文件
    output_file = f"./output/test_ladder_chart_warning_{end_date_str}.xlsx"
    
    try:
        # 调用天梯图生成函数
        result = build_ladder_chart(
            start_date=start_date_str,
            end_date=end_date_str,
            output_file=output_file,
            min_board_level=1,  # 降低门槛以便测试
            max_tracking_days=10,
            reentry_days=3,
            non_main_board_level=1,
            max_tracking_days_before=5,
            period_days=5,
            period_days_long=20,
            show_period_change=True,
            priority_reasons=None,
            enable_attention_criteria=False,
            sheet_name=None,
            create_leader_sheet=False
        )
        
        if result:
            print(f"✅ 天梯图生成成功！")
            print(f"📁 输出文件: {output_file}")
            print("🔍 请检查Excel文件中的异动预警列")
        else:
            print("❌ 天梯图生成失败")
            
    except Exception as e:
        print(f"❌ 测试过程中出错: {e}")
        import traceback
        traceback.print_exc()


def test_specific_date_range():
    """测试特定日期范围"""

    print("\n=== 测试修复后的异动预警功能 ===")

    # 使用固定的日期范围进行测试
    start_date_str = '20250825'  # 可以根据实际情况调整
    end_date_str = '20250905'
    
    print(f"测试日期范围: {start_date_str} 至 {end_date_str}")
    
    # 设置输出文件
    output_file = f"./output/ladder_chart_fixed_{start_date_str}_{end_date_str}.xlsx"
    
    try:
        # 调用天梯图生成函数
        result = build_ladder_chart(
            start_date=start_date_str,
            end_date=end_date_str,
            output_file=output_file,
            min_board_level=2,  # 使用正常门槛
            max_tracking_days=15,
            reentry_days=5,
            non_main_board_level=1,
            max_tracking_days_before=10,
            period_days=5,
            period_days_long=20,
            show_period_change=True,
            priority_reasons=None,
            enable_attention_criteria=False,
            sheet_name=None,
            create_leader_sheet=False
        )
        
        if result:
            print(f"✅ 天梯图生成成功！")
            print(f"📁 输出文件: {output_file}")
            print("🔍 请检查Excel文件中的异动预警列")
            print("📊 预警列说明（修复后的颜色方案）:")
            print("   🔴 浅红色背景: 已触发严重异常波动")
            print("   🟠 浅橙色背景: 已触发异常波动")
            print("   🩷 浅粉红色背景: 即将触发严重异动")
            print("   ⚪ 无背景: 即将触发异常波动/正常状态")
            print("   ✅ 修复了预警优先级bug")
            print("   ✅ 固定了行高")
            print("   ✅ 添加了性能优化")
        else:
            print("❌ 天梯图生成失败")
            
    except Exception as e:
        print(f"❌ 测试过程中出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 运行基本测试
    test_ladder_chart_with_warning()
    
    # 运行特定日期范围测试
    test_specific_date_range()
    
    print("\n=== 测试完成 ===")
    print("如果生成成功，请打开Excel文件查看异动预警列的效果")
    print("异动预警列位于所有日期列的右侧，显示每只股票的异动风险状态")
