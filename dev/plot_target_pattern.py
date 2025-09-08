import matplotlib.pyplot as plt
import numpy as np
import matplotlib.patches as patches
import matplotlib.font_manager as fm
import os
import platform

# 根据操作系统配置中文字体
system = platform.system()
font_prop = None
if system == 'Windows':
    # Windows系统
    font_path = 'C:/Windows/Fonts/simhei.ttf'  # Windows的默认黑体字体路径
    if not os.path.exists(font_path):
        # 尝试其他可能的字体
        candidates = ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc', 'C:/Windows/Fonts/simfang.ttf']
        for candidate in candidates:
            if os.path.exists(candidate):
                font_path = candidate
                break
    if os.path.exists(font_path):
        font_prop = fm.FontProperties(fname=font_path)
        plt.rcParams['font.family'] = font_prop.get_name()
    else:
        print("警告: 未找到合适的中文字体，图表中的中文可能无法正确显示")
elif system == 'Linux':
    # Linux系统
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'DejaVu Sans']
    try:
        font_prop = fm.FontProperties(family='WenQuanYi Micro Hei')
    except:
        pass
elif system == 'Darwin':
    # macOS系统
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'Heiti SC']
    try:
        font_prop = fm.FontProperties(family='PingFang SC')
    except:
        pass

# 解决负号显示问题
plt.rcParams['axes.unicode_minus'] = False


def generate_pattern_data():
    """生成符合"短周期蓄势突破"形态的模拟价格数据"""
    # 时间轴
    days = np.arange(0, 45)

    # --- 阶段1: 前期高波动拉升 (0-15天) ---
    high_vol_period = days[:15]
    # ผสมผสานแนวโน้มขาขึ้นกับการแกว่งตัวแบบสุ่มเพื่อสร้างความผันผวน
    price1 = 100 + np.cumsum(np.random.randn(len(high_vol_period)) * 1.5) + np.sin(high_vol_period * 0.5) * 4

    # --- 阶段2: 高位换手与波动收敛 (15-40天) ---
    consolidation_period = days[15:40]
    # 在前期高点附近开始，减小波动率，形成横盘整理
    peak_price = price1[-1]
    price2 = peak_price - 3 + np.cumsum(np.random.randn(len(consolidation_period)) * 0.45)
    # 人为制造几次"压力测试"，价格向上触碰高点
    price2[5] = peak_price + 0.5
    price2[10] = peak_price + 0.8
    price2[18] = peak_price + 0.2

    # --- 阶段3: 放量突破 (40-45天) ---
    breakout_period = days[40:]
    # 从整理期末尾的价格开始，形成强劲的上涨趋势
    start_breakout_price = price2[-1]
    price3 = start_breakout_price + np.cumsum(np.random.rand(len(breakout_period)) * 2 + 1.5)

    # 拼接所有阶段的价格数据
    full_price_series = np.concatenate((price1, price2, price3))
    return days, full_price_series


def plot_target_pattern():
    """使用Matplotlib绘制目标形态图"""
    days, prices = generate_pattern_data()

    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(16, 9))

    # 绘制价格曲线
    ax.plot(days, prices, label='价格 (Price)', color='#4a90e2', linewidth=2)
    ax.fill_between(days, prices, alpha=0.1, color='#4a90e2')

    # --- 核心特征标注 ---

    # 1. 前期高波动区域
    ax.axvspan(0, 15, color='#f5a623', alpha=0.15, label='前期高波动区')
    ax.text(7.5, 95, '(1) 前期高波动\n(High Volatility)', ha='center', fontsize=12, color='#c48a1c', style='italic', 
            fontproperties=font_prop)

    # 2. 高位换手与波动收敛区
    consolidation_start_day = 15
    consolidation_end_day = 40
    peak_price = np.max(prices[:consolidation_end_day])
    consolidation_low = np.min(prices[consolidation_start_day:consolidation_end_day])

    rect = patches.Rectangle((consolidation_start_day, consolidation_low),
                             consolidation_end_day - consolidation_start_day,
                             peak_price - consolidation_low,
                             linewidth=1, edgecolor='none', facecolor='#7ed321', alpha=0.15)
    ax.add_patch(rect)
    ax.text((consolidation_start_day + consolidation_end_day) / 2, consolidation_low - 4,
            '(2) 高位换手与波动收敛区\n(Consolidation & Contraction)', ha='center', fontsize=12, color='#5a9a18',
            style='italic', fontproperties=font_prop)

    # 枢轴/压力位线
    ax.axhline(y=peak_price, color='#d0021b', linestyle='--', linewidth=1.5, xmin=0.4, xmax=0.95)
    ax.text(consolidation_end_day + 1, peak_price, '压力位 (Resistance / Pivot)', va='center', ha='left', fontsize=11,
            color='#d0021b', fontproperties=font_prop)

    # 3. 压力测试标注
    ax.annotate('(3) 压力测试', xy=(25.5, peak_price + 0.5), xytext=(22, peak_price + 8),
                arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=6, connectionstyle="arc3,rad=-.1"),
                ha='center', fontsize=11, fontproperties=font_prop)
    ax.annotate('', xy=(30.5, peak_price + 0.8), xytext=(22, peak_price + 8.1),
                arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=6, connectionstyle="arc3,rad=-.1"))

    # 5. 理想买点
    breakout_day = 40
    breakout_price = prices[breakout_day]
    ax.plot(breakout_day, breakout_price, 'o', markersize=12, markerfacecolor='gold', markeredgecolor='black',
            label='理想买点 (Ideal Buy Point)', zorder=5)
    ax.annotate('(5) 理想买点\n(放量突破)', xy=(breakout_day, breakout_price), xytext=(35, breakout_price - 15),
                arrowprops=dict(facecolor='#ffbf00', shrink=0.05, width=2, headwidth=8,
                                connectionstyle="arc3,rad=.2"),
                ha='center', fontsize=14, fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.3", fc="yellow", ec="black", lw=1, alpha=0.8), 
                zorder=6, fontproperties=font_prop)

    # --- 图表美化 ---
    ax.set_title('目标形态: 短周期蓄势突破 (Short-term Consolidation Breakout)', 
                fontsize=20, fontweight='bold', pad=20, fontproperties=font_prop)
    ax.set_xlabel('交易日 (Trading Days)', fontsize=14, fontproperties=font_prop)
    ax.set_ylabel('价格 (Price)', fontsize=14, fontproperties=font_prop)
    
    # 为图例设置中文字体
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, prop=font_prop)
    
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()

    # 保存图表到文件
    output_filename = 'dev/target_pattern_visualization.png'
    plt.savefig(output_filename, dpi=300)
    print(f"图表已保存到: '{output_filename}'")


if __name__ == '__main__':
    # 在运行前，请确保已安装 matplotlib: pip install matplotlib
    plot_target_pattern() 