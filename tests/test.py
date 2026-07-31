import matplotlib
matplotlib.use("TkAgg")  # 避开 PyCharm InterAgg 与新版 matplotlib 的 tostring_rgb 不兼容
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

plt.figure(figsize=(12, 7), dpi=110)

# 坐标点模拟W底完整走势
x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
y = [10, 9, 7, 5, 6.8, 4.9, 6.7, 5.0, 6.8, 7.2, 7.5, 7.7, 8.1, 8.5, 9.0]

plt.plot(x, y, color="#2266bb", linewidth=2.5, label="价格走势")

# 颈线位置
neck_y = 6.8
plt.axhline(y=neck_y, color="#dd3333", linestyle="--", linewidth=2, label="颈线")

# 标注关键点位
plt.annotate("左底", xy=(4, 5), xytext=(3.2, 4.2), fontsize=11)
plt.annotate("右底", xy=(8, 5.0), xytext=(7.2, 4.2), fontsize=11)
plt.annotate("放量突破颈线", xy=(9, 6.8), xytext=(9.2, 7.3), fontsize=11)
plt.text(12, neck_y+0.12, "突破后上涨", fontsize=11, color="#2266bb")

# 前置下跌趋势示意
plt.plot([1, 3], [10, 7], color="#666666", linestyle=":", label="原有下跌趋势")

plt.ylim(3, 11)
plt.title("下跌趋势末端 · 标准W底（双底形态）", fontsize=13)
plt.grid(alpha=0.3)
plt.legend(loc="upper left")
plt.gca().set_xticks([])
plt.gca().set_yticks([])
plt.tight_layout()
plt.show()
