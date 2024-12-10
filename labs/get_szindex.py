import akshare as ak

# 获取上证指数数据
sz_index_df = ak.stock_zh_index_daily(symbol="sh000001")

# 将数据保存为CSV文件
sz_index_df.to_csv("shanghai_index.csv", index=False)
