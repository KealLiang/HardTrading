"""
周成交量增长策略 - 胜率分析工具

用于分析历史扫描结果的实际表现，统计胜率、收益率等指标
"""
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import numpy as np
from tqdm import tqdm


# ==================== 数据类定义 ====================

@dataclass
class TradeResult:
	"""单次交易结果"""
	code: str                      # 股票代码
	name: str = ""                 # 股票名称
	base_date: str = ""            # 基准日期（T日）
	buy_date: str = ""             # 买入日期（T+1日）
	sell_date: str = ""            # 卖出日期（T+2日）
	buy_price: float = 0.0         # 买入价格（T+1开盘价）
	sell_price: float = 0.0        # 加权卖出价格
	return_rate: float = 0.0       # 收益率
	is_profitable: bool = False    # 是否盈利
	error_msg: str = ""            # 错误信息（如数据缺失）
	
	# 详细数据
	t1_open: float = 0.0           # T+1开盘价
	t1_close: float = 0.0          # T+1收盘价
	t2_open: float = 0.0           # T+2开盘价
	t2_high: float = 0.0           # T+2最高价
	t2_close: float = 0.0          # T+2收盘价


@dataclass
class SellStrategy:
	"""卖出策略配置"""
	high_ratio: float = 0.25       # 在高点卖出的比例（默认1/4）
	close_ratio: float = 0.75      # 在收盘卖出的比例（默认3/4）
	description: str = "T+2日高点卖1/4，收盘卖3/4"
	
	def calculate_sell_price(self, t2_high: float, t2_close: float) -> float:
		"""计算加权卖出价格"""
		return t2_high * self.high_ratio + t2_close * self.close_ratio


@dataclass
class AnalysisReport:
	"""分析报告"""
	total_count: int = 0                    # 总数量
	valid_count: int = 0                    # 有效交易数量
	error_count: int = 0                    # 错误数量
	
	profitable_count: int = 0               # 盈利数量
	loss_count: int = 0                     # 亏损数量
	breakeven_count: int = 0                # 持平数量
	
	win_rate: float = 0.0                   # 胜率
	avg_return: float = 0.0                 # 平均收益率
	avg_profit: float = 0.0                 # 平均盈利收益率
	avg_loss: float = 0.0                   # 平均亏损收益率
	
	max_return: float = 0.0                 # 最大收益率
	min_return: float = 0.0                 # 最大亏损率
	
	median_return: float = 0.0              # 中位数收益率
	return_std: float = 0.0                 # 收益率标准差
	
	profit_loss_ratio: float = 0.0          # 盈亏比（平均盈利/平均亏损）
	
	trade_results: List[TradeResult] = field(default_factory=list)


# ==================== 核心分析类 ====================

class WinRateAnalyzer:
	"""胜率分析器"""
	
	def __init__(self, data_dir: str = './data/astocks'):
		self.data_dir = data_dir
		self.stock_cache: Dict[str, pd.DataFrame] = {}
	
	def _read_stock_data(self, code: str) -> Optional[pd.DataFrame]:
		"""读取股票数据（带缓存）"""
		if code in self.stock_cache:
			return self.stock_cache[code]
		
		# 查找文件
		for filename in os.listdir(self.data_dir):
			if filename.startswith(code) and filename.endswith('.csv'):
				filepath = os.path.join(self.data_dir, filename)
				try:
					column_names = [
						'date', 'code', 'open', 'close', 'high', 'low', 'volume',
						'amount', 'amplitude', 'pct_chg', 'turnover', 'pe_ratio'
					]
					df = pd.read_csv(
						filepath,
						header=None,
						names=column_names,
						index_col='date',
						parse_dates=True
					)
					df.index = df.index.tz_localize(None)
					self.stock_cache[code] = df
					return df
				except Exception as e:
					return None
		return None
	
	def _get_next_trading_dates(self, base_date: datetime, n: int = 2) -> List[datetime]:
		"""
		获取基准日期后的n个交易日
		
		Args:
			base_date: 基准日期（T日）
			n: 需要获取的交易日数量
		
		Returns:
			交易日列表（可能不足n个）
		"""
		# 简化实现：假设所有日期都是交易日
		# 实际会通过数据文件中的日期来确定
		dates = []
		current = base_date
		for i in range(1, n + 10):  # 多查几天，确保找到足够的交易日
			current = base_date + timedelta(days=i)
			dates.append(current)
			if len(dates) >= n:
				break
		return dates
	
	def analyze_single_stock(
		self, 
		code: str, 
		base_date_str: str,
		strategy: SellStrategy
	) -> TradeResult:
		"""
		分析单只股票的交易结果
		
		Args:
			code: 股票代码
			base_date_str: 基准日期字符串（格式：YYYYMMDD）
			strategy: 卖出策略
		
		Returns:
			TradeResult: 交易结果
		"""
		result = TradeResult(code=code, base_date=base_date_str)
		
		# 读取股票数据
		df = self._read_stock_data(code)
		if df is None or df.empty:
			result.error_msg = "数据文件不存在或为空"
			return result
		
		# 解析基准日期
		try:
			base_date = datetime.strptime(base_date_str, '%Y%m%d')
		except:
			result.error_msg = "基准日期格式错误"
			return result
		
		# 获取T+1和T+2日的数据
		try:
			# 找到基准日期在数据中的位置
			base_date_normalized = pd.Timestamp(base_date)
			if base_date_normalized not in df.index:
				result.error_msg = f"基准日期{base_date_str}不在数据中"
				return result
			
			base_idx = df.index.get_loc(base_date_normalized)
			
			# T+1日（买入日）
			if base_idx + 1 >= len(df):
				result.error_msg = "T+1日数据缺失"
				return result
			t1_row = df.iloc[base_idx + 1]
			result.buy_date = t1_row.name.strftime('%Y%m%d')
			result.t1_open = float(t1_row['open'])
			result.t1_close = float(t1_row['close'])
			result.buy_price = result.t1_open
			
			# T+2日（卖出日）
			if base_idx + 2 >= len(df):
				result.error_msg = "T+2日数据缺失"
				return result
			t2_row = df.iloc[base_idx + 2]
			result.sell_date = t2_row.name.strftime('%Y%m%d')
			result.t2_open = float(t2_row['open'])
			result.t2_high = float(t2_row['high'])
			result.t2_close = float(t2_row['close'])
			
			# 计算卖出价格（加权）
			result.sell_price = strategy.calculate_sell_price(
				result.t2_high, 
				result.t2_close
			)
			
			# 计算收益率
			result.return_rate = (result.sell_price - result.buy_price) / result.buy_price
			result.is_profitable = result.return_rate > 0
			
		except Exception as e:
			result.error_msg = f"计算错误: {str(e)}"
		
		return result
	
	def analyze_scan_file(
		self, 
		scan_file: str,
		strategy: SellStrategy = None
	) -> AnalysisReport:
		"""
		分析单个扫描文件
		
		Args:
			scan_file: 扫描文件路径（如：bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt）
			strategy: 卖出策略（默认为标准策略）
		
		Returns:
			AnalysisReport: 分析报告
		"""
		if strategy is None:
			strategy = SellStrategy()
		
		# 从文件名提取基准日期
		filename = os.path.basename(scan_file)
		try:
			# 文件名格式: candidate_stocks_weekly_growth_20251015.txt
			base_date_str = filename.split('_')[-1].replace('.txt', '')
			if len(base_date_str) != 8 or not base_date_str.isdigit():
				raise ValueError(f"无法从文件名提取日期: {filename}")
		except Exception as e:
			print(f"错误: {e}")
			return AnalysisReport()
		
		# 读取候选股列表
		if not os.path.exists(scan_file):
			print(f"文件不存在: {scan_file}")
			return AnalysisReport()
		
		with open(scan_file, 'r', encoding='utf-8') as f:
			codes = [line.strip() for line in f if line.strip()]
		
		report = AnalysisReport(total_count=len(codes))
		
		print(f"\n分析文件: {filename}")
		print(f"基准日期: {base_date_str}")
		print(f"候选股数量: {len(codes)}")
		print(f"卖出策略: {strategy.description}")
		
		# 分析每只股票
		for code in tqdm(codes, desc="分析进度"):
			result = self.analyze_single_stock(code, base_date_str, strategy)
			report.trade_results.append(result)
			
			if result.error_msg:
				report.error_count += 1
			else:
				report.valid_count += 1
				if result.is_profitable:
					report.profitable_count += 1
				elif result.return_rate < 0:
					report.loss_count += 1
				else:
					report.breakeven_count += 1
		
		# 计算统计指标
		self._calculate_statistics(report)
		
		return report
	
	def _calculate_statistics(self, report: AnalysisReport):
		"""计算统计指标"""
		valid_results = [r for r in report.trade_results if not r.error_msg]
		
		if not valid_results:
			return
		
		returns = [r.return_rate for r in valid_results]
		profits = [r.return_rate for r in valid_results if r.is_profitable]
		losses = [r.return_rate for r in valid_results if r.return_rate < 0]
		
		# 基本统计
		report.win_rate = report.profitable_count / report.valid_count if report.valid_count > 0 else 0
		report.avg_return = np.mean(returns)
		report.max_return = np.max(returns)
		report.min_return = np.min(returns)
		report.median_return = np.median(returns)
		report.return_std = np.std(returns)
		
		# 盈亏统计
		if profits:
			report.avg_profit = np.mean(profits)
		if losses:
			report.avg_loss = np.mean(losses)
		
		# 盈亏比
		if report.avg_loss != 0:
			report.profit_loss_ratio = abs(report.avg_profit / report.avg_loss)
	
	def print_report(self, report: AnalysisReport, detail_level: int = 1):
		"""
		打印分析报告
		
		Args:
			report: 分析报告
			detail_level: 详细级别（0=简要，1=标准，2=详细）
		"""
		print("\n" + "=" * 80)
		print("📊 胜率分析报告")
		print("=" * 80)
		
		# 基本信息
		print(f"\n【基本信息】")
		print(f"总数量: {report.total_count}")
		print(f"有效交易: {report.valid_count}")
		print(f"数据错误: {report.error_count}")
		
		if report.valid_count == 0:
			print("\n⚠️ 没有有效交易数据")
			return
		
		# 胜率统计
		print(f"\n【胜率统计】")
		print(f"盈利数量: {report.profitable_count} ({report.profitable_count/report.valid_count*100:.2f}%)")
		print(f"亏损数量: {report.loss_count} ({report.loss_count/report.valid_count*100:.2f}%)")
		print(f"持平数量: {report.breakeven_count} ({report.breakeven_count/report.valid_count*100:.2f}%)")
		print(f"✨ 胜率: {report.win_rate*100:.2f}%")
		
		# 收益率统计
		print(f"\n【收益率统计】")
		print(f"平均收益率: {report.avg_return*100:.2f}%")
		print(f"平均盈利: {report.avg_profit*100:.2f}%")
		print(f"平均亏损: {report.avg_loss*100:.2f}%")
		print(f"最大收益: {report.max_return*100:.2f}%")
		print(f"最大亏损: {report.min_return*100:.2f}%")
		print(f"中位数收益: {report.median_return*100:.2f}%")
		print(f"收益率标准差: {report.return_std*100:.2f}%")
		print(f"盈亏比: {report.profit_loss_ratio:.2f}")
		
		# 详细信息
		if detail_level >= 2:
			print(f"\n【详细交易记录】")
			for i, result in enumerate(report.trade_results[:20], 1):  # 只显示前20条
				if result.error_msg:
					print(f"{i}. {result.code} - 错误: {result.error_msg}")
				else:
					print(f"{i}. {result.code} - 收益率: {result.return_rate*100:.2f}% "
					      f"(买入: {result.buy_price:.2f}, 卖出: {result.sell_price:.2f})")
			if len(report.trade_results) > 20:
				print(f"... 还有 {len(report.trade_results) - 20} 条记录")
		
		print("\n" + "=" * 80)
	
	def save_report_to_markdown(self, report: AnalysisReport, output_file: str):
		"""保存报告到Markdown"""
		try:
			with open(output_file, 'w', encoding='utf-8') as f:
				# 标题
				f.write(f"# 胜率分析报告\n\n")
				f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
				
				# 基本信息
				f.write(f"## 📊 基本信息\n\n")
				f.write(f"| 指标 | 数值 |\n")
				f.write(f"|------|------|\n")
				f.write(f"| 总数量 | {report.total_count} |\n")
				f.write(f"| 有效交易 | {report.valid_count} |\n")
				f.write(f"| 数据错误 | {report.error_count} |\n")
				
				if report.valid_count == 0:
					f.write(f"\n⚠️ 没有有效交易数据\n")
					print(f"\n✅ 报告已保存到: {output_file}")
					return
				
				# 胜率统计
				f.write(f"\n## 🎯 胜率统计\n\n")
				f.write(f"| 指标 | 数量 | 占比 |\n")
				f.write(f"|------|------|------|\n")
				f.write(f"| 盈利数量 | {report.profitable_count} | {report.profitable_count/report.valid_count*100:.2f}% |\n")
				f.write(f"| 亏损数量 | {report.loss_count} | {report.loss_count/report.valid_count*100:.2f}% |\n")
				f.write(f"| 持平数量 | {report.breakeven_count} | {report.breakeven_count/report.valid_count*100:.2f}% |\n")
				f.write(f"| **✨ 胜率** | **{report.profitable_count}** | **{report.win_rate*100:.2f}%** |\n")
				
				# 收益率统计
				f.write(f"\n## 💰 收益率统计\n\n")
				f.write(f"| 指标 | 数值 |\n")
				f.write(f"|------|------|\n")
				f.write(f"| 平均收益率 | {report.avg_return*100:.2f}% |\n")
				f.write(f"| 平均盈利 | {report.avg_profit*100:.2f}% |\n")
				f.write(f"| 平均亏损 | {report.avg_loss*100:.2f}% |\n")
				f.write(f"| 最大收益 | {report.max_return*100:.2f}% |\n")
				f.write(f"| 最大亏损 | {report.min_return*100:.2f}% |\n")
				f.write(f"| 中位数收益 | {report.median_return*100:.2f}% |\n")
				f.write(f"| 收益率标准差 | {report.return_std*100:.2f}% |\n")
				f.write(f"| 盈亏比 | {report.profit_loss_ratio:.2f} |\n")
				
				# 交易明细
				f.write(f"\n## 📋 交易明细\n\n")
				f.write(f"| 股票代码 | 基准日期 | 买入价 | 卖出价 | 收益率 | 状态 |\n")
				f.write(f"|---------|---------|--------|--------|--------|------|\n")
				
				# 按收益率排序
				sorted_results = sorted(report.trade_results, key=lambda x: x.return_rate if not x.error_msg else -999, reverse=True)
				
				for r in sorted_results:
					if r.error_msg:
						f.write(f"| {r.code} | {r.base_date} | - | - | - | ❌ {r.error_msg} |\n")
					else:
						status = "✅ 盈利" if r.is_profitable else "❌ 亏损"
						f.write(f"| {r.code} | {r.base_date} | {r.buy_price:.2f} | {r.sell_price:.2f} | {r.return_rate*100:.2f}% | {status} |\n")
				
				# 详细数据（可选）
				f.write(f"\n## 📈 详细数据\n\n")
				f.write(f"| 股票代码 | T+1开盘 | T+1收盘 | T+2开盘 | T+2最高 | T+2收盘 |\n")
				f.write(f"|---------|---------|---------|---------|---------|----------|\n")
				
				for r in sorted_results:
					if not r.error_msg:
						f.write(f"| {r.code} | {r.t1_open:.2f} | {r.t1_close:.2f} | {r.t2_open:.2f} | {r.t2_high:.2f} | {r.t2_close:.2f} |\n")
			
			print(f"\n✅ 报告已保存到: {output_file}")
			
		except Exception as e:
			print(f"\n❌ 保存Markdown失败: {e}")


# ==================== 主函数 ====================

def analyze_single_file(scan_file: str, strategy: SellStrategy = None, save_report: bool = True):
	"""分析单个扫描文件"""
	analyzer = WinRateAnalyzer()
	report = analyzer.analyze_scan_file(scan_file, strategy)
	analyzer.print_report(report, detail_level=1)
	
	if save_report:
		output_file = scan_file.replace('.txt', '_analysis.md')
		analyzer.save_report_to_markdown(report, output_file)
	
	return report


def analyze_latest_or_specified(scan_file: str = None, high_ratio: float = 0.25, close_ratio: float = 0.75):
	"""
	分析指定文件或最新文件（main.py调用）
	
	Args:
		scan_file: 扫描文件路径（默认None，自动查找最新文件）
		high_ratio: 高点卖出比例
		close_ratio: 收盘卖出比例
	"""
	strategy = SellStrategy(
		high_ratio=high_ratio,
		close_ratio=close_ratio,
		description=f"T+2日高点卖{high_ratio*100:.0f}%，收盘卖{close_ratio*100:.0f}%"
	)
	
	if scan_file:
		return analyze_single_file(scan_file, strategy)
	else:
		# 自动查找最新文件
		directory = 'bin/candidate_temp'
		pattern = r'candidate_stocks_weekly_growth_\d{8}\.txt$'
		
		if not os.path.exists(directory):
			print(f"错误: 目录不存在 - {directory}")
			return None
		
		scan_files = []
		for filename in os.listdir(directory):
			if re.match(pattern, filename):
				scan_files.append(os.path.join(directory, filename))
		
		if not scan_files:
			print(f"错误: 目录中没有找到匹配的扫描文件 - {directory}")
			return None
		
		latest_file = sorted(scan_files)[-1]
		print(f"📂 分析最新文件: {latest_file}")
		return analyze_single_file(latest_file, strategy)


def batch_analyze_with_pattern(directory: str = 'bin/candidate_temp', 
                                pattern: str = r'candidate_stocks_weekly_growth_\d{8}\.txt$',
                                high_ratio: float = 0.25, 
                                close_ratio: float = 0.75):
	"""
	批量分析目录下匹配正则的扫描文件（main.py调用）
	
	Args:
		directory: 扫描文件目录
		pattern: 文件名正则匹配模式
		high_ratio: 高点卖出比例
		close_ratio: 收盘卖出比例
	"""
	if not os.path.exists(directory):
		print(f"错误: 目录不存在 - {directory}")
		return
	
	strategy = SellStrategy(
		high_ratio=high_ratio,
		close_ratio=close_ratio,
		description=f"T+2日高点卖{high_ratio*100:.0f}%，收盘卖{close_ratio*100:.0f}%"
	)
	
	# 查找匹配的扫描文件
	scan_files = []
	for filename in os.listdir(directory):
		if re.match(pattern, filename):
			scan_files.append(os.path.join(directory, filename))
	
	if not scan_files:
		print(f"错误: 目录中没有找到匹配模式 '{pattern}' 的文件 - {directory}")
		return
	
	print(f"📂 找到 {len(scan_files)} 个匹配的扫描文件")
	print(f"🔍 匹配模式: {pattern}\n")
	
	analyzer = WinRateAnalyzer()
	all_reports = []
	
	for scan_file in sorted(scan_files):
		report = analyzer.analyze_scan_file(scan_file, strategy)
		analyzer.print_report(report, detail_level=0)
		
		# 保存单个报告
		output_file = scan_file.replace('.txt', '_analysis.md')
		analyzer.save_report_to_markdown(report, output_file)
		
		all_reports.append(report)
	
	# 汇总统计
	print_summary_statistics(all_reports)


def print_summary_statistics(reports: List[AnalysisReport]):
	"""打印汇总统计"""
	print("\n" + "=" * 80)
	print("📈 汇总统计")
	print("=" * 80)
	
	total_valid = sum(r.valid_count for r in reports)
	total_profitable = sum(r.profitable_count for r in reports)
	
	if total_valid == 0:
		print("没有有效数据")
		return
	
	overall_win_rate = total_profitable / total_valid
	avg_return = np.mean([r.avg_return for r in reports if r.valid_count > 0])
	
	print(f"\n总扫描次数: {len(reports)}")
	print(f"总有效交易: {total_valid}")
	print(f"总盈利次数: {total_profitable}")
	print(f"整体胜率: {overall_win_rate*100:.2f}%")
	print(f"平均收益率: {avg_return*100:.2f}%")
	
	print("\n" + "=" * 80)


if __name__ == '__main__':
	import argparse
	
	parser = argparse.ArgumentParser(description='周成交量增长策略胜率分析')
	parser.add_argument('--file', type=str, help='单个扫描文件路径')
	parser.add_argument('--dir', type=str, default='bin/candidate_temp', help='扫描文件目录')
	parser.add_argument('--batch', action='store_true', help='批量分析目录下所有匹配文件')
	parser.add_argument('--pattern', type=str, 
	                   default=r'candidate_stocks_weekly_growth_\d{8}\.txt$',
	                   help='文件名正则匹配模式（默认只匹配weekly_growth格式）')
	parser.add_argument('--high-ratio', type=float, default=0.25, help='高点卖出比例（默认0.25）')
	parser.add_argument('--close-ratio', type=float, default=0.75, help='收盘卖出比例（默认0.75）')
	
	args = parser.parse_args()
	
	if args.file:
		# 分析单个文件
		strategy = SellStrategy(
			high_ratio=args.high_ratio,
			close_ratio=args.close_ratio,
			description=f"T+2日高点卖{args.high_ratio*100:.0f}%，收盘卖{args.close_ratio*100:.0f}%"
		)
		analyze_single_file(args.file, strategy)
	elif args.batch:
		# 批量分析
		batch_analyze_with_pattern(args.dir, args.pattern, args.high_ratio, args.close_ratio)
	else:
		# 默认：分析最新的文件
		analyze_latest_or_specified(None, args.high_ratio, args.close_ratio) 