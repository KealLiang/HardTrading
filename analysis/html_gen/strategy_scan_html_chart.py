"""
策略扫描结果HTML交互式图表生成器

根据scan_summary文件生成策略扫描入选股的HTML交互式图表，按股票分组展示。
每只股票一张图，可以显示多个信号日期。

作者：AI Assistant
版本：v2.0
日期：2026-01-15
"""

import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils.backtrade.visualizer import read_stock_data
from utils.date_util import get_n_trading_days_before, get_next_trading_day, get_current_or_prev_trading_day
from utils.stock_util import calculate_period_change_from_date

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

# 信号类型配置：(匹配模式, 显示名称)
# 与 main.py 中的 signal_patterns 保持对应
SIGNAL_TYPE_CONFIG = [
    ('二次确认信号', '二次确认'),  # 标准通道：观察期内二次确认
    ('买入信号: 快速通道', '快速通道'),  # 快速通道：信号日当天买入
    ('买入信号: 回踩确认', '回踩确认'),  # 缓冲通道：回调后买入
    ('买入信号: 止损纠错', '止损纠错'),  # 止损纠错：价格合适买入
]

DEFAULT_BEFORE_DAYS = 60  # 信号日前显示的交易日数
DEFAULT_AFTER_DAYS = 30  # 信号日后显示的交易日数

# 涨跌幅计算周期（交易日）
PERIOD_DAYS = [30, 60, 120]  # 计算30日、60日、120日涨跌幅


def _extract_signal_type(details: str) -> str:
    """
    从详情字段中提取简短的信号类型描述
    
    Args:
        details: scan_summary中的详情字段
        
    Returns:
        简短的信号类型，如 "止损纠错"、"回踩确认"、"二次确认" 等
    """
    if not details:
        return "Signal"

    for pattern, signal_type in SIGNAL_TYPE_CONFIG:
        if pattern in details:
            return signal_type

    return "Signal"


def parse_scan_summary(summary_file_path: str) -> Dict[str, List[Dict]]:
    """
    解析scan_summary文件，按股票代码分组
    
    Args:
        summary_file_path: summary文件路径
        
    Returns:
        Dict[股票代码, List[股票信息字典]]
        股票信息字典包含: code, name, signal_date, signal_type, price, score, details
    """
    stock_signals_map = defaultdict(list)

    try:
        with open(summary_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            if line.strip() and not line.startswith('扫描策略') and not line.startswith(
                    '扫描范围') and not line.startswith('总计发现') and not line.startswith('-'):
                # 解析格式：股票: 300732 设研院, 信号日期: 2025-08-11, 价格: 12.22, 评分: 0，详情: ...
                stock_match = re.search(r'股票:\s*(\d{6})\s*([^,]*)', line)
                date_match = re.search(r'信号日期:\s*(\d{4}-\d{2}-\d{2})', line)
                price_match = re.search(r'价格:\s*([\d.]+)', line)
                score_match = re.search(r'评分:\s*([^,]+)', line)
                details_match = re.search(r'详情:\s*(.+)$', line)

                if stock_match and date_match:
                    code = stock_match.group(1)
                    name = stock_match.group(2).strip()
                    signal_date = date_match.group(1)
                    price = float(price_match.group(1)) if price_match else None
                    score = score_match.group(1).strip() if score_match else None
                    details = details_match.group(1).strip() if details_match else ''
                    signal_type = _extract_signal_type(details)

                    stock_info = {
                        'code': code,
                        'name': name,
                        'signal_date': signal_date,
                        'signal_type': signal_type,
                        'price': price,
                        'score': score,
                        'details': details
                    }
                    stock_signals_map[code].append(stock_info)

        logging.info(f"解析完成，共找到 {len(stock_signals_map)} 只股票")
        for code, signals in list(stock_signals_map.items())[:5]:
            logging.info(f"  {code}: {len(signals)} 个信号")

    except Exception as e:
        logging.error(f"解析scan_summary文件失败: {e}")

    return stock_signals_map


def _calculate_period_changes(stock_code: str, signal_date: str, data_dir: str) -> Dict[int, float]:
    """
    计算股票从信号日期往前数N个交易日到信号日期的各周期涨跌幅
    
    Args:
        stock_code: 股票代码
        signal_date: 信号日期 YYYYMMDD
        data_dir: 数据目录
        
    Returns:
        Dict[周期天数, 涨跌幅百分比]
    """
    period_changes = {}

    # 计算各周期涨跌幅（从信号日期往前数N个交易日）
    for period in PERIOD_DAYS:
        try:
            change = calculate_period_change_from_date(stock_code, signal_date, period, data_dir)
            if change is not None:
                period_changes[period] = change
        except Exception as e:
            logging.debug(f"计算 {stock_code} {period}日涨跌幅失败: {e}")

    return period_changes


def _format_title(stock_code: str, stock_name: str, signal_dates_info: List[Dict]) -> str:
    """
    格式化图表标题
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        signal_dates_info: 信号日期信息列表
        
    Returns:
        格式化的标题HTML字符串
    """
    title_parts = [f"<b>{stock_code} {stock_name}</b>"]

    # 显示所有信号日期
    signal_info_parts = []
    for sig_info in signal_dates_info:
        signal_date = sig_info['signal_date']
        signal_type = sig_info.get('signal_type', 'Signal')
        price = sig_info.get('price')
        if price:
            signal_info_parts.append(f"{signal_date} ({signal_type}) @ {price:.2f}")
        else:
            signal_info_parts.append(f"{signal_date} ({signal_type})")

    if signal_info_parts:
        title_parts.append("信号: " + " | ".join(signal_info_parts))

    # 计算最新信号的周期涨跌幅
    if signal_dates_info:
        latest_signal = max(signal_dates_info, key=lambda x: x['signal_date'])
        signal_date_yyyymmdd = latest_signal['signal_date'].replace("-", "")
        period_changes = _calculate_period_changes(stock_code, signal_date_yyyymmdd, './data/astocks')

        if period_changes:
            change_items = []
            for period in sorted(period_changes.keys()):
                change = period_changes[period]
                # A股习惯：红涨绿跌
                color = 'red' if change > 0 else 'green' if change < 0 else 'gray'
                change_items.append(f"<span style='color:{color}'>{period}日: {change:+.2f}%</span>")

            if change_items:
                title_parts.append(" | ".join(change_items))

    return "<br>".join(title_parts)


def _create_single_chart_figure(
        stock_code: str,
        stock_name: str,
        chart_df: pd.DataFrame,
        signal_dates_info: List[Dict],
        before_days: int = DEFAULT_BEFORE_DAYS,
        after_days: int = DEFAULT_AFTER_DAYS,
        data_dir: str = './data/astocks'
) -> Optional[go.Figure]:
    """
    创建单个图表的Figure对象，支持多个信号日期标记
    
    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        chart_df: K线数据DataFrame
        signal_dates_info: 信号日期信息列表
        before_days: 信号日前显示的交易日数
        after_days: 信号日后显示的交易日数
        data_dir: 数据目录
        
    Returns:
        go.Figure: Plotly图表对象
    """
    try:
        # 创建子图：主图（K线）+ 成交量图
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],
            subplot_titles=('', '成交量')
        )

        # 准备数据 - 使用连续索引避免x轴留空
        dates = chart_df.index
        x_indices = list(range(len(chart_df)))
        date_labels = [d.strftime('%Y-%m-%d') for d in dates]

        # 转换为列表
        opens = chart_df['Open'].values.tolist()
        highs = chart_df['High'].values.tolist()
        lows = chart_df['Low'].values.tolist()
        closes = chart_df['Close'].values.tolist()
        volumes = chart_df['Volume'].values.tolist()

        # 验证数据有效性
        if len(opens) == 0:
            return None

        # 1. 绘制K线图
        candlestick = go.Candlestick(
            x=x_indices,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name='K线',
            increasing_line_color='#ff4444',
            decreasing_line_color='#00aa00',
            increasing_fillcolor='#ff4444',
            decreasing_fillcolor='#00aa00'
        )
        fig.add_trace(candlestick, row=1, col=1)

        # 1.1 计算并添加5日均线
        ma5 = pd.Series(closes).rolling(window=5, min_periods=1).mean()
        ma5_line = go.Scatter(
            x=x_indices,
            y=ma5.tolist(),
            mode='lines',
            name='MA5',
            line=dict(color='#FFA500', width=1.5),
            hovertemplate='MA5: %{y:.2f}<extra></extra>'
        )
        fig.add_trace(ma5_line, row=1, col=1)

        # 1.2 计算并添加10日均线
        ma10 = pd.Series(closes).rolling(window=10, min_periods=1).mean()
        ma10_line = go.Scatter(
            x=x_indices,
            y=ma10.tolist(),
            mode='lines',
            name='MA10',
            line=dict(color='#0000FF', width=1.5),
            hovertemplate='MA10: %{y:.2f}<extra></extra>'
        )
        fig.add_trace(ma10_line, row=1, col=1)

        # 2. 添加所有信号日期标记（不同颜色区分）
        signal_colors = ['blue', 'purple', 'orange', 'red', 'green', 'brown']
        signal_symbols = ['triangle-up', 'triangle-down', 'diamond', 'square', 'star', 'circle']

        for idx, sig_info in enumerate(signal_dates_info):
            signal_date = sig_info['signal_date']
            signal_type = sig_info.get('signal_type', 'Signal')
            price = sig_info.get('price')

            try:
                signal_date_dt = datetime.strptime(signal_date, '%Y-%m-%d')
                # 查找信号日期在数据中的位置
                signal_idx = None
                for i, date in enumerate(dates):
                    if date.date() == signal_date_dt.date():
                        signal_idx = i
                        break

                if signal_idx is not None and 0 <= signal_idx < len(chart_df):
                    # 信号标记放在K线下方，使用当日最低价的95%位置
                    signal_price = chart_df.iloc[signal_idx]['Low'] * 0.95
                    # 如果价格信息存在，在悬停时显示
                    display_price = price if price is not None else chart_df.iloc[signal_idx]['Close']

                    color = signal_colors[idx % len(signal_colors)]
                    symbol = signal_symbols[idx % len(signal_symbols)]

                    signal_marker = go.Scatter(
                        x=[signal_idx],
                        y=[signal_price],
                        mode='markers',
                        marker=dict(
                            symbol=symbol,
                            size=15,
                            color=color,
                            line=dict(width=1, color='darkblue')
                        ),
                        name=f'{signal_date} ({signal_type})',
                        hovertemplate=f'信号日: {signal_date}<br>类型: {signal_type}<br>价格: {display_price:.2f}<extra></extra>'
                    )
                    fig.add_trace(signal_marker, row=1, col=1)
            except Exception as e:
                logging.debug(f"添加信号标记失败 {signal_date}: {e}")

        # 3. 绘制成交量柱状图
        colors = ['#ff4444' if closes[i] >= opens[i] else '#00aa00'
                  for i in range(len(chart_df))]

        volume_bar = go.Bar(
            x=x_indices,
            y=volumes,
            name='成交量',
            marker_color=colors,
            opacity=0.6
        )
        fig.add_trace(volume_bar, row=2, col=1)

        # 4. 生成标题
        title = _format_title(stock_code, stock_name, signal_dates_info)

        # 5. 更新布局
        fig.update_layout(
            title=dict(
                text=title,
                x=0.05,
                xanchor='left',
                font=dict(size=11, color='black')
            ),
            height=600,
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
            xaxis_rangeslider_visible=False,
            margin=dict(l=50, r=50, t=120, b=50)
        )

        # 6. 更新坐标轴
        fig.update_xaxes(title_text="", row=2, col=1)
        fig.update_yaxes(title_text="价格", row=1, col=1, title_font=dict(size=10))
        fig.update_yaxes(title_text="成交量", row=2, col=1, title_font=dict(size=10))

        # 7. 设置x轴刻度
        tick_step = max(1, len(chart_df) // 10)
        tick_indices = list(range(0, len(chart_df), tick_step))
        if len(chart_df) - 1 not in tick_indices:
            tick_indices.append(len(chart_df) - 1)

        tick_texts = [date_labels[i] for i in tick_indices]

        fig.update_xaxes(
            type='linear',
            tickmode='array',
            tickvals=tick_indices,
            ticktext=tick_texts,
            tickangle=-45,
            row=2, col=1
        )
        fig.update_xaxes(
            type='linear',
            tickmode='array',
            tickvals=tick_indices,
            ticktext=tick_texts,
            tickangle=-45,
            row=1, col=1
        )

        return fig

    except Exception as e:
        logging.error(f"创建图表失败 {stock_code} {stock_name}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def _create_combined_html(figures: List[go.Figure], titles: List[str],
                          columns: int, rows: int) -> str:
    """创建包含所有图表的单个HTML文件，使用多个Plotly CDN备用源"""
    import json

    # 生成每个图表的JSON数据和div
    chart_data_list = []
    chart_divs = []

    for i, fig in enumerate(figures):
        fig_json_str = fig.to_json()
        fig_dict = json.loads(fig_json_str)
        chart_data_list.append(fig_dict)

        chart_div = f'<div id="chart_{i}" style="width:100%;height:600px;"></div>'
        chart_divs.append(chart_div)

    # 构建完整的HTML，使用多个Plotly CDN备用源
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>策略扫描结果</title>
    <!-- 多个Plotly CDN备用源 -->
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js" 
            onerror="this.onerror=null;this.src='https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.26.0/plotly.min.js';"></script>
    <script>
        // 如果第一个CDN失败，尝试第二个
        if (typeof Plotly === 'undefined') {{
            var script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.26.0/plotly.min.js';
            script.onerror = function() {{
                // 如果第二个也失败，尝试第三个
                script.src = 'https://unpkg.com/plotly.js@2.26.0/dist/plotly.min.js';
            }};
            document.head.appendChild(script);
        }}
    </script>
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
            background-color: white;
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .chart-title {{
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 10px;
            color: #333;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>策略扫描结果</h1>
        <p>共 {len(figures)} 只股票</p>
    </div>
    
    <div style="display: grid; grid-template-columns: repeat({columns}, 1fr); gap: 20px;">
"""

    # 添加每个图表
    for i, title in enumerate(titles):
        html_template += f"""
        <div class="chart-container">
            <div class="chart-title">{title}</div>
            {chart_divs[i]}
        </div>
"""

    html_template += """
    </div>
    
    <script>
        // 等待Plotly加载完成
        function initCharts() {
            if (typeof Plotly === 'undefined') {
                setTimeout(initCharts, 100);
                return;
            }
            
            const chartData = """ + json.dumps(chart_data_list, ensure_ascii=False) + """;
            
            chartData.forEach((data, index) => {
                Plotly.newPlot(`chart_${index}`, data.data, data.layout, {
                    responsive: true,
                    displayModeBar: true
                });
            });
        }
        
        // 页面加载完成后初始化图表
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initCharts);
        } else {
            initCharts();
        }
    </script>
</body>
</html>"""

    return html_template


def generate_strategy_scan_html_charts(
        base_dir: str,
        recent_days: int = 10,
        columns: int = 2,
        before_days: int = DEFAULT_BEFORE_DAYS,
        after_days: int = DEFAULT_AFTER_DAYS,
        output_dir: Optional[str] = None,
        data_dir: str = './data/astocks'
) -> Optional[str]:
    """
    生成策略扫描结果的HTML交互式图表
    
    按股票分组，每只股票一张图，可以显示多个信号日期。
    一次执行只生成一个HTML文件。
    
    Args:
        base_dir: 扫描结果基础目录（如 'bin/candidate_stocks_breakout_a'）
        recent_days: 只处理最近几天的信号，默认10天
        columns: 横向并排显示的列数（1、2或3），默认2
        before_days: 信号日前显示的交易日数，默认60
        after_days: 信号日后显示的交易日数，默认30
        output_dir: 输出目录，如果为None则使用 base_dir/html_charts
        data_dir: 股票数据目录
        
    Returns:
        str: 生成的HTML文件路径，失败返回None
    """
    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    # 查找最新的summary文件
    summary_files = [f for f in os.listdir(base_dir) if
                     f.startswith('scan_summary_') and f.endswith('.txt')]

    if not summary_files:
        logging.error(f"在目录 {base_dir} 中没有找到scan_summary文件")
        return None

    # 选择最新的summary文件
    latest_summary = sorted(summary_files)[-1]
    summary_path = os.path.join(base_dir, latest_summary)

    logging.info(f"使用summary文件: {summary_path}")

    # 解析summary文件，按股票分组
    stock_signals_map = parse_scan_summary(summary_path)

    if not stock_signals_map:
        logging.error("没有找到有效的股票信号数据")
        return None

    # 过滤：只保留最近recent_days天的信号
    current_date = get_current_or_prev_trading_day(datetime.now().strftime("%Y%m%d"))
    if current_date and "-" in current_date:
        current_date = current_date.replace("-", "")

    filtered_stocks = {}
    for code, signals in stock_signals_map.items():
        # 只保留最近recent_days天的信号
        recent_signals = []
        for sig in signals:
            signal_date_yyyymmdd = sig['signal_date'].replace("-", "")
            if current_date and signal_date_yyyymmdd >= current_date:
                # 如果是今天或未来的日期，保留
                recent_signals.append(sig)
            else:
                # 计算日期差（简化处理，假设每天都是交易日）
                try:
                    sig_dt = datetime.strptime(signal_date_yyyymmdd, '%Y%m%d')
                    curr_dt = datetime.strptime(current_date, '%Y%m%d') if current_date else datetime.now()
                    days_diff = (curr_dt - sig_dt).days
                    if days_diff <= recent_days * 2:  # 粗略估算，包含非交易日
                        recent_signals.append(sig)
                except:
                    recent_signals.append(sig)

        if recent_signals:
            filtered_stocks[code] = recent_signals

    if not filtered_stocks:
        logging.warning("过滤后没有找到符合条件的股票")
        return None

    logging.info(f"处理 {len(filtered_stocks)} 只股票")

    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.join(base_dir, 'html_charts')
    os.makedirs(output_dir, exist_ok=True)

    chart_figures = []
    chart_titles = []

    # 为每只股票生成图表
    for stock_code, signals_info in filtered_stocks.items():
        try:
            stock_name = signals_info[0]['name']  # 使用第一个信号的名称

            # 找到所有信号日期的最早和最晚日期
            signal_dates = [sig['signal_date'] for sig in signals_info]
            earliest_date = min(signal_dates)
            latest_date = max(signal_dates)

            # 计算绘图范围：从最早信号前before_days天到最晚信号后after_days天
            earliest_date_yyyymmdd = earliest_date.replace("-", "")
            latest_date_yyyymmdd = latest_date.replace("-", "")

            chart_start = get_n_trading_days_before(earliest_date_yyyymmdd, before_days)
            chart_end_str = latest_date_yyyymmdd

            for _ in range(after_days):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break

            # 读取股票数据
            stock_data = read_stock_data(stock_code, data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {stock_code} {stock_name} 的数据文件")
                continue

            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')

            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 在指定日期范围内无数据")
                continue

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {stock_code} {stock_name} 清理停牌数据后无有效数据")
                continue

            # 创建图表figure（包含所有信号日期）
            fig = _create_single_chart_figure(
                stock_code=stock_code,
                stock_name=stock_name,
                chart_df=chart_df,
                signal_dates_info=signals_info,
                before_days=before_days,
                after_days=after_days,
                data_dir=data_dir
            )

            if fig is not None:
                chart_figures.append(fig)
                # 生成标题
                signal_count = len(signals_info)
                title = f"{stock_code} {stock_name} ({signal_count}个信号)"
                chart_titles.append(title)

        except Exception as e:
            logging.error(f"生成股票 {stock_code} 的HTML图表失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            continue

    if not chart_figures:
        logging.warning("没有可用的图表，跳过HTML生成")
        return None

    # 计算网格布局
    num_charts = len(chart_figures)
    rows = (num_charts + columns - 1) // columns

    # 创建包含所有图表的HTML
    html_content = _create_combined_html(chart_figures, chart_titles, columns, rows)

    # 保存HTML文件（只生成一个文件）
    html_filename = f"strategy_scan_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"HTML图表生成完成: {html_path} (共 {num_charts} 个图表)")
    return html_path


if __name__ == '__main__':
    # 测试代码
    base_dir = 'bin/candidate_stocks_breakout_a'
    file = generate_strategy_scan_html_charts(
        base_dir=base_dir,
        recent_days=15,
        columns=2,
        before_days=60,
        after_days=30
    )

    if file:
        print(f"\n✅ 成功生成HTML文件: {file}")
    else:
        print("❌ 没有生成HTML文件")
