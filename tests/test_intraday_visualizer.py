"""
测试日内交易可视化工具
"""
import os
import sys
import pandas as pd
from datetime import datetime, timedelta

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from utils.backtrade.intraday_visualizer import plot_intraday_backtest


def generate_mock_data():
    """生成模拟的1分钟K线数据和信号"""
    # 生成3个交易日的1分钟K线数据
    dates = []
    for day in range(3):
        base_date = datetime(2025, 10, 21) + timedelta(days=day)
        # 上午：09:30-11:30
        for hour in range(9, 12):
            start_min = 30 if hour == 9 else 0
            end_min = 31 if hour == 11 else 60
            for minute in range(start_min, end_min):
                dates.append(base_date.replace(hour=hour, minute=minute))
        # 下午：13:00-15:00
        for hour in range(13, 15):
            for minute in range(0, 60):
                dates.append(base_date.replace(hour=hour, minute=minute))
        # 14:00-15:00的最后一分钟
        dates.append(base_date.replace(hour=15, minute=0))
    
    # 生成模拟价格数据（随机游走）
    import random
    random.seed(42)
    
    base_price = 45.0
    data = []
    for i, dt in enumerate(dates):
        # 随机波动
        change = random.uniform(-0.3, 0.3)
        base_price = max(40.0, min(50.0, base_price + change))
        
        open_price = base_price
        high_price = open_price + random.uniform(0, 0.5)
        low_price = open_price - random.uniform(0, 0.5)
        close_price = random.uniform(low_price, high_price)
        volume = random.randint(1000, 10000)
        
        data.append({
            'datetime': dt,
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2),
            'vol': volume
        })
        
        base_price = close_price
    
    df = pd.DataFrame(data)
    
    # 生成模拟信号
    signals = [
        {
            'type': 'BUY',
            'price': 43.56,
            'time': datetime(2025, 10, 21, 10, 15),
            'reason': '超卖买入(RSI:28.5)',
            'strength': 88
        },
        {
            'type': 'SELL',
            'price': 44.89,
            'time': datetime(2025, 10, 21, 14, 30),
            'reason': '超买卖出(RSI:73.2)',
            'strength': 76
        },
        {
            'type': 'BUY',
            'price': 42.34,
            'time': datetime(2025, 10, 22, 9, 45),
            'reason': '超卖买入(RSI:26.8)',
            'strength': 92
        },
        {
            'type': 'SELL',
            'price': 43.12,
            'time': datetime(2025, 10, 22, 11, 20),
            'reason': '超买卖出(RSI:71.5)',
            'strength': 68
        },
        {
            'type': 'BUY',
            'price': 44.01,
            'time': datetime(2025, 10, 23, 10, 0),
            'reason': '超卖买入(RSI:29.3)',
            'strength': 55
        },
    ]
    
    return df, signals


def test_visualizer():
    """测试可视化工具"""
    print("=" * 60)
    print("开始测试日内交易可视化工具")
    print("=" * 60)
    
    # 生成模拟数据
    print("\n1. 生成模拟数据...")
    df_1m, signals = generate_mock_data()
    print(f"   ✓ 生成了 {len(df_1m)} 根1分钟K线")
    print(f"   ✓ 生成了 {len(signals)} 个信号")
    
    # 调用可视化工具
    print("\n2. 生成可视化图表...")
    output_path = plot_intraday_backtest(
        df_1m=df_1m,
        signals=signals,
        symbol='300852',
        stock_name='鹏辉能源（测试）',
        backtest_start='2025-10-21 09:30',
        backtest_end='2025-10-23 15:00',
        output_dir='tests/test_output'
    )
    
    # 检查结果
    print("\n3. 验证输出...")
    if output_path and os.path.exists(output_path):
        file_size = os.path.getsize(output_path) / 1024  # KB
        print(f"   ✓ 图表生成成功")
        print(f"   ✓ 文件路径: {output_path}")
        print(f"   ✓ 文件大小: {file_size:.1f} KB")
    else:
        print(f"   ✗ 图表生成失败")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == '__main__':
    test_visualizer() 