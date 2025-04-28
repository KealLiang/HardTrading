import os
from datetime import datetime, timedelta

import akshare as ak
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
# 引入距离计算和标准化工具
from scipy.spatial.distance import euclidean
from sklearn.preprocessing import minmax_scale

# 解决中文显示问题
matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 用黑体显示中文
matplotlib.rcParams['axes.unicode_minus'] = False  # 正常显示负号

save_dir = './images/time_price/'


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


def calculate_distance_matrix(data_dict):
    """
    计算每对股票归一化分时涨跌幅数据之间的欧氏距离
    
    参数:
    data_dict (dict): 包含每只股票分时数据的字典
    
    返回:
    np.array: 距离矩阵
    list: 股票代码列表，与矩阵顺序对应
    """
    stock_codes = list(data_dict.keys())
    n_stocks = len(stock_codes)

    # 提取并处理数据
    data_list = []
    max_length = 0
    for code in stock_codes:
        df = data_dict.get(code)
        if df is not None and not df.empty and '涨跌幅' in df.columns:
            series = df['涨跌幅'].values
            data_list.append(series)
            max_length = max(max_length, len(series))
        else:
            data_list.append(None)  # 标记无效数据

    if max_length == 0:
        print("错误：所有股票数据均无效或为空，无法计算距离。")
        return np.full((n_stocks, n_stocks), np.inf), stock_codes  # 返回无穷大距离

    # 归一化数据并处理缺失
    normalized_data = []
    for series in data_list:
        if series is not None:
            # 填充或截断到统一长度
            if len(series) < max_length:
                # 用最后一个有效值填充 (或使用NaN)
                padded = np.pad(series, (0, max_length - len(series)), mode='edge')
                # padded = np.pad(series, (0, max_length - len(series)), mode='constant', constant_values=np.nan)
            else:
                padded = series[:max_length]

            # 检查是否存在NaN或inf，如果存在则跳过归一化或处理
            if np.any(np.isnan(padded)) or np.any(np.isinf(padded)):
                print(f"警告: 数据包含NaN或inf，将使用原始填充数据进行距离计算。")
                norm_series = padded  # 或者可以选择填充NaN为0或其他策略
            else:
                # 归一化到 [0, 1] 区间
                norm_series = minmax_scale(padded.reshape(-1, 1)).flatten()
            normalized_data.append(norm_series)
        else:
            normalized_data.append(np.full(max_length, np.nan))  # 无效数据用NaN填充

    # 计算距离矩阵
    distance_matrix = np.full((n_stocks, n_stocks), np.inf)

    for i in range(n_stocks):
        for j in range(i, n_stocks):  # 仅计算上三角
            if i == j:
                distance_matrix[i, j] = 0.0
            else:
                data_i = normalized_data[i]
                data_j = normalized_data[j]

                # 仅在两个序列都有效时计算距离
                valid_mask = ~np.isnan(data_i) & ~np.isnan(data_j)
                if np.sum(valid_mask) > 1:  # 至少需要两个共同的有效点
                    dist = euclidean(data_i[valid_mask], data_j[valid_mask])
                    # 可以根据序列长度进行归一化，使得距离与长度无关
                    normalized_dist = dist / np.sqrt(np.sum(valid_mask))
                    distance_matrix[i, j] = normalized_dist
                    distance_matrix[j, i] = normalized_dist  # 矩阵是对称的
                else:
                    # 如果没有足够的共同点，视为距离无限大
                    distance_matrix[i, j] = np.inf
                    distance_matrix[j, i] = np.inf

    return distance_matrix, stock_codes


def plot_time_sharing_data(data_dict, stock_names, date_str, deviation_data=None):
    """
    将多只股票的分时数据绘制在同一张图上，根据数据点接近程度优化视觉区分
    
    参数:
    data_dict (dict): 包含每只股票分时数据的字典
    stock_names (dict): 股票代码到股票名称的映射
    date_str (str): 日期字符串，格式为 "YYYYMMDD"
    deviation_data (dict, optional): 股票代码到偏离度数据的映射，格式为 {code: {'10d': value, '30d': value}}
    """
    if not data_dict:
        print("没有可用的数据进行绘图")
        return

    plt.figure(figsize=(15, 8))

    # 设置颜色循环
    colors = plt.cm.tab10(np.linspace(0, 1, len(data_dict)))
    # 定义线型和标记
    linestyles = ['-', '--', '-.', ':']
    markers = ['o', 's', '^', 'v', 'D', 'x', '+', '*', '.', ',']  # 增加更多标记
    marker_sizes = {'o': 4, 's': 4, '^': 5, 'v': 5, 'D': 4, 'x': 5, '+': 6, '*': 6, '.': 3, ',': 3}  # 调整大小
    linewidths = [1.5, 2, 1.5, 2]  # 可以交替线宽

    # 计算距离矩阵
    distance_matrix, ordered_stocks = calculate_distance_matrix(data_dict)
    # 距离阈值，小于此值认为两条线过于接近 - 稍微降低阈值
    distance_threshold = 0.08

    # 存储已分配的视觉属性，用于避免与接近的线重复
    assigned_properties = {}
    plotted_indices = []  # 存储已绘制股票的索引

    first_df = None
    all_changes = []

    # 绘制图形
    for i, stock_code in enumerate(ordered_stocks):
        df = data_dict.get(stock_code)
        if df is None or df.empty or '涨跌幅' not in df.columns:
            print(f"跳过绘制股票 {stock_code}，因为数据无效或缺失")
            continue

        if first_df is None:
            first_df = df

        series = df['涨跌幅']
        all_changes.extend(series.tolist())

        # --- 确定视觉属性 --- 
        current_props = {}

        # 查找与当前股票最接近的 *已绘制* 股票
        min_dist = np.inf
        closest_plotted_idx = -1
        closest_stock_code = None
        for plotted_idx in plotted_indices:
            dist = distance_matrix[i, plotted_idx]
            if dist < min_dist:
                min_dist = dist
                closest_plotted_idx = plotted_idx
                closest_stock_code = ordered_stocks[plotted_idx]

        # 默认视觉属性 (基于当前股票的索引 i 循环获取)
        base_color = colors[i % len(colors)]
        base_linestyle = linestyles[i % len(linestyles)]
        base_marker = markers[i % len(markers)]
        base_linewidth = linewidths[i % len(linewidths)]
        base_markevery = max(1, len(series) // 15)  # 调整标记密度
        base_markersize = marker_sizes.get(base_marker, 5)

        # 先赋值默认值
        current_props['color'] = base_color
        current_props['linestyle'] = base_linestyle
        current_props['marker'] = base_marker
        current_props['linewidth'] = base_linewidth
        current_props['markevery'] = base_markevery
        current_props['markersize'] = base_markersize

        if closest_plotted_idx != -1 and min_dist < distance_threshold:
            # 如果存在非常接近的已绘制线条
            closest_props = assigned_properties[closest_stock_code]
            print(
                f"股票 {stock_code} 与 {closest_stock_code} 距离 ({min_dist:.3f}) 小于阈值 {distance_threshold}，尝试调整视觉属性。")

            # 改进的样式选择逻辑：
            # 目标：选择一个与 closest_props 不同的 (linestyle, marker) 组合
            found_different_style = False
            # 优先尝试不同的线型
            for try_ls_idx in range(1, len(linestyles)):
                new_ls_idx = (i + try_ls_idx) % len(linestyles)
                new_ls = linestyles[new_ls_idx]
                if new_ls != closest_props.get('linestyle'):
                    current_props['linestyle'] = new_ls
                    # 线型不同了，标记可以使用默认或也尝试换一个
                    current_props['marker'] = base_marker  # 保持默认标记通常足够
                    found_different_style = True
                    print(f"  - 分配不同线型: {new_ls}")
                    break

            # 如果所有线型都与最近的线相同（不太可能但处理一下），则必须分配不同的标记
            if not found_different_style:
                current_props['linestyle'] = base_linestyle  # 保持默认线型
                for try_m_idx in range(1, len(markers)):
                    new_m_idx = (i + try_m_idx) % len(markers)
                    new_m = markers[new_m_idx]
                    if new_m != closest_props.get('marker'):
                        current_props['marker'] = new_m
                        current_props['markersize'] = marker_sizes.get(new_m, 5)
                        found_different_style = True
                        print(f"  - 线型无法区分，分配不同标记: {new_m}")
                        break

            # 如果连标记都找不到不同的（几乎不可能），就放弃治疗，使用默认值
            if not found_different_style:
                print(f"  - 警告：无法找到与 {closest_stock_code} 显著不同的线型或标记组合，使用默认样式。")
                # 使用前面已设置的默认值

        # 记录最终分配的属性
        assigned_properties[stock_code] = current_props
        plotted_indices.append(i)
        # --- 属性确定完毕 --- 

        # 准备股票标签，可能包含偏离度信息
        stock_label = f"{stock_code} {stock_names.get(stock_code, '')}"

        # 如果提供了偏离度数据，添加到标签中
        if deviation_data and stock_code in deviation_data:
            dev_10d = deviation_data[stock_code].get('10d', 0)
            dev_30d = deviation_data[stock_code].get('30d', 0)
            # 取整数显示偏离度
            stock_label += f" [10d:{int(round(dev_10d))}% 30d:{int(round(dev_30d))}%]"

        x_indices = np.arange(len(series))

        plt.plot(x_indices, series,
                 label=stock_label,
                 color=current_props['color'],
                 linestyle=current_props['linestyle'],
                 linewidth=current_props['linewidth'],
                 marker=current_props['marker'],
                 markevery=current_props['markevery'],
                 markersize=current_props['markersize'])

    # 设置y轴范围
    if all_changes:
        # 移除NaN和inf值以确定范围
        valid_changes = [c for c in all_changes if pd.notna(c) and np.isfinite(c)]
        if valid_changes:
            min_change = min(valid_changes)
            max_change = max(valid_changes)
            y_margin = max(0.5, (max_change - min_change) * 0.1)
            plt.ylim(min_change - y_margin, max_change + y_margin)
        else:
            print("警告：无法根据有效数据设置Y轴范围。")

    # 设置图表标题和标签
    date_formatted = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    plt.title(f"股票分时涨跌幅对比 ({date_formatted})", fontsize=16)
    plt.xlabel("时间", fontsize=12)
    plt.ylabel("涨跌幅 (%)", fontsize=12)

    # 设置x轴刻度标签 (与之前逻辑相同)
    if first_df is not None and len(first_df) >= 241:
        num_points = len(first_df)
        tick_indices = [0, 60, 120, 181, num_points - 1]
        tick_labels = ['09:30', '10:30', '11:30/13:00', '14:00', '15:00']
        valid_ticks = [(idx, lbl) for idx, lbl in zip(tick_indices, tick_labels) if 0 <= idx < num_points]
        if num_points - 1 == 181 and 181 in [item[0] for item in valid_ticks[:-1]]:
            valid_ticks = [(idx, lbl) for idx, lbl in valid_ticks if idx != 181 or idx == num_points - 1]
        valid_indices = [item[0] for item in valid_ticks]
        valid_labels = [item[1] for item in valid_ticks]
        if len(valid_indices) > 1:
            plt.xticks(valid_indices, valid_labels)
        else:
            print("警告：数据点不足或时间不连续，无法准确设置自定义时间轴标签。")
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
    else:
        print("警告：无法获取用于设置时间轴的数据，或数据点不足。")
        pass

    # 添加网格线和图例
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.legend(loc='best', fontsize=10)

    plt.tight_layout()

    # -- 保存图表 --
    os.makedirs(save_dir, exist_ok=True)  # 确保目录存在
    save_filename = os.path.join(save_dir, f"time_price_sharing_{date_str}.png")
    plt.savefig(save_filename)
    print(f"图表已保存至: {save_filename}")

    # 显示图表
    # plt.show()


def analyze_stocks_time_sharing(stock_codes, date_list, deviation_data=None):
    """
    主函数：获取并分析多只股票在多个日期内的分时数据，并保存图表
    
    参数:
    stock_codes (list): 股票代码列表，如 ["000001", "600000"]
    dates (list): 日期字符串列表，格式为 ["YYYYMMDD", "YYYYMMDD"], 如 ["20230601", "20230602"]
    deviation_data (dict, optional): 股票代码到偏离度数据的映射，格式为 {code: {'10d': value, '30d': value}}
    """
    if not isinstance(date_list, list):
        date_list = [date_list]  # 如果传入的是单个日期字符串，转为列表

    for date_str in date_list:
        print(f"\n--- 开始处理日期: {date_str} ---")
        print(f"开始获取 {len(stock_codes)} 只股票在 {date_str} 的分时数据...")

        # 获取分时数据和股票名称
        data_dict, stock_names = fetch_time_sharing_data(stock_codes, date_str)

        # 绘制分时数据对比图并保存
        if data_dict:  # 仅在获取到数据时绘图
            plot_time_sharing_data(data_dict, stock_names, date_str, deviation_data)
        else:
            print(f"日期 {date_str} 未获取到任何有效数据，跳过绘图。")


def analyze_abnormal_stocks_time_sharing(date_list=None, excel_file_path='./excel/serious_abnormal_history.xlsx'):
    """
    读取serious_abnormal_history.xlsx中的异动股票数据，生成分时图
    
    参数:
    date_list (list, optional): 日期字符串列表，格式为 ["YYYYMMDD", ...], 如 ["20230601"]. 
                              如果为None，则使用Excel中的所有日期。
    """
    try:
        df = pd.read_excel(excel_file_path)
        print(f"成功读取异动股票数据，共 {len(df)} 条记录")
    except Exception as e:
        print(f"读取Excel文件出错: {e}")
        return

    # 筛选【异动方向】为上涨且股票名称不带"ST"的数据
    filtered_df = df[(df['异动方向'] == "上涨") & (~df['股票名称'].str.contains('ST', na=False))]
    print(f"筛选后的上涨非ST股票数据: {len(filtered_df)} 条记录")

    # 如果没有指定日期，则使用Excel中的所有日期
    if date_list is None or len(date_list) == 0:
        unique_dates = filtered_df['日期'].unique()
        date_list = [d.strftime("%Y%m%d") for d in pd.to_datetime(unique_dates)]
        print(f"未指定日期，将使用Excel中的所有 {len(date_list)} 个日期")

    # 按日期处理
    for date_str in date_list:
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        date_formatted = date_obj.strftime("%Y-%m-%d")

        # 筛选该日期的股票
        date_stocks = filtered_df[pd.to_datetime(filtered_df['日期']).dt.strftime("%Y-%m-%d") == date_formatted]

        if len(date_stocks) > 0:
            # 按30日偏离度和10日偏离度降序排序
            date_stocks = date_stocks.sort_values(by=['30日偏离度(%)', '10日偏离度(%)'], ascending=False)

            # 获取股票代码列表和偏离度数据
            stock_codes = []
            deviation_data = {}  # 用于存储偏离度数据

            for _, row in date_stocks.iterrows():
                code = row['股票代码']
                # 确保股票代码为字符串格式并补齐6位
                if isinstance(code, (int, float)):
                    code_str = str(int(code)).zfill(6)
                elif isinstance(code, str):
                    code_str = code.zfill(6)
                else:
                    continue  # 跳过无法处理的代码

                stock_codes.append(code_str)

                # 收集偏离度数据
                deviation_data[code_str] = {
                    '10d': row['10日偏离度(%)'] if '10日偏离度(%)' in row else 0,
                    '30d': row['30日偏离度(%)'] if '30日偏离度(%)' in row else 0
                }

            print(f"日期 {date_formatted} 有 {len(stock_codes)} 只符合条件的异动股票")

            # 调用time_price_sharing的函数生成分时图，传递偏离度数据
            analyze_stocks_time_sharing(stock_codes, date_str, deviation_data)
        else:
            print(f"日期 {date_formatted} 没有符合条件的异动股票数据")


# 示例用法
if __name__ == "__main__":
    # 方法1：手动指定股票和日期
    # codes = ["002165", "002570", "600249", "001234", "601086"]
    # dates = ["20250416", "20250417", "20250418"]
    # analyze_stocks_time_sharing(codes, dates)

    # 方法2：从异动股票Excel中读取数据并生成分时图
    # 指定特定日期
    dates_list = ["20250422"]  # 可以指定多个日期
    analyze_abnormal_stocks_time_sharing(dates_list)

    # 不指定日期，使用Excel中的所有日期
    # analyze_abnormal_stocks_time_sharing()
