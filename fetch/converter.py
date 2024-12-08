import pandas as pd


def backtrade_form(name):
    # 读取Tushare数据
    df = pd.read_csv(f'data/{name}.csv')
    # 转换为Backtrader支持的格式
    df['datetime'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')  # 转换日期格式
    df = df.rename(columns={
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'vol': 'volume'
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]  # 保留需要的列
    df = df.sort_values('datetime')  # 按日期排序
    # 保存为新的CSV文件
    df.to_csv(f'data/{name}_bt.csv', index=False)
