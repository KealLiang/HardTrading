import logging
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

# 兼容从项目根目录或 alerting 目录运行
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from push.feishu_msg import send_alert
from utils.stock_util import convert_stock_code, stock_limit_ratio
from alerting.signal_scoring import SignalScorer, SignalStrength, calc_rsi_indicator_score
from utils.backtrade.intraday_visualizer import plot_intraday_backtest

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfig:
    """监控器配置（纯信号模式 - 对称参数）"""
    HOSTS = [
        ('117.34.114.27', 7709),
        ('202.96.138.90', 7709),
    ]

    # K线参数
    KLINE_1M = 7  # 1分钟K线
    MAX_HISTORY_BARS_1M = 500  # 1分钟历史K线数

    # 技术指标参数
    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2
    
    # 交易模式选择
    TRADING_MODE = "HYBRID"  # "LEFT"(左侧) / "RIGHT"(右侧) / "HYBRID"(混合)

    # === 核心信号阈值（对称设计，保证买卖平衡）===
    RSI_OVERSOLD = 30      # 超卖阈值
    RSI_OVERBOUGHT = 70    # 超买阈值（对称）
    RSI_EXTREME_OVERSOLD = 15   # 极度超卖
    RSI_EXTREME_OVERBOUGHT = 85  # 极度超买（对称）
    
    BB_TOLERANCE = 1.015   # 布林带容差（放宽至1.5%）
    
    # === 量价确认参数（优化：支持缩量见底）===
    VOLUME_CONFIRM_BUY = 0.8    # 买入量能确认（允许缩量0.8倍，捕捉缩量见底）
    VOLUME_CONFIRM_SELL = 1.2   # 卖出量能确认（降低至1.2倍，更敏感）
    VOLUME_SURGE_RATIO = 1.5    # 放量突破倍数
    
    # 量价背离检测
    DIVERGENCE_PRICE_CHANGE = 0.015  # 价格变化1.5%
    DIVERGENCE_VOLUME_CHANGE = -0.25 # 量能缩减25%

    # 冷却机制（优化：高位震荡可连续卖出）
    SIGNAL_COOLDOWN_SECONDS = 60   # 1分钟冷却（从3分钟缩短）
    REPEAT_PRICE_CHANGE = 0.01    # 价格变化1%即可重复（从1.5%降低）

    # 仓位控制
    MAX_TRADES_PER_DAY = 5
    
    # 🆕 信号质量过滤（做T适用性）
    MIN_SIGNAL_SCORE = 0  # 最低信号分数阈值（0=不过滤，建议55-65）
    # 说明：设置为55可过滤弱信号，设置为65只保留中强信号

    # 涨跌停判断
    # 移除硬编码阈值，改为动态获取（通过 stock_limit_ratio 方法）


class PositionManager:
    """仓位管理器（处理T+1限制）"""

    def __init__(self, initial_shares=0):
        self.total_shares = initial_shares
        self.available_shares = initial_shares
        self.today_buy = 0
        self.today_trades = 0
        self.last_trade_date = None

    def reset_daily(self):
        """每日重置"""
        today = datetime.now().date()
        if self.last_trade_date and self.last_trade_date < today:
            self.available_shares += self.today_buy
            self.today_buy = 0
            self.today_trades = 0
        self.last_trade_date = today

    def can_buy(self, shares):
        """检查是否可以买入"""
        self.reset_daily()
        if self.today_trades >= TMonitorConfig.MAX_TRADES_PER_DAY:
            return False, "今日交易次数已达上限"
        return True, "允许买入"

    def can_sell(self, shares):
        """检查是否可以卖出"""
        self.reset_daily()
        if shares > self.available_shares:
            return False, f"可卖数量不足（可卖:{self.available_shares}）"
        if self.today_trades >= TMonitorConfig.MAX_TRADES_PER_DAY:
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
    """V3做T监控器：纯信号模式 - RSI+布林带+量价确认"""

    def __init__(self, symbol, stop_event,
                 push_msg=True, is_backtest=False,
                 backtest_start=None, backtest_end=None,
                 position_manager=None, enable_visualization=True):
        """
        初始化V3监控器
        :param symbol: 股票代码
        :param stop_event: 停止事件
        :param push_msg: 是否推送消息
        :param is_backtest: 是否回测模式
        :param position_manager: 仓位管理器
        :param enable_visualization: 是否启用可视化（仅回测模式有效）
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
        self.enable_visualization = enable_visualization

        # 仓位管理
        self.position_mgr = position_manager or PositionManager()

        # 信号记录
        self.last_signal_time = {'BUY': None, 'SELL': None}
        self.last_signal_price = {'BUY': None, 'SELL': None}
        self.triggered_signals = []

        # 实时模式去重
        self._processed_signals = set()
        
        # 回测数据缓存（用于可视化）
        self.backtest_kline_data = None

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
        for host, port in TMonitorConfig.HOSTS:
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

    def _get_historical_data(self, start_time, end_time, period='1'):
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
        # 确保数值类型
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce')
        
        df['rsi14'] = self._calc_rsi(df['close'], TMonitorConfig.RSI_PERIOD)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self._calc_bollinger(
            df['close'], TMonitorConfig.BB_PERIOD, TMonitorConfig.BB_STD)
        df['vol_ma20'] = df['vol'].rolling(20).mean()
        return df

    def _is_limit_up(self, current_price, yesterday_close):
        """判断是否涨停（动态获取涨跌停阈值）"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        # 根据股票代码动态获取涨跌停阈值（主板10%、科创板/创业板20%、北交所30%）
        limit_ratio = stock_limit_ratio(self.symbol)
        # 留0.1%余量，避免临界值判断错误
        return change >= (limit_ratio - 0.001)

    def _is_limit_down(self, current_price, yesterday_close):
        """判断是否跌停（动态获取涨跌停阈值）"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        # 根据股票代码动态获取涨跌停阈值
        limit_ratio = stock_limit_ratio(self.symbol)
        # 留0.1%余量，避免临界值判断错误
        return change <= -(limit_ratio - 0.001)

    def _check_signal_cooldown(self, signal_type, current_time, current_price):
        """检查信号冷却"""
        last_time = self.last_signal_time.get(signal_type)
        last_price = self.last_signal_price.get(signal_type)

        if last_time:
            try:
                time_diff = (current_time - last_time).total_seconds()
                if time_diff < TMonitorConfig.SIGNAL_COOLDOWN_SECONDS:
                    if last_price:
                        price_change = abs(current_price - last_price) / last_price
                        if price_change < TMonitorConfig.REPEAT_PRICE_CHANGE:
                            return False, f"冷却期内且价格变化不足"
            except Exception:
                pass

        return True, "允许触发"

    def _check_volume_divergence(self, df_1m, i):
        """检查量价背离"""
        if i < 5:
            return False
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            
            # 跨日检测：确保recent_5在同一交易日
            current_date = recent_5['datetime'].iloc[-1].date() if hasattr(recent_5['datetime'].iloc[-1], 'date') else recent_5['datetime'].iloc[-1]
            first_date = recent_5['datetime'].iloc[0].date() if hasattr(recent_5['datetime'].iloc[0], 'date') else recent_5['datetime'].iloc[0]
            
            if current_date != first_date:
                # 跨日了，只使用当日数据
                recent_5 = recent_5[recent_5['datetime'].apply(lambda x: (x.date() if hasattr(x, 'date') else x) == current_date)]
                if len(recent_5) < 3:  # 当日数据不足
                    return False
            
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            price_change = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0]
            vol_change = (recent_5['vol'].iloc[-1] - recent_5['vol'].iloc[0]) / (recent_5['vol'].iloc[0] + 1e-10)
            
            # 顶背离：价涨量缩
            if price_change > TMonitorConfig.DIVERGENCE_PRICE_CHANGE and vol_change < TMonitorConfig.DIVERGENCE_VOLUME_CHANGE:
                return True
            
        except Exception:
            pass
        
        return False

    def _check_buy_volume_confirm(self, df_1m, i):
        """买入量价确认：缩量见底 OR 放量企稳"""
        if i < 5:
            return False, "数据不足"
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            
            # 跨日检测：确保recent_5在同一交易日
            current_date = recent_5['datetime'].iloc[-1].date() if hasattr(recent_5['datetime'].iloc[-1], 'date') else recent_5['datetime'].iloc[-1]
            first_date = recent_5['datetime'].iloc[0].date() if hasattr(recent_5['datetime'].iloc[0], 'date') else recent_5['datetime'].iloc[0]
            
            if current_date != first_date:
                # 跨日了，只使用当日数据
                recent_5 = recent_5[recent_5['datetime'].apply(lambda x: (x.date() if hasattr(x, 'date') else x) == current_date)]
                if len(recent_5) < 3:  # 当日数据不足3根
                    return False, "当日数据不足"
            
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            vol_early_3 = recent_5['vol'].iloc[:3].mean()
            vol_late_2 = recent_5['vol'].iloc[-2:].mean()
            latest_vol = recent_5['vol'].iloc[-1]
            
            if pd.isna(vol_early_3) or pd.isna(vol_late_2) or vol_early_3 == 0:
                return False, "量能数据异常"
            
            vol_ratio = vol_late_2 / vol_early_3
            
            # K线企稳判断
            latest = recent_5.iloc[-1]
            body = latest['close'] - latest['open']
            lower_shadow = min(latest['open'], latest['close']) - latest['low']
            body_pct = abs(body) / latest['close']
            is_stabilized = (body > 0 or 
                           lower_shadow > abs(body) * 2 or 
                           body_pct < 0.005)
            
            # 策略1: 缩量见底（量能萎缩至0.8倍以下 + 企稳）
            if vol_ratio < TMonitorConfig.VOLUME_CONFIRM_BUY and is_stabilized:
                return True, f"缩量见底✓({vol_ratio:.2f}x)"
            
            # 策略2: 放量企稳（放量1.2倍以上 + 企稳）
            if vol_ratio >= 1.2 and is_stabilized:
                return True, f"放量企稳✓({vol_ratio:.2f}x)"
            
            # 不满足
            if not is_stabilized:
                return False, "K线未企稳"
            else:
                return False, f"量能中性({vol_ratio:.2f}x)"
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 买入量价确认失败: {e}")
            return False, "确认异常"

    def _check_sell_volume_confirm(self, df_1m, i):
        """卖出量价确认：放量或背离"""
        if i < 5:
            return False, "数据不足"
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            
            # 跨日检测：确保recent_5在同一交易日
            current_date = recent_5['datetime'].iloc[-1].date() if hasattr(recent_5['datetime'].iloc[-1], 'date') else recent_5['datetime'].iloc[-1]
            first_date = recent_5['datetime'].iloc[0].date() if hasattr(recent_5['datetime'].iloc[0], 'date') else recent_5['datetime'].iloc[0]
            
            if current_date != first_date:
                # 跨日了，只使用当日数据
                recent_5 = recent_5[recent_5['datetime'].apply(lambda x: (x.date() if hasattr(x, 'date') else x) == current_date)]
                if len(recent_5) < 3:  # 当日数据不足3根
                    return False, "当日数据不足"
            
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            vol_ma5 = recent_5['vol'].mean()
            latest_vol = recent_5['vol'].iloc[-1]
            
            if pd.isna(vol_ma5) or pd.isna(latest_vol) or vol_ma5 == 0:
                return False, "量能数据异常"
            
            vol_ratio = latest_vol / vol_ma5
            
            # 1. 放量确认（降低阈值，更敏感）
            if vol_ratio > TMonitorConfig.VOLUME_CONFIRM_SELL:
                return True, f"放量卖出✓({vol_ratio:.2f}x)"
            
            # 2. 量价背离
            if self._check_volume_divergence(df_1m, i):
                return True, f"背离卖出✓"
            
            return False, f"量能不足({vol_ratio:.2f}x)"
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 卖出量价确认失败: {e}")
            return False, "确认异常"

    def _calc_signal_strength(self, df_1m, i, signal_type):
        """
        计算信号强度（使用独立评分模块）
        :param df_1m: 1分钟K线数据
        :param i: 当前索引
        :param signal_type: 'BUY' or 'SELL'
        :return: 0-100分数
        """
        if i < 20:
            return 50
        
        try:
            # 计算RSI指标得分（0-20分）
            rsi = df_1m['rsi14'].iloc[i]
            indicator_score = calc_rsi_indicator_score(rsi, signal_type)
            
            # 调用通用评分器
            score, strength = SignalScorer.calc_signal_strength(
                df=df_1m,
                i=i,
                signal_type=signal_type,
                indicator_score=indicator_score,
                bb_upper=df_1m['bb_upper'],
                bb_lower=df_1m['bb_lower'],
                vol_ma_period=20
            )
            
            return score
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 评分计算失败: {e}")
            return 50

    def _generate_signal(self, df_1m, i):
        """
        基于1分钟K线生成信号（支持左侧/右侧/混合模式）
        :return: (signal_type, reason, strength)
        """
        mode = TMonitorConfig.TRADING_MODE
        min_bars = TMonitorConfig.RSI_PERIOD + (3 if mode in ['RIGHT', 'HYBRID'] else 0)
        
        if i < min_bars:
            return None, None, 0
        
        # 1. 技术指标
        close = df_1m['close'].iloc[i]
        rsi = df_1m['rsi14'].iloc[i]
        bb_upper = df_1m['bb_upper'].iloc[i]
        bb_lower = df_1m['bb_lower'].iloc[i]
        ts = df_1m['datetime'].iloc[i]
        
        # 右侧/混合模式需要历史RSI
        if mode in ['RIGHT', 'HYBRID']:
            # 检查前2根K线是否在同一交易日
            ts_prev = df_1m['datetime'].iloc[i-1]
            ts_prev2 = df_1m['datetime'].iloc[i-2]
            date_current = ts.date() if hasattr(ts, 'date') else ts
            date_prev = ts_prev.date() if hasattr(ts_prev, 'date') else ts_prev
            date_prev2 = ts_prev2.date() if hasattr(ts_prev2, 'date') else ts_prev2
            
            # 如果跨日，则不使用右侧/混合逻辑（回退到左侧）
            if date_current != date_prev or date_current != date_prev2:
                # 当日数据不足，跳过此K线
                return None, "当日数据不足（跨日）", 0
            
            rsi_prev = df_1m['rsi14'].iloc[i-1]
            rsi_prev2 = df_1m['rsi14'].iloc[i-2]
        
        # 获取当日基准价（用于涨跌停判断）
        current_date = ts.date() if hasattr(ts, 'date') else ts
        day_first_bar = None
        for j in range(i, -1, -1):
            bar_date = df_1m['datetime'].iloc[j]
            bar_date = bar_date.date() if hasattr(bar_date, 'date') else bar_date
            if bar_date == current_date:
                day_first_bar = df_1m['open'].iloc[j]
            else:
                break
        
        reference_price = day_first_bar if day_first_bar is not None else (
            df_1m['close'].iloc[i-1] if i > 0 else close
        )
        
        # 涨跌停过滤
        if self._is_limit_up(close, reference_price):
            return None, "涨停，不追", 0
        if self._is_limit_down(close, reference_price):
            return None, "跌停，不杀", 0
        
        # 2. 买入信号判断
        buy_signal = False
        buy_reason_prefix = ""
        
        if mode == 'LEFT':
            # 左侧买入：RSI<30 + 触及下轨
            if rsi < TMonitorConfig.RSI_OVERSOLD and close <= bb_lower * TMonitorConfig.BB_TOLERANCE:
                buy_signal = True
                buy_reason_prefix = "左侧"
        
        elif mode == 'RIGHT':
            # 右侧买入：RSI从超卖区回升
            is_rsi_reversal_up = (rsi_prev2 < TMonitorConfig.RSI_OVERSOLD and 
                                 rsi_prev < TMonitorConfig.RSI_OVERSOLD and 
                                 rsi > TMonitorConfig.RSI_OVERSOLD)
            is_rsi_recovery = (rsi_prev < 25 and 25 <= rsi <= 35)
            
            if (is_rsi_reversal_up or is_rsi_recovery) and close > bb_lower:
                buy_signal = True
                buy_reason_prefix = "右侧"
        
        elif mode == 'HYBRID':
            # 混合买入：右侧确认（避免买早）+ 适度放宽
            # 策略1: RSI从超卖回升（确认筑底完成）
            is_rsi_reversal_up = (rsi_prev < TMonitorConfig.RSI_OVERSOLD and 
                                 rsi >= TMonitorConfig.RSI_OVERSOLD and 
                                 close > bb_lower * 0.995)  # 价格已离开下轨
            
            # 策略2: RSI在超卖区但呈上升趋势（底部反弹初期）
            is_rsi_rising = (rsi < 35 and rsi > rsi_prev and rsi_prev > rsi_prev2 and
                           close >= bb_lower)
            
            if is_rsi_reversal_up or is_rsi_rising:
                buy_signal = True
                buy_reason_prefix = "混合"
        
        if buy_signal:
            confirmed, confirm_msg = self._check_buy_volume_confirm(df_1m, i)
            if confirmed:
                allowed, cooldown_msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(df_1m, i, 'BUY')
                    
                    # 🆕 分数过滤
                    if TMonitorConfig.MIN_SIGNAL_SCORE > 0 and strength < TMonitorConfig.MIN_SIGNAL_SCORE:
                        return None, f"评分不足({strength}分<{TMonitorConfig.MIN_SIGNAL_SCORE})", 0
                    
                    reason = f"{buy_reason_prefix}买入(RSI:{rsi:.1f})"
                    return 'BUY', reason, strength
                else:
                    return None, cooldown_msg, 0
            else:
                return None, confirm_msg, 0
        
        # 3. 卖出信号判断
        sell_signal = False
        sell_reason_prefix = ""
        
        if mode == 'LEFT':
            # 左侧卖出：RSI>70 + 触及上轨
            if rsi > TMonitorConfig.RSI_OVERBOUGHT and close >= bb_upper * (2 - TMonitorConfig.BB_TOLERANCE):
                sell_signal = True
                sell_reason_prefix = "左侧"
        
        elif mode == 'RIGHT':
            # 右侧卖出：RSI从超买区回落
            is_rsi_reversal_down = (rsi_prev2 > TMonitorConfig.RSI_OVERBOUGHT and 
                                   rsi_prev > TMonitorConfig.RSI_OVERBOUGHT and 
                                   rsi < TMonitorConfig.RSI_OVERBOUGHT)
            is_rsi_decline = (rsi_prev > 75 and 65 <= rsi <= 75)
            
            if (is_rsi_reversal_down or is_rsi_decline) and close < bb_upper:
                sell_signal = True
                sell_reason_prefix = "右侧"
        
        elif mode == 'HYBRID':
            # 混合卖出：左侧积极（不错过拉升）+ 持续监控（抓住顶部震荡）
            # 策略1: 标准左侧卖出（拉升过程）
            is_left_sell = (rsi > TMonitorConfig.RSI_OVERBOUGHT and 
                          close >= bb_upper * (2 - TMonitorConfig.BB_TOLERANCE))
            
            # 策略2: 顶部震荡卖出（RSI虽回落但仍在高位）
            is_high_consolidation = (rsi > 65 and rsi < rsi_prev and 
                                   close >= bb_upper * 0.98)  # 接近上轨
            
            if is_left_sell or is_high_consolidation:
                sell_signal = True
                sell_reason_prefix = "混合"
        
        if sell_signal:
            confirmed, confirm_msg = self._check_sell_volume_confirm(df_1m, i)
            if confirmed:
                allowed, cooldown_msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(df_1m, i, 'SELL')
                    
                    # 🆕 分数过滤
                    if TMonitorConfig.MIN_SIGNAL_SCORE > 0 and strength < TMonitorConfig.MIN_SIGNAL_SCORE:
                        return None, f"评分不足({strength}分<{TMonitorConfig.MIN_SIGNAL_SCORE})", 0
                    
                    reason = f"{sell_reason_prefix}卖出(RSI:{rsi:.1f})"
                    return 'SELL', reason, strength
                else:
                    return None, cooldown_msg, 0
            else:
                return None, confirm_msg, 0
        
        return None, None, 0

    def _trigger_signal(self, signal_type, price, ts, reason, strength=None):
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

        # 格式化输出（增加强度标识）
        strength_tag = ""
        if strength is not None:
            if strength >= 85:
                strength_tag = " ⭐⭐⭐强"
            elif strength >= 65:
                strength_tag = " ⭐⭐中"
            else:
                strength_tag = " ⭐弱"
        
        prefix = "【历史信号】" if is_historical else "【V3信号】"
        msg = (f"{prefix}[{self.stock_name} {self.symbol}] {signal_type}{strength_tag} | "
               f"{reason} | 现价:{price:.2f} [{ts}]")

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
            'reason': reason,
            'strength': strength
        })

    def _process_1m_data(self, df_1m):
        """处理1分钟K线，生成信号"""
        if len(df_1m) < TMonitorConfig.RSI_PERIOD:
            return
        
        # 计算技术指标
        df_1m = self._prepare_indicators(df_1m)
        
        # 获取最新K线索引
        i = len(df_1m) - 1
        
        # 生成信号
        signal_type, reason, strength = self._generate_signal(df_1m, i)
        
        if signal_type:
            price = df_1m['close'].iloc[i]
            ts = df_1m['datetime'].iloc[i]
            self._trigger_signal(signal_type, price, ts, reason, strength)
        elif reason and self.is_backtest:
            # 回测模式显示被过滤的原因
            if "涨停" not in reason and "跌停" not in reason:
                tqdm.write(f"[{self.stock_name}] 信号被过滤: {reason}")

    def _run_live(self):
        """实时监控模式"""
        if not self._connect_api():
            logging.error(f"{self.symbol} 连接服务器失败")
            return

        count = 0
        try:
            while not self.stop_event.is_set():
                # 获取1分钟K线
                df_1m = self._get_realtime_bars(
                    TMonitorConfig.KLINE_1M,
                    TMonitorConfig.MAX_HISTORY_BARS_1M
                )

                if df_1m is None:
                    sys_time.sleep(60)
                    continue

                # 处理信号
                self._process_1m_data(df_1m)

                # 定期日志
                if count % 5 == 0:
                    latest_close = df_1m['close'].iloc[-1]
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
        """回测模式"""
        if self.backtest_start is None or self.backtest_end is None:
            logging.error("回测模式下必须指定 backtest_start/backtest_end")
            return

        # 获取1分钟历史数据
        df_1m = self._get_historical_data(self.backtest_start, self.backtest_end, period='1')

        if df_1m is None or df_1m.empty:
            logging.error("指定时间段内没有数据")
            return

        # 准备指标
        df_1m = self._prepare_indicators(df_1m)
        
        # 缓存K线数据用于可视化
        self.backtest_kline_data = df_1m.copy()

        logging.info(f"[回测 {self.symbol}] 1分钟K线数:{len(df_1m)}")

        # 遍历1分钟K线
        for i in range(TMonitorConfig.RSI_PERIOD, len(df_1m)):
            if self.stop_event.is_set():
                break

            # 生成信号
            signal_type, reason, strength = self._generate_signal(df_1m, i)

            if signal_type:
                price = df_1m['close'].iloc[i]
                ts = df_1m['datetime'].iloc[i]
                self._trigger_signal(signal_type, price, ts, reason, strength)

            sys_time.sleep(0.001)  # 模拟实时处理

        # 回测统计
        logging.info(f"[回测 {self.symbol}] 回测结束，共触发{len(self.triggered_signals)}个信号")
        
        # 输出数据统计
        valid_data = df_1m[df_1m['rsi14'].notna()]
        if len(valid_data) > 0:
            tqdm.write(f"\n{'='*60}")
            tqdm.write(f"[{self.stock_name} {self.symbol}] 回测数据统计:")
            tqdm.write(f"  有效K线数: {len(valid_data)}/{len(df_1m)}")
            tqdm.write(f"  价格范围: {valid_data['close'].min():.2f} ~ {valid_data['close'].max():.2f}")
            tqdm.write(f"  RSI范围: {valid_data['rsi14'].min():.1f} ~ {valid_data['rsi14'].max():.1f}")
            tqdm.write(f"  RSI平均: {valid_data['rsi14'].mean():.1f}")
            tqdm.write(f"  触及下轨次数: {(valid_data['close'] <= valid_data['bb_lower']).sum()}")
            tqdm.write(f"  触及上轨次数: {(valid_data['close'] >= valid_data['bb_upper']).sum()}")
            tqdm.write(f"  RSI<30次数: {(valid_data['rsi14'] < 30).sum()}")
            tqdm.write(f"  RSI>70次数: {(valid_data['rsi14'] > 70).sum()}")
            
            # 统计信号分布
            buy_signals = [s for s in self.triggered_signals if s['type'] == 'BUY']
            sell_signals = [s for s in self.triggered_signals if s['type'] == 'SELL']
            tqdm.write(f"  触发信号: {len(buy_signals)}买 / {len(sell_signals)}卖")
            tqdm.write(f"{'='*60}\n")
        
        # 生成可视化图表
        if self.enable_visualization and self.triggered_signals:
            try:
                tqdm.write(f"[{self.symbol}] 正在生成回测可视化图表...")
                plot_intraday_backtest(
                    df_1m=self.backtest_kline_data,
                    signals=self.triggered_signals,
                    symbol=self.symbol,
                    stock_name=self.stock_name,
                    backtest_start=self.backtest_start,
                    backtest_end=self.backtest_end
                )
            except Exception as e:
                tqdm.write(f"[警告] {self.symbol} 可视化失败: {e}")
                import traceback
                traceback.print_exc()

    def run(self):
        """启动监控"""
        if self.is_backtest:
            logging.info(
                f"[{self.stock_name} {self.symbol}] 回测模式 | "
                f"时间:{self.backtest_start} ~ {self.backtest_end}"
            )
            self._run_backtest()
        else:
            logging.info(f"[{self.stock_name} {self.symbol}] 实时监控")
            self._run_live()


class MonitorManagerV3:
    """V3多股票监控管理器"""

    def __init__(self, symbols,
                 is_backtest=False, backtest_start=None, backtest_end=None,
                 symbols_file=None, reload_interval_sec=5, enable_visualization=True):
        """
        :param symbols: 股票代码列表
        :param is_backtest: 是否回测
        :param symbols_file: 自选股文件路径
        :param enable_visualization: 是否启用可视化（仅回测模式）
        """
        self.symbols = symbols
        self.stop_event = Event()
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end
        self.symbols_file = symbols_file
        self.reload_interval_sec = reload_interval_sec
        self.enable_visualization = enable_visualization

        # 动态监控状态
        self._monitor_events = {}
        self._monitor_futures = {}
        self._monitors = {}
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

    def _start_monitor(self, symbol):
        """启动单个股票监控"""
        if symbol in self._monitor_events:
            return
        ev = Event()
        
        # 回测模式下给一个初始仓位
        position_mgr = None
        if self.is_backtest:
            position_mgr = PositionManager(initial_shares=1000)
        
        monitor = TMonitorV3(
            symbol, ev,
            push_msg=not self.is_backtest,
            is_backtest=self.is_backtest,
            backtest_start=self.backtest_start,
            backtest_end=self.backtest_end,
            position_manager=position_mgr,
            enable_visualization=self.enable_visualization
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

    def _watch_files(self):
        """监控自选股文件变化"""
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
        """启动所有监控"""
        # 初始加载
        initial_symbols = self._read_symbols_from_file()
        if initial_symbols is None:
            initial_symbols = self.symbols or []
            logging.info(f"使用参数 symbols: {initial_symbols}")
        else:
            logging.info(f"从自选股文件加载: {initial_symbols}")

        # 启动监控
        for symbol in initial_symbols:
            self._start_monitor(symbol)

        # 启动文件监控（仅实时模式）
        watcher = None
        if not self.is_backtest and self.symbols_file:
            import threading as _threading
            watcher = _threading.Thread(target=self._watch_files, daemon=True)
            watcher.start()

        try:
            if self.is_backtest:
                # 回测模式：等待所有任务完成后自动退出
                for fut in self._monitor_futures.values():
                    fut.result()
                logging.info("回测完成，程序退出")
            else:
                # 实时模式：持续运行直到收到停止信号
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
    IS_BACKTEST = True

    # 回测时间段
    backtest_start = "2025-10-20 09:30"
    backtest_end = "2025-10-24 15:00"

    # 股票列表
    symbols = ['300852']

    # 自选股文件（可选）
    symbols_file = 'watchlist.txt'

    manager = MonitorManagerV3(
        symbols=symbols,
        is_backtest=IS_BACKTEST,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        symbols_file=symbols_file,
        reload_interval_sec=5
    )

    logging.info("=" * 60)
    logging.info("启动V3做T监控 - 纯信号模式 (RSI+布林带+量价)")
    logging.info("=" * 60)
    manager.start()
