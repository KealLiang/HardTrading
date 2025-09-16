"""
盘中情绪分析器测试

测试竞价和盘中情绪分析功能，生成示例报告和图表。

使用方法：
python tests/test_mood_analyzer.py
"""

import sys
import os
sys.path.append('.')

from alerting.mood_analyzer import MoodAnalyzer
from datetime import datetime


def test_mood_analyzer():
    """测试情绪分析器"""
    print("=" * 60)
    print("🧪 盘中情绪分析器测试")
    print("=" * 60)
    
    # 创建分析器
    analyzer = MoodAnalyzer()
    
    # 测试日期
    test_date = '20250912'
    
    print(f"📅 测试日期: {test_date}")
    
    # 1. 测试竞价阶段情绪分析
    print("\n1️⃣ 测试竞价阶段情绪分析...")
    
    # 测试不同时间点
    auction_times = ["0915", "0920", "0925"]
    
    for time_point in auction_times:
        print(f"\n   测试时间点: {time_point[:2]}:{time_point[2:]}")
        
        # 执行分析
        analysis = analyzer.analyze_auction_mood(test_date, time_point)
        
        if analysis:
            print(f"   情绪评分: {analysis['score']}分")
            print(f"   情绪等级: {analysis['level']} {analysis['emoji']}")
            print(f"   涨停数量: {analysis['data']['涨停数量']}")
            print(f"   跌停数量: {analysis['data']['跌停数量']}")
            print(f"   竞价封板: {analysis['data']['竞价封板']}")
            
            # 生成报告和图表
            report_path = analyzer.generate_mood_report(analysis)
            chart_path = analyzer.plot_mood_chart(analysis)
            
            print(f"   ✅ 报告已生成: {report_path}")
            print(f"   ✅ 图表已生成: {chart_path}")
        else:
            print("   ❌ 分析失败")
    
    # 2. 测试盘中情绪分析
    print("\n2️⃣ 测试盘中情绪分析...")
    
    # 测试不同时间点
    intraday_times = ["1000", "1100", "1330", "1430"]
    
    for time_point in intraday_times:
        print(f"\n   测试时间点: {time_point[:2]}:{time_point[2:]}")
        
        # 执行分析
        analysis = analyzer.analyze_intraday_mood(test_date, time_point)
        
        if analysis:
            print(f"   情绪评分: {analysis['score']}分")
            print(f"   情绪等级: {analysis['level']} {analysis['emoji']}")
            print(f"   涨停数量: {analysis['data']['涨停数量']}")
            print(f"   跌停数量: {analysis['data']['跌停数量']}")
            print(f"   炸板数量: {analysis['data']['炸板数量']}")
            print(f"   炸板率: {analysis['data']['炸板率']:.1%}")
            
            # 生成报告和图表
            report_path = analyzer.generate_mood_report(analysis)
            chart_path = analyzer.plot_mood_chart(analysis)
            
            print(f"   ✅ 报告已生成: {report_path}")
            print(f"   ✅ 图表已生成: {chart_path}")
        else:
            print("   ❌ 分析失败")
    
    # 3. 查看生成的文件
    print("\n3️⃣ 查看生成的文件...")
    
    mood_dir = f"alerting/mood/{test_date}"
    if os.path.exists(mood_dir):
        files = os.listdir(mood_dir)
        files.sort()
        
        print(f"\n   📁 输出目录: {mood_dir}")
        print("   📄 生成的文件:")
        
        for file in files:
            file_path = os.path.join(mood_dir, file)
            file_size = os.path.getsize(file_path)
            
            if file.endswith('.md'):
                icon = "📝"
            elif file.endswith('.png'):
                icon = "📊"
            else:
                icon = "📄"
            
            print(f"     {icon} {file} ({file_size} bytes)")
    else:
        print(f"   ❌ 输出目录不存在: {mood_dir}")
    
    # 4. 展示报告内容示例
    print("\n4️⃣ 展示报告内容示例...")
    
    # 显示最新的竞价报告
    auction_report = f"{mood_dir}/0925_auction_mood.md"
    if os.path.exists(auction_report):
        print(f"\n   📝 竞价报告内容 ({auction_report}):")
        print("   " + "-" * 50)
        with open(auction_report, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只显示前10行
            lines = content.split('\n')[:10]
            for line in lines:
                print(f"   {line}")
        print("   " + "-" * 50)
    
    # 显示最新的盘中报告
    intraday_report = f"{mood_dir}/1000_intraday_mood.md"
    if os.path.exists(intraday_report):
        print(f"\n   📝 盘中报告内容 ({intraday_report}):")
        print("   " + "-" * 50)
        with open(intraday_report, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只显示前10行
            lines = content.split('\n')[:10]
            for line in lines:
                print(f"   {line}")
        print("   " + "-" * 50)
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("\n📊 总结:")
    print("   - 竞价阶段分析：专注开盘情绪，关注竞价封板")
    print("   - 盘中分析：关注炸板率、成交量变化")
    print("   - 情绪评分：0-100分，自动判断情绪等级")
    print("   - 报告简洁：便于盘中快速决策")
    print("   - 图表直观：仪表盘+对比图+分布图")
    print("\n🎯 使用建议:")
    print("   - 竞价阶段：关注开盘强度，制定当日策略")
    print("   - 盘中阶段：跟踪情绪变化，及时调整仓位")
    print("   - 情绪强度：>70分积极参与，<30分规避风险")
    print("=" * 60)


def test_specific_analysis():
    """测试特定分析功能"""
    print("\n🔬 测试特定分析功能...")
    
    analyzer = MoodAnalyzer()
    
    # 测试情绪评分算法
    test_data = {
        '涨停数量': 15,
        '跌停数量': 2,
        '竞价封板': 8,
        '最高连板': 4,
        '三板以上': 3,
        '炸板率': 0.2,
        '成交量比': 1.3,
        '平均换手率': 6.5,
        '净涨停': 13
    }
    
    score = analyzer.calculate_mood_score(test_data)
    level, emoji = analyzer.get_mood_level(score)
    
    print(f"   测试数据: {test_data}")
    print(f"   计算结果: {score}分 - {level} {emoji}")
    
    # 测试不同情绪等级
    test_scores = [95, 75, 55, 35, 15]
    print(f"\n   情绪等级测试:")
    for score in test_scores:
        level, emoji = analyzer.get_mood_level(score)
        print(f"     {score}分 → {level} {emoji}")


if __name__ == "__main__":
    test_mood_analyzer()
    test_specific_analysis()
