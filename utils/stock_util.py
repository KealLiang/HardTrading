def stock_limit_ratio(stock_code):
    """计算涨跌停系数"""
    if stock_code.startswith(('0', '3', '6')):
        limit_ratio = 0.1
    elif stock_code.startswith('688'):
        limit_ratio = 0.2
    elif stock_code.startswith('300'):
        limit_ratio = 0.2
    else:
        raise ValueError(f"未知的股票代码: {stock_code}")
    return limit_ratio