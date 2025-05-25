import os
from datetime import datetime, timedelta

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

# 解决中文显示问题
matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 用黑体显示中文
matplotlib.rcParams['axes.unicode_minus'] = False  # 正常显示负号


def plot_stock_closing_prices(stock_codes, start_date=None, end_date=None, data_dir='./data/astocks',
                              save_dir='./images'):
    """
    绘制多只股票的收盘价百分比变化折线图
    
    参数:
    stock_codes (list): 股票代码列表，如 ["000001", "600000"]
    start_date (str): 开始日期，格式为 "YYYYMMDD"，如 "20250101"
    end_date (str): 结束日期，格式为 "YYYYMMDD"，如 "20250131"
    data_dir (str): 股票数据所在目录
    save_dir (str): 图片保存目录
    
    返回:
    str: 保存的图片路径
    """
    # 确保保存目录存在
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    plt.figure(figsize=(15, 8))

    # 转换日期格式
    start_date_dt = None
    end_date_dt = None

    if start_date:
        start_date_dt = datetime.strptime(start_date, "%Y%m%d")
        start_date_str = start_date_dt.strftime("%Y-%m-%d")
        # 获取前一天的日期，用于计算基准价格
        base_date_dt = start_date_dt - timedelta(days=1)
        base_date_str = base_date_dt.strftime("%Y-%m-%d")
    else:
        start_date_str = None
        base_date_str = None

    if end_date:
        end_date_dt = datetime.strptime(end_date, "%Y%m%d")
        end_date_str = end_date_dt.strftime("%Y-%m-%d")
    else:
        end_date_str = None

    stock_names = {}  # 存储股票代码和名称的映射
    legend_labels = []  # 图例标签
    all_dates = set()  # 收集所有交易日期

    # 遍历每只股票
    for stock_code in stock_codes:
        # 查找股票文件
        found = False
        for filename in os.listdir(data_dir):
            if filename.startswith(stock_code):
                file_path = os.path.join(data_dir, filename)
                found = True

                # 从文件名中提取股票名称
                if '_' in filename:
                    stock_name = filename.split('_')[1].split('.')[0]
                    stock_names[stock_code] = stock_name
                else:
                    stock_names[stock_code] = stock_code

                # 读取股票数据
                df = pd.read_csv(file_path, header=None, names=[
                    'date', 'code', 'open', 'close', 'high', 'low', 'volume',
                    'amount', 'amplitude', 'change_percent', 'change', 'turnover'
                ])

                # 转换日期列为日期类型
                df['date'] = pd.to_datetime(df['date'])

                # 获取完整数据，包括基准日期
                full_df = df.copy()

                # 根据日期范围筛选数据
                if start_date_str:
                    df = df[df['date'] >= start_date_str]
                if end_date_str:
                    df = df[df['date'] <= end_date_str]

                if not df.empty:
                    # 收集所有交易日期
                    all_dates.update(df['date'].dt.date)

                    # 获取基准价格（起始日期前一天的收盘价）
                    base_price = None

                    if base_date_str:
                        base_row = full_df[full_df['date'] == base_date_str]
                        if not base_row.empty:
                            base_price = base_row.iloc[0]['close']
                        else:
                            # 如果找不到前一天的数据，尝试找到最接近的日期
                            full_df_before_start = full_df[full_df['date'] < start_date_str]
                            if not full_df_before_start.empty:
                                base_price = full_df_before_start.iloc[-1]['close']

                    # 如果无法获取基准价格，使用第一天的开盘价
                    if base_price is None and not df.empty:
                        base_price = df.iloc[0]['open']
                        print(f"警告: 股票 {stock_code} 无法获取基准日期收盘价，使用起始日期开盘价作为基准")

                    if base_price and base_price > 0:
                        # 计算每天收盘价相对于基准价格的百分比变化
                        df['percent_change'] = ((df['close'] - base_price) / base_price) * 100

                        # 绘制百分比变化折线图
                        plt.plot(df['date'], df['percent_change'], linewidth=2)
                        legend_labels.append(f"{stock_code}_{stock_names[stock_code]}")
                    else:
                        print(f"警告: 股票 {stock_code} 基准价格无效")
                else:
                    print(f"警告: 股票 {stock_code} 在指定日期范围内没有数据")

                break

        if not found:
            print(f"警告: 未找到股票 {stock_code} 的数据文件")

    # 设置图表属性
    plt.title('股票涨跌幅走势对比', fontsize=16)
    plt.xlabel('日期', fontsize=12)
    plt.ylabel('涨跌幅(%)', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)

    # 添加零线
    plt.axhline(y=0, color='r', linestyle='-', alpha=0.3)

    # 设置x轴日期格式，确保等距显示
    ax = plt.gca()

    # 将所有日期排序
    all_dates = sorted(list(all_dates))

    if all_dates:
        # 设置x轴刻度为所有交易日期，确保等距显示
        ax.set_xticks([datetime.combine(date, datetime.min.time()) for date in all_dates])

        # 设置日期格式
        date_formatter = mdates.DateFormatter('%Y-%m-%d')
        ax.xaxis.set_major_formatter(date_formatter)

        # 旋转日期标签，使其更易读
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    # 自动调整图例位置，避免遮挡数据
    # 尝试几个可能的位置，找到最佳位置
    legend_positions = ['best', 'upper left', 'upper right', 'lower left', 'lower right']
    for pos in legend_positions:
        legend = plt.legend(legend_labels, loc=pos, framealpha=0.7)
        # 检查图例是否遮挡了主要数据
        # 这里只是简单地尝试不同位置，实际上matplotlib会自动选择最佳位置
        if pos == 'best':
            break

    # 调整布局，确保所有元素都能显示
    plt.tight_layout()

    # 生成文件名
    date_str = datetime.now().strftime("%Y%m%d")
    if start_date and end_date:
        filename = f"stock_percent_change_{start_date}_to_{end_date}.png"
    else:
        filename = f"stock_percent_change_{date_str}.png"

    # 保存图表
    save_path = os.path.join(save_dir, filename)
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    plt.close()

    print(f"股票涨跌幅走势对比图已保存至: {save_path}")
    return save_path


def plot_multiple_stocks(stock_codes=None, start_date=None, end_date=None):
    """
    绘制多只股票的涨跌幅走势图
    
    参数:
    stock_codes (list): 股票代码列表，如 ["000001", "600000"]
    start_date (str): 开始日期，格式为 "YYYYMMDD"，如 "20250101"
    end_date (str): 结束日期，格式为 "YYYYMMDD"，如 "20250131"
    """
    if stock_codes is None or len(stock_codes) == 0:
        # 默认股票列表
        stock_codes = ["000001", "600000", "601318", "600036", "601166"]

    return plot_stock_closing_prices(stock_codes, start_date, end_date)
