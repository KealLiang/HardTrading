"""
测试异动检测器功能
"""

from analysis.abnormal_movement_detector import AbnormalMovementDetector
from datetime import datetime


def test_abnormal_movement_detector():
    """测试异动检测器"""
    
    print("=== 异动检测器测试 ===")
    
    # 创建检测器实例
    detector = AbnormalMovementDetector()
    
    # 测试股票列表（选择一些活跃的股票）
    test_stocks = [
        '000001',  # 平安银行
        '000002',  # 万科A
        '300001',  # 特锐德（创业板）
        '688001',  # 华兴源创（科创板）
    ]
    
    # 测试日期（使用最近的交易日）
    test_date = '2025-09-05'  # 可以根据实际情况调整
    
    print(f"测试日期: {test_date}")
    print("-" * 60)
    
    for stock_code in test_stocks:
        print(f"\n测试股票: {stock_code}")
        
        try:
            # 测试偏离值计算
            deviation_3d = detector.calculate_deviation_values(stock_code, test_date, 3)
            deviation_10d = detector.calculate_deviation_values(stock_code, test_date, 10)
            deviation_30d = detector.calculate_deviation_values(stock_code, test_date, 30)
            
            print(f"  3日偏离值: {deviation_3d}")
            print(f"  10日偏离值累计: {sum(deviation_10d) if deviation_10d else 0:.2f}%")
            print(f"  30日偏离值累计: {sum(deviation_30d) if deviation_30d else 0:.2f}%")
            
            # 测试换手率计算
            turnover_3d = detector.calculate_turnover_ratios(stock_code, test_date, 3)
            print(f"  3日换手率: {turnover_3d}")
            
            # 测试异动检测
            is_abnormal, abnormal_type, abnormal_detail = detector.check_abnormal_movement(stock_code, test_date)
            print(f"  异常波动: {is_abnormal}")
            if is_abnormal:
                print(f"    类型: {abnormal_type}")
                print(f"    详情: {abnormal_detail}")
            
            # 测试严重异动检测
            is_severe, severe_type, severe_detail = detector.check_severe_abnormal_movement(stock_code, test_date)
            print(f"  严重异常波动: {is_severe}")
            if is_severe:
                print(f"    类型: {severe_type}")
                print(f"    详情: {severe_detail}")
            
            # 测试预警信息
            warning = detector.get_warning_message(stock_code, test_date)
            print(f"  预警信息: {warning if warning else '无预警'}")
            
            # 综合分析
            result = detector.analyze_stock(stock_code, test_date)
            print(f"  综合分析: {result['warning_message'] if result['warning_message'] else '正常'}")
            
        except Exception as e:
            print(f"  测试出错: {e}")
        
        print("-" * 40)


def test_specific_stock():
    """测试特定股票的详细情况"""
    
    print("\n=== 特定股票详细测试 ===")
    
    detector = AbnormalMovementDetector()
    
    # 可以指定一个具体的股票和日期进行详细测试
    stock_code = '000001'  # 平安银行
    test_date = '2025-09-05'
    
    print(f"详细测试股票: {stock_code}")
    print(f"测试日期: {test_date}")
    
    try:
        # 获取市场类型
        from utils.stock_util import get_stock_market
        market = get_stock_market(stock_code)
        print(f"市场类型: {market}")
        
        # 获取对应指数数据
        index_df = detector.get_market_index_data(stock_code)
        print(f"指数数据条数: {len(index_df)}")
        
        # 获取股票数据
        stock_df = detector.get_stock_data_cached(stock_code)
        if stock_df is not None:
            print(f"股票数据条数: {len(stock_df)}")
            
            # 显示最近几天的数据
            recent_data = stock_df.tail(5)
            print("最近5天股票数据:")
            for _, row in recent_data.iterrows():
                print(f"  {row['日期'].strftime('%Y-%m-%d')}: 涨跌幅={row['涨跌幅']:.2f}%, 换手率={row['换手率']:.2f}%")
        
        # 显示最近几天的指数数据
        if not index_df.empty:
            recent_index = index_df.tail(5)
            print("最近5天指数数据:")
            for _, row in recent_index.iterrows():
                print(f"  {row['日期'].strftime('%Y-%m-%d')}: 涨跌幅={row['涨跌幅']:.2f}%")
        
        # 详细的偏离值分析
        print("\n偏离值详细分析:")
        for days in [3, 10, 30]:
            deviations = detector.calculate_deviation_values(stock_code, test_date, days)
            if deviations:
                cumulative = sum(deviations)
                print(f"  {days}日偏离值: {deviations}")
                print(f"  {days}日累计偏离值: {cumulative:.2f}%")
            else:
                print(f"  {days}日偏离值: 无数据")
        
    except Exception as e:
        print(f"详细测试出错: {e}")


if __name__ == "__main__":
    # 运行基本测试
    test_abnormal_movement_detector()
    
    # 运行详细测试
    test_specific_stock()
