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
from utils.stock_util import convert_stock_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class EmotionState(Enum):
    """市场情绪状态（基于量能异动+布林带趋势）"""
    NORMAL = 'normal'           # 正常波动
    MAIN_RALLY = 'main_rally'   # 主升浪（频繁触上轨+中轨上行）
    MAIN_DROP = 'main_drop'     # 主跌浪（频繁触下轨+中轨下行）
    EUPHORIA = 'euphoria'       # 情绪高涨（价升量涨）
    PANIC = 'panic'             # 恐慌杀跌（价跌量涨）


class ParamSet:
    """参数组：根据市场情绪状态动态切换"""
    
    # 标准参数组（正常波动）
    NORMAL = {
        'name': '📊正常',
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'bb_tolerance': 1.005,  # 布林带容差收紧（必须真正触及）
        'volume_confirm': 1.3,  # 量能确认倍数提高
        'need_stabilize': True,
    }
    
    # 主升浪参数组（频繁触上轨+趋势向上）
    MAIN_RALLY = {
        'name': '🚀主升',
        'rsi_oversold': 30,
        'rsi_overbought': 999,  # 主升浪不卖（除非背离）
        'bb_tolerance': 1.005,
        'volume_confirm': 1.3,
        'need_stabilize': True,
        'only_divergence_sell': True,  # 只在量价背离时卖出
    }
    
    # 主跌浪参数组（频繁触下轨+趋势向下）
    MAIN_DROP = {
        'name': '📉主跌',
        'rsi_oversold': 15,  # 主跌浪不抄底
        'rsi_overbought': 60,  # 反弹即卖
        'bb_tolerance': 0.98,  # 必须明确跌破
        'volume_confirm': 1.5,
        'need_stabilize': True,
        'need_strong_stabilize': True,  # 需要极强企稳
    }
    
    # 情绪高涨参数组（价升量涨但未形成主升浪）
    EUPHORIA = {
        'name': '🔥高涨',
        'rsi_oversold': 25,
        'rsi_overbought': 80,
        'bb_tolerance': 1.01,
        'volume_confirm': 1.5,
        'need_stabilize': True,
        'prioritize_divergence': True,
    }
    
    # 恐慌杀跌参数组（价跌量涨但未形成主跌浪）
    PANIC = {
        'name': '💥恐慌',
        'rsi_oversold': 20,
        'rsi_overbought': 65,
        'bb_tolerance': 0.99,
        'volume_confirm': 1.5,
        'need_stabilize': True,
        'need_strong_stabilize': True,
    }


class TMonitorConfig:
    """监控器配置"""
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

    # 量能异动识别
    VOLUME_ANOMALY_RATIO = 1.5  # 量能异动阈值（相对基准）
    PRICE_CHANGE_THRESHOLD = 0.01  # 价格变化阈值1%

    # 布林带趋势识别（实时检测，而非事后识别）
    BB_TREND_PERIOD = 10  # 检测近N根K线（10分钟窗口，快速响应）
    BB_MID_SLOPE_THRESHOLD = 0.0015  # 中轨斜率阈值0.15%
    TOUCH_BAND_RATIO = 0.3  # 近N根K线中触及轨道比例（30%=10根中3次）
    BB_ACCEL_PERIOD = 5  # 加速度检测窗口（最近5根）
    BB_ACCEL_RATIO = 1.5  # 加速比率（最近5根斜率 > 前5根的1.5倍）

    # 冷却机制（基于价格变化）
    SIGNAL_COOLDOWN_SECONDS = 180  # 3分钟冷却（1分钟K线波动大）
    REPEAT_PRICE_CHANGE = 0.015  # 价格变化1.5%才允许重复信号

    # 仓位控制
    MAX_TRADES_PER_DAY = 5  # 每日最多交易次数

    # 涨跌停判断
    LIMIT_UP_THRESHOLD = 0.099
    LIMIT_DOWN_THRESHOLD = -0.099


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
    """V3做T监控器：纯1分钟K线+量能异动识别+动态参数"""

    def __init__(self, symbol, stop_event,
                 push_msg=True, is_backtest=False,
                 backtest_start=None, backtest_end=None,
                 position_manager=None):
        """
        初始化V3监控器
        :param symbol: 股票代码
        :param stop_event: 停止事件
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

        # 仓位管理
        self.position_mgr = position_manager or PositionManager()

        # 信号记录
        self.last_signal_time = {'BUY': None, 'SELL': None}
        self.last_signal_price = {'BUY': None, 'SELL': None}
        self.triggered_signals = []

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
        
        # 确保成交量是数字类型
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce')
        
        df['rsi14'] = self._calc_rsi(df['close'], TMonitorConfig.RSI_PERIOD)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self._calc_bollinger(
            df['close'], TMonitorConfig.BB_PERIOD, TMonitorConfig.BB_STD)
        df['vol_ma20'] = df['vol'].rolling(20).mean()
        return df

    def _is_limit_up(self, current_price, yesterday_close):
        """判断是否涨停"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        return change >= TMonitorConfig.LIMIT_UP_THRESHOLD

    def _is_limit_down(self, current_price, yesterday_close):
        """判断是否跌停"""
        if yesterday_close is None or yesterday_close == 0:
            return False
        change = (current_price - yesterday_close) / yesterday_close
        return change <= TMonitorConfig.LIMIT_DOWN_THRESHOLD

    def _check_signal_cooldown(self, signal_type, current_time, current_price):
        """检查信号冷却"""
        last_time = self.last_signal_time.get(signal_type)
        last_price = self.last_signal_price.get(signal_type)

        if last_time:
            try:
                time_diff = (current_time - last_time).total_seconds()
                if time_diff < TMonitorConfig.SIGNAL_COOLDOWN_SECONDS:
                    # 在冷却期内，检查价格变化
                    if last_price:
                        price_change = abs(current_price - last_price) / last_price
                        if price_change < TMonitorConfig.REPEAT_PRICE_CHANGE:
                            return False, f"冷却期内且价格变化不足({price_change:.2%})"
            except Exception:
                pass

        return True, "允许触发"

    def _detect_market_state(self, df_1m, i):
        """
        综合检测市场状态（布林带趋势 + 量能异动）
        :return: (state, reason, volume_ratio)
        """
        if i < TMonitorConfig.BB_TREND_PERIOD:
            return EmotionState.NORMAL, None, 1.0
        
        try:
            # 1. 检测布林带趋势（实时识别，而非事后）
            recent_period = df_1m.iloc[i-TMonitorConfig.BB_TREND_PERIOD+1:i+1].copy()
            period_count = len(recent_period)
            current_close = df_1m['close'].iloc[i]
            current_bb_upper = df_1m['bb_upper'].iloc[i]
            current_bb_lower = df_1m['bb_lower'].iloc[i]
            
            # A. 布林带中轨斜率（整体趋势）
            bb_mid_first = recent_period['bb_mid'].iloc[0]
            bb_mid_last = recent_period['bb_mid'].iloc[-1]
            bb_mid_slope = (bb_mid_last - bb_mid_first) / bb_mid_first
            
            # B. 价格加速度（最近是否加速上涨/下跌）
            if i >= TMonitorConfig.BB_TREND_PERIOD + TMonitorConfig.BB_ACCEL_PERIOD:
                # 前5根K线的斜率
                earlier_5 = df_1m.iloc[i-TMonitorConfig.BB_TREND_PERIOD-TMonitorConfig.BB_ACCEL_PERIOD+1:i-TMonitorConfig.BB_ACCEL_PERIOD+1]
                earlier_slope = (earlier_5['close'].iloc[-1] - earlier_5['close'].iloc[0]) / earlier_5['close'].iloc[0]
                
                # 最近5根K线的斜率
                recent_5 = df_1m.iloc[i-TMonitorConfig.BB_ACCEL_PERIOD+1:i+1]
                recent_slope = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0]
                
                # 加速比率
                has_acceleration_up = recent_slope > abs(earlier_slope) * TMonitorConfig.BB_ACCEL_RATIO and recent_slope > 0.005
                has_acceleration_down = recent_slope < -abs(earlier_slope) * TMonitorConfig.BB_ACCEL_RATIO and recent_slope < -0.005
            else:
                has_acceleration_up = False
                has_acceleration_down = False
            
            # C. 统计触及上下轨次数和比例
            touch_upper_count = (recent_period['close'] >= recent_period['bb_upper'] * 0.995).sum()
            touch_lower_count = (recent_period['close'] <= recent_period['bb_lower'] * 1.005).sum()
            touch_upper_ratio = touch_upper_count / period_count
            touch_lower_ratio = touch_lower_count / period_count
            
            # D. 当前位置判断（必须正在触及轨道，而非已经离开）
            is_currently_at_upper = current_close >= current_bb_upper * 0.995
            is_currently_at_lower = current_close <= current_bb_lower * 1.005
            
            # === 判断主升浪 ===
            # 条件1：中轨上行
            # 条件2：频繁触上轨
            # 条件3：当前正在触及上轨（确保是实时的）
            # 条件4（可选）：有加速度（更强的信号）
            is_bb_uptrend = bb_mid_slope > TMonitorConfig.BB_MID_SLOPE_THRESHOLD
            is_frequent_touch_upper = touch_upper_ratio >= TMonitorConfig.TOUCH_BAND_RATIO
            
            if is_bb_uptrend and is_frequent_touch_upper and is_currently_at_upper:
                reason = f"主升浪(触上轨{touch_upper_count}/{period_count},中轨涨{bb_mid_slope*100:.2f}%"
                if has_acceleration_up:
                    reason += ",加速中"
                reason += ")"
                return EmotionState.MAIN_RALLY, reason, 1.0
            
            # === 判断主跌浪 ===
            is_bb_downtrend = bb_mid_slope < -TMonitorConfig.BB_MID_SLOPE_THRESHOLD
            is_frequent_touch_lower = touch_lower_ratio >= TMonitorConfig.TOUCH_BAND_RATIO
            
            if is_bb_downtrend and is_frequent_touch_lower and is_currently_at_lower:
                reason = f"主跌浪(触下轨{touch_lower_count}/{period_count},中轨跌{abs(bb_mid_slope)*100:.2f}%"
                if has_acceleration_down:
                    reason += ",加速中"
                reason += ")"
                return EmotionState.MAIN_DROP, reason, 1.0
            
            # 2. 量能异动检测（作为辅助）
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            baseline_10 = df_1m.iloc[i-9:i-4].copy()
            
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            baseline_10['vol'] = pd.to_numeric(baseline_10['vol'], errors='coerce')
            
            recent_vol_avg = recent_5['vol'].mean()
            baseline_vol_avg = baseline_10['vol'].mean()
            
            if pd.isna(recent_vol_avg) or pd.isna(baseline_vol_avg) or baseline_vol_avg == 0:
                return EmotionState.NORMAL, None, 1.0
            
            volume_ratio = recent_vol_avg / baseline_vol_avg
            price_change_5 = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0]
            
            # 量能异动（未形成主升/主跌浪的情况）
            if volume_ratio > TMonitorConfig.VOLUME_ANOMALY_RATIO:
                if price_change_5 > TMonitorConfig.PRICE_CHANGE_THRESHOLD:
                    return EmotionState.EUPHORIA, f"价升量涨(量比{volume_ratio:.1f})", volume_ratio
                elif price_change_5 < -TMonitorConfig.PRICE_CHANGE_THRESHOLD:
                    return EmotionState.PANIC, f"价跌量涨(量比{volume_ratio:.1f})", volume_ratio
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 市场状态检测失败: {e}")
        
        return EmotionState.NORMAL, None, 1.0

    def _check_buy_volume_confirm(self, df_1m, i, params):
        """买入量价确认"""
        if i < 5:
            return False, "数据不足"
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            vol_early = recent_5['vol'].iloc[:3].mean()
            vol_late = recent_5['vol'].iloc[-2:].mean()
            
            if pd.isna(vol_early) or pd.isna(vol_late) or vol_early == 0:
                return False, "量能数据异常"
            
            # 量能确认
            if vol_late < vol_early * params['volume_confirm']:
                return False, f"买入量能不足({vol_late:.0f}/{vol_early:.0f})"
            
            # 企稳确认
            if params.get('need_stabilize'):
                latest = recent_5.iloc[-1]
                
                # 恐慌模式：需要强企稳（连续2根阳线）
                if params.get('need_strong_stabilize'):
                    prev = recent_5.iloc[-2]
                    if not (latest['close'] > latest['open'] and prev['close'] > prev['open']):
                        return False, "未见强企稳（需连续2阳）"
                else:
                    # 正常模式：阳线或长下影
                    body = latest['close'] - latest['open']
                    lower_shadow = min(latest['open'], latest['close']) - latest['low']
                    if not (body > 0 or lower_shadow > abs(body) * 2):
                        return False, "K线未见企稳信号"
            
            return True, "量价确认买入✓"
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 买入量价确认失败: {e}")
            return False, "量价确认异常"

    def _check_sell_volume_confirm(self, df_1m, i, params):
        """卖出量价确认"""
        if i < 5:
            return False, "数据不足"
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            vol_ma5 = recent_5['vol'].mean()
            latest_vol = recent_5['vol'].iloc[-1]
            
            if pd.isna(vol_ma5) or pd.isna(latest_vol) or vol_ma5 == 0:
                return False, "量能数据异常"
            
            # 高位放量
            if latest_vol > vol_ma5 * params['volume_confirm']:
                return True, "高位放量确认卖出✓"
            
            # 或者量价背离
            is_divergence, _ = self._check_volume_divergence(df_1m, i)
            if is_divergence:
                return True, "量价背离确认卖出✓"
            
            return False, f"卖出量能不足({latest_vol:.0f}/{vol_ma5:.0f})"
            
        except Exception as e:
            if self.is_backtest:
                tqdm.write(f"[警告] 卖出量价确认失败: {e}")
            return False, "量价确认异常"

    def _check_volume_divergence(self, df_1m, i):
        """检查量价背离"""
        if i < 5:
            return False, None
        
        try:
            recent_5 = df_1m.iloc[i-4:i+1].copy()
            recent_5['vol'] = pd.to_numeric(recent_5['vol'], errors='coerce')
            
            price_change = (recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0]
            vol_change = (recent_5['vol'].iloc[-1] - recent_5['vol'].iloc[0]) / (recent_5['vol'].iloc[0] + 1e-10)
            
            # 价涨量缩（顶背离）
            if price_change > 0.01 and vol_change < -0.2:
                return True, f"顶背离(价+{price_change:.1%},量{vol_change:.1%})"
            
        except Exception:
            pass
        
        return False, None

    def _calc_signal_strength(self, rsi, signal_type, params):
        """计算信号强度"""
        score = 50
        
        if signal_type == 'BUY':
            # RSI越低，分数越高
            if rsi < 20:
                score += 30
            elif rsi < 25:
                score += 20
            elif rsi < 30:
                score += 10
        else:  # SELL
            # RSI越高，分数越高
            if rsi > 80:
                score += 30
            elif rsi > 75:
                score += 20
            elif rsi > 70:
                score += 10
        
        return min(100, max(0, score))

    def _generate_signal(self, df_1m, i):
        """
        基于1分钟K线生成信号（动态参数）
        :return: (signal_type, reason, strength)
        """
        if i < TMonitorConfig.RSI_PERIOD:
            return None, None, 0
        
        # 1. 检测市场状态（布林带趋势 + 量能异动）
        market_state, state_reason, vol_ratio = self._detect_market_state(df_1m, i)
        
        # 2. 选择参数组
        if market_state == EmotionState.MAIN_RALLY:
            params = ParamSet.MAIN_RALLY
        elif market_state == EmotionState.MAIN_DROP:
            params = ParamSet.MAIN_DROP
        elif market_state == EmotionState.EUPHORIA:
            params = ParamSet.EUPHORIA
        elif market_state == EmotionState.PANIC:
            params = ParamSet.PANIC
        else:
            params = ParamSet.NORMAL
        
        state_tag = params['name']
        
        # 3. 技术指标
        close = df_1m['close'].iloc[i]
        rsi = df_1m['rsi14'].iloc[i]
        bb_upper = df_1m['bb_upper'].iloc[i]
        bb_lower = df_1m['bb_lower'].iloc[i]
        ts = df_1m['datetime'].iloc[i]
        
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
        
        # 4. 买入信号判断
        if rsi < params['rsi_oversold'] and close <= bb_lower * params['bb_tolerance']:
            # 主跌浪：极度谨慎，几乎不买
            if market_state == EmotionState.MAIN_DROP:
                return None, "主跌浪中，不抄底", 0
            
            # 量价确认
            confirmed, confirm_msg = self._check_buy_volume_confirm(df_1m, i, params)
            if confirmed:
                # 冷却检查
                allowed, cooldown_msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(rsi, 'BUY', params)
                    reason = f"{state_tag} 超卖买入(RSI:{rsi:.1f})"
                    if state_reason:
                        reason += f" | {state_reason}"
                    return 'BUY', reason, strength
                else:
                    return None, cooldown_msg, 0
            else:
                return None, confirm_msg, 0
        
        # 5. 卖出信号判断
        elif rsi > params['rsi_overbought'] and close >= bb_upper * (2 - params['bb_tolerance']):
            # 主升浪：只在量价背离时卖出
            if market_state == EmotionState.MAIN_RALLY:
                if params.get('only_divergence_sell'):
                    is_divergence, div_reason = self._check_volume_divergence(df_1m, i)
                    if is_divergence:
                        allowed, cooldown_msg = self._check_signal_cooldown('SELL', ts, close)
                        if allowed:
                            strength = self._calc_signal_strength(rsi, 'SELL', params) + 20
                            return 'SELL', f"{state_tag} {div_reason}", strength
                    else:
                        return None, "主升浪中，持股待涨", 0
            
            # 情绪高涨时，优先看量价背离
            if market_state == EmotionState.EUPHORIA and params.get('prioritize_divergence'):
                is_divergence, div_reason = self._check_volume_divergence(df_1m, i)
                if is_divergence:
                    allowed, cooldown_msg = self._check_signal_cooldown('SELL', ts, close)
                    if allowed:
                        strength = self._calc_signal_strength(rsi, 'SELL', params) + 10
                        return 'SELL', f"{state_tag} {div_reason}", strength
            
            # 常规卖出量价确认
            confirmed, confirm_msg = self._check_sell_volume_confirm(df_1m, i, params)
            if confirmed:
                allowed, cooldown_msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(rsi, 'SELL', params)
                    reason = f"{state_tag} 超买卖出(RSI:{rsi:.1f})"
                    if state_reason:
                        reason += f" | {state_reason}"
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
            if strength >= 80:
                strength_tag = " ⭐⭐⭐强"
            elif strength >= 60:
                strength_tag = " ⭐⭐中"
            else:
                strength_tag = " ⭐弱"
        
        prefix = "【历史信号】" if is_historical else "【T警告-V3】"
        msg = (f"{prefix}[{self.stock_name} {self.symbol}] {signal_type}信号{strength_tag}！ "
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
                 symbols_file=None, reload_interval_sec=5):
        """
        :param symbols: 股票代码列表
        :param is_backtest: 是否回测
        :param symbols_file: 自选股文件路径
        """
        self.symbols = symbols
        self.stop_event = Event()
        self.is_backtest = is_backtest
        self.backtest_start = backtest_start
        self.backtest_end = backtest_end
        self.symbols_file = symbols_file
        self.reload_interval_sec = reload_interval_sec

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
            position_manager=position_mgr
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
    backtest_end = "2025-10-23 15:00"

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
    logging.info("启动V3做T监控 - 1分钟K线+量能异动识别")
    logging.info("=" * 60)
    manager.start()
