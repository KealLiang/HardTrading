"""做T监控公共基础设施（数据拉取、回测/实盘主循环）。"""
import logging
import os
import signal
import sys
import time as sys_time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pandas as pd
from pytdx.hq import TdxHq_API
from tqdm import tqdm

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

from alerting.monitor_state_store import (
    apply_loaded_state,
    build_payload,
    format_state_summary,
    load_live_state,
    save_live_state,
    state_file_path,
)
from alerting.backtest_data_source import (
    BACKTEST_SOURCE_AKSHARE,
    BACKTEST_SOURCE_TDX,
    BacktestDataUnavailable,
    fetch_akshare_minute,
    fetch_tdx_minute,
)
from utils.stock_util import convert_stock_code, get_stock_name, stock_limit_ratio
from utils.backtrade.intraday_visualizer import plot_intraday_backtest

MAX_TRADES_PER_DAY = 5
# 通达信 pytdx：1 分钟 K 线 category（协议常量，非策略参数）
TDX_KLINE_1M = 7


class PositionManager:
    """仓位管理器（处理T+1限制）"""

    def __init__(self, initial_shares=0):
        self.total_shares = initial_shares
        self.available_shares = initial_shares
        self.today_buy = 0
        self.today_trades = 0
        self.last_trade_date = None

    def reset_daily(self):
        today = datetime.now().date()
        if self.last_trade_date and self.last_trade_date < today:
            self.available_shares += self.today_buy
            self.today_buy = 0
            self.today_trades = 0
        self.last_trade_date = today

    def can_buy(self, shares):
        self.reset_daily()
        if self.today_trades >= MAX_TRADES_PER_DAY:
            return False, "今日交易次数已达上限"
        return True, "允许买入"

    def can_sell(self, shares):
        self.reset_daily()
        if shares > self.available_shares:
            return False, f"可卖数量不足（可卖:{self.available_shares}）"
        if self.today_trades >= MAX_TRADES_PER_DAY:
            return False, "今日交易次数已达上限"
        return True, "允许卖出"

    def execute_buy(self, shares):
        self.today_buy += shares
        self.total_shares += shares
        self.today_trades += 1

    def execute_sell(self, shares):
        self.available_shares -= shares
        self.total_shares -= shares
        self.today_trades += 1


class TMonitorBase:
    """做T监控器基类：子类实现信号逻辑与配置。"""

    CONFIG = None

    @property
    def cfg(self):
        return self.CONFIG

    def __init__(self, symbol, stop_event,
                 push_msg=True, is_backtest=False,
                 backtest_start=None, backtest_end=None,
                 position_manager=None, enable_visualization=True):
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
        self.enable_visualization = enable_visualization

        self.position_mgr = position_manager or PositionManager()
        self.last_signal_time = {'BUY': None, 'SELL': None}
        self.last_signal_price = {'BUY': None, 'SELL': None}
        self.rsi_wave_active = {'BUY': False, 'SELL': False}
        self.triggered_signals = []
        self._processed_signals = set()
        self.backtest_kline_data = None

    def _live_state_enabled(self):
        return (
            not self.is_backtest
            and getattr(self.cfg, "LIVE_STATE_PERSIST", False)
        )

    def _live_state_path(self):
        state_dir = getattr(self.cfg, "LIVE_STATE_DIR", None)
        return state_file_path(self.symbol, state_dir)

    def _load_live_state_if_needed(self):
        retention = int(getattr(self.cfg, "LIVE_STATE_RETENTION_DAYS", 2))
        data = load_live_state(self._live_state_path(), retention)
        if not data:
            return
        summaries = apply_loaded_state(self, data)
        if summaries:
            logging.info(
                f"[{self.stock_name} {self.symbol}] 已恢复波段状态 "
                f"(保留{retention}天): {', '.join(summaries)}"
            )

    def _save_live_state_if_needed(self):
        if not self._live_state_enabled():
            return
        wave_extreme = getattr(self, "_wave_extreme", None)
        payload = build_payload(
            self.symbol,
            self.last_signal_time,
            self.last_signal_price,
            self.rsi_wave_active,
            wave_extreme=wave_extreme,
        )
        try:
            save_live_state(self._live_state_path(), payload)
        except OSError as e:
            logging.warning(f"[{self.symbol}] 保存波段状态失败: {e}")

    def _reset_wave_state(self):
        self.last_signal_time = {'BUY': None, 'SELL': None}
        self.last_signal_price = {'BUY': None, 'SELL': None}
        self.rsi_wave_active = {'BUY': False, 'SELL': False}
        if hasattr(self, '_wave_extreme'):
            self._wave_extreme = {'BUY': None, 'SELL': None}

    def _record_signal_state(self, signal_type, price, ts):
        """仅更新波段记忆（回放预热与实盘推送共用，不推送）。"""
        self.last_signal_time[signal_type] = ts
        self.last_signal_price[signal_type] = price
        self.rsi_wave_active[signal_type] = True
        if (
            getattr(self.cfg, 'WAVE_END_REQUIRE_EXCURSION', False)
            and hasattr(self, '_wave_extreme')
        ):
            self._wave_extreme[signal_type] = price

    def _fetch_minute_data(
        self,
        end_time,
        start_time=None,
        retention_days=None,
        period='1',
        log_prefix='取数',
        *,
        log_level=logging.INFO,
    ):
        """回测与实盘预热共用的分钟线取数入口，返回 (df, meta)。"""
        source = self._backtest_data_source()
        try:
            if source == BACKTEST_SOURCE_AKSHARE:
                if retention_days is not None:
                    logging.warning(
                        f"{self.symbol} akshare 暂不支持 retention_days，"
                        "实盘预热请使用 BACKTEST_DATA_SOURCE='tdx'"
                    )
                    return None, None
                df, meta = fetch_akshare_minute(
                    self.full_symbol,
                    start_time,
                    end_time,
                    self.cfg.WARMUP_BARS,
                    period=period,
                )
            elif source == BACKTEST_SOURCE_TDX:
                if period != '1':
                    logging.warning(
                        f"{self.symbol} 通达信回测仅支持1分钟，已忽略 period={period}"
                    )
                if not self._connect_api():
                    logging.error(f"{self.symbol} 通达信连接失败，无法拉取数据")
                    return None, None
                try:
                    df, meta = fetch_tdx_minute(
                        self.api,
                        self.market,
                        self.symbol,
                        end_time,
                        self.cfg.WARMUP_BARS,
                        TDX_KLINE_1M,
                        self._process_raw_data,
                        start_time=start_time,
                        retention_days=retention_days,
                        chunk_size=getattr(self.cfg, "TDX_BACKTEST_CHUNK_BARS", 800),
                        max_chunks=getattr(self.cfg, "TDX_BACKTEST_MAX_CHUNKS", 50),
                    )
                finally:
                    self.api.disconnect()
            else:
                logging.error(
                    f"未知 BACKTEST_DATA_SOURCE={source}，"
                    f"请使用 '{BACKTEST_SOURCE_TDX}' 或 '{BACKTEST_SOURCE_AKSHARE}'"
                )
                return None, None

            self._log_fetch_meta(meta, log_prefix=log_prefix, log_level=log_level)
            return df, meta
        except BacktestDataUnavailable as e:
            logging.log(log_level, f"[{log_prefix} {self.symbol}] {e}")
            return None, None
        except Exception as e:
            logging.error(f"[{log_prefix} {self.symbol}] 获取数据失败: {e}")
            return None, None

    def _log_filtered_signal_reason(self, reason):
        """候选信号未触发时输出原因（回测调试用）。"""
        if not reason:
            return
        if "涨停" in reason or "跌停" in reason:
            return
        tqdm.write(f"[{self.stock_name}] 信号被过滤: {reason}")

    def _replay_history(self, df, active_start, *, record_only=False, log_filtered=None):
        """按 active_start 回放历史 K 线；record_only=True 时只更新波段记忆不推送。"""
        if log_filtered is None:
            log_filtered = getattr(self.cfg, 'LOG_FILTERED_SIGNALS', False)

        df = self._prepare_indicators(df)
        start_dt = pd.to_datetime(active_start)
        active_mask = df['datetime'] >= start_dt
        if not active_mask.any():
            return 0

        start_idx = active_mask.idxmax()
        if not record_only:
            self.backtest_kline_data = df[active_mask].copy()

        replay_count = 0
        for i in range(max(self.cfg.min_history_bars(), start_idx), len(df)):
            if not record_only and self.stop_event.is_set():
                break

            signal_type, reason, strength = self._generate_signal(df, i)
            if signal_type:
                price = df['close'].iloc[i]
                ts = df['datetime'].iloc[i]
                if record_only:
                    self._record_signal_state(signal_type, price, ts)
                else:
                    self._trigger_signal(signal_type, price, ts, reason, strength)
                replay_count += 1
            elif reason and log_filtered:
                self._log_filtered_signal_reason(reason)
        return replay_count

    def _warmup_live_state_from_history(self):
        """实盘启动时用近 N 日通达信 1 分钟线回放，重建波段记忆（不推送历史信号）。"""
        if not self._live_state_enabled():
            return

        retention = int(getattr(self.cfg, 'LIVE_STATE_RETENTION_DAYS', 2))
        if getattr(self.cfg, 'LIVE_STATE_REPLAY_ON_START', True):
            end_dt = datetime.now()
            end_str = end_dt.strftime('%Y-%m-%d %H:%M')

            self._reset_wave_state()
            df, meta = self._fetch_minute_data(
                end_str,
                retention_days=retention,
                log_prefix='实盘回放',
                log_level=logging.WARNING,
            )
            if df is None or df.empty or meta is None:
                logging.warning(
                    f"[{self.stock_name} {self.symbol}] 近{retention}日回放无数据，空状态启动"
                )
                return

            replay_count = self._replay_history(
                df, meta.active_start, record_only=True, log_filtered=False
            )
            self._save_live_state_if_needed()
            summaries = format_state_summary(self)
            detail = ', '.join(summaries) if summaries else '无未结束波段'
            logging.info(
                f"[{self.stock_name} {self.symbol}] 已从近{retention}日行情回放重建记忆 "
                f"({replay_count}个历史触发点): {detail}"
            )
        else:
            self._load_live_state_if_needed()

    def _get_stock_name(self):
        data_path = os.path.join(parent_dir, 'data', 'astocks')
        return get_stock_name(self.symbol, data_path=data_path)

    def _determine_market(self):
        p = self.symbol[:1]
        if p in ['6', '9']:
            return 1
        if p in ['0', '3']:
            return 0
        raise ValueError(f"无法识别的股票代码: {self.symbol}")

    def _connect_api(self):
        for host, port in self.cfg.HOSTS:
            if self.api.connect(host, port):
                return True
        return False

    def _get_realtime_bars(self, category, count):
        try:
            data = self.api.get_security_bars(
                category=category,
                market=self.market,
                code=self.symbol,
                start=0,
                count=count,
            )
            return self._process_raw_data(data)
        except Exception as e:
            logging.error(f"获取{self.symbol}数据失败: {e}")
            return None

    def _backtest_data_source(self):
        return getattr(self.cfg, "BACKTEST_DATA_SOURCE", BACKTEST_SOURCE_TDX).lower()

    def _log_fetch_meta(self, meta, log_prefix='取数', log_level=logging.INFO):
        fetched = (
            f"拉取 {meta.fetched_bars} 根"
            f"({meta.fetched_oldest} ~ {meta.fetched_newest}) | "
            if meta.fetched_bars else ""
        )
        replay = ""
        if meta.replay_dates:
            replay = (
                f"回放 {len(meta.replay_dates)} 日 "
                f"{meta.replay_dates[0]} ~ {meta.replay_dates[-1]} | "
            )
        logging.log(
            log_level,
            f"[{log_prefix} {self.symbol}] 数据源={meta.source} | "
            f"{fetched}"
            f"{replay}"
            f"切片 {meta.total_bars} 根({meta.oldest} ~ {meta.newest}) | "
            f"活跃 {meta.active_bars}根 + 预热 {meta.warmup_bars}根"
        )

    def _get_historical_data(self, start_time, end_time, period='1'):
        df, _ = self._fetch_minute_data(
            end_time,
            start_time=start_time,
            period=period,
            log_prefix='回测取数',
        )
        return df

    @staticmethod
    def _process_raw_data(raw_data):
        df = pd.DataFrame(raw_data)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df[['datetime', 'open', 'high', 'low', 'close', 'vol']]

    @staticmethod
    def _calc_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_bollinger(series, period=20, std_dev=2):
        mid = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        return mid + std_dev * std, mid, mid - std_dev * std

    def _is_limit_up(self, current_price, yesterday_close):
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        limit_ratio = stock_limit_ratio(self.symbol)
        return change >= (limit_ratio - 0.001)

    def _is_limit_down(self, current_price, yesterday_close):
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        limit_ratio = stock_limit_ratio(self.symbol)
        return change <= -(limit_ratio - 0.001)

    @staticmethod
    def _date_of(ts):
        return ts.date() if hasattr(ts, 'date') else ts

    def _get_previous_close(self, df_1m, i, current_date):
        try:
            prev_df = df_1m.iloc[:i].copy()
            prev_df = prev_df[prev_df['datetime'].apply(lambda x: self._date_of(x) < current_date)]
            if prev_df.empty:
                return None
            return prev_df['close'].iloc[-1]
        except Exception:
            return None

    def _prepare_indicators(self, df):
        raise NotImplementedError

    def _generate_signal(self, df_1m, i):
        raise NotImplementedError

    def _trigger_signal(self, signal_type, price, ts, reason, strength=None):
        raise NotImplementedError

    def _get_monitor_params(self):
        return None

    def _process_1m_data(self, df_1m):
        if self.cfg.CONFIRM_CLOSED_BAR:
            df_1m = df_1m.iloc[:-1].copy()
        if len(df_1m) < self.cfg.min_history_bars():
            return

        df_1m = self._prepare_indicators(df_1m)
        i = len(df_1m) - 1
        signal_type, reason, strength = self._generate_signal(df_1m, i)

        if signal_type:
            price = df_1m['close'].iloc[i]
            ts = df_1m['datetime'].iloc[i]
            self._trigger_signal(signal_type, price, ts, reason, strength)
        elif reason and self.is_backtest:
            # 原设计：仅回测模式下单根评估时输出；实盘 loop 不会进入（is_backtest=False）
            self._log_filtered_signal_reason(reason)

    def _run_live(self):
        self._warmup_live_state_from_history()
        if not self._connect_api():
            logging.error(f"{self.symbol} 连接服务器失败")
            return

        count = 0
        try:
            while not self.stop_event.is_set():
                df_1m = self._get_realtime_bars(
                    TDX_KLINE_1M,
                    self.cfg.MAX_HISTORY_BARS_1M,
                )
                if df_1m is None:
                    sys_time.sleep(60)
                    continue

                self._process_1m_data(df_1m)

                if count % 5 == 0:
                    latest_idx = -2 if self.cfg.CONFIRM_CLOSED_BAR and len(df_1m) > 1 else -1
                    latest_close = df_1m['close'].iloc[latest_idx]
                    logging.info(
                        f"[{self.stock_name} {self.symbol}] 最新价:{latest_close:.2f}"
                    )
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

        df_1m, meta = self._fetch_minute_data(
            self.backtest_end,
            start_time=self.backtest_start,
            log_prefix='回测取数',
        )
        if df_1m is None or df_1m.empty or meta is None:
            logging.error("指定时间段内没有数据")
            return

        logging.info(
            f"[回测 {self.symbol}] 数据源={self._backtest_data_source()} | "
            f"1分钟K线数:{meta.active_bars} (warm-up:{meta.warmup_bars})"
        )

        # log_filtered 默认走 cfg.LOG_FILTERED_SIGNALS（False），与历史回测一致
        self._replay_history(df_1m, meta.active_start, record_only=False)

        logging.info(f"[回测 {self.symbol}] 回测结束，共触发{len(self.triggered_signals)}个信号")

        bt_df = self.backtest_kline_data
        valid_data = bt_df[bt_df['rsi14'].notna()] if bt_df is not None else pd.DataFrame()
        if len(valid_data) > 0:
            tqdm.write(f"\n{'='*60}")
            tqdm.write(f"[{self.stock_name} {self.symbol}] 回测数据统计:")
            tqdm.write(f"  有效K线数: {len(valid_data)}/{len(bt_df)}")
            tqdm.write(f"  价格范围: {valid_data['close'].min():.2f} ~ {valid_data['close'].max():.2f}")
            tqdm.write(f"  RSI范围: {valid_data['rsi14'].min():.1f} ~ {valid_data['rsi14'].max():.1f}")
            tqdm.write(f"  RSI平均: {valid_data['rsi14'].mean():.1f}")
            tqdm.write(f"  触及下轨次数: {(valid_data['close'] <= valid_data['bb_lower']).sum()}")
            tqdm.write(f"  触及上轨次数: {(valid_data['close'] >= valid_data['bb_upper']).sum()}")
            tqdm.write(f"  RSI<30次数: {(valid_data['rsi14'] < 30).sum()}")
            tqdm.write(f"  RSI>70次数: {(valid_data['rsi14'] > 70).sum()}")
            buy_signals = [s for s in self.triggered_signals if s['type'] == 'BUY']
            sell_signals = [s for s in self.triggered_signals if s['type'] == 'SELL']
            tqdm.write(f"  触发信号: {len(buy_signals)}买 / {len(sell_signals)}卖")
            tqdm.write(f"{'='*60}\n")

        if self.enable_visualization and self.triggered_signals:
            try:
                tqdm.write(f"[{self.symbol}] 正在生成回测可视化图表...")
                plot_intraday_backtest(
                    df_1m=self.backtest_kline_data,
                    signals=self.triggered_signals,
                    symbol=self.symbol,
                    stock_name=self.stock_name,
                    backtest_start=self.backtest_start,
                    backtest_end=self.backtest_end,
                    monitor_params=self._get_monitor_params(),
                )
            except Exception as e:
                tqdm.write(f"[警告] {self.symbol} 可视化失败: {e}")
                import traceback
                traceback.print_exc()

    def run(self):
        if self.is_backtest:
            logging.info(
                f"[{self.stock_name} {self.symbol}] 回测模式 | "
                f"时间:{self.backtest_start} ~ {self.backtest_end}"
            )
            self._run_backtest()
        else:
            logging.info(f"[{self.stock_name} {self.symbol}] 实时监控")
            self._run_live()


class MonitorManagerBase:
    """多股票监控管理器基类。"""

    monitor_class = None
    monitor_label = "监控"

    def __init__(self, symbols,
                 is_backtest=False, backtest_start=None, backtest_end=None,
                 symbols_file=None, reload_interval_sec=5, enable_visualization=True):
        self.symbols = symbols
        self.stop_event = Event()
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end
        self.symbols_file = symbols_file
        self.reload_interval_sec = reload_interval_sec
        self.enable_visualization = enable_visualization

        self._monitor_events = {}
        self._monitor_futures = {}
        self._monitors = {}
        self._symbols_set = set()

        initial_count = len(symbols) if symbols else 0
        self.executor = ThreadPoolExecutor(max_workers=max(1, initial_count + 50))

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        logging.info("接收到终止信号，开始优雅退出...")
        self.stop_event.set()
        for ev in list(self._monitor_events.values()):
            try:
                ev.set()
            except Exception:
                pass
        self.executor.shutdown(wait=False)
        sys.exit(0)

    def _resolve_file_path(self, filename):
        if not filename:
            return None
        candidates = []
        try:
            if os.path.isabs(filename):
                candidates.append(filename)
            else:
                candidates.append(filename)
                candidates.append(os.path.join(parent_dir, filename))
                candidates.append(os.path.join(current_dir, filename))
        except Exception:
            return None

        for c in candidates:
            try:
                if os.path.exists(c):
                    return os.path.abspath(c)
            except Exception:
                continue

        try:
            return os.path.abspath(os.path.join(parent_dir, filename))
        except Exception:
            return None

    def _read_symbols_from_file(self):
        if not self.symbols_file:
            return None
        try:
            path = self._resolve_file_path(self.symbols_file)
            if not path or not os.path.exists(path):
                return None
            syms = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    s = s.split('#', 1)[0].strip()
                    if len(s) == 6 and s.isdigit():
                        syms.append(s)
            return syms
        except Exception as e:
            logging.error(f"读取自选股文件失败: {e}")
            return None

    def _start_monitor(self, symbol):
        if symbol in self._monitor_events:
            return
        if self.monitor_class is None:
            raise NotImplementedError("子类需设置 monitor_class")

        ev = Event()
        position_mgr = PositionManager(initial_shares=1000) if self.is_backtest else None

        monitor = self.monitor_class(
            symbol, ev,
            push_msg=not self.is_backtest,
            is_backtest=self.is_backtest,
            backtest_start=self.backtest_start,
            backtest_end=self.backtest_end,
            position_manager=position_mgr,
            enable_visualization=self.enable_visualization,
        )
        fut = self.executor.submit(monitor.run)
        self._monitor_events[symbol] = ev
        self._monitor_futures[symbol] = fut
        self._monitors[symbol] = monitor
        logging.info(f"已启动{self.monitor_label}: {symbol}")

    def _stop_monitor(self, symbol):
        ev = self._monitor_events.get(symbol)
        if ev:
            try:
                ev.set()
                logging.info(f"已请求停止监控: {symbol}")
            except Exception:
                pass
        self._monitor_events.pop(symbol, None)
        self._monitor_futures.pop(symbol, None)
        self._monitors.pop(symbol, None)

    def _reconcile_symbols(self, desired_symbols):
        desired_set = set(desired_symbols)
        for sym in list(self._symbols_set - desired_set):
            self._stop_monitor(sym)
        for sym in sorted(desired_set - self._symbols_set):
            self._start_monitor(sym)
        self._symbols_set = set(self._monitor_events.keys())

    def _watch_files(self):
        last_symbols_mtime = None
        while not self.stop_event.is_set():
            try:
                if self.symbols_file:
                    path = self._resolve_file_path(self.symbols_file)
                    if path and os.path.exists(path):
                        mtime = os.path.getmtime(path)
                        if last_symbols_mtime is None or mtime != last_symbols_mtime:
                            syms = self._read_symbols_from_file()
                            if syms is not None:
                                logging.info("检测到自选股文件变更，重新加载...")
                                self._reconcile_symbols(syms)
                            last_symbols_mtime = mtime
            except Exception as e:
                logging.error(f"监控文件时出错: {e}")

            if self.stop_event.wait(timeout=self.reload_interval_sec):
                break

    def start(self):
        if self.is_backtest:
            initial_symbols = self.symbols or []
            logging.info(f"回测使用参数 symbols: {initial_symbols}")
        else:
            initial_symbols = self._read_symbols_from_file()
            if initial_symbols is None:
                initial_symbols = []
                logging.warning("实时监控未能从 symbols_file 加载股票列表")
            else:
                logging.info(f"从自选股文件加载: {initial_symbols}")

        for symbol in initial_symbols:
            self._start_monitor(symbol)

        watcher = None
        if not self.is_backtest and self.symbols_file:
            import threading as _threading
            watcher = _threading.Thread(target=self._watch_files, daemon=True)
            watcher.start()

        try:
            if self.is_backtest:
                for fut in self._monitor_futures.values():
                    fut.result()
                logging.info("回测完成，程序退出")
            else:
                while not self.stop_event.is_set():
                    sys_time.sleep(1)
        finally:
            for ev in list(self._monitor_events.values()):
                try:
                    ev.set()
                except Exception:
                    pass
            if watcher is not None:
                self.stop_event.set()
                try:
                    watcher.join(timeout=2)
                except Exception:
                    pass
            self.executor.shutdown()
