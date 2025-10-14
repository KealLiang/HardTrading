import concurrent.futures  # 添加多线程支持
import logging
import os
from datetime import datetime
from threading import Lock

import akshare as ak
import pandas as pd
import tushare as ts

from config.holder import config
from decorators.practical import timer
from fetch.tonghuashun.fupan import get_zt_stocks, get_zaban_stocks, get_lianban_stocks, get_dieting_stocks
from utils.date_util import get_next_trading_day, get_prev_trading_day, get_trading_days
from utils.file_util import read_stock_data

os.environ['NODE_OPTIONS'] = '--no-deprecation'

# 向后兼容的全局变量
default_analysis_type = ['涨停', '连板', '跌停', '炸板']
ENABLE_API_FALLBACK = False
FORCE_SINGLE_THREAD_WHEN_API = True
FUPAN_EXCEL_PATH = 'excel/fupan_stocks.xlsx'


class FupanConfig:
    """复盘分析配置类"""

    # 开关配置
    ENABLE_API_FALLBACK = False  # 是否启用API兜底查询，默认关闭
    FORCE_SINGLE_THREAD_WHEN_API = True  # 当启用API时强制单线程

    # 文件路径
    FUPAN_EXCEL_PATH = 'excel/fupan_stocks.xlsx'
    ASTOCKS_DATA_PATH = 'data/astocks'

    # 分析类型
    DEFAULT_ANALYSIS_TYPES = ['涨停', '连板', '跌停', '炸板']

    # 数据类型到sheet名称的映射
    SHEET_MAPPING = {
        '涨停': ['首板数据', '连板数据'],  # 涨停包含首板和连板
        '连板': '连板数据',
        '跌停': '跌停数据',
        '炸板': '炸板数据'
    }

    # 各数据类型的列名定义
    COLUMN_DEFINITIONS = {
        '涨停': ['股票代码', '股票简称', '涨停开板次数', '最终涨停时间', '几天几板', '最新价', '首次涨停时间',
                 '最新涨跌幅', '连续涨停天数', '涨停原因类别'],
        '连板': ['股票代码', '股票简称', '涨停开板次数', '最终涨停时间', '几天几板', '最新价', '首次涨停时间',
                 '最新涨跌幅', '连续涨停天数', '涨停原因类别'],
        '跌停': ['股票代码', '股票简称', '跌停开板次数', '首次跌停时间', '跌停类型', '最新价', '最新涨跌幅',
                 '连续跌停天数', '跌停原因类型'],
        '炸板': ['股票代码', '股票简称', '涨停开板次数', '首次涨停时间', '最新价', '曾涨停', '最新涨跌幅',
                 '涨停封板时长', '涨停时间明细']
    }

    # 涨停开板次数分组配置（最后一个表示"X+")
    OPEN_BREAK_BUCKETS = [0, 1, 2, 3]


class FupanDataAccess:
    """复盘数据访问类"""

    def __init__(self, config=None):
        self.config = config or FupanConfig()
        self._excel_cache = {}  # Excel数据缓存

    def get_fupan_data(self, date, analysis_type):
        """
        统一的复盘数据获取接口

        Args:
            date: 日期，格式为 'YYYYMMDD'
            analysis_type: 分析类型

        Returns:
            DataFrame: 股票数据
        """
        try:
            # 检查Excel文件是否存在
            if not os.path.exists(self.config.FUPAN_EXCEL_PATH):
                print(f"Excel文件不存在: {self.config.FUPAN_EXCEL_PATH}")
                return pd.DataFrame()

            # 格式化日期
            excel_date = self._format_date_for_excel(date)
            if not excel_date:
                return pd.DataFrame()

            # 获取对应的sheet名称
            sheet_names = self.config.SHEET_MAPPING.get(analysis_type)
            if not sheet_names:
                print(f"未知的分析类型: {analysis_type}")
                return pd.DataFrame()

            # 如果是涨停数据，需要合并首板和连板数据
            if analysis_type == '涨停':
                all_data = []
                for sheet_name in sheet_names:
                    df_data = self._read_sheet_data(sheet_name, excel_date, date, analysis_type)
                    if not df_data.empty:
                        all_data.append(df_data)

                if all_data:
                    return pd.concat(all_data, ignore_index=True)
                else:
                    return pd.DataFrame()
            else:
                # 单个sheet的数据
                return self._read_sheet_data(sheet_names, excel_date, date, analysis_type)

        except Exception as e:
            print(f"从Excel读取数据失败: {str(e)}")
            return pd.DataFrame()

    def _format_date_for_excel(self, date_str):
        """将YYYYMMDD格式的日期转换为Excel中的格式：YYYY年MM月DD日"""
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            return date_obj.strftime('%Y年%m月%d日')
        except ValueError:
            print(f"日期格式错误: {date_str}")
            return None

    def _read_sheet_data(self, sheet_name, excel_date, date, analysis_type):
        """从指定sheet读取数据（带缓存）"""
        try:
            # 检查缓存
            cache_key = f"{sheet_name}_{excel_date}"
            if cache_key in self._excel_cache:
                date_data = self._excel_cache[cache_key]
            else:
                # 读取Excel数据
                df = pd.read_excel(self.config.FUPAN_EXCEL_PATH, sheet_name=sheet_name, index_col=0)

                # 检查日期列是否存在
                if excel_date not in df.columns:
                    print(f"在sheet '{sheet_name}' 中未找到日期列: {excel_date}")
                    return pd.DataFrame()

                # 获取该日期的数据并缓存
                date_data = df[excel_date].dropna()
                self._excel_cache[cache_key] = date_data

            if date_data.empty:
                print(f"在sheet '{sheet_name}' 的 {excel_date} 列中没有数据")
                return pd.DataFrame()

            # 解析数据
            columns = self.config.COLUMN_DEFINITIONS[analysis_type]
            parsed_data = []

            for cell_value in date_data:
                row_data = self._parse_excel_cell_data(cell_value, columns, date)
                if row_data:
                    parsed_data.append(row_data)

            if not parsed_data:
                return pd.DataFrame()

            # 创建DataFrame
            result_df = pd.DataFrame(parsed_data)

            # 数据后处理，确保格式与原接口一致
            if '最新涨跌幅' in result_df.columns:
                # 确保涨跌幅格式正确
                result_df['最新涨跌幅'] = result_df['最新涨跌幅'].apply(
                    lambda x: f"{float(x):.1f}%" if x and str(x).replace('.', '').replace('-', '').isdigit() else x
                )

            return result_df

        except Exception as e:
            print(f"读取sheet '{sheet_name}' 数据失败: {str(e)}")
            return pd.DataFrame()

    def _parse_excel_cell_data(self, cell_value, columns, date):
        """解析Excel单元格中的分号分隔数据"""
        if pd.isna(cell_value) or not str(cell_value).strip():
            return None

        parts = str(cell_value).split(';')
        if len(parts) < len(columns):
            # 如果数据不完整，补充空值
            parts.extend([''] * (len(columns) - len(parts)))

        # 创建数据字典，并添加日期相关的列名
        data = {}
        for i, col in enumerate(columns):
            if i < len(parts):
                value = parts[i].strip()
                # 为包含日期的列名添加日期后缀
                if col in ['涨停开板次数', '最终涨停时间', '几天几板', '首次涨停时间', '连续涨停天数', '涨停原因类别',
                           '跌停开板次数', '首次跌停时间', '跌停类型', '连续跌停天数', '跌停原因类型',
                           '曾涨停', '涨停封板时长', '涨停时间明细']:
                    data[f'{col}[{date}]'] = value
                else:
                    data[col] = value
            else:
                data[col] = ''

        return data


# 向后兼容的全局变量和函数
SHEET_MAPPING = FupanConfig.SHEET_MAPPING
COLUMN_DEFINITIONS = FupanConfig.COLUMN_DEFINITIONS

# 创建全局数据访问实例
_global_data_access = FupanDataAccess()


def get_local_fupan_data(date, analysis_type):
    """
    从本地Excel文件读取复盘数据（向后兼容函数）

    Args:
        date: 日期，格式为 'YYYYMMDD'
        analysis_type: 分析类型，'涨停'、'连板'、'跌停'、'炸板'

    Returns:
        DataFrame: 股票数据，格式与原接口函数一致
    """
    return _global_data_access.get_fupan_data(date, analysis_type)


# 向后兼容的工具函数
def format_date_for_excel(date_str):
    """将YYYYMMDD格式的日期转换为Excel中的格式：YYYY年MM月DD日"""
    return _global_data_access._format_date_for_excel(date_str)


def parse_excel_cell_data(cell_value, columns, date):
    """解析Excel单元格中的分号分隔数据"""
    return _global_data_access._parse_excel_cell_data(cell_value, columns, date)


def init_tushare():
    """
    初始化 Tushare SDK
    Returns:
        tushare.Pro: Tushare Pro API 实例
    """
    try:
        token = config.get('API', 'tushare_token')
        ts.set_token(token)
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
        # 计算涨跌幅超过 9% 的数量
        up_over_9 = len(data[data['pct_chg'] >= 9])
        down_over_9 = len(data[data['pct_chg'] <= -9])

        # 返回统计数据
        return {
            '日期': target_date,
            '上涨家数': up_count,
            '下跌家数': down_count,
            '平盘家数': flat_count,
            '涨幅超过5%家数': up_over_5,
            '跌幅超过5%家数': down_over_5,
            '涨幅超过7%家数': up_over_7,
            '跌幅超过7%家数': down_over_7,
            '涨幅超过9%家数': up_over_9,
            '跌幅超过9%家数': down_over_9
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
                local_data = get_local_data(base_date, next_date, stock_code)

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
        # 检查是否启用API兜底
        if not FupanConfig.ENABLE_API_FALLBACK:
            logging.warning(f"本地数据不足且API兜底已关闭，跳过股票 {stock_code}")
            return pd.DataFrame()

        logging.info(f"从本地读取[{stock_code}]数据失败，从API获取")
        try:
            # 处理股票代码格式
            if stock_code.startswith('6'):
                formatted_code = f"sh{stock_code}"
            else:
                formatted_code = f"sz{stock_code}"

            # 通过API获取数据
            stock_data = ak.stock_zh_a_daily(symbol=formatted_code,
                                             start_date=base_date,
                                             end_date=next_date)

            # 检查API返回的数据是否有效
            if stock_data is None or stock_data.empty:
                logging.warning(f"API也未能获取到股票 {stock_code} 的数据")
                return pd.DataFrame()

        except Exception as e:
            logging.error(f"处理股票 {stock_code} 时出错: {str(e)}")
            return pd.DataFrame()

    return stock_data


def get_local_data(base_date, next_date, stock_code, data_path='data/astocks'):
    local_data = None
    try:
        # 读取股票数据
        local_df = read_stock_data(stock_code, data_path)

        if local_df is None:
            logging.warning(f"未找到股票{stock_code}的数据文件")
            return None

        # 由于read_stock_data返回的日期列是datetime类型，需要转为字符串类型以匹配后续处理
        local_df['日期'] = local_df['日期'].dt.strftime('%Y-%m-%d')

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


# 注释掉不再使用的函数
# def merge_zt_and_zaban_stocks(date):
#     """
#     合并涨停和炸板的股票数据
#     Args:
#         date: 日期，格式为 'YYYYMMDD'
#     Returns:
#         pd.DataFrame: 合并后的DataFrame
#     """
#     try:
#         # 获取涨停和炸板数据
#         zt_df = get_zt_stocks(date)
#         zb_df = get_zaban_stocks(date)
#
#         if zt_df is None or zb_df is None:
#             return None
#
#         # 获取两个DataFrame的共同列
#         common_columns = list(set(zt_df.columns) & set(zb_df.columns))
#
#         # 使用共同列合并数据
#         zt_df = zt_df[common_columns]
#         zb_df = zb_df[common_columns]
#
#         # 合并并去重
#         merged_df = pd.concat([zt_df, zb_df]).drop_duplicates(subset=['股票代码'])
#
#         return merged_df
#     except Exception as e:
#         print(f"合并数据时出错: {str(e)}")
#         return None


def compute_open_break_group_stats(stock_df, performance, date):
    """
    计算基于涨停开板次数的分组统计数据
    Args:
        stock_df: 包含涨停开板次数的DataFrame
        performance: 次日表现数据字典
        date: 日期，格式为 'YYYYMMDD'
    Returns:
        dict: 包含分组统计数据的字典
    """
    try:
        # 确定列名
        candidate_cols = [f'涨停开板次数[{date}]', '涨停开板次数']
        open_break_col = None
        for c in candidate_cols:
            if c in stock_df.columns:
                open_break_col = c
                break

        if open_break_col is None or stock_df.empty:
            return {}

        # 解析代码与开板次数
        df_tmp = stock_df[['股票代码']].copy()
        df_tmp['代码key'] = df_tmp['股票代码'].astype(str).apply(lambda x: x.split('.')[0])
        df_tmp['开板次数_raw'] = pd.to_numeric(stock_df[open_break_col], errors='coerce')

        buckets = getattr(FupanConfig, 'OPEN_BREAK_BUCKETS', [0, 1, 2, 3, 4])
        last_bucket = buckets[-1] if buckets else 4

        def map_to_bucket(v):
            if pd.isna(v):
                return None
            for b in buckets[:-1]:
                if v == b:
                    return str(b)
            # 最后一档为 X+
            if v >= last_bucket:
                return f"{last_bucket}+"
            return None

        df_tmp['开板组'] = df_tmp['开板次数_raw'].apply(map_to_bucket)
        df_tmp = df_tmp.dropna(subset=['开板组'])

        # 收集每组的收益
        perf_map = performance  # {code: {...}}
        group_labels = list(dict.fromkeys(df_tmp['开板组'].tolist()))  # 保留出现过的顺序

        def is_valid_number(x):
            try:
                import math
                return x is not None and not (isinstance(x, float) and (math.isnan(x)))
            except Exception:
                return False

        group_stats = {}
        for label in group_labels:
            codes_in_group = df_tmp.loc[df_tmp['开板组'] == label, '代码key'].tolist()
            open_vals = []
            close_vals = []
            valid_count = 0
            total_in_group = len(codes_in_group)
            with_perf = 0
            open_ok = 0
            close_ok = 0
            for code_key in codes_in_group:
                p = perf_map.get(code_key)
                if p is None:
                    continue
                with_perf += 1
                ov = p.get('t+1收入开盘盈利')
                cv = p.get('t+1收入收盘盈利')
                if is_valid_number(ov):
                    open_vals.append(ov)
                    open_ok += 1
                if is_valid_number(cv):
                    close_vals.append(cv)
                    close_ok += 1
                # 样本数要求两者都有效
                if is_valid_number(ov) and is_valid_number(cv):
                    valid_count += 1

            # 计算均值与样本数（基于有效样本）
            open_mean = round(sum(open_vals) / len(open_vals), 2) if open_vals else None
            close_mean = round(sum(close_vals) / len(close_vals), 2) if close_vals else None

            group_stats[f'开板{label}_开盘收益'] = open_mean
            group_stats[f'开板{label}_收盘收益'] = close_mean
            group_stats[f'开板{label}_样本数'] = valid_count

            # 可选调试输出：设置环境变量 OPEN_BREAK_DEBUG=1 时打印缺失概况
            try:
                import os
                if os.getenv('OPEN_BREAK_DEBUG') == '1':
                    print(f"[OPEN_BREAK_DEBUG][{date}] 组={label} 总数={total_in_group} 有绩效={with_perf} 开盘有效={open_ok} 收盘有效={close_ok} 有效样本(两者均有效)={valid_count}")
            except Exception:
                pass

        return group_stats
    except Exception as e:
        print(f"计算开板次数分组统计失败: {str(e)}")
        return {}


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
        # 优先从本地Excel获取数据
        print(f"尝试从本地Excel获取 {date} 的{analysis_type}数据...")
        stock_df = get_local_fupan_data(date, analysis_type)

        # 如果本地数据为空，根据开关决定是否从接口获取
        if stock_df is None or stock_df.empty:
            if FupanConfig.ENABLE_API_FALLBACK:
                print(f"本地数据为空，从接口获取 {date} 的{analysis_type}数据...")
                if analysis_type == '涨停':
                    stock_df = get_zt_stocks(date)
                elif analysis_type == '连板':
                    stock_df = get_lianban_stocks(date)
                elif analysis_type == '跌停':
                    stock_df = get_dieting_stocks(date)
                elif analysis_type == '炸板':
                    stock_df = get_zaban_stocks(date)
                else:
                    print(f"未知的分析类型: {analysis_type}")
                    return None
            else:
                print(f"本地数据为空且API兜底已关闭，跳过 {date} 的{analysis_type}数据分析")
                return None
        else:
            print(f"成功从本地Excel获取到 {len(stock_df)} 条{analysis_type}数据")

        if stock_df is None or stock_df.empty:
            print(f"未获取到 {date} 的{analysis_type}股票数据")
            return None

        # 获取次日表现数据，直接传入整个DataFrame
        performance = get_stock_next_day_performance(stock_df, date)
        if not performance:
            return None

        # 统计数据（过滤掉nan值）
        import math

        def filter_nan(values):
            return [x for x in values if not (isinstance(x, float) and math.isnan(x))]

        close_open_profit = filter_nan([data['t+1收入开盘盈利'] for data in performance.values()])
        close_close_profit = filter_nan([data['t+1收入收盘盈利'] for data in performance.values()])
        close_high_profit = filter_nan([data['t+1收入高价盈利'] for data in performance.values()])
        close_low_profit = filter_nan([data['t+1收入低价盈利'] for data in performance.values()])
        today_changes = filter_nan([data['t+1实体涨跌幅'] for data in performance.values()])
        open_open_profit = filter_nan([data['t+1开入开盘盈利'] for data in performance.values()])
        open_close_profit = filter_nan([data['t+1开入收盘盈利'] for data in performance.values()])
        high_open_profit = filter_nan([data['t+1高入开盘盈利'] for data in performance.values()])
        high_close_profit = filter_nan([data['t+1高入收盘盈利'] for data in performance.values()])

        # 计算统计指标（安全计算，避免除零错误）
        def safe_mean(values):
            return round(sum(values) / len(values), 2) if values else 0

        def safe_ratio(values):
            return round(len([x for x in values if x > 0]) / len(values) * 100, 2) if values else 0

        stats = {
            '分析类型': analysis_type,
            '样本数量': len(performance),
            '次日收入开盘': safe_mean(close_open_profit),
            '次日收入收盘': safe_mean(close_close_profit),
            '次日收入高价': safe_mean(close_high_profit),
            '次日收入低价': safe_mean(close_low_profit),
            '次日实体': safe_mean(today_changes),
            '次日开入开盘': safe_mean(open_open_profit),
            '次日开入收盘': safe_mean(open_close_profit),
            '次日高入开盘': safe_mean(high_open_profit),
            '次日高入收盘': safe_mean(high_close_profit),
            '次日收入开盘涨比': safe_ratio(close_open_profit),
            '次日收入收盘涨比': safe_ratio(close_close_profit),
            '次日实体上涨比例': safe_ratio(today_changes),
            '次日开入开盘涨比': safe_ratio(open_open_profit),
            '次日开入收盘涨比': safe_ratio(open_close_profit),
            '次日高入开盘涨比': safe_ratio(high_open_profit),
            '次日高入收盘涨比': safe_ratio(high_close_profit),
            '详细数据': performance
        }

        # 基于涨停开板次数的分组统计（仅对涨停分析执行）
        if analysis_type == '涨停':
            try:
                group_stats = compute_open_break_group_stats(stock_df, performance, date)
                stats.update(group_stats)
            except Exception as e:
                print(f"按开板次数分组统计失败: {str(e)}")

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
        for analysis_type in FupanConfig.DEFAULT_ANALYSIS_TYPES:
            tasks.append((date, analysis_type))

    # 根据API开关决定是否使用多线程
    config = FupanConfig()
    if config.ENABLE_API_FALLBACK and config.FORCE_SINGLE_THREAD_WHEN_API:
        print("启用API兜底且强制单线程模式")
        max_workers = 1
    elif not config.ENABLE_API_FALLBACK:
        print("API兜底已关闭，使用多线程处理本地数据")

    # 使用线程池处理任务
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
                else:
                    print(f"\n{date} {analysis_type}股票分析失败，跳过")
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
                # 获取涨停数据（优先从本地）
                zt_df = get_local_fupan_data(date, '涨停')
                if zt_df.empty and FupanConfig.ENABLE_API_FALLBACK:
                    zt_df = get_zt_stocks(date)
                zt_count = len(zt_df) if zt_df is not None else 0
                record['涨停数'] = zt_count

                # 获取跌停数据（优先从本地）
                dt_df = get_local_fupan_data(date, '跌停')
                if dt_df.empty and FupanConfig.ENABLE_API_FALLBACK:
                    dt_df = get_dieting_stocks(date)
                dt_count = len(dt_df) if dt_df is not None else 0
                record['跌停数'] = dt_count

                # 获取连板数据（优先从本地）
                lb_df = get_local_fupan_data(date, '连板')
                if lb_df.empty and FupanConfig.ENABLE_API_FALLBACK:
                    lb_df = get_lianban_stocks(date)
                lb_count = len(lb_df) if lb_df is not None else 0
                record['连板数'] = lb_count

                # 获取炸板数据（优先从本地）
                zb_df = get_local_fupan_data(date, '炸板')
                if zb_df.empty and FupanConfig.ENABLE_API_FALLBACK:
                    zb_df = get_zaban_stocks(date)
                zb_count = len(zb_df) if zb_df is not None else 0
                record['炸板数'] = zb_count

                # 添加前一日分析结果
                for analysis_type in FupanConfig.DEFAULT_ANALYSIS_TYPES:
                    if analysis_type in zt_stats[date]:
                        stats = zt_stats[date][analysis_type]
                        # 检查stats是否为None
                        if stats is not None:
                            stats_copy = stats.copy()
                            stats_copy.pop('详细数据', None)
                            stats_copy.pop('分析类型', None)

                            # 为每个指标添加分析类型前缀
                            for key, value in stats_copy.items():
                                record[f'{analysis_type}_{key}'] = value

            new_records.append(record)

        # 创建新数据的DataFrame
        new_df = pd.DataFrame(new_records)

        if not existing_df.empty:
            # 删除现有数据中与新数据日期重复的行
            new_dates = new_df['日期'].astype(str).tolist()
            existing_df = existing_df[~existing_df['日期'].astype(str).isin(new_dates)]
            # 合并数据
            final_df = pd.concat([existing_df, new_df], ignore_index=True)
            # 统一日期列的数据类型后排序
            final_df['日期'] = final_df['日期'].astype(str)
            final_df = final_df.sort_values('日期').reset_index(drop=True)
        else:
            final_df = new_df

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

        # 检查哪些日期需要更新（新日期或数据不完整的日期）
        new_dates = []
        incomplete_dates = []

        for date in trading_days:
            if date not in existing_dates:
                new_dates.append(date)
            else:
                # 检查现有数据是否完整（涨停分析数据是否为空）
                date_row = existing_df[existing_df['日期'].astype(str) == date]
                if not date_row.empty:
                    # 检查关键的涨停分析列是否为空
                    key_cols = ['涨停_次日收入开盘', '涨停_次日收入收盘', '连板_次日收入开盘']
                    is_incomplete = False
                    for col in key_cols:
                        if col in date_row.columns:
                            if pd.isna(date_row[col].iloc[0]):
                                is_incomplete = True
                                break

                    if is_incomplete:
                        incomplete_dates.append(date)
                        new_dates.append(date)

        if not new_dates:
            print("所有日期的数据都已存在且完整，无需更新")
            return

        if incomplete_dates:
            print(f"发现数据不完整的日期: {incomplete_dates}")

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
