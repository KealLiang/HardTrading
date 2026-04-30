import logging
import os
import sys
import winsound
from threading import Event

import pandas as pd
from tqdm import tqdm

# 兼容从项目根目录或 alerting 目录运行
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

from push.feishu_msg import send_alert
from alerting.t_trade_alert_v3 import (
    MonitorManagerV3,
    PositionManager,
    TMonitorConfig,
    TMonitorV3,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class TMonitorConfigV4:
    """V4配置：识别日内情绪局部衰竭点。"""

    # 复用V3的数据源和基础运行参数
    KLINE_1M = TMonitorConfig.KLINE_1M
    WARMUP_BARS = 240
    MAX_HISTORY_BARS_1M = WARMUP_BARS + 1
    CONFIRM_CLOSED_BAR = True

    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2

    # 情绪窗口
    # SETUP_WINDOW：判断是否出现一段恐慌/亢奋；调大更看重慢性情绪，调小更偏急杀/急拉。
    SETUP_WINDOW = 20
    # EXTREME_WINDOW：寻找最近极端RSI/触轨；调大更容易捕捉早先极端，调小更要求极端刚发生。
    EXTREME_WINDOW = 8
    # CONFIRM_WINDOW：右侧衰竭结构确认；调大更稳但更滞后，调小更灵敏但噪声更大。
    CONFIRM_WINDOW = 5
    # MOMENTUM_WINDOW：比较近端涨跌速变化；调大更平滑，调小更敏感。
    MOMENTUM_WINDOW = 6

    # 信号阈值
    # MIN_SIGNAL_SCORE：最终信号门槛；调大信号更少更强，调小信号更多但噪声增加。
    MIN_SIGNAL_SCORE = 72
    # MIN_SETUP_SCORE：极端情绪门槛；调大要求更强恐慌/亢奋，调小会纳入温和波动。
    MIN_SETUP_SCORE = 24
    # MIN_CONFIRM_SCORE：右侧衰竭门槛；调大更晚更稳，调小更早更灵敏。
    MIN_CONFIRM_SCORE = 24

    # 同向重复信号管理
    # REPEAT_PRICE_CHANGE：同一情绪波段重复提示所需的新价格空间；调大重复更少，调小更密集。
    REPEAT_PRICE_CHANGE = 0.018
    # RSI回到中性区后，认为上一段恐慌/亢奋波段结束。
    RSI_BUY_WAVE_RESET = 45
    RSI_SELL_WAVE_RESET = 55
    # 重复信号评分惩罚：价格走出足够新空间则不扣分，否则按接近程度扣分。
    REPEAT_PRICE_FULL_SCORE_CHANGE = 0.018
    REPEAT_PRICE_MAX_SCORE_PENALTY = 35


class TMonitorV4(TMonitorV3):
    """V4做T监控器：识别恐慌/亢奋情绪的局部衰竭点。"""

    def _prepare_indicators(self, df):
        df = df.copy()
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['vol'] = pd.to_numeric(df['vol'], errors='coerce')

        df['rsi14'] = self._calc_rsi(df['close'], TMonitorConfigV4.RSI_PERIOD)
        df['bb_upper'], df['bb_mid'], df['bb_lower'] = self._calc_bollinger(
            df['close'], TMonitorConfigV4.BB_PERIOD, TMonitorConfigV4.BB_STD
        )
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['vol_ma20'] = df['vol'].rolling(20).mean()
        return df

    def _refresh_rsi_wave_state(self, rsi):
        if self.rsi_wave_active['BUY'] and rsi >= TMonitorConfigV4.RSI_BUY_WAVE_RESET:
            self.rsi_wave_active['BUY'] = False
        if self.rsi_wave_active['SELL'] and rsi <= TMonitorConfigV4.RSI_SELL_WAVE_RESET:
            self.rsi_wave_active['SELL'] = False

    def _check_signal_cooldown(self, signal_type, current_time, current_price):
        """同一情绪波段内按价格新空间去重，不使用固定时间冷却。"""
        if not self.rsi_wave_active.get(signal_type):
            return True, "允许触发"

        last_price = self.last_signal_price.get(signal_type)
        last_time = self.last_signal_time.get(signal_type)
        if not last_price or not last_time:
            return True, "允许触发"

        try:
            current_dt = pd.to_datetime(current_time)
            last_dt = pd.to_datetime(last_time)
            if current_dt.date() != last_dt.date():
                return True, "允许触发"

            if signal_type == 'BUY':
                favorable_change = (last_price - current_price) / last_price
                if favorable_change < TMonitorConfigV4.REPEAT_PRICE_CHANGE:
                    return False, "同一恐慌波段价格空间不足"
            else:
                favorable_change = (current_price - last_price) / last_price
                if favorable_change < TMonitorConfigV4.REPEAT_PRICE_CHANGE:
                    return False, "同一亢奋波段价格空间不足"
        except Exception:
            return True, "允许触发"

        return True, "允许触发"

    def _calc_repeat_price_penalty(self, signal_type, current_price, current_time):
        """同一情绪波段内，只有走出新空间的重复信号才保留高分。"""
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

            if favorable_change >= TMonitorConfigV4.REPEAT_PRICE_FULL_SCORE_CHANGE:
                return 0
            if favorable_change <= 0:
                return TMonitorConfigV4.REPEAT_PRICE_MAX_SCORE_PENALTY

            penalty = TMonitorConfigV4.REPEAT_PRICE_MAX_SCORE_PENALTY * (
                1 - favorable_change / TMonitorConfigV4.REPEAT_PRICE_FULL_SCORE_CHANGE
            )
            return int(round(max(0, min(TMonitorConfigV4.REPEAT_PRICE_MAX_SCORE_PENALTY, penalty))))
        except Exception:
            return 0

    @staticmethod
    def _window(df, i, size):
        return df.iloc[max(0, i - size + 1):i + 1]

    @staticmethod
    def _safe_range_position(value, low, high):
        return (value - low) / (high - low + 1e-10)

    @staticmethod
    def _bb_position(row):
        half_width = max(row['bb_upper'] - row['bb_mid'], 1e-10)
        return (row['close'] - row['bb_mid']) / half_width

    @staticmethod
    def _momentum(series):
        if len(series) < 2:
            return 0
        return series.iloc[-1] / (series.iloc[0] + 1e-10) - 1

    def _panic_setup_score(self, df_1m, i):
        row = df_1m.iloc[i]
        recent = self._window(df_1m, i, TMonitorConfigV4.SETUP_WINDOW)
        extreme = self._window(df_1m, i, TMonitorConfigV4.EXTREME_WINDOW)

        score = 0
        reasons = []

        min_rsi = extreme['rsi14'].min()
        if min_rsi <= 15:
            score += 16
            reasons.append(f"RSI极低{min_rsi:.1f}")
        elif min_rsi <= 25:
            score += 12
            reasons.append(f"RSI低位{min_rsi:.1f}")
        elif min_rsi <= 32:
            score += 7

        touched_lower = (extreme['close'] <= extreme['bb_lower'] * 1.005).any()
        if touched_lower:
            score += 11
            reasons.append("触下轨")

        drop_from_high = row['close'] / (recent['high'].max() + 1e-10) - 1
        if drop_from_high <= -0.035:
            score += 12
            reasons.append(f"20m回撤{drop_from_high:.1%}")
        elif drop_from_high <= -0.020:
            score += 8
            reasons.append(f"20m回撤{drop_from_high:.1%}")

        down_ratio = (recent['close'].diff().dropna() < 0).mean()
        if down_ratio >= 0.60:
            score += 5

        bb_pos = self._bb_position(row)
        if bb_pos <= -0.9:
            score += 6

        return score, "，".join(reasons) if reasons else "恐慌不足"

    def _climax_setup_score(self, df_1m, i):
        row = df_1m.iloc[i]
        recent = self._window(df_1m, i, TMonitorConfigV4.SETUP_WINDOW)
        extreme = self._window(df_1m, i, TMonitorConfigV4.EXTREME_WINDOW)

        score = 0
        reasons = []

        max_rsi = extreme['rsi14'].max()
        if max_rsi >= 85:
            score += 16
            reasons.append(f"RSI极高{max_rsi:.1f}")
        elif max_rsi >= 75:
            score += 12
            reasons.append(f"RSI高位{max_rsi:.1f}")
        elif max_rsi >= 68:
            score += 7

        touched_upper = (extreme['close'] >= extreme['bb_upper'] * 0.995).any()
        if touched_upper:
            score += 11
            reasons.append("触上轨")

        rise_from_low = row['close'] / (recent['low'].min() + 1e-10) - 1
        if rise_from_low >= 0.035:
            score += 12
            reasons.append(f"20m拉升{rise_from_low:.1%}")
        elif rise_from_low >= 0.020:
            score += 8
            reasons.append(f"20m拉升{rise_from_low:.1%}")

        up_ratio = (recent['close'].diff().dropna() > 0).mean()
        if up_ratio >= 0.60:
            score += 5

        bb_pos = self._bb_position(row)
        if bb_pos >= 0.9:
            score += 6

        return score, "，".join(reasons) if reasons else "亢奋不足"

    def _panic_exhaustion_score(self, df_1m, i):
        row = df_1m.iloc[i]
        confirm = self._window(df_1m, i, TMonitorConfigV4.CONFIRM_WINDOW)
        momentum = self._window(df_1m, i, TMonitorConfigV4.MOMENTUM_WINDOW)
        prev = df_1m.iloc[i - 1]
        prev2 = df_1m.iloc[i - 2]

        score = 0
        reasons = []

        prior_low = confirm.iloc[:-1]['low'].min()
        if row['low'] >= prior_low * 0.998:
            score += 12
            reasons.append("不再新低")
        if row['close'] >= prior_low * 1.006:
            score += 8
            reasons.append("脱离低点")

        if row['rsi14'] > prev['rsi14'] and prev['rsi14'] <= confirm['rsi14'].min() + 2:
            score += 12
            reasons.append("RSI回升")
        elif row['rsi14'] > prev['rsi14'] > prev2['rsi14']:
            score += 8
            reasons.append("RSI连续回升")

        last3_ret = self._momentum(momentum['close'].iloc[-3:])
        prev3_ret = self._momentum(momentum['close'].iloc[:3])
        if last3_ret > prev3_ret:
            score += 7
            reasons.append("跌速放缓")

        if row['close'] > row['ema5'] or row['close'] > prev['close']:
            score += 8
            reasons.append("价格转强")

        vol_ma20 = row.get('vol_ma20')
        if pd.notna(vol_ma20) and vol_ma20 > 0:
            if row['vol'] <= vol_ma20 * 1.8:
                score += 5
            if row['close'] > row['open'] and row['vol'] >= vol_ma20 * 0.7:
                score += 5

        return score, "，".join(reasons) if reasons else "未见衰竭"

    def _climax_exhaustion_score(self, df_1m, i):
        row = df_1m.iloc[i]
        confirm = self._window(df_1m, i, TMonitorConfigV4.CONFIRM_WINDOW)
        momentum = self._window(df_1m, i, TMonitorConfigV4.MOMENTUM_WINDOW)
        prev = df_1m.iloc[i - 1]
        prev2 = df_1m.iloc[i - 2]

        score = 0
        reasons = []

        prior_high = confirm.iloc[:-1]['high'].max()
        if row['high'] <= prior_high * 1.002:
            score += 12
            reasons.append("不再新高")
        if row['close'] <= prior_high * 0.994:
            score += 8
            reasons.append("脱离高点")

        if row['rsi14'] < prev['rsi14'] and prev['rsi14'] >= confirm['rsi14'].max() - 2:
            score += 12
            reasons.append("RSI回落")
        elif row['rsi14'] < prev['rsi14'] < prev2['rsi14']:
            score += 8
            reasons.append("RSI连续回落")

        last3_ret = self._momentum(momentum['close'].iloc[-3:])
        prev3_ret = self._momentum(momentum['close'].iloc[:3])
        if last3_ret < prev3_ret:
            score += 7
            reasons.append("涨速放缓")

        if row['close'] < row['ema5'] or row['close'] < prev['close']:
            score += 8
            reasons.append("价格转弱")

        vol_ma20 = row.get('vol_ma20')
        if pd.notna(vol_ma20) and vol_ma20 > 0:
            if row['vol'] >= vol_ma20 * 1.2 and row['close'] <= prev['close'] * 1.003:
                score += 7
                reasons.append("放量滞涨")
            elif row['vol'] <= vol_ma20 * 0.9:
                score += 4

        return score, "，".join(reasons) if reasons else "未见衰竭"

    def _location_score(self, df_1m, i, signal_type):
        recent = self._window(df_1m, i, 60)
        row = df_1m.iloc[i]
        pos = self._safe_range_position(row['close'], recent['low'].min(), recent['high'].max())
        if signal_type == 'BUY':
            if pos <= 0.12:
                return 10
            if pos <= 0.25:
                return 6
            return 0
        if pos >= 0.88:
            return 10
        if pos >= 0.75:
            return 6
        return 0

    @staticmethod
    def _classify_signal_label(signal_type, setup_reason, confirm_reason):
        """细化信号描述；只影响文案，不改变触发逻辑。"""
        setup = setup_reason or ""
        confirm = confirm_reason or ""

        if signal_type == 'BUY':
            has_confirmed_turn = "脱离低点" in confirm and "价格转强" in confirm
            has_slowdown = "跌速放缓" in confirm
            if "20m回撤" in setup and has_confirmed_turn:
                return "急杀衰竭转折买入"
            if "RSI极低" in setup and "RSI回升" in confirm and has_confirmed_turn:
                return "极端恐慌修复买入"
            if "RSI极低" in setup and "RSI回升" in confirm:
                return "极端恐慌修复观察买入"
            if "不再新低" in confirm and has_slowdown and has_confirmed_turn:
                return "低位钝化修复买入"
            if "不再新低" in confirm and ("RSI回升" in confirm or "价格转强" in confirm):
                return "低位修复观察买入"
            if "触下轨" in setup and "价格转强" in confirm:
                return "下轨修复观察买入"
            return "恐慌衰竭买入"

        if "放量滞涨" in confirm:
            return "放量滞涨卖出"
        has_confirmed_turn = "脱离高点" in confirm and "价格转弱" in confirm
        has_slowdown = "涨速放缓" in confirm
        if "20m拉升" in setup and has_confirmed_turn:
            return "冲高衰竭转折卖出"
        if "RSI极高" in setup and "RSI回落" in confirm and has_confirmed_turn:
            return "极端亢奋回落卖出"
        if "RSI极高" in setup and "RSI回落" in confirm:
            return "极端亢奋降温预警卖出"
        if "不再新高" in confirm and has_slowdown and has_confirmed_turn:
            return "高位钝化回落卖出"
        if "不再新高" in confirm and ("RSI回落" in confirm or has_slowdown):
            return "高位降温预警卖出"
        if "触上轨" in setup and "价格转弱" in confirm:
            return "上轨转弱预警卖出"
        return "亢奋衰竭卖出"

    def _generate_signal(self, df_1m, i):
        min_bars = max(
            TMonitorConfigV4.MIN_BARS if hasattr(TMonitorConfigV4, 'MIN_BARS') else 0,
            TMonitorConfigV4.SETUP_WINDOW,
            TMonitorConfigV4.BB_PERIOD,
            TMonitorConfigV4.RSI_PERIOD,
            TMonitorConfigV4.CONFIRM_WINDOW + 2,
        )
        if i < min_bars:
            return None, None, 0

        row = df_1m.iloc[i]
        close = row['close']
        rsi = row['rsi14']
        ts = row['datetime']
        if pd.isna(rsi) or pd.isna(row['bb_upper']) or pd.isna(row['bb_lower']):
            return None, None, 0

        self._refresh_rsi_wave_state(rsi)

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
        buy_score = buy_setup + buy_confirm + self._location_score(df_1m, i, 'BUY')

        sell_setup, sell_setup_reason = self._climax_setup_score(df_1m, i)
        sell_confirm, sell_confirm_reason = self._climax_exhaustion_score(df_1m, i)
        sell_score = sell_setup + sell_confirm + self._location_score(df_1m, i, 'SELL')

        candidates = []
        if (
            buy_setup >= TMonitorConfigV4.MIN_SETUP_SCORE and
            buy_confirm >= TMonitorConfigV4.MIN_CONFIRM_SCORE
        ):
            candidates.append(('BUY', buy_score, buy_setup_reason, buy_confirm_reason))
        if (
            sell_setup >= TMonitorConfigV4.MIN_SETUP_SCORE and
            sell_confirm >= TMonitorConfigV4.MIN_CONFIRM_SCORE
        ):
            candidates.append(('SELL', sell_score, sell_setup_reason, sell_confirm_reason))

        if not candidates:
            return None, None, 0

        signal_type, score, setup_reason, confirm_reason = max(candidates, key=lambda item: item[1])
        allowed, cooldown_msg = self._check_signal_cooldown(signal_type, ts, close)
        if not allowed:
            return None, cooldown_msg, 0

        repeat_penalty = self._calc_repeat_price_penalty(signal_type, close, ts)
        score = max(0, min(100, int(round(score - repeat_penalty))))
        if score < TMonitorConfigV4.MIN_SIGNAL_SCORE:
            return None, f"评分不足({score}分<{TMonitorConfigV4.MIN_SIGNAL_SCORE})", 0

        label = self._classify_signal_label(signal_type, setup_reason, confirm_reason)
        reason = f"{label}(RSI:{rsi:.1f}; {setup_reason}; {confirm_reason})"
        return signal_type, reason, score

    def _trigger_signal(self, signal_type, price, ts, reason, strength=None):
        """触发并记录V4信号。"""
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

        prefix = "【历史信号】" if self.is_backtest else "【V4信号】"
        msg = (
            f"{prefix}[{self.stock_name} {self.symbol}] **{signal_type}**{strength_tag} | "
            f"{reason} | 现价:**{price:.2f}** [{ts}]"
        )

        if self.is_backtest:
            tqdm.write(msg)
        else:
            logging.warning(msg)

        if self.push_msg:
            winsound.Beep(1500 if signal_type == 'BUY' else 500, 500)
            send_alert(msg)

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


class MonitorManagerV4(MonitorManagerV3):
    """V4多股票监控管理器。"""

    def _start_monitor(self, symbol):
        if symbol in self._monitor_events:
            return
        ev = Event()

        position_mgr = None
        if self.is_backtest:
            position_mgr = PositionManager(initial_shares=1000)

        monitor = TMonitorV4(
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
        logging.info(f"已启动V4监控: {symbol}")


if __name__ == "__main__":
    IS_BACKTEST = True
    # IS_BACKTEST = False

    symbols = ['600821']
    backtest_start = "2026-04-21 09:30"
    backtest_end = "2026-04-29 15:00"

    symbols_file = 'watchlist.txt'

    manager = MonitorManagerV4(
        symbols=symbols,
        is_backtest=IS_BACKTEST,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
        symbols_file=symbols_file,
        reload_interval_sec=5
    )

    logging.info("=" * 60)
    logging.info("启动V4做T监控 - 情绪衰竭拐点模式")
    logging.info("=" * 60)
    manager.start()
