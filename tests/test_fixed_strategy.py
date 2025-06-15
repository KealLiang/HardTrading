import backtrader as bt
import pandas as pd
import numpy as np
import os
import sys
from tests.talib_pattern_fixed import TALibPatternStrategy

# 定义命令行参数解析
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description='测试修复版K线形态识别策略')
    
    parser.add_argument('--data', '-d',
                        default='data/159949.csv',
                        help='数据文件路径')
    
    parser.add_argument('--window', '-w',
                        type=int, default=20,
                        help='形态识别窗口大小')
    
    parser.add_argument('--penetration', '-p',
                        type=float, default=0.0,
                        help='星形态渗透率参数')
    
    parser.add_argument('--cash', '-c',
                        type=float, default=100000.0,
                        help='初始资金')
    
    return parser.parse_args()

def load_data(file_path):
    """加载CSV数据文件"""
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        sys.exit(1)
        
    try:
        df = pd.read_csv(file_path)
        print(f"成功加载数据: {file_path}")
        print(f"数据行数: {len(df)}")
        
        # 检查必要的列
        required_cols = ['open', 'high', 'low', 'close']
        
        # 处理列名大小写不一致的问题
        df.columns = [col.lower() for col in df.columns]
        
        # 检查列是否存在
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"数据文件缺少必要的列: {missing_cols}")
            sys.exit(1)
        
        # 处理日期列
        if 'date' in df.columns:
            date_col = 'date'
        elif 'datetime' in df.columns:
            date_col = 'datetime'
        elif 'time' in df.columns:
            date_col = 'time'
        elif 'trade_date' in df.columns:
            date_col = 'trade_date'
            # 创建真正的日期字段
            try:
                # 如果是数值类型，尝试转换
                if isinstance(df[date_col].iloc[0], (int, np.int64)) or (isinstance(df[date_col].iloc[0], str) and df[date_col].iloc[0].isdigit()):
                    df['date'] = pd.to_datetime(df[date_col], format='%Y%m%d')
                    date_col = 'date'
                    print("转换数值日期为datetime格式")
            except Exception as e:
                print(f"日期转换错误: {str(e)}")
                # 创建一个简单的日期序列
                print("使用索引创建日期列")
                df['date'] = pd.date_range(start='2020-01-01', periods=len(df))
                date_col = 'date'
        else:
            print("警告: 未找到日期列，将使用行索引作为日期")
            df['date'] = pd.date_range(start='2020-01-01', periods=len(df))
            date_col = 'date'
        
        # 确保数据按日期排序
        df = df.sort_values(date_col)
        
        return df, date_col
    except Exception as e:
        print(f"加载数据时出错: {str(e)}")
        sys.exit(1)

def prepare_backtrader_data(df, date_column):
    """准备Backtrader可用的数据"""
    # 创建一个数据Feed
    data = bt.feeds.PandasData(
        dataname=df,
        datetime=date_column,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='vol' if 'vol' in df.columns else 'volume' if 'volume' in df.columns else None,
        openinterest=None,
        plot=True
    )
    
    return data

def run_backtest(args):
    """运行回测"""
    # 创建Cerebro引擎
    cerebro = bt.Cerebro()
    
    # 加载数据
    df, date_col = load_data(args.data)
    data = prepare_backtrader_data(df, date_col)
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(
        TALibPatternStrategy, 
        window_size=args.window, 
        penetration=args.penetration
    )
    
    # 设置初始资金
    cerebro.broker.setcash(args.cash)
    
    # 设置手续费，默认为千分之二
    cerebro.broker.setcommission(commission=0.002)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.DrawDown)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio)
    
    # 输出初始资金
    print('初始资金: %.2f' % cerebro.broker.getvalue())
    
    # 运行回测
    result = cerebro.run()
    
    # 输出回测结果
    print('回测结束后资金: %.2f' % cerebro.broker.getvalue())
    
    # 计算其他指标
    strategy = result[0]
    
    # 计算最大回撤
    strat_drawdown = strategy.analyzers.drawdown.get_analysis()
    max_drawdown = strat_drawdown.get('max', {}).get('drawdown', 0)
    print(f'最大回撤: {max_drawdown:.2%}')
    
    # 计算夏普比率
    strat_sharpe = strategy.analyzers.sharperatio.get_analysis()
    sharpe_ratio = strat_sharpe.get('sharperatio', 0)
    print(f'夏普比率: {sharpe_ratio:.2f}')
    
    # 计算年化收益率
    initial_value = args.cash
    final_value = cerebro.broker.getvalue()
    total_return = (final_value / initial_value) - 1
    
    # 假设回测时间为整个数据集的时间跨度
    if isinstance(df[date_col].iloc[0], pd.Timestamp):
        start_date = df[date_col].iloc[0]
        end_date = df[date_col].iloc[-1]
    else:
        # 使用日期索引
        days = len(df)
        years = days / 252  # 假设一年约有252个交易日
        print(f"数据包含大约 {years:.2f} 年的交易日")
        annual_return = ((1 + total_return) ** (1 / max(years, 1))) - 1
        print(f'年化收益率: {annual_return:.2%}')
        return result
    
    years = (end_date - start_date).days / 365.25
    if years > 0:
        annual_return = ((1 + total_return) ** (1 / years)) - 1
        print(f'年化收益率: {annual_return:.2%}')
    
    return result

if __name__ == '__main__':
    # 解析命令行参数
    args = parse_args()
    
    # 运行回测
    run_backtest(args) 