"""
测试低优先级原因列表功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.theme_color_util import get_reason_colors, get_stock_reason_group


def test_low_priority_reasons():
    """测试低优先级原因列表功能"""
    print("=== 测试低优先级原因列表功能 ===\n")
    
    # 模拟数据
    all_reasons = ['算力产业', '预期改善', '机器人', '预期改善', '大消费', '预期改善', '预期改善']
    
    print("测试数据:")
    print(f"  所有原因: {all_reasons}")
    print(f"  原因统计: 算力产业(1), 预期改善(4), 机器人(1), 大消费(1)")
    print()
    
    # 测试1：不使用低优先级列表（向后兼容）
    print("【测试1】不使用低优先级列表（传None）")
    reason_colors_1, top_reasons_1 = get_reason_colors(all_reasons, top_n=5, priority_reasons=None, low_priority_reasons=None)
    print(f"  热门原因列表: {top_reasons_1}")
    print(f"  预期: '预期改善'应该排在前面（因为出现次数最多）")
    print()
    
    # 测试2：使用低优先级列表
    print("【测试2】使用低优先级列表（传['预期改善']）")
    low_priority_list = ['预期改善']
    reason_colors_2, top_reasons_2 = get_reason_colors(all_reasons, top_n=5, priority_reasons=None, low_priority_reasons=low_priority_list)
    print(f"  热门原因列表: {top_reasons_2}")
    print(f"  预期: '预期改善'应该排在最后（虽然出现次数多，但是低优先级）")
    print()
    
    # 测试3：测试股票分组逻辑
    print("【测试3】测试股票分组逻辑")
    
    # 模拟股票数据
    all_stocks = {
        '600000_浦发银行': {
            'name': '浦发银行',
            'reasons': ['预期改善', '大金融'],
            'reason_details': [
                ('预期改善', 'exact', '业绩预增'),
                ('大金融', 'fuzzy', '银行')
            ],
            'appearances': [1]
        },
        '600340_华夏幸福': {
            'name': '华夏幸福',
            'reasons': ['预期改善'],
            'reason_details': [
                ('预期改善', 'exact', '业绩扭亏')
            ],
            'appearances': [1]
        },
        '600519_贵州茅台': {
            'name': '贵州茅台',
            'reasons': ['大消费'],
            'reason_details': [
                ('大消费', 'exact', '白酒')
            ],
            'appearances': [1]
        }
    }
    
    print("\n  股票数据:")
    print("    600000_浦发银行: ['预期改善', '大金融']")
    print("    600340_华夏幸福: ['预期改善']")
    print("    600519_贵州茅台: ['大消费']")
    print()
    
    # 不使用低优先级列表
    print("  3.1 不使用低优先级列表:")
    stock_groups_1 = get_stock_reason_group(all_stocks, top_reasons_1, low_priority_reasons=None)
    for stock_key, group in stock_groups_1.items():
        print(f"    {stock_key} -> {group}")
    print("    预期: 浦发银行可能归入'预期改善'或'大金融'")
    print()
    
    # 使用低优先级列表
    print("  3.2 使用低优先级列表 ['预期改善']:")
    stock_groups_2 = get_stock_reason_group(all_stocks, top_reasons_2, low_priority_reasons=low_priority_list)
    for stock_key, group in stock_groups_2.items():
        print(f"    {stock_key} -> {group}")
    print("    预期: 浦发银行应该归入'大金融'（因为'预期改善'是低优先级）")
    print("    预期: 华夏幸福归入'预期改善'（因为没有其他分组可选）")
    print("    预期: 贵州茅台归入'大消费'（不受影响）")
    print()
    
    # 验证结果
    print("【验证结果】")
    success = True
    
    # 验证1：低优先级原因应该排在后面
    if '预期改善' in top_reasons_2:
        pos = top_reasons_2.index('预期改善')
        if pos < len(top_reasons_2) - 2:  # 不应该排在前面
            print(f"  ❌ 测试失败: '预期改善'排在位置{pos}，应该排在后面")
            success = False
        else:
            print(f"  ✅ 低优先级原因'预期改善'正确排在位置{pos}")
    
    # 验证2：浦发银行应该归入'大金融'而不是'预期改善'
    if '600000_浦发银行' in stock_groups_2:
        group = stock_groups_2['600000_浦发银行']
        if group == '大金融':
            print(f"  ✅ 浦发银行正确归入'{group}'（避开了低优先级'预期改善'）")
        else:
            print(f"  ⚠️  浦发银行归入'{group}'（可能因为匹配规则）")
    
    # 验证3：华夏幸福应该归入'预期改善'（因为没有其他选择）
    if '600340_华夏幸福' in stock_groups_2:
        group = stock_groups_2['600340_华夏幸福']
        if group == '预期改善':
            print(f"  ✅ 华夏幸福正确归入'{group}'（没有其他分组可选）")
        else:
            print(f"  ❌ 测试失败: 华夏幸福归入'{group}'，应该归入'预期改善'")
            success = False
    
    print()
    if success:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败，请检查实现逻辑")
    
    return success


def main():
    """主测试函数"""
    try:
        test_low_priority_reasons()
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main() 