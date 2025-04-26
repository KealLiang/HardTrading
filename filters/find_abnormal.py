import concurrent.futures
import os
from datetime import datetime, timedelta
from multiprocessing import cpu_count

import a_trade_calendar
import pandas as pd
from tqdm import tqdm

from decorators.practical import timer

# 定义偏离度阈值
DEVIATION_30D_UP_THRESHOLD = 200.0  # 30日上涨偏离度触发阈值
DEVIATION_30D_DOWN_THRESHOLD = -70.0  # 30日下跌偏离度触发阈值
DEVIATION_10D_UP_THRESHOLD = 100.0  # 10日上涨偏离度触发阈值
DEVIATION_10D_DOWN_THRESHOLD = -50.0  # 10日下跌偏离度触发阈值

# 定义多线程处理的最大线程数
MAX_WORKERS = cpu_count() or 4  # 如果无法获取CPU核心数，默认使用4个线程

# 定义预测范围系数 - 用于计算预测阈值范围
PREDICT_CLOSE_FACTOR = 0.80  # 接近触发的系数（例如：30日阈值的90%）
PREDICT_FURTHER_FACTOR = 0.75  # 较远触发的系数（例如：30日阈值的85%）

# 下跌时的阈值系数（由于下跌阈值是负数，使用不同因子）
PREDICT_DOWN_CLOSE_FACTOR = 0.95  # 下跌接近触发系数
PREDICT_DOWN_FURTHER_FACTOR = 0.90  # 下跌较远触发系数

# 定义必显示列表（用于调试）
# 格式："股票代码": "股票名称"
MUST_SHOW_STOCKS = {
    # "600610": "中毅达",
    # 可以添加其他需要调试的股票
}


# 定义严重异动股票对象
class SeriousAbnormalStock:
    def __init__(self, stock_code, stock_name, date, trigger_reason=None):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.date = date
        self.trigger_reason = trigger_reason or '未知'  # 触发原因
        self.cumulative_deviation_10d = 0.0  # 10日偏离度
        self.cumulative_deviation_30d = 0.0  # 30日偏离度
        self.abnormal_count_10d_up = 0  # 10日上涨异常波动次数
        self.abnormal_count_10d_down = 0  # 10日下跌异常波动次数
        self.abnormal_direction = None  # 异常方向: 上涨 or 下跌
        self.latest_price = 0.0  # 最新价格
        self.prediction_status = ''  # 预测状态
        self.days_to_trigger = 0  # 预计触发天数
        self.is_debug = False  # 是否是调试用的必显示股票

    def __str__(self):
        # 根据异常波动方向选择显示哪个计数
        abnormal_count = self.abnormal_count_10d_up if self.abnormal_direction == "上涨" else self.abnormal_count_10d_down

        base_str = (f'[{self.stock_code} {self.stock_name}] - 触发原因:{self.trigger_reason} - '
                    f'10日偏离度:{self.cumulative_deviation_10d:.2f}% - '
                    f'30日偏离度:{self.cumulative_deviation_30d:.2f}% - '
                    f'10日异常波动次数:{abnormal_count} - '
                    f'异动方向:{self.abnormal_direction} - '
                    f'日期:{self.date}')

        if self.prediction_status:
            base_str += f' - 预测:{self.prediction_status}'

        if self.is_debug:
            base_str += ' [调试显示]'

        return base_str


def process_stock_file(filename, date, data_path, next_trading_day, check_updown_fluctuation):
    """
    处理单个股票文件，用于多线程并行处理
    
    :param filename: 股票数据文件名
    :param date: 查询日期字符串
    :param data_path: 数据路径
    :param next_trading_day: 下一个交易日
    :param check_updown_fluctuation: 是否检查同向异常波动
    :return: 元组(触发的股票, 潜在的股票, 调试的股票)
    """
    if not filename.endswith('.csv'):
        return None, None, None

    # 获取股票代码和名称
    stock_code, stock_name = filename.split('_')
    stock_name = stock_name.replace('.csv', '')  # 去掉后缀

    # 读取股票的交易数据
    stock_data = pd.read_csv(os.path.join(data_path, filename), header=None,
                             names=['日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额',
                                    '振幅', '涨跌幅', '涨跌额', '换手率'])
    stock_data['日期'] = pd.to_datetime(stock_data['日期'])
    stock_data = stock_data.sort_values(by='日期')  # 按日期排序

    # 跳过数据不足的股票 - 需要31天计算真正的30日偏离度
    if len(stock_data) < 31:  # 至少需要31天数据来计算30日偏离度
        return None, None, None

    # 查找当天数据
    date_dt = pd.to_datetime(date)
    date_index = stock_data['日期'].searchsorted(date_dt)
    if date_index >= len(stock_data) or stock_data.iloc[date_index]['日期'] != date_dt:
        return None, None, None  # 没有当天数据

    # 检查是否为必显示股票
    is_must_show = stock_code in MUST_SHOW_STOCKS

    # 检查是否已触发严重异动
    triggered = check_serious_abnormal(stock_code, stock_name, date, stock_data, date_index, check_updown_fluctuation)
    if triggered:
        return triggered, None, None  # 已触发的股票不再预测

    # 预测下一交易日可能触发的股票
    if next_trading_day:
        potential = predict_potential_trigger(stock_code, stock_name, date, next_trading_day, stock_data, date_index)
        if potential:
            return None, potential, None  # 已预测的股票不再进行调试显示

    # 如果是必显示股票但未被识别为已触发或可能触发，单独处理并添加到调试列表
    if is_must_show:
        debug_stock = create_debug_stock(stock_code, stock_name, date, stock_data, date_index)
        return None, None, debug_stock

    return None, None, None


@timer
def find_serious_abnormal_stocks(date, data_path='./data/astocks', predict_next_day=True, check_updown_fluctuation=True):
    """
    查找指定日期触发严重异动的股票，以及预测下一交易日可能触发严重异动的股票
    
    :param date: 查询日期，格式为'YYYY-MM-DD'
    :param data_path: 股票数据路径
    :param predict_next_day: 是否预测下一交易日可能的异动
    :param check_updown_fluctuation: 是否检查同向异常波动，默认True
    :return: 严重异动股票列表
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    # 确保日期为交易日
    if not a_trade_calendar.is_trade_date(date):
        date = get_previous_trading_date(date)
        print(f"输入日期非交易日，已调整为最近交易日: {date}")

    # 获取下一个交易日
    next_trading_day = None
    if predict_next_day:
        next_trading_day = get_next_trading_date(date)

    # 获取所有股票文件
    stock_files = [f for f in os.listdir(data_path) if f.endswith('.csv')]

    triggered_stocks = []  # 已触发严重异动的股票
    potential_stocks = []  # 可能在下一交易日触发的股票
    debug_stocks = []  # 调试用必显示股票

    # 单线程处理所有股票文件
    # for filename in tqdm(stock_files, desc=f"正在处理日期[{date}]"):  # 多线程时日志会刷屏
    for filename in stock_files:
        triggered, potential, debug = process_stock_file(
            filename, date, data_path, next_trading_day, check_updown_fluctuation
        )
        if triggered:
            triggered_stocks.append(triggered)
        if potential:
            potential_stocks.append(potential)
        if debug:
            debug_stocks.append(debug)

    # 按触发原因排序
    triggered_stocks.sort(key=lambda x: x.trigger_reason)
    potential_stocks.sort(key=lambda x: x.days_to_trigger)

    # 合并结果
    all_stocks = triggered_stocks + potential_stocks + debug_stocks

    # 输出
    print(f"已触发严重异动的股票数量: {len(triggered_stocks)}")
    for stock in triggered_stocks:
        print(stock)

    print(f"可能即将触发严重异动的股票数量: {len(potential_stocks)}")
    for stock in potential_stocks:
        print(stock)

    if debug_stocks:
        print(f"调试显示的股票数量: {len(debug_stocks)}")
        for stock in debug_stocks:
            print(stock)

    return all_stocks


def find_serious_abnormal_stocks_range(start_date=None, end_date=None, data_path='./data/astocks', 
                                      predict_next_day=True, check_updown_fluctuation=True,
                                      skip_existing=True):
    """
    在指定日期范围内查找触发严重异动的股票，使用多线程并行处理多个日期
    
    :param start_date: 开始日期，格式为'YYYY-MM-DD'，如果为None则使用end_date
    :param end_date: 结束日期，格式为'YYYY-MM-DD'，如果为None则使用当前日期
    :param data_path: 股票数据路径
    :param predict_next_day: 是否预测下一交易日可能的异动
    :param check_updown_fluctuation: 是否检查同向异常波动，默认True
    :param skip_existing: 是否跳过已存在结果的日期，默认True
    :return: 包含所有日期严重异动股票的字典，键为日期
    """
    # 处理日期参数
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    if start_date is None:
        start_date = end_date
    
    # 确保日期格式正确
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    # 获取日期范围内的所有交易日
    current_dt = start_dt
    trading_dates = []
    
    while current_dt <= end_dt:
        current_date = current_dt.strftime('%Y-%m-%d')
        if a_trade_calendar.is_trade_date(current_date):
            trading_dates.append(current_date)
        current_dt += timedelta(days=1)
    
    if not trading_dates:
        print(f"在 {start_date} 到 {end_date} 范围内没有找到交易日")
        return {}
    
    # 检查已存在的日期数据
    excel_file_path = './excel/serious_abnormal_history.xlsx'
    existing_dates = set()
    
    if skip_existing and os.path.exists(excel_file_path):
        try:
            existing_df = pd.read_excel(excel_file_path)
            if '日期' in existing_df.columns:
                existing_dates = set(existing_df['日期'].astype(str).unique())
                print(f"已从Excel文件中读取 {len(existing_dates)} 个已处理日期")
        except Exception as e:
            print(f"读取现有Excel文件时出错: {e}")
    
    # 过滤掉已存在的日期
    if skip_existing and existing_dates:
        original_count = len(trading_dates)
        trading_dates = [date for date in trading_dates if date not in existing_dates]
        skipped_count = original_count - len(trading_dates)
        if skipped_count > 0:
            print(f"已跳过 {skipped_count} 个已处理的日期")
    
    if not trading_dates:
        print("所有日期都已处理，无需重复计算")
        return {}
    
    # 存储所有日期的结果
    all_results = {}
    
    # 使用多线程并行处理多个日期
    print(f"使用多线程处理 {len(trading_dates)} 个交易日，最大线程数: {MAX_WORKERS}")
    
    def process_date(date):
        """处理单个日期的函数，用于多线程"""
        try:
            print(f"正在处理日期: {date}")
            stocks = find_serious_abnormal_stocks(
                date, 
                data_path=data_path, 
                predict_next_day=predict_next_day,
                check_updown_fluctuation=check_updown_fluctuation
            )
            return date, stocks
        except Exception as e:
            print(f"处理日期 {date} 时出错: {e}")
            return date, []
    
    # 使用线程池并行处理多个日期
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 创建任务列表
        futures = [executor.submit(process_date, date) for date in trading_dates]
        
        # 收集结果
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="处理多个日期"):
            date, stocks = future.result()
            if stocks:
                all_results[date] = stocks
    
    # 输出汇总信息
    print(f"已完成 {len(trading_dates)} 个交易日的严重异动股票查找")
    for date, stocks in all_results.items():
        triggered_stocks = [s for s in stocks if s.days_to_trigger == 0]
        potential_stocks = [s for s in stocks if s.days_to_trigger > 0]
        debug_stocks = [s for s in stocks if s.is_debug]
        
        print(f"日期 {date}: 已触发 {len(triggered_stocks)} 只, 潜在 {len(potential_stocks)} 只, 调试 {len(debug_stocks)} 只")
    
    # 串行写入Excel文件
    print("开始写入Excel文件...")
    excel_file_path = './excel/serious_abnormal_history.xlsx'
    
    # 先读取现有Excel文件
    existing_df = None
    if os.path.exists(excel_file_path):
        try:
            existing_df = pd.read_excel(excel_file_path)
        except Exception as e:
            print(f"读取现有Excel文件时出错: {e}")
    
    # 处理每个日期的数据并写入
    for date, stocks in all_results.items():
        write_to_excel(stocks, excel_file_path, date, existing_df)
        # 更新existing_df以便下一次写入
        try:
            existing_df = pd.read_excel(excel_file_path)
        except Exception as e:
            print(f"更新Excel数据时出错: {e}")
    
    return all_results


def is_abnormal_fluctuation(stock_code, stock_name, data_3d, stock_data=None, end_idx=None):
    """
    判断股票是否出现异常波动
    
    :param stock_code: 股票代码
    :param stock_name: 股票名称
    :param data_3d: 最近3个交易日的数据
    :param stock_data: 完整股票数据，用于计算换手率
    :param end_idx: 截止索引，用于计算前5日数据
    :return: 是否异常波动，异常方向
    """
    # 确保有3天数据
    if len(data_3d) < 3:
        return False, None

    # 计算3日累计涨跌幅
    cumulative_change = data_3d['涨跌幅'].sum()

    # 根据股票类型确定异常波动阈值
    if 'ST' in stock_name or '*ST' in stock_name:
        # ST和*ST主板股票
        threshold = 12
    elif stock_code.startswith('688'):
        # 科创板股票
        threshold = 30
    elif stock_code.startswith('300'):
        # 创业板股票
        threshold = 30
    else:
        # 主板股票
        threshold = 20

        # 检查换手率条件（主板特有）
        try:
            if '换手率' in data_3d.columns and stock_data is not None and end_idx is not None:
                # 计算3日累计换手率
                cumulative_turnover = data_3d['换手率'].sum()

                # 获取前5个交易日数据
                if end_idx > 8:  # 确保有足够的历史数据
                    start_idx = end_idx - 8  # 3天+5天=8天
                    prev_5d_data = stock_data.iloc[start_idx:start_idx + 5]

                    if len(prev_5d_data) == 5 and '换手率' in prev_5d_data.columns:
                        prev_5d_avg_turnover = prev_5d_data['换手率'].mean()
                        current_3d_avg_turnover = data_3d['换手率'].mean()

                        # 判断换手率条件
                        if (cumulative_turnover >= 20 and
                                current_3d_avg_turnover / prev_5d_avg_turnover >= 30):
                            return True, "上涨" if cumulative_change > 0 else "下跌"
        except Exception as e:
            # 如果换手率数据缺失或计算出错，则忽略换手率条件
            pass

    # 判断涨跌幅条件
    if cumulative_change >= threshold:
        return True, "上涨"
    elif cumulative_change <= -threshold:
        return True, "下跌"

    return False, None


def calculate_period_deviation(stock_data):
    """
    计算周期内的价格偏离度（首尾价格对比）
    
    :param stock_data: 股票历史数据（按时间排序）
    :return: 计算后的偏离度百分比
    """
    # 确保日期已排序
    stock_data = stock_data.sort_values(by='日期').copy()

    if len(stock_data) < 2:
        return 0.0

    # 获取首尾价格
    start_price = stock_data.iloc[0]['收盘']
    end_price = stock_data.iloc[-1]['收盘']

    # 计算偏离度
    deviation = ((end_price / start_price) - 1) * 100

    return deviation


def check_serious_abnormal(stock_code, stock_name, date, stock_data, date_index, check_updown_fluctuation=True):
    """
    检查股票是否触发严重异动
    
    :param stock_code: 股票代码
    :param stock_name: 股票名称
    :param date: 日期
    :param stock_data: 股票历史数据
    :param date_index: 当前日期在数据中的索引
    :param check_updown_fluctuation: 是否检查同向异常波动，默认True
    :return: 严重异动股票对象或None
    """
    # 提取数据
    end_idx = date_index + 1  # 不含结束索引

    # 确保有足够的历史数据 - 需要31天才能计算真正的30日偏离度
    if date_index < 31:
        return None

    # 取真正30日偏离度的数据 (31天数据，计算第1天到第31天，共30个间隔)
    data_30d = stock_data.iloc[end_idx - 31:end_idx].copy()

    # 取真正10日偏离度的数据 (11天数据，计算第1天到第11天，共10个间隔)
    data_10d = stock_data.iloc[end_idx - 11:end_idx].copy()

    # 计算10日和30日偏离度
    deviation_10d = calculate_period_deviation(data_10d)
    deviation_30d = calculate_period_deviation(data_30d)

    # 为预测取9日和29日数据
    data_9d = stock_data.iloc[end_idx - 10:end_idx].copy()  # 10天数据，计算9个间隔
    data_29d = stock_data.iloc[end_idx - 30:end_idx].copy()  # 30天数据，计算29个间隔
    deviation_9d = calculate_period_deviation(data_9d)
    deviation_29d = calculate_period_deviation(data_29d)

    # 判断是否是科创板股票
    is_sci_tech_board = stock_code.startswith('688')

    # 检查连续10个交易日内的异常波动次数
    # 注意：这里仍然使用10天数据，因为我们要检查的是10天内的异常波动
    abnormal_data = stock_data.iloc[end_idx - 10:end_idx].copy()
    abnormal_count_up = 0
    abnormal_count_down = 0

    # 滑动窗口检查每个连续3天区间是否存在异常波动
    for i in range(len(abnormal_data) - 2):
        data_3d = abnormal_data.iloc[i:i + 3]
        is_abnormal, direction = is_abnormal_fluctuation(stock_code, stock_name, data_3d, stock_data, end_idx)

        if is_abnormal:
            if direction == "上涨":
                abnormal_count_up += 1
            elif direction == "下跌":
                abnormal_count_down += 1

    # 确定需要的异常波动次数
    required_count = 3 if is_sci_tech_board else 4  # 科创板3次，主板4次

    # 触发检查 - 首先检查价格偏离度条件（优先级更高）
    trigger_reason = None
    abnormal_direction = None

    # 1. 检查30日偏离度 (最高优先级)
    if deviation_30d >= DEVIATION_30D_UP_THRESHOLD:
        trigger_reason = f"30日偏离度达到+{deviation_30d:.2f}%"
        abnormal_direction = "上涨"
    elif deviation_30d <= DEVIATION_30D_DOWN_THRESHOLD:
        trigger_reason = f"30日偏离度达到{deviation_30d:.2f}%"
        abnormal_direction = "下跌"

    # 2. 检查10日偏离度 (第二优先级)
    elif deviation_10d >= DEVIATION_10D_UP_THRESHOLD:
        trigger_reason = f"10日偏离度达到+{deviation_10d:.2f}%"
        abnormal_direction = "上涨"
    elif deviation_10d <= DEVIATION_10D_DOWN_THRESHOLD:
        trigger_reason = f"10日偏离度达到{deviation_10d:.2f}%"
        abnormal_direction = "下跌"

    # 3. 检查10日内异常波动次数 (最低优先级 - 补充规则)
    elif check_updown_fluctuation and abnormal_count_up >= required_count:
        trigger_reason = f"10日内{abnormal_count_up}次同向上涨异常波动"
        abnormal_direction = "上涨"
    elif check_updown_fluctuation and abnormal_count_down >= required_count:
        trigger_reason = f"10日内{abnormal_count_down}次同向下跌异常波动"
        abnormal_direction = "下跌"

    # 如果触发严重异动
    if trigger_reason:
        abnormal_stock = SeriousAbnormalStock(stock_code, stock_name, date, trigger_reason)
        abnormal_stock.cumulative_deviation_10d = deviation_10d
        abnormal_stock.cumulative_deviation_30d = deviation_30d
        abnormal_stock.abnormal_count_10d_up = abnormal_count_up
        abnormal_stock.abnormal_count_10d_down = abnormal_count_down
        abnormal_stock.abnormal_direction = abnormal_direction
        abnormal_stock.latest_price = stock_data.iloc[date_index]['收盘']

        # 为已触发的股票也添加预测
        predict_next_deviation(abnormal_stock, deviation_9d, deviation_29d)

        return abnormal_stock

    return None


def predict_next_deviation(stock, deviation_9d, deviation_29d):
    """
    为股票预测下一个交易日可能的偏离度变化
    
    :param stock: 股票对象
    :param deviation_9d: 9日偏离度
    :param deviation_29d: 29日偏离度
    """
    prediction_msg = []

    if stock.abnormal_direction == "上涨":
        # 计算距离10日和30日异动的距离
        distance_to_10d = DEVIATION_10D_UP_THRESHOLD - stock.cumulative_deviation_10d
        distance_to_30d = DEVIATION_30D_UP_THRESHOLD - stock.cumulative_deviation_30d

        # 判断哪个更接近触发
        if 0 <= distance_to_10d <= distance_to_30d:
            if distance_to_10d <= 0:
                prediction_msg.append(f"已触发10日上涨异动，超出阈值{abs(distance_to_10d):.2f}%")
            else:
                prediction_msg.append(f"接近10日上涨异动，还差{distance_to_10d:.2f}%")
        else:
            if distance_to_30d <= 0:
                prediction_msg.append(f"已触发30日上涨异动，超出阈值{abs(distance_to_30d):.2f}%")
            else:
                prediction_msg.append(f"接近30日上涨异动，还差{distance_to_30d:.2f}%")

        # 添加9日预测
        if deviation_9d > 0:
            needed_for_10d = DEVIATION_10D_UP_THRESHOLD - deviation_9d
            if needed_for_10d <= 10:  # 只有当差值较小时才显示
                prediction_msg.append(f"9日偏离度已达{deviation_9d:.2f}%，再涨{needed_for_10d:.2f}%将触发10日异动")

        # 添加29日预测
        if deviation_29d > 0:
            needed_for_30d = DEVIATION_30D_UP_THRESHOLD - deviation_29d
            if needed_for_30d <= 20:  # 只有当差值较小时才显示
                prediction_msg.append(f"29日偏离度已达{deviation_29d:.2f}%，再涨{needed_for_30d:.2f}%将触发30日异动")
    else:
        # 下跌方向的分析
        distance_to_10d = DEVIATION_10D_DOWN_THRESHOLD - stock.cumulative_deviation_10d
        distance_to_30d = DEVIATION_30D_DOWN_THRESHOLD - stock.cumulative_deviation_30d

        # 判断哪个更接近触发
        if distance_to_10d >= 0:
            prediction_msg.append(f"已触发10日下跌异动，超出阈值{abs(distance_to_10d):.2f}%")
        elif distance_to_30d >= 0:
            prediction_msg.append(f"已触发30日下跌异动，超出阈值{abs(distance_to_30d):.2f}%")
        elif abs(distance_to_10d) <= abs(distance_to_30d):
            prediction_msg.append(f"接近10日下跌异动，还差{abs(distance_to_10d):.2f}%")
        else:
            prediction_msg.append(f"接近30日下跌异动，还差{abs(distance_to_30d):.2f}%")

        # 添加9日预测
        if deviation_9d < 0:
            needed_for_10d = DEVIATION_10D_DOWN_THRESHOLD - deviation_9d
            if needed_for_10d >= -10:  # 只有当差值较小时才显示
                prediction_msg.append(f"9日偏离度已达{deviation_9d:.2f}%，再跌{abs(needed_for_10d):.2f}%将触发10日异动")

        # 添加29日预测
        if deviation_29d < 0:
            needed_for_30d = DEVIATION_30D_DOWN_THRESHOLD - deviation_29d
            if needed_for_30d >= -20:  # 只有当差值较小时才显示
                prediction_msg.append(
                    f"29日偏离度已达{deviation_29d:.2f}%，再跌{abs(needed_for_30d):.2f}%将触发30日异动")

    # 设置预测信息
    if prediction_msg:
        stock.prediction_status = " | ".join(prediction_msg)


def predict_potential_trigger(stock_code, stock_name, date, next_date, stock_data, date_index):
    """
    预测股票是否可能在下一交易日通过偏离度触发严重异动
    
    :param stock_code: 股票代码
    :param stock_name: 股票名称
    :param date: 当前日期
    :param next_date: 下一交易日
    :param stock_data: 股票历史数据
    :param date_index: 当前日期在数据中的索引
    :return: 可能触发严重异动的股票对象或None
    """
    # 提取数据
    end_idx = date_index + 1  # 不含结束索引

    # 确保有足够的历史数据
    if date_index < 31:  # 需要31天才能计算真正的30日偏离度
        return None

    # 取真正30日偏离度的数据 (31天数据，计算第1天到第31天，共30个间隔)
    data_30d = stock_data.iloc[end_idx - 31:end_idx].copy()

    # 取真正10日偏离度的数据 (11天数据，计算第1天到第11天，共10个间隔)
    data_10d = stock_data.iloc[end_idx - 11:end_idx].copy()

    # 为预测取9日和29日数据
    data_9d = stock_data.iloc[end_idx - 10:end_idx].copy()  # 10天数据，计算9个间隔
    data_29d = stock_data.iloc[end_idx - 30:end_idx].copy()  # 30天数据，计算29个间隔

    # 计算偏离度
    deviation_10d = calculate_period_deviation(data_10d)
    deviation_9d = calculate_period_deviation(data_9d)
    deviation_30d = calculate_period_deviation(data_30d)
    deviation_29d = calculate_period_deviation(data_29d)

    # 计算预测阈值
    # 上涨偏离度预测阈值
    threshold_29d_close_up = DEVIATION_30D_UP_THRESHOLD * PREDICT_CLOSE_FACTOR  # 29日接近触发阈值
    threshold_29d_further_up = DEVIATION_30D_UP_THRESHOLD * PREDICT_FURTHER_FACTOR  # 29日较远触发阈值
    threshold_9d_close_up = DEVIATION_10D_UP_THRESHOLD * PREDICT_CLOSE_FACTOR  # 9日接近触发阈值
    threshold_9d_further_up = DEVIATION_10D_UP_THRESHOLD * PREDICT_FURTHER_FACTOR  # 9日较远触发阈值

    # 下跌偏离度预测阈值（由于是负数，要用不同的计算方式）
    threshold_29d_close_down = DEVIATION_30D_DOWN_THRESHOLD * PREDICT_DOWN_CLOSE_FACTOR  # 29日接近触发阈值
    threshold_29d_further_down = DEVIATION_30D_DOWN_THRESHOLD * PREDICT_DOWN_FURTHER_FACTOR  # 29日较远触发阈值 
    threshold_9d_close_down = DEVIATION_10D_DOWN_THRESHOLD * PREDICT_DOWN_CLOSE_FACTOR  # 9日接近触发阈值
    threshold_9d_further_down = DEVIATION_10D_DOWN_THRESHOLD * PREDICT_DOWN_FURTHER_FACTOR  # 9日较远触发阈值

    # 检查是否可能在下一交易日触发偏离度条件
    prediction_reason = None
    days_to_trigger = 99  # 默认大数值
    abnormal_direction = "上涨" if deviation_10d > 0 else "下跌"

    # 核心逻辑：检查下一个交易日可能触发的情况，按照优先级顺序

    # 1. 预测30日偏离度触发条件 (最高优先级)
    if threshold_29d_close_up <= deviation_29d < DEVIATION_30D_UP_THRESHOLD:
        # 下一日若上涨(200-deviation_29d)%就会触发
        needed_increase = DEVIATION_30D_UP_THRESHOLD - deviation_29d
        prediction_reason = f"29日偏离度已达{deviation_29d:.2f}%，下一交易日若涨幅>={needed_increase:.2f}%将触发严重异动"
        days_to_trigger = 1
        abnormal_direction = "上涨"
    elif DEVIATION_30D_DOWN_THRESHOLD < deviation_29d <= threshold_29d_close_down:
        # 下一日若下跌(70+deviation_29d)%就会触发
        needed_decrease = DEVIATION_30D_DOWN_THRESHOLD - deviation_29d
        prediction_reason = f"29日偏离度已达{deviation_29d:.2f}%，下一交易日若跌幅>={abs(needed_decrease):.2f}%将触发严重异动"
        days_to_trigger = 1
        abnormal_direction = "下跌"

    # 2. 预测10日偏离度触发条件 (次高优先级)
    elif threshold_9d_close_up <= deviation_9d < DEVIATION_10D_UP_THRESHOLD:
        # 下一日若上涨(100-deviation_9d)%就会触发
        needed_increase = DEVIATION_10D_UP_THRESHOLD - deviation_9d
        prediction_reason = f"9日偏离度已达{deviation_9d:.2f}%，下一交易日若涨幅>={needed_increase:.2f}%将触发严重异动"
        days_to_trigger = 1
        abnormal_direction = "上涨"
    elif DEVIATION_10D_DOWN_THRESHOLD < deviation_9d <= threshold_9d_close_down:
        # 下一日若下跌(50+deviation_9d)%就会触发
        needed_decrease = DEVIATION_10D_DOWN_THRESHOLD - deviation_9d
        prediction_reason = f"9日偏离度已达{deviation_9d:.2f}%，下一交易日若跌幅>={abs(needed_decrease):.2f}%将触发严重异动"
        days_to_trigger = 1
        abnormal_direction = "下跌"

    # 3. 较长期30日预测 (第三优先级)
    elif threshold_29d_further_up <= deviation_29d < threshold_29d_close_up:
        days_to_trigger = 2
        prediction_reason = f"29日偏离度已达{deviation_29d:.2f}%，即将临近严重异动阈值"
        abnormal_direction = "上涨"
    elif threshold_29d_close_down < deviation_29d <= threshold_29d_further_down:
        days_to_trigger = 2
        prediction_reason = f"29日偏离度已达{deviation_29d:.2f}%，即将临近严重异动阈值"
        abnormal_direction = "下跌"

    # 4. 较长期10日预测 (第四优先级)
    elif threshold_9d_further_up <= deviation_9d < threshold_9d_close_up:
        days_to_trigger = 2
        prediction_reason = f"9日偏离度已达{deviation_9d:.2f}%，即将临近严重异动阈值"
        abnormal_direction = "上涨"
    elif threshold_9d_close_down < deviation_9d <= threshold_9d_further_down:
        days_to_trigger = 2
        prediction_reason = f"9日偏离度已达{deviation_9d:.2f}%，即将临近严重异动阈值"
        abnormal_direction = "下跌"

    # 如果可能在下一交易日触发严重异动
    if prediction_reason:
        abnormal_stock = SeriousAbnormalStock(stock_code, stock_name, date)
        abnormal_stock.cumulative_deviation_10d = deviation_10d
        abnormal_stock.cumulative_deviation_30d = deviation_30d
        abnormal_stock.abnormal_direction = abnormal_direction
        abnormal_stock.latest_price = stock_data.iloc[date_index]['收盘']
        abnormal_stock.prediction_status = prediction_reason
        abnormal_stock.days_to_trigger = days_to_trigger
        return abnormal_stock

    return None


def get_previous_trading_date(end_date):
    """
    获取end_date的上一个交易日，如果end_date是交易日，则返回自身。
    
    :param end_date: 结束日期，格式为'YYYY-MM-DD'。
    :return: 上一个交易日的日期，格式为'YYYY-MM-DD'。
    """
    # 检查end_date是否为交易日
    if a_trade_calendar.is_trade_date(end_date):
        return end_date

    # 如果end_date不是交易日，则找到end_date之前的最近一个交易日
    date_dt = datetime.strptime(end_date, '%Y-%m-%d')
    previous_date = date_dt - timedelta(days=1)
    while not a_trade_calendar.is_trade_date(previous_date.strftime('%Y-%m-%d')):
        previous_date -= timedelta(days=1)

    return previous_date.strftime('%Y-%m-%d')


def get_next_trading_date(date):
    """
    获取date的下一个交易日。
    
    :param date: 日期，格式为'YYYY-MM-DD'。
    :return: 下一个交易日的日期，格式为'YYYY-MM-DD'。
    """
    date_dt = datetime.strptime(date, '%Y-%m-%d')
    next_date = date_dt + timedelta(days=1)
    while not a_trade_calendar.is_trade_date(next_date.strftime('%Y-%m-%d')):
        next_date += timedelta(days=1)

    return next_date.strftime('%Y-%m-%d')


def write_to_excel(result_list, output_path, date, existing_df=None):
    """
    将结果保存为Excel文件，使用追加模式
    
    :param result_list: 严重异动股票列表
    :param output_path: 输出路径
    :param date: 日期，用于标记数据来源
    :param existing_df: 已存在的DataFrame，如果为None则从文件读取
    """
    # 选择正确的异常波动次数字段
    df_data = []
    for stock in result_list:
        abnormal_count = stock.abnormal_count_10d_up if hasattr(stock,
                                                                'abnormal_direction') and stock.abnormal_direction == "上涨" else \
            stock.abnormal_count_10d_down if hasattr(stock, 'abnormal_direction') else 0

        df_data.append({
            '日期': date,  # 添加日期列
            '股票代码': stock.stock_code,
            '股票名称': stock.stock_name,
            '触发原因': stock.trigger_reason if hasattr(stock,
                                                        'trigger_reason') and stock.trigger_reason != '未知' else stock.prediction_status,
            '10日偏离度(%)': stock.cumulative_deviation_10d,
            '30日偏离度(%)': stock.cumulative_deviation_30d,
            '10日异常波动次数': abnormal_count,
            '异动方向': stock.abnormal_direction,
            '最新价格': stock.latest_price,
            '预计触发天数': stock.days_to_trigger if hasattr(stock, 'days_to_trigger') else 0
        })

    # 创建当前数据的DataFrame
    new_df = pd.DataFrame(df_data)

    try:
        # 尝试读取现有文件或使用传入的DataFrame
        if existing_df is not None:
            # 使用传入的DataFrame
            combined_df = existing_df.copy()
        elif os.path.exists(output_path):
            # 读取现有Excel文件
            combined_df = pd.read_excel(output_path)
        else:
            # 如果文件不存在，直接使用新数据
            combined_df = new_df
            
        # 检查新数据中的日期是否已存在于文件中
        if date in combined_df['日期'].astype(str).values:
            # 删除已存在的同一日期的数据
            combined_df = combined_df[combined_df['日期'].astype(str) != date]

        # 合并现有数据和新数据
        combined_df = pd.concat([combined_df, new_df], ignore_index=True)

        # 按日期降序排序
        combined_df = combined_df.sort_values(by='日期', ascending=False)

        # 创建ExcelWriter对象
        writer = pd.ExcelWriter(output_path, engine='xlsxwriter')

        # 写入合并后的数据
        combined_df.to_excel(writer, index=False, sheet_name='严重异动股票历史')

        # 获取工作簿和工作表对象
        workbook = writer.book
        worksheet = writer.sheets['严重异动股票历史']

        # 定义格式
        already_triggered = workbook.add_format({'bg_color': '#FF6347'})  # 番茄色 - 已触发
        potential_1day = workbook.add_format({'bg_color': '#FFD700'})  # 金色 - 1日内可能触发
        potential_2day = workbook.add_format({'bg_color': '#90EE90'})  # 浅绿色 - 2-3日内可能触发
        up_direction = workbook.add_format({'bg_color': '#FFCCCB'})  # 浅粉色 - 上涨方向
        down_direction = workbook.add_format({'bg_color': '#AFEEEE'})  # 浅青色 - 下跌方向

        # 应用条件格式 - 注意列索引需要考虑新增的日期列
        for row in range(1, len(combined_df) + 1):
            days_to_trigger = combined_df.iloc[row - 1]['预计触发天数']
            direction = combined_df.iloc[row - 1]['异动方向']

            # 触发原因列的条件格式
            if days_to_trigger == 0:  # 已触发
                worksheet.conditional_format(row, 3, row, 3, {'type': 'no_blanks', 'format': already_triggered})
            elif days_to_trigger == 1:  # 1日内可能触发
                worksheet.conditional_format(row, 3, row, 3, {'type': 'no_blanks', 'format': potential_1day})
            elif days_to_trigger <= 3:  # 2-3日内可能触发
                worksheet.conditional_format(row, 3, row, 3, {'type': 'no_blanks', 'format': potential_2day})

            # 异动方向列的条件格式 (索引7对应H列-异动方向)
            if direction == "上涨":
                worksheet.conditional_format(row, 7, row, 7, {'type': 'no_blanks', 'format': up_direction})
            elif direction == "下跌":
                worksheet.conditional_format(row, 7, row, 7, {'type': 'no_blanks', 'format': down_direction})

        # 调整列宽
        worksheet.set_column('A:K', 15)  # 注意调整为11列(A-K)，因为添加了日期列
        worksheet.set_column('D:D', 40)  # 触发原因列宽度加大，索引从A开始，D列是第4列

        # 保存
        writer.close()

        print(f"日期 {date} 的数据已追加保存到Excel文件: {output_path}")

    except Exception as e:
        print(f"保存Excel文件时出错: {e}")
        # 尝试简单的保存方式
        try:
            new_df.to_excel(output_path, index=False)
            print(f"已使用简单模式保存Excel文件: {output_path}")
        except:
            print(f"无法保存Excel文件，请检查文件是否被占用")


def create_debug_stock(stock_code, stock_name, date, stock_data, date_index):
    """
    为必显示列表中的股票创建调试对象
    
    :param stock_code: 股票代码
    :param stock_name: 股票名称
    :param date: 日期
    :param stock_data: 股票历史数据
    :param date_index: 当前日期在数据中的索引
    :return: 调试用的股票对象
    """
    # 提取数据
    end_idx = date_index + 1  # 不含结束索引

    # 确保有足够的历史数据
    if date_index < 31:
        # 取最多可用的数据
        data_30d = stock_data.iloc[max(0, end_idx - 31):end_idx].copy()  # 最多31天数据
        data_10d = stock_data.iloc[max(0, end_idx - 11):end_idx].copy()  # 最多11天数据
        data_9d = stock_data.iloc[max(0, end_idx - 10):end_idx].copy()  # 最多10天数据
        data_29d = stock_data.iloc[max(0, end_idx - 30):end_idx].copy()  # 最多30天数据
    else:
        # 有足够数据时，取完整天数
        data_30d = stock_data.iloc[end_idx - 31:end_idx].copy()  # 31天数据，计算30个间隔
        data_10d = stock_data.iloc[end_idx - 11:end_idx].copy()  # 11天数据，计算10个间隔
        data_9d = stock_data.iloc[end_idx - 10:end_idx].copy()  # 10天数据，计算9个间隔
        data_29d = stock_data.iloc[end_idx - 30:end_idx].copy()  # 30天数据，计算29个间隔

    # 计算偏离度
    deviation_10d = calculate_period_deviation(data_10d)
    deviation_9d = calculate_period_deviation(data_9d)
    deviation_30d = calculate_period_deviation(data_30d)
    deviation_29d = calculate_period_deviation(data_29d)

    # 检查连续10个交易日内的异常波动次数
    # 使用10天的数据来计算异常波动
    abnormal_data = stock_data.iloc[max(0, end_idx - 10):end_idx].copy()
    abnormal_count_up = 0
    abnormal_count_down = 0

    # 滑动窗口检查每个连续3天区间是否存在异常波动
    if len(abnormal_data) >= 3:  # 确保有足够数据进行滑动窗口分析
        for i in range(len(abnormal_data) - 2):
            data_3d = abnormal_data.iloc[i:i + 3]
            is_abnormal, direction = is_abnormal_fluctuation(stock_code, stock_name, data_3d, stock_data, end_idx)

            if is_abnormal:
                if direction == "上涨":
                    abnormal_count_up += 1
                elif direction == "下跌":
                    abnormal_count_down += 1

    # 判断是否是科创板股票
    is_sci_tech_board = stock_code.startswith('688')
    required_count = 3 if is_sci_tech_board else 4  # 科创板3次，主板4次

    # 创建调试股票对象
    debug_msg = (
        f"调试信息: 10日偏离度={deviation_10d:.2f}%, "
        f"9日偏离度={deviation_9d:.2f}%, "
        f"30日偏离度={deviation_30d:.2f}%, "
        f"29日偏离度={deviation_29d:.2f}%, "
        f"上涨异常次数={abnormal_count_up}, "
        f"下跌异常次数={abnormal_count_down}, "
        f"所需异常次数={required_count}"
    )

    abnormal_stock = SeriousAbnormalStock(stock_code, stock_name, date, debug_msg)
    abnormal_stock.cumulative_deviation_10d = deviation_10d
    abnormal_stock.cumulative_deviation_30d = deviation_30d
    abnormal_stock.abnormal_count_10d_up = abnormal_count_up
    abnormal_stock.abnormal_count_10d_down = abnormal_count_down
    abnormal_stock.abnormal_direction = "上涨" if deviation_10d > 0 else "下跌"
    abnormal_stock.latest_price = stock_data.iloc[date_index]['收盘']
    abnormal_stock.is_debug = True

    # 添加预测
    predict_next_deviation(abnormal_stock, deviation_9d, deviation_29d)

    return abnormal_stock


if __name__ == "__main__":
    # 示例用法
    import sys

    if len(sys.argv) > 2:
        # 如果提供了两个参数，视为日期范围
        start_date = sys.argv[1]
        end_date = sys.argv[2]
        find_serious_abnormal_stocks_range(start_date, end_date)
    elif len(sys.argv) > 1:
        # 如果只提供了一个参数，视为单个日期
        date = sys.argv[1]
        find_serious_abnormal_stocks(date)
    else:
        # 如果没有提供参数，使用当前日期
        date = datetime.now().strftime('%Y-%m-%d')
        find_serious_abnormal_stocks(date)
