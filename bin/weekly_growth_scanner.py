import os

import pandas as pd
from tqdm import tqdm

from utils.stock_util import stock_limit_ratio

# --- Config ---
DATA_DIR = './data/astocks'
OUTPUT_FILE = './bin/candidate_stocks_weekly_growth.txt'
MIN_DATA_LEN = 30  # 至少要有基本数据


def read_stock_data(file_path):
	"""
	读取单个股票的CSV文件，列格式与 `bin/resilience_scanner.py` 保持一致。
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
		# 确保索引 tz-naive
		df.index = df.index.tz_localize(None)
		return df
	except Exception:
		return None


def _is_st_filename(filename: str) -> bool:
	"""根据文件名判断是否ST，文件名形如: 600000_浦发银行.csv"""
	try:
		name_part = os.path.splitext(filename)[0].split('_', 1)[1]
		return 'ST' in name_part.upper()
	except Exception:
		return False


def _passes_weekly_volume_growth(df: pd.DataFrame) -> bool:
	"""自然周(周日为周终)维度计算周成交量，最近一周较上一周增长>100%"""
	weekly_volume = df['volume'].resample('W-SUN').sum()
	if len(weekly_volume) < 2:
		return False
	last_week_volume = weekly_volume.iloc[-1]
	prev_week_volume = weekly_volume.iloc[-2]
	if prev_week_volume <= 0:
		return False
	growth_rate = (last_week_volume - prev_week_volume) / prev_week_volume
	return growth_rate > 1.0


def _passes_three_month_return(df: pd.DataFrame) -> bool:
	"""近3个月区间涨跌幅 < 40.1%"""
	if len(df) < 2:
		return False
	last_date = df.index[-1]
	start_date = last_date - pd.DateOffset(months=3)
	sub_df = df.loc[df.index >= start_date]
	if len(sub_df) < 2:
		return False
	start_close = sub_df['close'].iloc[0]
	end_close = sub_df['close'].iloc[-1]
	if start_close <= 0:
		return False
	interval_return = (end_close / start_close) - 1.0
	return interval_return < 0.401


def _passes_today_constraints(df: pd.DataFrame, code: str) -> bool:
	"""
	今日未涨停，且 当前价>前收 且 涨幅<4.5%
	涨停价按A股规则四舍五入到两位小数: round(prev_close * (1+limit_ratio), 2)
	"""
	if len(df) < 2:
		return False
	prev_close = float(df['close'].iloc[-2])
	today_close = float(df['close'].iloc[-1])
	limit_ratio = float(stock_limit_ratio(code))
	limit_up_price = round(prev_close * (1.0 + limit_ratio), 2)
	# 今日未涨停: 收盘价严格小于涨停价
	if not (today_close < limit_up_price):
		return False
	# 当前价>前日收盘价 且 涨幅<4.5%
	if today_close <= prev_close:
		return False
	pct_change = (today_close - prev_close) / prev_close
	return pct_change < 0.045


def analyze_stock(df: pd.DataFrame, code: str) -> tuple[bool, str]:
	"""按新规则筛选股票。"""
	if len(df) < MIN_DATA_LEN:
		return False, '数据不足'
	# 条件1: 周成交量环比增长>100%
	if not _passes_weekly_volume_growth(df):
		return False, '周成交量环比未>100%'
	# 条件2: 近3个月区间涨跌幅<40.1%
	if not _passes_three_month_return(df):
		return False, '近3个月涨跌幅不满足'
	# 条件3: 今日未涨停 + 涨幅<4.5% 且 >0
	if not _passes_today_constraints(df, code):
		return False, '当日价格/涨停条件不满足'
	return True, '通过周量增+三月涨幅+当日条件筛选'


def run_filter():
	"""扫描并输出候选股到 OUTPUT_FILE。"""
	if not os.path.exists(DATA_DIR):
		print(f"错误: 数据目录 '{DATA_DIR}' 不存在。")
		return

	stock_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
	if not stock_files:
		print(f"错误: 数据目录 '{DATA_DIR}' 中没有找到CSV文件。")
		return

	print(f"开始扫描 {len(stock_files)} 只股票...")
	candidate_stocks: list[str] = []

	for filename in tqdm(stock_files, desc='扫描进度'):
		# 非ST股
		if _is_st_filename(filename):
			continue

		code = filename.split('_')[0]
		file_path = os.path.join(DATA_DIR, filename)
		df = read_stock_data(file_path)
		if df is None or df.empty:
			continue

		is_candidate, reason = analyze_stock(df.copy(), code)
		if is_candidate:
			candidate_stocks.append(code)
			tqdm.write(f"  [+] 候选: {code} - {reason}")

	print("\n" + "=" * 50)
	print(f"扫描完成！发现 {len(candidate_stocks)} 只候选股票。")
	print("=" * 50)

	if candidate_stocks:
		output_dir = os.path.dirname(OUTPUT_FILE)
		if not os.path.exists(output_dir):
			os.makedirs(output_dir)
		with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
			for code in candidate_stocks:
				f.write(code + '\n')
		print(f"候选股列表已保存到: {OUTPUT_FILE}")
	else:
		print('未发现符合条件的候选股。')


if __name__ == '__main__':
	run_filter() 