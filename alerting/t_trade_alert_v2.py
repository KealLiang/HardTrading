import logging
import signal
import sys
import time as sys_time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import akshare as ak
import pandas as pd
import winsound
from pytdx.hq import TdxHq_API
from tqdm import tqdm

# 兼容从项目根目录或 alerting 目录运行
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from alerting.push.feishu_msg import send_alert
from utils.stock_util import convert_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfigV2:
    HOSTS = [
        ('117.34.114.27', 7709),
        ('202.96.138.90', 7709),
    ]
    # MACD
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    # KDJ
    KDJ_N = 9
    KDJ_K = 3
    KDJ_D = 3
    KD_HIGH = 80
    KD_LOW = 20
    KD_CROSS_LOOKBACK = 3
    # 信号对齐容忍（单位：根K线）。允许 KDJ 与 MACD 背离在 ±N 根内完成配对
    ALIGN_TOLERANCE = 2
    # 峰/谷配对的最大回溯峰数量（仅在最近 M 个局部峰/谷内寻找参照）
    MAX_PEAK_LOOKBACK = 60

    # 极值与数据窗口
    EXTREME_WINDOW = 120
    MAX_HISTORY_BARS = 360
    KLINE_CATEGORY = 7  # 1m

    # 背离阈值
    PRICE_DIFF_BUY_THR = 0.02
    PRICE_DIFF_SELL_THR = 0.02
    MACD_DIFF_THR = 0.15

    # 防重复
    REPEAT_PRICE_CHANGE = 0.05

    # 诊断日志（按需开启）
    DIAG = False  # 打开后会输出调试信息
    # 关注的时间点
    DIAG_TICKS: set[str] = {"2025-08-28 09:33:00", "2025-08-28 09:44:00"}


def is_duplicated(new_node, triggered_signals):
    new_price = new_node['price']
    new_time = new_node['time']
    new_day = new_time.date() if hasattr(new_time, 'date') else None
    for s in triggered_signals:
        sp = s['price']
        st = s['time']
        sday = st.date() if hasattr(st, 'date') else None
        if (new_price == sp and new_day == sday) or (new_time == st):
            return True
    return False


class TMonitorV2:
    def __init__(self, symbol, stop_event, push_msg=True, is_backtest=False, backtest_start=None, backtest_end=None):
        self.symbol = symbol
        self.full_symbol = convert_stock_code(self.symbol)
        self.api = TdxHq_API()
        self.market = self._determine_market()
        self.stock_name = self._get_stock_name()
        self.stop_event = stop_event
        self.push_msg = push_msg
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end

        self.triggered_buy_signals = []
        self.triggered_sell_signals = []
        self.last_signal_price = {'BUY': None, 'SELL': None}
        # 待确认队列（用于容忍 KDJ 与 MACD 背离的先后顺序差异）
        self.pending_sell = []  # [{'node': new_peak, 'deadline_idx': i+tol, 'price_diff':..., 'macd_diff':...}, ...]
        self.pending_buy = []   # 同上

    def _get_stock_name(self):
        try:
            df = ak.stock_individual_info_em(symbol=self.symbol)
            m = {row['item']: row['value'] for _, row in df.iterrows()}
            return m.get('股票简称', self.symbol)
        except Exception:
            return self.symbol

    def _determine_market(self):
        p = self.symbol[:1]
        if p in ['6', '9']:
            return 1
        if p in ['0', '3']:
            return 0
        raise ValueError(f"无法识别的股票代码: {self.symbol}")

    def _connect_api(self):
        for host, port in TMonitorConfigV2.HOSTS:
            if self.api.connect(host, port):
                return True
        return False

    def _get_realtime_bars(self):
        try:
            data = self.api.get_security_bars(
                category=TMonitorConfigV2.KLINE_CATEGORY,
                market=self.market,
                code=self.symbol,
                start=0,
                count=TMonitorConfigV2.MAX_HISTORY_BARS,
            )
            return self._process_raw_data(data)
        except Exception as e:
            logging.error(f"获取{self.symbol}数据失败: {e}")
            return None

    def _get_historical_data(self, start_time, end_time):
        try:
            df = ak.stock_zh_a_minute(symbol=self.full_symbol, period="1", adjust="qfq")
            df['datetime'] = pd.to_datetime(df['day'])
            start_dt = pd.to_datetime(start_time)
            end_dt = pd.to_datetime(end_time)
            df = df[(df['datetime'] >= start_dt) & (df['datetime'] <= end_dt)].copy()
            df = df.sort_values(by='datetime').reset_index(drop=True)
            df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'vol'}, inplace=True)
            return df[['datetime', 'open', 'high', 'low', 'close']]
        except Exception as e:
            logging.error(f"获取历史数据失败: {e}")
            return None

    @staticmethod
    def _process_raw_data(raw_data):
        df = pd.DataFrame(raw_data)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df[['datetime', 'open', 'high', 'low', 'close']]

    @staticmethod
    def _calc_macd(df):
        close = df['close']
        ema12 = close.ewm(span=TMonitorConfigV2.MACD_FAST, adjust=False).mean()
        ema26 = close.ewm(span=TMonitorConfigV2.MACD_SLOW, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=TMonitorConfigV2.MACD_SIGNAL, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif, dea, macd

    @staticmethod
    def _calc_kdj(df):
        n = TMonitorConfigV2.KDJ_N
        low_n = df['low'].rolling(window=n, min_periods=1).min()
        high_n = df['high'].rolling(window=n, min_periods=1).max()
        import numpy as np
        denom = (high_n - low_n).astype(float)
        denom = denom.replace(0.0, np.nan)
        rsv = ((df['close'].astype(float) - low_n.astype(float)) / denom) * 100.0
        rsv = rsv.fillna(0.0).astype(float)
        # 使用EMA近似 K/D 平滑（alpha=1/3）
        k = rsv.ewm(alpha=1/3, adjust=False).mean()
        d = k.ewm(alpha=1/3, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j

    @staticmethod
    def _is_local_peak(df, i, window):
        # 优先使用预计算的滚动最大，避免每步切片 max 的高开销
        if '_rh' in df.columns:
            return df['high'].iloc[i] >= df['_rh'].iloc[i]
        start = max(0, i - window + 1)
        return df['high'].iloc[i] >= df['high'].iloc[start:i + 1].max()

    @staticmethod
    def _is_local_trough(df, i, window):
        if '_rl' in df.columns:
            return df['low'].iloc[i] <= df['_rl'].iloc[i]
        start = max(0, i - window + 1)
        return df['low'].iloc[i] <= df['low'].iloc[start:i + 1].min()

    @staticmethod
    def _has_dead_cross_recent(k, d, i, lookback):
        start = max(1, i - lookback + 1)
        for t in range(start, i + 1):
            if t - 1 >= 0 and k.iloc[t - 1] >= d.iloc[t - 1] and k.iloc[t] < d.iloc[t]:
                return True
        return False

    @staticmethod
    def _has_golden_cross_recent(k, d, i, lookback):
        start = max(1, i - lookback + 1)
        for t in range(start, i + 1):
            if t - 1 >= 0 and k.iloc[t - 1] <= d.iloc[t - 1] and k.iloc[t] > d.iloc[t]:
                return True
        return False

    def _confirm_top_by_kdj(self, df, i):
        # 允许在最近 ALIGN_TOLERANCE 根内存在顶部确认（仅回溯，不前瞻）
        lookback = TMonitorConfigV2.ALIGN_TOLERANCE
        start = max(0, i - lookback)
        for t in range(start, i + 1):
            k, d, j = df['k'], df['d'], df['j']
            if k.iloc[t] > TMonitorConfigV2.KD_HIGH and d.iloc[t] > TMonitorConfigV2.KD_HIGH:
                if self._has_dead_cross_recent(k, d, t, TMonitorConfigV2.KD_CROSS_LOOKBACK):
                    return True
                if t >= 1 and j.iloc[t] < j.iloc[t - 1]:
                    return True
        return False

    def _confirm_bottom_by_kdj(self, df, i):
        lookback = TMonitorConfigV2.ALIGN_TOLERANCE
        start = max(0, i - lookback)
        for t in range(start, i + 1):
            k, d, j = df['k'], df['d'], df['j']
            if k.iloc[t] < TMonitorConfigV2.KD_LOW and d.iloc[t] < TMonitorConfigV2.KD_LOW:
                if self._has_golden_cross_recent(k, d, t, TMonitorConfigV2.KD_CROSS_LOOKBACK):
                    return True
                if t >= 1 and j.iloc[t] > j.iloc[t - 1]:
                    return True
    def _enqueue_pending(self, side, node, i, price_diff, macd_diff):
        tol = TMonitorConfigV2.ALIGN_TOLERANCE
        try:
            import pandas as _pd
            deadline_ts = node['time'] + _pd.Timedelta(minutes=tol)
        except Exception:
            deadline_ts = node['time']
        item = {'node': node, 'deadline_ts': deadline_ts, 'price_diff': price_diff, 'macd_diff': macd_diff}
        if side == 'SELL':
            self.pending_sell.append(item)
        else:
            self.pending_buy.append(item)

    def _flush_pending(self, df, i):
        # 如果当前K满足KDJ确认，就匹配相应 pending，触发信号（防重复与价格偏移检查仍然适用）
        # 同时清理过期 pending（超过 deadline_idx 未等到确认则丢弃）
        def _consume(queue, side, confirm_fn):
            keep = []
            for it in queue:
                node = it['node']
                # 时间方向与窗口：只允许 MACD→KDJ 的前向确认，并限定在 ALIGN_TOLERANCE 分钟内
                ts_confirm = df['datetime'].iloc[i]
                try:
                    bar_diff = int(round((ts_confirm - node['time']).total_seconds() / 60))
                except Exception:
                    bar_diff = 0
                if bar_diff < 0:
                    # KDJ 尚未出现，保留等待
                    keep.append(it)
                    continue
                if bar_diff > TMonitorConfigV2.ALIGN_TOLERANCE:
                    # 超窗过期，丢弃
                    continue
                if confirm_fn(df, i):
                    if side == 'SELL':
                        if not is_duplicated(node, self.triggered_sell_signals):
                            lastp = self.last_signal_price.get('SELL')
                            if lastp is None or abs(node['price'] - lastp) / lastp >= TMonitorConfigV2.REPEAT_PRICE_CHANGE:
                                extra = None
                                if TMonitorConfigV2.DIAG:
                                    extra = f"path=pending MACD@{node['time']} KDJ@{ts_confirm} lag={bar_diff}"
                                self._trigger_signal('SELL', it['price_diff'], it['macd_diff'], node['price'], ts_confirm, extra)
                                self.triggered_sell_signals.append(node)
                    else:
                        if not is_duplicated(node, self.triggered_buy_signals):
                            lastp = self.last_signal_price.get('BUY')
                            if lastp is None or abs(node['price'] - lastp) / lastp >= TMonitorConfigV2.REPEAT_PRICE_CHANGE:
                                extra = None
                                if TMonitorConfigV2.DIAG:
                                    extra = f"path=pending MACD@{node['time']} KDJ@{ts_confirm} lag={bar_diff}"
                                self._trigger_signal('BUY', it['price_diff'], it['macd_diff'], node['price'], ts_confirm, extra)
                                self.triggered_buy_signals.append(node)
                else:
                    keep.append(it)
            return keep

        self.pending_sell = _consume(self.pending_sell, 'SELL', self._confirm_top_by_kdj)
        self.pending_buy = _consume(self.pending_buy, 'BUY', self._confirm_bottom_by_kdj)

    def _trigger_signal(self, side, price_diff, macd_diff, price, ts, extra_info: str | None = None):
        # 标准模板（与 v1 对齐）：仅在非 DIAG 或无 extra_info 时使用
        if not TMonitorConfigV2.DIAG or not extra_info:
            msg = f"【T警告】[{self.stock_name} {self.symbol}] {side}信号！ 价格变动：{price_diff:.2%} MACD变动：{macd_diff:.2%} 现价：{price:.2f} [{ts}]"
        else:
            # 诊断模板（包含路径信息）
            msg = f"【T警告】[{self.stock_name} {self.symbol}] {side}-背离 价格变动：{price_diff:.2%} MACD变动：{macd_diff:.2%} 现价：{price:.2f} [{ts}] | {extra_info}"
        if self.is_backtest:
            tqdm.write(msg)
        else:
            logging.warning(msg)
        if self.push_msg:
            winsound.Beep(1500 if side == 'BUY' else 500, 500)
            send_alert(msg)
        self.last_signal_price[side] = price

    def _detect_signals(self, df):
        window = TMonitorConfigV2.EXTREME_WINDOW
        # 预计算滚动高/低，显著减少局部峰/谷判定的复杂度
        if '_rh' not in df.columns:
            df['_rh'] = df['high'].rolling(window, min_periods=1).max()
        if '_rl' not in df.columns:
            df['_rl'] = df['low'].rolling(window, min_periods=1).min()

        peaks, troughs = [], []
        # 记录已输出的诊断时间，避免重复刷屏（跨回测全程仅输出一次）
        if not hasattr(self, '_diag_printed'):
            self._diag_printed: set[str] = set()

        for i in range(window, len(df)):
            # 先处理待确认队列中过期项
            self._flush_pending(df, i)

            # 诊断钩子：关注时间点输出关键指标（仅输出一次）
            if TMonitorConfigV2.DIAG:
                ts = str(df['datetime'].iloc[i])
                if ts in TMonitorConfigV2.DIAG_TICKS and ts not in self._diag_printed:
                    k, d, j = df['k'].iloc[i], df['d'].iloc[i], df['j'].iloc[i]
                    logging.info(
                        f"[DIAG {self.symbol}] ts={ts} close={df['close'].iloc[i]:.2f} "
                        f"macd={df['macd'].iloc[i]:.4f} dif={df['dif'].iloc[i]:.4f} dea={df['dea'].iloc[i]:.4f} "
                        f"K={k:.2f} D={d:.2f} J={j:.2f}"
                    )
                    try:
                        self._diag_probe(df, i)
                    except Exception:
                        pass
                    self._diag_printed.add(ts)

            # 局部峰
            if self._is_local_peak(df, i, window):
                new_peak = {
                    'idx': i,
                    'price': df['high'].iloc[i],
                    'macd': df['macd'].iloc[i],
                    'time': df['datetime'].iloc[i],
                }
                # 与历史峰比较 -> 顶背离（仅在最近 MAX_PEAK_LOOKBACK 个峰内配对）
                recent_peaks = peaks[-TMonitorConfigV2.MAX_PEAK_LOOKBACK:] if TMonitorConfigV2.MAX_PEAK_LOOKBACK > 0 else peaks
                for p in recent_peaks:
                    price_diff = (new_peak['price'] - p['price']) / max(p['price'], 1e-6)
                    macd_diff = (p['macd'] - new_peak['macd']) / max(abs(p['macd']), 1e-6)
                    if price_diff > TMonitorConfigV2.PRICE_DIFF_SELL_THR and \
                       new_peak['macd'] < p['macd'] * (1 - TMonitorConfigV2.MACD_DIFF_THR):
                        # 两种路径：
                        # 1) KDJ 已在容忍窗口内确认 -> 立即触发
                        if self._confirm_top_by_kdj(df, i):
                            if not is_duplicated(new_peak, self.triggered_sell_signals):
                                lastp = self.last_signal_price.get('SELL')
                                if lastp is None or abs(new_peak['price'] - lastp) / lastp >= TMonitorConfigV2.REPEAT_PRICE_CHANGE:
                                    extra = None
                                    if TMonitorConfigV2.DIAG:
                                        extra = f"path=immediate MACD@{p.get('time','?')}->@{new_peak['time']}"
                                    self._trigger_signal('SELL', price_diff, macd_diff, new_peak['price'], new_peak['time'], extra)
                                    self.triggered_sell_signals.append(new_peak)
                        else:
                            # 2) 先记录待确认，等待后续 KDJ 在容忍窗口内补确认
                            self._enqueue_pending('SELL', new_peak, i, price_diff, macd_diff)
                peaks.append(new_peak)

            # 局部谷
            if self._is_local_trough(df, i, window):
                new_trough = {
                    'idx': i,
                    'price': df['low'].iloc[i],
                    'macd': df['macd'].iloc[i],
                    'time': df['datetime'].iloc[i],
                }
                recent_troughs = troughs[-TMonitorConfigV2.MAX_PEAK_LOOKBACK:] if TMonitorConfigV2.MAX_PEAK_LOOKBACK > 0 else troughs
                for t in recent_troughs:
                    price_diff = (t['price'] - new_trough['price']) / max(t['price'], 1e-6)
                    macd_diff = (new_trough['macd'] - t['macd']) / max(abs(t['macd']), 1e-6)
                    if price_diff > TMonitorConfigV2.PRICE_DIFF_BUY_THR and \
                       new_trough['macd'] > t['macd'] * (1 + TMonitorConfigV2.MACD_DIFF_THR):
                        if self._confirm_bottom_by_kdj(df, i):
                            if not is_duplicated(new_trough, self.triggered_buy_signals):
                                lastp = self.last_signal_price.get('BUY')
                                if lastp is None or abs(new_trough['price'] - lastp) / lastp >= TMonitorConfigV2.REPEAT_PRICE_CHANGE:
                                    extra = None
                                    if TMonitorConfigV2.DIAG:
                                        extra = f"path=immediate MACD@{t.get('time','?')}->@{new_trough['time']}"
                                    self._trigger_signal('BUY', price_diff, macd_diff, new_trough['price'], new_trough['time'], extra)
                                    self.triggered_buy_signals.append(new_trough)
                        else:
                            self._enqueue_pending('BUY', new_trough, i, price_diff, macd_diff)
                troughs.append(new_trough)

    def _prepare_indicators(self, df):
        df = df.copy()
        df['dif'], df['dea'], df['macd'] = self._calc_macd(df)
        df['k'], df['d'], df['j'] = self._calc_kdj(df)
        return df

    def _run_live(self):
        if not self._connect_api():
            logging.error(f"{self.symbol} 连接服务器失败")
            return
        count = 0
        try:
            while not self.stop_event.is_set():
                df = self._get_realtime_bars()
                if df is None or len(df) < TMonitorConfigV2.EXTREME_WINDOW:
                    sys_time.sleep(60)
                    continue
                df = self._prepare_indicators(df)
                self._detect_signals(df)
                if count % 5 == 0:
                    latest_close = df['close'].iloc[-1]
                    logging.info(f"[{self.stock_name} {self.symbol}] 最新价:{latest_close:.2f}")
                count += 1
                if self.stop_event.wait(timeout=60):
                    break
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logging.error(f"{self.symbol} 运行异常: {e}")
        finally:
            self.api.disconnect()
            logging.info(f"{self.symbol} 监控已退出")

    def _run_backtest(self):
        if self.backtest_start is None or self.backtest_end is None:
            logging.error("回测模式下必须指定 backtest_start/backtest_end")
            return
        df = self._get_historical_data(self.backtest_start, self.backtest_end)
        if df is None or df.empty:
            logging.error("指定时间段内没有数据")
            return
        # 单次准备 + 单次扫描，避免 O(n^2) 重复计算造成卡顿
        df = df.sort_values('datetime').reset_index(drop=True)
        if len(df) < TMonitorConfigV2.EXTREME_WINDOW:
            logging.warning("样本不足，跳过回测")
            return
        df = self._prepare_indicators(df)
        # 预计算滚动极值，供局部峰/谷判定
        window = TMonitorConfigV2.EXTREME_WINDOW
        df['_rh'] = df['high'].rolling(window, min_periods=1).max()
        df['_rl'] = df['low'].rolling(window, min_periods=1).min()
        # 单次检测（流式逻辑不看未来，等价于逐根推进）
        self._detect_signals(df)
        logging.info(f"[回测 {self.symbol}] 回测结束")

    def run(self):
        if self.is_backtest:
            logging.info(f"[{self.stock_name} {self.symbol}] 回测 {self.backtest_start} ~ {self.backtest_end}")
            self._run_backtest()
        else:
            logging.info(f"[{self.stock_name} {self.symbol}] 实时监控模式")
            self._run_live()


class MonitorManagerV2:
    def __init__(self, symbols, is_backtest=False, backtest_start=None, backtest_end=None):
        self.symbols = symbols
        self.stop_event = Event()
        self.executor = ThreadPoolExecutor(max_workers=len(symbols))
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        logging.info("接收到终止信号，开始优雅退出...")
        self.stop_event.set()
        self.executor.shutdown(wait=False)
        sys.exit(0)

    def start(self):
        futures = []
        for symbol in self.symbols:
            monitor = TMonitorV2(symbol, self.stop_event,
                                 push_msg=not self.is_backtest,
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
    IS_BACKTEST = True
    backtest_start = "2025-08-25 09:30"
    backtest_end = "2025-08-29 15:00"
    symbols = ['600111', '603516']

    manager = MonitorManagerV2(symbols,
                               is_backtest=IS_BACKTEST,
                               backtest_start=backtest_start,
                               backtest_end=backtest_end)
    logging.info("启动多股票监控V2...")
    manager.start()

