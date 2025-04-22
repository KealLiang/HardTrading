from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import re

# 设置 matplotlib 的字体为支持中文的字体
plt.rcParams['font.sans-serif'] = ['SimHei']  # 'SimHei' 是黑体的意思
plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号


def read_and_plot_data(fupan_file, start_date=None, end_date=None):
    # 读取 Excel 中的三个 sheet：连板数据、跌停数据和首板数据
    lianban_data = pd.read_excel(fupan_file, sheet_name="连板数据", index_col=0)
    dieting_data = pd.read_excel(fupan_file, sheet_name="跌停数据", index_col=0)
    shouban_data = pd.read_excel(fupan_file, sheet_name="首板数据", index_col=0)

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
    lianban_second_results = []  # 存储连续涨停天数次高值及其股票
    dieting_results = []  # 存储连续跌停天数最大值及其股票
    shouban_counts = []  # 存储每日首板数量
    max_ji_ban_results = []  # 存储每日最高几板值及其股票

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
        
        # 从"几天几板"中提取"几板"数值
        def extract_ji_ban(ji_tian_ji_ban):
            match = re.search(r'(\d+)天(\d+)板', str(ji_tian_ji_ban))
            if match:
                return int(match.group(2))  # 返回"几板"的数值
            return 0
            
        lianban_df['几板'] = lianban_df['几天几板'].apply(extract_ji_ban)
        
        # 提取最高几板股
        max_ji_ban = lianban_df['几板'].max()
        max_ji_ban_stocks = lianban_df[lianban_df['几板'] == max_ji_ban]['股票简称'].tolist()
        max_ji_ban_results.append((date, max_ji_ban, max_ji_ban_stocks))

        # 提取最高连板股
        max_lianban = lianban_df['连续涨停天数'].max()
        max_lianban_stocks = lianban_df[lianban_df['连续涨停天数'] == max_lianban]['股票简称'].tolist()

        # 提取次高连板股
        second_lianban = lianban_df[lianban_df['连续涨停天数'] < max_lianban]['连续涨停天数'].max()
        if pd.isna(second_lianban):  # 处理可能的NaN值
            second_lianban = 0
        second_lianban_stocks = lianban_df[lianban_df['连续涨停天数'] == second_lianban]['股票简称'].tolist()

        lianban_results.append((date, max_lianban, max_lianban_stocks))
        lianban_second_results.append((date, second_lianban, second_lianban_stocks))  # 存储次高连板股

        # 跌停数据处理
        dieting_col = dieting_data[date].dropna()  # 去除空单元格
        dieting_col = dieting_col.fillna('').astype(str)  # 填充空数据
        dieting_stocks = dieting_col.str.split(';').apply(lambda x: [item.strip() for item in x])  # 分列处理
        dieting_df = pd.DataFrame(dieting_stocks.tolist(), columns=[
            '股票代码', '股票简称', '跌停开板次数', '首次跌停时间',
            '跌停类型', '最新价', '最新涨跌幅',
            '连续跌停天数', '跌停原因类型'
        ])
        if not dieting_df.empty:
            dieting_df['连续跌停天数'] = dieting_df['连续跌停天数'].astype(int)
            max_dieting = dieting_df['连续跌停天数'].max()
            max_dieting_stocks = dieting_df[dieting_df['连续跌停天数'] == max_dieting]['股票简称'].tolist()
        else:
            max_dieting = 0
            max_dieting_stocks = []
        dieting_results.append((date, -max_dieting, max_dieting_stocks))  # 跌停天数为负数

        # 首板数据处理
        shouban_col = shouban_data[date].dropna()  # 去除空单元格
        shouban_counts.append(len(shouban_col))  # 统计每日首板数量

    # 绘图
    fig, ax = plt.subplots(figsize=(21, 9))
    
    # 辅助函数：快速放置标签，优化性能
    def place_labels(x, y, labels, color, line_type=None):
        # 标签格子系统 - 将图表区域划分为网格，用于快速检测碰撞
        grid_size = 1.0  # 格子大小
        label_grid = {}  # 格子占用情况
        text_objects = []  # 保存所有文本对象
        
        # 处理任何可能的NaN值
        cleaned_data = []
        for i, (xi, yi, label) in enumerate(zip(x, y, labels)):
            if pd.isna(yi):  # 跳过y值为NaN的点
                continue
            cleaned_data.append((i, xi, yi, label))
        
        if not cleaned_data:  # 如果没有有效数据点
            return
            
        # 按日期将点分组
        date_clusters = {}
        for i, xi, yi, label in cleaned_data:
            date_str = xi.strftime('%Y-%m-%d')
            if date_str not in date_clusters:
                date_clusters[date_str] = []
            date_clusters[date_str].append((i, xi, yi, label))
        
        # 预定义位置模板 - 右、左、上、下四个方向的固定偏移量
        position_templates = [
            {'name': 'right', 'ha': 'left', 'va': 'center', 'dx': 10, 'dy': 0},
            {'name': 'left', 'ha': 'right', 'va': 'center', 'dx': -10, 'dy': 0},
            {'name': 'top', 'ha': 'center', 'va': 'bottom', 'dx': 0, 'dy': 10},
            {'name': 'bottom', 'ha': 'center', 'va': 'top', 'dx': 0, 'dy': -10},
        ]
        
        # 根据线条类型的偏移调整
        line_offset = 0
        if line_type == 'main':
            line_offset = 5
        elif line_type == 'secondary':
            line_offset = -5
            
        # 设置标签大致尺寸估计值 (宽度，高度)
        estimated_label_size = (1.5, 0.8)  # 根据实际情况调整
            
        # 处理每个日期组的点
        for date_str, points in date_clusters.items():
            # 按Y值排序
            points.sort(key=lambda p: p[2])
            
            # 为每个点放置标签
            for j, (i, xi, yi, label) in enumerate(points):
                # 如果标签为空或者y值无效，跳过
                if not label or pd.isna(yi):
                    continue
                    
                # 为点选择一个位置模板
                template_idx = j % len(position_templates)
                position = position_templates[template_idx].copy()
                
                # 对主要/次要线条应用额外偏移
                if position['name'] in ['top', 'bottom']:
                    position['dy'] += line_offset
                else:
                    position['dx'] += line_offset
                
                # 尝试多个位置直到找到无碰撞的位置
                found_position = False
                
                # 记录已尝试的位置
                tried_positions = set()
                
                # 尝试所有4个基本位置
                for attempt in range(len(position_templates)):
                    # 选择下一个位置模板
                    template_idx = (j + attempt) % len(position_templates)
                    position = position_templates[template_idx].copy()
                    
                    # 对主要/次要线条应用额外偏移
                    if position['name'] in ['top', 'bottom']:
                        position['dy'] += line_offset
                    else:
                        position['dx'] += line_offset
                    
                    # 计算标签的大致位置
                    pos_key = (position['dx'], position['dy'])
                    if pos_key in tried_positions:
                        continue
                    tried_positions.add(pos_key)
                        
                    # 将日期时间转换为数值以用于网格计算
                    # 使用简单序号而不是实际时间
                    try:
                        date_index = list(date_clusters.keys()).index(date_str)
                        grid_x = date_index
                        grid_y = int(yi) if abs(yi) < 1000 else int(yi / grid_size)  # 安全转换
                    except (ValueError, TypeError):
                        continue  # 如果转换失败，尝试下一个位置
                    
                    # 检查该区域是否已有标签
                    collision = False
                    label_width, label_height = estimated_label_size
                    
                    # 确定标签相对于点的位置
                    if position['name'] == 'right':
                        grid_cells = [(grid_x + dx, grid_y + dy) 
                                    for dx in range(1, int(label_width) + 2)
                                    for dy in range(-int(label_height), int(label_height) + 1)]
                    elif position['name'] == 'left':
                        grid_cells = [(grid_x - dx, grid_y + dy) 
                                    for dx in range(1, int(label_width) + 2)
                                    for dy in range(-int(label_height), int(label_height) + 1)]
                    elif position['name'] == 'top':
                        grid_cells = [(grid_x + dx, grid_y + dy) 
                                    for dx in range(-int(label_width), int(label_width) + 1)
                                    for dy in range(1, int(label_height) + 2)]
                    else:  # 'bottom'
                        grid_cells = [(grid_x + dx, grid_y - dy) 
                                    for dx in range(-int(label_width), int(label_width) + 1)
                                    for dy in range(1, int(label_height) + 2)]
                    
                    # 快速检查这些格子是否已被占用
                    for cell in grid_cells:
                        if cell in label_grid:
                            collision = True
                            break
                    
                    if not collision:
                        # 标记这些格子为已占用
                        for cell in grid_cells:
                            label_grid[cell] = True
                        found_position = True
                        break
                
                # 如果四个基本位置都有碰撞，尝试微调位置
                if not found_position:
                    # 返回到初始位置模板
                    template_idx = j % len(position_templates)
                    position = position_templates[template_idx].copy()
                    
                    # 尝试小偏移
                    for offset_x in [-15, 0, 15]:
                        for offset_y in [-15, 0, 15]:
                            # 跳过已尝试的位置
                            if offset_x == 0 and offset_y == 0:
                                continue
                                
                            adjusted_dx = position['dx'] + offset_x
                            adjusted_dy = position['dy'] + offset_y
                            
                            pos_key = (adjusted_dx, adjusted_dy)
                            if pos_key in tried_positions:
                                continue
                            tried_positions.add(pos_key)
                            
                            # 同样的碰撞检测逻辑
                            try:
                                date_index = list(date_clusters.keys()).index(date_str)
                                grid_x = date_index
                                grid_y = int(yi) if abs(yi) < 1000 else int(yi / grid_size)  # 安全转换
                            except (ValueError, TypeError):
                                continue
                            
                            # 简化，只检查基本方向
                            dx_sign = 1 if adjusted_dx >= 0 else -1
                            dy_sign = 1 if adjusted_dy >= 0 else -1
                            
                            grid_cells = []
                            label_width, label_height = estimated_label_size
                            
                            if abs(adjusted_dx) > abs(adjusted_dy):  # 水平为主
                                grid_cells = [(grid_x + dx_sign * dx, grid_y + dy) 
                                            for dx in range(1, int(label_width) + 2)
                                            for dy in range(-int(label_height), int(label_height) + 1)]
                            else:  # 垂直为主
                                grid_cells = [(grid_x + dx, grid_y + dy_sign * dy) 
                                            for dx in range(-int(label_width), int(label_width) + 1)
                                            for dy in range(1, int(label_height) + 2)]
                            
                            collision = False
                            for cell in grid_cells:
                                if cell in label_grid:
                                    collision = True
                                    break
                            
                            if not collision:
                                position['dx'] = adjusted_dx
                                position['dy'] = adjusted_dy
                                # 标记这些格子为已占用
                                for cell in grid_cells:
                                    label_grid[cell] = True
                                found_position = True
                                break
                            
                        if found_position:
                            break
                
                # 创建文本对象并添加到图表
                text = ax.annotate(
                    label.replace(', ', '\n'), 
                    xy=(xi, yi),
                    xytext=(position['dx'], position['dy']),
                    textcoords='offset points',
                    fontsize=7,
                    va=position['va'],
                    ha=position['ha'],
                    color=color,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.8, ec=color, lw=0.5),
                    zorder=100  # 确保标签始终在最上层
                )
                text_objects.append(text)

    # 提取数据并绘制最高连板折线
    lianban_dates = [datetime.strptime(item[0], "%Y年%m月%d日") for item in lianban_results]
    lianban_days = [item[1] for item in lianban_results]
    lianban_labels = [', '.join(item[2]) for item in lianban_results]
    ax.plot(lianban_dates, lianban_days, label='最高连续涨停天数', color='red', marker='o', alpha=0.7)
    place_labels(lianban_dates, lianban_days, lianban_labels, 'red', 'main')

    # 提取数据并绘制次高连板折线
    lianban_second_days = [item[1] for item in lianban_second_results]
    lianban_second_labels = [', '.join(item[2]) for item in lianban_second_results]
    ax.plot(lianban_dates, lianban_second_days, label='次高连续涨停天数', color='pink', marker='D', linestyle='-.', alpha=0.6)
    place_labels(lianban_dates, lianban_second_days, lianban_second_labels, 'pink', 'secondary')
                
    # 提取数据并绘制最高几板折线
    max_ji_ban_values = [item[1] for item in max_ji_ban_results]
    max_ji_ban_labels = [', '.join(item[2]) for item in max_ji_ban_results]
    ax.plot(lianban_dates, max_ji_ban_values, label='最高几板', color='purple', marker='*')
    place_labels(lianban_dates, max_ji_ban_values, max_ji_ban_labels, 'purple', 'main')

    # 提取数据并绘制跌停折线
    dieting_days = [item[1] for item in dieting_results]
    dieting_labels = [', '.join(item[2][:10]) + f'...{len(item[2])}' if len(item[2]) > 10 else ', '.join(item[2])
                      for item in dieting_results]  # 太长则省略
    ax.plot(lianban_dates, dieting_days, label='连续跌停天数', color='green', marker='s')
    place_labels(lianban_dates, dieting_days, dieting_labels, 'green', 'secondary')

    # 添加副坐标轴并绘制首板数量折线
    ax2 = ax.twinx()  # 创建副坐标轴
    ax2.plot(lianban_dates, shouban_counts, label='首板数量', color='blue', marker='p', linestyle='--', alpha=0.1)
    ax2.set_ylabel('数量', fontsize=12)  # 设置副 y 轴标签

    # 设置图表信息
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')  # 添加水平参考线
    ax.set_title("连板/跌停/首板个股走势", fontsize=16)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("天数/板数", fontsize=12)  # 更新Y轴标签
    ax.set_xticks(lianban_dates)  # 设置横轴刻度为所有日期
    ax.set_xticklabels([date.strftime('%Y-%m-%d') for date in lianban_dates], rotation=45, fontsize=9, ha='right')
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))  # 设置 y 轴刻度为整数
    ax.legend(loc='upper left')  # 主 y 轴图例
    ax2.legend(loc='upper right')  # 副 y 轴图例
    plt.tight_layout()
    plt.show()
    # plt.savefig("fupan_lb.png", format='png')
    # plt.close()


def draw_fupan_lb(start_date=None, end_date=None):
    # 示例调用
    fupan_file = "./excel/fupan_stocks.xlsx"
    read_and_plot_data(fupan_file, start_date, end_date)


if __name__ == '__main__':
    start_date = '20241201'  # 开始日期
    # end_date = '20241101'  # 结束日期
    end_date = None
    draw_fupan_lb(start_date, end_date)
