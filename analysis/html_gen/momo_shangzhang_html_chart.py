"""
【默默上涨】HTML交互式图表生成器

使用Plotly生成交互式HTML图表，展示【默默上涨】股票的K线图：
- K线图（蜡烛图）
- 成交量柱状图
- 入选日标记（蓝色向上三角）

作者：AI Assistant
版本：v1.0
日期：2025-01-XX
"""

import logging
import os
import re
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils.backtrade.visualizer import read_stock_data
from utils.date_util import get_n_trading_days_before, get_next_trading_day, get_trading_days

# 【默默上涨】相关参数
FUPAN_FILE = "./excel/fupan_stocks.xlsx"
DEFAULT_DAYS = 20  # 默认最近20个交易日


def _parse_momo_cell(cell_value: str) -> Optional[Dict]:
    """解析【默默上涨】数据单元格"""
    if pd.isna(cell_value) or not cell_value:
        return None

    try:
        parts = [p.strip() for p in str(cell_value).split(';')]
        if len(parts) < 2:
            return None

        return {
            'code': parts[0],
            'name': parts[1] if len(parts) > 1 else '',
            'latest_price': parts[2] if len(parts) > 2 else '',
            'latest_change': parts[3] if len(parts) > 3 else '',
            'interval_change': parts[4] if len(parts) > 4 else '',
            'interval_turnover': parts[5] if len(parts) > 5 else '',
            'interval_amplitude': parts[6] if len(parts) > 6 else '',
            'listing_days': parts[7] if len(parts) > 7 else ''
        }
    except Exception as e:
        logging.warning(f"解析单元格失败: {cell_value}, 错误: {e}")
        return None


def _parse_column_date(column_date: str) -> Optional[datetime]:
    """将Excel列名日期转为datetime"""
    try:
        # 格式1: YYYY年MM月DD日
        match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', column_date)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return datetime(year, month, day)

        # 格式2: YYYY/MM/DD
        match = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', column_date)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return datetime(year, month, day)

        # 格式3: 直接解析
        return pd.to_datetime(column_date)
    except:
        return None


def load_momo_stocks_for_period(days: int = DEFAULT_DAYS) -> List[Dict]:
    """
    加载指定天数内的【默默上涨】股票数据（去重）
    
    逻辑：
    1. 先读取所有可用的日期数据，记录每只股票在所有日期的出现情况
    2. 对于每只股票，在指定时间范围内找到最近一次连续入选的起始日期
       （连续入选：在trading_days中相邻的日期都出现，算作同一次入选）
    3. 使用该起始日期的数据（区间涨跌幅等）
    4. 筛选出入选日期在最近N个交易日内的股票
    
    Args:
        days: 最近N个交易日，默认20
        
    Returns:
        List[Dict]: 股票信息列表，每个元素包含 {code, name, entry_date, extra_data}
    """
    try:
        # 读取【默默上涨】数据
        df = pd.read_excel(FUPAN_FILE, sheet_name="默默上涨", index_col=0)

        # 获取最近N个交易日（用于最终筛选）
        today_str = datetime.now().strftime('%Y%m%d')
        start_date_str = get_n_trading_days_before(today_str, days)
        # 处理日期格式（可能带横线）
        if '-' in start_date_str:
            start_date_str = start_date_str.replace('-', '')

        trading_days = get_trading_days(start_date_str, today_str)
        trading_days_set = set(trading_days)  # 用于最终筛选

        if not trading_days:
            logging.warning("未找到交易日数据")
            return []

        # 第一步：读取所有日期列，找到每只股票的真实入选日期
        all_date_columns = []
        for col in df.columns:
            col_date = _parse_column_date(str(col))
            if col_date:
                date_str = col_date.strftime('%Y%m%d')
                all_date_columns.append((col, date_str))

        if not all_date_columns:
            logging.warning("未找到任何日期列数据")
            return []

        # 第二步：收集所有股票，找到每只股票在指定时间范围内的所有入选日期
        stocks_appearances = {}  # {code: {name, dates: [date_str, ...], data_by_date: {date_str: extra_data}}}

        for col, date_str in all_date_columns:
            for idx, cell_value in df[col].items():
                parsed = _parse_momo_cell(cell_value)
                if not parsed:
                    continue

                code = parsed['code']
                # 提取纯代码（去除市场后缀）
                pure_code = code.split('.')[0] if '.' in code else code

                if pure_code not in stocks_appearances:
                    stocks_appearances[pure_code] = {
                        'code': code,
                        'name': parsed['name'],
                        'dates': [],
                        'data_by_date': {}
                    }

                # 记录该日期出现的数据
                stocks_appearances[pure_code]['dates'].append(date_str)
                stocks_appearances[pure_code]['data_by_date'][date_str] = {
                    'latest_price': parsed.get('latest_price', ''),
                    'latest_change': parsed.get('latest_change', ''),
                    'interval_change': parsed.get('interval_change', ''),
                    'interval_turnover': parsed.get('interval_turnover', ''),
                    'interval_amplitude': parsed.get('interval_amplitude', ''),
                    'listing_days': parsed.get('listing_days', '')
                }

        # 第三步：找到每只股票最近一次连续入选的起始日期
        # 注意：需要检查范围外的日期，如果与范围内日期连续，起始日应该是范围外的日期
        stocks_dict = {}  # {code: {name, entry_date, extra_data}}

        # 获取所有交易日（用于判断连续性，需要包含范围外的日期）
        # 为了判断连续性，需要获取更早的交易日
        extended_start_date_str = get_n_trading_days_before(today_str, days + 30)  # 多往前看30天
        if '-' in extended_start_date_str:
            extended_start_date_str = extended_start_date_str.replace('-', '')
        extended_trading_days = get_trading_days(extended_start_date_str, today_str)
        extended_trading_days_set = set(extended_trading_days)

        for pure_code, stock_info in stocks_appearances.items():
            # 筛选出在扩展时间范围内的日期（包含范围外的日期，用于判断连续性）
            dates_in_extended_range = [d for d in stock_info['dates'] if d in extended_trading_days_set]

            # 筛选出在指定时间范围内的日期（用于判断是否显示）
            dates_in_range = [d for d in dates_in_extended_range if d in trading_days_set]

            if not dates_in_range:
                continue  # 该股票在指定时间范围内未出现

            # 对日期排序（从早到晚）
            dates_in_extended_range.sort()

            # 找到最近一次连续入选的起始日期
            # 从最近往前找，找到第一个连续区间的起始日期
            entry_date = None
            entry_date_data = None

            # 从最近往前遍历，找到连续区间的起始
            # 找到最近一个在指定范围内的日期
            latest_date_in_range = max(dates_in_range)
            latest_date_idx = dates_in_extended_range.index(latest_date_in_range)

            # 从最近往前找连续日期
            i = latest_date_idx
            while i >= 0:
                current_date = dates_in_extended_range[i]
                # 往前找连续日期
                j = i
                while j > 0:
                    # 检查前一个日期是否在extended_trading_days中且连续
                    try:
                        prev_date = dates_in_extended_range[j - 1]
                        prev_date_idx_in_trading = extended_trading_days.index(prev_date)
                        current_date_idx_in_trading = extended_trading_days.index(dates_in_extended_range[j])
                        # 如果两个日期在trading_days中相邻（连续交易日），则属于同一段
                        if current_date_idx_in_trading - prev_date_idx_in_trading == 1:
                            j -= 1
                        else:
                            break
                    except ValueError:
                        # 如果日期不在extended_trading_days中，跳过
                        break

                # j 是连续区间的起始位置
                entry_date = dates_in_extended_range[j]
                # 使用起始日期的数据，如果起始日期不在范围内，使用范围内最早的数据
                if entry_date in stock_info['data_by_date']:
                    entry_date_data = stock_info['data_by_date'][entry_date]
                else:
                    # 如果起始日期没有数据，使用范围内最早日期的数据
                    earliest_date_in_range = min(dates_in_range)
                    entry_date_data = stock_info['data_by_date'][earliest_date_in_range]
                break  # 找到最近一段，退出

            if entry_date:
                stocks_dict[pure_code] = {
                    'code': stock_info['code'],
                    'name': stock_info['name'],
                    'entry_date': entry_date,
                    'extra_data': entry_date_data
                }

        # 第四步：筛选出在指定时间范围内出现的股票（不要求起始日期在范围内）
        filtered_stocks = []
        for pure_code, stock in stocks_dict.items():
            # 只要该股票在指定时间范围内出现过，就包含
            # 检查该股票是否在指定时间范围内出现过
            if pure_code in stocks_appearances:
                stock_dates_in_range = [d for d in stocks_appearances[pure_code]['dates']
                                        if d in trading_days_set]
                if stock_dates_in_range:
                    filtered_stocks.append(stock)

        # 按入选日期倒序排序（最近的在前）
        filtered_stocks.sort(key=lambda x: x['entry_date'], reverse=True)

        logging.info(f"加载【默默上涨】股票: 共 {len(filtered_stocks)} 只（去重后，真实入选日在最近{days}个交易日内）")
        return filtered_stocks

    except Exception as e:
        logging.error(f"加载【默默上涨】数据失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return []


def _create_single_chart_figure(
        stock_info: Dict,
        chart_df: pd.DataFrame,
        entry_date: str,
        before_days: int = 30,
        after_days: int = 10
) -> Optional[go.Figure]:
    """
    创建单个图表的Figure对象
    
    Args:
        stock_info: 股票信息字典
        chart_df: K线数据DataFrame
        entry_date: 入选日期 YYYYMMDD
        before_days: 入选日前显示的交易日数
        after_days: 入选日后显示的交易日数
        
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

        # 2. 添加入选日标记（蓝色向上三角）
        entry_date_dt = datetime.strptime(entry_date, '%Y%m%d')
        try:
            idx = chart_df.index.searchsorted(entry_date_dt, side='right') - 1
            if 0 <= idx < len(chart_df):
                entry_marker = go.Scatter(
                    x=[idx],
                    y=[chart_df.iloc[idx]['Low'] * 0.97],
                    mode='markers',
                    marker=dict(
                        symbol='triangle-up',
                        size=15,
                        color='blue',
                        line=dict(width=1, color='darkblue')
                    ),
                    name='入选日',
                    hovertemplate=f'入选日: {entry_date}<br>股票: {stock_info["name"]}<extra></extra>'
                )
                fig.add_trace(entry_marker, row=1, col=1)
        except:
            pass

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
        code_6digit = stock_info['code'].split('.')[0] if '.' in stock_info['code'] else stock_info['code']
        extra = stock_info.get('extra_data', {})
        title_parts = [f"{code_6digit} {stock_info['name']}"]

        # 添加区间涨跌幅（如果有）
        if extra.get('interval_change'):
            title_parts.append(f"区间涨跌幅: {extra['interval_change']}")

        title = "<br>".join(title_parts)

        # 5. 更新布局
        fig.update_layout(
            title=dict(
                text=title,
                x=0.05,
                xanchor='left',
                font=dict(size=12, color='black')
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
            margin=dict(l=50, r=50, t=80, b=50)
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
        logging.error(f"创建图表失败 {stock_info.get('code')} {stock_info.get('name')}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def generate_momo_html_charts(
        days: int = DEFAULT_DAYS,
        columns: int = 2,
        before_days: int = 30,
        after_days: int = 10,
        output_dir: str = './images/html_charts',
        data_dir: str = './data/astocks'
) -> Optional[str]:
    """
    生成【默默上涨】股票的HTML交互式图表
    
    Args:
        days: 最近N个交易日，默认20
        columns: 横向并排显示的列数（1、2或3），默认2
        before_days: 入选日前显示的交易日数，默认30
        after_days: 入选日后显示的交易日数，默认10
        output_dir: 输出目录
        data_dir: 股票数据目录
        
    Returns:
        str: 生成的HTML文件路径，失败返回None
    """

    if columns not in [1, 2, 3]:
        logging.warning(f"列数 {columns} 无效，使用默认值2")
        columns = 2

    # 加载股票数据
    stocks = load_momo_stocks_for_period(days)
    if not stocks:
        logging.warning("未找到【默默上涨】股票数据")
        return None

    logging.info(f"开始生成HTML图表，共 {len(stocks)} 只股票，布局: {columns}列...")

    # 收集所有图表的figure对象
    chart_figures = []
    chart_titles = []

    for stock_info in stocks:
        try:
            code_6digit = stock_info['code'].split('.')[0] if '.' in stock_info['code'] else stock_info['code']
            entry_date = stock_info['entry_date']

            # 计算绘图范围
            chart_start = get_n_trading_days_before(entry_date, before_days)
            chart_end_str = entry_date
            for _ in range(after_days):
                next_day = get_next_trading_day(chart_end_str)
                if next_day:
                    chart_end_str = next_day
                else:
                    break

            # 读取股票数据
            stock_data = read_stock_data(code_6digit, data_dir)
            if stock_data is None or stock_data.empty:
                logging.warning(f"未找到股票 {code_6digit} {stock_info['name']} 的数据文件")
                continue

            # 截取数据范围
            chart_start_dt = datetime.strptime(chart_start.replace('-', ''), '%Y%m%d')
            chart_end_dt = datetime.strptime(chart_end_str, '%Y%m%d')

            chart_df = stock_data.loc[chart_start_dt:chart_end_dt].copy()

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {stock_info['name']} 在指定日期范围内无数据")
                continue

            # 清理停牌数据
            chart_df = chart_df.dropna(subset=['Open', 'High', 'Low', 'Close'])

            if chart_df.empty:
                logging.warning(f"股票 {code_6digit} {stock_info['name']} 清理停牌数据后无有效数据")
                continue

            # 创建图表figure
            fig = _create_single_chart_figure(
                stock_info=stock_info,
                chart_df=chart_df,
                entry_date=entry_date,
                before_days=before_days,
                after_days=after_days
            )

            if fig is not None:
                chart_figures.append(fig)
                # 生成标题
                code_6digit = stock_info['code'].split('.')[0] if '.' in stock_info['code'] else stock_info['code']
                extra = stock_info.get('extra_data', {})
                title_parts = [f"{code_6digit} {stock_info['name']}"]
                if extra.get('interval_change'):
                    title_parts.append(f"区间涨跌幅: {extra['interval_change']}")
                chart_titles.append("<br>".join(title_parts))

        except Exception as e:
            logging.error(f"生成股票 {stock_info.get('code')} {stock_info.get('name')} 的HTML图表失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            continue

    if not chart_figures:
        logging.warning("没有可用的图表，跳过HTML生成")
        return None

    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 计算网格布局
    num_charts = len(chart_figures)
    rows = (num_charts + columns - 1) // columns

    # 创建包含所有图表的HTML
    html_content = _create_combined_html(chart_figures, chart_titles, columns, rows)

    # 保存HTML文件
    html_filename = f"momo_shangzhang_charts_{columns}cols.html"
    html_path = os.path.join(output_dir, html_filename)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logging.info(f"HTML图表生成完成，共 {num_charts} 个图表，保存在: {html_path}")

    return html_path


def _create_combined_html(figures: List[go.Figure], titles: List[str], columns: int, rows: int) -> str:
    """创建包含所有图表的单个HTML文件"""
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

    # 构建完整的HTML
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>【默默上涨】形态分析图表</title>
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
        <h1>【默默上涨】形态分析图表</h1>
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
        // 图表数据
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
