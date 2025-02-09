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
    EXTREME_WINDOW = 30  # 窗口大小
    PRICE_DIFF_THRESHOLD = 0.02  # 价格最小变动幅度（2%）
    MACD_DIFF_THRESHOLD = 0.15  # MACD最小变动幅度（15%）

    # 数据获取参数
    KLINE_CATEGORY = 7  # 1分钟K线
    MAX_HISTORY_BARS = 240  # 240根1分钟K线


class TMonitor:
    """做T监控器核心类"""

    def __init__(self, symbol, stop_event, push_msg=True):
        """
        初始化监控器
        :param symbol: 股票代码（如：'000001'）
        """
        self.symbol = symbol
        self.stock_info = self._get_stock_info()
        self.market = self._determine_market()
        self.api = TdxHq_API()
        self.stock_name = self.stock_info.get('股票简称', '未知股票')
        self.stop_event = stop_event  # 线程停止事件
        self.push_msg = push_msg

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

    def _process_raw_data(self, raw_data):
        """处理原始K线数据"""
        df = pd.DataFrame(raw_data)
        # 处理时间格式
        df['datetime'] = pd.to_datetime(
            df['year'].astype(str) + '-' +
            df['month'].astype(str).str.zfill(2) + '-' +
            df['day'].astype(str).str.zfill(2) + ' ' +
            df['hour'].astype(str).str.zfill(2) + ':' +
            df['minute'].astype(str).str.zfill(2)
        )
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

    def _check_divergence(self, high_pairs, low_pairs, df):
        """检测背离信号"""
        # 顶背离检测
        if len(high_pairs) >= 2:
            (ph1, mh1), (ph2, mh2) = high_pairs[-2], high_pairs[-1]
            price_diff = (df['high'].iloc[ph2] - df['high'].iloc[ph1]) / df['high'].iloc[ph1]
            macd_diff = (df['macd'].iloc[mh1] - df['macd'].iloc[mh2]) / abs(df['macd'].iloc[mh1])

            if price_diff > TMonitorConfig.PRICE_DIFF_THRESHOLD and \
                    macd_diff > TMonitorConfig.MACD_DIFF_THRESHOLD:
                self._print_signal("顶背离卖出", price_diff, macd_diff)

        # 底背离检测
        if len(low_pairs) >= 2:
            (pl1, ml1), (pl2, ml2) = low_pairs[-2], low_pairs[-1]
            price_diff = (df['low'].iloc[pl1] - df['low'].iloc[pl2]) / df['low'].iloc[pl1]
            macd_diff = (df['macd'].iloc[ml2] - df['macd'].iloc[ml1]) / abs(df['macd'].iloc[ml1])

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

    def run(self):
        """启动监控"""
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

                # 信号检测
                high_pairs, low_pairs = self._find_extremes(df)
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


class MonitorManager:
    """多股票监控管理器"""

    def __init__(self, symbols):
        self.symbols = symbols
        self.stop_event = Event()
        self.executor = ThreadPoolExecutor(max_workers=len(symbols))

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
            monitor = TMonitor(symbol, self.stop_event)
            futures.append(self.executor.submit(monitor.run))

        try:
            while not self.stop_event.is_set():
                sys_time.sleep(1)
        finally:
            self.executor.shutdown()


if __name__ == "__main__":
    # 示例用法
    symbols = ['000001', '600519', '300750']  # 监控多只股票

    manager = MonitorManager(symbols)
    logging.info("启动多股票监控...")
    manager.start()
