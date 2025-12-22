"""
股票分组逻辑验证脚本

用途：
1. 验证股票的题材概念如何被分配到概念组
2. 分析分组的优先级和匹配规则
3. 快速诊断分组异常问题

使用方法：
python tests/test_stock_grouping.py

注意：
- 测试使用的同义词组配置：data/reasons/origin_synonym_groups.py（与实际代码一致）
- 分组逻辑使用：select_concept_group_for_stock()（与实际代码一致）
"""

import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from utils.theme_color_util import (
    normalize_reason, get_reason_colors, extract_reasons_with_match_type
)
from analysis.ladder_chart import select_concept_group_for_stock
from data.reasons.origin_synonym_groups import synonym_groups


def analyze_concept_matching(concept_text):
    """
    分析单个概念如何被匹配到分组
    
    Args:
        concept_text: 原始概念文本，如 "商业航天"
        
    Returns:
        dict: 匹配详情
    """
    print(f"\n{'=' * 70}")
    print(f"分析概念: 【{concept_text}】")
    print(f"{'=' * 70}")

    # 规范化原因
    normalized = normalize_reason(concept_text)
    print(f"✓ 规范化结果: {normalized}")

    # 查找所有可能的匹配
    import re
    matches = []

    for main_reason, synonyms in synonym_groups.items():
        for synonym in synonyms:
            # 通配符匹配
            if '%' in synonym:
                pattern = synonym.replace('%', '(.*)')
                regex = re.compile(f"^{pattern}$")
                match = regex.search(concept_text.replace(' ', ''))

                if match:
                    matched_text = concept_text.replace(' ', '')
                    for group in match.groups():
                        matched_text = matched_text.replace(group, '')
                    match_strength = len(matched_text) / len(concept_text)
                    matches.append({
                        'group': main_reason,
                        'synonym': synonym,
                        'type': '模糊匹配',
                        'strength': match_strength
                    })

            # 包含匹配
            elif synonym in concept_text:
                match_strength = len(synonym) / len(concept_text)
                # 判断是否精确匹配
                match_type = '精确匹配' if synonym == concept_text else '包含匹配'
                matches.append({
                    'group': main_reason,
                    'synonym': synonym,
                    'type': match_type,
                    'strength': match_strength
                })

    if matches:
        print(f"\n找到 {len(matches)} 个匹配:")
        # 按匹配强度排序
        matches.sort(key=lambda x: x['strength'], reverse=True)

        for i, match in enumerate(matches, 1):
            symbol = "★" if i == 1 else " "
            print(f"  {symbol} [{match['type']}] {match['group']:<15} "
                  f"(匹配词: {match['synonym']:<20} 强度: {match['strength']:.2%})")

        print(f"\n→ 最终选择: 【{matches[0]['group']}】(匹配强度最高)")
    else:
        print(f"\n✗ 无匹配，将被标记为: 未分类_{concept_text}")

    return {
        'original': concept_text,
        'normalized': normalized,
        'matches': matches
    }


def quick_test(stock_name, concepts_text, priority_reasons=None,
               low_priority_reasons=None, entry_type='normal'):
    """
    快速测试模式 - 测试分组逻辑（与实际运行等价）
    
    Args:
        stock_name: 股票名称
        concepts_text: 题材概念文本
        priority_reasons: 优先选择的原因列表，默认为None
        low_priority_reasons: 低优先级原因列表，默认为None
        entry_type: 入选类型，默认为'normal'
    
    说明：
    - 使用当前股票的概念计算top_reasons（虽然不准确，但足以测试基本分组逻辑）
    - top_reasons主要影响：当股票有多个概念且都在top_reasons中时，按top_reasons顺序选择
    - 如果股票的概念不在top_reasons中，或只有一个概念，则top_reasons不影响结果
    """
    print(f"\n{'=' * 80}")
    print(f"测试股票: {stock_name}")
    print(f"概念: {concepts_text}")
    print(f"{'.' * 80}")

    # 提取概念（包含匹配类型）
    reason_details = extract_reasons_with_match_type(concepts_text)
    concepts = [normalized for normalized, _, _ in reason_details]

    print(f"\n【步骤1】概念提取与规范化")
    print(f"{'-' * 70}")
    print(f"原始概念: {concepts_text.split('+')}")
    print(f"规范化后: {concepts}")
    print(f"\n匹配类型详情:")
    for normalized, match_type, original in reason_details:
        match_symbol = "✓" if match_type == "exact" else ("~" if match_type == "fuzzy" else "✗")
        match_label = "精确" if match_type == "exact" else ("模糊" if match_type == "fuzzy" else "未匹配")
        print(f"  {match_symbol} {original} → {normalized} ({match_label})")

    # 计算热门概念（使用当前股票的概念，虽然不准确但足以测试基本逻辑）
    print(f"\n【步骤2】计算热门概念 (top_reasons)")
    print(f"{'-' * 70}")
    print(f"注意: 使用当前股票的概念计算top_reasons（仅用于测试基本分组逻辑）")
    _, top_reasons = get_reason_colors(
        concepts,
        priority_reasons=priority_reasons,
        low_priority_reasons=low_priority_reasons
    )

    print(f"热门概念列表 (共{len(top_reasons)}个):")
    for i, reason in enumerate(top_reasons, 1):
        in_stock = "✓" if reason in concepts else " "
        print(f"  {i:2d}. [{in_stock}] {reason}")

    # 测试分组逻辑（与实际代码一致：使用select_concept_group_for_stock）
    print(f"\n【步骤3】分组逻辑测试 (select_concept_group_for_stock)")
    print(f"{'-' * 70}")
    concept_group = select_concept_group_for_stock(
        concepts_text,
        entry_type,
        top_reasons,
        low_priority_reasons
    )

    print(f"→ 分组结果: 【{concept_group}】")

    # 显示分组决策过程
    print(f"\n【步骤4】分组决策分析")
    print(f"{'-' * 70}")

    # 统计该股票的概念出现次数
    concept_counter = Counter(concepts)

    # 找出该股票拥有的热门原因
    top_reasons_found = [reason for reason in top_reasons if reason in concept_counter]

    if top_reasons_found:
        print(f"该股票拥有的热门原因: {top_reasons_found}")
        print(f"\n各热门原因的详细信息:")

        for reason in top_reasons_found:
            # 找到该原因的匹配类型
            match_types = [mt for norm, mt, orig in reason_details if norm == reason]
            match_type = match_types[0] if match_types else 'unknown'
            match_label = "精确" if match_type == "exact" else ("模糊" if match_type == "fuzzy" else "未知")
            priority = top_reasons.index(reason) + 1
            count = concept_counter[reason]
            is_low_priority = reason in (low_priority_reasons or [])
            symbol = "★" if reason == concept_group else " "

            print(f"  {symbol} {reason}:")
            print(f"     匹配类型: {match_label}")
            print(f"     出现次数: {count}次")
            print(f"     热门度排名: 第{priority}位")
            print(f"     低优先级: {'是' if is_low_priority else '否'}")
    else:
        print(f"该股票没有热门原因，将使用其他分组规则")

    print(f"\n分组优先级规则:")
    print(f"  1. low_priority_reasons: 不在低优先级列表中的概念优先")
    print(f"  2. 匹配类型: 精确匹配 > 模糊匹配")
    print(f"  3. 热门度排名: top_reasons中的排名（受priority_reasons影响）")

    print(f"\n{'=' * 80}\n")

    return {
        'concept_group': concept_group,
        'top_reasons': top_reasons,
        'concepts': concepts,
        'reason_details': reason_details
    }


def analyze_stock_grouping(stock_name, concepts_text, simulate_top_reasons=None):
    """
    完整分析一只股票的分组逻辑（保留原有功能，向后兼容）
    
    Args:
        stock_name: 股票名称
        concepts_text: 题材概念文本，如 "商业航天+氢能装备+液力传动+央企"
        simulate_top_reasons: 模拟热门原因列表（用于测试），None则使用真实数据
        
    Returns:
        dict: 分组结果和详情
    """
    print(f"\n{'#' * 80}")
    print(f"# 分析股票: {stock_name}")
    print(f"# 题材概念: {concepts_text}")
    print(f"{'#' * 80}")

    # 第一步：提取并规范化所有概念
    print(f"\n【步骤1】提取并规范化所有概念")
    print(f"{'-' * 70}")

    reason_details = extract_reasons_with_match_type(concepts_text)
    concepts = [normalized for normalized, _, _ in reason_details]

    print(f"原始概念列表: {concepts_text.split('+')}")
    print(f"规范化后列表: {concepts}")
    print(f"\n匹配类型详情:")
    for normalized, match_type, original in reason_details:
        match_label = "精确匹配" if match_type == "exact" else ("模糊匹配" if match_type == "fuzzy" else "未匹配")
        print(f"  • {original} → {normalized} ({match_label})")

    # 第二步：分析每个概念的匹配情况
    print(f"\n【步骤2】分析每个概念的匹配详情")

    concept_details = []
    for concept in concepts_text.split('+'):
        detail = analyze_concept_matching(concept.strip())
        concept_details.append(detail)

    # 第三步：统计规范化后的概念出现次数
    print(f"\n【步骤3】统计规范化后的概念出现次数")
    print(f"{'-' * 70}")

    concept_counter = Counter(concepts)
    print("\n概念统计:")
    for concept, count in concept_counter.items():
        print(f"  • {concept}: {count}次")

    # 第四步：获取热门原因列表
    print(f"\n【步骤4】确定热门原因列表")
    print(f"{'-' * 70}")

    if simulate_top_reasons is None:
        # 使用真实的热门原因
        _, top_reasons = get_reason_colors(concepts)
    else:
        top_reasons = simulate_top_reasons

    print(f"热门原因列表 (共{len(top_reasons)}个):")
    for i, reason in enumerate(top_reasons, 1):
        in_stock = "✓" if reason in concept_counter else " "
        print(f"  {i:2d}. [{in_stock}] {reason}")

    # 第五步：应用分组规则（使用实际代码中的函数）
    print(f"\n【步骤5】应用分组规则 (select_concept_group_for_stock)")
    print(f"{'-' * 70}")

    concept_group = select_concept_group_for_stock(
        concepts_text,
        'normal',  # 默认入选类型
        top_reasons,
        None  # 默认无低优先级
    )

    # 找出该股票的热门原因
    top_reasons_found = [reason for reason in top_reasons if reason in concept_counter]

    print(f"\n该股票拥有的热门原因: {top_reasons_found}")

    if top_reasons_found:
        print(f"\n各热门原因的出现次数:")
        top_reason_counts = [(reason, concept_counter[reason]) for reason in top_reasons_found]
        top_reason_counts.sort(key=lambda x: x[1], reverse=True)

        for reason, count in top_reason_counts:
            priority = top_reasons.index(reason) + 1
            symbol = "★" if reason == concept_group else " "
            print(f"  {symbol} {reason}: {count}次 (热门度排名: 第{priority}位)")

        print(f"\n分组规则:")
        print(f"  1. low_priority_reasons: 不在低优先级列表中的概念优先")
        print(f"  2. 匹配类型：精确匹配 > 模糊匹配（最高优先级）")
        print(f"  3. 热门度：全市场热门度高的优先（top_reasons排名）")

        # 显示匹配类型信息
        print(f"\n各热门原因的匹配类型:")
        for reason in top_reasons_found:
            # 找到该原因的匹配类型
            match_types = [mt for norm, mt, orig in reason_details if norm == reason]
            if match_types:
                match_type = match_types[0]  # 取第一个（如果有多个相同的）
                match_label = "精确匹配" if match_type == "exact" else "模糊匹配"
                priority = top_reasons.index(reason) + 1
                count = concept_counter[reason]
                symbol = "★" if reason == concept_group else " "
                print(f"  {symbol} {reason}: {match_label}, {count}次, 热门度第{priority}位")

    print(f"\n{'=' * 70}")
    print(f"【最终结果】")
    print(f"  股票: {stock_name}")
    print(f"  分组: 【{concept_group}】")
    print(f"{'=' * 70}")

    return {
        'stock_name': stock_name,
        'concepts_text': concepts_text,
        'concepts': concepts,
        'concept_counter': concept_counter,
        'top_reasons': top_reasons,
        'top_reasons_found': top_reasons_found,
        'final_group': concept_group,
        'concept_details': concept_details
    }


if __name__ == "__main__":
    # 验证分组逻辑
    print("\n" + "=" * 80)
    print("验证分组逻辑（与实际运行等价）")
    print("注意：测试使用的同义词组配置：data/reasons/origin_synonym_groups.py")
    print("=" * 80)

    test_cases = [
        ("钧达股份", "TOPCon电池+钙钛矿电池+外销+海南自贸区+AH上市"),
        # ("和而泰", "人形机器人+参股摩尔线程+卫星芯片+三季报增长"),
    ]

    for name, concepts in test_cases:
        quick_test(name, concepts)

    print("\n" + "=" * 80)
    print("提示：")
    print("  1. 如需自定义测试，可以修改test_cases列表")
    print("  2. 如需详细分析，使用analyze_stock_grouping()函数")
    print("  3. 如需分析单个概念匹配，使用analyze_concept_matching()函数")
    print("=" * 80)
