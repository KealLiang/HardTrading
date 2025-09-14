"""
竞价阶段数据准确性测试

对比我们的数据与同花顺软件显示的竞价阶段涨跌停数据，
找出差异原因并验证数据准确性。

根据用户反馈：
- 同花顺显示20250912竞价涨停4个，跌停1个
- 我们的报告显示竞价阶段封板数: 2 只

测试目标：
1. 验证竞价阶段股票识别逻辑
2. 对比封板时间判断标准
3. 分析数据差异原因
"""

import sys
import os
sys.path.append('.')

import pandas as pd
from fetch.auction_fengdan_data import AuctionFengdanCollector
from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer


def test_auction_data_accuracy():
    """测试竞价阶段数据准确性"""
    print("=" * 60)
    print("🔍 竞价阶段数据准确性测试")
    print("=" * 60)
    
    # 测试日期
    test_date = '20250912'
    
    collector = AuctionFengdanCollector()
    
    print(f"\n📅 测试日期: {test_date}")
    print(f"🎯 同花顺显示: 竞价涨停4个，跌停1个")
    
    # 1. 获取原始数据
    print("\n1️⃣ 获取原始涨停数据...")
    zt_data = collector.get_zt_fengdan_data(test_date)
    print(f"   涨停总数: {len(zt_data)}")
    
    print("\n2️⃣ 获取原始跌停数据...")
    dt_data = collector.get_dt_fengdan_data(test_date)
    print(f"   跌停总数: {len(dt_data)}")
    
    # 2. 分析首次封板时间字段
    print("\n3️⃣ 分析首次封板时间字段...")
    if not zt_data.empty and '首次封板时间' in zt_data.columns:
        print("   涨停数据中的首次封板时间样本:")
        time_samples = zt_data['首次封板时间'].head(10).tolist()
        for i, time_val in enumerate(time_samples, 1):
            print(f"     {i}. {time_val} (类型: {type(time_val)})")
        
        # 统计时间分布
        print("\n   首次封板时间分布:")
        time_counts = zt_data['首次封板时间'].value_counts().head(10)
        for time_val, count in time_counts.items():
            print(f"     {time_val}: {count}只")
    
    # 3. 测试竞价阶段识别逻辑
    print("\n4️⃣ 测试竞价阶段识别逻辑...")
    
    # 当前逻辑：092开头
    current_logic_zt = zt_data[zt_data['首次封板时间'].astype(str).str.startswith('092')] if '首次封板时间' in zt_data.columns else pd.DataFrame()
    current_logic_dt = dt_data[dt_data['首次封板时间'].astype(str).str.startswith('092')] if '首次封板时间' in dt_data.columns else pd.DataFrame()
    
    print(f"   当前逻辑(092开头) - 涨停: {len(current_logic_zt)}只, 跌停: {len(current_logic_dt)}只")
    
    if not current_logic_zt.empty:
        print("   当前逻辑识别的竞价涨停:")
        for _, row in current_logic_zt.iterrows():
            code = str(row['代码']).zfill(6)
            print(f"     {code} {row['名称']}: {row['首次封板时间']}")
    
    if not current_logic_dt.empty:
        print("   当前逻辑识别的竞价跌停:")
        for _, row in current_logic_dt.iterrows():
            code = str(row['代码']).zfill(6)
            print(f"     {code} {row['名称']}: {row['首次封板时间']}")
    
    # 4. 尝试其他识别逻辑
    print("\n5️⃣ 尝试其他识别逻辑...")
    
    # 逻辑1：09:15-09:25之间的时间
    def is_auction_time_range(time_str):
        """判断是否在竞价时间范围内"""
        try:
            time_str = str(time_str)
            if len(time_str) == 6:  # HHMMSS格式
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                if hour == 9 and 15 <= minute <= 25:
                    return True
            elif len(time_str) == 5:  # HMMSS格式
                if time_str.startswith('9'):
                    minute = int(time_str[1:3])
                    if 15 <= minute <= 25:
                        return True
            return False
        except:
            return False
    
    range_logic_zt = zt_data[zt_data['首次封板时间'].apply(is_auction_time_range)] if '首次封板时间' in zt_data.columns else pd.DataFrame()
    range_logic_dt = dt_data[dt_data['首次封板时间'].apply(is_auction_time_range)] if '首次封板时间' in dt_data.columns else pd.DataFrame()
    
    print(f"   时间范围逻辑(09:15-09:25) - 涨停: {len(range_logic_zt)}只, 跌停: {len(range_logic_dt)}只")
    
    if not range_logic_zt.empty:
        print("   时间范围逻辑识别的竞价涨停:")
        for _, row in range_logic_zt.iterrows():
            code = str(row['代码']).zfill(6)
            print(f"     {code} {row['名称']}: {row['首次封板时间']}")
    
    if not range_logic_dt.empty:
        print("   时间范围逻辑识别的竞价跌停:")
        for _, row in range_logic_dt.iterrows():
            code = str(row['代码']).zfill(6)
            print(f"     {code} {row['名称']}: {row['首次封板时间']}")
    
    # 5. 对比同花顺数据
    print("\n6️⃣ 对比同花顺数据...")
    tonghuashun_codes = ['600475', '603359', '601619', '605398', '600103']  # 从图片中看到的代码
    
    print("   同花顺显示的竞价股票:")
    for code in tonghuashun_codes:
        # 在涨停数据中查找
        zt_match = zt_data[zt_data['代码'].astype(str).str.zfill(6) == code]
        dt_match = dt_data[dt_data['代码'].astype(str).str.zfill(6) == code]
        
        if not zt_match.empty:
            row = zt_match.iloc[0]
            print(f"     {code} {row['名称']} (涨停): {row.get('首次封板时间', 'N/A')}")
        elif not dt_match.empty:
            row = dt_match.iloc[0]
            print(f"     {code} {row['名称']} (跌停): {row.get('首次封板时间', 'N/A')}")
        else:
            print(f"     {code}: 未找到数据")
    
    # 6. 分析差异原因
    print("\n7️⃣ 差异分析...")
    print(f"   同花顺: 涨停4只, 跌停1只 = 总计5只")
    print(f"   当前逻辑: 涨停{len(current_logic_zt)}只, 跌停{len(current_logic_dt)}只 = 总计{len(current_logic_zt) + len(current_logic_dt)}只")
    print(f"   时间范围逻辑: 涨停{len(range_logic_zt)}只, 跌停{len(range_logic_dt)}只 = 总计{len(range_logic_zt) + len(range_logic_dt)}只")
    
    # 7. 保存详细数据用于分析
    print("\n8️⃣ 保存详细数据...")
    
    # 保存所有涨停数据的首次封板时间
    if not zt_data.empty:
        analysis_data = zt_data[['代码', '名称', '首次封板时间', '封板资金']].copy()
        analysis_data['代码'] = analysis_data['代码'].astype(str).str.zfill(6)
        analysis_data = analysis_data.sort_values('封板资金', ascending=False)
        
        output_file = f'tests/auction_analysis_{test_date}_zt.csv'
        analysis_data.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"   涨停详细数据已保存: {output_file}")
    
    if not dt_data.empty:
        print(f"   跌停数据字段: {list(dt_data.columns)}")
        # 检查跌停数据有哪些字段
        available_cols = ['代码', '名称']
        for col in ['首次封板时间', '封板资金', '封单额', '封板金额']:
            if col in dt_data.columns:
                available_cols.append(col)

        analysis_data = dt_data[available_cols].copy()
        analysis_data['代码'] = analysis_data['代码'].astype(str).str.zfill(6)

        output_file = f'tests/auction_analysis_{test_date}_dt.csv'
        analysis_data.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"   跌停详细数据已保存: {output_file}")
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！请查看上述分析结果。")
    print("=" * 60)


if __name__ == "__main__":
    test_auction_data_accuracy()
