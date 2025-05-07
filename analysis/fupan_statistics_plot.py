import os
import warnings
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# 忽略pandas的FutureWarning
warnings.filterwarnings('ignore', category=FutureWarning)


def plot_market_overview(df, save_path):
    """绘制市场整体情况图"""
    plt.figure(figsize=(15, 8))
    ax1 = plt.gca()

    # 格式化日期显示
    dates = [d.strftime('%Y%m%d') if isinstance(d, pd.Timestamp) else d for d in df.index]
    x = np.arange(len(dates))

    # 绘制堆叠柱状图（涨跌平家数）
    bottom = pd.Series(0, index=df.index)
    for col, color in zip(['上涨家数', '下跌家数', '平盘家数'], ['#cc0000', '#006600', '#666666']):
        ax1.bar(x, df[col], bottom=bottom, label=col, color=color, alpha=0.5)
        bottom += df[col]

    # 创建次坐标轴
    ax2 = ax1.twinx()

    # 绘制涨停和跌停数量的折线
    ax2.plot(x, df['涨停数'], 'r-o', label='涨停数', linewidth=2)
    ax2.plot(x, df['跌停数'], 'g-*', label='跌停数', linewidth=2)

    # 设置标签和标题
    ax1.set_xlabel('日期')
    ax1.set_ylabel('家数')
    ax2.set_ylabel('涨跌停数量')
    plt.title('市场整体情况分析', fontsize=14)

    # 设置x轴刻度
    ax1.set_xticks(x)
    ax1.set_xticklabels(dates, rotation=45, ha='right')

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    plt.savefig(f'{save_path}_overview.png')
    plt.close()


def plot_market_strength(df, save_path):
    """绘制市场强弱分布图"""
    plt.figure(figsize=(15, 8))
    x = np.arange(len(df))
    width = 0.35

    # 上半部分（涨幅）
    plt.bar(x, df['涨幅超过5%家数'], width, color='red', alpha=0.6, label='涨幅>5%')
    plt.bar(x, df['涨幅超过7%家数'], width, color='darkred', alpha=0.7, label='涨幅>7%')

    # 下半部分（跌幅）
    plt.bar(x, -df['跌幅超过5%家数'], width, color='green', alpha=0.6, label='跌幅>5%')
    plt.bar(x, -df['跌幅超过7%家数'], width, color='darkgreen', alpha=0.7, label='跌幅>7%')

    plt.xlabel('日期')
    plt.ylabel('家数')
    plt.title('市场强弱分布', fontsize=14)
    plt.xticks(x, [d.strftime('%Y%m%d') if isinstance(d, pd.Timestamp) else d for d in df.index],
               rotation=45, ha='right')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'{save_path}_strength.png')
    plt.close()


def plot_limit_up_effect(df, save_path):
    """绘制涨停板效应分析图"""
    plt.figure(figsize=(15, 8))
    ax1 = plt.gca()

    # 设置x轴位置
    x = np.arange(len(df))
    width = 0.25

    # 绘制柱状图
    ax1.bar(x - width, df['涨停数'], width, label='涨停数', color='red', alpha=0.3)
    ax1.bar(x, df['连板数'], width, label='连板数', color='blue', alpha=0.3)
    ax1.bar(x + width, df['炸板数'], width, label='炸板数', color='orange', alpha=0.3)

    # 创建次坐标轴
    ax2 = ax1.twinx()

    # 绘制次日表现折线
    ax2.plot(x, df['涨停_次日实体'], 'r-o', label='涨停次日实体', linewidth=1)
    ax2.plot(x, df['连板_次日实体'], 'b-s', label='连板次日实体', linewidth=1)
    ax2.plot(x, df['炸板_次日实体'], color='orange', linestyle='-', marker='D', label='炸板次日实体',
             linewidth=1)

    ax2.plot(x, df['涨停_次日高入开盘'], 'r--o', label='涨停次日高入开盘', linewidth=1, alpha=0.5)
    # ax2.plot(x, df['连板_次日开入开盘'], 'b--s', label='连板次日开入开盘', linewidth=1, alpha=0.5)
    ax2.plot(x, df['炸板_次日开入开盘'], color='orange', linestyle='--', marker='D', label='炸板次日开入开盘',
             linewidth=1, alpha=0.5)

    ax1.set_xlabel('日期')
    ax1.set_ylabel('数量')
    ax2.set_ylabel('次日涨跌幅(%)')
    plt.title('涨停板效应分析', fontsize=14)

    # 设置x轴刻度
    ax1.set_xticks(x)
    ax1.set_xticklabels([d.strftime('%Y%m%d') if isinstance(d, pd.Timestamp) else d for d in df.index],
                        rotation=45, ha='right')

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    plt.savefig(f'{save_path}_limit_up.png')
    plt.close()


def plot_zt_next_day_performance(df, save_path):
    """绘制涨停次日表现对比图"""
    plt.figure(figsize=(15, 8))

    # 创建主坐标轴和次坐标轴
    ax1 = plt.gca()
    ax2 = ax1.twinx()

    # 设置x轴位置
    x = np.arange(len(df))

    # 绘制涨停股的次日表现（主坐标轴）
    ax1.plot(x, df['涨停_次日高入开盘'], 'r-o', label='涨停股高入开盘', linewidth=2)
    ax1.plot(x, df['涨停_次日高入收盘'], 'r--o', label='涨停股高入收盘', alpha=0.5)

    # 绘制连板股的次日表现（主坐标轴）
    ax1.plot(x, df['连板_次日高入开盘'], 'b-s', label='连板股高入开盘', linewidth=2)
    ax1.plot(x, df['连板_次日高入收盘'], 'b--s', label='连板股高入收盘', alpha=0.5)

    # 绘制曾涨停的次日表现（主坐标轴）
    ax1.plot(x, df['曾涨停_次日高入开盘'], 'c-s', label='曾涨停股高入开盘', linewidth=2)
    ax1.plot(x, df['曾涨停_次日高入收盘'], 'c--s', label='曾涨停股高入收盘', alpha=0.5)

    # 绘制上涨比例（次坐标轴）
    bar_width = 0.15
    ax2.bar(x - 1.5 * bar_width, df['涨停_次日高入开盘涨比'],
            bar_width, alpha=0.3, color='red', label='涨停次日高入开盘涨比')
    ax2.bar(x - 0.5 * bar_width, df['连板_次日高入开盘涨比'],
            bar_width, alpha=0.3, color='blue', label='连板次日高入开盘涨比')
    ax2.bar(x + 0.5 * bar_width, df['涨停_次日高入收盘涨比'],
            bar_width, alpha=0.3, color='red', label='涨停次日高入收盘涨比', hatch='+', edgecolor='white')
    ax2.bar(x + 1.5 * bar_width, df['连板_次日高入收盘涨比'],
            bar_width, alpha=0.3, color='blue', label='连板次日高入收盘涨比', hatch='+', edgecolor='white')

    # 设置标签和标题
    ax1.set_xlabel('日期')
    ax1.set_ylabel('涨跌幅(%)')
    ax2.set_ylabel('上涨比例(%)')
    plt.title('次日表现分析', fontsize=14)

    # 设置x轴刻度
    ax1.set_xticks(x)
    ax1.set_xticklabels([d.strftime('%Y%m%d') if isinstance(d, pd.Timestamp) else d for d in df.index],
                        rotation=45, ha='right')

    # 安全地设置y轴范围
    min_val = df[['涨停_次日收入低价', '连板_次日收入低价', '曾涨停_次日高入开盘']].min().min()
    max_val = df[['涨停_次日收入高价', '连板_次日收入高价', '曾涨停_次日开入收盘']].max().max()

    # 处理无效值
    if pd.isna(min_val) or pd.isna(max_val):
        y_min, y_max = -8, 8  # 默认值
    else:
        y_min = min(min_val * 1.1, -8)
        y_max = max(max_val * 1.1, 8)

    ax1.set_ylim(y_min, y_max)
    ax2.set_ylim(0, 100)

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    # 添加网格
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{save_path}_next_day_zt.png')
    plt.close()


def plot_dt_next_day_performance(df, save_path):
    """绘制跌停次日表现对比图"""
    plt.figure(figsize=(15, 8))

    # 创建主坐标轴和次坐标轴
    ax1 = plt.gca()
    ax2 = ax1.twinx()

    # 设置x轴位置
    x = np.arange(len(df))

    # 绘制跌停开的次日表现（主坐标轴）
    ax1.plot(x, df['开盘跌停_次日开入开盘'], 'c-p', label='跌停开次日开入开盘', linewidth=2)
    ax1.plot(x, df['开盘跌停_次日开入收盘'], 'c--p', label='跌停开次日开入收盘', alpha=0.5)

    # 绘制跌停股的次日表现（主坐标轴）
    ax1.plot(x, df['跌停_次日实体'], 'g-x', label='跌停股实体', linewidth=2)

    # 绘制炸板股的次日表现（主坐标轴）
    ax1.plot(x, df['炸板_次日实体'], 'y-*', label='炸板股实体', linewidth=2)
    ax1.plot(x, df['炸板_次日高入收盘'], 'y--*', label='炸板股次日高入收盘', alpha=0.5)

    # 绘制上涨比例（次坐标轴）
    bar_width = 0.25
    ax2.bar(x - bar_width, df['开盘跌停_次日开入开盘涨比'],
            bar_width, alpha=0.3, color='cyan', label='跌停开次日开入开盘涨比')
    ax2.bar(x, df['跌停_次日实体上涨比例'],
            bar_width, alpha=0.3, color='green', label='跌停次日实体上涨')
    ax2.bar(x + bar_width, df['炸板_次日实体上涨比例'],
            bar_width, alpha=0.3, color='yellow', label='炸板次日实体上涨')

    # 设置标签和标题
    ax1.set_xlabel('日期')
    ax1.set_ylabel('涨跌幅(%)')
    ax2.set_ylabel('上涨比例(%)')
    plt.title('次日表现分析', fontsize=14)

    # 设置x轴刻度
    ax1.set_xticks(x)
    ax1.set_xticklabels([d.strftime('%Y%m%d') if isinstance(d, pd.Timestamp) else d for d in df.index],
                        rotation=45, ha='right')

    # 安全地设置y轴范围
    min_val = df[['开盘跌停_次日开入开盘', '跌停_次日收入开盘', '炸板_次日高入开盘']].min().min()
    max_val = df[['开盘跌停_次日开入收盘', '跌停_次日实体', '炸板_次日实体']].max().max()

    # 处理无效值
    if pd.isna(min_val) or pd.isna(max_val):
        y_min, y_max = -8, 8  # 默认值
    else:
        y_min = min(min_val * 1.1, -8)
        y_max = max(max_val * 1.1, 8)

    ax1.set_ylim(y_min, y_max)
    ax2.set_ylim(0, 100)

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    # 添加网格
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{save_path}_next_day_dt.png')
    plt.close()


def plot_limit_up_history_data(df, save_path):
    """绘制涨停板历史数据综合分析图表"""
    plt.figure(figsize=(16, 10))

    # 获取所有唯一日期并确保排序
    dates = sorted(df['评估日期'].unique())
    targets = sorted(df['晋级目标'].unique())

    # 为每个日期创建x轴坐标映射
    date_positions = {date: i for i, date in enumerate(dates)}
    x_ticks = list(range(len(dates)))

    # 创建主坐标轴和次坐标轴
    ax1 = plt.gca()
    ax2 = ax1.twinx()
    ax3 = ax1.twinx()
    ax3.spines['right'].set_position(('outward', 60))  # 调整第三个y轴的位置

    # 设置颜色映射
    colors = plt.cm.tab10(np.linspace(0, 1, len(targets)))

    # 绘制晋级率折线（主坐标轴）
    for i, target in enumerate(targets):
        target_df = df[df['晋级目标'] == target]
        if len(target_df) > 0:
            # 将日期转换为X轴位置
            x_pos = [date_positions[date] for date in target_df['评估日期']]

            ax1.plot(x_pos, target_df['晋级率'] * 100,
                     marker='o', linestyle='-', color=colors[i],
                     linewidth=2, label=f'{target}晋级率',
                     alpha=0.9)  # 晋级率是主要指标，透明度低

            # 存活率和死亡率（次要指标）
            ax1.plot(x_pos, target_df['存活率'] * 100,
                     marker='s', linestyle='--', color=colors[i],
                     linewidth=1.5, label=f'{target}存活率',
                     alpha=0.5)  # 次要指标，透明度高
            ax1.plot(x_pos, target_df['死亡率'] * 100,
                     marker='^', linestyle=':', color=colors[i],
                     linewidth=1, label=f'{target}死亡率',
                     alpha=0.3)  # 次要指标，透明度更高

    # 绘制数量柱状图（次坐标轴）
    width = 0.8 / max(len(targets), 1)  # 防止除零，使用max确保分母至少为1

    for i, target in enumerate(targets):
        target_df = df[df['晋级目标'] == target].copy()
        if len(target_df) > 0:
            # 获取每个目标日期的x位置
            x_pos = [date_positions[date] for date in target_df['评估日期']]

            # 绘制总数柱状图（透明度降低）
            ax2.bar([pos + (i - (len(targets) - 1) / 2) * width for pos in x_pos],
                    target_df['总数'],
                    width=width,
                    color=colors[i],
                    alpha=0.3,
                    label=f'{target}总数')

    # 绘制高开相关指标（第三坐标轴）
    for i, target in enumerate(targets):
        target_df = df[df['晋级目标'] == target]
        if len(target_df) > 0:
            # 将日期转换为X轴位置
            x_pos = [date_positions[date] for date in target_df['评估日期']]

            # 高开晋级率（重要指标）
            ax3.plot(x_pos, target_df['高开晋级率'] * 100,
                     marker='*', linestyle='-.', color=colors[i],
                     linewidth=1.5, label=f'{target}高开晋级率',
                     alpha=0.7)

    # 设置标签和标题
    ax1.set_xlabel('日期', fontsize=12)
    ax1.set_ylabel('比率(%)', fontsize=12)
    ax2.set_ylabel('数量', fontsize=12)
    ax3.set_ylabel('高开相关指标(%)', fontsize=12)
    plt.title('涨停板历史数据综合分析', fontsize=16)

    # 设置x轴刻度和格式化日期标签
    ax1.set_xticks(x_ticks)
    # 格式化日期为YYYY-MM-DD格式
    date_labels = [date.strftime('%Y-%m-%d') for date in dates]
    ax1.set_xticklabels(date_labels, rotation=45, ha='right')

    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    lines3, labels3 = ax3.get_legend_handles_labels()

    # 按类型分组排序图例
    legend_items = []
    legend_labels = []

    # 先添加晋级率（最重要）
    jj_lines = [line for line, label in zip(lines1, labels1) if '晋级率' in label]
    jj_labels = [label for label in labels1 if '晋级率' in label]
    legend_items.extend(jj_lines)
    legend_labels.extend(jj_labels)

    # 添加高开晋级率
    gk_lines = [line for line, label in zip(lines3, labels3) if '高开晋级率' in label]
    gk_labels = [label for label in labels3 if '高开晋级率' in label]
    legend_items.extend(gk_lines)
    legend_labels.extend(gk_labels)

    # 添加存活率
    sc_lines = [line for line, label in zip(lines1, labels1) if '存活率' in label]
    sc_labels = [label for label in labels1 if '存活率' in label]
    legend_items.extend(sc_lines)
    legend_labels.extend(sc_labels)

    # 添加死亡率
    sw_lines = [line for line, label in zip(lines1, labels1) if '死亡率' in label]
    sw_labels = [label for label in labels1 if '死亡率' in label]
    legend_items.extend(sw_lines)
    legend_labels.extend(sw_labels)

    # 添加总数
    zs_lines = [line for line, label in zip(lines2, labels2) if '总数' in label]
    zs_labels = [label for label in labels2 if '总数' in label]
    legend_items.extend(zs_lines)
    legend_labels.extend(zs_labels)

    # 创建图例，放置在图表下方
    ax1.legend(legend_items, legend_labels, loc='upper center',
               bbox_to_anchor=(0.5, -0.15), ncol=5, frameon=True,
               fontsize=10, fancybox=True, shadow=True)

    # 添加网格线
    ax1.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.25)  # 为图例留出空间
    plt.savefig(f'{save_path}_history.png')
    plt.close()

    print(f"涨停板历史数据分析图表已保存到 {save_path}_history.png")


def handle_limit_up_data(end_date, limit_up_df, start_date):
    """处理涨停历史数据的基本预处理"""
    # 百分比数据转换为小数
    for col in ['晋级率', '存活率', '死亡率', '高开晋级率', '高开存活率', '高开死亡率']:
        if col in limit_up_df.columns:
            limit_up_df[col] = limit_up_df[col].str.rstrip('%').astype('float') / 100

    # 评估日期转换为日期类型
    limit_up_df['评估日期'] = pd.to_datetime(limit_up_df['评估日期'], format='%Y-%m-%d')

    # 日期过滤
    if start_date:
        start_date = pd.to_datetime(start_date, format='%Y%m%d')
        limit_up_df = limit_up_df[limit_up_df['评估日期'] >= start_date]
    if end_date:
        end_date = pd.to_datetime(end_date, format='%Y%m%d')
        limit_up_df = limit_up_df[limit_up_df['评估日期'] <= end_date]

    return limit_up_df


def filter_data_by_date(df, start_date=None, end_date=None):
    """
    按日期范围过滤数据
    Args:
        df: DataFrame, 原始数据
        start_date: str, 开始日期，格式为'YYYYMMDD'
        end_date: str, 结束日期，格式为'YYYYMMDD'
    Returns:
        DataFrame: 过滤后的数据
    """
    # 确保索引是datetime类型，并且格式统一
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, format='%Y%m%d')

    # 过滤日期范围
    if start_date:
        start_date = pd.to_datetime(start_date, format='%Y%m%d')
        df = df[df.index >= start_date]
    if end_date:
        end_date = pd.to_datetime(end_date, format='%Y%m%d')
        df = df[df.index <= end_date]

    return df


def plot_limit_up_key_metrics_combined(df, save_path):
    """将晋级率、存活率、高开晋级率和高开存活率热力图合并到一张2x2分面图中"""
    if df.empty:
        print("警告：涨停板数据为空，跳过热力图绘制")
        return

    # 获取所有唯一日期和晋级目标
    dates = sorted(df['评估日期'].unique())

    # 简化排序：直接提取"进"后面的数字作为排序键（大的在上面）
    targets = sorted(df['晋级目标'].unique(),
                     key=lambda x: int(x.split('进')[1]) if '进' in x and x.split('进')[1].isdigit() else 0,
                     reverse=True)

    # 创建必要的目录
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 创建2x2分面图布局
    fig, axes = plt.subplots(2, 2, figsize=(26, 14), sharex=True)
    plt.suptitle('涨停板指标分析', fontsize=20, y=0.98)

    # 定义要绘制的指标 - 使用2x2布局
    metrics = [
        ('晋级率', '晋级率热力图 (%)', 'Reds', axes[0, 0]),
        ('存活率', '存活率热力图 (%)', 'YlOrRd', axes[1, 0]),
        ('高开晋级率', '高开晋级率热力图 (%)', 'Blues', axes[0, 1]),
        ('高开存活率', '高开存活率热力图 (%)', 'GnBu', axes[1, 1])
    ]

    # 创建热力图绘制函数，避免代码重复
    def draw_heatmap(metric_name, title, cmap, ax):
        # 构建热力图数据
        heatmap_data = pd.DataFrame(index=targets, columns=dates)

        # 填充数据
        for target in targets:
            target_df = df[df['晋级目标'] == target]
            for _, row in target_df.iterrows():
                date = row['评估日期']
                # 确保该列存在
                if metric_name in row:
                    value = row[metric_name] * 100  # 将小数转为百分比
                    heatmap_data.loc[target, date] = value

        # 使用infer_objects()避免FutureWarning
        heatmap_data = heatmap_data.fillna(0).infer_objects()

        # 设置热力图
        sns.heatmap(heatmap_data, annot=True, fmt=".1f", cmap=cmap,
                    linewidths=0.5, ax=ax, cbar_kws={'label': '百分比(%)'})

        # 设置标题和标签
        ax.set_title(title, fontsize=14, pad=10)  # 增加pad值防止重叠
        ax.set_ylabel('晋级目标', fontsize=12)

        # 格式化日期标签
        date_labels = [date.strftime('%Y-%m-%d') for date in dates]
        ax.set_xticklabels(date_labels, rotation=45, ha='right')

        return ax

    # 为每个指标创建热力图
    for i, (metric_name, title, cmap, ax) in enumerate(metrics):
        draw_heatmap(metric_name, title, cmap, ax)

        # 只在底部子图设置x轴标签
        if i >= 2:  # 下排图表
            ax.set_xlabel('日期', fontsize=12)
        else:
            ax.set_xlabel('')

    # 调整布局以防止重叠
    plt.tight_layout()
    plt.subplots_adjust(top=0.92, hspace=0.15, wspace=0.1)  # 为总标题留出空间，调整子图间距

    # 保存图形
    plt.savefig(f'{save_path}_promote_metrics_combined.png')
    plt.close()

    print(f"涨停板多指标热力图已保存到 {save_path}_promote_metrics_combined.png")


def plot_market_analysis(df, save_path='./images/market_analysis', limit_up_df=None):
    """
    绘制市场分析图表
    Args:
        df: DataFrame, 包含市场分析数据
        save_path: str, 图片保存的基础路径
        limit_up_df: DataFrame, 包含涨停板历史数据，可选
        limit_up_save_path: str, 涨停板历史图片保存的基础路径，可选
    """
    # 设置matplotlib中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False

    # 确保保存目录存在
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 绘制市场分析各个图表
    plot_market_overview(df, save_path)
    plot_market_strength(df, save_path)
    plot_limit_up_effect(df, save_path)
    plot_zt_next_day_performance(df, save_path)
    # plot_dt_next_day_performance(df, save_path)
    # 绘制涨停板历史数据图表
    # plot_limit_up_history_data(limit_up_df, save_path)
    plot_limit_up_key_metrics_combined(limit_up_df, save_path)


def plot_all(start_date=None, end_date=None, path='./excel/'):
    """绘制所有分析图表"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    market_analysis_path = path + 'market_analysis.xlsx'
    limit_up_history = path + 'limit_up_history.xlsx'

    # 读取市场分析Excel数据
    df = pd.read_excel(market_analysis_path)
    df.set_index('日期', inplace=True)
    filtered_df = filter_data_by_date(df, start_date, end_date)

    # 确定保存路径
    if start_date or end_date:
        date_range = f"{start_date or 'start'}_to_{end_date or 'end'}"
        market_save_path = f'./images/market_analysis_{date_range}'
    else:
        market_save_path = './images/market_analysis'

    # 读取涨停历史数据
    limit_up_df = pd.read_excel(limit_up_history)
    limit_up_df = handle_limit_up_data(end_date, limit_up_df, start_date)

    # 生成所有图表
    plot_market_analysis(filtered_df, market_save_path, limit_up_df)


if __name__ == "__main__":
    # 示例：绘制指定日期范围的图表
    plot_all('20250106', '20250108')

    # 或者绘制所有数据的图表
    # plot_all()
