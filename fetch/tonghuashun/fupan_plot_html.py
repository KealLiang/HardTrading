"""
HTML交互式复盘图生成器 - 使用Plotly

优势：
1. 鼠标悬停显示详细信息，完全解决标签重叠问题
2. 支持缩放、平移、保存图片
3. 可添加更多交互功能
4. 生成单个HTML文件，方便分享
"""

from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import sys
import os

# 导入工具函数
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from utils.stock_util import stock_limit_ratio


def format_stock_name_with_indicators(stock_code: str, stock_name: str, 
                                    zhangting_open_times: str = None, 
                                    first_zhangting_time: str = None, 
                                    final_zhangting_time: str = None) -> str:
    """
    格式化股票名称，添加涨跌幅标识和一字板标识
    
    标识说明：
    - | = 一字板涨停
    - * = 20%涨跌幅限制
    - ** = 30%涨跌幅限制
    """
    try:
        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
        limit_ratio = stock_limit_ratio(clean_code)
        formatted_name = stock_name
        
        # 判断是否为一字板
        is_yizi_ban = is_yizi_board_zhangting(zhangting_open_times, first_zhangting_time, final_zhangting_time)
        if is_yizi_ban:
            formatted_name = f"{formatted_name}|"
        
        # 根据涨跌幅比例添加星号
        if limit_ratio == 0.2:
            return f"{formatted_name}*"
        elif limit_ratio == 0.3:
            return f"{formatted_name}**"
        else:
            return formatted_name
    except:
        return stock_name


def is_yizi_board_zhangting(zhangting_open_times: str, first_zhangting_time: str, final_zhangting_time: str) -> bool:
    """判断是否为一字板涨停"""
    try:
        if zhangting_open_times is None or str(zhangting_open_times).strip() == '':
            return False
        open_times = int(str(zhangting_open_times).strip())
        if open_times != 0:
            return False
        
        if (first_zhangting_time is None or final_zhangting_time is None or 
            str(first_zhangting_time).strip() == '' or str(final_zhangting_time).strip() == ''):
            return False
        
        first_time = str(first_zhangting_time).strip()
        final_time = str(final_zhangting_time).strip()
        
        if first_time != final_time:
            return False
        
        if not is_market_open_time(first_time):
            return False
        
        return True
    except:
        return False


def is_market_open_time(time_str: str) -> bool:
    """判断是否为开盘时间"""
    try:
        time_str = time_str.strip()
        if time_str == "09:30:00" or time_str == "09:25:00":
            return True
        if time_str.startswith("09:30") or time_str.startswith("09:25"):
            return True
        return False
    except:
        return False


def read_and_plot_html(fupan_file, start_date=None, end_date=None, output_path=None):
    """
    读取数据并生成HTML交互式图表
    
    Args:
        fupan_file: Excel文件路径
        start_date: 开始日期（格式: YYYYMMDD）
        end_date: 结束日期（格式: YYYYMMDD）
        output_path: 输出HTML文件路径（可选）
    
    Returns:
        str: 生成的HTML文件路径
    """
    # 读取Excel数据
    lianban_data = pd.read_excel(fupan_file, sheet_name="连板数据", index_col=0)
    dieting_data = pd.read_excel(fupan_file, sheet_name="跌停数据", index_col=0)
    shouban_data = pd.read_excel(fupan_file, sheet_name="首板数据", index_col=0)
    
    # 读取默默上涨数据（可能不存在）
    try:
        momo_data = pd.read_excel(fupan_file, sheet_name="默默上涨", index_col=0)
        has_momo_data = True
    except:
        momo_data = None
        has_momo_data = False
        print("未找到【默默上涨】数据sheet，将跳过该数据")

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
    lianban_results = []
    lianban_second_results = []
    dieting_results = []
    shouban_counts = []
    max_ji_ban_results = []
    momo_results = []  # 默默上涨数据

    # 逐列提取数据
    for date in dates:
        # 连板数据处理
        lianban_col = lianban_data[date].dropna()
        lianban_stocks = lianban_col.str.split(';').apply(lambda x: [item.strip() for item in x])
        lianban_df = pd.DataFrame(lianban_stocks.tolist(), columns=[
            '股票代码', '股票简称', '涨停开板次数', '最终涨停时间',
            '几天几板', '最新价', '首次涨停时间', '最新涨跌幅',
            '连续涨停天数', '涨停原因类别'
        ])
        
        # 清理数据
        lianban_df['连续涨停天数'] = lianban_df['连续涨停天数'].fillna(0)
        lianban_df['连续涨停天数'] = lianban_df['连续涨停天数'].replace('', 0)
        lianban_df['连续涨停天数'] = pd.to_numeric(lianban_df['连续涨停天数'], errors='coerce').fillna(0).astype(int)
        
        # 提取几板数值
        def extract_ji_ban(ji_tian_ji_ban):
            match = re.search(r'(\d+)天(\d+)板', str(ji_tian_ji_ban))
            if match:
                return int(match.group(2))
            return 0
        
        lianban_df['几板'] = lianban_df['几天几板'].apply(extract_ji_ban)
        
        # 提取最高几板（确保即使为0也显示）
        max_ji_ban = lianban_df['几板'].max() if not lianban_df.empty else 0
        if pd.isna(max_ji_ban):
            max_ji_ban = 0
        max_ji_ban_filtered = lianban_df[lianban_df['几板'] == max_ji_ban]
        max_ji_ban_stocks = []
        if not max_ji_ban_filtered.empty:
            max_ji_ban_stocks = [format_stock_name_with_indicators(
                row['股票代码'], row['股票简称'],
                row['涨停开板次数'], row['首次涨停时间'], row['最终涨停时间']
            ) for _, row in max_ji_ban_filtered.iterrows()]
        max_ji_ban_results.append((date, max_ji_ban, max_ji_ban_stocks))

        # 提取最高连板（确保即使为0也显示）
        max_lianban = lianban_df['连续涨停天数'].max() if not lianban_df.empty else 0
        if pd.isna(max_lianban):
            max_lianban = 0
        max_lianban_filtered = lianban_df[lianban_df['连续涨停天数'] == max_lianban]
        max_lianban_stocks = []
        if not max_lianban_filtered.empty:
            max_lianban_stocks = [format_stock_name_with_indicators(
                row['股票代码'], row['股票简称'],
                row['涨停开板次数'], row['首次涨停时间'], row['最终涨停时间']
            ) for _, row in max_lianban_filtered.iterrows()]

        # 提取次高连板（确保即使为0也显示）
        second_lianban = lianban_df[lianban_df['连续涨停天数'] < max_lianban]['连续涨停天数'].max() if not lianban_df.empty and max_lianban > 0 else 0
        if pd.isna(second_lianban):
            second_lianban = 0
        second_lianban_filtered = lianban_df[lianban_df['连续涨停天数'] == second_lianban]
        second_lianban_stocks = []
        if not second_lianban_filtered.empty and second_lianban > 0:
            second_lianban_stocks = [format_stock_name_with_indicators(
                row['股票代码'], row['股票简称'],
                row['涨停开板次数'], row['首次涨停时间'], row['最终涨停时间']
            ) for _, row in second_lianban_filtered.iterrows()]

        lianban_results.append((date, max_lianban, max_lianban_stocks))
        lianban_second_results.append((date, second_lianban, second_lianban_stocks))

        # 跌停数据处理
        dieting_col = dieting_data[date].dropna()
        dieting_col = dieting_col.fillna('').astype(str)
        dieting_stocks = dieting_col.str.split(';').apply(lambda x: [item.strip() for item in x])
        dieting_df = pd.DataFrame(dieting_stocks.tolist(), columns=[
            '股票代码', '股票简称', '跌停开板次数', '首次跌停时间',
            '跌停类型', '最新价', '最新涨跌幅',
            '连续跌停天数', '跌停原因类型'
        ])
        
        if not dieting_df.empty:
            dieting_df['连续跌停天数'] = dieting_df['连续跌停天数'].fillna(0)
            dieting_df['连续跌停天数'] = dieting_df['连续跌停天数'].replace('', 0)
            dieting_df['连续跌停天数'] = pd.to_numeric(dieting_df['连续跌停天数'], errors='coerce').fillna(0).astype(int)

            max_dieting = dieting_df['连续跌停天数'].max()
            max_dieting_filtered = dieting_df[dieting_df['连续跌停天数'] == max_dieting]
            max_dieting_stocks = []
            if not max_dieting_filtered.empty:
                max_dieting_stocks = [format_stock_name_with_indicators(row['股票代码'], row['股票简称']) 
                                     for _, row in max_dieting_filtered.iterrows()]
        else:
            max_dieting = 0
            max_dieting_stocks = []
        dieting_results.append((date, -max_dieting, max_dieting_stocks))

        # 首板数据
        shouban_col = shouban_data[date].dropna()
        shouban_counts.append(len(shouban_col))
        
        # 默默上涨数据处理
        if has_momo_data and date in momo_data.columns:
            momo_col = momo_data[date].dropna()
            momo_stocks_data = []
            momo_zhangfus = []
            
            for cell in momo_col:
                if pd.isna(cell) or str(cell).strip() == '':
                    continue
                parts = str(cell).split(';')
                if len(parts) >= 5:
                    # 格式：股票代码; 股票简称; 最新价; 最新涨跌幅; 区间涨跌幅; 区间成交额; 区间振幅; 上市交易日天数
                    stock_code = parts[0].strip()
                    stock_name = parts[1].strip()
                    qujian_zhangfu = parts[4].strip()  # 区间涨跌幅（第5个字段）
                    
                    try:
                        # 去掉百分号，转换为浮点数
                        zhangfu_value = float(qujian_zhangfu.rstrip('%'))
                        momo_zhangfus.append(zhangfu_value)
                        momo_stocks_data.append(f"{stock_name}({qujian_zhangfu})")
                    except:
                        pass
            
            # 计算平均涨幅或最大涨幅
            if momo_zhangfus:
                avg_zhangfu = sum(momo_zhangfus) / len(momo_zhangfus)
                max_zhangfu = max(momo_zhangfus)
                # 找出涨幅最高的前3只股票
                top_3_indices = sorted(range(len(momo_zhangfus)), key=lambda i: momo_zhangfus[i], reverse=True)[:3]
                top_3_stocks = [momo_stocks_data[i] for i in top_3_indices if i < len(momo_stocks_data)]
                momo_results.append((date, avg_zhangfu, momo_stocks_data, top_3_stocks))
            else:
                # 没有数据时用None，不影响Y轴范围
                momo_results.append((date, None, [], []))
        elif has_momo_data:
            # 该日期没有默默上涨数据，用None
            momo_results.append((date, None, [], []))

    # === 开始绘制Plotly图表 ===
    
    # 提取日期和数据
    lianban_dates = [datetime.strptime(item[0], "%Y年%m月%d日") for item in lianban_results]
    date_labels = [d.strftime('%Y-%m-%d') for d in lianban_dates]  # 修改日期格式为 yyyy-MM-dd
    
    # 创建多Y轴图表（需要为默默上涨单独创建一个Y轴）
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # 首板数量线（主Y轴）
    fig.add_trace(
        go.Scatter(
            x=date_labels,
            y=shouban_counts,
            name='首板数量',
            mode='lines+markers+text',  # 添加text模式，永久显示标签
            line=dict(color='blue', width=2, dash='dash'),
            marker=dict(symbol='diamond', size=8),
            text=[f'{count}' for count in shouban_counts],  # 显示数量
            textposition='top center',
            textfont=dict(size=10, color='blue'),
            opacity=0.3,
            hovertemplate='首板数量: %{y}<extra></extra>',  # 去掉日期，顶部统一显示
        ),
        secondary_y=False,
    )
    
    # 最高连板线（副Y轴）
    lianban_days = [item[1] for item in lianban_results]
    # 悬浮窗股票列表：每5只股票换一行
    lianban_stocks = []
    for item in lianban_results:
        stocks = item[2]
        if len(stocks) > 5:
            # 每5只换行
            stock_lines = [', '.join(stocks[i:i+5]) for i in range(0, len(stocks), 5)]
            lianban_stocks.append('<br>'.join(stock_lines))
        else:
            lianban_stocks.append(', '.join(stocks))
    # 创建显示在图上的标签（股票名称），有省略时添加"……"
    lianban_labels = []
    for item in lianban_results:
        if len(item[2]) > 3:
            lianban_labels.append('<br>'.join(item[2][:3]) + '<br>……')
        else:
            lianban_labels.append('<br>'.join(item[2]) if item[2] else '')
    
    fig.add_trace(
        go.Scatter(
            x=date_labels,
            y=lianban_days,
            name='最高连续涨停天数',
            mode='lines+markers+text',  # 添加text模式
            line=dict(color='red', width=2),
            marker=dict(symbol='circle', size=10),
            text=lianban_labels,  # 永久显示的标签
            textposition='top center',
            textfont=dict(size=9, color='red'),
            customdata=lianban_stocks,
            hovertemplate='连板: %{y}板<br>股票: %{customdata}<extra></extra>',  # 去掉日期
        ),
        secondary_y=True,
    )
    
    # 次高连板线（副Y轴）
    lianban_second_days = [item[1] for item in lianban_second_results]
    # 悬浮窗股票列表：每5只股票换一行
    lianban_second_stocks = []
    for item in lianban_second_results:
        stocks = item[2]
        if len(stocks) > 5:
            stock_lines = [', '.join(stocks[i:i+5]) for i in range(0, len(stocks), 5)]
            lianban_second_stocks.append('<br>'.join(stock_lines))
        else:
            lianban_second_stocks.append(', '.join(stocks))
    lianban_second_labels = []
    for item in lianban_second_results:
        if len(item[2]) > 3:
            lianban_second_labels.append('<br>'.join(item[2][:3]) + '<br>……')
        else:
            lianban_second_labels.append('<br>'.join(item[2]) if item[2] else '')
    
    fig.add_trace(
        go.Scatter(
            x=date_labels,
            y=lianban_second_days,
            name='次高连续涨停天数',
            mode='lines+markers+text',
            line=dict(color='orange', width=2),
            marker=dict(symbol='square', size=8),
            text=lianban_second_labels,
            textposition='bottom center',
            textfont=dict(size=9, color='orange'),
            customdata=lianban_second_stocks,
            hovertemplate='次高连板: %{y}板<br>股票: %{customdata}<extra></extra>',  # 去掉日期
        ),
        secondary_y=True,
    )
    
    # 跌停线（副Y轴）
    dieting_days = [item[1] for item in dieting_results]
    # 悬浮窗股票列表：每5只股票换一行
    dieting_stocks = []
    for item in dieting_results:
        stocks = item[2]
        if len(stocks) > 5:
            stock_lines = [', '.join(stocks[i:i+5]) for i in range(0, len(stocks), 5)]
            dieting_stocks.append('<br>'.join(stock_lines))
        else:
            dieting_stocks.append(', '.join(stocks))
    dieting_labels = []
    for item in dieting_results:
        if len(item[2]) > 3:
            dieting_labels.append('<br>'.join(item[2][:3]) + '<br>……')
        else:
            dieting_labels.append('<br>'.join(item[2]) if item[2] else '')
    
    fig.add_trace(
        go.Scatter(
            x=date_labels,
            y=dieting_days,
            name='最大连续跌停天数',
            mode='lines+markers+text',
            line=dict(color='green', width=2),
            marker=dict(symbol='triangle-down', size=8),
            text=dieting_labels,
            textposition='bottom center',
            textfont=dict(size=9, color='green'),
            customdata=dieting_stocks,
            hovertemplate='跌停: %{y}天<br>股票: %{customdata}<extra></extra>',  # 去掉日期
        ),
        secondary_y=True,
    )
    
    # 最高几板线（副Y轴）
    max_ji_ban_days = [item[1] for item in max_ji_ban_results]
    # 悬浮窗股票列表：每5只股票换一行
    max_ji_ban_stocks = []
    for item in max_ji_ban_results:
        stocks = item[2]
        if len(stocks) > 5:
            stock_lines = [', '.join(stocks[i:i+5]) for i in range(0, len(stocks), 5)]
            max_ji_ban_stocks.append('<br>'.join(stock_lines))
        else:
            max_ji_ban_stocks.append(', '.join(stocks))
    max_ji_ban_labels = []
    for item in max_ji_ban_results:
        if len(item[2]) > 3:
            max_ji_ban_labels.append('<br>'.join(item[2][:3]) + '<br>……')
        else:
            max_ji_ban_labels.append('<br>'.join(item[2]) if item[2] else '')
    
    fig.add_trace(
        go.Scatter(
            x=date_labels,
            y=max_ji_ban_days,
            name='最高几板',
            mode='lines+markers+text',
            line=dict(color='purple', width=2),
            marker=dict(symbol='star', size=10),
            text=max_ji_ban_labels,
            textposition='top center',
            textfont=dict(size=9, color='purple'),
            customdata=max_ji_ban_stocks,
            hovertemplate='几板: %{y}板<br>股票: %{customdata}<extra></extra>',  # 去掉日期
        ),
        secondary_y=True,
    )
    
    # 默默上涨线（独立Y轴）- 显示平均涨幅
    momo_trace_index = None
    if has_momo_data and momo_results:
        momo_zhangfus = [item[1] for item in momo_results]  # 平均涨幅
        # 悬浮窗股票列表：每5只股票换一行
        momo_all_stocks = []
        for item in momo_results:
            all_stocks = item[2]  # 所有股票
            if len(all_stocks) > 5:
                stock_lines = [', '.join(all_stocks[i:i+5]) for i in range(0, len(all_stocks), 5)]
                momo_all_stocks.append('<br>'.join(stock_lines))
            else:
                momo_all_stocks.append(', '.join(all_stocks))
        
        # 记录默默上涨trace的索引（当前是最后一个）
        momo_trace_index = len(fig.data)
        
        # 创建标签：显示前3只涨幅最高的股票
        momo_labels = []
        for item in momo_results:
            if item[1] is None:  # 没有数据
                momo_labels.append('')
            else:
                top_3 = item[3]  # 前3只涨幅最高的股票
                if len(top_3) > 0:
                    momo_labels.append('<br>'.join(top_3[:3]) if len(top_3) <= 3 else '<br>'.join(top_3[:3]) + '<br>……')
                else:
                    momo_labels.append('')
        
        fig.add_trace(
            go.Scatter(
                x=date_labels,
                y=momo_zhangfus,
                name='默默上涨(平均涨幅%)',
                mode='lines+markers+text',  # 添加text显示标签
                line=dict(color='brown', width=2, dash='dot'),
                marker=dict(symbol='diamond-open', size=8),
                text=momo_labels,  # 显示TOP3股票
                textposition='top center',
                textfont=dict(size=9, color='brown'),
                visible=False,  # 默认隐藏，不显示
                showlegend=True,  # 显示图例
                legendgroup='momo',  # 图例分组
                customdata=momo_all_stocks,
                # 独立悬浮窗，去掉日期（顶部已有）
                hovertemplate='平均涨幅: %{y:.1f}%<br>股票: %{customdata}<extra></extra>',
                hoverinfo='all',
                hoverlabel=dict(
                    bgcolor='rgba(139, 69, 19, 0.9)',  # 棕色背景
                    font=dict(color='white', size=12, family='SimHei')
                ),
                yaxis='y3',  # 使用第三个Y轴
            )
        )
    
    # 创建图层切换按钮（如果有默默上涨数据）
    updatemenus = []
    if momo_trace_index is not None:
        total_traces = len(fig.data)
        updatemenus = [
            dict(
                type="buttons",
                direction="left",
                buttons=[
                    dict(
                        args=[
                            {"visible": [True if i != momo_trace_index else False for i in range(total_traces)]},
                            {
                                "yaxis.visible": True,
                                "yaxis2.visible": True,
                                "yaxis3.visible": False,
                            }
                        ],
                        label="📊 连板天梯",
                        method="update"
                    ),
                    dict(
                        args=[
                            {"visible": [False if i != momo_trace_index else True for i in range(total_traces)]},
                            {
                                "yaxis.visible": False,
                                "yaxis2.visible": False,
                                "yaxis3.visible": True,
                            }
                        ],
                        label="📈 默默上涨",
                        method="update"
                    ),
                ],
                pad={"r": 10, "t": 10},
                showactive=True,
                active=0,  # 默认选中"连板天梯"
                x=0.15,
                xanchor="left",
                y=1.09,
                yanchor="top",
                bgcolor='rgba(255, 255, 255, 0.95)',
                bordercolor='#2196F3',
                borderwidth=2,
                font=dict(size=13, family='SimHei', color='#333'),
            ),
        ]
    
    # 更新布局
    fig.update_xaxes(
        title_text="日期",
        tickangle=-45,
        tickfont=dict(size=10),
        type='category',  # 确保日期按分类显示，不会自动格式化
    )
    
    fig.update_yaxes(
        title_text="数量",
        secondary_y=False,
        tickformat=',d',
        zeroline=True,
        zerolinewidth=2,
        zerolinecolor='gray',
    )
    
    fig.update_yaxes(
        title_text="连板/跌停/几板天数",
        secondary_y=True,
        tickformat=',d',
        zeroline=True,
        zerolinewidth=2,
        zerolinecolor='gray',
    )
    

    
    fig.update_layout(
        title=dict(
            text="连板/跌停/首板/默默上涨个股走势",
            x=0.5,
            xanchor='center',
            font=dict(size=20, family='SimHei'),
        ),
        hovermode='x unified',
        legend=dict(
            x=0.01,
            y=0.99,
            xanchor='left',
            yanchor='top',
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='gray',
            borderwidth=1,
        ),
        updatemenus=updatemenus,  # 添加切换按钮
        width=1800,
        height=900,
        font=dict(family='SimHei'),
        plot_bgcolor='white',
        paper_bgcolor='white',
        # 配置第三个Y轴（默默上涨专用）
        yaxis3=dict(
            title=dict(
                text="默默上涨涨幅(%)",
                font=dict(color='brown', size=12, family='SimHei')
            ),
            overlaying='y',  # 覆盖在主Y轴上
            side='right',    # 显示在右侧
            # 不设置position，让它自然靠近图表右侧
            showgrid=True,   # 显示网格线
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor='gray',
            tickfont=dict(color='brown', size=10),
            tickformat='.1f',
            ticksuffix='%',
            visible=False,   # 默认隐藏（连板天梯图层不显示）
        ),
    )
    
    # 添加网格线
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray', secondary_y=False)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray', secondary_y=True)
    
    # 生成文件名
    if output_path is None:
        date_range = ""
        if start_date and end_date:
            date_range = f"{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}"
        elif start_date:
            date_range = f"from_{start_date.strftime('%Y%m%d')}"
        elif end_date:
            date_range = f"to_{end_date.strftime('%Y%m%d')}"
        else:
            date_range = datetime.now().strftime('%Y%m%d')
        
        output_path = f"images/fupan_lb_{date_range}.html"
    
    # 确保目录存在
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    
    # 保存HTML文件
    fig.write_html(
        output_path,
        config={
            'displayModeBar': True,
            'displaylogo': False,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
            'toImageButtonOptions': {
                'format': 'png',
                'filename': 'fupan_lb',
                'height': 900,
                'width': 1800,
                'scale': 2
            }
        }
    )
    
    print(f"HTML图表已保存到: {output_path}")
    return output_path


def draw_fupan_lb_html(start_date=None, end_date=None, output_path=None):
    """
    生成HTML交互式复盘图的便捷函数
    
    Args:
        start_date: 开始日期（格式: YYYYMMDD）
        end_date: 结束日期（格式: YYYYMMDD）
        output_path: 输出HTML文件路径（可选）
    
    Returns:
        str: 生成的HTML文件路径
    """
    fupan_file = "./excel/fupan_stocks.xlsx"
    return read_and_plot_html(fupan_file, start_date, end_date, output_path)


if __name__ == '__main__':
    # 测试
    start_date = '20250830'
    end_date = None
    draw_fupan_lb_html(start_date, end_date) 