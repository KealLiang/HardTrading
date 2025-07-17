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


# === 策略组件 (积木) ===

def check_background_trend(data, params):
    """1.1 趋势背景: MA60 > MA200"""
    if data['last_row']['ma60'] < data['last_row']['ma200']:
        return False, "趋势背景不符 (MA60 < MA200)"
    return True, "趋势向好"


def check_liquidity(data, params):
    """1.2 流动性: 近20日均成交额"""
    if data['last_row']['avg_amount_20'] < params['MIN_AVG_AMOUNT']:
        return False, f"流动性不足 (< {params['MIN_AVG_AMOUNT'] / 1_000_000:.0f}M)"
    return True, "流动性充足"


def check_squat_action(data, params):
    """2.1 发生过“跌破”事件: 近期收盘价曾低于MA60"""
    recent_data = data['df'].tail(params['SQUAT_LOOKBACK_DAYS'])
    dip_occurred = (recent_data['close'] < recent_data['ma60']).any()
    if not dip_occurred:
        return False, f"近期({params['SQUAT_LOOKBACK_DAYS']}天)无深蹲洗盘"
    return True, "近期有深蹲洗盘"


def check_strong_support(data, params):
    """(新) 强势支撑: 近期收盘价未曾低于MA60"""
    recent_data = data['df'].tail(params['SQUAT_LOOKBACK_DAYS'])
    dip_occurred = (recent_data['close'] < recent_data['ma60']).any()
    if dip_occurred:
        return False, f"近期({params['SQUAT_LOOKBACK_DAYS']}天)跌破过MA60"
    return True, "形态保持强势"


def check_recovery(data, params):
    """3.1 价格收复: 当前收盘价必须重新站上MA60"""
    if data['last_row']['close'] < data['last_row']['ma60']:
        return False, "当前价格仍在MA60下方"
    return True, "已站上MA60"


def check_short_term_trend(data, params):
    """3.2 短期趋势跟进 (MA10上穿MA20，且MA10拐头向上)"""
    if data['last_row']['ma10'] < data['last_row']['ma20']:
        return False, "短期趋势未转好 (MA10 < MA20)"
    if data['last_row']['ma10'] < data['df']['ma10'].iloc[-params['MA10_SLOPE_DAYS']]:
        return False, f"短期趋势未转好 (MA10在{params['MA10_SLOPE_DAYS']}日内未上升)"
    return True, "短期趋势已转好"


def check_launchpad_volatility(data, params):
    """4.1 横盘蓄势: 近期振幅较低"""
    launchpad_window = data['df'].tail(params['LAUNCHPAD_VOLATILITY_DAYS'])
    recent_high = launchpad_window['high'].max()
    recent_low = launchpad_window['low'].min()
    volatility = (recent_high - recent_low) / recent_low
    if volatility > params['MAX_LAUNCHPAD_VOLATILITY']:
        return False, f"近期({params['LAUNCHPAD_VOLATILITY_DAYS']}天)振幅过大 (>{volatility:.1%})"
    return True, "近期振幅收缩"


def check_volume_contraction(data, params):
    """4.2 量能收缩: 近5日均量低于20日均量"""
    if data['last_row']['vol_ma5'] > data['last_row']['vol_ma20']:
        return False, "近期量能未收缩 (5日均量 > 20日均量)"
    return True, "近期量能收缩"


# === 策略定义 ===

STRATEGIES = {
    "浴火重生": [
        check_background_trend,
        check_liquidity,
        check_squat_action,  # 必须经历洗盘
        check_recovery,  # 必须完成收复
        check_short_term_trend,
        check_launchpad_volatility,
        check_volume_contraction,
    ],
    "强势平台": [
        check_background_trend,
        check_liquidity,
        check_strong_support,  # 必须未跌破支撑
        check_short_term_trend,
        check_launchpad_volatility,
        check_volume_contraction,
    ]
}

# 将所有可配置参数打包，方便传递
SCANNER_PARAMS = {
    "MIN_AVG_AMOUNT": MIN_AVG_AMOUNT,
    "SQUAT_LOOKBACK_DAYS": SQUAT_LOOKBACK_DAYS,
    "MA10_SLOPE_DAYS": MA10_SLOPE_DAYS,
    "LAUNCHPAD_VOLATILITY_DAYS": LAUNCHPAD_VOLATILITY_DAYS,
    "MAX_LAUNCHPAD_VOLATILITY": MAX_LAUNCHPAD_VOLATILITY,
}


def analyze_stock_with_strategies(df, code):
    """
    对单个股票应用所有已定义的策略。
    """
    # --- 健康检查 ---
    if len(df) < MIN_DATA_LEN:
        return None, f"数据不足 (少于 {MIN_DATA_LEN} 天)"

    # --- 计算所有需要的指标 ---
    df['ma10'] = df['close'].rolling(window=10).mean()
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma60'] = df['close'].rolling(window=60).mean()
    df['ma200'] = df['close'].rolling(window=200).mean()
    df['avg_amount_20'] = df['amount'].rolling(window=20).mean()
    df['vol_ma5'] = df['volume'].rolling(window=5).mean()
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()

    df.dropna(inplace=True)
    if df.empty:
        return None, "数据不足 (计算指标后为空)"

    # 将数据打包，方便传递给检查函数
    data_packet = {
        'df': df,
        'last_row': df.iloc[-1]
    }

    # --- 依次应用每个策略 ---
    for name, strategy_checks in STRATEGIES.items():
        is_candidate = True
        fail_reason = ""
        for check_func in strategy_checks:
            passed, reason = check_func(data_packet, SCANNER_PARAMS)
            if not passed:
                is_candidate = False
                fail_reason = reason  # 可以记录最后失败的原因，但当前逻辑下不需要
                break  # 当前策略失败，跳出检查循环

        if is_candidate:
            return name, f"符合「{name}」模型"

    # 所有策略都未通过
    return None, "不符合任何已定义策略"


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
            continue

        strategy_name, reason = analyze_stock_with_strategies(df.copy(), code)
        if strategy_name:
            # 只存储股票代码，以保持输出格式兼容性
            candidate_stocks.append(code)
            tqdm.write(f"  [+] 发现候选股: {code} - 模型: {strategy_name}")

    print("\n" + "=" * 50)
    # 使用set去重并排序，保证输出一致性
    unique_candidates = sorted(list(set(candidate_stocks)))
    print(f"扫描完成！发现 {len(unique_candidates)} 只候选股票。")
    print("=" * 50)

    if unique_candidates:
        # 确保输出目录存在
        output_dir = os.path.dirname(OUTPUT_FILE)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 恢复为写入TXT文件的原始逻辑
        with open(OUTPUT_FILE, 'w') as f:
            for code in unique_candidates:
                f.write(code + '\n')
        print(f"候选股列表已保存到: {OUTPUT_FILE}")
    else:
        print("未发现符合条件的候选股。")


if __name__ == '__main__':
    run_filter()
