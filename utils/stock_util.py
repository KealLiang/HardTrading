def format_stock_code(code) -> str:
    """
    格式化股票代码为6位字符串，补全前导零
    
    Args:
        code: 股票代码，可以是字符串或数字
    
    Returns:
        str: 6位股票代码字符串，如 '000001', '600000'
    
    Examples:
        >>> format_stock_code(1)
        '000001'
        >>> format_stock_code('1')
        '000001'
        >>> format_stock_code('600000')
        '600000'
        >>> format_stock_code(2424)
        '002424'
    """
    return str(code).zfill(6)


def stock_limit_ratio(stock_code: str) -> float:
    """
    根据股票代码确定其涨跌停限制比例。
    注意：此函数返回常规交易日的涨跌幅限制，不考虑新股上市首日、ST/*ST股等特殊情况。
    :param stock_code: 6位数字的股票代码字符串。
    :return: 涨跌停比例 (例如 0.1 表示 ±10%)。
    """
    if not isinstance(stock_code, str):
        stock_code = str(stock_code)

    market = get_stock_market(stock_code)

    market_ratios = {
        'main': 0.1,
        'star': 0.2,
        'gem': 0.2,
        'bse': 0.3,
    }

    if market in market_ratios:
        return market_ratios[market]
    elif market == 'neeq':
        print(f"【警告】新三板股票({stock_code})不适用常规涨跌停限制。")
        return 1
    else:
        # 对于债券等未明确分类的，默认按主板的10%处理或抛出异常，这里选择抛出异常以更严谨
        raise ValueError(f"无法确定股票代码 {stock_code} 的涨跌停限制。")


def convert_stock_code(code: str) -> str:
    """
    将6位股票代码转换为交易所代码格式。
    :param code: 6位数字的股票代码字符串, 如 '600000'。
    :return: 带交易所前缀的股票代码, 如 'sh600000'。
    """
    if not isinstance(code, str):
        code = str(code)

    # 沪市
    if code.startswith(('60', '68')) or \
            code.startswith(('110', '113', '118')):  # 沪市股票、科创板、部分沪市可转债
        return f"sh{code}"
    # 深市
    elif code.startswith(('00', '30')) or \
            code.startswith(('12', '11', '13')):  # 深市股票、创业板、部分深市可转债/债券
        return f"sz{code}"
    # 北交所 & 新三板
    elif code.startswith(('8', '92', '43', '87')):
        return f"bj{code}"
    else:
        # 尝试根据市场进行二次判断（适用于一些未明确列出的债券等）
        market = get_stock_market(code)
        if market in ['main', 'star']:
            return f"sh{code}"
        elif market == 'gem':
            return f"sz{code}"
        elif market in ['bse', 'neeq']:
            return f"bj{code}"
        raise ValueError(f"无法识别的股票代码格式: {code}")


def get_stock_market(code: str) -> str:
    """
    确定股票所处的市场。
    :param code: 6位数字的股票代码字符串, 如 '600000'。
    :return: 市场类型: 'main'(主板), 'gem'(创业板), 'star'(科创板), 'bse'(北交所), 'neeq'(新三板)。
    """
    if not isinstance(code, str):
        code = str(code)

    # 优先判断特殊板块
    if code.startswith('68'):  # 科创板
        return 'star'
    elif code.startswith('30'):  # 创业板
        return 'gem'
    elif code.startswith(('8', '92')):  # 北交所
        return 'bse'
    elif code.startswith(('43', '83', '87')):  # 新三板
        return 'neeq'
    # 主板
    elif code.startswith('60'):  # 上交所主板
        return 'main'
    elif code.startswith('00'):  # 深交所主板
        return 'main'
    # 债券等其他情况，简单归类为主板处理
    elif code.startswith(('11', '12', '13')):
        return 'main'
    else:
        raise ValueError(f"无法识别的股票代码市场: {code}")
