"""
测试低优先级原因功能的完整工作流
模拟从identify_first_significant_board到最终Excel分组的完整流程
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.theme_color_util import extract_reasons_with_match_type


def test_concept_group_selection_with_low_priority():
    """测试概念组选择逻辑（模拟get_global_concept_group函数）"""
    print("=== 测试完整的概念组选择逻辑 ===\n")
    
    # 模拟global_top_reasons（热门原因列表）
    global_top_reasons = ['算力产业', '机器人', '大消费', '大金融']
    
    # 模拟low_priority_reasons
    low_priority_reasons = ['预期改善']
    
    # 测试案例（使用+分割的概念字符串格式，使用同义词分组中实际存在的词）
    test_cases = [
        {
            'name': '某证券公司（有预期改善+大金融）',
            'concept_str': '业绩预增+证券',
            'expected_without_low': '预期改善',  # 不使用低优先级时，可能选预期改善
            'expected_with_low': '大金融'       # 使用低优先级时，应避开预期改善选大金融
        },
        {
            'name': '华夏幸福（只有预期改善）',
            'concept_str': '业绩扭亏',
            'expected_without_low': '预期改善',
            'expected_with_low': '预期改善'     # 只有低优先级，仍归入
        },
        {
            'name': '贵州茅台（有大消费）',
            'concept_str': '白酒',
            'expected_without_low': '大消费',
            'expected_with_low': '大消费'       # 不受影响
        },
        {
            'name': '某机器人公司（有机器人+预期改善）',
            'concept_str': '人形机器人+业绩预增',
            'expected_without_low': '机器人',  # 不使用低优先级时可能选机器人或预期改善
            'expected_with_low': '机器人'      # 使用低优先级时，应避开预期改善选机器人
        },
        {
            'name': '某AI公司（有AI应用+预期改善）',
            'concept_str': '大模型+业绩报增',
            'expected_without_low': 'AI应用',  # 不使用低优先级时
            'expected_with_low': 'AI应用'      # 使用低优先级时，应避开预期改善选AI应用
        }
    ]
    
    print("测试配置:")
    print(f"  热门原因列表: {global_top_reasons}")
    print(f"  低优先级列表: {low_priority_reasons}")
    print()
    
    # 定义get_global_concept_group函数（与ladder_chart.py中的逻辑一致）
    def get_global_concept_group(concept_str, use_low_priority=False):
        if not concept_str:
            return "其他"
        
        # 提取概念及其匹配类型
        concepts_with_type = extract_reasons_with_match_type(concept_str)
        if not concepts_with_type:
            return "其他"
        
        # 分离精确匹配和模糊匹配的概念
        exact_concepts = [c[0] for c in concepts_with_type if c[1] == 'exact']
        fuzzy_concepts = [c[0] for c in concepts_with_type if c[1] == 'fuzzy']
        
        # 使用或不使用低优先级列表
        low_priority_list = low_priority_reasons if use_low_priority else []
        
        # 优先级1：精确匹配的非低优先级概念
        if exact_concepts:
            # 1a. 优先选择热门的、非低优先级的精确匹配概念
            for top_reason in global_top_reasons:
                if top_reason in exact_concepts and top_reason not in low_priority_list:
                    return top_reason
            
            # 1b. 如果有非低优先级的精确匹配，也优先返回
            non_low_priority_exact = [c for c in exact_concepts if c not in low_priority_list]
            if non_low_priority_exact:
                return non_low_priority_exact[0]
        
        # 优先级2：模糊匹配的非低优先级概念
        if fuzzy_concepts:
            # 2a. 优先选择热门的、非低优先级的模糊匹配概念
            for top_reason in global_top_reasons:
                if top_reason in fuzzy_concepts and top_reason not in low_priority_list:
                    return top_reason
            
            # 2b. 如果有非低优先级的模糊匹配，也优先返回
            non_low_priority_fuzzy = [c for c in fuzzy_concepts if c not in low_priority_list]
            if non_low_priority_fuzzy:
                return non_low_priority_fuzzy[0]
        
        # 优先级3：如果所有概念都是低优先级
        if exact_concepts:
            for top_reason in global_top_reasons:
                if top_reason in exact_concepts:
                    return top_reason
            return exact_concepts[0]
        
        if fuzzy_concepts:
            for top_reason in global_top_reasons:
                if top_reason in fuzzy_concepts:
                    return top_reason
            return fuzzy_concepts[0]
        
        # 兜底
        all_concepts = [c[0] for c in concepts_with_type]
        return all_concepts[0] if all_concepts else "其他"
    
    # 运行测试
    all_pass = True
    for i, case in enumerate(test_cases, 1):
        print(f"【测试{i}】{case['name']}")
        print(f"  概念字符串: '{case['concept_str']}'")
        
        # 提取概念详情
        concepts_with_type = extract_reasons_with_match_type(case['concept_str'])
        print(f"  提取的概念: {concepts_with_type}")
        
        # 不使用低优先级
        result_without = get_global_concept_group(case['concept_str'], use_low_priority=False)
        print(f"  不使用低优先级: {result_without} (预期: {case['expected_without_low']})")
        
        # 使用低优先级
        result_with = get_global_concept_group(case['concept_str'], use_low_priority=True)
        print(f"  使用低优先级: {result_with} (预期: {case['expected_with_low']})")
        
        # 验证结果
        if result_with == case['expected_with_low']:
            print(f"  ✅ 测试通过")
        else:
            print(f"  ❌ 测试失败: 期望 {case['expected_with_low']}, 实际 {result_with}")
            all_pass = False
        
        print()
    
    if all_pass:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败，请检查实现逻辑")
    
    return all_pass


def main():
    """主测试函数"""
    try:
        test_concept_group_selection_with_low_priority()
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main() 