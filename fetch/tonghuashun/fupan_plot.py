from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import re
import math

# 设置 matplotlib 的字体为支持中文的字体
plt.rcParams['font.sans-serif'] = ['SimHei']  # 'SimHei' 是黑体的意思
plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

# 标签配置参数
LABEL_CONFIG = {
    'font_size': 7,                 # 标签字体大小
    'width': 1.5,                   # 标签估计宽度
    'height': 0.8,                  # 标签估计高度
    'base_offset': 3,               # 基础偏移距离
    'max_offset': 20,                # 最大偏移距离
    'search_radius': 10,             # 搜索半径
    'alpha': 0.8,                   # 标签背景透明度
    'padding': 0.2,                 # 标签内边距
}


# 全局标签管理类，用于处理重叠点的标签
class GlobalLabelManager:
    def __init__(self):
        self.points = {}  # 格式: {date_str: {y_value: [(line_type, priority)]}}
        self.label_positions = []  # 记录所有已放置标签的位置 [(date_idx, y, width, height), ...]
        
    def register_point(self, date_str, y_value, line_type, priority):
        """记录一个数据点的位置和优先级"""
        if date_str not in self.points:
            self.points[date_str] = {}
            
        y_key = self._get_y_key(y_value)
        
        if y_key not in self.points[date_str]:
            self.points[date_str][y_key] = []
            
        self.points[date_str][y_key].append((line_type, priority))
        
    def is_highest_priority(self, date_str, y_value, line_type, priority):
        """检查给定点是否是当前位置的最高优先级"""
        if date_str not in self.points:
            return True
            
        y_key = self._get_y_key(y_value)
        
        if y_key not in self.points[date_str]:
            return True
            
        points_at_position = self.points[date_str][y_key]
        
        # 检查是否有其他点的优先级高于当前点
        for other_line_type, other_priority in points_at_position:
            if other_priority > priority:
                return False
                
        return True
        
    def get_points_count_at(self, date_str, y_value):
        """获取指定位置有多少个点"""
        if date_str not in self.points:
            return 0
            
        y_key = self._get_y_key(y_value)
        
        if y_key not in self.points[date_str]:
            return 0
            
        return len(self.points[date_str][y_key])
        
    def _get_y_key(self, y_value):
        """获取y值的键，用于近似比较"""
        if abs(y_value) < 1000:
            return int(y_value)
        return int(y_value / 0.5)  # 使用网格大小做近似
        
    def add_label_position(self, date_index, y, width, height):
        """记录已经放置的标签位置"""
        self.label_positions.append((date_index, y, width, height))
        
    def check_collision(self, date_index, y, width, height):
        """检查是否与已有标签重叠"""
        for pos_x, pos_y, pos_w, pos_h in self.label_positions:
            # 检查日期是否相同或相邻
            if abs(pos_x - date_index) > 1:
                continue
                
            # 检查是否重叠
            if (date_index < pos_x + pos_w and
                date_index + width > pos_x and
                y < pos_y + pos_h and
                y + height > pos_y):
                return True
                
        return False
        
    def find_best_empty_space(self, date_index, y, width, height, search_radius=None):
        """在周围寻找最佳的空白空间放置标签"""
        if search_radius is None:
            search_radius = LABEL_CONFIG['search_radius']
            
        if not self.label_positions:
            return 0, 0  # 没有其他标签，使用默认位置
            
        best_pos = None
        min_distance = float('inf')
        
        # 尝试不同的位置
        for dx in range(-search_radius, search_radius + 1):
            for dy in range(-search_radius, search_radius + 1):
                if dx == 0 and dy == 0:
                    continue  # 跳过原始位置
                    
                new_x = date_index + dx * 0.2  # 细分搜索空间
                new_y = y + dy * 0.2
                
                # 检查是否重叠
                if not self.check_collision(new_x, new_y, width, height):
                    # 计算与原点的距离
                    distance = math.sqrt(dx*dx + dy*dy)
                    if distance < min_distance:
                        min_distance = distance
                        best_pos = (dx * 0.2, dy * 0.2)
                        
        return best_pos if best_pos else (0, 0)


def read_and_plot_data(fupan_file, start_date=None, end_date=None, label_config=None):
    # 使用默认配置或传入的配置
    config = LABEL_CONFIG.copy()
    if label_config:
        config.update(label_config)
        
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
    
    # 创建全局标签管理器
    global_label_manager = GlobalLabelManager()
    
    # 辅助函数：智能放置标签，优化性能
    def place_labels(x, y, labels, color, line_type=None, priority=1):
        # 处理任何可能的NaN值
        cleaned_data = []
        for i, (xi, yi, label) in enumerate(zip(x, y, labels)):
            if pd.isna(yi):  # 跳过y值为NaN的点
                continue
            cleaned_data.append((i, xi, yi, label))
        
        if not cleaned_data:  # 如果没有有效数据点
            return
            
        # 按日期将点分组并记录所有数据点
        date_clusters = {}
        all_points = []
        
        for i, xi, yi, label in cleaned_data:
            date_str = xi.strftime('%Y-%m-%d') if isinstance(xi, datetime) else str(xi)
            if date_str not in date_clusters:
                date_clusters[date_str] = []
            date_clusters[date_str].append((i, xi, yi, label))
            all_points.append((date_str, yi, label, priority))
        
        # 注册每个点到全局管理器
        for date_str, points in date_clusters.items():
            for i, xi, yi, label in points:
                global_label_manager.register_point(date_str, yi, line_type, priority)
        
        # 预先计算日期索引映射
        date_to_index = {date: idx for idx, date in enumerate(date_clusters.keys())}
        
        # 将所有点按优先级排序，高优先级先处理
        all_points.sort(key=lambda p: p[3], reverse=True)
        
        # 预定义位置模板 - 右、左、上、下四个方向的固定偏移量
        base_offset = config['base_offset']
        position_templates = [
            {'name': 'right', 'ha': 'left', 'va': 'center', 'dx': base_offset, 'dy': 0},
            {'name': 'left', 'ha': 'right', 'va': 'center', 'dx': -base_offset, 'dy': 0},
            {'name': 'top', 'ha': 'center', 'va': 'bottom', 'dx': 0, 'dy': base_offset},
            {'name': 'bottom', 'ha': 'center', 'va': 'top', 'dx': 0, 'dy': -base_offset},
        ]
        
        # 附加偏移模板 - 用于尝试更多位置
        max_offset = config['max_offset']
        mid_offset = max_offset // 2
        additional_offsets = [
            (mid_offset, mid_offset), (mid_offset, -mid_offset), (-mid_offset, mid_offset), (-mid_offset, -mid_offset),  # 对角线方向
            (max_offset, 0), (-max_offset, 0), (0, max_offset), (0, -max_offset),  # 更远的直线方向
            (max_offset, mid_offset), (max_offset, -mid_offset), (-max_offset, mid_offset), (-max_offset, -mid_offset),  # 更远的对角线
        ]
            
        # 设置标签大致尺寸估计值
        estimated_label_size = (config['width'], config['height'])
        
        # 处理每个点
        for date_str, yi, label, point_priority in all_points:
            # 如果标签为空或者y值无效，跳过
            if not label or pd.isna(yi):
                continue
                
            date_index = date_to_index[date_str]
            points = date_clusters[date_str]
            
            # 查找具有该y值的点索引
            point_idx = None
            for j, (i, xi, y_val, l) in enumerate(points):
                if y_val == yi and l == label:
                    point_idx = i
                    point_xi = xi
                    break
                    
            if point_idx is None:
                continue  # 找不到对应点，跳过
                
            # 检查该点是否是当前优先级最高的
            is_highest_priority = global_label_manager.is_highest_priority(date_str, yi, line_type, priority)
            
            # 计算初始方向 - 对于共享位置的点，自动分配不同方向
            neighbors = global_label_manager.get_points_count_at(date_str, yi)
            direction_offset = neighbors % 4
                
            # 为点选择一个位置模板 - 使用方向偏移量选择初始方向
            template_idx = (point_idx + direction_offset) % len(position_templates)
            position = position_templates[template_idx].copy()
            
            # 对于完全重叠但不是最高优先级的点，使用备选位置
            if not is_highest_priority and neighbors > 0:
                # 强制选择一个不同的方向
                template_idx = (direction_offset + 2) % len(position_templates)  # 选择对面的方向
                position = position_templates[template_idx].copy()
            
            # 根据线条类型应用额外偏移
            line_offset = 0
            if line_type == 'main':
                line_offset = base_offset // 2  # 使用配置的基础偏移的一半，而不是固定值5
            elif line_type == 'secondary':
                line_offset = -base_offset // 2
                
            if position['name'] in ['top', 'bottom']:
                position['dy'] += line_offset
            else:
                position['dx'] += line_offset
            
            # 标签体积估计值
            label_width, label_height = estimated_label_size
            
            # 记录原始位置为候选位置
            candidates = [(position['dx'], position['dy'])]
            
            # 如果是重叠点，添加更多候选位置
            if neighbors > 0:
                # 添加所有基本方向
                for i, template in enumerate(position_templates):
                    if i != template_idx:  # 排除已选方向
                        new_pos = template.copy()
                        if new_pos['name'] in ['top', 'bottom']:
                            new_pos['dy'] += line_offset
                        else:
                            new_pos['dx'] += line_offset
                        candidates.append((new_pos['dx'], new_pos['dy']))
                
                # 添加附加偏移
                for dx, dy in additional_offsets:
                    candidates.append((dx, dy))  # 直接使用计算好的偏移值
                    
                # 使用智能空间查找
                dx, dy = global_label_manager.find_best_empty_space(
                    date_index, yi, label_width, label_height, search_radius=config['search_radius']
                )
                if dx != 0 or dy != 0:
                    # 将这个位置添加到候选的前面，优先考虑
                    candidates.insert(0, (dx * base_offset, dy * base_offset))  # 放大偏移以增加间隔
                
            # 尝试所有候选位置，找到第一个无碰撞的
            found_position = False
            final_position = None
            
            for dx, dy in candidates:
                # 检查是否与已有标签重叠
                collision = global_label_manager.check_collision(
                    date_index, yi, label_width, label_height
                )
                
                if not collision:
                    final_position = {'dx': dx, 'dy': dy}
                    
                    # 确定文本对齐方式
                    if dx > 0:
                        final_position['ha'] = 'left'
                    elif dx < 0:
                        final_position['ha'] = 'right'
                    else:
                        final_position['ha'] = 'center'
                        
                    if dy > 0:
                        final_position['va'] = 'bottom'
                    elif dy < 0:
                        final_position['va'] = 'top'
                    else:
                        final_position['va'] = 'center'
                        
                    found_position = True
                    break
            
            # 如果没找到无碰撞位置，使用原始位置但增加偏移
            if not found_position:
                final_position = position.copy()
                
                # 根据优先级调整位置
                if not is_highest_priority:
                    if final_position['name'] in ['right', 'left']:
                        # 水平方向，增加垂直偏移
                        vertical_offset = (neighbors % 3) * base_offset  # 使用配置的基础偏移
                        if neighbors % 2 == 0:
                            final_position['dy'] += vertical_offset
                        else:
                            final_position['dy'] -= vertical_offset
                    else:
                        # 垂直方向，增加水平偏移
                        horizontal_offset = (neighbors % 3) * base_offset  # 使用配置的基础偏移
                        if neighbors % 2 == 0:
                            final_position['dx'] += horizontal_offset
                        else:
                            final_position['dx'] -= horizontal_offset
                            
            # 设置对齐方式
            ha = final_position.get('ha', position['ha'])
            va = final_position.get('va', position['va'])
            
            # 设置标签的z-order使其在重叠时优先显示
            z_order = 100 + priority * 10  # 优先级高的在上面
            
            # 创建文本对象并添加到图表
            text = ax.annotate(
                label.replace(', ', '\n'), 
                xy=(point_xi, yi),
                xytext=(final_position['dx'], final_position['dy']),
                textcoords='offset points',
                fontsize=config['font_size'],
                va=va,
                ha=ha,
                color=color,
                bbox=dict(boxstyle="round,pad="+str(config['padding']), fc="white", alpha=config['alpha'], ec=color, lw=0.5),
                zorder=z_order  # 确保标签始终在最上层，且优先级高的在最上
            )
            
            # 记录标签位置
            global_label_manager.add_label_position(
                date_index, yi, label_width, label_height
            )

    # 提取实际日期和交易日索引
    lianban_dates = [datetime.strptime(item[0], "%Y年%m月%d日") for item in lianban_results]
    # 使用交易日索引作为x轴，而不是真实日期
    x_indices = list(range(len(lianban_dates)))
    
    # 提取数据并绘制最高连板折线
    lianban_days = [item[1] for item in lianban_results]
    lianban_labels = [', '.join(item[2]) for item in lianban_results]
    ax.plot(x_indices, lianban_days, label='最高连续涨停天数', color='red', marker='o', alpha=0.7)
    place_labels(x_indices, lianban_days, lianban_labels, 'red', 'main', priority=3)

    # 提取数据并绘制次高连板折线
    lianban_second_days = [item[1] for item in lianban_second_results]
    lianban_second_labels = [', '.join(item[2]) for item in lianban_second_results]
    ax.plot(x_indices, lianban_second_days, label='次高连续涨停天数', color='pink', marker='D', linestyle='-.', alpha=0.6)
    place_labels(x_indices, lianban_second_days, lianban_second_labels, 'pink', 'secondary', priority=1)
                
    # 提取数据并绘制最高几板折线
    max_ji_ban_values = [item[1] for item in max_ji_ban_results]
    max_ji_ban_labels = [', '.join(item[2]) for item in max_ji_ban_results]
    ax.plot(x_indices, max_ji_ban_values, label='最高几板', color='purple', marker='*')
    place_labels(x_indices, max_ji_ban_values, max_ji_ban_labels, 'purple', 'main', priority=2)

    # 提取数据并绘制跌停折线
    dieting_days = [item[1] for item in dieting_results]
    dieting_labels = [', '.join(item[2][:10]) + f'...{len(item[2])}' if len(item[2]) > 10 else ', '.join(item[2])
                      for item in dieting_results]  # 太长则省略
    ax.plot(x_indices, dieting_days, label='连续跌停天数', color='green', marker='s')
    place_labels(x_indices, dieting_days, dieting_labels, 'green', 'secondary', priority=1)

    # 添加副坐标轴并绘制首板数量折线
    ax2 = ax.twinx()  # 创建副坐标轴
    ax2.plot(x_indices, shouban_counts, label='首板数量', color='blue', marker='p', linestyle='--', alpha=0.1)
    ax2.set_ylabel('数量', fontsize=12)  # 设置副 y 轴标签

    # 设置图表信息
    ax.axhline(0, color='black', linewidth=0.8, linestyle='--')  # 添加水平参考线
    ax.set_title("连板/跌停/首板个股走势", fontsize=16)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("天数/板数", fontsize=12)  # 更新Y轴标签
    
    # 设置等间距x轴刻度
    ax.set_xticks(x_indices)
    # 使用原始日期作为标签
    ax.set_xticklabels([date.strftime('%Y-%m-%d') for date in lianban_dates], rotation=45, fontsize=9, ha='right')
    
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))  # 设置 y 轴刻度为整数
    ax.legend(loc='upper left')  # 主 y 轴图例
    ax2.legend(loc='upper right')  # 副 y 轴图例
    plt.tight_layout()
    plt.show()
    # plt.savefig("fupan_lb.png", format='png')
    # plt.close()


def draw_fupan_lb(start_date=None, end_date=None, label_config=None):
    # 示例调用
    fupan_file = "./excel/fupan_stocks.xlsx"
    read_and_plot_data(fupan_file, start_date, end_date, label_config)


if __name__ == '__main__':
    start_date = '20241201'  # 开始日期
    # end_date = '20241101'  # 结束日期
    end_date = None
    
    # 可以通过自定义标签配置来调整标签样式
    # 例如：使用更大的字体和更远的偏移距离
    custom_label_config = {
        'font_size': 8,       # 调整字体大小
        'max_offset': 50,     # 调整最大偏移距离
        'width': 2.0,         # 增加标签宽度
        'height': 1.0,        # 增加标签高度
    }
    
    # 使用默认配置
    draw_fupan_lb(start_date, end_date)
    
    # 或者使用自定义配置 (取消注释下面一行)
    # draw_fupan_lb(start_date, end_date, custom_label_config)
