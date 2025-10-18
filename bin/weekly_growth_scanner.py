import os
import shutil

import pandas as pd
from tqdm import tqdm

from utils.stock_util import stock_limit_ratio

# --- Config ---
DATA_DIR = './data/astocks'
OUTPUT_FILE = './bin/candidate_temp/candidate_stocks_weekly_growth.txt'
MIN_DATA_LEN = 30  # 至少要有基本数据
WEEK_WINDOW = 5  # 周期窗口：5个交易日为一周


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
	"""
	以WEEK_WINDOW个交易日为周期计算周成交量环比增长率
	本周=最近WEEK_WINDOW个交易日，上周=前一个WEEK_WINDOW周期
	增长率 > 100%
	"""
	min_required = WEEK_WINDOW * 2  # 至少需要2个完整周期的数据
	if len(df) < min_required:
		return False
	
	# 本周：最近WEEK_WINDOW个交易日的成交量总和
	recent_week_volume = df['volume'].iloc[-WEEK_WINDOW:].sum()
	
	# 上周：前一个WEEK_WINDOW周期的成交量总和
	prev_week_volume = df['volume'].iloc[-WEEK_WINDOW*2:-WEEK_WINDOW].sum()
	
	if prev_week_volume <= 0:
		return False
	
	growth_rate = (recent_week_volume - prev_week_volume) / prev_week_volume
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
	当日(T日)条件检查 - 用于T日收盘后筛选、T+1日买入的场景
	
	检查T日的表现是否符合条件（在T日收盘后，所有数据已知）：
	1. 排除高开5%以上：⚠️ 无法在扫描时实现（需T+1日开盘时判断）
	2. 今日未涨停：T日收盘价 < T日涨停价
	3. 当前价 > 前日收盘价：T日收盘 > T-1日收盘（小幅上涨）
	4. 涨幅 < 4.5%：T日涨幅 < 4.5%（温和上涨，不追高）
	
	策略意图：选择T日表现温和、未涨停的股票，在T+1日买入
	⚠️ 注意：T+1日开盘时需人工/程序判断是否高开5%以上，若是则放弃买入
	涨停价按A股规则四舍五入到两位小数: round(T-1日收盘 * (1+limit_ratio), 2)
	"""
	if len(df) < 2:
		return False
	prev_close = float(df['close'].iloc[-2])  # T-1日收盘价
	today_close = float(df['close'].iloc[-1])  # T日收盘价（当前价）
	limit_ratio = float(stock_limit_ratio(code))
	limit_up_price = round(prev_close * (1.0 + limit_ratio), 2)
	
	# 1. 排除高开5%以上
	# ⚠️ 此条件指的是T+1日开盘相对T日收盘不能高开5%以上
	#    但在T日收盘后无法预知T+1日开盘价，因此此条件无法在扫描时实现
	#    需要在T+1日开盘时人工或程序判断，超过5%高开则放弃买入
	# 
	# 实现示例（在T+1日开盘后执行）：
	# next_day_open = get_realtime_price(code)  # 获取实时开盘价
	# gap_open_pct = (next_day_open - today_close) / today_close
	# if gap_open_pct >= 0.05:
	#     print(f"{code} 高开{gap_open_pct*100:.2f}%，放弃买入")
	#     return False
	
	# 2. 今日(T日)未涨停: T日收盘价 < T日涨停价(基于T-1日收盘计算)
	if not (today_close < limit_up_price):
		return False
	
	# 3. 当前价(T日收盘) > 前日收盘价(T-1日收盘)
	if today_close <= prev_close:
		return False
	
	# 4. 涨幅 < 4.5%：(T日收盘 - T-1日收盘) / T-1日收盘
	pct_change = (today_close - prev_close) / prev_close
	return pct_change < 0.045


def analyze_stock(df: pd.DataFrame, code: str) -> tuple[bool, str]:
	"""
	筛选股票的完整策略 - 用于T日收盘后筛选、T+1日买入的场景
	
	扫描时可实现的条件（基于T日及之前的数据）：
	1. 周成交量环比增长率 > 100%（基于WEEK_WINDOW个交易日周期，量能放大）
	2. 近3个月区间涨跌幅 < 40.1%（避免追高位股）
	3. T日未涨停
	4. T日收盘 > T-1日收盘（小幅上涨）
	5. T日涨幅 < 4.5%（温和上涨，不追高）
	6. 非ST股（在调用侧已过滤）
	
	⚠️ T+1日开盘时需额外判断：
	- 排除高开5%以上：若T+1日开盘相对T日收盘高开>=5%，则放弃买入
	
	选股意图：量能放大 + 位置不高 + T日表现温和 → T+1日买入机会
	"""
	if len(df) < MIN_DATA_LEN:
		return False, '数据不足'
	# 条件1: 周成交量环比增长>100%
	if not _passes_weekly_volume_growth(df):
		return False, '周成交量环比未>100%'
	# 条件2: 近3个月区间涨跌幅<40.1%
	if not _passes_three_month_return(df):
		return False, '近3个月涨跌幅不满足'
	# 条件3-5: 排除高开5%以上 + 今日未涨停 + 当前价>前收 + 涨幅<4.5%
	if not _passes_today_constraints(df, code):
		return False, '当日条件不满足(高开/涨停/涨幅)'
	return True, '✓ 通过全部筛选条件'


def run_filter(offset_days: int = 0):
	"""
	扫描并输出候选股到文件。
	
	Args:
		offset_days: 时间偏移量（天数），默认0
			- 0: 以T日为基准（今天），使用截至T日的数据
			- 1: 以T-1日为基准（昨天），使用截至T-1日的数据
			- N: 以T-N日为基准，使用截至T-N日的数据
			
		⚠️ 注意：扫描T-N日时，只使用截至T-N日的数据，不使用未来数据
	"""
	if not os.path.exists(DATA_DIR):
		print(f"错误: 数据目录 '{DATA_DIR}' 不存在。")
		return

	stock_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
	if not stock_files:
		print(f"错误: 数据目录 '{DATA_DIR}' 中没有找到CSV文件。")
		return

	# 打印扫描配置
	if offset_days > 0:
		print(f"⏰ 时间偏移: {offset_days}天 (扫描T-{offset_days}日的数据)")
	else:
		print(f"⏰ 扫描当前数据 (T日)")
	
	print(f"开始扫描 {len(stock_files)} 只股票...")
	candidate_stocks: list[str] = []
	base_date = None  # 基准日期

	for filename in tqdm(stock_files, desc='扫描进度'):
		# 非ST股
		if _is_st_filename(filename):
			continue

		code = filename.split('_')[0]
		file_path = os.path.join(DATA_DIR, filename)
		df = read_stock_data(file_path)
		if df is None or df.empty:
			continue
		
		# 应用时间偏移：截取到T-offset_days日
		if offset_days > 0:
			if len(df) <= offset_days:
				continue  # 数据不足，跳过
			df = df.iloc[:-offset_days]
		
		# 记录基准日期（第一次遇到有效数据时）
		if base_date is None and not df.empty:
			base_date = df.index[-1]

		is_candidate, reason = analyze_stock(df.copy(), code)
		if is_candidate:
			candidate_stocks.append(code)
			tqdm.write(f"  [+] 候选: {code} - {reason}")

	# 构建输出文件名（包含基准日期）
	if base_date is not None:
		date_str = base_date.strftime('%Y%m%d')
		output_file = OUTPUT_FILE.replace('.txt', f'_{date_str}.txt')
	else:
		output_file = OUTPUT_FILE
		date_str = "未知"
	
	print("\n" + "=" * 50)
	print(f"📅 基准日期: {date_str}")
	print(f"扫描完成！发现 {len(candidate_stocks)} 只候选股票。")
	print("=" * 50)

	if candidate_stocks:
		output_dir = os.path.dirname(output_file)
		if not os.path.exists(output_dir):
			os.makedirs(output_dir)
		
		# 保存到带日期的文件
		with open(output_file, 'w', encoding='utf-8') as f:
			for code in candidate_stocks:
				f.write(code + '\n')
		print(f"候选股列表已保存到: {output_file}")
		
		# 自动复制到不带日期的文件（供后续流程使用）
		shutil.copy2(output_file, OUTPUT_FILE)
		print(f"✓ 已同步到: {OUTPUT_FILE} (供strategy_scan使用)")
	else:
		print('未发现符合条件的候选股。')


if __name__ == '__main__':
	run_filter() 