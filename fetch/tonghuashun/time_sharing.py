import akshare as ak
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
import matplotlib

# 解决中文显示问题
matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 用黑体显示中文
matplotlib.rcParams['axes.unicode_minus'] = False    # 正常显示负号

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
                
            # 使用akshare获取分时数据
            df = ak.stock_zh_a_hist_min_em(symbol=stock_code, period='1', start_date=date_str, end_date=date_str)
            
            if df is not None and not df.empty:
                # 处理日期时间格式
                df['datetime'] = pd.to_datetime(df['时间'])
                # 计算相对于开盘价的涨跌幅
                first_price = df.iloc[0]['收盘']
                df['涨跌幅'] = (df['收盘'] / first_price - 1) * 100
                
                # 过滤掉休市时间段 (11:30-13:00)
                df = df[~((df['datetime'].dt.hour == 11) & (df['datetime'].dt.minute >= 30)) & 
                         ~((df['datetime'].dt.hour == 12))]
                
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
    
    for (stock_code, df), color in zip(data_dict.items(), colors):
        stock_label = f"{stock_code} {stock_names.get(stock_code, '')}"
        plt.plot(df['datetime'], df['涨跌幅'], label=stock_label, color=color, linewidth=2)
    
    # 设置图表标题和标签
    date_formatted = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    plt.title(f"股票分时涨跌幅对比 ({date_formatted})", fontsize=16)
    plt.xlabel("时间", fontsize=12)
    plt.ylabel("涨跌幅 (%)", fontsize=12)
    
    # 设置x轴时间格式，只显示交易时间段
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=1))
    
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
    stock_codes = ["002165", "002570", "600249"]
    date_str = "20250416"
    
    analyze_stocks_time_sharing(stock_codes, date_str)