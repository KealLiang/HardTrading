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


def convert_stock_code(code: str) -> str:
    """
    将股票代码转换为交易所代码格式
    :param code: 股票代码，如'600000'
    :return: 完整的股票代码，如'sh600000'
    """
    if not code.isdigit():  # 检查是否为纯数字
        raise ValueError("股票代码必须是纯数字！")

    if code.startswith('60'):  # 沪市股票代码以60开头
        return f"sh{code}"
    elif code.startswith(('00', '002', '300', '301', '13', '14', '18', '20')):  # 深市股票代码
        return f"sz{code}"
    elif code.startswith('8'):  # 北交所股票代码以8开头
        return f"bj{code}"
    elif code.startswith(('11', '12', '13', '14', '18', '20')):  # 深市债券、可转债等特殊代码
        return f"sz{code}"
    elif code.startswith(('110', '113', '123', '128')):  # 沪市债券、可转债等特殊代码
        return f"sh{code}"
    else:
        raise ValueError("无法识别的股票代码格式！")
