import logging
import os
import signal
import sys
from enum import Enum

import pandas as pd
import winsound
from tqdm import tqdm

# 兼容从项目根目录或 alerting 目录运行
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

from push.feishu_msg import send_alert
from alerting.signal_scoring import SignalScorer, SignalStrength, calc_rsi_indicator_score
from alerting.t_trade_alert_base import MonitorManagerBase, PositionManager, TMonitorBase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfig:
    """监控器配置（纯信号模式 - 对称参数）"""
    HOSTS = [
        ('117.34.114.27', 7709),
        ('202.96.138.90', 7709),
    ]

    # ==================== K线参数 ====================
    WARMUP_BARS = 200  # 指标预热窗口；回测和实盘保持同一历史视野
    MAX_HISTORY_BARS_1M = WARMUP_BARS + 1  # 实时多取1根，用于丢弃未收完的当前分钟K线
    CONFIRM_CLOSED_BAR = True  # 实盘是否使用收线确认；False则使用当前未完成分钟K线

    # ==================== 技术指标参数 ====================
    RSI_PERIOD = 14   # RSI计算周期（分钟数）
                      # 调大(如20)：RSI更平滑，反应滞后，适合波段
                      # 调小(如6)：RSI更敏感，信号频繁，适合超短线
                      # 标准值14是经典平衡点
    
    BB_PERIOD = 20    # 布林带均线周期（分钟数）
                      # 调大(如30)：通道更宽，触发信号减少，过滤震荡
                      # 调小(如10)：通道更窄，触发信号增多，捕捉短期波动
    
    BB_STD = 2        # 布林带标准差倍数
                      # 调大(如2.5)：上下轨更宽，信号更保守（极端位置才触发）
                      # 调小(如1.5)：上下轨更窄，信号更激进（小波动也触发）
                      # 标准值2对应95%置信区间
    
    # ==================== 交易模式选择 ====================
    TRADING_MODE = "HYBRID"  # 信号触发策略
                             # "LEFT"   - 左侧交易：抄底摸顶，RSI触及极值区立即信号（激进）
                             # "RIGHT"  - 右侧交易：趋势确认，RSI从极值区回归才信号（保守）
                             # "HYBRID" - 混合模式：极值触达/转向确认 + 评分过滤，买卖保持镜像

    # ==================== 核心信号阈值（对称设计）====================
    RSI_OVERSOLD = 30       # 超卖阈值（买入参考线）
                            # 调小(如20)：等待更深回调，信号更少但质量更高
                            # 调大(如35)：提前介入，信号更多但假突破风险增大
    
    RSI_OVERBOUGHT = 70     # 超买阈值（卖出参考线，应与OVERSOLD对称）
                            # 调大(如80)：等待更充分拉升，可能错过顶部
                            # 调小(如65)：提前止盈，避免回撤但收益受限
    
    RSI_EXTREME_OVERSOLD = 15   # 极度超卖（强信号加分项，评分系统使用）
    RSI_EXTREME_OVERBOUGHT = 85  # 极度超买（强信号加分项，评分系统使用）
    
    BB_TOLERANCE = 1.015    # 布林带容差（1.015 = 允许1.5%偏差）
                            # 调大(如1.03)：放宽触轨判断，信号增多
                            # 调小(如1.005)：严格触轨判断，信号减少
                            # 用途：避免"接近但未触及"的边界情况被过滤
    
    # ==================== 量价确认参数 ====================
    VOLUME_CONFIRM_BUY = 0.8    # 买入量能确认倍数（相对前期均量）
                                # 设为0.8表示【缩量见底】策略：量能萎缩至80%以下视为恐慌出尽
                                # 调大(如1.0)：要求放量确认，信号更保守
                                # 调小(如0.6)：允许极端缩量，捕捉底部，但假信号增多
    
    VOLUME_CONFIRM_SELL = 1.2   # 卖出量能确认倍数（相对近5分钟均量）
                                # 设为1.2表示放量20%以上才卖出
                                # 调大(如1.5)：等待明显放量，可能错过逃顶
                                # 调小(如1.1)：对量能更敏感，提前止盈
    
    VOLUME_SURGE_RATIO = 1.5    # 放量突破倍数（评分系统用，判断是否放量）
                                # 调大(如2.0)：认定"放量"的标准更高
                                # 调小(如1.3)：轻微放量即认可

    # 量价背离检测（顶背离卖出信号）
    DIVERGENCE_PRICE_CHANGE = 0.015   # 价格变化阈值（1.5%）
                                       # 调大：只捕捉大级别背离
                                       # 调小：对小背离也敏感
    
    DIVERGENCE_VOLUME_CHANGE = -0.25  # 量能缩减阈值（-25%）
                                       # 调大(如-0.15)：轻微缩量即判定背离，信号增多
                                       # 调小(如-0.35)：要求明显缩量，信号更可靠

    OPENING_GAP_THRESHOLD = 0.03  # 开盘前几分钟相对昨收涨跌超过3%，视为重要情绪信息

    # ==================== 冷却机制（防止重复信号）====================
    SIGNAL_COOLDOWN_SECONDS = 60   # 同类信号最小间隔（秒）
                                   # 调大(如180)：强制3分钟冷却，避免高频信号
                                   # 调小(如30)：允许快速连续信号，适合极端行情
                                   # 建议：60秒（1根K线周期）平衡噪音与灵敏度
    
    REPEAT_PRICE_CHANGE = 0.01     # 价格变化多少允许突破冷却（1%）
                                   # 调大(如0.02)：价格需显著变化才能重复信号
                                   # 调小(如0.005)：小波动也能触发新信号
                                   # 用途：冷却期内若价格剧变仍可发信号（避免踏空/深套）

    # ==================== 仓位控制 ====================
    MAX_TRADES_PER_DAY = 5  # 单票每日最大交易次数（买入+卖出总计）
                            # ⚠️ 当前为预留功能，需配合自动交易系统使用
                            # 调大(如10)：允许高频做T，适合震荡市
                            # 调小(如3)：限制交易频率，降低成本
                            # 说明：5次 ≈ 最多做2个完整T（买-卖-买-卖-买）
    
    # ==================== 信号质量过滤 ====================
    MIN_SIGNAL_SCORE = 65   # 最低信号分数阈值（0-100分）
                            # 0   = 不过滤，所有信号都输出
                            # 55  = 过滤弱信号，保留中等及以上质量
                            # 65  = 只保留中强信号，适合选择困难症
                            # 75+ = 只保留强信号，信号极少但胜率高
                            # 调大：信号数量↓，质量↑，可能错过机会
                            # 调小：信号数量↑，质量↓，噪音增多

    # ==================== 重复信号评分惩罚 ====================
    RSI_BUY_WAVE_RESET = 45    # 买入信号后，RSI回到该值以上视为低位情绪波段结束
    RSI_SELL_WAVE_RESET = 55   # 卖出信号后，RSI回到该值以下视为高位情绪波段结束
    REPEAT_PRICE_FULL_SCORE_CHANGE = 0.02  # 同向信号价格走出2%新空间后，不再因重复扣分
    REPEAT_PRICE_MAX_SCORE_PENALTY = 40     # 同价位附近重复信号的最高扣分（略高于100-MIN_SIGNAL_SCORE，可过滤价格相近的重复信号）

    # ==================== 涨跌停判断 ====================
    # 移除硬编码阈值，改为动态获取（通过 stock_limit_ratio 方法）
    # 自动适配：主板10%、科创板/创业板20%、北交所30%

    @classmethod
    def min_history_bars(cls):
        """生成信号所需的最少历史K线数。"""
        return cls.RSI_PERIOD


class TMonitorV3(TMonitorBase):
    """V3做T监控器：纯信号模式 - RSI+布林带+量价确认"""

    CONFIG = TMonitorConfig

    def _prepare_indicators(self, df):
        """计算所有技术指标"""
        df = df.copy()
        # 确保数值类型
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce')
        
        df['rsi14'] = self._calc_rsi(df['close'], self.cfg.RSI_PERIOD)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self._calc_bollinger(
            df['close'], self.cfg.BB_PERIOD, self.cfg.BB_STD)
        df['vol_ma20'] = df['vol'].rolling(20).mean()
        return df

    def _check_signal_cooldown(self, signal_type, current_time, current_price):
        """检查信号冷却"""
        last_time = self.last_signal_time.get(signal_type)
        last_price = self.last_signal_price.get(signal_type)

        if last_time:
            try:
                time_diff = (current_time - last_time).total_seconds()
                if time_diff < self.cfg.SIGNAL_COOLDOWN_SECONDS:
                    if last_price:
                        price_change = abs(current_price - last_price) / last_price
                        if price_change < self.cfg.REPEAT_PRICE_CHANGE:
                            return False, f"冷却期内且价格变化不足"
            except Exception:
                pass

        return True, "允许触发"

    @staticmethod
    def _format_gap_msg(gap_change):
        if gap_change is None:
            return "较昨收:未知"
        return f"较昨收:{gap_change * 100:+.1f}%"

    def _check_opening_buy_confirm(self, df_1m, i, recent_today, current_date):
        """当日K线不足3根时的买入弱确认。"""
        latest = recent_today.iloc[-1]
        body = latest['close'] - latest['open']
        lower_shadow = min(latest['open'], latest['close']) - latest['low']
        body_pct = abs(body) / latest['close']
        is_stabilized = (
            body > 0 or
            lower_shadow > abs(body) * 2 or
            body_pct < 0.005
        )

        prev_close = self._get_previous_close(df_1m, i, current_date)
        gap_change = None
        if prev_close is not None and prev_close > 0:
            gap_change = (latest['close'] - prev_close) / prev_close

        gap_msg = self._format_gap_msg(gap_change)
        if is_stabilized:
            return True, f"开盘企稳✓({gap_msg})"
        return False, f"开盘K线未企稳({gap_msg})"

    def _check_opening_sell_confirm(self, df_1m, i, recent_today, current_date):
        """当日K线不足3根时的卖出弱确认。"""
        latest = recent_today.iloc[-1]
        body = latest['close'] - latest['open']
        upper_shadow = latest['high'] - max(latest['open'], latest['close'])
        body_pct = abs(body) / latest['close']
        is_weakening = (
            body < 0 or
            upper_shadow > abs(body) * 2 or
            body_pct < 0.005
        )

        prev_close = self._get_previous_close(df_1m, i, current_date)
        gap_change = None
        if prev_close is not None and prev_close > 0:
            gap_change = (latest['close'] - prev_close) / prev_close

        is_gap_up = gap_change is not None and gap_change >= TMonitorConfig.OPENING_GAP_THRESHOLD
        gap_msg = self._format_gap_msg(gap_change)
        if is_weakening or is_gap_up:
            return True, f"开盘转弱/高开确认✓({gap_msg})"
        return False, f"开盘K线未转弱({gap_msg})"

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
                    return self._check_opening_buy_confirm(df_1m, i, recent_5, current_date)
            
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
                    return self._check_opening_sell_confirm(df_1m, i, recent_5, current_date)
            
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

    def _refresh_rsi_wave_state(self, rsi):
        """RSI回到中性区后，结束同向重复信号的扣分上下文。"""
        if self.rsi_wave_active['BUY'] and rsi >= TMonitorConfig.RSI_BUY_WAVE_RESET:
            self.rsi_wave_active['BUY'] = False
        if self.rsi_wave_active['SELL'] and rsi <= TMonitorConfig.RSI_SELL_WAVE_RESET:
            self.rsi_wave_active['SELL'] = False

    def _calc_repeat_price_penalty(self, signal_type, current_price, current_time):
        """同一RSI情绪波段内，同向信号若仍在上一信号价附近则扣分。"""
        if not self.rsi_wave_active.get(signal_type):
            return 0

        last_price = self.last_signal_price.get(signal_type)
        last_time = self.last_signal_time.get(signal_type)

        if not last_price or not last_time:
            return 0

        try:
            current_dt = pd.to_datetime(current_time)
            last_dt = pd.to_datetime(last_time)
            if current_dt.date() != last_dt.date():
                return 0

            if signal_type == 'BUY':
                favorable_change = (last_price - current_price) / last_price
            else:
                favorable_change = (current_price - last_price) / last_price

            full_score_change = TMonitorConfig.REPEAT_PRICE_FULL_SCORE_CHANGE
            if favorable_change >= full_score_change:
                return 0

            max_penalty = TMonitorConfig.REPEAT_PRICE_MAX_SCORE_PENALTY
            if favorable_change <= 0:
                return max_penalty

            penalty = max_penalty * (1 - favorable_change / full_score_change)
            return int(round(max(0, min(max_penalty, penalty))))
        except Exception:
            return 0

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

        if pd.isna(rsi) or pd.isna(bb_upper) or pd.isna(bb_lower):
            return None, None, 0

        self._refresh_rsi_wave_state(rsi)

        # 右侧/混合模式需要历史RSI
        if mode in ['RIGHT', 'HYBRID']:
            # 检查前2根K线是否在同一交易日
            ts_prev = df_1m['datetime'].iloc[i-1]
            ts_prev2 = df_1m['datetime'].iloc[i-2]
            date_current = ts.date() if hasattr(ts, 'date') else ts
            date_prev = ts_prev.date() if hasattr(ts_prev, 'date') else ts_prev
            date_prev2 = ts_prev2.date() if hasattr(ts_prev2, 'date') else ts_prev2
            
            is_cross_day = (date_current != date_prev or date_current != date_prev2)
            
            if is_cross_day:
                # 🔧 跨日时回退到左侧模式（避免开盘前2-3分钟信号缺失）
                # 说明：开盘初期（如09:31-09:32）前2根K线是前一日的，
                # 若直接跳过会导致高质量信号（如RSI>80）被过滤
                mode = 'LEFT'
            else:
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
            # 混合买入：低位极值触达或转强确认，重复信号交给评分系统处理
            # 策略0: 低位极值触达
            is_lower_extreme_touch = (rsi < TMonitorConfig.RSI_OVERSOLD and
                                    close <= bb_lower * TMonitorConfig.BB_TOLERANCE)

            # 策略1: RSI从超卖回升（确认筑底完成）
            is_rsi_reversal_up = (rsi_prev < TMonitorConfig.RSI_OVERSOLD and 
                                 rsi >= TMonitorConfig.RSI_OVERSOLD and 
                                 close > bb_lower * 0.995)  # 价格已离开下轨
            
            # 策略2: RSI在超卖区但呈上升趋势（底部反弹初期）
            is_rsi_rising = (rsi < 35 and rsi > rsi_prev and rsi_prev > rsi_prev2 and
                           close >= bb_lower)
            
            if is_lower_extreme_touch or is_rsi_reversal_up or is_rsi_rising:
                buy_signal = True
                buy_reason_prefix = "混合"
        
        if buy_signal:
            confirmed, confirm_msg = self._check_buy_volume_confirm(df_1m, i)
            if confirmed:
                allowed, cooldown_msg = self._check_signal_cooldown('BUY', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(df_1m, i, 'BUY')
                    repeat_penalty = self._calc_repeat_price_penalty('BUY', close, ts)
                    strength = max(0, strength - repeat_penalty)
                    
                    # 🆕 分数过滤
                    if TMonitorConfig.MIN_SIGNAL_SCORE > 0 and strength < TMonitorConfig.MIN_SIGNAL_SCORE:
                        penalty_msg = f"，重复扣分{repeat_penalty}" if repeat_penalty else ""
                        return None, f"评分不足({strength}分<{TMonitorConfig.MIN_SIGNAL_SCORE}{penalty_msg})", 0
                    
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
            # 混合卖出：高位极值触达或转弱确认，重复信号交给评分系统处理
            is_upper_extreme_touch = (rsi > TMonitorConfig.RSI_OVERBOUGHT and
                                    close >= bb_upper * (2 - TMonitorConfig.BB_TOLERANCE))
            
            is_rsi_reversal_down = (rsi_prev > TMonitorConfig.RSI_OVERBOUGHT and
                                   rsi <= TMonitorConfig.RSI_OVERBOUGHT and
                                   close >= bb_upper * 0.98)
            
            is_rsi_falling = (rsi > 65 and rsi < rsi_prev and rsi_prev < rsi_prev2 and
                            close >= bb_upper * 0.98)
            
            if is_upper_extreme_touch or is_rsi_reversal_down or is_rsi_falling:
                sell_signal = True
                sell_reason_prefix = "混合"
        
        if sell_signal:
            confirmed, confirm_msg = self._check_sell_volume_confirm(df_1m, i)
            if confirmed:
                allowed, cooldown_msg = self._check_signal_cooldown('SELL', ts, close)
                if allowed:
                    strength = self._calc_signal_strength(df_1m, i, 'SELL')
                    repeat_penalty = self._calc_repeat_price_penalty('SELL', close, ts)
                    strength = max(0, strength - repeat_penalty)
                    
                    # 🆕 分数过滤
                    if TMonitorConfig.MIN_SIGNAL_SCORE > 0 and strength < TMonitorConfig.MIN_SIGNAL_SCORE:
                        penalty_msg = f"，重复扣分{repeat_penalty}" if repeat_penalty else ""
                        return None, f"评分不足({strength}分<{TMonitorConfig.MIN_SIGNAL_SCORE}{penalty_msg})", 0
                    
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
            medium_threshold = TMonitorConfig.MIN_SIGNAL_SCORE + (100 - TMonitorConfig.MIN_SIGNAL_SCORE) / 3
            strong_threshold = TMonitorConfig.MIN_SIGNAL_SCORE + (100 - TMonitorConfig.MIN_SIGNAL_SCORE) * 2 / 3
            if strength >= strong_threshold:
                strength_tag = f" ⭐⭐⭐[强:{strength}]"
            elif strength >= medium_threshold:
                strength_tag = f" ⭐⭐[中:{strength}]"
            else:
                strength_tag = f" ⭐[弱:{strength}]"
        
        prefix = "【历史信号】" if is_historical else "【V3信号】"
        msg = (f"{prefix}[{self.stock_name} {self.symbol}] **{signal_type}**{strength_tag} | "
               f"{reason} | 现价:**{price:.2f}** [{ts}]")

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
        self.rsi_wave_active[signal_type] = True
        self.triggered_signals.append({
            'type': signal_type,
            'price': price,
            'time': ts,
            'reason': reason,
            'strength': strength
        })


class MonitorManagerV3(MonitorManagerBase):
    """V3多股票监控管理器"""

    monitor_class = TMonitorV3
    monitor_label = "V3监控"


if __name__ == "__main__":
    # ============ 使用示例 ============
    # 实盘说明：
    # 1) 默认 CONFIRM_CLOSED_BAR=True：实时监控会丢弃最后一根未收完分钟K，使用收线确认，信号最多慢1分钟。
    #    如需恢复实时K线触发，可将 CONFIRM_CLOSED_BAR 设为 False。
    # 2) 回测会额外带入 WARMUP_BARS 根历史K线做指标预热，但只在回测起止时间内触发信号。
    IS_BACKTEST = True
    # IS_BACKTEST = False

    # 回测股票列表（仅 IS_BACKTEST=True 时使用；实时监控使用 symbols_file）
    symbols = ['301611']
    # 回测时间段
    backtest_start = "2026-04-21 09:30"
    backtest_end = "2026-04-28 15:00"

    # 实时监控自选股文件（仅 IS_BACKTEST=False 时使用）
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
