"""
测试二板定龙头分析功能
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.erban_longtou_analyzer import analyze_erban_longtou

if __name__ == '__main__':
    # 使用近期的时间范围测试
    report_path = analyze_erban_longtou(
        start_date='20251101',
        end_date='20251130',
        min_concept_samples=1  # 降低最小样本数以便测试
    )
    
    if report_path:
        print(f"\n✅ 测试成功！报告路径: {report_path}")
        
        # 打印报告内容预览
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print("\n" + "="*60)
            print("报告内容预览（前2000字符）：")
            print("="*60)
            print(content[:2000])
    else:
        print("\n❌ 测试失败，未生成报告") 