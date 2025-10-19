"""
测试增强版相似走势查找功能

演示如何使用新的enhanced_weighted方法和性能优化参数
"""
from datetime import datetime
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.seek_historical_similar import find_other_similar_trends


def test_basic_enhanced_weighted():
    """
    测试1：基础增强版相似度计算（小规模）
    使用场景：精确匹配，候选数量较少
    """
    print("=" * 60)
    print("测试1：基础增强版相似度计算")
    print("=" * 60)
    
    target_stock_code = "301308"
    start_date = datetime.strptime('20250901', "%Y%m%d")
    end_date = datetime.strptime('20250929', "%Y%m%d")
    
    # 指定少量候选股票
    stock_codes = [
        "600928",
        "601319",
        "001227",
        "000001",
        "600036"
    ]
    
    find_other_similar_trends(
        target_stock_code=target_stock_code,
        start_date=start_date,
        end_date=end_date,
        stock_codes=stock_codes,
        data_dir="./data/astocks",
        method="enhanced_weighted",  # 使用增强版方法
        trend_end_date=end_date,
        same_market=True
    )


def test_same_market_search():
    """
    测试2：同市场查找（中等规模）
    使用场景：候选数量100-500，已内置文件映射表优化
    """
    print("\n" + "=" * 60)
    print("测试2：同市场查找（已自动优化IO性能）")
    print("=" * 60)
    
    target_stock_code = "301308"
    start_date = datetime.strptime('20250901', "%Y%m%d")
    end_date = datetime.strptime('20250929', "%Y%m%d")
    
    # 不指定stock_codes，自动扫描所有股票（但会被同市场过滤）
    find_other_similar_trends(
        target_stock_code=target_stock_code,
        start_date=start_date,
        end_date=end_date,
        stock_codes=None,  # 扫描所有
        data_dir="./data/astocks",
        method="enhanced_weighted",
        trend_end_date=end_date,
        same_market=True  # 只在同市场查找
    )


def test_full_market_search():
    """
    测试3：全市场查找（大规模）
    使用场景：候选数量 > 500，已内置文件映射表优化
    """
    print("\n" + "=" * 60)
    print("测试3：全市场查找（已自动优化IO性能）")
    print("=" * 60)
    
    target_stock_code = "301308"
    start_date = datetime.strptime('20250901', "%Y%m%d")
    end_date = datetime.strptime('20250929', "%Y%m%d")
    
    find_other_similar_trends(
        target_stock_code=target_stock_code,
        start_date=start_date,
        end_date=end_date,
        stock_codes=None,  # 扫描所有
        data_dir="./data/astocks",
        method="enhanced_weighted",
        trend_end_date=end_date,
        same_market=False  # 全市场查找
    )


def test_method_comparison():
    """
    测试4：对比不同方法的效果
    """
    print("\n" + "=" * 60)
    print("测试4：方法对比测试")
    print("=" * 60)
    
    target_stock_code = "301308"
    start_date = datetime.strptime('20250901', "%Y%m%d")
    end_date = datetime.strptime('20250929', "%Y%m%d")
    
    # 指定少量候选以便快速对比
    stock_codes = ["600928", "601319", "001227", "000001", "600036"]
    
    methods = [
        ("close_price", "仅收盘价相关性"),
        ("weighted", "原加权方法"),
        ("enhanced_weighted", "增强版加权方法"),
    ]
    
    for method, desc in methods:
        print(f"\n--- 使用方法: {method} ({desc}) ---")
        find_other_similar_trends(
            target_stock_code=target_stock_code,
            start_date=start_date,
            end_date=end_date,
            stock_codes=stock_codes,
            data_dir="./data/astocks",
            method=method,
            trend_end_date=end_date,
            same_market=True
        )


def test_two_stage_search():
    """
    测试5：两阶段搜索策略（最优实践）
    第一阶段：快速粗筛
    第二阶段：精确匹配
    """
    print("\n" + "=" * 60)
    print("测试5：两阶段搜索策略（推荐）")
    print("=" * 60)
    
    target_stock_code = "301308"
    start_date = datetime.strptime('20250901', "%Y%m%d")
    end_date = datetime.strptime('20250929', "%Y%m%d")
    
    print("\n【第一阶段】快速粗筛...")
    # 注意：实际使用时需要捕获返回结果
    print("使用 weighted 方法快速扫描全市场")
    
    # 这里只是演示，实际应该获取结果
    # results_rough = find_other_similar_trends(...)
    
    print("\n【第二阶段】精确匹配...")
    print("使用 enhanced_weighted 方法对TOP候选进行精确计算")
    
    # 模拟：假设从第一阶段得到了TOP候选
    top_candidates = ["600928", "601319", "001227"]
    
    find_other_similar_trends(
        target_stock_code=target_stock_code,
        start_date=start_date,
        end_date=end_date,
        stock_codes=top_candidates,  # 只计算TOP候选
        data_dir="./data/astocks",
        method="enhanced_weighted",  # 精确方法
        trend_end_date=end_date,
        same_market=True
    )


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════╗
║        相似走势查找 - 性能优化版测试                        ║
╚════════════════════════════════════════════════════════════╝

本测试脚本演示了以下功能：
1. 增强版相似度算法（enhanced_weighted）
2. 同市场查找（已内置IO优化）
3. 全市场查找（已内置IO优化）
4. 方法对比
5. 两阶段搜索策略

性能优化亮点：
✅ 预先构建文件映射表（提速50-100倍）
✅ 去掉预筛选机制（减少IO负担）
✅ 优化V2版本双重扫描

请根据需要选择测试项目运行。
    """)
    
    # 可以选择运行哪个测试
    test_cases = {
        '1': ('基础增强版相似度计算', test_basic_enhanced_weighted),
        '2': ('同市场查找（IO已优化）', test_same_market_search),
        '3': ('全市场查找（IO已优化）', test_full_market_search),
        '4': ('方法对比测试', test_method_comparison),
        '5': ('两阶段搜索策略', test_two_stage_search),
        'all': ('运行所有测试', None),
    }
    
    print("可选测试项目：")
    for key, (desc, _) in test_cases.items():
        print(f"  {key}. {desc}")
    
    choice = input("\n请输入测试编号 (默认1): ").strip() or '1'
    
    if choice == 'all':
        for key in ['1', '2', '3', '4', '5']:
            test_cases[key][1]()
    elif choice in test_cases and choice != 'all':
        test_cases[choice][1]()
    else:
        print(f"无效的选择: {choice}")
        print("运行默认测试...")
        test_basic_enhanced_weighted()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60) 