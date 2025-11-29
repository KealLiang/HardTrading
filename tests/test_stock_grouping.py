"""
股票分组逻辑验证脚本

用途：
1. 验证股票的题材概念如何被分配到概念组
2. 分析分组的优先级和匹配规则
3. 快速诊断分组异常问题

使用方法：
python tests/test_stock_grouping.py
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
from utils.theme_color_util import normalize_reason, extract_reasons, get_stock_reason_group, get_reason_colors
from data.reasons.origin_synonym_groups import synonym_groups


def analyze_concept_matching(concept_text):
    """
    分析单个概念如何被匹配到分组
    
    Args:
        concept_text: 原始概念文本，如 "商业航天"
        
    Returns:
        dict: 匹配详情
    """
    print(f"\n{'='*70}")
    print(f"分析概念: 【{concept_text}】")
    print(f"{'='*70}")
    
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


def analyze_stock_grouping(stock_name, concepts_text, simulate_top_reasons=None):
    """
    完整分析一只股票的分组逻辑
    
    Args:
        stock_name: 股票名称
        concepts_text: 题材概念文本，如 "商业航天+氢能装备+液力传动+央企"
        simulate_top_reasons: 模拟热门原因列表（用于测试），None则使用真实数据
        
    Returns:
        dict: 分组结果和详情
    """
    print(f"\n{'#'*80}")
    print(f"# 分析股票: {stock_name}")
    print(f"# 题材概念: {concepts_text}")
    print(f"{'#'*80}")
    
    # 第一步：提取并规范化所有概念
    print(f"\n【步骤1】提取并规范化所有概念")
    print(f"{'-'*70}")
    
    from utils.theme_color_util import extract_reasons_with_match_type
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
    print(f"{'-'*70}")
    
    concept_counter = Counter(concepts)
    print("\n概念统计:")
    for concept, count in concept_counter.items():
        print(f"  • {concept}: {count}次")
    
    # 第四步：获取热门原因列表
    print(f"\n【步骤4】确定热门原因列表")
    print(f"{'-'*70}")
    
    if simulate_top_reasons is None:
        # 使用真实的热门原因（需要从Excel读取，这里简化处理）
        # 实际应该调用get_reason_colors
        _, top_reasons = get_reason_colors(concepts)
    else:
        top_reasons = simulate_top_reasons
    
    print(f"热门原因列表 (共{len(top_reasons)}个):")
    for i, reason in enumerate(top_reasons, 1):
        in_stock = "✓" if reason in concept_counter else " "
        print(f"  {i:2d}. [{in_stock}] {reason}")
    
    # 第五步：应用分组规则
    print(f"\n【步骤5】应用分组规则")
    print(f"{'-'*70}")
    
    stock_key = f"test_{stock_name}"
    all_stocks = {
        stock_key: {
            'name': stock_name,
            'reasons': concepts,
            'reason_details': reason_details,  # 新增：包含匹配类型信息
            'appearances': [1]
        }
    }
    
    stock_reason_group = get_stock_reason_group(all_stocks, top_reasons)
    
    # 找出该股票的热门原因
    top_reasons_found = [reason for reason in top_reasons if reason in concept_counter]
    
    print(f"\n该股票拥有的热门原因: {top_reasons_found}")
    
    if top_reasons_found:
        print(f"\n各热门原因的出现次数:")
        top_reason_counts = [(reason, concept_counter[reason]) for reason in top_reasons_found]
        top_reason_counts.sort(key=lambda x: x[1], reverse=True)
        
        for reason, count in top_reason_counts:
            priority = top_reasons.index(reason) + 1
            symbol = "★" if reason == stock_reason_group.get(stock_key) else " "
            print(f"  {symbol} {reason}: {count}次 (热门度排名: 第{priority}位)")
        
        print(f"\n分组规则（新版）:")
        print(f"  1. 匹配类型优先：精确匹配 > 模糊匹配（最高优先级）")
        print(f"  2. 出现次数：在该股票内出现次数多的优先")
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
                symbol = "★" if reason == stock_reason_group.get(stock_key) else " "
                print(f"  {symbol} {reason}: {match_label}, {count}次, 热门度第{priority}位")
    
    final_group = stock_reason_group.get(stock_key, "其他")
    
    print(f"\n{'='*70}")
    print(f"【最终结果】")
    print(f"  股票: {stock_name}")
    print(f"  分组: 【{final_group}】")
    print(f"{'='*70}")
    
    return {
        'stock_name': stock_name,
        'concepts_text': concepts_text,
        'concepts': concepts,
        'concept_counter': concept_counter,
        'top_reasons': top_reasons,
        'top_reasons_found': top_reasons_found,
        'final_group': final_group,
        'concept_details': concept_details
    }


def quick_test(stock_name, concepts_text):
    """
    快速测试模式 - 只显示关键信息
    
    Args:
        stock_name: 股票名称
        concepts_text: 题材概念文本
    """
    from utils.theme_color_util import extract_reasons_with_match_type
    
    # 提取概念（包含匹配类型）
    reason_details = extract_reasons_with_match_type(concepts_text)
    concepts = [normalized for normalized, _, _ in reason_details]
    
    print(f"\n股票: {stock_name}")
    print(f"概念: {concepts_text}")
    print(f"规范化: {' + '.join(concepts)}")
    
    # 显示匹配类型
    print(f"匹配类型:")
    for normalized, match_type, original in reason_details:
        match_symbol = "✓" if match_type == "exact" else "~"
        match_label = "精确" if match_type == "exact" else "模糊"
        print(f"  {match_symbol} {original} → {normalized} ({match_label})")
    
    # 创建股票数据（新格式：包含匹配类型）
    stock_key = f"{stock_name}"
    all_stocks = {
        stock_key: {
            'name': stock_name,
            'reasons': concepts,
            'reason_details': reason_details,  # 新增：匹配类型信息
            'appearances': [1]
        }
    }
    
    # 获取分组
    _, top_reasons = get_reason_colors(concepts)
    stock_reason_group = get_stock_reason_group(all_stocks, top_reasons)
    
    final_group = stock_reason_group.get(stock_key, "其他")
    print(f"→ 分组: 【{final_group}】（基于新规则：精确匹配优先）\n")
    
    return final_group


if __name__ == "__main__":
    # 示例1：分析"航天动力"的分组问题
    print("\n" + "="*80)
    print("示例1：完整分析航天动力的分组逻辑")
    print("="*80)
    
    result = analyze_stock_grouping(
        stock_name="航天动力",
        concepts_text="商业航天+氢能装备+液力传动+央企"
    )
    
    # 示例2：快速测试其他股票
    print("\n" + "="*80)
    print("示例2：快速测试模式")
    print("="*80)
    
    test_cases = [
        ("航天动力", "商业航天+氢能装备+液力传动+央企"),
        ("测试股票A", "AI服务器+算力+数据中心"),
        ("测试股票B", "新能源车+锂电池+动力电池"),
        ("测试股票C", "创新药+疫苗+医疗器械"),
    ]
    
    for name, concepts in test_cases:
        quick_test(name, concepts)
    
    print("\n" + "="*80)
    print("提示：")
    print("  1. 如需自定义测试，可以修改test_cases列表")
    print("  2. 如需详细分析，使用analyze_stock_grouping()函数")
    print("  3. 如需分析单个概念匹配，使用analyze_concept_matching()函数")
    print("="*80) 