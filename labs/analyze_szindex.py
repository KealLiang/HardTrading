import pandas as pd

# 读取CSV文件
df = pd.read_csv('shanghai_index.csv')

# 初始化计数器
high_and_high = 0  # 高开高走
low_and_high = 0  # 低开高走
flat_and_high = 0  # 平开高走

# 遍历数据
for i in range(1, len(df)):
    # 获取前一天的收盘价
    previous_close = df.iloc[i - 1]['close']
    # 获取当天的开盘价和收盘价
    current_open = df.iloc[i]['open']
    current_close = df.iloc[i]['close']

    if current_open > previous_close and current_close > previous_close:
        high_and_high += 1

    if current_open < previous_close and current_close > previous_close:
        low_and_high += 1

    if current_open == previous_close and current_close > previous_close:
        flat_and_high += 1

# 打印结果
print(f"总数次数：{len(df) - 1}")
print(f"高开高走出现的次数：{high_and_high}")
print(f"低开高走现的次数：{low_and_high}")
print(f"平开高走现的次数：{flat_and_high}")
