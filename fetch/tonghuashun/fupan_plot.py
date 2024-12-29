from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd

# 设置 matplotlib 的字体为支持中文的字体
plt.rcParams['font.sans-serif'] = ['SimHei']  # 'SimHei' 是黑体的意思
plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号


def read_and_plot_data(fupan_file, start_date=None, end_date=None):
    # 读取 Excel 中的两个 sheet：连板数据和跌停数据
    lianban_data = pd.read_excel(fupan_file, sheet_name="连板数据", index_col=0)
    dieting_data = pd.read_excel(fupan_file, sheet_name="跌停数据", index_col=0)

    # 提取日期列
    dates = lianban_data.columns

    # 筛选时间范围
    if start_date:
        start_date = datetime.strptime(start_date, "%Y%m%d")
    if end_date:
        end_date = datetime.strptime(end_date, "%Y%m%d")

    filtered_dates = []
    for date in dates:
        date_obj = datetime.strptime(date, "%Y年%m月%d日")
        if (not start_date or date_obj >= start_date) and (not end_date or date_obj <= end_date):
            filtered_dates.append(date)

    dates = filtered_dates

    # 初始化结果存储
    lianban_results = []  # 存储连续涨停天数最大值及其股票
    dieting_results = []  # 存储连续跌停天数最大值及其股票

    # 逐列提取数据
    for date in dates:
        # 连板数据处理
        lianban_col = lianban_data[date].dropna()  # 去除空单元格
        lianban_stocks = lianban_col.str.split(';').apply(lambda x: [item.strip() for item in x])  # 分列处理
        lianban_df = pd.DataFrame(lianban_stocks.tolist(), columns=[
            '股票代码', '股票简称', '涨停开板次数', '最终涨停时间',
            '几天几板', '最新价', '首次涨停时间', '最新涨跌幅',
            '连续涨停天数', '涨停原因类别'
        ])
        lianban_df['连续涨停天数'] = lianban_df['连续涨停天数'].astype(int)
        max_lianban = lianban_df['连续涨停天数'].max()
        max_lianban_stocks = lianban_df[lianban_df['连续涨停天数'] == max_lianban]['股票简称'].tolist()
        lianban_results.append((date, max_lianban, max_lianban_stocks))

        # 跌停数据处理
        dieting_col = dieting_data[date].dropna()  # 去除空单元格
        dieting_col = dieting_col.fillna('').astype(str)  # 填充空数据
        dieting_stocks = dieting_col.str.split(';').apply(lambda x: [item.strip() for item in x])  # 分列处理
        dieting_df = pd.DataFrame(dieting_stocks.tolist(), columns=[
            '股票代码', '股票简称', '跌停开板次数', '首次跌停时间',
            '跌停类型', '最新价', '最新涨跌幅',
            '连续跌停天数', '跌停原因类型'
        ])
        dieting_df['连续跌停天数'] = dieting_df['连续跌停天数'].astype(int)
        max_dieting = dieting_df['连续跌停天数'].max()
        max_dieting_stocks = dieting_df[dieting_df['连续跌停天数'] == max_dieting]['股票简称'].tolist()
        dieting_results.append((date, -max_dieting, max_dieting_stocks))  # 跌停天数为负数

    # 绘图
    fig, ax = plt.subplots(figsize=(12, 6))

    # 提取数据并绘制连板折线
    lianban_dates = [datetime.strptime(item[0], "%Y年%m月%d日") for item in lianban_results]
    lianban_days = [item[1] for item in lianban_results]
    lianban_labels = [', '.join(item[2]) for item in lianban_results]
    ax.plot(lianban_dates, lianban_days, label='连续涨停天数', color='red', marker='o')
    for i, txt in enumerate(lianban_labels):
        ax.text(lianban_dates[i], lianban_days[i], txt.replace(', ', '\n'),
                ha='left', va='bottom', fontsize=7)  # 用换行符分隔，右上方显示

    # 提取数据并绘制跌停折线
    dieting_days = [item[1] for item in dieting_results]
    dieting_labels = [', '.join(item[2][:10]) + f'...{len(item[2])}' if len(item[2]) > 10 else ', '.join(item[2])
                      for item in dieting_results]  # 太长则省略
    ax.plot(lianban_dates, dieting_days, label='连续跌停天数', color='green', marker='o')
    for i, txt in enumerate(dieting_labels):
        ax.text(lianban_dates[i], dieting_days[i], txt.replace(', ', '\n'),
                ha='left', va='bottom', fontsize=7)  # 用换行符分隔，右上方显示

    # 设置图表信息
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')  # 添加水平参考线
    ax.set_title("连板/跌停个股走势", fontsize=16)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("天数", fontsize=12)
    ax.set_xticks(lianban_dates)  # 设置横轴刻度为所有日期
    ax.set_xticklabels([date.strftime('%Y-%m-%d') for date in lianban_dates], rotation=45, fontsize=9)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))  # 设置y轴刻度为整数
    ax.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    # plt.savefig("fupan_lb.png", format='png')
    # plt.close()


def draw_fupan_lb():
    # 示例调用
    fupan_file = "./excel/fupan_stocks.xlsx"
    start_date = '20241201'  # 开始日期
    # end_date = '20241101'  # 结束日期
    end_date = None
    read_and_plot_data(fupan_file, start_date, end_date)


if __name__ == '__main__':
    draw_fupan_lb()
