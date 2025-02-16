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
    EXTREME_WINDOW = 20  # 窗口大小
    PRICE_DIFF_THRESHOLD = 0.02  # 价格最小变动幅度（2%）
    MACD_DIFF_THRESHOLD = 0.15  # MACD最小变动幅度（15%）

    # 数据获取参数
    KLINE_CATEGORY = 7  # 1分钟K线
    MAX_HISTORY_BARS = 240  # 240根1分钟K线


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
            return df.reset_index(drop=True)
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

    def _find_extremes(self, df):
        """寻找局部极值点"""
        window = TMonitorConfig.EXTREME_WINDOW
        high_indices = []
        low_indices = []

        for i in range(window, len(df)):
            # 价格极值
            high_window = df['high'].iloc[i - window:i]
            low_window = df['low'].iloc[i - window:i]

            # MACD极值
            macd_window = df['macd'].iloc[i - window:i]

            # 综合极值判断
            price_high_idx = high_window.idxmax()
            price_low_idx = low_window.idxmin()
            macd_high_idx = macd_window.idxmax()
            macd_low_idx = macd_window.idxmin()

            high_indices.append((price_high_idx, macd_high_idx))
            low_indices.append((price_low_idx, macd_low_idx))

        return high_indices[-2:], low_indices[-2:]

    def _find_extremes_improved(self, df, order=5, tolerance=2):
        """
        改进的极值点检测：
        - 仅使用当前及过去的K线（order+1根）判断局部极值，避免未来数据。
        - 在匹配价格极值和MACD极值时，允许一个时间（索引）容差 tolerance。

        参数：
          - order: 计算局部极值时，使用过去 `order` 根K线进行比较。
          - tolerance: 价格极值和 MACD 极值之间允许的最大周期差。
        参数取值建议：
          - 震荡或盘整突破：order 5~7, tolerance 1~2
          - 单边趋势型走势：order 8~10, tolerance 2~3
          - 低波动市场：order 3~5, tolerance 1
        返回：
          - high_pairs: 最近两组匹配的顶部极值对 [(price_index, macd_index), ...]
          - low_pairs: 最近两组匹配的底部极值对 [(price_index, macd_index), ...]
        """
        # 仅使用必要的数据列
        if 'high' not in df.columns or 'low' not in df.columns or 'macd' not in df.columns:
            return [], []

        # 仅利用过去数据：对于每个当前点i，只看其前order根K线加上当前点，共order+1根数据
        price_high_indices = [
            i for i in range(order, len(df))
            if df['high'].iloc[i] == max(df['high'].iloc[i - order:i + 1])
        ]
        price_low_indices = [
            i for i in range(order, len(df))
            if df['low'].iloc[i] == min(df['low'].iloc[i - order:i + 1])
        ]
        macd_high_indices = [
            i for i in range(order, len(df))
            if df['macd'].iloc[i] == max(df['macd'].iloc[i - order:i + 1])
        ]
        macd_low_indices = [
            i for i in range(order, len(df))
            if df['macd'].iloc[i] == min(df['macd'].iloc[i - order:i + 1])
        ]

        # 根据容差将价格极值与MACD极值匹配
        high_pairs = []
        for ph in price_high_indices:
            possible_macd = [mh for mh in macd_high_indices if abs(mh - ph) <= tolerance]
            if possible_macd:
                mh = min(possible_macd, key=lambda x: abs(x - ph))
                high_pairs.append((ph, mh))

        low_pairs = []
        for pl in price_low_indices:
            possible_macd = [ml for ml in macd_low_indices if abs(ml - pl) <= tolerance]
            if possible_macd:
                ml = min(possible_macd, key=lambda x: abs(x - pl))
                low_pairs.append((pl, ml))

        # 只保留最近两个匹配点
        high_pairs = high_pairs[-2:] if len(high_pairs) >= 2 else high_pairs
        low_pairs = low_pairs[-2:] if len(low_pairs) >= 2 else low_pairs

        return high_pairs, low_pairs

    def _check_divergence(self, high_pairs, low_pairs, df):
        """检测背离信号"""
        # 顶背离检测
        if len(high_pairs) >= 2:
            (ph1, mh1), (ph2, mh2) = high_pairs[-2], high_pairs[-1]
            price_diff = (df['high'].iloc[ph2] - df['high'].iloc[ph1]) / df['high'].iloc[ph1]
            base_macd = abs(df['macd'].iloc[mh1])
            macd_diff = (df['macd'].iloc[mh1] - df['macd'].iloc[mh2]) / max(base_macd, 1e-6)  # 避免除0

            if price_diff > TMonitorConfig.PRICE_DIFF_THRESHOLD and \
                    macd_diff > TMonitorConfig.MACD_DIFF_THRESHOLD:
                self._print_signal("顶背离卖出", price_diff, macd_diff)

        # 底背离检测
        if len(low_pairs) >= 2:
            (pl1, ml1), (pl2, ml2) = low_pairs[-2], low_pairs[-1]
            price_diff = (df['low'].iloc[pl1] - df['low'].iloc[pl2]) / df['low'].iloc[pl1]
            base_macd = abs(df['macd'].iloc[ml1])
            macd_diff = (df['macd'].iloc[ml2] - df['macd'].iloc[ml1]) / max(base_macd, 1e-6)  # 避免除0

            if price_diff > TMonitorConfig.PRICE_DIFF_THRESHOLD and \
                    macd_diff > TMonitorConfig.MACD_DIFF_THRESHOLD:
                self._print_signal("底背离买入", price_diff, macd_diff)

    def _print_signal(self, signal_type, price_diff, macd_diff):
        """统一格式化输出信号"""
        msg = f"[{self.stock_name} {self.symbol}] {signal_type}信号！ 价格变动：{price_diff:.2%} MACD变动：{macd_diff:.2%}"
        logging.warning(msg)
        # 飞书告警
        if self.push_msg is True:
            send_alert(msg)

    def _run_live(self):
        """启动监控"""
        if not self._connect_api():
            print(f"{self.symbol} 连接服务器失败")
            return

        order = 7
        tolerance = 2
        min_bars_required = max(TMonitorConfig.EXTREME_WINDOW, 2 * order)  # 需要一定的历史数据才能计算macd
        while not self.stop_event.is_set():  # 检查停止标志
            try:
                df = self._get_realtime_bars()
                if df is None or len(df) < min_bars_required:
                    sys_time.sleep(60)
                    continue

                # 指标计算
                df['dif'], df['dea'], df['macd'] = self._calculate_macd(df)

                # 信号检测
                # high_pairs, low_pairs = self._find_extremes(df)
                high_pairs, low_pairs = self._find_extremes_improved(df, order, tolerance)
                self._check_divergence(high_pairs, low_pairs, df)

                # 控制更新频率
                latest_close = df['close'].iloc[-1]
                latest_amount = df['vol'].iloc[-1] * latest_close / 10000
                logging.info(
                    f"[{self.stock_name} {self.symbol}]  最新价:{latest_close:.2f}元, 成交额:{latest_amount:.2f}万元")

                # 等待60s，如果在等待过程中检测到停止标志，则提前返回True
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
        order = 5
        tolerance = 3
        min_bars_required = max(TMonitorConfig.EXTREME_WINDOW, 2 * order)  # 需要一定的历史数据才能计算macd
        # 假设数据已按时间排序
        for current_index in range(min_bars_required, len(df)):
            if self.stop_event.is_set():
                break
            # 取从0到当前时间点的所有数据
            df_current = df.iloc[:current_index + 1].copy()

            # 指标计算
            df_current['dif'], df_current['dea'], df_current['macd'] = self._calculate_macd(df_current)

            # 信号检测
            high_pairs, low_pairs = self._find_extremes_improved(df_current, order, tolerance)
            self._check_divergence(high_pairs, low_pairs, df_current)

            # 模拟实时：打印当前时刻数据
            latest_close = df_current['close'].iloc[-1]
            latest_time = df_current['datetime'].iloc[-1]
            logging.info(f"[回测 {self.stock_name} {self.symbol}] {latest_time}  最新价:{latest_close:.2f}元")

            # 模拟时间步长，可根据需求设定（例如延时0.1秒或不延时）
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
    IS_BACKTEST = False  # True 表示回测模式，False 表示实时监控

    # 若为回测模式，指定回测起止时间（格式根据实际情况确定）
    backtest_start = "2025-02-06 09:30"
    backtest_end = "2025-02-07 15:00"

    # 监控标的
    symbols = ['000681']  # 监控多只股票

    manager = MonitorManager(symbols,
                             is_backtest=IS_BACKTEST,

                             backtest_start=backtest_start,
                             backtest_end=backtest_end)
    logging.info("启动多股票监控...")
    manager.start()
