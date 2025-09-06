"""
异动检测器 - 用于检测股票的异常波动和严重异常波动

监管规则：
1. 异常波动标准：
   - 连续3个交易日内日收盘价格涨跌幅偏离值累计达到±20%
   - 或连续3个交易日内日均换手率与前5个交易日的日均换手率的比值达到30倍且累计换手率达到20%

2. 严重异常波动标准：
   - 10个交易日内累计偏离值达到100%(-50%)
   - 或30个交易日内累计偏离值达到200%(-70%)

3. 偏离值计算：个股涨幅减去对应市场指数的差值
"""

import os
from datetime import timedelta
from functools import lru_cache

import pandas as pd

from utils.file_util import read_stock_data
from utils.stock_util import get_stock_market, stock_limit_ratio


class AbnormalMovementDetector:
    """异动检测器"""

    def __init__(self):
        """初始化异动检测器"""
        self.index_data_cache = {}
        self.stock_data_cache = {}

        # 指数文件路径
        self.index_files = {
            'main': './data/indexes/sh000001_上证指数.csv',  # 主板使用上证指数
            'gem': './data/indexes/sz399006_创业板指.csv',  # 创业板使用创业板指数
            'star': './data/indexes/sh000688_科创50.csv',  # 科创板使用科创50
            'bse': './data/indexes/bj899050_北证50.csv'  # 北交所使用北证50
        }

        # 预警优先级配置（数值越小优先级越高）
        self.warning_priority = {
            'imminent_severe': 1,  # 即将严重异动
            'severe': 2,  # 严重异动
            'imminent_normal': 3,  # 即将异动
            'normal': 4  # 异动
        }

        # 预加载指数数据
        self._load_index_data()

    def _load_index_data(self):
        """预加载所有指数数据"""
        for market, file_path in self.index_files.items():
            if os.path.exists(file_path):
                try:
                    # 读取指数数据（无表头）
                    df = pd.read_csv(file_path, header=None,
                                     names=['日期', '开盘', '最高', '最低', '收盘', '成交量'])

                    # 转换日期格式
                    df['日期'] = pd.to_datetime(df['日期'])

                    # 计算涨跌幅
                    df['涨跌幅'] = df['收盘'].pct_change() * 100

                    # 按日期排序
                    df = df.sort_values('日期').reset_index(drop=True)

                    self.index_data_cache[market] = df
                    print(f"成功加载{market}指数数据，共{len(df)}条记录")

                except Exception as e:
                    print(f"加载{market}指数数据失败: {e}")
                    self.index_data_cache[market] = pd.DataFrame()
            else:
                print(f"指数文件不存在: {file_path}")
                self.index_data_cache[market] = pd.DataFrame()

    @lru_cache(maxsize=1000)
    def get_stock_data_cached(self, stock_code):
        """缓存股票数据读取"""
        if stock_code not in self.stock_data_cache:
            self.stock_data_cache[stock_code] = read_stock_data(stock_code)
        return self.stock_data_cache[stock_code]

    def get_market_index_data(self, stock_code):
        """根据股票代码获取对应的市场指数数据"""
        try:
            market = get_stock_market(stock_code)
            return self.index_data_cache.get(market, self.index_data_cache.get('main', pd.DataFrame()))
        except Exception as e:
            print(f"获取股票{stock_code}市场类型失败: {e}")
            return self.index_data_cache.get('main', pd.DataFrame())

    def calculate_deviation_values(self, stock_code, end_date, days):
        """
        计算指定天数内的偏离值序列

        Args:
            stock_code: 股票代码
            end_date: 结束日期 (YYYY-MM-DD 或 YYYYMMDD)
            days: 计算天数

        Returns:
            list: 偏离值列表，按时间顺序排列
        """
        try:
            # 获取股票数据
            stock_df = self.get_stock_data_cached(stock_code)
            if stock_df is None or stock_df.empty:
                return []

            # 获取对应指数数据
            index_df = self.get_market_index_data(stock_code)
            if index_df.empty:
                return []

            # 统一日期格式
            if isinstance(end_date, str) and len(end_date) == 8:
                end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            end_date = pd.to_datetime(end_date)

            # 获取指定天数的交易日期
            start_date = end_date - timedelta(days=days * 2)  # 预留足够的天数

            # 筛选日期范围内的数据
            stock_period = stock_df[(stock_df['日期'] >= start_date) & (stock_df['日期'] <= end_date)].copy()
            index_period = index_df[(index_df['日期'] >= start_date) & (index_df['日期'] <= end_date)].copy()

            if stock_period.empty or index_period.empty:
                return []

            # 按日期合并数据
            merged = pd.merge(stock_period[['日期', '涨跌幅']],
                              index_period[['日期', '涨跌幅']],
                              on='日期', suffixes=('_stock', '_index'))

            # 计算偏离值
            merged['偏离值'] = merged['涨跌幅_stock'] - merged['涨跌幅_index']

            # 取最近的days天数据
            deviation_values = merged.tail(days)['偏离值'].tolist()

            return deviation_values

        except Exception as e:
            print(f"计算股票{stock_code}偏离值时出错: {e}")
            return []

    def calculate_cumulative_deviation(self, stock_code, end_date, days):
        """
        计算指定天数内的累计偏离值（使用复合涨跌幅）

        Args:
            stock_code: 股票代码
            end_date: 结束日期 (YYYY-MM-DD 或 YYYYMMDD)
            days: 计算天数

        Returns:
            float: 累计偏离值
        """
        try:
            # 获取股票数据
            stock_df = self.get_stock_data_cached(stock_code)
            if stock_df is None or stock_df.empty:
                return 0.0

            # 获取对应指数数据
            index_df = self.get_market_index_data(stock_code)
            if index_df.empty:
                return 0.0

            # 统一日期格式
            if isinstance(end_date, str) and len(end_date) == 8:
                end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            end_date = pd.to_datetime(end_date)

            # 获取指定天数的交易日期
            start_date = end_date - timedelta(days=days * 2)  # 预留足够的天数

            # 筛选日期范围内的数据
            stock_period = stock_df[(stock_df['日期'] >= start_date) & (stock_df['日期'] <= end_date)].copy()
            index_period = index_df[(index_df['日期'] >= start_date) & (index_df['日期'] <= end_date)].copy()

            if stock_period.empty or index_period.empty:
                return 0.0

            # 按日期合并数据，包含收盘价
            merged = pd.merge(stock_period[['日期', '涨跌幅', '收盘']],
                              index_period[['日期', '涨跌幅', '收盘']],
                              on='日期', suffixes=('_stock', '_index'))

            # 取最近的days天数据
            recent_data = merged.tail(days)

            if len(recent_data) < days:
                # 如果数据不足，降级到每日偏离值累加
                recent_data['偏离值'] = recent_data['涨跌幅_stock'] - recent_data['涨跌幅_index']
                return recent_data['偏离值'].sum()

            # 计算复合涨跌幅
            # 股票复合涨跌幅：从第一天开盘价到最后一天收盘价
            stock_start_price = recent_data['收盘_stock'].iloc[0] / (1 + recent_data['涨跌幅_stock'].iloc[0] / 100)
            stock_end_price = recent_data['收盘_stock'].iloc[-1]
            stock_compound_change = (stock_end_price / stock_start_price - 1) * 100

            # 指数复合涨跌幅
            index_start_price = recent_data['收盘_index'].iloc[0] / (1 + recent_data['涨跌幅_index'].iloc[0] / 100)
            index_end_price = recent_data['收盘_index'].iloc[-1]
            index_compound_change = (index_end_price / index_start_price - 1) * 100

            # 累计偏离值 = 股票复合涨跌幅 - 指数复合涨跌幅
            cumulative_deviation = stock_compound_change - index_compound_change

            return cumulative_deviation

        except Exception as e:
            print(f"计算股票{stock_code}累计偏离值时出错: {e}")
            # 降级到原有方法
            deviation_values = self.calculate_deviation_values(stock_code, end_date, days)
            return sum(deviation_values) if deviation_values else 0.0

    # def calculate_deviation_values_legacy(self, stock_code, end_date, days):
    #     """
    #     原有的偏离值计算方法（每日偏离值累加，未计算复利）
    #     作为备用方法保留
    #     """
    #     try:
    #         # 获取股票数据
    #         stock_df = self.get_stock_data_cached(stock_code)
    #         if stock_df is None or stock_df.empty:
    #             return []
    #
    #         # 获取对应指数数据
    #         index_df = self.get_market_index_data(stock_code)
    #         if index_df.empty:
    #             return []
    #
    #         # 统一日期格式
    #         if isinstance(end_date, str) and len(end_date) == 8:
    #             end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    #         end_date = pd.to_datetime(end_date)
    #
    #         # 获取指定天数的交易日期
    #         start_date = end_date - timedelta(days=days*2)  # 预留足够的天数
    #
    #         # 筛选日期范围内的数据
    #         stock_period = stock_df[(stock_df['日期'] >= start_date) & (stock_df['日期'] <= end_date)].copy()
    #         index_period = index_df[(index_df['日期'] >= start_date) & (index_df['日期'] <= end_date)].copy()
    #
    #         if stock_period.empty or index_period.empty:
    #             return []
    #
    #         # 按日期合并数据
    #         merged = pd.merge(stock_period[['日期', '涨跌幅']],
    #                         index_period[['日期', '涨跌幅']],
    #                         on='日期', suffixes=('_stock', '_index'))
    #
    #         # 计算偏离值
    #         merged['偏离值'] = merged['涨跌幅_stock'] - merged['涨跌幅_index']
    #
    #         # 取最近的days天数据
    #         deviation_values = merged.tail(days)['偏离值'].tolist()
    #
    #         return deviation_values
    #
    #     except Exception as e:
    #         print(f"计算股票{stock_code}偏离值时出错: {e}")
    #         return []

    def calculate_turnover_ratios(self, stock_code, end_date, days):
        """
        计算指定天数内的换手率序列
        
        Args:
            stock_code: 股票代码
            end_date: 结束日期
            days: 计算天数
            
        Returns:
            list: 换手率列表
        """
        try:
            stock_df = self.get_stock_data_cached(stock_code)
            if stock_df is None or stock_df.empty:
                return []

            # 统一日期格式
            if isinstance(end_date, str) and len(end_date) == 8:
                end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            end_date = pd.to_datetime(end_date)

            # 获取指定天数的数据
            start_date = end_date - timedelta(days=days * 2)
            stock_period = stock_df[(stock_df['日期'] >= start_date) & (stock_df['日期'] <= end_date)].copy()

            if stock_period.empty:
                return []

            # 取最近的days天换手率数据
            turnover_ratios = stock_period.tail(days)['换手率'].tolist()

            return turnover_ratios

        except Exception as e:
            print(f"计算股票{stock_code}换手率时出错: {e}")
            return []

    def check_abnormal_movement(self, stock_code, end_date):
        """
        检查是否触发异常波动

        Args:
            stock_code: 股票代码
            end_date: 检查日期

        Returns:
            tuple: (是否触发, 触发类型, 详细信息)
        """
        try:
            # 检查连续3个交易日偏离值累计±20%
            cumulative_deviation = self.calculate_cumulative_deviation(stock_code, end_date, 3)
            if abs(cumulative_deviation) >= 20:
                return True, "偏离值", f"3日累计偏离值{cumulative_deviation:.2f}%"

            # 检查连续3个交易日换手率条件
            turnover_3d = self.calculate_turnover_ratios(stock_code, end_date, 3)
            turnover_5d = self.calculate_turnover_ratios(stock_code, end_date, 8)  # 前5日+当前3日

            if len(turnover_3d) >= 3 and len(turnover_5d) >= 8:
                # 计算前5日平均换手率
                prev_5d_avg = sum(turnover_5d[:5]) / 5 if len(turnover_5d) >= 8 else 0
                # 计算当前3日平均换手率
                current_3d_avg = sum(turnover_3d) / 3
                # 计算当前3日累计换手率
                current_3d_cumulative = sum(turnover_3d)

                if prev_5d_avg > 0:
                    ratio = current_3d_avg / prev_5d_avg
                    if ratio >= 30 and current_3d_cumulative >= 20:
                        return True, "换手率", f"3日换手率比值{ratio:.1f}倍，累计{current_3d_cumulative:.2f}%"

            return False, "", ""

        except Exception as e:
            print(f"检查股票{stock_code}异常波动时出错: {e}")
            return False, "", ""

    def check_severe_abnormal_movement(self, stock_code, end_date):
        """
        检查是否触发严重异常波动

        Args:
            stock_code: 股票代码
            end_date: 检查日期

        Returns:
            tuple: (是否触发, 触发类型, 详细信息)
        """
        try:
            # 首先检查基于绝对涨跌幅的严重异动（新增）
            from analysis.ladder_chart import calculate_stock_period_change
            from utils.date_util import get_n_trading_days_before

            # 检查10日绝对涨跌幅是否超过100%
            try:
                end_date_str = end_date if isinstance(end_date, str) else end_date.strftime('%Y%m%d')
                start_date_10d = get_n_trading_days_before(end_date_str, 10)
                if '-' in start_date_10d:
                    start_date_10d = start_date_10d.replace('-', '')

                period_change_10d = calculate_stock_period_change(stock_code, start_date_10d, end_date_str)
                if period_change_10d is not None:
                    if period_change_10d >= 100:
                        return True, "10日绝对涨幅", f"10日涨幅{period_change_10d:.2f}%"
                    elif period_change_10d <= -50:
                        return True, "10日绝对跌幅", f"10日跌幅{period_change_10d:.2f}%"
            except Exception:
                pass  # 如果计算失败，继续使用偏离值检查

            # 检查30日绝对涨跌幅是否超过150%（调整阈值，比偏离值更宽松）
            try:
                start_date_30d = get_n_trading_days_before(end_date_str, 30)
                if '-' in start_date_30d:
                    start_date_30d = start_date_30d.replace('-', '')

                period_change_30d = calculate_stock_period_change(stock_code, start_date_30d, end_date_str)
                if period_change_30d is not None:
                    if period_change_30d >= 150:
                        return True, "30日绝对涨幅", f"30日涨幅{period_change_30d:.2f}%"
                    elif period_change_30d <= -60:
                        return True, "30日绝对跌幅", f"30日跌幅{period_change_30d:.2f}%"
            except Exception:
                pass  # 如果计算失败，继续使用偏离值检查

            # 修正后的偏离值检查逻辑（使用复合涨跌幅）
            # 检查10个交易日内累计偏离值100%(-50%)
            cumulative_deviation_10d = self.calculate_cumulative_deviation(stock_code, end_date, 10)
            if cumulative_deviation_10d >= 100 or cumulative_deviation_10d <= -50:
                return True, "10日偏离值", f"10日累计偏离值{cumulative_deviation_10d:.2f}%"

            # 检查30个交易日内累计偏离值200%(-70%)
            cumulative_deviation_30d = self.calculate_cumulative_deviation(stock_code, end_date, 30)
            if cumulative_deviation_30d >= 200 or cumulative_deviation_30d <= -70:
                return True, "30日偏离值", f"30日累计偏离值{cumulative_deviation_30d:.2f}%"

            return False, "", ""

        except Exception as e:
            print(f"检查股票{stock_code}严重异常波动时出错: {e}")
            return False, "", ""

    def should_skip_detection(self, stock_code, period_data=None):
        """
        快速筛选：判断是否可以跳过异动检测

        Args:
            stock_code: 股票代码
            period_data: 已有的周期涨幅数据，格式如 {'5d': 0.05, '10d': 0.08, '30d': 0.15}

        Returns:
            bool: True表示可以跳过检测，False表示需要检测
        """
        try:
            # 获取股票的涨跌幅限制
            limit_ratio = stock_limit_ratio(stock_code.split('.')[0])  # 去掉后缀

            # 如果有周期数据，进行快速判断
            if period_data:
                # 检查各周期涨幅是否远小于可能触发异动的阈值

                # 对于3日异动（±20%），如果近期涨幅很小，可能不会触发
                # 考虑到偏离值是相对于指数的，我们设置一个保守的阈值
                if '5d' in period_data:
                    recent_gain = abs(period_data['5d'])
                    # 如果5日涨幅小于5%，且小于单日涨跌停的一半，很可能不会触发异动
                    if recent_gain < 0.05 and recent_gain < limit_ratio * 0.5:
                        return True

                # 对于10日严重异动（100%/-50%），如果10日涨幅很小，可以跳过
                if '10d' in period_data:
                    gain_10d = period_data['10d']
                    # 如果10日涨幅小于20%，且为正值小于30%，很可能不会触发严重异动
                    if gain_10d < 0.2 and gain_10d > -0.1:
                        # 同时检查30日数据
                        if '30d' in period_data:
                            gain_30d = period_data['30d']
                            # 如果30日涨幅也小于50%，且为正值小于80%，可以跳过
                            if gain_30d < 0.5 and gain_30d > -0.2:
                                return True

            return False  # 默认不跳过，进行完整检测

        except Exception as e:
            # 如果出错，保守起见不跳过检测
            return False

    def get_warning_message(self, stock_code, end_date, period_data=None):
        """
        获取预警信息

        Args:
            stock_code: 股票代码
            end_date: 检查日期
            period_data: 已有的周期涨幅数据，用于快速筛选

        Returns:
            str: 预警信息字符串
        """
        try:
            # 快速筛选：如果可以跳过检测，直接返回空字符串
            if self.should_skip_detection(stock_code, period_data):
                return ""

            # 收集所有可能的预警信息，按优先级排序
            warnings = []

            # 1. 检查即将触发严重异动预警（最高优先级）
            # 检查10日偏离值预警（严重异动）
            current_cumulative_10d = self.calculate_cumulative_deviation(stock_code, end_date, 10)
            if current_cumulative_10d >= 0:
                remaining_for_severe = 100 - current_cumulative_10d
                if remaining_for_severe > 0 and remaining_for_severe <= 30:
                    warnings.append((self.warning_priority['imminent_severe'],
                                     f"上涨{remaining_for_severe:.1f}%将触发严重异动(10日+100%)"))
            else:
                remaining_for_severe = abs(-50 - current_cumulative_10d)
                if remaining_for_severe <= 20:
                    warnings.append((self.warning_priority['imminent_severe'],
                                     f"下跌{remaining_for_severe:.1f}%将触发严重异动(10日-50%)"))

            # 检查30日偏离值预警（严重异动）
            current_cumulative_30d = self.calculate_cumulative_deviation(stock_code, end_date, 30)
            if current_cumulative_30d >= 0:
                remaining_for_severe = 200 - current_cumulative_30d
                if remaining_for_severe > 0 and remaining_for_severe <= 50:
                    warnings.append((self.warning_priority['imminent_severe'],
                                     f"上涨{remaining_for_severe:.1f}%将触发严重异动(30日+200%)"))
            else:
                remaining_for_severe = abs(-70 - current_cumulative_30d)
                if remaining_for_severe <= 30:
                    warnings.append((self.warning_priority['imminent_severe'],
                                     f"下跌{remaining_for_severe:.1f}%将触发严重异动(30日-70%)"))

            # 2. 检查已触发严重异动（第二优先级）
            is_severe, severe_type, severe_detail = self.check_severe_abnormal_movement(stock_code, end_date)
            if is_severe:
                warnings.append((self.warning_priority['severe'],
                                 f"已触发严重异常波动({severe_type}): {severe_detail}"))

            # 3. 检查即将触发普通异动预警（第三优先级）
            current_cumulative = self.calculate_cumulative_deviation(stock_code, end_date, 3)
            remaining_for_abnormal = 20 - abs(current_cumulative)
            if remaining_for_abnormal > 0 and remaining_for_abnormal <= 15:  # 距离触发较近时才预警
                direction = "上涨" if current_cumulative >= 0 else "下跌"
                warnings.append((self.warning_priority['imminent_normal'],
                                 f"{direction}{remaining_for_abnormal:.1f}%将触发异常波动(3日±20%)"))

            # 4. 检查已触发普通异动（最低优先级）
            is_abnormal, abnormal_type, abnormal_detail = self.check_abnormal_movement(stock_code, end_date)
            if is_abnormal:
                warnings.append((self.warning_priority['normal'],
                                 f"已触发异常波动({abnormal_type}): {abnormal_detail}"))

            # 按优先级排序并返回最高优先级的预警
            if warnings:
                warnings.sort(key=lambda x: x[0])  # 按优先级数值排序（越小优先级越高）
                return warnings[0][1]  # 返回最高优先级的预警信息

            return ""  # 无预警

        except Exception as e:
            print(f"获取股票{stock_code}预警信息时出错: {e}")
            return ""

    def analyze_stock(self, stock_code, end_date):
        """
        综合分析股票的异动情况

        Args:
            stock_code: 股票代码
            end_date: 分析日期

        Returns:
            dict: 分析结果
        """
        result = {
            'stock_code': stock_code,
            'end_date': end_date,
            'is_abnormal': False,
            'is_severe': False,
            'warning_message': '',
            'details': {}
        }

        try:
            # 检查异常波动
            is_abnormal, abnormal_type, abnormal_detail = self.check_abnormal_movement(stock_code, end_date)
            result['is_abnormal'] = is_abnormal
            if is_abnormal:
                result['details']['abnormal'] = {'type': abnormal_type, 'detail': abnormal_detail}

            # 检查严重异常波动
            is_severe, severe_type, severe_detail = self.check_severe_abnormal_movement(stock_code, end_date)
            result['is_severe'] = is_severe
            if is_severe:
                result['details']['severe'] = {'type': severe_type, 'detail': severe_detail}

            # 获取预警信息
            result['warning_message'] = self.get_warning_message(stock_code, end_date)

            return result

        except Exception as e:
            print(f"分析股票{stock_code}时出错: {e}")
            result['warning_message'] = "分析出错"
            return result
