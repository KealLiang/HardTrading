import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter

def analyze_zt_reasons(excel_file='./excel/fupan_stocks.xlsx', date=None, top_n=20, output_format='normal', plot=False):
    """
    分析涨停原因类别，对数据进行聚合统计
    
    参数:
    excel_file: Excel文件路径
    date: 指定日期，格式为 "YYYY年MM月DD日"，为None时分析所有日期数据
    top_n: 显示前多少个最常见的原因类别
    output_format: 输出格式，可选 'normal'(默认), 'simple'(简洁), 'detailed'(详细)
    plot: 是否生成可视化图表
    
    返回:
    无，直接打印分析结果
    """
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 'SimHei'
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

    # 读取连板数据和首板数据
    lianban_data = pd.read_excel(excel_file, sheet_name="连板数据", index_col=0)
    shouban_data = pd.read_excel(excel_file, sheet_name="首板数据", index_col=0)
    
    # 选择要分析的日期列
    if date:
        if date in lianban_data.columns:
            lianban_dates = [date]
        else:
            print(f"错误: 未找到日期 {date}")
            return
    else:
        lianban_dates = lianban_data.columns
    
    # 统计所有类别
    all_reasons = Counter()
    daily_results = []
    
    # 处理连板数据
    for date in lianban_dates:
        # 提取当日连板数据
        lianban_col = lianban_data[date].dropna()
        lianban_stocks = lianban_col.str.split(';').apply(lambda x: [item.strip() for item in x])
        
        lianban_df = pd.DataFrame(lianban_stocks.tolist(), columns=[
            '股票代码', '股票简称', '涨停开板次数', '最终涨停时间',
            '几天几板', '最新价', '首次涨停时间', '最新涨跌幅',
            '连续涨停天数', '涨停原因类别'
        ])
        
        # 提取当日首板数据
        shouban_col = shouban_data[date].dropna()
        shouban_stocks = shouban_col.str.split(';').apply(lambda x: [item.strip() for item in x])
        
        # 首板数据可能有不同的列结构，这里假设最后一列是涨停原因类别
        shouban_df = pd.DataFrame(shouban_stocks.tolist())
        shouban_reasons_col = shouban_df.iloc[:, -1] if not shouban_df.empty else pd.Series([])
        
        # 分析连板数据中的涨停原因
        lianban_reasons = Counter()
        for reason_str in lianban_df['涨停原因类别']:
            if pd.notna(reason_str):
                # 拆分"+"连接的原因
                reasons = [r.strip() for r in reason_str.split('+')]
                for r in reasons:
                    if r:  # 确保不是空字符串
                        lianban_reasons[r] += 1
                        all_reasons[r] += 1
        
        # 分析首板数据中的涨停原因
        shouban_reasons = Counter()
        for reason_str in shouban_reasons_col:
            if pd.notna(reason_str):
                # 拆分"+"连接的原因
                reasons = [r.strip() for r in reason_str.split('+')]
                for r in reasons:
                    if r:  # 确保不是空字符串
                        shouban_reasons[r] += 1
                        all_reasons[r] += 1
        
        # 合并两种数据的统计结果
        day_reasons = lianban_reasons + shouban_reasons
        
        # 存储当日结果
        daily_results.append({
            'date': date,
            'total_stocks': len(lianban_df) + len(shouban_df),
            'lianban_count': len(lianban_df),
            'shouban_count': len(shouban_df),
            'reasons': day_reasons,
            'lianban_df': lianban_df,
            'shouban_df': shouban_df
        })
    
    # 根据输出格式打印结果
    if output_format == 'simple':
        # 简洁输出模式 - 只显示最近一天或指定日期的热点
        if daily_results:
            latest_day = daily_results[-1]
            print(f"\n📅 {latest_day['date']} 涨停热点 (Top {top_n}):")
            for reason, count in latest_day['reasons'].most_common(top_n):
                print(f"{reason}: {count}次")
            
            # 打印汇总信息
            print(f"\n📊 当日涨停: {latest_day['total_stocks']}只 (连板: {latest_day['lianban_count']}, 首板: {latest_day['shouban_count']})")
    
    elif output_format == 'detailed':
        # 详细输出模式 - 显示所有日期数据
        for day_data in daily_results:
            print(f"\n=== {day_data['date']} 涨停原因类别统计 ===")
            print(f">>> 当日涨停股票总数: {day_data['total_stocks']}")
            print(f">>> 连板股票数: {day_data['lianban_count']}, 首板股票数: {day_data['shouban_count']}")
            print("\n>>> 涨停原因类别统计 (按频率降序):")
            
            for reason, count in day_data['reasons'].most_common():
                print(f"{reason}: {count}次")
        
        # 打印所有日期统计结果（如果分析了多个日期）
        if len(daily_results) > 1:
            print("\n=== 所有日期涨停原因类别汇总 ===")
            print(f">>> 涨停原因类别总数: {len(all_reasons)}")
            print("\n>>> 涨停原因类别统计 (Top {top_n}):")
            
            for reason, count in all_reasons.most_common(top_n):
                print(f"{reason}: {count}次")
    
    else:  # 默认 normal 模式
        # 标准输出模式 - 显示基本信息
        for day_data in daily_results:
            print(f"\n=== {day_data['date']} 涨停热点 ===")
            print(f"📊 涨停: {day_data['total_stocks']}只 (连板: {day_data['lianban_count']}, 首板: {day_data['shouban_count']})")
            print("\n📈 热点类别 (Top {}):\n".format(top_n))
            
            for i, (reason, count) in enumerate(day_data['reasons'].most_common(top_n), 1):
                print(f"{i}. {reason}: {count}次")
        
        # 打印所有日期统计结果（如果分析了多个日期）
        if len(daily_results) > 1:
            print("\n=== 所有日期涨停原因类别汇总 (Top {}) ===".format(top_n))
            
            for i, (reason, count) in enumerate(all_reasons.most_common(top_n), 1):
                print(f"{i}. {reason}: {count}次")
    
    # 如果需要绘图
    if plot and daily_results:
        # 获取最新一天的数据进行可视化
        latest_day = daily_results[-1]
        plot_reason_distribution(latest_day['date'], latest_day['reasons'], top_n)
        
    # 返回分析结果，便于其他函数使用
    return daily_results


def plot_reason_distribution(date, reasons_counter, top_n=15):
    """
    绘制涨停原因分布图
    
    参数:
    date: 日期字符串
    reasons_counter: Counter对象，包含原因和频次
    top_n: 显示前多少个最常见的原因
    """
    # 获取前N个最常见的原因
    top_reasons = reasons_counter.most_common(top_n)
    
    # 提取原因和频次
    reasons = [reason for reason, _ in top_reasons]
    counts = [count for _, count in top_reasons]
    
    # 创建水平条形图
    plt.figure(figsize=(12, 8))
    
    # 绘制水平条形图
    bars = plt.barh(range(len(reasons)), counts, align='center', color='cornflowerblue')
    
    # 设置y轴标签
    plt.yticks(range(len(reasons)), reasons)
    
    # 添加数据标签
    for bar in bars:
        width = bar.get_width()
        plt.text(width + 0.3, bar.get_y() + bar.get_height()/2, 
                 f'{width:.0f}', ha='left', va='center')
    
    # 设置标题和标签
    plt.title(f'{date} 涨停原因类别分布 (Top {top_n})', fontsize=14)
    plt.xlabel('出现频次', fontsize=12)
    plt.ylabel('涨停原因', fontsize=12)
    plt.tight_layout()
    
    # 显示图表
    plt.show()
    # 可以选择保存图表
    # plt.savefig(f"zt_reasons_{date.replace('年', '').replace('月', '').replace('日', '')}.png", dpi=300, bbox_inches='tight')


def get_latest_date_data(excel_file):
    """
    获取Excel文件中最新的日期
    
    参数:
    excel_file: Excel文件路径
    
    返回:
    最新的日期字符串
    """
    try:
        lianban_data = pd.read_excel(excel_file, sheet_name="连板数据", index_col=0)
        latest_date = lianban_data.columns[-1]
        return latest_date
    except Exception as e:
        print(f"获取最新日期时出错: {e}")
        return None


def find_stocks_by_hot_themes(excel_file='./excel/fupan_stocks.xlsx', date=None, top_n=5):
    """
    根据热点类别找出覆盖多个热点的股票
    
    参数:
    excel_file: Excel文件路径
    date: 指定日期，格式为 "YYYY年MM月DD日"，None时使用最新日期
    top_n: 获取排名前几的热点类别
    
    返回:
    无，直接打印结果
    """
    # 如果没有指定日期，获取最新日期
    if date is None:
        date = get_latest_date_data(excel_file)
        if date is None:
            print("无法获取有效日期")
            return
    
    # 分析涨停数据
    daily_results = analyze_zt_reasons(excel_file, date, top_n=top_n, output_format='simple', plot=False)
    
    if not daily_results:
        print("未获取到有效数据")
        return
    
    # 获取当日数据
    day_data = daily_results[0]  # 因为我们传入的是单一日期，所以只有一个结果
    
    # 获取前N个热点类别（包括并列）
    hot_reasons = day_data['reasons'].most_common()
    
    # 找出频次排名前N的热点（包括并列）
    if not hot_reasons:
        print("未找到热点类别")
        return
    
    # 获取第N个热点的频次
    nth_count = hot_reasons[min(top_n-1, len(hot_reasons)-1)][1]
    
    # 找出所有频次≥第N个热点频次的热点（即包括并列的情况）
    top_hot_reasons = [(reason, count) for reason, count in hot_reasons if count >= nth_count]
    
    print(f"\n🔥 {date} 热点类别 Top {len(top_hot_reasons)}:")
    for i, (reason, count) in enumerate(top_hot_reasons, 1):
        print(f"{i}. {reason}: {count}次")
    
    # 获取连板和首板数据
    lianban_df = day_data['lianban_df']
    shouban_df = day_data['shouban_df']
    
    # 合并两个DataFrame
    if shouban_df.empty:
        all_stocks_df = lianban_df.copy()
    else:
        # 确保首板DataFrame的列与连板DataFrame匹配
        # 假设首板数据的顺序与连板数据相同，但可能缺少某些列
        shouban_df_adjusted = pd.DataFrame()
        
        # 复制连板数据的列结构
        for col in lianban_df.columns:
            if col in shouban_df.columns:
                shouban_df_adjusted[col] = shouban_df[col]
            else:
                # 如果首板数据缺少某列，用空值填充
                shouban_df_adjusted[col] = pd.NA
        
        # 合并数据
        all_stocks_df = pd.concat([lianban_df, shouban_df_adjusted], ignore_index=True)
    
    # 计算每只股票的热点覆盖得分
    stock_scores = []
    
    for _, stock_row in all_stocks_df.iterrows():
        # 提取股票信息
        stock_code = stock_row['股票代码']
        stock_name = stock_row['股票简称']
        stock_board = stock_row['几天几板'] if pd.notna(stock_row['几天几板']) else ''
        stock_reasons_str = stock_row['涨停原因类别'] if pd.notna(stock_row['涨停原因类别']) else ''
        
        # 拆分股票的涨停原因
        stock_reasons = [r.strip() for r in stock_reasons_str.split('+')] if stock_reasons_str else []
        
        # 计算得分：覆盖的热点越靠前，分值越高
        score = 0
        covered_hot_reasons = []
        
        for hot_reason_idx, (hot_reason, _) in enumerate(top_hot_reasons):
            weight = len(top_hot_reasons) - hot_reason_idx  # 排名靠前的热点权重更高
            
            if any(hot_reason in r for r in stock_reasons):
                score += weight
                covered_hot_reasons.append(hot_reason)
        
        # 记录股票得分和覆盖的热点
        if score > 0:  # 只关注有覆盖热点的股票
            stock_scores.append({
                '股票代码': stock_code,
                '股票简称': stock_name,
                '几天几板': stock_board,
                '涨停原因类别': stock_reasons_str,
                '覆盖热点': covered_hot_reasons,
                '热点数量': len(covered_hot_reasons),
                '得分': score
            })
    
    # 根据得分对股票排序
    stock_scores.sort(key=lambda x: (x['得分'], x['热点数量']), reverse=True)
    
    # 输出结果
    print("\n🏆 覆盖热点最多的股票:")
    for i, stock in enumerate(stock_scores[:15], 1):  # 只显示前15只
        covered_hot_str = ', '.join(stock['覆盖热点'])
        print(f"{i}. {stock['股票代码']} {stock['股票简称']} | {stock['几天几板']} | 覆盖热点: {covered_hot_str}")
        print(f"   原始涨停原因: {stock['涨停原因类别']}")
        print()
    
    return stock_scores


if __name__ == '__main__':
    # 文件路径
    excel_file = "E:/demo/MachineLearning/HardTrading/excel/fupan_stocks.xlsx"
    
    # 获取最新日期
    latest_date = get_latest_date_data(excel_file)
    
    # 找出覆盖热点最多的股票
    find_stocks_by_hot_themes(excel_file, date="2025年04月25日", top_n=5)
    
    # 其他使用示例:
    # 分析最新一天的数据，使用简洁模式，显示前15个热点
    # analyze_zt_reasons(excel_file, latest_date, top_n=15, output_format='simple', plot=True)
    
    # 2. 分析指定日期数据，使用标准模式，并生成图表
    # analyze_zt_reasons(excel_file, date="2025年04月25日", output_format='normal', plot=True)
    
    # 3. 分析所有日期数据，使用标准模式，显示前10个热点
    # analyze_zt_reasons(excel_file, date=None, top_n=10)
