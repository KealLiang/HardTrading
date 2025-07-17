import os

import pandas as pd
from tqdm import tqdm

# --- 可配置参数 ---
DATA_DIR = './data/astocks'  # 股票数据目录
OUTPUT_FILE = './bin/candidate_stocks_ready.txt'  # 候选股输出文件
MIN_DATA_LEN = 200  # 股票需要的最少交易日数据
# --- 阶段一: 背景筛选 ---
MIN_AVG_AMOUNT = 30_000_000  # 最小20日平均成交额 (3000万)
# --- 阶段二: "深蹲"行为定义 ---
SQUAT_LOOKBACK_DAYS = 30  # "深蹲"行为的回看周期
# --- 阶段三: "重生"确认 ---
MA10_SLOPE_DAYS = 3  # 计算MA10斜率的回看天数
# --- 阶段四: "发射平台"筛选 ---
LAUNCHPAD_VOLATILITY_DAYS = 5  # 计算近期振幅的天数
MAX_LAUNCHPAD_VOLATILITY = 0.15  # 近期最大振幅 (15%)


def read_stock_data(file_path):
    """
    读取单个股票的CSV文件。
    参考自 simulator.py, 格式保持一致。
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
        # 在主循环中捕获并报告错误，这里返回None
        return None


def analyze_stock(df, code):
    """
    对单个股票的DataFrame应用“浴火重生”扫描逻辑。
    """
    # --- 健康检查 ---
    if len(df) < MIN_DATA_LEN:
        return False, f"数据不足 (少于 {MIN_DATA_LEN} 天)"

    # --- 计算所有需要的指标 ---
    df['ma10'] = df['close'].rolling(window=10).mean()
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma60'] = df['close'].rolling(window=60).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()
    df['avg_amount_20'] = df['amount'].rolling(window=20).mean()
    df['vol_ma5'] = df['volume'].rolling(window=5).mean()
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()

    # 删除因计算指标产生的NaN行
    df.dropna(inplace=True)
    if df.empty:
        return False, "数据不足 (计算指标后为空)"

    last_row = df.iloc[-1]

    # === 阶段一: 定义“有资格”的背景 ===
    # 1.1 趋势背景: MA60 > MA200
    if last_row['ma60'] < last_row['ma200']:
        return False, "趋势背景不符 (MA60 < MA200)"
    # 1.2 流动性: 近20日均成交额
    if last_row['avg_amount_20'] < MIN_AVG_AMOUNT:
        return False, f"流动性不足 (日均成交额 < {MIN_AVG_AMOUNT / 1_000_000:.0f}M)"

    # === 阶段二: 捕捉“深蹲”或“洗盘”行为 ===
    recent_data = df.tail(SQUAT_LOOKBACK_DAYS)
    # 2.1 发生过“跌破”事件: 近期收盘价曾低于MA60
    dip_occurred = (recent_data['close'] < recent_data['ma60']).any()
    if not dip_occurred:
        return False, f"近期({SQUAT_LOOKBACK_DAYS}天)未发生跌破MA60的洗盘"

    # === 阶段三: 确认“重生”与“站稳” ===
    # 3.1 价格收复: 当前收盘价必须重新站上MA60
    if last_row['close'] < last_row['ma60']:
        return False, "当前价格仍在MA60下方，未完成收复"
    # 3.2 短期趋势跟进 (MA10上穿MA20，且MA10拐头向上)
    if last_row['ma10'] < last_row['ma20']:
        return False, "短期趋势未转好 (MA10 < MA20)"
    if last_row['ma10'] < df['ma10'].iloc[-MA10_SLOPE_DAYS]:
        return False, f"短期趋势未转好 (MA10在{MA10_SLOPE_DAYS}日内未上升)"

    # === 阶段四: 寻找“发射平台” ===
    # 4.1 横盘蓄势: 近期振幅较低
    launchpad_window = df.tail(LAUNCHPAD_VOLATILITY_DAYS)
    recent_high = launchpad_window['high'].max()
    recent_low = launchpad_window['low'].min()
    volatility = (recent_high - recent_low) / recent_low
    if volatility > MAX_LAUNCHPAD_VOLATILITY:
        return False, f"近期({LAUNCHPAD_VOLATILITY_DAYS}天)振幅过大 (>{volatility:.1%})"
    # 4.2 量能收缩: 近5日均量低于20日均量
    if last_row['vol_ma5'] > last_row['vol_ma20']:
        return False, "近期量能未收缩 (5日均量 > 20日均量)"

    # 所有检查通过，这是一个合格的候选者
    return True, "符合“浴火重生”模型"


def run_filter():
    """
    主函数，执行扫描并输出结果。
    """
    if not os.path.exists(DATA_DIR):
        print(f"错误: 数据目录 '{DATA_DIR}' 不存在。")
        return

    stock_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if not stock_files:
        print(f"错误: 数据目录 '{DATA_DIR}' 中没有找到CSV文件。")
        return

    print(f"开始扫描 {len(stock_files)} 只股票...")
    candidate_stocks = []

    # 使用tqdm来显示进度条
    for filename in tqdm(stock_files, desc="扫描进度"):
        code = filename.split('_')[0]
        file_path = os.path.join(DATA_DIR, filename)

        df = read_stock_data(file_path)
        if df is None:
            # tqdm.write(f"警告: 读取 {code} 数据失败。")
            continue

        is_candidate, reason = analyze_stock(df.copy(), code)  # 使用copy避免后续操作影响
        if is_candidate:
            candidate_stocks.append(code)
            tqdm.write(f"  [+] 发现候选股: {code} - 原因: {reason}")

    print("\n" + "=" * 50)
    print(f"扫描完成！发现 {len(candidate_stocks)} 只候选股票。")
    print("=" * 50)

    if candidate_stocks:
        # 确保输出目录存在
        output_dir = os.path.dirname(OUTPUT_FILE)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(OUTPUT_FILE, 'w') as f:
            for code in candidate_stocks:
                f.write(code + '\n')
        print(f"候选股列表已保存到: {OUTPUT_FILE}")
    else:
        print("未发现符合条件的候选股。")


if __name__ == '__main__':
    run_filter()
