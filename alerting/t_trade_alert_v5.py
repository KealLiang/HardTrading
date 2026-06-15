"""
V5：在 V4「情绪局部衰竭」框架上的对称升级。

相对 V4 的改动（买卖对称）：
1. 软入池：双强路径 OR 总分+偏科下限，替代单一 setup∧confirm 硬闸。
2. 结构确认：低点抬高/高点降低、EMA 占比、RSI 背离/斜率，弱化单根 tick 条件。
3. 慢磨 setup：阴跌磨底 / 慢推升温，与急杀/急拉并列（取较高分，不叠满）。
4. 总分软门槛：结构强且位置合理时，允许略低于默认 MIN_SIGNAL_SCORE。
5. 文案：RSI 语境异常时 BUY/SELL 前加「疑似」（不改变是否触发）。

不包含「横盘起爆/突破」逻辑（与衰竭拐点不同赛道）。

实盘记忆：与 V4 相同，目的是保障实盘和回测一致（继承 TMonitorConfigV4 的 LIVE_STATE_*，逻辑在 t_trade_alert_base）；
启动时通达信静默回放重建波段状态，回测不受影响。
"""
import logging
import os
import sys
import winsound

import pandas as pd
from tqdm import tqdm

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

from push.feishu_msg import send_alert
from alerting.t_trade_alert_base import MonitorManagerBase
from alerting.t_trade_alert_v4 import TMonitorConfigV4, TMonitorV4

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfigV5(TMonitorConfigV4):
    """V5 配置：对称软门槛 + 结构确认。"""

    # --- 软入池（买卖共用同一套规则）---
    # 路径 A：两侧都够（略低于 V4 硬 26，便于 tdx 边界）
    MIN_SETUP_SCORE = 24
    MIN_CONFIRM_SCORE = 24
    # 路径 B：总分够且不能偏科太狠
    POOL_SUM_MIN = 52
    POOL_FLOOR_MIN = 20

    # --- 最终触发 ---
    MIN_SIGNAL_SCORE = 70
    # 路径 C：setup+confirm 已很强且位置加分够时，总分可略降
    STRONG_LEG_SUM = 58
    STRONG_LOCATION_SCORE = 6
    STRONG_MIN_SIGNAL_SCORE = 68

    # --- 结构确认参数 ---
    STRUCT_LOW_RISE_MIN = 0.001
    STRUCT_HIGH_DROP_MIN = 0.001
    EMA5_HOLD_BARS = 5
    EMA5_HOLD_RATIO = 0.6
    RSI_SLOPE_BARS = 3

    # --- 慢磨情绪铺垫（与急杀/急拉 OR，取 max）---
    SLOW_GRIND_TREND_RATIO = 0.55
    SLOW_GRIND_BUY_DROP_MIN = -0.020
    SLOW_GRIND_BUY_DROP_MAX = -0.006
    SLOW_GRIND_SELL_RISE_MIN = 0.006
    SLOW_GRIND_SELL_RISE_MAX = 0.020
    SLOW_GRIND_RANGE_MAX = 0.018

    # --- 文案「疑似」标记（不改变触发逻辑）---
    RSI_SUSPICIOUS_LOW = 5
    RSI_SUSPICIOUS_HIGH = 95
    RSI_EXTREME_LOW = 5
    RSI_EXTREME_HIGH = 95
    # setup 叙事与当前 RSI 明显不符时标疑似
    RSI_BUY_MISMATCH_MIN = 38
    RSI_SELL_MISMATCH_MAX = 62

    @classmethod
    def monitor_params(cls):
        base = super().monitor_params()
        return base + [
            cls.POOL_SUM_MIN,
            cls.POOL_FLOOR_MIN,
            cls.STRONG_LEG_SUM,
            cls.STRONG_MIN_SIGNAL_SCORE,
        ]


class TMonitorV5(TMonitorV4):
    """V5：对称软门槛 + 结构型衰竭确认。"""

    CONFIG = TMonitorConfigV5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_signal_suspicious = False

    # ---------- RSI 异常文案标记（不改变触发）----------

    def _extreme_window_spans_prior_day(self, df_1m, i):
        window = self._window(df_1m, i, self.cfg.EXTREME_WINDOW)
        dates = window['datetime'].apply(self._date_of)
        return dates.nunique() > 1

    def _assess_suspicious_rsi(self, df_1m, i, signal_type, setup_reason, rsi):
        """识别一眼不合理的 RSI 语境，仅用于 BUY/SELL 前加「疑似」。"""
        cfg = self.cfg
        if pd.isna(rsi):
            return True

        extreme = self._window(df_1m, i, cfg.EXTREME_WINDOW)
        ext_min = float(extreme['rsi14'].min())
        ext_max = float(extreme['rsi14'].max())
        setup = setup_reason or ""

        if rsi <= cfg.RSI_SUSPICIOUS_LOW or rsi >= cfg.RSI_SUSPICIOUS_HIGH:
            return True

        if ext_min <= cfg.RSI_EXTREME_LOW and ext_max >= cfg.RSI_EXTREME_HIGH:
            return True

        if signal_type == 'BUY':
            if (
                ("RSI极低" in setup or "RSI低位" in setup)
                and ext_min <= cfg.RSI_EXTREME_LOW
                and rsi >= cfg.RSI_BUY_MISMATCH_MIN
            ):
                return True
        elif (
            ("RSI极高" in setup or "RSI高位" in setup)
            and ext_max >= cfg.RSI_EXTREME_HIGH
            and rsi <= cfg.RSI_SELL_MISMATCH_MAX
        ):
            return True

        if self._extreme_window_spans_prior_day(df_1m, i):
            if ext_min <= cfg.RSI_EXTREME_LOW or ext_max >= cfg.RSI_EXTREME_HIGH:
                return True

        return False

    # ---------- 软入池 / 总分（买卖对称）----------

    def _passes_emotion_pool(self, setup, confirm):
        cfg = self.cfg
        if setup >= cfg.MIN_SETUP_SCORE and confirm >= cfg.MIN_CONFIRM_SCORE:
            return True
        leg_sum = setup + confirm
        return leg_sum >= cfg.POOL_SUM_MIN and min(setup, confirm) >= cfg.POOL_FLOOR_MIN

    def _passes_signal_score(self, score, setup, confirm, location):
        cfg = self.cfg
        if score >= cfg.MIN_SIGNAL_SCORE:
            return True
        leg_sum = setup + confirm
        return (
            leg_sum >= cfg.STRONG_LEG_SUM
            and location >= cfg.STRONG_LOCATION_SCORE
            and score >= cfg.STRONG_MIN_SIGNAL_SCORE
        )

    # ---------- 结构辅助 ----------

    def _split_window_halves(self, df, i, size):
        w = self._window(df, i, size)
        if len(w) < 4:
            return None, None
        mid = len(w) // 2
        return w.iloc[:mid], w.iloc[mid:]

    def _lows_rising_structure(self, df_1m, i):
        first, second = self._split_window_halves(df_1m, i, self.cfg.CONFIRM_WINDOW)
        if first is None:
            return False, ""
        low_first = first['low'].min()
        low_second = second['low'].min()
        if low_second >= low_first * (1 + self.cfg.STRUCT_LOW_RISE_MIN):
            return True, "低点抬高"
        return False, ""

    def _highs_falling_structure(self, df_1m, i):
        first, second = self._split_window_halves(df_1m, i, self.cfg.CONFIRM_WINDOW)
        if first is None:
            return False, ""
        high_first = first['high'].max()
        high_second = second['high'].max()
        if high_second <= high_first * (1 - self.cfg.STRUCT_HIGH_DROP_MIN):
            return True, "高点降低"
        return False, ""

    def _ema_hold_structure_score(self, df_1m, i, signal_type):
        n = self.cfg.EMA5_HOLD_BARS
        if i < n:
            return 0, ""
        recent = df_1m.iloc[i - n + 1:i + 1]
        if signal_type == 'BUY':
            ratio = (recent['close'] > recent['ema5']).mean()
            if ratio >= self.cfg.EMA5_HOLD_RATIO:
                return 8, "收盘站稳短均"
            if ratio >= 0.4:
                return 4, ""
        else:
            ratio = (recent['close'] < recent['ema5']).mean()
            if ratio >= self.cfg.EMA5_HOLD_RATIO:
                return 8, "收盘承压短均"
            if ratio >= 0.4:
                return 4, ""
        return 0, ""

    def _rsi_slope_structure_score(self, df_1m, i, signal_type):
        n = self.cfg.RSI_SLOPE_BARS
        if i < n:
            return 0, ""
        rsi = df_1m['rsi14'].iloc[i - n + 1:i + 1]
        if rsi.isna().any():
            return 0, ""
        delta = rsi.iloc[-1] - rsi.iloc[0]
        if signal_type == 'BUY' and delta >= 2:
            return 8, "RSI斜率回升"
        if signal_type == 'SELL' and delta <= -2:
            return 8, "RSI斜率回落"
        return 0, ""

    def _rsi_divergence_score(self, df_1m, i, signal_type):
        confirm = self._window(df_1m, i, self.cfg.CONFIRM_WINDOW)
        if len(confirm) < 4:
            return 0, ""
        row = df_1m.iloc[i]
        body = confirm.iloc[:-1]
        if signal_type == 'BUY':
            prior_low_idx = body['low'].idxmin()
            prior_low = body['low'].min()
            prior_rsi_at_low = df_1m.loc[prior_low_idx, 'rsi14']
            if (
                row['low'] <= prior_low * 1.002
                and row['rsi14'] > prior_rsi_at_low + 1.5
            ):
                return 10, "RSI底背离"
        else:
            prior_high_idx = body['high'].idxmax()
            prior_high = body['high'].max()
            prior_rsi_at_high = df_1m.loc[prior_high_idx, 'rsi14']
            if (
                row['high'] >= prior_high * 0.998
                and row['rsi14'] < prior_rsi_at_high - 1.5
            ):
                return 10, "RSI顶背离"
        return 0, ""

    def _detach_from_extreme_score(self, df_1m, i, signal_type):
        confirm = self._window(df_1m, i, self.cfg.CONFIRM_WINDOW)
        if len(confirm) < 2:
            return 0, ""
        row = df_1m.iloc[i]
        body = confirm.iloc[:-1]
        if signal_type == 'BUY':
            prior_low = body['low'].min()
            if row['close'] >= prior_low * 1.004:
                return 7, "脱离低点"
        else:
            prior_high = body['high'].max()
            if row['close'] <= prior_high * 0.996:
                return 7, "脱离高点"
        return 0, ""

    # ---------- 慢磨 setup（买卖对称）----------

    def _slow_grind_panic_setup(self, df_1m, i):
        row = df_1m.iloc[i]
        recent = self._window(df_1m, i, self.cfg.SETUP_WINDOW)
        if len(recent) < 8:
            return 0, ""

        drop = row['close'] / (recent['high'].max() + 1e-10) - 1
        down_ratio = (recent['close'].diff().dropna() < 0).mean()
        rng = (recent['high'].max() - recent['low'].min()) / (recent['high'].max() + 1e-10)
        pos = self._safe_range_position(
            row['close'], recent['low'].min(), recent['high'].max()
        )

        score = 0
        reasons = []
        cfg = self.cfg
        if not (
            cfg.SLOW_GRIND_BUY_DROP_MIN <= drop <= cfg.SLOW_GRIND_BUY_DROP_MAX
            and down_ratio >= cfg.SLOW_GRIND_TREND_RATIO
            and rng <= cfg.SLOW_GRIND_RANGE_MAX
            and pos <= 0.35
        ):
            return 0, ""

        score += 14
        reasons.append(f"阴跌磨底{drop:.1%}")
        if down_ratio >= 0.65:
            score += 5
        if pos <= 0.2:
            score += 5
            reasons.append("区间低位")
        return score, "，".join(reasons)

    def _slow_grind_climax_setup(self, df_1m, i):
        row = df_1m.iloc[i]
        recent = self._window(df_1m, i, self.cfg.SETUP_WINDOW)
        if len(recent) < 8:
            return 0, ""

        rise = row['close'] / (recent['low'].min() + 1e-10) - 1
        up_ratio = (recent['close'].diff().dropna() > 0).mean()
        rng = (recent['high'].max() - recent['low'].min()) / (recent['high'].max() + 1e-10)
        pos = self._safe_range_position(
            row['close'], recent['low'].min(), recent['high'].max()
        )

        score = 0
        reasons = []
        cfg = self.cfg
        if not (
            cfg.SLOW_GRIND_SELL_RISE_MIN <= rise <= cfg.SLOW_GRIND_SELL_RISE_MAX
            and up_ratio >= cfg.SLOW_GRIND_TREND_RATIO
            and rng <= cfg.SLOW_GRIND_RANGE_MAX
            and pos >= 0.65
        ):
            return 0, ""

        score += 14
        reasons.append(f"慢推升温{rise:.1%}")
        if up_ratio >= 0.65:
            score += 5
        if pos >= 0.8:
            score += 5
            reasons.append("区间高位")
        return score, "，".join(reasons)

    def _merge_setup_score(self, primary_score, primary_reason, slow_score, slow_reason):
        if slow_score > primary_score:
            return slow_score, slow_reason
        if slow_score > 0 and slow_score == primary_score and slow_reason:
            return primary_score, f"{primary_reason}；{slow_reason}" if primary_reason else slow_reason
        return primary_score, primary_reason

    # ---------- 覆盖 setup / confirm ----------

    def _panic_setup_score(self, df_1m, i):
        base_score, base_reason = super()._panic_setup_score(df_1m, i)
        slow_score, slow_reason = self._slow_grind_panic_setup(df_1m, i)
        return self._merge_setup_score(base_score, base_reason, slow_score, slow_reason)

    def _climax_setup_score(self, df_1m, i):
        base_score, base_reason = super()._climax_setup_score(df_1m, i)
        slow_score, slow_reason = self._slow_grind_climax_setup(df_1m, i)
        return self._merge_setup_score(base_score, base_reason, slow_score, slow_reason)

    def _panic_exhaustion_score(self, df_1m, i):
        if i < self.cfg.min_history_bars():
            return 0, ""

        row = df_1m.iloc[i]
        momentum = self._window(df_1m, i, self.cfg.MOMENTUM_WINDOW)
        score = 0
        reasons = []

        rising, r1 = self._lows_rising_structure(df_1m, i)
        if rising:
            score += 12
            reasons.append(r1)

        detach, r2 = self._detach_from_extreme_score(df_1m, i, 'BUY')
        if detach:
            score += detach
            if r2:
                reasons.append(r2)

        div_score, div_reason = self._rsi_divergence_score(df_1m, i, 'BUY')
        if div_score:
            score += div_score
            if div_reason:
                reasons.append(div_reason)

        slope_score, slope_reason = self._rsi_slope_structure_score(df_1m, i, 'BUY')
        if slope_score:
            score += slope_score
            if slope_reason:
                reasons.append(slope_reason)

        if len(momentum) >= 6:
            last3_ret = self._momentum(momentum['close'].iloc[-3:])
            prev3_ret = self._momentum(momentum['close'].iloc[:3])
            if last3_ret > prev3_ret:
                score += 7
                reasons.append("跌速放缓")

        ema_score, ema_reason = self._ema_hold_structure_score(df_1m, i, 'BUY')
        if ema_score:
            score += ema_score
            if ema_reason:
                reasons.append(ema_reason)

        volume_score, volume_reason = self._volume_structure_score(df_1m, i, 'BUY')
        if volume_score:
            score += volume_score
            if volume_reason:
                reasons.append(volume_reason)

        if row['close'] > df_1m.iloc[i - 1]['close']:
            score += 2

        return score, "，".join(reasons) if reasons else "未见衰竭"

    def _climax_exhaustion_score(self, df_1m, i):
        if i < self.cfg.min_history_bars():
            return 0, ""

        row = df_1m.iloc[i]
        momentum = self._window(df_1m, i, self.cfg.MOMENTUM_WINDOW)
        score = 0
        reasons = []

        falling, r1 = self._highs_falling_structure(df_1m, i)
        if falling:
            score += 12
            reasons.append(r1)

        detach, r2 = self._detach_from_extreme_score(df_1m, i, 'SELL')
        if detach:
            score += detach
            if r2:
                reasons.append(r2)

        div_score, div_reason = self._rsi_divergence_score(df_1m, i, 'SELL')
        if div_score:
            score += div_score
            if div_reason:
                reasons.append(div_reason)

        slope_score, slope_reason = self._rsi_slope_structure_score(df_1m, i, 'SELL')
        if slope_score:
            score += slope_score
            if slope_reason:
                reasons.append(slope_reason)

        if len(momentum) >= 6:
            last3_ret = self._momentum(momentum['close'].iloc[-3:])
            prev3_ret = self._momentum(momentum['close'].iloc[:3])
            if last3_ret < prev3_ret:
                score += 7
                reasons.append("涨速放缓")

        ema_score, ema_reason = self._ema_hold_structure_score(df_1m, i, 'SELL')
        if ema_score:
            score += ema_score
            if ema_reason:
                reasons.append(ema_reason)

        volume_score, volume_reason = self._volume_structure_score(df_1m, i, 'SELL')
        if volume_score:
            score += volume_score
            if volume_reason:
                reasons.append(volume_reason)

        if row['close'] < df_1m.iloc[i - 1]['close']:
            score += 2

        return score, "，".join(reasons) if reasons else "未见衰竭"

    # ---------- 文案（适配新 confirm 关键字）----------

    @staticmethod
    def _classify_signal_label(signal_type, setup_reason, confirm_reason):
        setup = setup_reason or ""
        confirm = confirm_reason or ""

        if signal_type == 'BUY':
            has_price_turn = (
                "收盘站稳短均" in confirm
                or "承接修复" in confirm
                or "放量修复" in confirm
            )
            has_confirmed_turn = "脱离低点" in confirm and has_price_turn
            has_slowdown = "跌速放缓" in confirm
            if "阴跌磨底" in setup and has_confirmed_turn:
                return "阴跌磨底衰竭买入"
            if "m回撤" in setup and has_confirmed_turn:
                return "急杀衰竭转折买入"
            if "RSI极低" in setup and ("RSI斜率回升" in confirm or "RSI底背离" in confirm):
                if has_confirmed_turn:
                    return "极端恐慌修复买入"
                return "极端恐慌修复观察买入"
            if "低点抬高" in confirm and has_slowdown and has_confirmed_turn:
                return "低位钝化修复买入"
            if "低点抬高" in confirm and (
                "RSI斜率回升" in confirm or "RSI底背离" in confirm or has_price_turn
            ):
                return "低位修复观察买入"
            if "触下轨" in setup and has_price_turn:
                return "下轨修复观察买入"
            return "恐慌衰竭买入"

        if "放量滞涨" in confirm:
            return "放量滞涨卖出"
        has_price_turn = (
            "收盘承压短均" in confirm
            or "放量滞涨" in confirm
            or "主动回落" in confirm
        )
        has_confirmed_turn = "脱离高点" in confirm and has_price_turn
        has_slowdown = "涨速放缓" in confirm
        if "慢推升温" in setup and has_confirmed_turn:
            return "慢推升温衰竭卖出"
        if "m拉升" in setup and has_confirmed_turn:
            return "冲高衰竭转折卖出"
        if "RSI极高" in setup and ("RSI斜率回落" in confirm or "RSI顶背离" in confirm):
            if has_confirmed_turn:
                return "极端亢奋回落卖出"
            return "极端亢奋降温预警卖出"
        if "高点降低" in confirm and has_slowdown and has_confirmed_turn:
            return "高位钝化回落卖出"
        if "高点降低" in confirm and (
            "RSI斜率回落" in confirm or "RSI顶背离" in confirm or has_slowdown
        ):
            return "高位降温预警卖出"
        if "触上轨" in setup and has_price_turn:
            return "上轨转弱预警卖出"
        return "亢奋衰竭卖出"

    def _generate_signal(self, df_1m, i):
        if i < self.cfg.min_history_bars():
            return None, None, 0

        row = df_1m.iloc[i]
        close = row['close']
        rsi = row['rsi14']
        ts = row['datetime']
        if pd.isna(rsi) or pd.isna(row['bb_upper']) or pd.isna(row['bb_lower']):
            return None, None, 0

        self._refresh_rsi_wave_state(row)

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
            df_1m['close'].iloc[i - 1] if i > 0 else close
        )
        if self._is_limit_up(close, reference_price):
            return None, "涨停，不追", 0
        if self._is_limit_down(close, reference_price):
            return None, "跌停，不杀", 0

        buy_setup, buy_setup_reason = self._panic_setup_score(df_1m, i)
        buy_confirm, buy_confirm_reason = self._panic_exhaustion_score(df_1m, i)
        buy_location = self._location_score(df_1m, i, 'BUY')
        buy_score = buy_setup + buy_confirm + buy_location

        sell_setup, sell_setup_reason = self._climax_setup_score(df_1m, i)
        sell_confirm, sell_confirm_reason = self._climax_exhaustion_score(df_1m, i)
        sell_location = self._location_score(df_1m, i, 'SELL')
        sell_score = sell_setup + sell_confirm + sell_location

        candidates = []
        if self._passes_emotion_pool(buy_setup, buy_confirm):
            candidates.append(('BUY', buy_score, buy_setup_reason, buy_confirm_reason))
        if self._passes_emotion_pool(sell_setup, sell_confirm):
            candidates.append(('SELL', sell_score, sell_setup_reason, sell_confirm_reason))

        if not candidates:
            return None, None, 0

        signal_type, score, setup_reason, confirm_reason = max(candidates, key=lambda item: item[1])
        allowed, cooldown_msg = self._check_signal_cooldown(signal_type, ts, close)
        if not allowed:
            return None, cooldown_msg, 0

        repeat_penalty = self._calc_repeat_price_penalty(signal_type, close, ts)
        score = max(0, min(100, int(round(score - repeat_penalty))))

        leg_setup = buy_setup if signal_type == 'BUY' else sell_setup
        leg_confirm = buy_confirm if signal_type == 'BUY' else sell_confirm
        leg_location = buy_location if signal_type == 'BUY' else sell_location

        if not self._passes_signal_score(score, leg_setup, leg_confirm, leg_location):
            return None, f"评分不足({score}分)", 0

        label = self._classify_signal_label(signal_type, setup_reason, confirm_reason)
        reason = f"{label}(RSI:{rsi:.1f}; {setup_reason}; {confirm_reason})"
        self._last_signal_suspicious = self._assess_suspicious_rsi(
            df_1m, i, signal_type, setup_reason, rsi
        )
        return signal_type, reason, score

    def _trigger_signal(self, signal_type, price, ts, reason, strength=None):
        if not self.is_backtest:
            signal_key = f"{signal_type}_{ts}_{price:.2f}"
            if signal_key in self._processed_signals:
                return
            self._processed_signals.add(signal_key)

        strength_tag = ""
        if strength is not None:
            if strength >= 88:
                strength_tag = f" [强:{strength}]"
            elif strength >= 76:
                strength_tag = f" [中:{strength}]"
            else:
                strength_tag = f" [弱:{strength}]"

        display_type = (
            f"疑似{signal_type}" if getattr(self, '_last_signal_suspicious', False) else signal_type
        )
        prefix = "【历史信号】" if self.is_backtest else "【V5信号】"
        msg = (
            f"{prefix}[{self.stock_name} {self.symbol}] **{display_type}**{strength_tag} | "
            f"{reason} | 现价:**{price:.2f}** [{ts}]"
        )

        if self.is_backtest:
            tqdm.write(msg)
        else:
            logging.warning(msg)

        if self.push_msg:
            winsound.Beep(1500 if signal_type == 'BUY' else 500, 500)
            send_alert(msg)

        self._record_signal_state(signal_type, price, ts)
        self.triggered_signals.append({
            'type': signal_type,
            'price': price,
            'time': ts,
            'reason': reason,
            'strength': strength,
        })
        self._save_live_state_if_needed()


class MonitorManagerV5(MonitorManagerBase):
    """V5 多股票监控管理器。"""

    monitor_class = TMonitorV5
    monitor_label = "V5监控"


if __name__ == "__main__":
    IS_BACKTEST = True
    # IS_BACKTEST = False

    BACKTEST_DATA_SOURCE = "tdx"
    TMonitorConfigV5.BACKTEST_DATA_SOURCE = BACKTEST_DATA_SOURCE

    WAVE_END_REQUIRE_EXCURSION = True
    TMonitorConfigV5.WAVE_END_REQUIRE_EXCURSION = WAVE_END_REQUIRE_EXCURSION

    # symbols = ['002181', '002940', '300390', '300620', '301306', '301611', '600338', '600821', '688195', '600584', '688323', '603520', '605589']
    symbols = ['605589']
    backtest_start = "2026-06-07 09:30"
    backtest_end = "2026-06-12 15:00"
    symbols_file = 'watchlist.txt'

    wave_mode = "须走出再回锚" if WAVE_END_REQUIRE_EXCURSION else "回锚即结束"
    logging.info("=" * 60)
    logging.info("启动 V5 情绪衰竭拐点监控（对称软门槛 + 结构确认）")
    logging.info(
        f"回测数据源={BACKTEST_DATA_SOURCE} | 波段结束={wave_mode} | "
        f"POOL_SUM>={TMonitorConfigV5.POOL_SUM_MIN} FLOOR>={TMonitorConfigV5.POOL_FLOOR_MIN} | "
        f"MIN_SIGNAL={TMonitorConfigV5.MIN_SIGNAL_SCORE}"
    )
    logging.info("=" * 60)

    manager = MonitorManagerV5(
        symbols=symbols,
        is_backtest=IS_BACKTEST,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        symbols_file=symbols_file,
        reload_interval_sec=5,
    )
    manager.start()
