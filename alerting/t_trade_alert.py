import logging
import signal
import sys
import time as sys_time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import akshare as ak
import pandas as pd
from pytdx.hq import TdxHq_API

from alerting.push.feishu_msg import send_alert
from utils.stock_util import convert_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfig:
    """监控器配置类"""
    HOSTS = [
        ('117.34.114.27', 7709),  # 服务器1
        ('202.96.138.90', 7709)  # 服务器2
    ]

    # 指标参数
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9

    # 信号检测参数
    EXTREME_WINDOW = 120  # 用于判断局部极值的窗口大小
    PRICE_DIFF_THRESHOLD = 0.02  # 价格变动阈值
    MACD_DIFF_THRESHOLD = 0.15  # MACD变动阈值

    # 数据获取参数
    KLINE_CATEGORY = 7  # 1分钟K线
    MAX_HISTORY_BARS = 240  # 240根K线


class TMonitor:
    """做T监控器核心类"""

    def __init__(self, symbol, stop_event, push_msg=False, is_backtest=False, backtest_start=None, backtest_end=None):
        """
        初始化监控器
        :param symbol: 股票代码（如：'000001'）
        """
        self.symbol = symbol
        self.full_symbol = convert_stock_code(self.symbol)
        self.stock_info = self._get_stock_info()
        self.market = self._determine_market()
        self.api = TdxHq_API()
        self.stock_name = self.stock_info.get('股票简称', '未知股票')
        self.stop_event = stop_event  # 线程停止事件
        self.push_msg = push_msg

        # 模式控制
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end

        # 存储已触发的信号时间，避免重复触发
        self.triggered_signals = set()

    def _get_stock_info(self):
        """获取股票基本信息"""
        try:
            df = ak.stock_individual_info_em(symbol=self.symbol)
            return {row['item']: row['value'] for _, row in df.iterrows()}
        except Exception as e:
            print(f"获取{self.symbol}基本信息失败: {str(e)}")
            return {}

    def _determine_market(self):
        """根据股票代码确定市场代码"""
        code_prefix = self.symbol[:1]
        if code_prefix in ['6', '9']:
            return 1  # 沪市
        elif code_prefix in ['0', '3']:
            return 0  # 深市
        raise ValueError(f"无法识别的股票代码: {self.symbol}")

    def _connect_api(self):
        """连接行情服务器"""
        for host, port in TMonitorConfig.HOSTS:
            if self.api.connect(host, port):
                return True
        return False

    def _get_realtime_bars(self):
        """获取实时K线数据"""
        try:
            data = self.api.get_security_bars(
                category=TMonitorConfig.KLINE_CATEGORY,
                market=self.market,
                code=self.symbol,
                start=0,
                count=TMonitorConfig.MAX_HISTORY_BARS
            )
            return self._process_raw_data(data)
        except Exception as e:
            print(f"获取{self.symbol}数据失败: {str(e)}")
            return None

    def _get_historical_data(self, start_time, end_time):
        """
        获取指定时间段的历史1分钟K线数据
        """
        try:
            # 例如：使用 akshare 的股票历史数据接口，注意部分接口可能返回日K线数据
            df = ak.stock_zh_a_minute(symbol=self.full_symbol, period="1", adjust="qfq")
            df['datetime'] = pd.to_datetime(df['day'])
            # 筛选指定时间段数据
            start_dt = pd.to_datetime(start_time)
            end_dt = pd.to_datetime(end_time)
            df = df[(df['datetime'] >= start_dt) & (df['datetime'] <= end_dt)]
            # 确保时间升序排序
            df = df.sort_values(by='datetime').reset_index(drop=True)
            return df
        except Exception as e:
            print(f"获取历史数据失败: {str(e)}")
            return None

    def _process_raw_data(self, raw_data):
        """处理原始K线数据"""
        df = pd.DataFrame(raw_data)
        # 处理时间格式
        df['datetime'] = pd.to_datetime(df['datetime']).dt.strftime('%Y-%m-%d %H:%M:%S')
        return df[['datetime', 'open', 'high', 'low', 'close', 'vol']]

    def _calculate_macd(self, df):
        """计算MACD指标"""
        close = df['close']
        ema12 = close.ewm(span=TMonitorConfig.MACD_FAST, adjust=False).mean()
        ema26 = close.ewm(span=TMonitorConfig.MACD_SLOW, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=TMonitorConfig.MACD_SIGNAL, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif, dea, macd

    def _calculate_macd_slope(self, df, i):
        """
        计算给定时刻MACD的斜率
        :param df: 股票K线数据，包含'MACD'列
        :param i: 当前时刻的索引
        :return: 当前时刻的MACD斜率
        """
        if i == 0:
            return 0  # 斜率无法计算，返回0
        current_slope = df['macd'].iloc[i] - df['macd'].iloc[i - 1]
        if i > 1:
            prev_slope = df['macd'].iloc[i - 1] - df['macd'].iloc[i - 2]
        else:
            prev_slope = 0  # 作为一个初始值
        return current_slope, prev_slope

    def _detect_divergence(self, df):
        """
        模仿人工找背离：
        - 遍历从EXTREME_WINDOW开始的数据，判断当前K线是否为局部极值（峰或谷），
          仅使用过去的数据判断。
        - 如果为局部峰，则将其保存到peaks列表，并与之前所有峰比较，
          若新峰价格明显创新高，但MACD未能同步创新高，则认为出现顶背离信号。
        - 如果为局部谷，则保存到troughs列表，并与之前所有谷比较，
          若新谷价格明显创新低，但MACD未能同步创新低，则认为出现底背离信号。
        """
        window = TMonitorConfig.EXTREME_WINDOW
        peaks = []  # 每个元素格式：{'idx': i, 'price': high, 'macd': macd}
        troughs = []  # 每个元素格式：{'idx': i, 'price': low, 'macd': macd}

        # 从window开始，确保有足够的历史数据用于判断局部极值
        for i in range(window, len(df)):
            start = max(0, i - window + 1)

            # 判断局部峰
            local_max = df['high'].iloc[start:i + 1].max()
            if df['high'].iloc[i] >= local_max:
                new_peak = {
                    'idx': i,
                    'price': df['high'].iloc[i],
                    'macd': df['macd'].iloc[i],
                    'time': df['datetime'].iloc[i]  # 添加时间戳
                }

                # 计算MACD的斜率：当前斜率与前一时刻的斜率进行比较
                current_slope, prev_slope = self._calculate_macd_slope(df, i)

                # 判断MACD是否由上升转为下降
                if prev_slope > current_slope:
                    # 与之前所有局部峰比较顶背离：价格创新高，但MACD未随之上移
                    for p in peaks:
                        if new_peak['price'] > p['price'] * (1 + TMonitorConfig.PRICE_DIFF_THRESHOLD) and \
                                new_peak['macd'] < p['macd'] * (1 - TMonitorConfig.MACD_DIFF_THRESHOLD):
                            price_diff = (new_peak['price'] - p['price']) / p['price']
                            macd_diff = (p['macd'] - new_peak['macd']) / (abs(p['macd']) + 1e-6)

                            # 检查时间点是否已触发过信号
                            if new_peak['time'] not in self.triggered_signals:
                                self._trigger_signal("顶背离SELL", price_diff, macd_diff, new_peak['price'],
                                                     new_peak['time'])
                                self.triggered_signals.add(new_peak['time'])  # 记录时间点
                peaks.append(new_peak)

            # 判断局部谷
            local_min = df['low'].iloc[start:i + 1].min()
            if df['low'].iloc[i] <= local_min:
                new_trough = {
                    'idx': i,
                    'price': df['low'].iloc[i],
                    'macd': df['macd'].iloc[i],
                    'time': df['datetime'].iloc[i]  # 添加时间戳
                }

                # 计算MACD的斜率：当前斜率与前一时刻的斜率进行比较
                current_slope, prev_slope = self._calculate_macd_slope(df, i)

                # 判断MACD是否由下降转为上升
                if prev_slope < current_slope:
                    # 与之前所有局部谷比较底背离：价格创新低，但MACD未随之下移
                    for t in troughs:
                        if new_trough['price'] < t['price'] * (1 - TMonitorConfig.PRICE_DIFF_THRESHOLD) and \
                                new_trough['macd'] > t['macd'] * (1 + TMonitorConfig.MACD_DIFF_THRESHOLD):
                            price_diff = (t['price'] - new_trough['price']) / t['price']
                            macd_diff = (new_trough['macd'] - t['macd']) / (abs(t['macd']) + 1e-6)

                            # 检查时间点是否已触发过信号
                            if new_trough['time'] not in self.triggered_signals:
                                self._trigger_signal("底背离BUY", price_diff, macd_diff, new_trough['price'],
                                                     new_trough['time'])
                                self.triggered_signals.add(new_trough['time'])  # 记录时间点
                troughs.append(new_trough)

    def _trigger_signal(self, signal_type, price_diff, macd_diff, price, signal_time):
        """统一格式化输出信号"""
        msg = f"[{self.stock_name} {self.symbol}] {signal_type}信号！ 价格变动：{price_diff:.2%} MACD变动：{macd_diff:.2%} 现价：{price:.2f} [{signal_time}]"
        logging.warning(msg)
        # 飞书告警
        if self.push_msg is True:
            send_alert(msg)

    def _run_live(self):
        """启动监控（实时模式）"""
        if not self._connect_api():
            print(f"{self.symbol} 连接服务器失败")
            return

        while not self.stop_event.is_set():  # 检查停止标志
            try:
                df = self._get_realtime_bars()
                if df is None or len(df) < TMonitorConfig.EXTREME_WINDOW:
                    sys_time.sleep(60)
                    continue

                # 指标计算
                df['dif'], df['dea'], df['macd'] = self._calculate_macd(df)

                # 检测背离信号（使用全部已闭合K线）
                self._detect_divergence(df)

                # 控制更新频率
                latest_close = df['close'].iloc[-1]
                latest_amount = df['vol'].iloc[-1] * latest_close / 10000
                logging.info(
                    f"[{self.stock_name} {self.symbol}]  最新价:{latest_close:.2f}元, 成交额:{latest_amount:.2f}万元")

                # 等待60s，如果在等待过程中检测到停止标志，则提前返回
                if self.stop_event.wait(timeout=60):
                    break

            except KeyboardInterrupt:
                print(f"{self.symbol} 监控已停止")
                break
            except Exception as e:
                print(f"{self.symbol} 运行异常: {str(e)}")
                sys_time.sleep(30)

        # 退出时关闭连接
        self.api.disconnect()
        logging.info(f"{self.symbol} 监控已安全退出")

    def _run_backtest(self):
        """回测模式：对指定时间段内的历史数据进行模拟遍历"""
        if self.backtest_start is None or self.backtest_end is None:
            print("回测模式下必须指定backtest_start和backtest_end")
            return

        df = self._get_historical_data(self.backtest_start, self.backtest_end)
        if df is None or df.empty:
            print("指定时间段内没有数据")
            return

        # 模拟逐步遍历历史数据，每次用最新的部分数据进行指标计算和信号检测
        # 假设数据已按时间排序
        for current_index in range(TMonitorConfig.EXTREME_WINDOW, len(df)):
            if self.stop_event.is_set():
                break
            # 截取从0到当前时刻的所有数据
            df_current = df.iloc[:current_index + 1].copy()

            # 指标计算
            df_current['dif'], df_current['dea'], df_current['macd'] = self._calculate_macd(df_current)

            # 检测背离信号
            self._detect_divergence(df_current)

            # 模拟实时：打印当前时刻数据
            # latest_close = df_current['close'].iloc[-1]
            # latest_time = df_current['datetime'].iloc[-1]
            # logging.info(f"[回测 {self.stock_name} {self.symbol}] {latest_time}  最新价:{latest_close:.2f}元")

            # 模拟时间步长（例如延时0.1秒）
            sys_time.sleep(0.1)

        logging.info(f"[回测 {self.symbol}] 回测结束")

    def run(self):
        """根据模式开关启动实时监控或回测模式"""
        if self.is_backtest:
            logging.info(
                f"[{self.stock_name} {self.symbol}] 启动回测模式，回测时间段：{self.backtest_start} 至 {self.backtest_end}")
            self._run_backtest()
        else:
            logging.info(f"[{self.stock_name} {self.symbol}] 启动实时监控模式")
            self._run_live()


class MonitorManager:
    """多股票监控管理器"""

    def __init__(self, symbols, is_backtest=False, backtest_start=None, backtest_end=None):
        self.symbols = symbols
        self.stop_event = Event()
        self.executor = ThreadPoolExecutor(max_workers=len(symbols))
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end

        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """处理系统信号"""
        logging.info("接收到终止信号，开始优雅退出...")
        self.stop_event.set()
        self.executor.shutdown(wait=False)
        sys.exit(0)

    def start(self):
        """启动所有监控"""
        futures = []
        for symbol in self.symbols:
            monitor = TMonitor(symbol, self.stop_event,
                               is_backtest=self.is_backtest,
                               backtest_start=self.backtest_start,
                               backtest_end=self.backtest_end)
            futures.append(self.executor.submit(monitor.run))

        try:
            while not self.stop_event.is_set():
                sys_time.sleep(1)
        finally:
            self.executor.shutdown()


if __name__ == "__main__":
    # 示例用法：通过开关控制实时监控还是回测
    IS_BACKTEST = True  # True 表示回测模式，False 表示实时监控

    # 若为回测模式，指定回测起止时间（格式根据实际情况确定）
    backtest_start = "2025-02-06 09:30"
    backtest_end = "2025-02-12 15:00"

    # 监控标的
    symbols = ['000681']  # 监控多只股票

    manager = MonitorManager(symbols,
                             is_backtest=IS_BACKTEST,
                             backtest_start=backtest_start,
                             backtest_end=backtest_end)
    logging.info("启动多股票监控...")
    manager.start()
