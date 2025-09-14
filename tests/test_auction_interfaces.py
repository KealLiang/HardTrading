"""
测试集合竞价相关接口数据

详细测试akshare的涨停板和跌停板接口，分析数据结构和特点，
帮助理解接口的局限性和使用方法。

作者：Trading System
创建时间：2025-01-14
"""

import sys
import os
sys.path.append('.')

try:
    import akshare as ak
    import pandas as pd
    from datetime import datetime, timedelta
    print("✅ 成功导入基础库")
except ImportError as e:
    print(f"❌ 导入基础库失败: {e}")
    sys.exit(1)

try:
    from utils.date_util import get_prev_trading_day, is_trading_day
    print("✅ 成功导入日期工具")
except ImportError as e:
    print(f"⚠️  导入日期工具失败，使用简化版本: {e}")

    def get_prev_trading_day(date_str):
        """简化版本的获取前一交易日"""
        from datetime import datetime, timedelta
        date = datetime.strptime(date_str, '%Y%m%d')
        # 简单地减去1-3天来找到可能的交易日
        for i in range(1, 4):
            prev_date = date - timedelta(days=i)
            if prev_date.weekday() < 5:  # 周一到周五
                return prev_date.strftime('%Y%m%d')
        return (date - timedelta(days=1)).strftime('%Y%m%d')

    def is_trading_day(date_str):
        """简化版本的交易日判断"""
        from datetime import datetime
        date = datetime.strptime(date_str, '%Y%m%d')
        return date.weekday() < 5  # 简单判断：周一到周五

import json


def test_zt_pool_interface():
    """测试涨停板接口详细数据"""
    print("=" * 80)
    print("📊 测试涨停板接口 (ak.stock_zt_pool_em)")
    print("=" * 80)
    
    # 获取最近的交易日
    today = datetime.now().strftime('%Y%m%d')
    if not is_trading_day(today):
        trading_day = get_prev_trading_day(today)
    else:
        trading_day = today
    
    print(f"测试日期: {trading_day}")
    
    try:
        # 获取涨停板数据
        zt_data = ak.stock_zt_pool_em(date=trading_day)
        
        print(f"✅ 成功获取数据，共 {len(zt_data)} 只股票")
        print(f"📋 数据列名: {list(zt_data.columns)}")
        
        # 显示数据类型
        print(f"\n📊 数据类型:")
        for col in zt_data.columns:
            print(f"  {col}: {zt_data[col].dtype}")
        
        # 显示前5行完整数据
        print(f"\n📄 前5行完整数据:")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        print(zt_data.head())
        
        # 分析首次封板时间
        print(f"\n⏰ 首次封板时间分析:")
        time_analysis = zt_data['首次封板时间'].value_counts().head(20)
        print(time_analysis)
        
        # 分析竞价阶段数据
        print(f"\n🎯 竞价阶段分析 (092开头的时间):")
        auction_mask = zt_data['首次封板时间'].astype(str).str.startswith('092')
        auction_stocks = zt_data[auction_mask]
        print(f"竞价阶段封板股票数量: {len(auction_stocks)}")
        
        if not auction_stocks.empty:
            print("竞价阶段封板股票详情:")
            for _, row in auction_stocks.iterrows():
                print(f"  {row['代码']} {row['名称']}: 封单 {row['封板资金']:,.0f} 元, 时间 {row['首次封板时间']}")
        
        # 分析封单额分布
        print(f"\n💰 封单额统计:")
        print(f"  最大封单额: {zt_data['封板资金'].max():,.0f} 元")
        print(f"  最小封单额: {zt_data['封板资金'].min():,.0f} 元")
        print(f"  平均封单额: {zt_data['封板资金'].mean():,.0f} 元")
        print(f"  封单额中位数: {zt_data['封板资金'].median():,.0f} 元")
        
        # 保存详细数据用于分析
        output_file = f"temp/zt_data_sample_{trading_day}.csv"
        zt_data.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n💾 详细数据已保存到: {output_file}")
        
        return zt_data
        
    except Exception as e:
        print(f"❌ 涨停板接口测试失败: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()


def test_dt_pool_interface():
    """测试跌停板接口"""
    print("\n" + "=" * 80)
    print("📉 测试跌停板接口")
    print("=" * 80)
    
    # 获取最近的交易日
    today = datetime.now().strftime('%Y%m%d')
    if not is_trading_day(today):
        trading_day = get_prev_trading_day(today)
    else:
        trading_day = today
    
    print(f"测试日期: {trading_day}")
    
    # 尝试不同的跌停板接口
    interfaces_to_test = [
        ('stock_dt_pool_em', 'ak.stock_dt_pool_em'),
        ('stock_zt_pool_dtgc_em', 'ak.stock_zt_pool_dtgc_em'),  # 可能的跌停接口
    ]
    
    for interface_name, interface_desc in interfaces_to_test:
        print(f"\n🔍 测试接口: {interface_desc}")
        try:
            if hasattr(ak, interface_name):
                interface_func = getattr(ak, interface_name)
                dt_data = interface_func(date=trading_day)
                
                if dt_data is not None and not dt_data.empty:
                    print(f"✅ 成功获取数据，共 {len(dt_data)} 只股票")
                    print(f"📋 数据列名: {list(dt_data.columns)}")
                    
                    # 显示前5行
                    print(f"📄 前5行数据:")
                    print(dt_data.head())
                    
                    # 保存数据
                    output_file = f"temp/dt_data_sample_{trading_day}_{interface_name}.csv"
                    dt_data.to_csv(output_file, index=False, encoding='utf-8-sig')
                    print(f"💾 数据已保存到: {output_file}")
                    
                    return dt_data
                else:
                    print(f"⚠️  接口返回空数据")
            else:
                print(f"❌ 接口不存在: {interface_name}")
                
        except Exception as e:
            print(f"❌ 接口 {interface_name} 测试失败: {e}")
    
    # 尝试其他可能的接口
    print(f"\n🔍 尝试查找其他跌停相关接口...")
    ak_functions = [func for func in dir(ak) if 'dt' in func.lower() or 'drop' in func.lower()]
    print(f"可能的跌停相关函数: {ak_functions[:10]}")  # 只显示前10个
    
    return pd.DataFrame()


def test_realtime_vs_historical():
    """测试实时数据与历史数据的差异"""
    print("\n" + "=" * 80)
    print("🕐 测试实时数据与历史数据差异")
    print("=" * 80)
    
    current_time = datetime.now()
    print(f"当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试今天和昨天的数据
    today = current_time.strftime('%Y%m%d')
    yesterday = (current_time - timedelta(days=1)).strftime('%Y%m%d')
    
    for test_date in [today, yesterday]:
        print(f"\n📅 测试日期: {test_date}")
        print(f"是否为交易日: {is_trading_day(test_date)}")
        
        try:
            zt_data = ak.stock_zt_pool_em(date=test_date)
            if not zt_data.empty:
                print(f"  涨停板数量: {len(zt_data)}")
                auction_count = len(zt_data[zt_data['首次封板时间'].astype(str).str.startswith('092')])
                print(f"  竞价阶段封板: {auction_count}")
                print(f"  封单总额: {zt_data['封板资金'].sum():,.0f} 元")
            else:
                print(f"  无涨停板数据")
        except Exception as e:
            print(f"  获取数据失败: {e}")


def test_data_structure_analysis():
    """详细分析数据结构"""
    print("\n" + "=" * 80)
    print("🔬 详细数据结构分析")
    print("=" * 80)
    
    trading_day = get_prev_trading_day(datetime.now().strftime('%Y%m%d'))
    
    try:
        zt_data = ak.stock_zt_pool_em(date=trading_day)
        
        if zt_data.empty:
            print("❌ 无数据可分析")
            return
        
        print(f"📊 数据维度: {zt_data.shape}")
        
        # 分析关键字段
        key_fields = ['代码', '名称', '封板资金', '首次封板时间', '最后封板时间', '炸板次数']
        
        for field in key_fields:
            if field in zt_data.columns:
                print(f"\n🔍 字段分析: {field}")
                print(f"  数据类型: {zt_data[field].dtype}")
                print(f"  非空值数量: {zt_data[field].notna().sum()}")
                print(f"  唯一值数量: {zt_data[field].nunique()}")
                
                if field == '代码':
                    # 分析股票代码格式
                    print(f"  代码示例: {zt_data[field].head().tolist()}")
                    print(f"  代码长度分布: {zt_data[field].astype(str).str.len().value_counts()}")
                
                elif field == '首次封板时间':
                    # 分析时间格式
                    print(f"  时间示例: {zt_data[field].head().tolist()}")
                    print(f"  时间长度分布: {zt_data[field].astype(str).str.len().value_counts()}")
                    
                    # 分析竞价时间段
                    auction_times = zt_data[zt_data[field].astype(str).str.startswith('092')][field]
                    if not auction_times.empty:
                        print(f"  竞价时间段样本: {auction_times.tolist()}")
                
                elif field == '封板资金':
                    # 分析封单额分布
                    print(f"  最大值: {zt_data[field].max():,.0f}")
                    print(f"  最小值: {zt_data[field].min():,.0f}")
                    print(f"  分位数:")
                    for q in [0.25, 0.5, 0.75, 0.9, 0.95]:
                        print(f"    {q*100}%: {zt_data[field].quantile(q):,.0f}")
        
        # 生成数据字典
        data_dict = {
            'date': trading_day,
            'total_stocks': len(zt_data),
            'columns': list(zt_data.columns),
            'data_types': {col: str(zt_data[col].dtype) for col in zt_data.columns},
            'sample_data': zt_data.head(3).to_dict('records'),
            'auction_analysis': {
                'auction_stocks_count': len(zt_data[zt_data['首次封板时间'].astype(str).str.startswith('092')]),
                'auction_times': zt_data[zt_data['首次封板时间'].astype(str).str.startswith('092')]['首次封板时间'].tolist(),
            }
        }
        
        # 保存数据字典
        dict_file = f"temp/data_structure_analysis_{trading_day}.json"
        with open(dict_file, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n💾 数据结构分析已保存到: {dict_file}")
        
    except Exception as e:
        print(f"❌ 数据结构分析失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主测试函数"""
    print("🧪 集合竞价接口详细测试")
    print("=" * 80)
    print("本测试将详细分析akshare相关接口的数据结构和特点")
    print()
    
    # 确保测试目录存在
    os.makedirs('temp', exist_ok=True)
    
    # 1. 测试涨停板接口
    zt_data = test_zt_pool_interface()
    
    # 2. 测试跌停板接口
    dt_data = test_dt_pool_interface()
    
    # 3. 测试实时vs历史数据
    test_realtime_vs_historical()
    
    # 4. 详细数据结构分析
    test_data_structure_analysis()
    
    print("\n" + "=" * 80)
    print("🎯 测试总结")
    print("=" * 80)
    print("✅ 涨停板接口测试完成")
    print("✅ 跌停板接口测试完成")
    print("✅ 数据结构分析完成")
    print("📁 测试结果文件保存在 temp/ 目录下")
    print("\n💡 建议:")
    print("1. 查看生成的CSV文件了解详细数据结构")
    print("2. 查看JSON文件了解数据分析结果")
    print("3. 根据测试结果调整数据采集策略")


if __name__ == "__main__":
    main()
