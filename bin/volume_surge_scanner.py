import os
from datetime import datetime
from typing import Optional

import pandas as pd
from tqdm import tqdm

from utils.stock_util import stock_limit_ratio, format_stock_code

# --- 可配置参数 ---
DATA_DIR = './data/astocks'  # 股票数据目录
OUTPUT_FILE = './bin/candidate_temp/candidate_stocks_volume_surge.txt'  # 候选股输出文件
MIN_DATA_LEN = 30  # 股票需要的最少交易日数据
LOOKBACK_DAYS = 30  # 回看周期（最近30个交易日）
MAX_RECENT_CROSS_DAYS = 5  # 最近一次金叉必须在5天内
MIN_CROSS_COUNT = 2  # 至少需要2次金叉
VOLUME_PERIOD_DAYS = 5  # 成交量周期天数（默认5个交易日为一个周期）
VOLUME_SURGE_RATIO = 2.0  # 成交量放大倍率（最近一个周期相较上一个周期，总成交量要放大N倍）


def read_stock_data(file_path):
    """
    读取单个股票的CSV文件。
    参考自 resilience_scanner.py, 格式保持一致。
    """
    try:
        column_names = [
            'date', 'code', 'open', 'close', 'high', 'low', 'volume',
            'amount', 'amplitude', 'pct_chg', 'turnover', 'pe_ratio'
        ]
        df = pd.read_csv(
            file_path,
            header=None,
            names=column_names,
            index_col='date',
            parse_dates=True
        )
        # 确保索引是tz-naive，以避免比较问题
        df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        return None


def filter_data_by_date(df: pd.DataFrame, base_date: pd.Timestamp) -> pd.DataFrame:
    """
    过滤数据，只保留基准日之前（含当日）的数据。
    
    Args:
        df: 股票数据DataFrame
        base_date: 基准日期（Timestamp）
    
    Returns:
        过滤后的DataFrame
    """
    return df[df.index <= base_date].copy()


def check_price_stability(df: pd.DataFrame, stock_code: str, lookback_days: int = LOOKBACK_DAYS) -> bool:
    """
    检查最近N个交易日股价是否平稳。
    条件：振幅小于股票涨跌幅限制的2倍。
    
    Args:
        df: 股票数据DataFrame（已按日期排序，最新的在最后）
        stock_code: 股票代码
        lookback_days: 回看天数
    
    Returns:
        bool: 是否满足平稳条件
    """
    if len(df) < lookback_days:
        return False
    
    # 获取最近N个交易日的数据
    recent_data = df.tail(lookback_days)
    
    # 获取涨跌幅限制
    try:
        limit_ratio = stock_limit_ratio(stock_code)
    except ValueError:
        # 如果无法确定涨跌幅限制，默认使用10%
        limit_ratio = 0.1
    
    # 计算最大振幅（最高价和最低价的差值相对于最低价的比例）
    max_high = recent_data['high'].max()
    min_low = recent_data['low'].min()
    
    if min_low <= 0:
        return False
    
    amplitude_ratio = (max_high - min_low) / min_low
    
    # 振幅必须小于涨跌幅限制的2倍
    max_allowed_amplitude = limit_ratio * 2
    
    return amplitude_ratio < max_allowed_amplitude


def detect_volume_crosses(df: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS, 
                          max_recent_days: int = MAX_RECENT_CROSS_DAYS,
                          min_cross_count: int = MIN_CROSS_COUNT) -> tuple[bool, list]:
    """
    检测成交量的5日均线和10日均线的金叉情况。
    严格金叉：5日线上穿10日线，且次日确认（5日均线 > 10日均线）。
    
    Args:
        df: 股票数据DataFrame（已按日期排序，最新的在最后）
        lookback_days: 回看天数
        max_recent_days: 最近一次金叉必须在N天内
        min_cross_count: 至少需要N次金叉
    
    Returns:
        tuple: (是否满足条件, 金叉日期列表)
    """
    if len(df) < lookback_days:
        return False, []
    
    # 获取最近N个交易日的数据
    recent_data = df.tail(lookback_days).copy()
    
    # 计算5日和10日成交量均线
    recent_data['vol_ma5'] = recent_data['volume'].rolling(window=5).mean()
    recent_data['vol_ma10'] = recent_data['volume'].rolling(window=10).mean()
    
    # 删除因计算均线产生的NaN行
    recent_data = recent_data.dropna()
    
    if len(recent_data) < 2:
        return False, []
    
    # 检测金叉
    crosses = []
    
    # 从第2行开始检查（因为需要前一天的数据来判断是否上穿）
    for i in range(1, len(recent_data)):
        prev_ma5 = recent_data['vol_ma5'].iloc[i-1]
        prev_ma10 = recent_data['vol_ma10'].iloc[i-1]
        curr_ma5 = recent_data['vol_ma5'].iloc[i]
        curr_ma10 = recent_data['vol_ma10'].iloc[i]
        
        # 严格金叉：前一天5日线 < 10日线，当天5日线 > 10日线（上穿）
        # 且次日（如果存在）确认：5日均线 > 10日均线（确认金叉有效，不是碰一下）
        if prev_ma5 < prev_ma10 and curr_ma5 > curr_ma10:
            # 检查次日确认（如果存在）
            if i + 1 < len(recent_data):
                next_ma5 = recent_data['vol_ma5'].iloc[i+1]
                next_ma10 = recent_data['vol_ma10'].iloc[i+1]
                # 次日5日均线必须仍然大于10日均线，才算严格金叉（确认不是碰一下）
                if next_ma5 > next_ma10:
                    cross_date = recent_data.index[i]
                    crosses.append(cross_date)
            else:
                # 如果是最后一天（基准日），且当天满足上穿条件，也算金叉
                # 但这种情况无法确认次日，所以需要更严格的条件：当天5日线明显大于10日线
                if curr_ma5 > curr_ma10 * 1.01:  # 至少高出1%才算有效
                    cross_date = recent_data.index[i]
                    crosses.append(cross_date)
    
    if len(crosses) < min_cross_count:
        return False, crosses
    
    # 检查最近一次金叉是否在max_recent_days天内
    if not crosses:
        return False, crosses
    
    # 获取基准日期（数据的最后一天）
    base_date = recent_data.index[-1]
    
    # 最近一次金叉的日期
    latest_cross = crosses[-1]
    
    # 计算最近一次金叉距离基准日的天数
    # 需要计算实际交易日数（不是自然日）
    cross_idx = recent_data.index.get_loc(latest_cross)
    base_idx = len(recent_data) - 1
    trading_days_ago = base_idx - cross_idx
    
    if trading_days_ago > max_recent_days:
        return False, crosses
    
    return True, crosses


def check_volume_surge(df: pd.DataFrame, period_days: int = VOLUME_PERIOD_DAYS, 
                       surge_ratio: float = VOLUME_SURGE_RATIO) -> bool:
    """
    检查最近一个周期相较上一个周期，总成交量是否明显放大。
    
    Args:
        df: 股票数据DataFrame（已按日期排序，最新的在最后）
        period_days: 周期天数（默认5个交易日为一个周期）
        surge_ratio: 成交量放大倍率（最近一个周期相较上一个周期，总成交量要放大N倍）
    
    Returns:
        bool: 是否满足成交量放大条件
    """
    # 至少需要2个完整周期的数据
    min_required = period_days * 2
    if len(df) < min_required:
        return False
    
    # 最近一个周期：最后period_days个交易日的成交量总和
    recent_period_volume = df['volume'].iloc[-period_days:].sum()
    
    # 上一个周期：前一个period_days周期的成交量总和
    prev_period_volume = df['volume'].iloc[-period_days*2:-period_days].sum()
    
    if prev_period_volume <= 0:
        return False
    
    # 计算成交量放大倍率
    volume_ratio = recent_period_volume / prev_period_volume
    
    # 最近一个周期相较上一个周期，总成交量要放大surge_ratio倍
    return volume_ratio >= surge_ratio


def analyze_stock(df: pd.DataFrame, code: str, base_date: Optional[pd.Timestamp] = None):
    """
    对单个股票的DataFrame应用成交量金叉扫描逻辑。
    
    Args:
        df: 股票数据DataFrame
        code: 股票代码
        base_date: 基准日期（Timestamp），如果为None则使用数据的最新日期
    
    Returns:
        tuple: (是否满足条件, 原因说明)
    """
    # 格式化股票代码
    code = format_stock_code(code)
    
    # 如果没有指定基准日期，使用数据的最新日期
    if base_date is None:
        base_date = df.index.max()
    
    # 过滤数据，只使用基准日之前（含当日）的数据
    df_filtered = filter_data_by_date(df, base_date)
    
    if len(df_filtered) < MIN_DATA_LEN:
        return False, f"数据不足 (少于 {MIN_DATA_LEN} 天)"
    
    # 按日期排序（从早到晚）
    df_filtered = df_filtered.sort_index()
    
    # 条件1：检查股价平稳性
    if not check_price_stability(df_filtered, code, LOOKBACK_DAYS):
        return False, "最近30个交易日股价波动过大"
    
    # 条件2：检查成交量金叉
    has_crosses, cross_dates = detect_volume_crosses(
        df_filtered, 
        LOOKBACK_DAYS, 
        MAX_RECENT_CROSS_DAYS,
        MIN_CROSS_COUNT
    )
    
    if not has_crosses:
        if len(cross_dates) < MIN_CROSS_COUNT:
            return False, f"金叉次数不足 (仅{len(cross_dates)}次，需要{MIN_CROSS_COUNT}次)"
        else:
            return False, "最近一次金叉不在5天内"
    
    # 条件3：检查成交量放大
    if not check_volume_surge(df_filtered, VOLUME_PERIOD_DAYS, VOLUME_SURGE_RATIO):
        return False, f"成交量放大不足 (最近{VOLUME_PERIOD_DAYS}日周期相较上一个周期，未达到{VOLUME_SURGE_RATIO}倍)"
    
    # 所有检查通过
    cross_dates_str = [d.strftime('%Y-%m-%d') for d in cross_dates]
    return True, f"符合条件 (金叉日期: {', '.join(cross_dates_str)})"


def run_filter(base_date: Optional[str] = None):
    """
    主函数，执行扫描并输出结果。
    
    Args:
        base_date: 基准日期，格式为 'YYYYMMDD' 或 'YYYY-MM-DD'，如果为None则使用今天
    """
    if not os.path.exists(DATA_DIR):
        print(f"错误: 数据目录 '{DATA_DIR}' 不存在。")
        return
    
    # 解析基准日期
    if base_date is None:
        base_date_dt = pd.Timestamp.now().normalize()
    else:
        # 支持 'YYYYMMDD' 和 'YYYY-MM-DD' 两种格式
        if len(base_date) == 8 and base_date.isdigit():
            base_date_dt = pd.Timestamp(f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:8]}")
        else:
            base_date_dt = pd.Timestamp(base_date).normalize()
    
    print(f"基准日期: {base_date_dt.strftime('%Y-%m-%d')}")
    print(f"开始扫描股票数据目录: {DATA_DIR}")
    
    stock_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if not stock_files:
        print(f"错误: 数据目录 '{DATA_DIR}' 中没有找到CSV文件。")
        return
    
    print(f"共找到 {len(stock_files)} 只股票的数据文件")
    candidate_stocks = []
    
    # 使用tqdm来显示进度条
    for filename in tqdm(stock_files, desc="扫描进度"):
        code = filename.split('_')[0]
        file_path = os.path.join(DATA_DIR, filename)
        
        df = read_stock_data(file_path)
        if df is None:
            continue
        
        is_candidate, reason = analyze_stock(df.copy(), code, base_date_dt)
        if is_candidate:
            candidate_stocks.append(code)
            tqdm.write(f"  [+] 发现候选股: {code} - {reason}")
    
    print("\n" + "=" * 50)
    print(f"扫描完成！发现 {len(candidate_stocks)} 只候选股票。")
    print("=" * 50)
    
    if candidate_stocks:
        # 确保输出目录存在
        output_dir = os.path.dirname(OUTPUT_FILE)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for code in candidate_stocks:
                f.write(code + '\n')
        print(f"候选股列表已保存到: {OUTPUT_FILE}")
    else:
        print("未发现符合条件的候选股。")


if __name__ == '__main__':
    import sys
    
    # 支持命令行参数传入基准日期
    if len(sys.argv) > 1:
        base_date = sys.argv[1]
        run_filter(base_date=base_date)
    else:
        run_filter()

