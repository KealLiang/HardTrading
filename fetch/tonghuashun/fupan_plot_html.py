"""
HTML交互式复盘图生成器 - 使用Plotly

优势：
1. 鼠标悬停显示详细信息，完全解决标签重叠问题
2. 支持缩放、平移、保存图片
3. 可添加更多交互功能
4. 生成单个HTML文件，方便分享
"""

import os
import re
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 导入工具函数
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from utils.stock_util import stock_limit_ratio

# 配置悬浮窗换行阈值
LIANBAN_STOCKS_PER_LINE = 5  # 连板天梯图层：每5只股票换行
MOMO_STOCKS_PER_LINE = 3  # 默默上涨图层：每3只股票换行


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


# ========== 工具函数：避免重复代码 ==========

def _inject_click_copy_script(html_path, momo_trace_index):
    """
    向HTML文件注入JavaScript代码，实现点击【默默上涨】节点复制股票代码功能
    
    Args:
        html_path: HTML文件路径
        momo_trace_index: 默默上涨trace在图表中的索引
    """
    # 读取HTML文件
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 准备JavaScript代码
    js_code = f"""
<script>
// 点击复制股票代码功能
(function() {{
    const momoTraceIndex = {momo_trace_index};  // 默默上涨trace的索引
    const plotDiv = document.querySelector('.plotly-graph-div');
    
    if (!plotDiv) {{
        console.error('未找到Plotly图表元素');
        return;
    }}
    
    // 监听点击事件
    plotDiv.on('plotly_click', function(data) {{
        // 检查是否点击的是默默上涨trace
        if (data.points && data.points.length > 0) {{
            const point = data.points[0];
            
            // 判断是否点击的是默默上涨图层
            if (point.curveNumber === momoTraceIndex) {{
                // 获取股票代码字符串（customdata[1]）
                const stockCodes = point.customdata[1];
                
                if (stockCodes && stockCodes.trim() !== '') {{
                    // 复制到剪贴板
                    copyToClipboard(stockCodes);
                    
                    // 显示提示信息
                    showCopyNotification(point.x, '已复制 ' + stockCodes.split('\\n').length + ' 只股票代码！');
                }} else {{
                    showCopyNotification(point.x, '该日期无股票代码');
                }}
            }}
        }}
    }});
    
    // 复制到剪贴板函数
    function copyToClipboard(text) {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            // 现代浏览器
            navigator.clipboard.writeText(text).then(function() {{
                console.log('复制成功');
            }}).catch(function(err) {{
                console.error('复制失败:', err);
                fallbackCopy(text);
            }});
        }} else {{
            // 兼容旧浏览器
            fallbackCopy(text);
        }}
    }}
    
    // 兼容旧浏览器的复制方法
    function fallbackCopy(text) {{
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {{
            document.execCommand('copy');
            console.log('复制成功（兼容模式）');
        }} catch (err) {{
            console.error('复制失败（兼容模式）:', err);
        }}
        document.body.removeChild(textarea);
    }}
    
    // 显示复制成功提示
    function showCopyNotification(date, message) {{
        // 创建提示元素
        const notification = document.createElement('div');
        notification.textContent = message;
        notification.style.position = 'fixed';
        notification.style.top = '20px';
        notification.style.left = '50%';
        notification.style.transform = 'translateX(-50%)';
        notification.style.backgroundColor = 'rgba(76, 175, 80, 0.95)';
        notification.style.color = 'white';
        notification.style.padding = '12px 24px';
        notification.style.borderRadius = '6px';
        notification.style.fontSize = '14px';
        notification.style.fontWeight = 'bold';
        notification.style.zIndex = '10000';
        notification.style.boxShadow = '0 4px 12px rgba(0,0,0,0.3)';
        notification.style.fontFamily = 'SimHei, Arial, sans-serif';
        
        document.body.appendChild(notification);
        
        // 2秒后自动消失
        setTimeout(function() {{
            notification.style.transition = 'opacity 0.5s';
            notification.style.opacity = '0';
            setTimeout(function() {{
                document.body.removeChild(notification);
            }}, 500);
        }}, 2000);
    }}
}})();
</script>
"""
    
    # 在</body>之前插入JavaScript代码
    html_content = html_content.replace('</body>', js_code + '\n</body>')
    
    # 写回HTML文件
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print("✅ 已注入点击复制功能")


def format_stock_list_for_hover(stock_list, stocks_per_line=5):
    """
    格式化股票列表用于悬浮窗显示（每N只换一行）
    
    Args:
        stock_list: 股票列表
        stocks_per_line: 每行显示的股票数，默认5
        
    Returns:
        格式化后的字符串，用<br>分隔
    """
    if len(stock_list) > stocks_per_line:
        stock_lines = [', '.join(stock_list[i:i + stocks_per_line]) for i in range(0, len(stock_list), stocks_per_line)]
        return '<br>'.join(stock_lines)
    else:
        return ', '.join(stock_list)


def create_display_labels(stock_list, max_display=3):
    """
    创建图表上显示的标签（超过max_display个时添加省略号）
    
    Args:
        stock_list: 股票列表
        max_display: 最大显示数量，默认3
        
    Returns:
        格式化后的标签文本
    """
    if len(stock_list) > max_display:
        return '<br>'.join(stock_list[:max_display]) + '<br>……'
    else:
        return '<br>'.join(stock_list) if stock_list else ''


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
        second_lianban = lianban_df[lianban_df['连续涨停天数'] < max_lianban][
            '连续涨停天数'].max() if not lianban_df.empty and max_lianban > 0 else 0
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
            dieting_df['连续跌停天数'] = pd.to_numeric(dieting_df['连续跌停天数'], errors='coerce').fillna(0).astype(
                int)

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
            momo_stocks_data = []  # 完整信息（涨幅+成交额）用于悬浮窗
            momo_stocks_simple = []  # 简化信息（仅涨幅）用于节点标签
            momo_stock_codes = []  # 股票代码列表，用于点击复制
            momo_zhangfus = []

            for cell in momo_col:
                if pd.isna(cell) or str(cell).strip() == '':
                    continue
                parts = str(cell).split(';')
                if len(parts) >= 6:
                    # 格式：股票代码; 股票简称; 最新价; 最新涨跌幅; 区间涨跌幅; 区间成交额; 区间振幅; 上市交易日天数
                    stock_code = parts[0].strip()
                    stock_name = parts[1].strip()
                    qujian_zhangfu = parts[4].strip()  # 区间涨跌幅（第5个字段）
                    qujian_chengjiao = parts[5].strip() if len(parts) > 5 else ''  # 区间成交额（第6个字段）

                    try:
                        # 去掉百分号，转换为浮点数
                        zhangfu_value = float(qujian_zhangfu.rstrip('%'))
                        momo_zhangfus.append(zhangfu_value)
                        # 提取股票代码（去掉交易所后缀，如 .SH .SZ）
                        clean_code = stock_code.split('.')[0] if '.' in stock_code else stock_code
                        momo_stock_codes.append(clean_code)
                        # 完整信息：股票名称(涨幅, 成交额) - 用于悬浮窗
                        momo_stocks_data.append(f"{stock_name}({qujian_zhangfu}, {qujian_chengjiao})")
                        # 简化信息：股票名称(涨幅) - 用于节点标签
                        momo_stocks_simple.append(f"{stock_name}({qujian_zhangfu})")
                    except:
                        pass

            # 计算平均涨幅或最大涨幅
            if momo_zhangfus:
                avg_zhangfu = sum(momo_zhangfus) / len(momo_zhangfus)
                max_zhangfu = max(momo_zhangfus)
                sample_count = len(momo_zhangfus)  # 样本数量
                # 找出涨幅最高的前3只股票（用简化信息）
                top_3_indices = sorted(range(len(momo_zhangfus)), key=lambda i: momo_zhangfus[i], reverse=True)[:3]
                top_3_stocks = [momo_stocks_simple[i] for i in top_3_indices if i < len(momo_stocks_simple)]
                # 将股票代码列表转换为换行符分隔的字符串（便于复制）
                codes_str = '\n'.join(momo_stock_codes)
                # 添加样本数量和股票代码到结果中
                momo_results.append((date, avg_zhangfu, momo_stocks_data, top_3_stocks, sample_count, codes_str))
            else:
                # 没有数据时用None，不影响Y轴范围
                momo_results.append((date, None, [], [], 0, ''))
        elif has_momo_data:
            # 该日期没有默默上涨数据，用None
            momo_results.append((date, None, [], [], 0, ''))

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

    # 最高几板线（副Y轴）- 调整到连板之前
    max_ji_ban_days = [item[1] for item in max_ji_ban_results]
    max_ji_ban_stocks = [format_stock_list_for_hover(item[2], LIANBAN_STOCKS_PER_LINE) for item in max_ji_ban_results]
    max_ji_ban_labels = [create_display_labels(item[2]) for item in max_ji_ban_results]

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
            hovertemplate='几板: %{y}板<br>股票: %{customdata}<extra></extra>',
        ),
        secondary_y=True,
    )

    # 最高连板线（副Y轴）
    lianban_days = [item[1] for item in lianban_results]
    lianban_stocks = [format_stock_list_for_hover(item[2], LIANBAN_STOCKS_PER_LINE) for item in lianban_results]
    lianban_labels = [create_display_labels(item[2]) for item in lianban_results]

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
    lianban_second_stocks = [format_stock_list_for_hover(item[2], LIANBAN_STOCKS_PER_LINE) for item in
                             lianban_second_results]
    lianban_second_labels = [create_display_labels(item[2]) for item in lianban_second_results]

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
    dieting_stocks = [format_stock_list_for_hover(item[2], LIANBAN_STOCKS_PER_LINE) for item in dieting_results]
    dieting_labels = [create_display_labels(item[2]) for item in dieting_results]

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

    # 默默上涨线（独立Y轴）- 显示平均涨幅
    momo_trace_index = None
    momo_annotations = []  # 用于存储样本数量的annotations
    if has_momo_data and momo_results:
        momo_zhangfus = [item[1] for item in momo_results]  # 平均涨幅
        # 悬浮窗显示所有股票（包含成交额），每3只换行
        momo_all_stocks = [format_stock_list_for_hover(item[2], MOMO_STOCKS_PER_LINE) for item in momo_results]
        # 提取股票代码字符串（用于点击复制）
        momo_stock_codes = [item[5] for item in momo_results]  # item[5] 是代码字符串

        # 记录默默上涨trace的索引（当前是最后一个）
        momo_trace_index = len(fig.data)

        # 创建标签：显示前3只涨幅最高的股票（注意：是item[3]而不是item[2]）
        momo_labels = []
        for item in momo_results:
            if item[1] is None:  # 没有数据
                momo_labels.append('')
            else:
                momo_labels.append(create_display_labels(item[3]))

        # 创建样本数量的annotations（显示在节点下方）
        for i, item in enumerate(momo_results):
            if item[1] is not None:  # 有数据时才显示
                sample_count = item[4]  # 样本数量
                momo_annotations.append(
                    dict(
                        x=date_labels[i],
                        y=item[1],  # Y坐标为平均涨幅
                        xref='x',
                        yref='y3',  # 使用y3轴
                        text=f'{sample_count}只',
                        showarrow=False,
                        font=dict(size=8, color='brown'),
                        xanchor='center',
                        yanchor='top',
                        yshift=-10,  # 向下偏移10像素
                        visible=False,  # 默认隐藏（跟随图层切换）
                    )
                )

        # 准备 customdata（二维数组：[股票列表用于hover, 股票代码用于复制]）
        momo_customdata = [[stocks, codes] for stocks, codes in zip(momo_all_stocks, momo_stock_codes)]

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
                customdata=momo_customdata,
                # 独立悬浮窗，去掉日期（顶部已有），添加点击提示
                hovertemplate='平均涨幅: %{y:.1f}%<br>股票: %{customdata[0]}<br><i>💡 点击节点复制股票代码</i><extra></extra>',
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
        # 为每个annotation设置visible属性（跟随图层切换）
        annotations_count = len(momo_annotations)

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
                                # 隐藏所有样本数量annotations
                                "annotations": [dict(ann, visible=False) for ann in momo_annotations],
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
                                # 显示所有样本数量annotations
                                "annotations": [dict(ann, visible=True) for ann in momo_annotations],
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
        annotations=momo_annotations,  # 添加样本数量标注（默认隐藏）
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
            side='right',  # 显示在右侧
            # 不设置position，让它自然靠近图表右侧
            showgrid=True,  # 显示网格线
            gridwidth=1,
            gridcolor='lightgray',
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor='gray',
            tickfont=dict(color='brown', size=10),
            tickformat='.1f',
            ticksuffix='%',
            visible=False,  # 默认隐藏（连板天梯图层不显示）
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

    # 注入JavaScript实现点击复制股票代码功能
    if has_momo_data and momo_trace_index is not None:
        _inject_click_copy_script(output_path, momo_trace_index)

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
