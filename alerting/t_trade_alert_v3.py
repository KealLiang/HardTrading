import logging
# 兼容从项目根目录或 alerting 目录运行
import os
import signal
import sys
import time as sys_time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from enum import Enum
from threading import Event

import akshare as ak
import pandas as pd
import winsound
from pytdx.hq import TdxHq_API
from tqdm import tqdm

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from push.feishu_msg import send_alert
from utils.stock_util import convert_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MarketRegime(Enum):
    """市场状态枚举"""
    RANGE = 'range'  # 震荡市
    UPTREND = 'uptrend'  # 上涨趋势
    DOWNTREND = 'downtrend'  # 下跌趋势


class TMonitorConfigV3:
    """V3监控器配置"""
    HOSTS = [
        ('117.34.114.27', 7709),
        ('202.96.138.90', 7709),
    ]

    # K线参数
    KLINE_5M = 0  # 5分钟K线
    KLINE_1M = 7  # 1分钟K线
    MAX_HISTORY_BARS_5M = 200  # 5分钟历史K线数
    MAX_HISTORY_BARS_1M = 360  # 1分钟历史K线数

    # 技术指标参数
    EMA_PERIOD = 21
    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2

    # 信号阈值
    RSI_OVERSOLD_RANGE = 30  # 震荡市超卖
    RSI_OVERBOUGHT_RANGE = 70  # 震荡市超买
    RSI_OVERSOLD_UPTREND = 40  # 上涨趋势超卖
    RSI_OVERBOUGHT_DOWNTREND = 60  # 下跌趋势超买
    RSI_EXTREME_OVERSOLD = 20  # 极度超卖（下跌趋势谨慎回补）

    # EMA容差（价格在EMA附近的判断范围）
    EMA_TOLERANCE = 0.005  # 0.5%

    # 1分钟确认参数
    VOLUME_CONFIRM_RATIO = 1.2  # 成交量确认：需大于前一根的1.2倍
    CONFIRM_TIMEOUT_BARS = 5  # 5分钟信号在5根1分钟内有效

    # 防重复
    SIGNAL_COOLDOWN_SECONDS = 300  # 同类型信号冷却时间5分钟
    REPEAT_PRICE_CHANGE = 0.005  # 价格变化超过0.5%才允许重复信号

    # 仓位控制
    MAX_POSITION_PCT = 1.0  # 最大仓位100%
    MIN_POSITION_PCT = 0.5  # 最小底仓50%（上涨趋势保留）
    SINGLE_TRADE_PCT = 0.25  # 单次交易25%
    MAX_TRADES_PER_DAY = 3  # 每日最多3笔

    # 止盈止损
    STOP_LOSS_PCT = 0.015  # 1.5%止损
    TAKE_PROFIT_PCT = 0.015  # 1.5%止盈

    # 涨跌停判断
    LIMIT_UP_THRESHOLD = 0.099  # 涨停阈值9.9%
    LIMIT_DOWN_THRESHOLD = -0.099  # 跌停阈值-9.9%


class PositionManager:
    """仓位管理器（处理T+1限制）"""

    def __init__(self, initial_shares=0):
        self.total_shares = initial_shares  # 总持股
        self.available_shares = initial_shares  # 可卖股数（T-1及之前买入）
        self.today_buy = 0  # 今日买入（T+1可卖）
        self.today_trades = 0  # 今日交易次数
        self.last_trade_date = None

    def reset_daily(self):
        """每日重置"""
        today = datetime.now().date()
        if self.last_trade_date and self.last_trade_date < today:
            # 今日买入转为可卖
            self.available_shares += self.today_buy
            self.today_buy = 0
            self.today_trades = 0
        self.last_trade_date = today

    def can_buy(self, shares):
        """检查是否可以买入"""
        self.reset_daily()
        if self.today_trades >= TMonitorConfigV3.MAX_TRADES_PER_DAY:
            return False, "今日交易次数已达上限"
        return True, "允许买入"

    def can_sell(self, shares):
        """检查是否可以卖出"""
        self.reset_daily()
        if shares > self.available_shares:
            return False, f"可卖数量不足（可卖:{self.available_shares}）"
        if self.today_trades >= TMonitorConfigV3.MAX_TRADES_PER_DAY:
            return False, "今日交易次数已达上限"
        return True, "允许卖出"

    def execute_buy(self, shares):
        """执行买入"""
        self.today_buy += shares
        self.total_shares += shares
        self.today_trades += 1

    def execute_sell(self, shares):
        """执行卖出"""
        self.available_shares -= shares
        self.total_shares -= shares
        self.today_trades += 1


class TMonitorV3:
    """V3做T监控器：服务于持仓成本管理"""

    def __init__(self, symbol, stop_event, market_regime='range',
                 push_msg=True, is_backtest=False,
                 backtest_start=None, backtest_end=None,
                 position_manager=None):
        """
        初始化V3监控器
        :param symbol: 股票代码
        :param stop_event: 停止事件
        :param market_regime: 市场状态 'range'/'uptrend'/'downtrend'
        :param push_msg: 是否推送消息
        :param is_backtest: 是否回测模式
        :param position_manager: 仓位管理器
        """
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

        # 市场状态
        self.market_regime = MarketRegime(market_regime)

        # 仓位管理
        self.position_mgr = position_manager or PositionManager()

        # 信号记录
        self.last_signal_time = {'BUY': None, 'SELL': None}
        self.last_signal_price = {'BUY': None, 'SELL': None}
        self.triggered_signals = []

        # 待确认信号队列（5分钟生成，等待1分钟确认）
        self.pending_signals = []  # [{'type': 'BUY', 'price': 10.5, 'time': ..., 'deadline': ...}, ...]

        # 实时模式去重
        self._processed_signals = set()

    def _get_stock_name(self):
        """获取股票名称"""
        try:
            df = ak.stock_individual_info_em(symbol=self.symbol)
            m = {row['item']: row['value'] for _, row in df.iterrows()}
            return m.get('股票简称', self.symbol)
        except Exception:
            return self.symbol

    def _determine_market(self):
        """确定市场代码"""
        p = self.symbol[:1]
        if p in ['6', '9']:
            return 1  # 沪市
        if p in ['0', '3']:
            return 0  # 深市
        raise ValueError(f"无法识别的股票代码: {self.symbol}")

    def _connect_api(self):
        """连接行情服务器"""
        for host, port in TMonitorConfigV3.HOSTS:
            if self.api.connect(host, port):
                return True
        return False

    def _get_realtime_bars(self, category, count):
        """获取实时K线数据"""
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

    def _get_historical_data(self, start_time, end_time, period='5'):
        """获取历史K线数据"""
        try:
            df = ak.stock_zh_a_minute(symbol=self.full_symbol, period=period, adjust="qfq")
            df['datetime'] = pd.to_datetime(df['day'])
            start_dt = pd.to_datetime(start_time)
            end_dt = pd.to_datetime(end_time)
            df = df[(df['datetime'] >= start_dt) & (df['datetime'] <= end_dt)].copy()
            df = df.sort_values(by='datetime').reset_index(drop=True)
            df.rename(columns={'volume': 'vol'}, inplace=True)
            return df[['datetime', 'open', 'high', 'low', 'close', 'vol']]
        except Exception as e:
            logging.error(f"获取历史数据失败: {e}")
            return None

    @staticmethod
    def _process_raw_data(raw_data):
        """处理原始K线数据"""
        df = pd.DataFrame(raw_data)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df[['datetime', 'open', 'high', 'low', 'close', 'vol']]

    @staticmethod
    def _calc_ema(series, period):
        """计算EMA"""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _calc_rsi(series, period=14):
        """计算RSI"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calc_bollinger(series, period=20, std_dev=2):
        """计算布林带"""
        mid = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    def _prepare_indicators(self, df):
        """计算所有技术指标"""
        df = df.copy()
        df['ema21'] = self._calc_ema(df['close'], TMonitorConfigV3.EMA_PERIOD)
        df['rsi14'] = self._calc_rsi(df['close'], TMonitorConfigV3.RSI_PERIOD)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self._calc_bollinger(
            df['close'], TMonitorConfigV3.BB_PERIOD, TMonitorConfigV3.BB_STD)
        # 成交量均值（用于1分钟确认）
        if 'vol' in df.columns:
            df['vol_ma'] = df['vol'].rolling(20).mean()
        return df

    def _is_limit_up(self, current_price, yesterday_close):
        """判断是否涨停"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        return change >= TMonitorConfigV3.LIMIT_UP_THRESHOLD

    def _is_limit_down(self, current_price, yesterday_close):
        """判断是否跌停"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        return change <= TMonitorConfigV3.LIMIT_DOWN_THRESHOLD

    def _check_signal_cooldown(self, signal_type, current_time, current_price):
        """检查信号冷却"""
        last_time = self.last_signal_time.get(signal_type)
        last_price = self.last_signal_price.get(signal_type)

        # 时间冷却
        if last_time:
            try:
                time_diff = (current_time - last_time).total_seconds()
                if time_diff < TMonitorConfigV3.SIGNAL_COOLDOWN_SECONDS:
                    # 在冷却期内，检查价格变化
                    if last_price:
                        price_change = abs(current_price - last_price) / last_price
                        if price_change < TMonitorConfigV3.REPEAT_PRICE_CHANGE:
                            return False, f"冷却期内且价格变化不足({price_change:.2%})"
            except Exception:
                pass

        return True, "允许触发"

    def _generate_signal_5m(self, df_5m, i):
        """
        5分钟主决策引擎
        :return: (signal_type, reason) 或 (None, None)
        """
        if i < TMonitorConfigV3.EMA_PERIOD:
            return None, None

        close = df_5m['close'].iloc[i]
        ema21 = df_5m['ema21'].iloc[i]
        rsi14 = df_5m['rsi14'].iloc[i]
        bb_upper = df_5m['bb_upper'].iloc[i]
        bb_lower = df_5m['bb_lower'].iloc[i]
        ts = df_5m['datetime'].iloc[i]

        # 获取昨收价（用于涨跌停判断）
        yesterday_close = df_5m['close'].iloc[0] if len(df_5m) > 0 else None

        # 涨跌停过滤
        if self._is_limit_up(close, yesterday_close):
            return None, "涨停，不追"
        if self._is_limit_down(close, yesterday_close):
            return None, "跌停，不杀"

        regime = self.market_regime

        # ============ 震荡市策略 ============
        if regime == MarketRegime.RANGE:
            # 买入：价格触及下轨 + RSI<30
            if close <= bb_lower and rsi14 < TMonitorConfigV3.RSI_OVERSOLD_RANGE:
                allowed, msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    return 'BUY', f'震荡下轨买入(RSI:{rsi14:.1f})'

            # 卖出：价格触及上轨 + RSI>70
            elif close >= bb_upper and rsi14 > TMonitorConfigV3.RSI_OVERBOUGHT_RANGE:
                allowed, msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    return 'SELL', f'震荡上轨卖出(RSI:{rsi14:.1f})'

        # ============ 上涨趋势策略 ============
        elif regime == MarketRegime.UPTREND:
            # 买入：价格回踩EMA21 + RSI<40
            if (close < ema21 * (1 + TMonitorConfigV3.EMA_TOLERANCE) and
                    close > ema21 * (1 - TMonitorConfigV3.EMA_TOLERANCE) and
                    rsi14 < TMonitorConfigV3.RSI_OVERSOLD_UPTREND):
                allowed, msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    return 'BUY', f'上涨回调买入(RSI:{rsi14:.1f})'

            # 卖出：价格触及上轨（止盈）
            # 注意：上涨趋势中禁止因RSI超买而提前卖出
            elif close >= bb_upper:
                allowed, msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    return 'SELL', f'上涨止盈卖出(价格:{close:.2f})'

        # ============ 下跌趋势策略 ============
        elif regime == MarketRegime.DOWNTREND:
            # 卖出：价格反弹至EMA21 + RSI>60
            if (close < ema21 * (1 + TMonitorConfigV3.EMA_TOLERANCE) and
                    close > ema21 * (1 - TMonitorConfigV3.EMA_TOLERANCE) and
                    rsi14 > TMonitorConfigV3.RSI_OVERBOUGHT_DOWNTREND):
                allowed, msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    return 'SELL', f'下跌反弹减仓(RSI:{rsi14:.1f})'

            # 买入：价格触及下轨 + RSI极度超卖（谨慎）
            # 注意：下跌趋势中禁止因RSI一般超卖而抄底
            elif (close <= bb_lower and
                  rsi14 < TMonitorConfigV3.RSI_EXTREME_OVERSOLD and
                  self.position_mgr.available_shares > 0):
                allowed, msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    return 'BUY', f'下跌超跌回补(RSI:{rsi14:.1f},谨慎)'

        return None, None

    def _confirm_signal_1m(self, df_1m, signal_type):
        """
        1分钟执行确认
        :param df_1m: 1分钟K线数据
        :param signal_type: 'BUY' 或 'SELL'
        :return: (confirmed, reason)
        """
        if len(df_1m) < 2:
            return False, "数据不足"

        latest = df_1m.iloc[-1]
        prev = df_1m.iloc[-2]

        # 确认1：价格动能方向一致
        if signal_type == 'BUY':
            # 买入需要小阳线启动
            if latest['close'] <= latest['open']:
                return False, "1分钟未见阳线启动"
        else:
            # 卖出需要小阴线确认
            if latest['close'] >= latest['open']:
                return False, "1分钟未见阴线确认"

        # 确认2：成交量放大
        if 'vol' in latest and 'vol' in prev:
            if latest['vol'] < prev['vol'] * TMonitorConfigV3.VOLUME_CONFIRM_RATIO:
                return False, f"成交量未放大({latest['vol']}/{prev['vol']})"

        return True, "1分钟确认通过"

    def _directional_risk_check(self, signal_type):
        """
        方向性风控检查
        :return: (allowed, reason)
        """
        regime = self.market_regime

        if signal_type == 'BUY':
            # 下跌趋势限制买入
            if regime == MarketRegime.DOWNTREND:
                current_pos_pct = self.position_mgr.total_shares / 10000  # 假设总股数单位
                if current_pos_pct >= TMonitorConfigV3.MAX_POSITION_PCT * 0.8:
                    return False, "下跌趋势，仓位过高，禁止加仓"

            # 检查T+1买入限制
            allowed, msg = self.position_mgr.can_buy(100)  # 假设100股
            return allowed, msg

        else:  # SELL
            # 上涨趋势保留底仓
            if regime == MarketRegime.UPTREND:
                current_pos_pct = self.position_mgr.total_shares / 10000
                if current_pos_pct <= TMonitorConfigV3.MIN_POSITION_PCT:
                    return False, "上涨趋势，底仓不足，禁止减仓"

            # 检查T+1卖出限制
            allowed, msg = self.position_mgr.can_sell(100)
            return allowed, msg

    def _trigger_signal(self, signal_type, price, ts, reason, regime_desc):
        """触发并记录信号"""
        # 实时模式去重
        if not self.is_backtest:
            signal_key = f"{signal_type}_{ts}_{price:.2f}"
            if signal_key in self._processed_signals:
                return
            self._processed_signals.add(signal_key)

        # 判断是否为历史信号
        is_historical = False
        if not self.is_backtest:
            try:
                signal_time = pd.to_datetime(ts) if isinstance(ts, str) else ts
                today = datetime.now().date()
                if signal_time.date() < today:
                    is_historical = True
            except Exception:
                pass

        # 格式化输出
        prefix = "【历史信号】" if is_historical else "【T警告-V3】"
        msg = (f"{prefix}[{self.stock_name} {self.symbol}] {signal_type}信号！ "
               f"状态:{regime_desc} | {reason} | 现价:{price:.2f} [{ts}]")

        if self.is_backtest:
            tqdm.write(msg)
        else:
            logging.warning(msg)

        if self.push_msg:
            winsound.Beep(1500 if signal_type == 'BUY' else 500, 500)
            send_alert(msg)

        # 记录信号
        self.last_signal_time[signal_type] = ts
        self.last_signal_price[signal_type] = price
        self.triggered_signals.append({
            'type': signal_type,
            'price': price,
            'time': ts,
            'reason': reason
        })

    def _process_5m_and_1m(self, df_5m, df_1m):
        """处理5分钟和1分钟K线，生成信号"""
        if len(df_5m) < TMonitorConfigV3.EMA_PERIOD:
            return

        # 计算5分钟指标
        df_5m = self._prepare_indicators(df_5m)

        # 计算1分钟指标（用于确认）
        df_1m = self._prepare_indicators(df_1m)

        # 获取最新5分钟K线索引
        i = len(df_5m) - 1

        # 生成5分钟信号
        signal_type, reason = self._generate_signal_5m(df_5m, i)

        if signal_type:
            # 方向性风控检查
            allowed, risk_msg = self._directional_risk_check(signal_type)
            if not allowed:
                logging.info(f"[{self.stock_name}] 信号被风控拦截: {risk_msg}")
                return

            # 1分钟确认
            confirmed, confirm_msg = self._confirm_signal_1m(df_1m, signal_type)

            if confirmed:
                # 触发信号
                price = df_5m['close'].iloc[i]
                ts = df_5m['datetime'].iloc[i]
                regime_desc = self.market_regime.value
                self._trigger_signal(signal_type, price, ts, reason, regime_desc)
            else:
                logging.debug(f"[{self.stock_name}] 1分钟确认未通过: {confirm_msg}")

    def _run_live(self):
        """实时监控模式"""
        if not self._connect_api():
            logging.error(f"{self.symbol} 连接服务器失败")
            return

        count = 0
        try:
            while not self.stop_event.is_set():
                # 获取5分钟和1分钟K线
                df_5m = self._get_realtime_bars(
                    TMonitorConfigV3.KLINE_5M,
                    TMonitorConfigV3.MAX_HISTORY_BARS_5M
                )
                df_1m = self._get_realtime_bars(
                    TMonitorConfigV3.KLINE_1M,
                    TMonitorConfigV3.MAX_HISTORY_BARS_1M
                )

                if df_5m is None or df_1m is None:
                    sys_time.sleep(60)
                    continue

                # 处理信号
                self._process_5m_and_1m(df_5m, df_1m)

                # 定期日志
                if count % 5 == 0:
                    latest_close = df_1m['close'].iloc[-1]
                    regime_desc = self.market_regime.value
                    logging.info(
                        f"[{self.stock_name} {self.symbol}] 状态:{regime_desc} | "
                        f"最新价:{latest_close:.2f}"
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
        """回测模式"""
        if self.backtest_start is None or self.backtest_end is None:
            logging.error("回测模式下必须指定 backtest_start/backtest_end")
            return

        # 获取5分钟历史数据
        df_5m = self._get_historical_data(self.backtest_start, self.backtest_end, period='5')
        # 获取1分钟历史数据
        df_1m = self._get_historical_data(self.backtest_start, self.backtest_end, period='1')

        if df_5m is None or df_5m.empty or df_1m is None or df_1m.empty:
            logging.error("指定时间段内没有数据")
            return

        # 准备指标
        df_5m = self._prepare_indicators(df_5m)
        df_1m = self._prepare_indicators(df_1m)

        logging.info(f"[回测 {self.symbol}] 5分钟K线数:{len(df_5m)} | 1分钟K线数:{len(df_1m)}")

        # 遍历5分钟K线
        for i in range(TMonitorConfigV3.EMA_PERIOD, len(df_5m)):
            if self.stop_event.is_set():
                break

            # 获取当前5分钟时间
            current_5m_time = df_5m['datetime'].iloc[i]

            # 筛选对应的1分钟数据（当前5分钟时间段内的1分钟K线）
            df_1m_current = df_1m[df_1m['datetime'] <= current_5m_time].copy()

            if len(df_1m_current) < 2:
                continue

            # 生成信号
            signal_type, reason = self._generate_signal_5m(df_5m, i)

            if signal_type:
                # 方向性风控
                allowed, risk_msg = self._directional_risk_check(signal_type)
                if not allowed:
                    continue

                # 1分钟确认
                confirmed, confirm_msg = self._confirm_signal_1m(df_1m_current, signal_type)

                if confirmed:
                    price = df_5m['close'].iloc[i]
                    ts = current_5m_time
                    regime_desc = self.market_regime.value
                    self._trigger_signal(signal_type, price, ts, reason, regime_desc)

            sys_time.sleep(0.001)  # 模拟实时处理

        logging.info(f"[回测 {self.symbol}] 回测结束，共触发{len(self.triggered_signals)}个信号")

    def run(self):
        """启动监控"""
        regime_desc = self.market_regime.value
        if self.is_backtest:
            logging.info(
                f"[{self.stock_name} {self.symbol}] 回测模式 | 状态:{regime_desc} | "
                f"时间:{self.backtest_start} ~ {self.backtest_end}"
            )
            self._run_backtest()
        else:
            logging.info(f"[{self.stock_name} {self.symbol}] 实时监控 | 状态:{regime_desc}")
            self._run_live()


class MonitorManagerV3:
    """V3多股票监控管理器"""

    def __init__(self, symbols, market_regime='range',
                 is_backtest=False, backtest_start=None, backtest_end=None,
                 symbols_file=None, regime_file=None, reload_interval_sec=5):
        """
        :param symbols: 股票代码列表
        :param market_regime: 初始市场状态
        :param symbols_file: 自选股文件路径
        :param regime_file: 市场状态配置文件（支持动态切换）
        """
        self.symbols = symbols
        self.market_regime = market_regime
        self.stop_event = Event()
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end
        self.symbols_file = symbols_file
        self.regime_file = regime_file
        self.reload_interval_sec = reload_interval_sec

        # 动态监控状态
        self._monitor_events = {}
        self._monitor_futures = {}
        self._monitors = {}  # 保存monitor实例，用于动态切换状态
        self._symbols_set = set()

        # 线程池
        initial_count = len(symbols) if symbols else 0
        self.executor = ThreadPoolExecutor(max_workers=max(1, initial_count + 50))

        # 信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """处理系统信号"""
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
        """解析文件路径"""
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
        """从文件读取股票列表"""
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

    def _read_regime_from_file(self):
        """从文件读取市场状态"""
        if not self.regime_file:
            return None
        try:
            path = self._resolve_file_path(self.regime_file)
            if not path or not os.path.exists(path):
                return None
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # 支持注释
                if '#' in content:
                    content = content.split('#')[0].strip()
                if content in ['range', 'uptrend', 'downtrend']:
                    return content
        except Exception as e:
            logging.error(f"读取市场状态文件失败: {e}")
        return None

    def _start_monitor(self, symbol):
        """启动单个股票监控"""
        if symbol in self._monitor_events:
            return
        ev = Event()
        monitor = TMonitorV3(
            symbol, ev,
            market_regime=self.market_regime,
            push_msg=not self.is_backtest,
            is_backtest=self.is_backtest,
            backtest_start=self.backtest_start,
            backtest_end=self.backtest_end
        )
        fut = self.executor.submit(monitor.run)
        self._monitor_events[symbol] = ev
        self._monitor_futures[symbol] = fut
        self._monitors[symbol] = monitor
        logging.info(f"已启动监控: {symbol}")

    def _stop_monitor(self, symbol):
        """停止单个股票监控"""
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
        """同步股票列表"""
        desired_set = set(desired_symbols)
        for sym in list(self._symbols_set - desired_set):
            self._stop_monitor(sym)
        for sym in sorted(desired_set - self._symbols_set):
            self._start_monitor(sym)
        self._symbols_set = set(self._monitor_events.keys())

    def _update_regime(self, new_regime):
        """动态更新所有监控器的市场状态"""
        if new_regime != self.market_regime:
            logging.info(f"市场状态切换: {self.market_regime} -> {new_regime}")
            self.market_regime = new_regime
            for monitor in self._monitors.values():
                monitor.market_regime = MarketRegime(new_regime)

    def _watch_files(self):
        """监控文件变化（自选股+市场状态）"""
        last_symbols_mtime = None
        last_regime_mtime = None

        while not self.stop_event.is_set():
            try:
                # 监控自选股文件
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

                # 监控市场状态文件
                if self.regime_file:
                    path = self._resolve_file_path(self.regime_file)
                    if path and os.path.exists(path):
                        mtime = os.path.getmtime(path)
                        if last_regime_mtime is None or mtime != last_regime_mtime:
                            regime = self._read_regime_from_file()
                            if regime:
                                self._update_regime(regime)
                            last_regime_mtime = mtime

            except Exception as e:
                logging.error(f"监控文件时出错: {e}")

            if self.stop_event.wait(timeout=self.reload_interval_sec):
                break

    def start(self):
        """启动所有监控"""
        # 初始加载
        initial_symbols = self._read_symbols_from_file()
        if initial_symbols is None:
            initial_symbols = self.symbols or []
            logging.info(f"使用参数 symbols: {initial_symbols}")
        else:
            logging.info(f"从自选股文件加载: {initial_symbols}")

        # 读取初始市场状态
        regime = self._read_regime_from_file()
        if regime:
            self.market_regime = regime
            logging.info(f"从配置文件读取市场状态: {regime}")

        # 启动监控
        for symbol in initial_symbols:
            self._start_monitor(symbol)

        # 启动文件监控（仅实时模式）
        watcher = None
        if not self.is_backtest and (self.symbols_file or self.regime_file):
            import threading as _threading
            watcher = _threading.Thread(target=self._watch_files, daemon=True)
            watcher.start()
            if self.regime_file:
                logging.info(f"支持动态切换市场状态，请修改文件: {self.regime_file}")

        try:
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


if __name__ == "__main__":
    # ============ 使用示例 ============
    IS_BACKTEST = False

    # 回测时间段
    backtest_start = "2025-10-13 09:30"
    backtest_end = "2025-10-17 15:00"

    # 股票列表
    symbols = ['300852']

    # 自选股文件（可选）
    symbols_file = 'watchlist.txt'

    # 市场状态配置文件（支持动态切换）
    # 文件内容示例：range / uptrend / downtrend
    regime_file = 'regime.txt'

    # 初始市场状态（如果有regime_file会被覆盖）
    initial_regime = 'uptrend'  # 'range' / 'uptrend' / 'downtrend'

    manager = MonitorManagerV3(
        symbols=symbols,
        market_regime=initial_regime,
        is_backtest=IS_BACKTEST,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        symbols_file=symbols_file,
        regime_file=regime_file,
        reload_interval_sec=5
    )

    logging.info("=" * 60)
    logging.info("启动V3做T监控 - 持仓成本管理工具")
    logging.info("=" * 60)
    manager.start()
