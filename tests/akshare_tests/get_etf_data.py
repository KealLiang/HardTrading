import akshare as ak
import pandas as pd

# 设置pandas显示选项，取消列数、行数限制，完整显示所有内容
pd.set_option('display.max_columns', None)  # 显示所有列
pd.set_option('display.max_rows', None)     # 显示所有行（可选）
pd.set_option('display.width', None)        # 不限制显示宽度
pd.set_option('display.max_colwidth', None) # 不限制列内容长度

# 获取沪深300 ETF（510300）的最新行情数据
etf_300_df = ak.fund_etf_hist_em(symbol="510300", period="daily", start_date="20260120", end_date="20260210")
print("=== 沪深300 ETF（510300）最新数据 ===")
print(etf_300_df.tail(1))  # 只显示最后一行（最新数据）

print("\n" + "="*50 + "\n")

# 获取黄金ETF（518880）的最新行情数据
etf_gold_df = ak.fund_etf_hist_em(symbol="518880", period="daily", start_date="20260120", end_date="20260210")
print("=== 黄金ETF（518880）最新数据 ===")
print(etf_gold_df.tail(1))  # 只显示最后一行（最新数据）