from datetime import datetime, timedelta

import akshare as ak
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 解决中文显示问题
matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 用黑体显示中文
matplotlib.rcParams['axes.unicode_minus'] = False  # 正常显示负号


def fetch_time_sharing_data(stock_codes, date_str):
    """
    获取多只股票的分时数据
    
    参数:
    stock_codes (list): 股票代码列表，如 ["000001", "600000"]
    date_str (str): 日期字符串，格式为 "YYYYMMDD"，如 "20230601"
    
    返回:
    dict: 包含每只股票分时数据的字典
    """
    result = {}
    stock_names = {}  # 存储股票代码和名称的映射

    # 获取日期对象，用于计算前一交易日
    current_date = datetime.strptime(date_str, "%Y%m%d")
    
    # 尝试获取前20个交易日数据，确保能找到前一交易日
    prev_days_range = 20
    
    for stock_code in stock_codes:
        try:
            # 判断股票代码所属市场
            if stock_code.startswith('6'):
                market = "1"  # 上海
            else:
                market = "0"  # 深圳

            # 获取股票名称
            try:
                stock_info = ak.stock_individual_info_em(symbol=stock_code)
                stock_name = stock_info.iloc[1].value
                stock_names[stock_code] = stock_name
            except:
                stock_names[stock_code] = stock_code
                print(f"获取股票 {stock_code} 名称失败，将使用代码作为名称")
                
            # 获取前一交易日收盘价
            prev_close = None
            try:
                # 获取股票的历史日K数据
                start_date = (current_date - timedelta(days=prev_days_range)).strftime("%Y%m%d")
                end_date = date_str
                
                hist_df = ak.stock_zh_a_hist(symbol=stock_code, start_date=start_date, end_date=end_date, adjust="")
                
                if hist_df is not None and not hist_df.empty and len(hist_df) > 1:
                    # 倒数第二行是前一交易日
                    prev_close = hist_df.iloc[-2]['收盘']
                    print(f"股票 {stock_code} 前一交易日收盘价: {prev_close}")
                else:
                    print(f"无法获取股票 {stock_code} 的前一交易日数据")
            except Exception as e:
                print(f"获取股票 {stock_code} 历史价格时出错: {e}")

            # 使用akshare获取分时数据
            df = ak.stock_zh_a_hist_min_em(symbol=stock_code, period='1', start_date=date_str, end_date=date_str)

            if df is not None and not df.empty:
                # 处理日期时间格式
                df['datetime'] = pd.to_datetime(df['时间'])
                
                # 计算相对于前一交易日收盘价的涨跌幅
                if prev_close is not None and prev_close > 0:
                    df['涨跌幅'] = (df['收盘'] / prev_close - 1) * 100
                    print(f"成功计算 {stock_code} 相对于前一交易日收盘价的涨跌幅")
                else:
                    # 如果无法获取前一交易日收盘价，使用当日第一个价格
                    first_price = df.iloc[0]['收盘']
                    df['涨跌幅'] = (df['收盘'] / first_price - 1) * 100
                    print(f"警告: 使用 {stock_code} 当日第一个价格计算涨跌幅")

                result[stock_code] = df
                print(f"成功获取股票 {stock_code}({stock_names[stock_code]}) 的分时数据")
            else:
                print(f"未获取到股票 {stock_code} 的分时数据")
        except Exception as e:
            print(f"获取股票 {stock_code} 的分时数据时出错: {e}")

    return result, stock_names


def plot_time_sharing_data(data_dict, stock_names, date_str):
    """
    将多只股票的分时数据绘制在同一张图上
    
    参数:
    data_dict (dict): 包含每只股票分时数据的字典
    stock_names (dict): 股票代码到股票名称的映射
    date_str (str): 日期字符串，格式为 "YYYYMMDD"
    """
    if not data_dict:
        print("没有可用的数据进行绘图")
        return

    plt.figure(figsize=(15, 8))

    # 设置颜色循环
    colors = plt.cm.tab10(np.linspace(0, 1, len(data_dict)))

    first_df = None  # 用于确定x轴刻度
    
    # 用于确定y轴范围
    all_changes = []

    for i, ((stock_code, df), color) in enumerate(zip(data_dict.items(), colors)):
        if df is not None and not df.empty:
            if first_df is None:
                first_df = df  # 获取第一个有效的DataFrame
            stock_label = f"{stock_code} {stock_names.get(stock_code, '')}"
            # 使用从0开始的索引作为x轴
            x_indices = np.arange(len(df))
            plt.plot(x_indices, df['涨跌幅'], label=stock_label, color=color, linewidth=2)
            
            # 收集所有涨跌幅数据用于设置y轴范围
            all_changes.extend(df['涨跌幅'].tolist())
        else:
            print(f"跳过绘制股票 {stock_code}，因为数据为空")
    
    # 设置y轴范围确保能显示所有正负值
    if all_changes:
        min_change = min(all_changes)
        max_change = max(all_changes)
        # 增加一些边距使图表更美观
        y_margin = max(0.5, (max_change - min_change) * 0.1)  # 至少0.5%的边距或范围的10%
        plt.ylim(min_change - y_margin, max_change + y_margin)

    # 设置图表标题和标签
    date_formatted = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    plt.title(f"股票分时涨跌幅对比 ({date_formatted})", fontsize=16)
    plt.xlabel("时间", fontsize=12)
    plt.ylabel("涨跌幅 (%)", fontsize=12)

    # 设置x轴刻度和标签，跳过非交易时段
    if first_df is not None and len(first_df) >= 241:  # 检查是否有足够的数据点来设置标签
        num_points = len(first_df)
        
        # 确定刻度位置和标签 (合并 11:30 和 13:00)
        # tick_indices = [0, 60, 120, 121, 181, num_points - 1] # 原来的
        # tick_labels = ['09:30', '10:30', '11:30', '13:00', '14:00', '15:00'] # 原来的
        
        # 合并标签以避免重叠
        tick_indices = [0, 60, 120, 181, num_points - 1] 
        tick_labels = ['09:30', '10:30', '11:30/13:00', '14:00', '15:00']

        # 过滤掉可能超出范围的刻度
        valid_ticks = [(idx, lbl) for idx, lbl in zip(tick_indices, tick_labels) if 0 <= idx < num_points]
        
        # 特殊处理：如果最后一个点和14:00重合，只显示15:00
        if num_points - 1 == 181 and 181 in [item[0] for item in valid_ticks[:-1]]:
             valid_ticks = [(idx, lbl) for idx, lbl in valid_ticks if idx != 181 or idx == num_points -1]

        valid_indices = [item[0] for item in valid_ticks]
        valid_labels = [item[1] for item in valid_ticks]


        if len(valid_indices) > 1:
            # 设置刻度，不再需要旋转，因为重叠问题已通过合并解决
            plt.xticks(valid_indices, valid_labels) 
        else:
            print("警告：数据点不足或时间不连续，无法准确设置自定义时间轴标签。")
            # Fallback to default formatting if needed
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
    else:
        print("警告：无法获取用于设置时间轴的数据，或数据点不足。")
        pass  # Keep default ticks if no data

    # 添加网格线和图例
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(loc='best', fontsize=10)

    # 添加水平参考线（0%线）
    plt.axhline(y=0, color='gray', linestyle='-', alpha=0.5)

    plt.tight_layout()

    # 保存图表
    # save_path = f"e:\\demo\\MachineLearning\\HardTrading\\output\\time_sharing_{date_str}.png"
    # plt.savefig(save_path)
    # print(f"图表已保存至: {save_path}")

    # 显示图表
    plt.show()


def analyze_stocks_time_sharing(stock_codes, date_str):
    """
    主函数：获取并分析多只股票的分时数据
    
    参数:
    stock_codes (list): 股票代码列表，如 ["000001", "600000"]
    date_str (str): 日期字符串，格式为 "YYYYMMDD"，如 "20230601"
    """
    print(f"开始获取 {len(stock_codes)} 只股票在 {date_str} 的分时数据...")

    # 获取分时数据和股票名称
    data_dict, stock_names = fetch_time_sharing_data(stock_codes, date_str)

    # 绘制分时数据对比图
    plot_time_sharing_data(data_dict, stock_names, date_str)

    return data_dict


# 示例用法
if __name__ == "__main__":
    # 示例：多股分时图叠加
    stock_codes = ["002165", "002570", "600249", "001234", "601086"]
    date_str = "20250417"

    analyze_stocks_time_sharing(stock_codes, date_str)
