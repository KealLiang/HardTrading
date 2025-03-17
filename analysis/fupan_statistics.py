import concurrent.futures  # 添加多线程支持
import logging
import os
from datetime import datetime

import akshare as ak
import pandas as pd
import tushare as ts

from threading import Lock
from decorators.practical import timer
from fetch.tonghuashun.fupan import get_open_dieting_stocks, get_zt_stocks, get_zaban_stocks, get_lianban_stocks, \
    get_dieting_stocks
from utils.date_util import get_next_trading_day, get_prev_trading_day, get_trading_days

os.environ['NODE_OPTIONS'] = '--no-deprecation'
default_analysis_type = ['涨停', '连板', '开盘跌停', '跌停', '炸板', '曾涨停']


def init_tushare():
    """
    初始化 Tushare SDK
    Returns:
        tushare.Pro: Tushare Pro API 实例
    """
    try:
        # config = configparser.ConfigParser()
        # config.read('config.ini')  # 读取配置文件
        # ts.set_token(config['API']['tushare_token'])
        ts.set_token('823b48b8fbb6f051271f07ebd1180209a077532aa14eae61cc89fcd9')
        return ts.pro_api()
    except Exception as e:
        print(f"初始化 Tushare 失败: {str(e)}")
        return None


def get_tushare_dapan_statistics(pro, target_date):
    """
    获取某日 A股大盘 的统计数据
    Args:
        pro: Tushare Pro API 实例
        target_date: 指定日期，格式为 'YYYYMMDD'
    Returns:
        dict: 包含统计数据的字典
    """
    try:
        # 获取某日股票数据
        data = pro.daily(trade_date=target_date)

        # 计算涨跌家数
        up_count = len(data[data['pct_chg'] > 0])  # 上涨家数
        down_count = len(data[data['pct_chg'] < 0])  # 下跌家数
        flat_count = len(data[data['pct_chg'] == 0])  # 平盘家数

        # 计算涨跌幅超过 5% 的数量
        up_over_5 = len(data[data['pct_chg'] >= 5])
        down_over_5 = len(data[data['pct_chg'] <= -5])
        # 计算涨跌幅超过 7% 的数量
        up_over_7 = len(data[data['pct_chg'] >= 7])
        down_over_7 = len(data[data['pct_chg'] <= -7])

        # 返回统计数据
        return {
            '日期': target_date,
            '上涨家数': up_count,
            '下跌家数': down_count,
            '平盘家数': flat_count,
            '涨幅超过5%家数': up_over_5,
            '跌幅超过5%家数': down_over_5,
            '涨幅超过7%家数': up_over_7,
            '跌幅超过7%家数': down_over_7
        }

    except Exception as e:
        print(f"获取 {target_date} 数据时出错: {e}")
        return None


def get_multiple_dates_statistics(pro, start_date, end_date):
    """
    获取指定日期范围内的 A 股统计数据
    Args:
        pro: Tushare Pro API 实例
        start_date: 开始日期，格式为 'YYYYMMDD'
        end_date: 结束日期，格式为 'YYYYMMDD'
    Returns:
        pd.DataFrame: 包含统计数据的 DataFrame
    """
    trading_days = get_trading_days(start_date, end_date)
    statistics_list = []

    for date in trading_days:
        statistics = get_tushare_dapan_statistics(pro, date)
        if statistics:
            statistics_list.append(statistics)

    return pd.DataFrame(statistics_list)


def fetch_statistics():
    # 初始化 Tushare
    pro = init_tushare()
    if pro is None:
        return

    # 示例调用
    start_date = '20241230'
    end_date = '20250110'
    statistics_df = get_multiple_dates_statistics(pro, start_date, end_date)
    # 打印结果
    print(statistics_df)


def get_stock_next_day_performance(pre_df, base_date):
    """
    获取股票列表在下一个交易日的表现
    Args:
        pre_df: 涨停股DataFrame，包含股票代码信息
        base_date: 基准日期，格式为 'YYYYMMDD'
    Returns:
        dict: 包含每只股票次日表现的字典
    """
    try:
        next_date = get_next_trading_day(base_date)
        # 使用线程安全的字典
        result_lock = Lock()
        result = {}

        for _, row in pre_df.iterrows():
            try:
                stock_code = row['股票代码'].split('.')[0]
                stock_name = row.get('股票简称', '')
                
                logging.debug(f"开始处理股票: {stock_code} ({stock_name})")

                # 尝试从本地文件读取数据
                local_data = get_local_data(base_date, next_date, stock_code, stock_name)

                # 如果本地数据获取成功，使用本地数据；否则通过API获取
                stock_data = get_stock_data(base_date, next_date, stock_code, local_data)

                if stock_data is not None and not stock_data.empty and len(stock_data) >= 2:
                    # 正确访问DataFrame的数据
                    prev_data = stock_data.iloc[0]
                    base_price = float(prev_data['close'])
                    base_open_price = float(prev_data['open'])
                    base_high_price = float(prev_data['high'])
                    next_data = stock_data.iloc[1]
                    today_base = float(next_data['open'])

                    # 计算涨跌幅
                    close_open_profit = (float(next_data['open']) - base_price) / base_price * 100
                    close_close_profit = (float(next_data['close']) - base_price) / base_price * 100
                    close_high_profit = (float(next_data['high']) - base_price) / base_price * 100
                    close_low_profit = (float(next_data['low']) - base_price) / base_price * 100
                    today_change = (float(next_data['close']) - today_base) / today_base * 100
                    open_open_porfit = (float(next_data['open']) - base_open_price) / base_open_price * 100
                    open_close_porfit = (float(next_data['close']) - base_open_price) / base_open_price * 100
                    high_open_porfit = (float(next_data['open']) - base_high_price) / base_high_price * 100
                    high_close_porfit = (float(next_data['close']) - base_high_price) / base_high_price * 100

                    # 使用锁保护共享资源的写入
                    with result_lock:
                        result[stock_code] = {
                            't+1收入开盘盈利': round(close_open_profit, 2),
                            't+1收入收盘盈利': round(close_close_profit, 2),
                            't+1收入高价盈利': round(close_high_profit, 2),
                            't+1收入低价盈利': round(close_low_profit, 2),
                            't+1实体涨跌幅': round(today_change, 2),
                            't+1开入开盘盈利': round(open_open_porfit, 2),
                            't+1开入收盘盈利': round(open_close_porfit, 2),
                            't+1高入开盘盈利': round(high_open_porfit, 2),
                            't+1高入收盘盈利': round(high_close_porfit, 2)
                        }
                else:
                    logging.warning(f"未获取到股票 {stock_code} 的完整数据")

            except Exception as e:
                logging.error(f"处理股票 {stock_code} 时出错: {str(e)}")
                continue

        return result
    except Exception as e:
        logging.error(f"获取次日表现数据失败: {str(e)}")
        return None


def get_stock_data(base_date, next_date, stock_code, local_data):
    if local_data is not None and len(local_data) >= 2:
        stock_data = local_data
        # 转换列名以匹配后续处理
        stock_data = stock_data.rename(columns={
            '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low'
        })
    else:
        logging.info(f"从本地读取[{stock_code}]数据失败，从API获取")
        # 处理股票代码格式
        if stock_code.startswith('6'):
            formatted_code = f"sh{stock_code}"
        else:
            formatted_code = f"sz{stock_code}"

        # 通过API获取数据
        stock_data = ak.stock_zh_a_daily(symbol=formatted_code,
                                         start_date=base_date,
                                         end_date=next_date)
    return stock_data


def get_local_data(base_date, next_date, stock_code, stock_name, data_path='data/astocks'):
    local_data = None
    try:
        # 确保使用绝对路径
        abs_data_path = os.path.abspath(data_path)
        if not os.path.exists(abs_data_path):
            logging.warning(f"数据路径不存在: {abs_data_path}")
            return None
            
        # 查找所有匹配股票代码的文件
        try:
            matching_files = [f for f in os.listdir(abs_data_path) if f.startswith(f"{stock_code}_")]
        except Exception as e:
            logging.error(f"列出目录内容失败: {str(e)}")
            return None

        if len(matching_files) == 1:
            # 只找到一个文件，直接使用
            file_path = os.path.join(abs_data_path, matching_files[0])
        elif len(matching_files) > 1 and stock_name:
            # 找到多个文件，使用股票名称进一步筛选
            processed_stock_name = ''.join(stock_name.split())
            name_matched_files = [f for f in matching_files
                                  if processed_stock_name in ''.join(f.split('_')[1].split('.')[0].split())]
            if name_matched_files:
                file_path = os.path.join(abs_data_path, name_matched_files[0])
            else:
                # 如果没有匹配的，使用第一个文件
                file_path = os.path.join(abs_data_path, matching_files[0])
                logging.warning(f"股票{stock_code}({stock_name})存在多个数据文件，使用: {matching_files[0]}")
        else:
            logging.warning(f"未找到股票{stock_code}的数据文件")
            return None

        # 使用文件锁确保线程安全的文件读取
        with open(file_path, 'r') as f:
            # 读取本地数据
            local_df = pd.read_csv(file_path, header=None,
                                names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅',
                                        '涨跌幅', '涨跌额', '换手率'],
                                dtype={'日期': str})

            # 转换日期格式 YYYYMMDD -> YYYY-MM-DD
            base_date_formatted = f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}"
            next_date_formatted = f"{next_date[:4]}-{next_date[4:6]}-{next_date[6:]}"

            # 筛选出基准日和次日的数据
            filtered_df = local_df[local_df['日期'].isin([base_date_formatted, next_date_formatted])]

            if len(filtered_df) >= 2:
                # 创建数据副本，避免多线程共享同一个DataFrame
                local_data = filtered_df.sort_values(by='日期').reset_index(drop=True).copy()
                logging.debug(f"成功从本地读取股票 {stock_code} 的数据")
            else:
                logging.warning(f"本地文件中未找到股票 {stock_code} 的完整数据 base[{base_date}]-next[{next_date}]")
    except Exception as e:
        logging.error(f"从本地读取股票 {stock_code} 数据失败: {str(e)}")
    
    return local_data


def merge_zt_and_zaban_stocks(date):
    """
    合并涨停和炸板的股票数据
    Args:
        date: 日期，格式为 'YYYYMMDD'
    Returns:
        pd.DataFrame: 合并后的DataFrame
    """
    try:
        # 获取涨停和炸板数据
        zt_df = get_zt_stocks(date)
        zb_df = get_zaban_stocks(date)

        if zt_df is None or zb_df is None:
            return None

        # 获取两个DataFrame的共同列
        common_columns = list(set(zt_df.columns) & set(zb_df.columns))

        # 使用共同列合并数据
        zt_df = zt_df[common_columns]
        zb_df = zb_df[common_columns]

        # 合并并去重
        merged_df = pd.concat([zt_df, zb_df]).drop_duplicates(subset=['股票代码'])

        return merged_df
    except Exception as e:
        print(f"合并数据时出错: {str(e)}")
        return None


def analyze_zt_stocks_performance(date, analysis_type='涨停'):
    """
    分析指定日期涨停股在次日的表现
    Args:
        date: 日期，格式为 'YYYYMMDD'
        analysis_type: 分析类型，'涨停' 或 '曾涨停' 或 '连板'
    Returns:
        dict: 包含统计信息的字典
    """
    try:
        # 根据分析类型获取不同的数据
        if analysis_type == '涨停':
            stock_df = get_zt_stocks(date)
        elif analysis_type == '连板':
            stock_df = get_lianban_stocks(date)
        elif analysis_type == '开盘跌停':
            stock_df = get_open_dieting_stocks(date)
        elif analysis_type == '跌停':
            stock_df = get_dieting_stocks(date)
        elif analysis_type == '炸板':
            stock_df = get_zaban_stocks(date)
        else:  # '曾涨停'
            stock_df = merge_zt_and_zaban_stocks(date)

        if stock_df is None or stock_df.empty:
            print(f"未获取到 {date} 的{analysis_type}股票数据")
            return None

        # 获取次日表现数据，直接传入整个DataFrame
        performance = get_stock_next_day_performance(stock_df, date)
        if not performance:
            return None

        # 统计数据
        close_open_profit = [data['t+1收入开盘盈利'] for data in performance.values()]
        close_close_profit = [data['t+1收入收盘盈利'] for data in performance.values()]
        close_high_profit = [data['t+1收入高价盈利'] for data in performance.values()]
        close_low_profit = [data['t+1收入低价盈利'] for data in performance.values()]
        today_changes = [data['t+1实体涨跌幅'] for data in performance.values()]
        open_open_profit = [data['t+1开入开盘盈利'] for data in performance.values()]
        open_close_profit = [data['t+1开入收盘盈利'] for data in performance.values()]
        high_open_profit = [data['t+1高入开盘盈利'] for data in performance.values()]
        high_close_profit = [data['t+1高入收盘盈利'] for data in performance.values()]

        # 计算统计指标
        stats = {
            '分析类型': analysis_type,
            '样本数量': len(performance),
            '次日收入开盘': round(sum(close_open_profit) / len(close_open_profit), 2),
            '次日收入收盘': round(sum(close_close_profit) / len(close_close_profit), 2),
            '次日收入高价': round(sum(close_high_profit) / len(close_high_profit), 2),
            '次日收入低价': round(sum(close_low_profit) / len(close_low_profit), 2),
            '次日实体': round(sum(today_changes) / len(today_changes), 2),
            '次日开入开盘': round(sum(open_open_profit) / len(open_open_profit), 2),
            '次日开入收盘': round(sum(open_close_profit) / len(open_close_profit), 2),
            '次日高入开盘': round(sum(high_open_profit) / len(high_open_profit), 2),
            '次日高入收盘': round(sum(high_close_profit) / len(high_close_profit), 2),
            '次日收入开盘涨比': round(len([x for x in close_open_profit if x > 0]) / len(close_open_profit) * 100, 2),
            '次日收入收盘涨比': round(len([x for x in close_close_profit if x > 0]) / len(close_close_profit) * 100, 2),
            '次日实体上涨比例': round(len([x for x in today_changes if x > 0]) / len(today_changes) * 100, 2),
            '次日开入开盘涨比': round(len([x for x in open_open_profit if x > 0]) / len(open_open_profit) * 100, 2),
            '次日开入收盘涨比': round(len([x for x in open_close_profit if x > 0]) / len(open_close_profit) * 100, 2),
            '次日高入开盘涨比': round(len([x for x in high_open_profit if x > 0]) / len(high_open_profit) * 100, 2),
            '次日高入收盘涨比': round(len([x for x in high_close_profit if x > 0]) / len(high_close_profit) * 100, 2),
            '详细数据': performance
        }

        return stats
    except Exception as e:
        print(f"分析{analysis_type}股票表现时出错: {str(e)}")
        return None


def zt_analysis(start_date=None, end_date=None, max_workers=5):
    """
    分析指定时间段内涨停股、连板股和曾涨停股的表现
    Args:
        start_date: 开始日期，格式为 'YYYYMMDD'，如果为None则使用当天
        end_date: 结束日期，格式为 'YYYYMMDD'，如果为None则使用当天
        max_workers: 最大线程数
    Returns:
        dict: 按日期存储的分析结果
    """
    if start_date is None:
        start_date = datetime.now().strftime('%Y%m%d')
    if end_date is None:
        end_date = start_date

    # 获取交易日列表
    trading_days = get_trading_days(start_date, end_date)

    # 用于存储每日的分析结果
    daily_results = {}

    # 创建任务列表
    tasks = []
    for date in trading_days:
        for analysis_type in default_analysis_type:
            tasks.append((date, analysis_type))

    # 使用线程池并行处理任务
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(analyze_zt_stocks_performance, date, analysis_type): (date, analysis_type)
            for date, analysis_type in tasks
        }

        # 处理完成的任务
        for future in concurrent.futures.as_completed(future_to_task):
            date, analysis_type = future_to_task[future]
            try:
                stats = future.result()
                if stats:
                    # 初始化日期字典（如果不存在）
                    if date not in daily_results:
                        daily_results[date] = {}

                    # 存储分析结果
                    daily_results[date][analysis_type] = stats

                    # 打印当日结果
                    print(f"\n{date} {analysis_type}股票次日表现:")
                    print(f"样本数量: {stats['样本数量']}只")
                    print(f"次日开入开盘涨比: {stats['次日开入开盘涨比']}%")
                    print(f"次日开入收盘涨比: {stats['次日开入收盘涨比']}%")
                    print(f"次日收入收盘涨比: {stats['次日收入收盘涨比']}%")
                    print(f"次日高入收盘涨比: {stats['次日高入收盘涨比']}%")
            except Exception as e:
                print(f"处理 {date} 的 {analysis_type} 分析时出错: {str(e)}")

    return daily_results


def merge_and_save_analysis(dapan_stats, zt_stats, excel_path='./excel/market_analysis.xlsx'):
    """
    合并大盘数据和涨停分析数据，并保存到Excel
    Args:
        dapan_stats: DataFrame, 大盘统计数据
        zt_stats: dict, 涨停分析数据
        excel_path: str, Excel文件路径
    """
    try:
        # 读取现有的Excel文件（如果存在）
        try:
            existing_df = pd.read_excel(excel_path)
        except FileNotFoundError:
            existing_df = pd.DataFrame()

        # 准备新数据
        new_records = []
        for _, row in dapan_stats.iterrows():
            date = row['日期']
            # 创建基础记录（大盘数据）
            record = row.to_dict()

            # 添加涨停分析数据
            if date in zt_stats:
                # 获取涨停数据
                zt_df = get_zt_stocks(date)
                zt_count = len(zt_df) if zt_df is not None else 0
                record['涨停数'] = zt_count

                # 获取跌停数据
                dt_df = get_dieting_stocks(date)
                dt_count = len(dt_df) if dt_df is not None else 0
                record['跌停数'] = dt_count

                # 获取连板数据
                lb_df = get_lianban_stocks(date)
                lb_count = len(lb_df) if lb_df is not None else 0
                record['连板数'] = lb_count

                # 获取炸板数据
                zb_df = get_zaban_stocks(date)
                zb_count = len(zb_df) if zb_df is not None else 0
                record['炸板数'] = zb_count

                # 添加前一日分析结果
                for analysis_type in default_analysis_type:
                    if analysis_type in zt_stats[date]:
                        stats = zt_stats[date][analysis_type]
                        stats_copy = stats.copy()
                        stats_copy.pop('详细数据', None)
                        stats_copy.pop('分析类型', None)

                        # 为每个指标添加分析类型前缀
                        for key, value in stats_copy.items():
                            record[f'{analysis_type}_{key}'] = value

            new_records.append(record)

        # 创建新数据的DataFrame并合并
        new_df = pd.DataFrame(new_records)
        final_df = pd.concat([existing_df, new_df], ignore_index=True) if not existing_df.empty else new_df

        # 确保excel目录存在并保存
        os.makedirs(os.path.dirname(excel_path), exist_ok=True)
        final_df.to_excel(excel_path, index=False)
        print(f"数据已保存到 {excel_path}")

    except Exception as e:
        print(f"合并和保存数据时出错: {str(e)}")


@timer
def fupan_all_statistics(start_date, end_date=None, excel_path='./excel/market_analysis.xlsx', max_workers=2):
    """
    分析指定时间段的市场数据并保存
    Args:
        start_date: 开始日期，格式为 'YYYYMMDD'
        end_date: 结束日期，格式为 'YYYYMMDD'
        excel_path: Excel文件路径
        max_workers: 最大线程数
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    try:
        # 读取现有的Excel文件（如果存在）
        try:
            existing_df = pd.read_excel(excel_path)
            existing_dates = existing_df['日期'].astype(str).tolist()
        except FileNotFoundError:
            existing_df = pd.DataFrame()
            existing_dates = []

        # 获取需要分析的交易日列表
        trading_days = get_trading_days(start_date, end_date)
        new_dates = [date for date in trading_days if date not in existing_dates]

        if not new_dates:
            print("所有日期的数据都已存在，无需更新")
            return

        print(f"需要分析的日期: {new_dates}")

        # 获取大盘统计数据
        pro = init_tushare()
        if not pro:
            return

        dapan_stats = get_multiple_dates_statistics(pro, min(new_dates), max(new_dates))
        print("\n大盘统计数据:")
        print(dapan_stats)

        # 获取涨停分析数据（日期前移一天）
        prev_start_date = get_prev_trading_day(min(new_dates))
        prev_end_date = get_prev_trading_day(max(new_dates))
        zt_stats = zt_analysis(prev_start_date, prev_end_date, max_workers=max_workers)

        # 调整涨停分析数据的日期，使其与大盘数据对齐
        aligned_zt_stats = {}
        for date, stats in zt_stats.items():
            next_date = get_next_trading_day(date)
            if next_date and next_date in new_dates:
                aligned_zt_stats[next_date] = stats

        # 合并数据并保存到Excel
        merge_and_save_analysis(dapan_stats, aligned_zt_stats, excel_path)

    except Exception as e:
        print(f"分析过程中出错: {str(e)}")
