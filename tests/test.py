# 保存为check_numpy.py并运行
import akshare as ak

all_data = ak.stock_zh_index_daily(symbol='sz399006')
print(all_data.tail(10))
