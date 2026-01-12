import akshare as ak

# 设置目标股票代码和时间范围
stock_code = "600519"  # 贵州茅台
start_time = "2025-12-23 09:30:00"  # 开盘时间
end_time = "2025-12-23 09:45:00"  # 10分钟后
period = "5"  # 1分钟级别的k线

# 获取1分钟K线数据
df = ak.stock_zh_a_hist_min_em(symbol=stock_code, period=period, start_date=start_time, end_date=end_time)

# 检查数据是否为空
if df.empty:
    print("⚠️ 当前查询日期为超限的日期或未来日期，无数据返回。请使用历史交易日，如：2024-12-26")
else:
    print(df.head().to_string())
