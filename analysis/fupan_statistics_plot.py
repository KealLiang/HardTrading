import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


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
    ax2.plot(x, df['涨停_次日收盘'], 'r-o', label='涨停次日收盘', linewidth=1)
    ax2.plot(x, df['连板_次日收盘'], 'b-s', label='连板次日收盘', linewidth=1)
    ax2.plot(x, df['炸板_次日收盘盈利'], color='orange', linestyle='-', marker='D', label='炸板次日收盘盈利',
             linewidth=1)

    ax2.plot(x, df['涨停_次日开盘'], 'r--o', label='涨停次日开盘', linewidth=1, alpha=0.5)
    ax2.plot(x, df['连板_次日开盘'], 'b--s', label='连板次日开盘', linewidth=1, alpha=0.5)
    ax2.plot(x, df['炸板_次日开盘盈利'], color='orange', linestyle='--', marker='D', label='炸板次日开盘盈利',
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
    ax1.plot(x, df['涨停_次日开盘'], 'r-o', label='涨停股开盘', linewidth=2)
    ax1.plot(x, df['涨停_次日收盘'], 'r--o', label='涨停股收盘', alpha=0.5)

    # 绘制连板股的次日表现（主坐标轴）
    ax1.plot(x, df['连板_次日开盘盈利'], 'b-s', label='连板股开盘盈利', linewidth=2)
    ax1.plot(x, df['连板_次日收盘盈利'], 'b--s', label='连板股收盘盈利', alpha=0.5)

    # 绘制上涨比例（次坐标轴）
    bar_width = 0.15
    ax2.bar(x - 1.5 * bar_width, df['涨停_次日开盘上涨比例'],
            bar_width, alpha=0.3, color='red', label='涨停次日开盘上涨')
    ax2.bar(x - 0.5 * bar_width, df['连板_次日开盘盈利比例'],
            bar_width, alpha=0.3, color='blue', label='连板次日开盘盈利')
    ax2.bar(x + 0.5 * bar_width, df['涨停_次日收盘上涨比例'],
            bar_width, alpha=0.3, color='red', label='涨停次日收盘上涨', hatch='+', edgecolor='white')
    ax2.bar(x + 1.5 * bar_width, df['连板_次日收盘盈利比例'],
            bar_width, alpha=0.3, color='blue', label='连板次日收盘盈利', hatch='+', edgecolor='white')

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
    min_val = df[['涨停_次日最低', '连板_次日最低']].min().min()
    max_val = df[['涨停_次日最高', '连板_次日最高', '连板_次日开盘盈利', '连板_次日收盘盈利']].max().max()

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
    ax1.plot(x, df['开盘跌停_次日开盘盈利'], 'c-p', label='跌停开开盘盈利', linewidth=2)
    ax1.plot(x, df['开盘跌停_次日收盘盈利'], 'c--p', label='跌停开收盘盈利', alpha=0.5)

    # 绘制跌停股的次日表现（主坐标轴）
    ax1.plot(x, df['跌停_次日实体'], 'g-x', label='跌停股实体', linewidth=2)
    ax1.plot(x, df['跌停_次日收盘盈利'], 'g--x', label='跌停股收盘盈利', alpha=0.5)

    # 绘制炸板股的次日表现（主坐标轴）
    ax1.plot(x, df['炸板_次日实体'], 'y-*', label='炸板股实体', linewidth=2)
    ax1.plot(x, df['炸板_次日收盘'], 'y--*', label='炸板股收盘', alpha=0.5)

    # 绘制上涨比例（次坐标轴）
    bar_width = 0.25
    ax2.bar(x - bar_width, df['开盘跌停_次日开盘盈利比例'],
            bar_width, alpha=0.3, color='cyan', label='跌停开次日开盘盈利')
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
    min_val = df[['开盘跌停_次日最低', '跌停_次日最低', '跌停_次日实体', '跌停_次日收盘盈利']].min().min()
    max_val = df[['开盘跌停_次日最高', '跌停_次日最高', '开盘跌停_次日开盘盈利', '跌停_次日收盘盈利']].max().max()

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


def plot_market_analysis(df, save_path='./images/market_analysis'):
    """
    绘制市场分析图表
    Args:
        df: DataFrame, 包含市场分析数据
        save_path: str, 图片保存的基础路径
    """
    # 设置matplotlib中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False

    # 确保保存目录存在
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 绘制各个图表
    plot_market_overview(df, save_path)
    plot_market_strength(df, save_path)
    plot_limit_up_effect(df, save_path)
    plot_zt_next_day_performance(df, save_path)
    plot_dt_next_day_performance(df, save_path)

    print(f"所有图表已保存到 {save_path} 目录下")


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


def plot_all(start_date=None, end_date=None, data_path='./excel/market_analysis.xlsx'):
    """测试绘图功能"""
    # 读取Excel数据
    df = pd.read_excel(data_path)
    df.set_index('日期', inplace=True)

    # 过滤日期范围
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        print("\n警告: 过滤后的数据为空！请检查日期范围是否正确。")
        return

    # 如果指定了日期范围，在保存路径中添加日期信息
    if start_date or end_date:
        date_range = f"{start_date or 'start'}_to_{end_date or 'end'}"
        save_path = f'./images/market_analysis_{date_range}'
    else:
        save_path = './images/market_analysis'

    # 生成图表
    plot_market_analysis(filtered_df, save_path)


if __name__ == "__main__":
    # 示例：绘制指定日期范围的图表
    plot_all('20250106', '20250108')

    # 或者绘制所有数据的图表
    # plot_all()
