"""
爆量分歧转一致形态HTML交互式图表生成器

使用Plotly生成交互式HTML图表，展示和PNG图相同的内容：
- K线图（蜡烛图）
- 成交量柱状图
- 爆量日标记（蓝色向上三角）
- 成交量面板标记（紫色星号）

支持生成单个HTML文件，使用网格布局，支持1/2/3列并排显示。

作者：AI Assistant
版本：v2.0
日期：2025-01-XX
"""

import logging
import os
from datetime import datetime
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analysis.pattern_analyzer_base import PatternInfo


def _create_single_chart_figure(
        pattern_info: PatternInfo,
        chart_df: pd.DataFrame,
        title: str
) -> go.Figure:
    """
    创建单个图表的Figure对象（用于合并到总HTML中）
    
    Args:
        pattern_info: 形态信息（包含所有信号日期）
        chart_df: K线数据DataFrame，索引为日期，包含Open/High/Low/Close/Volume列
        title: 图表标题
        
    Returns:
        go.Figure: Plotly图表对象
    """
    try:
        # 创建子图：主图（K线）+ 成交量图
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],  # K线图占70%，成交量图占30%
            subplot_titles=('', '成交量')
        )

        # 准备数据 - 使用连续索引避免x轴留空
        dates = chart_df.index
        # 使用连续整数索引，避免非交易日留空
        x_indices = list(range(len(chart_df)))
        # 保存日期映射用于hover显示
        date_labels = [d.strftime('%Y-%m-%d') for d in dates]

        # 转换为列表，确保Plotly能正确处理
        opens = chart_df['Open'].values.tolist()
        highs = chart_df['High'].values.tolist()
        lows = chart_df['Low'].values.tolist()
        closes = chart_df['Close'].values.tolist()
        volumes = chart_df['Volume'].values.tolist()

        # 验证数据有效性
        if len(opens) == 0 or len(highs) == 0 or len(lows) == 0 or len(closes) == 0:
            logging.warning(f"股票 {pattern_info.code} 数据为空，跳过图表生成")
            return None

        # 1. 绘制K线图（蜡烛图）- 使用连续索引
        # 注意：Candlestick不支持hovertemplate，使用默认hover或hovertext
        candlestick = go.Candlestick(
            x=x_indices,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name='K线',
            increasing_line_color='#ff4444',  # 上涨红色
            decreasing_line_color='#00aa00',  # 下跌绿色
            increasing_fillcolor='#ff4444',
            decreasing_fillcolor='#00aa00'
            # 不设置hover相关属性，使用默认hover行为（会显示open/high/low/close）
        )
        fig.add_trace(candlestick, row=1, col=1)

        # 2. 添加爆量日标记（蓝色向上三角）
        surge_dates = []
        surge_prices = []
        surge_labels = []

        for date_str in pattern_info.pattern_dates:
            pattern_date_dt = datetime.strptime(date_str, '%Y%m%d')
            try:
                # 查找对应的索引
                idx = chart_df.index.searchsorted(pattern_date_dt, side='right') - 1
                if 0 <= idx < len(chart_df):
                    surge_dates.append(idx)  # 使用连续索引
                    # 标记位置：当日最低价的97%（在K线下方）
                    surge_prices.append(chart_df.iloc[idx]['Low'] * 0.97)
                    # 生成标签信息
                    extra = pattern_info.extra_data
                    if len(pattern_info.pattern_dates) > 1:
                        # 多信号情况，显示所有信号信息
                        all_signals = extra.get('all_signals', [])
                        signal_info = all_signals[pattern_info.pattern_dates.index(date_str)]
                        volume_ratio = signal_info.get('volume_ratio', 'N/A')
                        pct_change = signal_info.get('pct_change', 'N/A')
                        label = f"爆量日: {date_str}<br>量比: {volume_ratio}倍<br>涨幅: {pct_change}%"
                    else:
                        # 单信号情况
                        volume_ratio = extra.get('volume_ratio', 'N/A')
                        pct_change = extra.get('pct_change', 'N/A')
                        label = f"爆量日: {date_str}<br>量比: {volume_ratio}倍<br>涨幅: {pct_change}%"
                    surge_labels.append(label)
            except Exception as e:
                logging.warning(f"添加爆量日标记失败 {date_str}: {e}")
                continue

        if surge_dates:
            surge_marker = go.Scatter(
                x=surge_dates,
                y=surge_prices,
                mode='markers',
                marker=dict(
                    symbol='triangle-up',
                    size=15,
                    color='blue',
                    line=dict(width=1, color='darkblue')
                ),
                name=f'爆量日({len(surge_dates)}个)',
                hovertemplate='%{text}<extra></extra>',
                text=surge_labels
            )
            fig.add_trace(surge_marker, row=1, col=1)

        # 3. 绘制成交量柱状图 - 使用连续索引
        # 根据涨跌设置颜色
        colors = ['#ff4444' if closes[i] >= opens[i] else '#00aa00'
                  for i in range(len(chart_df))]

        # 生成成交量hover文本
        volume_hover_texts = [
            f'日期: {date_labels[i]}<br>成交量: {volumes[i]:,.0f}'
            for i in range(len(chart_df))
        ]

        volume_bar = go.Bar(
            x=x_indices,
            y=volumes,
            name='成交量',
            marker_color=colors,
            opacity=0.6,
            hovertext=volume_hover_texts,
            hoverinfo='text'
        )
        fig.add_trace(volume_bar, row=2, col=1)

        # 4. 添加成交量面板标记（紫色星号）
        volume_marker_dates = []
        volume_marker_values = []
        volume_marker_labels = []

        for date_str in pattern_info.pattern_dates:
            pattern_date_dt = datetime.strptime(date_str, '%Y%m%d')
            try:
                idx = chart_df.index.searchsorted(pattern_date_dt, side='right') - 1
                if 0 <= idx < len(chart_df):
                    volume_marker_dates.append(idx)  # 使用连续索引
                    volume_marker_values.append(chart_df.iloc[idx]['Volume'])
                    # 生成标签信息
                    extra = pattern_info.extra_data
                    if len(pattern_info.pattern_dates) > 1:
                        all_signals = extra.get('all_signals', [])
                        signal_info = all_signals[pattern_info.pattern_dates.index(date_str)]
                        volume_ratio = signal_info.get('volume_ratio', 'N/A')
                        volume = signal_info.get('current_volume', 'N/A')
                        avg_volume = signal_info.get('avg_volume', 'N/A')
                        label = f"爆量: {date_str}<br>量比: {volume_ratio}倍<br>当日量: {volume:.0f}<br>均量: {avg_volume:.0f}"
                    else:
                        volume_ratio = extra.get('volume_ratio', 'N/A')
                        volume = extra.get('current_volume', 'N/A')
                        avg_volume = extra.get('avg_volume', 'N/A')
                        label = f"爆量: {date_str}<br>量比: {volume_ratio}倍<br>当日量: {volume:.0f}<br>均量: {avg_volume:.0f}"
                    volume_marker_labels.append(label)
            except Exception as e:
                logging.warning(f"添加成交量标记失败 {date_str}: {e}")
                continue

        if volume_marker_dates:
            volume_marker = go.Scatter(
                x=volume_marker_dates,
                y=volume_marker_values,
                mode='markers',
                marker=dict(
                    symbol='star',
                    size=12,
                    color='magenta',
                    line=dict(width=1, color='darkmagenta')
                ),
                name='爆量',
                hovertemplate='%{text}<extra></extra>',
                text=volume_marker_labels,
                showlegend=True
            )
            fig.add_trace(volume_marker, row=2, col=1)

        # 5. 更新布局
        fig.update_layout(
            title=dict(
                text=title,
                x=0.05,
                xanchor='left',
                font=dict(size=12, color='black')
            ),
            height=600,  # 降低高度，适合网格布局
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=9)
            ),
            hovermode='x unified',
            template='plotly_white',
            xaxis_rangeslider_visible=False,  # 隐藏底部滑块
            margin=dict(l=50, r=50, t=80, b=50)
        )

        # 6. 更新坐标轴标签
        fig.update_xaxes(title_text="", row=2, col=1)  # 底部x轴不显示标题（节省空间）
        fig.update_yaxes(title_text="价格", row=1, col=1, title_font=dict(size=10))
        fig.update_yaxes(title_text="成交量", row=2, col=1, title_font=dict(size=10))

        # 7. 设置x轴刻度 - 使用日期标签但基于连续索引
        # 只显示部分日期标签，避免过于拥挤
        tick_step = max(1, len(chart_df) // 10)  # 大约显示10个标签
        tick_indices = list(range(0, len(chart_df), tick_step))
        if len(chart_df) - 1 not in tick_indices:
            tick_indices.append(len(chart_df) - 1)

        tick_texts = [date_labels[i] for i in tick_indices]

        # 设置x轴类型为线性（使用连续索引）
        fig.update_xaxes(
            type='linear',  # 使用线性轴，支持连续索引
            tickmode='array',
            tickvals=tick_indices,
            ticktext=tick_texts,
            tickangle=-45,
            row=2, col=1
        )
        fig.update_xaxes(
            type='linear',  # 使用线性轴，支持连续索引
            tickmode='array',
            tickvals=tick_indices,
            ticktext=tick_texts,
            tickangle=-45,
            row=1, col=1
        )

        return fig

    except Exception as e:
        logging.error(f"创建图表失败 {pattern_info.code} {pattern_info.name}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def generate_html_charts_for_analyzer(
        analyzer,
        output_dir: Optional[str] = None,
        columns: int = 2
) -> str:
    """
    为VolumeSurgeAnalyzer生成单个HTML文件，包含所有股票的图表
    
    Args:
        analyzer: VolumeSurgeAnalyzer实例
        output_dir: 输出目录，如果为None则使用analyzer.output_dir
        columns: 横向并排显示的列数（1、2或3），默认2
        
    Returns:
        str: 生成的HTML文件路径
    """
    # 输出路径统一改为 images/html_charts
    output_dir = './images/html_charts'

    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    from utils.backtrade.visualizer import read_stock_data
    from utils.date_util import get_n_trading_days_before, get_next_trading_day

    logging.info(f"开始生成HTML图表，共 {len(analyzer.filtered_stocks)} 只股票，布局: {columns}列...")

    # 按入选日期倒序排序（最近的在前）
    sorted_stocks = sorted(analyzer.filtered_stocks, key=lambda x: x.pattern_date, reverse=True)

    # 收集所有图表的figure对象
    chart_figures = []
    chart_titles = []

    for pattern_info in sorted_stocks:
        try:
            code_6digit = analyzer._extract_stock_code(pattern_info.code)

            # 计算绘图范围
            all_dates = pattern_info.pattern_dates
            first_date = min(all_dates)
            last_date = max(all_dates)

            chart_start = get_n_trading_days_before(first_date, analyzer.config.before_days)
            chart_end_str = last_date
            for _ in range(analyzer.config.after_days):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break

            # 读取股票数据
            stock_data = read_stock_data(code_6digit, analyzer.config.data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {code_6digit} {pattern_info.name} 的数据文件")
                continue

            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')

            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {pattern_info.name} 在指定日期范围内无数据")
                continue

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {pattern_info.name} 清理停牌数据后无有效数据")
                continue

            # 获取图表标题
            title = analyzer.get_chart_title(pattern_info)

            # 创建图表figure
            fig = _create_single_chart_figure(
                pattern_info=pattern_info,
                chart_df=chart_df,
                title=title
            )

            if fig is not None:
                chart_figures.append(fig)
                chart_titles.append(title)

        except Exception as e:
            logging.error(f"生成股票 {pattern_info.code} {pattern_info.name} 的HTML图表失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            continue

    if not chart_figures:
        logging.warning("没有可用的图表，跳过HTML生成")
        return None

    # 计算网格布局
    num_charts = len(chart_figures)
    rows = (num_charts + columns - 1) // columns  # 向上取整

    # 创建包含所有图表的HTML
    html_content = _create_combined_html(chart_figures, chart_titles, columns, rows)

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 保存HTML文件
    html_filename = f"volume_surge_charts_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"HTML图表生成完成，共 {num_charts} 个图表，保存在: {html_path}")

    return html_path


def _create_combined_html(figures: List[go.Figure], titles: List[str], columns: int, rows: int) -> str:
    """
    创建包含所有图表的单个HTML文件
    
    Args:
        figures: 图表figure对象列表
        titles: 图表标题列表
        columns: 列数
        rows: 行数
        
    Returns:
        str: HTML内容
    """
    import json

    # 生成每个图表的JSON数据和div
    chart_data_list = []
    chart_divs = []

    for i, fig in enumerate(figures):
        # 将figure转换为JSON字符串，然后解析为Python字典
        fig_json_str = fig.to_json()
        fig_dict = json.loads(fig_json_str)
        chart_data_list.append(fig_dict)

        # 创建div容器
        chart_div = f'<div id="chart_{i}" style="width:100%;height:600px;"></div>'
        chart_divs.append(chart_div)

    # 构建完整的HTML
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>爆量分歧转一致形态分析图表</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            color: #333;
        }}
        .header p {{
            margin: 10px 0 0 0;
            color: #666;
        }}
        .chart-container {{
            margin-bottom: 30px;
            background-color: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .chart-grid {{
            display: grid;
            grid-template-columns: repeat({columns}, 1fr);
            gap: 20px;
        }}
        @media (max-width: 1200px) {{
            .chart-grid {{
                grid-template-columns: repeat({min(columns, 2)}, 1fr);
            }}
        }}
        @media (max-width: 768px) {{
            .chart-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>爆量分歧转一致形态分析图表</h1>
        <p>共 {len(figures)} 只股票 | 布局: {columns}列 | 支持缩放、平移、悬停查看详情</p>
    </div>
    
    <div class="chart-grid">
"""

    # 添加所有图表div
    for i, div in enumerate(chart_divs):
        html_template += f"""        <div class="chart-container">
            {div}
        </div>
"""

    html_template += """    </div>
    
    <script>
        // 图表数据 - 使用JSON.parse解析JSON字符串
        var chartData = """

    # 将Python字典列表转换为JSON字符串
    chart_data_json = json.dumps(chart_data_list, ensure_ascii=False, indent=2)
    html_template += chart_data_json

    html_template += """;
        
        // 渲染所有图表
        for (var i = 0; i < chartData.length; i++) {
            Plotly.newPlot('chart_' + i, chartData[i].data, chartData[i].layout, {
                displayModeBar: true,
                displaylogo: false,
                responsive: true
            });
        }
    </script>
</body>
</html>"""

    return html_template
