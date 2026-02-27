"""
爆量突破A策略 (Breakout-A) 回测分析器

解析 scan_simple_YYYYMMDD-YYYYMMDD.txt 格式的选股信号文件，
回测多种入场 / 出场参数组合，回答：
  1. 选股正确率（胜率）
  2. 最佳买入时机（T+1/T+2/T+3 开盘；还是等到均线附近再买）
  3. 最佳卖出策略（固定止盈止损、均线跌破止损）
"""

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from utils.date_util import get_next_trading_day
from utils.file_util import read_stock_data

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────────────

@dataclass
class Signal:
    signal_date: str   # YYYYMMDD
    code: str
    name: str


@dataclass
class Trade:
    signal_date: str
    code: str
    name: str
    scenario: str = ''

    buy_date: str = ''
    buy_price: float = 0.0

    sell_date: str = ''
    sell_price: float = 0.0
    sell_reason: str = ''

    hold_days: int = 0
    profit_pct: float = 0.0
    is_win: bool = False
    is_valid: bool = False

    max_profit_pct: float = 0.0   # 持有期间最高浮盈（基于最高价）
    max_loss_pct: float = 0.0     # 持有期间最大浮亏（基于最低价）

    # 均线信息（买入当日）
    ma5_at_buy: float = 0.0
    ma20_at_buy: float = 0.0
    price_vs_ma5_pct: float = 0.0   # (开盘 - MA5) / MA5 × 100

    # 信号日信息
    signal_close: float = 0.0
    signal_vs_ma5_pct: float = 0.0  # (信号日收盘 - MA5) / MA5 × 100


@dataclass
class Stats:
    scenario_name: str
    total_signals: int = 0
    valid_trades: int = 0
    skipped: int = 0        # 未触发买入条件（如等均线超时）
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0    # 平均盈利（盈利笔）
    avg_loss: float = 0.0   # 平均亏损（亏损笔，正数表示亏损幅度）
    profit_loss_ratio: float = 0.0
    expected_value: float = 0.0
    avg_hold_days: float = 0.0
    max_single_profit: float = 0.0
    max_single_loss: float = 0.0
    trades: List[Trade] = field(default_factory=list)


# ──────────────────────────────────────────────────────
#  主回测类
# ──────────────────────────────────────────────────────

class BreakoutABacktester:
    DATA_PATH = './data/astocks'
    MAX_HOLD_DAYS = 20   # 最长持仓（交易日）
    MIN_HOLD_DAYS = 1    # T+1规则：至少持有1天，第2天才可卖出

    def __init__(self, signal_file: str, output_dir: str, data_path: str = None):
        self.signal_file = signal_file
        self.output_dir = output_dir
        self.data_path = data_path or self.DATA_PATH
        os.makedirs(output_dir, exist_ok=True)

    # ── 1. 解析信号文件 ─────────────────────────────────

    def parse_signals(self) -> List[Signal]:
        """解析 scan_simple_*.txt 格式文件"""
        signals = []
        current_date = None

        with open(self.signal_file, encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('='):
                    current_date = None
                    continue
                # 日期行：YYYY-MM-DD
                if re.match(r'^\d{4}-\d{2}-\d{2}$', line):
                    current_date = line.replace('-', '')
                    continue
                # 股票行：6位代码 + 名称（名称可能含空格）
                if current_date:
                    parts = line.split(None, 1)
                    if len(parts) >= 2 and re.match(r'^\d{6}$', parts[0]):
                        code = parts[0].strip()
                        name = parts[1].strip()
                        signals.append(Signal(signal_date=current_date, code=code, name=name))

        return signals

    # ── 2. 加载股票数据 + 计算均线 ─────────────────────

    def _load_df(self, code: str) -> Optional[pd.DataFrame]:
        clean_code = code.split('.')[0]
        df = read_stock_data(clean_code, self.data_path)
        if df is None or df.empty:
            return None
        df = df.sort_values('日期').reset_index(drop=True)
        df['日期_str'] = df['日期'].dt.strftime('%Y%m%d')
        df['MA5']  = df['收盘'].rolling(5).mean()
        df['MA10'] = df['收盘'].rolling(10).mean()
        df['MA20'] = df['收盘'].rolling(20).mean()
        return df

    def _find_idx(self, df: pd.DataFrame, date_str: str) -> Optional[int]:
        """在 df 中查找日期对应的整数行索引，找不到返回 None"""
        mask = df['日期_str'] == date_str
        if not mask.any():
            return None
        return int(df.index[mask][0])

    def _nth_after(self, df: pd.DataFrame, signal_date: str, n: int) -> Optional[Tuple[int, str]]:
        """
        获取信号日之后第 n 个交易日的 (行索引, 日期字符串)。
        n=1 → T+1 (次日), n=2 → T+2, 以此类推。
        直接在已排序的 df 里取 signal_idx + n，不依赖日历（数据文件本身只含交易日）。
        """
        sig_idx = self._find_idx(df, signal_date)
        if sig_idx is None:
            return None
        target = sig_idx + n
        if target >= len(df):
            return None
        row = df.iloc[target]
        return target, row['日期_str']

    # ── 3. 单笔持仓模拟 ────────────────────────────────

    def _simulate(self,
                  df: pd.DataFrame,
                  buy_idx: int,
                  buy_price: float,
                  exit_rule: str,
                  profit_target: float,
                  stop_loss: float,
                  intraday_exit: bool = False) -> Tuple[str, float, int, str, float, float]:
        """
        从 buy_idx 开始模拟持仓，返回 (sell_date, sell_price, hold_days, sell_reason, max_profit, max_loss)

        exit_rule:
          'fixed_pnl'       : 盈利 >= profit_target 或 亏损 >= stop_loss 时平仓
                              • intraday_exit=False（默认）: 收盘价触发，以收盘价成交
                              • intraday_exit=True         : 盘中最高/最低触发，以目标价成交（更贴近实战挂单）
          'sell_at_open'    : 满足 T+1 持仓规则的第一个交易日**开盘**直接卖出（高周转模式）
          'ma5_trail'       : 收盘跌破 MA5 时平仓
          'ma10_trail'      : 收盘跌破 MA10 时平仓
          'ma20_trail'      : 收盘跌破 MA20 时平仓
          'ma5_trail_sl'    : 收盘跌破 MA5 或 亏损 >= stop_loss 时平仓
          'ma5_trail_pt'    : 收盘跌破 MA5 或 盈利 >= profit_target 时平仓（趋势跟踪+止盈）
          'ma5_trail_pt_sl' : 三合一：MA5跌破 / 止盈 / 止损

        T+1 规则说明：
          买入日本身计为 hold_days=1，满足 hold_days > MIN_HOLD_DAYS(=1) 才允许卖出，
          即最早在 hold_days=2 的当天（买入后的下一个交易日）触发卖出。
          这保证了 A 股 T+1 交易规则：当天买入，最早次日卖出。
        """
        max_profit = 0.0
        max_loss   = 0.0
        max_idx    = len(df) - 1

        for i in range(buy_idx, min(buy_idx + self.MAX_HOLD_DAYS, max_idx + 1)):
            row   = df.iloc[i]
            open_ = row['开盘']
            close = row['收盘']
            high  = row['最高']
            low   = row['最低']
            ma5   = row.get('MA5',  float('nan'))
            ma10  = row.get('MA10', float('nan'))
            ma20  = row.get('MA20', float('nan'))

            hold_days = i - buy_idx + 1

            intraday_max = (high  - buy_price) / buy_price * 100
            intraday_min = (low   - buy_price) / buy_price * 100
            close_pct    = (close - buy_price) / buy_price * 100

            max_profit = max(max_profit, intraday_max)
            max_loss   = min(max_loss,   intraday_min)

            # T+1 规则：至少持有 MIN_HOLD_DAYS 天后才可触发卖出
            if hold_days > self.MIN_HOLD_DAYS:
                triggered  = False
                reason     = ''
                sell_price = close   # 默认以收盘价成交

                if exit_rule == 'sell_at_open':
                    # 高周转：满足持仓规则的第一日开盘直接卖出
                    triggered  = True
                    sell_price = open_
                    reason     = '开盘卖出'

                elif exit_rule == 'fixed_pnl' and intraday_exit:
                    # 盘中价格触发：更贴近实战挂止损/止盈委托单
                    target_price = buy_price * (1 + profit_target / 100)
                    stop_price   = buy_price * (1 - stop_loss   / 100)
                    if low <= stop_price:
                        # 止损优先（保守：若同一天止损和止盈价都被触及，以止损成交）
                        triggered  = True
                        sell_price = stop_price
                        reason     = f'止损{stop_loss:.0f}%(盘中)'
                    elif high >= target_price:
                        triggered  = True
                        sell_price = target_price
                        reason     = f'止盈{profit_target:.0f}%(盘中)'

                elif exit_rule == 'fixed_pnl':
                    if close_pct >= profit_target:
                        triggered  = True
                        reason     = f'止盈{profit_target:.0f}%'
                        # 以目标价成交（模拟收盘前挂好止盈限价单），避免收盘价远超目标虚增收益
                        sell_price = buy_price * (1 + profit_target / 100)
                    elif close_pct <= -stop_loss:
                        triggered  = True
                        reason     = f'止损{stop_loss:.0f}%'
                        sell_price = buy_price * (1 - stop_loss / 100)

                elif exit_rule == 'ma5_trail':
                    if pd.notna(ma5) and close < ma5:
                        triggered, reason = True, '跌破MA5'

                elif exit_rule == 'ma10_trail':
                    if pd.notna(ma10) and close < ma10:
                        triggered, reason = True, '跌破MA10'

                elif exit_rule == 'ma20_trail':
                    if pd.notna(ma20) and close < ma20:
                        triggered, reason = True, '跌破MA20'

                elif exit_rule == 'ma5_trail_sl':
                    if pd.notna(ma5) and close < ma5:
                        triggered, reason = True, '跌破MA5'
                    elif close_pct <= -stop_loss:
                        triggered, reason = True, f'止损{stop_loss:.0f}%'

                elif exit_rule == 'ma5_trail_pt':
                    if pd.notna(ma5) and close < ma5:
                        triggered, reason = True, '跌破MA5'
                    elif close_pct >= profit_target:
                        triggered, reason = True, f'止盈{profit_target:.0f}%'

                elif exit_rule == 'ma5_trail_pt_sl':
                    if pd.notna(ma5) and close < ma5:
                        triggered, reason = True, '跌破MA5'
                    elif close_pct >= profit_target:
                        triggered, reason = True, f'止盈{profit_target:.0f}%'
                    elif close_pct <= -stop_loss:
                        triggered, reason = True, f'止损{stop_loss:.0f}%'

                if triggered:
                    return row['日期_str'], sell_price, hold_days, reason, max_profit, max_loss

        # 达到最大持仓天数或数据截止
        last_i    = min(buy_idx + self.MAX_HOLD_DAYS - 1, max_idx)
        last_row  = df.iloc[last_i]
        hold_days = last_i - buy_idx + 1
        is_maxed  = hold_days >= self.MAX_HOLD_DAYS
        reason    = f'持满{self.MAX_HOLD_DAYS}天' if is_maxed else '数据截止'
        return last_row['日期_str'], last_row['收盘'], hold_days, reason, max_profit, max_loss

    # ── 4. 运行单个场景 ────────────────────────────────

    def run_scenario(self,
                     signals: List[Signal],
                     scenario_name: str,
                     entry_delay: int = 1,
                     exit_rule: str = 'fixed_pnl',
                     profit_target: float = 5.0,
                     stop_loss: float = 5.0,
                     near_ma5_pct: float = None,
                     near_ma5_max_wait: int = 5,
                     intraday_exit: bool = False,
                     max_ma5_pct: float = None,
                     min_ma5_pct: float = None) -> Stats:
        """
        运行单个场景回测。

        entry_delay      : 入场延迟天数（1=T+1开盘, 2=T+2开盘, 3=T+3开盘）
        near_ma5_pct     : 若设置，则从 T+1 起等待开盘价在 MA5 上方 X% 以内才买入，
                           最多等 near_ma5_max_wait 天，否则跳过。
        max_ma5_pct      : 若设置，入场时开盘价距MA5超过此比例则**跳过不买**
                           （直接过滤，不等待回踩；用于排除追高入场）。
        min_ma5_pct      : 若设置，入场时开盘价距MA5低于此比例则**跳过不买**
                           （与 max_ma5_pct 组合可精确限定入场的MA5距离区间）。
                           传 None 表示无下限；传 0.0 表示必须在MA5之上。
        """
        stats  = Stats(scenario_name=scenario_name, total_signals=len(signals))
        trades: List[Trade] = []

        # 去重：若同一只股票还在持仓中，不重复买入
        holding: Dict[str, str] = {}   # code -> sell_date (YYYYMMDD)

        _cache: Dict[str, Optional[pd.DataFrame]] = {}   # 数据缓存

        for sig in tqdm(signals, desc=f'  {scenario_name}', leave=False, ncols=100):
            # 懒加载
            if sig.code not in _cache:
                _cache[sig.code] = self._load_df(sig.code)
            df = _cache[sig.code]
            if df is None:
                continue

            # ── 确定买入日和买入价 ──
            buy_idx    = None
            buy_price  = None
            buy_date   = None
            ma5_at_buy = 0.0
            ma20_at_buy = 0.0
            price_vs_ma5 = 0.0

            if near_ma5_pct is not None:
                # 等待开盘在 MA5 上方 near_ma5_pct% 以内
                for delay in range(1, near_ma5_max_wait + 1):
                    result = self._nth_after(df, sig.signal_date, delay)
                    if result is None:
                        break
                    idx, d_str = result
                    row = df.iloc[idx]
                    ma5  = row['MA5']
                    _open = row['开盘']
                    if pd.notna(ma5) and ma5 > 0:
                        pct_above = (_open - ma5) / ma5 * 100
                        if pct_above <= near_ma5_pct:
                            buy_idx      = idx
                            buy_price    = _open
                            buy_date     = d_str
                            ma5_at_buy   = ma5
                            price_vs_ma5 = pct_above
                            break
                if buy_idx is None:
                    stats.skipped += 1
                    continue
            else:
                result = self._nth_after(df, sig.signal_date, entry_delay)
                if result is None:
                    continue
                buy_idx, buy_date = result
                row         = df.iloc[buy_idx]
                buy_price   = row['开盘']
                ma5_val     = row['MA5']
                ma20_val    = row['MA20']
                ma5_at_buy  = ma5_val  if pd.notna(ma5_val)  else 0.0
                ma20_at_buy = ma20_val if pd.notna(ma20_val) else 0.0
                if ma5_at_buy > 0:
                    price_vs_ma5 = (buy_price - ma5_at_buy) / ma5_at_buy * 100

                # ── MA5距离区间过滤：排除追高 / 限定入场窗口 ──
                if ma5_at_buy > 0:
                    if max_ma5_pct is not None and price_vs_ma5 > max_ma5_pct:
                        stats.skipped += 1
                        continue
                    if min_ma5_pct is not None and price_vs_ma5 <= min_ma5_pct:
                        stats.skipped += 1
                        continue

            # ── 持仓去重检查 ──
            if sig.code in holding and buy_date <= holding[sig.code]:
                stats.skipped += 1
                continue

            # ── 一字涨停过滤（开盘=最高=最低，无法买入） ──
            buy_row = df.iloc[buy_idx]
            if abs(buy_row['最高'] - buy_row['最低']) < 0.005:
                continue

            # ── 信号日 MA 信息 ──
            signal_vs_ma5 = 0.0
            sig_idx = self._find_idx(df, sig.signal_date)
            if sig_idx is not None:
                sig_row  = df.iloc[sig_idx]
                sig_close = sig_row['收盘']
                sig_ma5   = sig_row['MA5']
                if pd.notna(sig_ma5) and sig_ma5 > 0:
                    signal_vs_ma5 = (sig_close - sig_ma5) / sig_ma5 * 100
            else:
                sig_close = 0.0

            # ── 模拟持仓 ──
            sell_date, sell_price, hold_days, sell_reason, max_p, max_l = self._simulate(
                df, buy_idx, buy_price, exit_rule, profit_target, stop_loss,
                intraday_exit=intraday_exit
            )

            profit_pct = (sell_price - buy_price) / buy_price * 100

            trade = Trade(
                signal_date=sig.signal_date,
                code=sig.code,
                name=sig.name,
                scenario=scenario_name,
                buy_date=buy_date,
                buy_price=buy_price,
                sell_date=sell_date,
                sell_price=sell_price,
                sell_reason=sell_reason,
                hold_days=hold_days,
                profit_pct=profit_pct,
                is_win=profit_pct > 0,
                is_valid=True,
                max_profit_pct=max_p,
                max_loss_pct=max_l,
                ma5_at_buy=ma5_at_buy,
                ma20_at_buy=ma20_at_buy,
                price_vs_ma5_pct=price_vs_ma5,
                signal_close=sig_close,
                signal_vs_ma5_pct=signal_vs_ma5,
            )
            trades.append(trade)

            # 更新持仓记录
            holding[sig.code] = sell_date

        # ── 统计 ──
        stats.valid_trades = len(trades)
        stats.trades       = trades

        if trades:
            wins   = [t for t in trades if t.is_win]
            losses = [t for t in trades if not t.is_win]
            stats.win_trades   = len(wins)
            stats.loss_trades  = len(losses)
            stats.win_rate     = len(wins) / len(trades) * 100

            avg_w = sum(t.profit_pct for t in wins)   / len(wins)   if wins   else 0.0
            avg_l = abs(sum(t.profit_pct for t in losses) / len(losses)) if losses else 0.0
            stats.avg_win  = avg_w
            stats.avg_loss = avg_l
            stats.profit_loss_ratio = avg_w / avg_l if avg_l > 0 else 0.0

            wr = stats.win_rate / 100
            stats.expected_value = wr * avg_w - (1 - wr) * avg_l

            stats.avg_hold_days      = sum(t.hold_days  for t in trades) / len(trades)
            stats.max_single_profit  = max(t.profit_pct for t in trades)
            stats.max_single_loss    = min(t.profit_pct for t in trades)

        return stats

    # ── 5. 运行全部预设场景 ─────────────────────────────

    def run_all(self) -> Tuple[List[Signal], Dict[str, Stats]]:
        print(f"\n{'=' * 65}")
        print(f"  爆量突破A策略 回测分析")
        print(f"  信号文件: {os.path.basename(self.signal_file)}")
        print(f"{'=' * 65}\n")

        signals = self.parse_signals()
        print(f"[1/8] 解析信号文件... 共 {len(signals)} 条信号，"
              f"{len(set(s.code for s in signals))} 只不同股票\n")

        results: Dict[str, Stats] = {}

        # ── A. 入场时机对比（统一止盈止损 5%/5%）──────────────
        print("[2/8] 入场时机对比...")
        for delay in [1, 2, 3]:
            name = f'T+{delay}开盘_5%止盈5%止损'
            results[name] = self.run_scenario(
                signals, name, entry_delay=delay,
                exit_rule='fixed_pnl', profit_target=5, stop_loss=5)

        # 近 MA5 买入
        for thr, lbl in [(5.0, '5%以内'), (2.0, '2%以内')]:
            name = f'T+1~5_近MA5({lbl})_5%止盈5%止损'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='fixed_pnl', profit_target=5, stop_loss=5,
                near_ma5_pct=thr, near_ma5_max_wait=5)

        # ── B. 止盈止损参数矩阵（T+1 买入）──────────────────
        print("[3/8] 止盈止损参数矩阵（T+1 买入）...")
        PROFIT_TARGETS = [3, 5, 8, 10, 15]
        STOP_LOSSES    = [3, 5, 8]
        for pt in PROFIT_TARGETS:
            for sl in STOP_LOSSES:
                name = f'T+1_止盈{pt}%_止损{sl}%'
                results[name] = self.run_scenario(
                    signals, name, entry_delay=1,
                    exit_rule='fixed_pnl', profit_target=pt, stop_loss=sl)

        # ── C. 均线跟踪止损（T+1 买入，仅 MA5）─────────────
        print("[4/8] 均线跟踪止损（仅MA5）...")
        name = 'T+1_MA5跟踪止损'
        results[name] = self.run_scenario(
            signals, name, entry_delay=1, exit_rule='ma5_trail')

        # 均线跟踪 + 固定止损
        for sl in [5, 8]:
            name = f'T+1_MA5跟踪+止损{sl}%'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='ma5_trail_sl', stop_loss=sl)

        # 均线跟踪 + 止盈
        for pt in [8, 10]:
            name = f'T+1_MA5跟踪+止盈{pt}%'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='ma5_trail_pt', profit_target=pt)

        # 三合一（MA5 + 止盈 + 止损）
        for pt, sl in [(8, 5), (10, 5), (8, 8)]:
            name = f'T+1_MA5跟踪_止盈{pt}%止损{sl}%'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='ma5_trail_pt_sl', profit_target=pt, stop_loss=sl)

        # ── D. 入场质量优化（MA5距离过滤 + 止盈>止损）──────
        print("[5/8] 入场质量优化（MA5距离过滤）...")

        # D1. T+1 入场，限制买入时距MA5不超过X%
        for max_dist in [3.0, 5.0]:
            for pt, sl in [(5, 3), (8, 3), (8, 5), (10, 5)]:
                name = f'T+1_MA5≤{max_dist:.0f}%_止盈{pt}%止损{sl}%'
                results[name] = self.run_scenario(
                    signals, name, entry_delay=1,
                    exit_rule='fixed_pnl', profit_target=pt, stop_loss=sl,
                    max_ma5_pct=max_dist)

        # D2. 近MA5(2%以内) 等待买入 + 不同止盈止损组合
        for pt, sl in [(5, 3), (8, 3), (8, 5), (10, 5)]:
            name = f'近MA5(2%)_止盈{pt}%止损{sl}%'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='fixed_pnl', profit_target=pt, stop_loss=sl,
                near_ma5_pct=2.0, near_ma5_max_wait=5)

        # D3. T+2 入场 + MA5距离过滤
        for max_dist in [3.0, 5.0]:
            for pt, sl in [(5, 3), (5, 5), (8, 5)]:
                name = f'T+2_MA5≤{max_dist:.0f}%_止盈{pt}%止损{sl}%'
                results[name] = self.run_scenario(
                    signals, name, entry_delay=2,
                    exit_rule='fixed_pnl', profit_target=pt, stop_loss=sl,
                    max_ma5_pct=max_dist)

        # ── E. 高周转专项对比（尽快出局，追求低持仓天数）──────
        print("[6/8] 高周转策略专项...")

        # D1. 次日/后日开盘直接卖出（无条件退出，看次日开盘表现）
        for delay, sell_label in [(1, 'T+2'), (2, 'T+3')]:
            name = f'T+1买入_{sell_label}开盘卖出'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='sell_at_open')
            # entry_delay 只影响买入日，sell_at_open 在 MIN_HOLD_DAYS 满足后第一日开盘卖
            # 为区分 T+2/T+3 开盘，用 entry_delay 不变，而 MIN_HOLD_DAYS 通过继承固定为1
            # 注：sell_at_open 总在 hold_days==2 时触发，即 T+2 开盘；"T+3开盘" 需 entry=2
        # 修正：T+3 开盘应 entry_delay=1 + 再持一天 → 用 entry_delay=2 买，T+1规则下 T+3 开盘
        name = 'T+2买入_T+3开盘卖出'
        results[name] = self.run_scenario(
            signals, name, entry_delay=2,
            exit_rule='sell_at_open')

        # D2. 盘中价格触发止盈止损（最贴近实战挂委托单场景）
        for pt, sl in [(3, 3), (5, 3), (5, 5), (8, 5), (10, 5)]:
            name = f'T+1买入_止盈{pt}%止损{sl}%(盘中触发)'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='fixed_pnl', profit_target=pt, stop_loss=sl,
                intraday_exit=True)

        # D3. 近MA5买入 + 盘中触发（高质量入场+快速退出）
        name = 'T+1~5_近MA5(2%)_止盈5%止损3%(盘中)'
        results[name] = self.run_scenario(
            signals, name, entry_delay=1,
            exit_rule='fixed_pnl', profit_target=5, stop_loss=3,
            near_ma5_pct=2.0, near_ma5_max_wait=5,
            intraday_exit=True)

        # ── F. 入场位置分析（按相对MA5距离分桶）──────────────
        # 目的：量化"在MA5不同位置入场"的胜率/盈亏差异，回答"什么位置入场更优"
        # 用统一的固定止盈8%/止损5%比较，避免出场策略干扰入场分析
        print("[7/8] 入场位置分析（MA5距离分桶）...")
        # 5个分桶：≤0% / 0~3% / 3~8% / 8~15% / >15%
        ENTRY_BUCKETS = [
            ('MA5以下',    None,  0.0),   # price ≤ MA5
            ('MA5+0~3%',   0.0,   3.0),
            ('MA5+3~8%',   3.0,   8.0),
            ('MA5+8~15%',  8.0,  15.0),
            ('MA5>15%',   15.0,  None),
        ]
        for label, lo, hi in ENTRY_BUCKETS:
            name = f'T+1_入场{label}_止盈8%止损5%'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='fixed_pnl', profit_target=8, stop_loss=5,
                min_ma5_pct=lo, max_ma5_pct=hi)

        # 同一批桶，用盘中触发验证是否一致
        for label, lo, hi in ENTRY_BUCKETS:
            name = f'T+1_入场{label}_止盈8%止损5%(盘中)'
            results[name] = self.run_scenario(
                signals, name, entry_delay=1,
                exit_rule='fixed_pnl', profit_target=8, stop_loss=5,
                min_ma5_pct=lo, max_ma5_pct=hi,
                intraday_exit=True)

        print("[8/8] 生成报告...\n")
        return signals, results

    # ── 6. 生成 Markdown 报告 ──────────────────────────

    # ── 6a. 进阶统计指标 ────────────────────────────────

    def _calc_advanced_stats(self, trades: List[Trade]) -> Dict:
        """
        计算年化收益率、夏普比率、最大回撤、盈亏因子等进阶指标。

        方法说明：
          - 日均收益率 = profit_pct / hold_days（每笔交易均摊到持仓天数）
          - 年化收益率 = mean(日均收益率) × 250
          - 年化夏普    = mean(日均) / std(日均) × √250  （假设无风险利率=0）
          - 最大回撤    = 基于按买入日排序的顺序权益曲线（单仓顺序模拟）
          - 盈亏因子    = Σ盈利 / |Σ亏损|
        """
        import math, statistics

        if not trades:
            return {}

        n      = len(trades)
        wins   = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]

        # 每笔交易的日均收益率（%/天）
        daily_rets = [t.profit_pct / t.hold_days for t in trades if t.hold_days > 0]
        # 注意：mean(p_i/d_i) 会被"快速止盈"的交易拉高（如3天+10%=3.3%/天），
        # 改用 mean(p_i)/mean(d_i) 即"总收益/总持仓天数"，更保守也更准确。
        mean_profit   = statistics.mean(t.profit_pct for t in trades)
        mean_hold     = statistics.mean(t.hold_days  for t in trades if t.hold_days > 0)
        mean_daily    = mean_profit / mean_hold if mean_hold > 0 else 0.0
        std_daily     = statistics.stdev(daily_rets) if len(daily_rets) > 1 else 0.0

        annualized_return = mean_daily * 250
        # 夏普仍用 mean(p_i/d_i) 的标准差（反映单笔日收益的波动性）
        mean_daily_indiv = statistics.mean(daily_rets)
        sharpe = (mean_daily * 250) / (std_daily * math.sqrt(250)) if std_daily > 0 else 0.0

        # 盈亏因子
        total_gain = sum(t.profit_pct for t in wins)   if wins   else 0.0
        total_loss = abs(sum(t.profit_pct for t in losses)) if losses else 1e-9
        profit_factor = total_gain / total_loss

        # 顺序权益曲线 → 最大回撤（单仓假设）
        sorted_trades = sorted(trades, key=lambda t: t.buy_date or '')
        equity = 100.0
        peak   = 100.0
        max_dd = 0.0
        for t in sorted_trades:
            equity *= (1 + t.profit_pct / 100)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)

        # 顺序复利（仅用于计算最大回撤，本身不作展示：数字无实际意义）
        calmar = annualized_return / max_dd if max_dd > 0 else 0.0

        # 单仓期间简单总收益：若始终持有一只股票（顺序不重叠），n笔均摊到回测天数
        # = 期望值 × n / period_trading_days × period_trading_days = 期望值 × n（简单累加）
        simple_total = sum(t.profit_pct for t in trades)  # 所有笔简单加总（无复利）

        # 最大连胜/连亏
        max_win_streak = max_loss_streak = cur_w = cur_l = 0
        for t in sorted_trades:
            if t.is_win:
                cur_w += 1; cur_l = 0
                max_win_streak = max(max_win_streak, cur_w)
            else:
                cur_l += 1; cur_w = 0
                max_loss_streak = max(max_loss_streak, cur_l)

        # 回测期间总自然日数
        buy_dates  = [t.buy_date  for t in trades if t.buy_date]
        sell_dates = [t.sell_date for t in trades if t.sell_date]
        period_days = 0
        if buy_dates and sell_dates:
            d1 = datetime.strptime(min(buy_dates),  '%Y%m%d')
            d2 = datetime.strptime(max(sell_dates), '%Y%m%d')
            period_days = (d2 - d1).days

        return dict(
            n=n,
            win_rate=len(wins) / n * 100,
            mean_profit=statistics.mean(t.profit_pct for t in trades),
            std_profit=statistics.stdev(t.profit_pct for t in trades) if n > 1 else 0.0,
            annualized_return=annualized_return,
            sharpe=sharpe,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            calmar=calmar,
            simple_total=simple_total,
            max_win_streak=max_win_streak,
            max_loss_streak=max_loss_streak,
            period_days=period_days,
        )

    # ── 6b. 解析策略名称 ────────────────────────────────

    def _parse_strategy_name(self, name: str) -> Dict:
        """从策略名称中解析入场/出场参数，用于生成可读的交易规则。"""
        import re
        p: Dict = {}

        # 入场方式
        if '近MA5' in name:
            m = re.search(r'近MA5\((\d+\.?\d*)%', name)
            p['entry_type']    = 'near_ma5'
            p['near_ma5_pct']  = float(m.group(1)) if m else 2.0
            p['near_ma5_wait'] = 5
        elif name.startswith('T+2') or '_T+2_' in name:
            p['entry_type']  = 'T+2'
            p['entry_delay'] = 2
        else:
            p['entry_type']  = 'T+1'
            p['entry_delay'] = 1

        # MA5距离上限过滤
        m = re.search(r'MA5≤(\d+\.?\d*)%', name)
        p['max_ma5_pct'] = float(m.group(1)) if m else None

        # 止盈
        m = re.search(r'止盈(\d+)%', name)
        p['profit_target'] = int(m.group(1)) if m else 5

        # 止损
        m = re.search(r'止损(\d+)%', name)
        p['stop_loss'] = int(m.group(1)) if m else 5

        # 盘中触发
        p['intraday'] = '盘中' in name

        return p

    # ── 6c. 执行摘要 & 完整交易规则 ─────────────────────

    def _make_executive_summary(self,
                                signals: List[Signal],
                                results: Dict[str, Stats],
                                ranked: List) -> str:
        """生成报告顶部的执行摘要：进阶指标 + 完整可执行交易方案。"""
        L: List[str] = []

        if not ranked:
            return ''

        top_name, top_s = ranked[0]
        p = self._parse_strategy_name(top_name)
        adv = self._calc_advanced_stats(top_s.trades)

        # ── 进阶指标卡片 ──────────────────────────────────
        L += [
            '## 🎯 执行摘要\n',
            '### 最优策略核心指标\n',
            f'> **最优策略**: `{top_name}`',
            f'> 基于 **{adv.get("n", 0)}** 笔有效交易 / 回测区间 **{adv.get("period_days", 0)}** 自然日\n',
            '| 指标 | 数值 | 说明 |',
            '|------|------|------|',
            f'| 胜率 | **{adv.get("win_rate", 0):.1f}%** | 盈利交易占比 |',
            f'| 均盈 / 均亏 | **+{top_s.avg_win:.2f}% / -{top_s.avg_loss:.2f}%** | 平均单笔盈亏 |',
            f'| 盈亏比 | **{top_s.profit_loss_ratio:.2f}** | 均盈 ÷ 均亏 |',
            f'| 单笔期望值 | **{top_s.expected_value:+.2f}%** | 每笔交易平均预期收益 |',
            f'| 均持天数 | **{top_s.avg_hold_days:.1f} 个交易日** | |',
            f'| **年化收益率** | **{adv.get("annualized_return", 0):.1f}%** | 期望值÷均持天数×250，单仓满仓估算，实际受并发持仓和空仓期影响 |',
            f'| **夏普比率** | **{adv.get("sharpe", 0):.2f}** | ≥1 可用，≥2 优秀 |',
            f'| **盈亏因子** | **{adv.get("profit_factor", 0):.2f}** | 总盈利÷总亏损，>1.5 较好 |',
            f'| **最大回撤** | **{adv.get("max_drawdown", 0):.1f}%** | 顺序单仓模拟（多仓并发时实际回撤更小） |',
            f'| Calmar比率 | **{adv.get("calmar", 0):.2f}** | 年化收益÷最大回撤 |',
            f'| 最大连胜 / 连亏 | {adv.get("max_win_streak", 0)}连胜 / {adv.get("max_loss_streak", 0)}连亏 | |',
            f'| 全笔简单总收益 | {adv.get("simple_total", 0):+.1f}% | 所有笔收益率直接相加（无复利），反映策略"总创造价值" |',
            '',
        ]

        # ── 各主要策略进阶指标对比 ────────────────────────
        key_names = [
            top_name,
            'T+1~5_近MA5(2%以内)_5%止盈5%止损',
            'T+1_止盈3%_止损8%',
            'T+1开盘_5%止盈5%止损',
            'T+1_止盈5%_止损5%',
        ]
        L += [
            '\n### 主要策略进阶指标对比\n',
            '| 策略 | 年化收益 | 夏普 | 盈亏因子 | 最大回撤 | Calmar |',
            '|------|----------|------|----------|----------|--------|',
        ]
        for kn in key_names:
            if kn in results and results[kn].valid_trades > 0:
                s   = results[kn]
                adv_k = self._calc_advanced_stats(s.trades)
                mk = '🥇 ' if kn == top_name else ''
                L.append(f'| {mk}{kn} | {adv_k["annualized_return"]:.1f}% | '
                         f'{adv_k["sharpe"]:.2f} | {adv_k["profit_factor"]:.2f} | '
                         f'{adv_k["max_drawdown"]:.1f}% | {adv_k["calmar"]:.2f} |')

        # ── 完整交易方案 ──────────────────────────────────
        L += ['\n---\n', '### 📋 最优策略完整交易方案（可直接执行）\n']

        # 解析参数
        entry_type   = p.get('entry_type', 'T+1')
        max_ma5      = p.get('max_ma5_pct')
        near_ma5_pct = p.get('near_ma5_pct')
        near_wait    = p.get('near_ma5_wait', 5)
        pt           = p.get('profit_target') or 5
        sl           = p.get('stop_loss') or 5
        intraday     = p.get('intraday', False)

        # 开仓条件
        L.append('#### 🟢 开仓条件\n')
        L.append('1. **信号来源**：每个交易日收盘后，由爆量突破A策略筛选出候选股（信号日=T）。')
        if entry_type == 'near_ma5':
            L.append(f'2. **入场时机**：T+1 开盘起，每日开盘时检查，等待开盘价回落到 MA5 **上方 {near_ma5_pct:.0f}% 以内**；'
                     f'最多等待 {near_wait} 个交易日，超时则放弃该信号。')
            L.append('3. **买入价**：满足条件当日的**开盘价**。')
        elif entry_type == 'T+2':
            L.append('2. **入场时机**：信号日后第 **2个交易日（T+2）** 开盘时买入。')
            L.append('3. **买入价**：T+2 日的**开盘价**。')
        else:
            L.append('2. **入场时机**：信号日后第 **1个交易日（T+1）** 开盘时买入。')
            L.append('3. **买入价**：T+1 日的**开盘价**。')

        if max_ma5 is not None:
            L.append(f'4. **入场过滤（关键）**：买入日开盘价必须在 MA5 **上方 ≤{max_ma5:.0f}%** 以内；'
                     f'若开盘价偏离 MA5 超过 {max_ma5:.0f}%，**放弃不追高**，等待下一个信号。')
        elif near_ma5_pct is not None:
            L.append(f'4. **入场过滤**：等待价格回踩至 MA5 上方 {near_ma5_pct:.0f}% 以内，避免追高。')

        # 持仓条件
        L.append('\n#### 🟡 持仓管理\n')
        L.append(f'1. **T+1 规则**：买入当日不可卖出（A股规则），最早于**买入次日**开始触发止盈止损。')
        L.append(f'2. **最长持仓**：{self.MAX_HOLD_DAYS} 个交易日，超时下一交易日开盘卖出。')
        L.append('3. **不重复建仓**：同一只股票在持仓期间若再次出现信号，跳过。')

        # 清仓条件
        L.append('\n#### 🔴 清仓条件（买入次日收盘起触发）\n')
        if intraday:
            L.append(f'1. **止盈**：盘中最高价 ≥ 买入价 × {1 + pt/100:.2f}（即盈利 **{pt}%**）→ 以止盈价挂限价委托，当日成交。')
            L.append(f'2. **止损**：盘中最低价 ≤ 买入价 × {1 - sl/100:.2f}（即亏损 **{sl}%**）→ 以止损价挂限价委托，当日成交。止损优先。')
        else:
            L.append(f'1. **止盈**：当日**收盘价** ≥ 买入价 × {1 + pt/100:.2f}（即收盘盈利 ≥ **{pt}%**）→ 以收盘价卖出。')
            L.append(f'2. **止损**：当日**收盘价** ≤ 买入价 × {1 - sl/100:.2f}（即收盘亏损 ≥ **{sl}%**）→ 以收盘价卖出。')
        L.append(f'3. **超时清仓**：持满 {self.MAX_HOLD_DAYS} 个交易日仍未触发，下一交易日开盘卖出。')

        # 风险提示
        L.append('\n#### ⚠️ 风险提示与注意事项\n')
        L.append(f'- **样本量**：当前回测仅 {adv.get("n", 0)} 笔，统计结论具有一定局限性，建议持续积累更多信号后复核参数。')
        L.append(f'- **最大连亏**：历史最多 **{adv.get("max_loss_streak", 0)} 笔连续亏损**，需做好心态管理，不因连亏轻易放弃策略。')
        dd = adv.get("max_drawdown", 0)
        L.append(f'- **最大回撤**：单仓顺序执行的历史最大回撤约 **{dd:.1f}%**，实际多仓并发时回撤可能更小。')
        L.append(f'- **年化收益率 {adv.get("annualized_return", 0):.1f}%** 为理论估算'
                 f'（=期望值÷均持天数×250，假设单仓始终满仓）。'
                 f'实际有并发持仓、空仓期、交易成本等因素，真实收益会低于此值。')
        L.append('- **交易成本**：当前回测未扣除佣金和印花税（约 0.1~0.15% 双向），建议在期望值基础上再扣除约 0.2%/笔。')

        L.append('\n---\n')
        return '\n'.join(L)

    def _calc_group(self, group: List[Trade]) -> Dict:
        if not group:
            return {}
        wins   = [t for t in group if t.is_win]
        losses = [t for t in group if not t.is_win]
        n      = len(group)
        wr     = len(wins) / n * 100
        aw     = sum(t.profit_pct for t in wins)   / len(wins)   if wins   else 0.0
        al     = abs(sum(t.profit_pct for t in losses) / len(losses)) if losses else 0.0
        plr    = aw / al if al > 0 else 0.0
        ev     = (wr / 100) * aw - (1 - wr / 100) * al
        avg_p  = sum(t.profit_pct for t in group) / n
        return dict(n=n, wr=wr, aw=aw, al=al, plr=plr, ev=ev, avg_p=avg_p)

    def _stats_row(self, s: Stats) -> str:
        if s.valid_trades == 0:
            return f'| {s.scenario_name} | 0 | {s.skipped} | - | - | - | - | - | - |'
        ev_mark = '✅' if s.expected_value > 0 else '⚠️'
        return (f'| {s.scenario_name} | {s.valid_trades} | {s.skipped} | '
                f'{s.win_rate:.1f}% | +{s.avg_win:.2f}% | -{s.avg_loss:.2f}% | '
                f'{s.profit_loss_ratio:.2f} | {ev_mark}{s.expected_value:+.2f}% | '
                f'{s.avg_hold_days:.1f}天 |')

    def generate_report(self,
                        signals: List[Signal],
                        results: Dict[str, Stats],
                        suffix: str = '') -> str:

        report_path = os.path.join(self.output_dir, f'backtest_report{suffix}.md')
        L: List[str] = []

        # ── 预先计算全策略排名（执行摘要需要用到）────────
        ranked = sorted(
            [(n, s) for n, s in results.items() if s.valid_trades > 0],
            key=lambda x: x[1].expected_value, reverse=True
        )

        # ── 标题 ──────────────────────────────────────
        L += [
            '# 📊 爆量突破A策略 回测分析报告\n',
            f'**信号文件**: `{os.path.basename(self.signal_file)}`  ',
            f'**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  ',
            f'**总信号数**: {len(signals)} 条 / {len(set(s.code for s in signals))} 只股票  ',
            f'**最大持仓**: {self.MAX_HOLD_DAYS} 交易日  ',
            '',
        ]

        # ── 执行摘要（最优策略指标 + 完整交易方案）──────
        L.append(self._make_executive_summary(signals, results, ranked))

        # ── 说明 ──────────────────────────────────────
        L += [
            '## 📝 回测规则说明\n',
            '| 项目 | 说明 |',
            '|------|------|',
            '| 信号日(T) | 复盘筛选出候选股的日期 |',
            '| **买入价** | 买入日的**开盘价** |',
            '| **卖出价（默认）** | 退出条件触发当日的**收盘价**（止盈/止损均以收盘价检查并成交） |',
            '| **卖出价（盘中触发模式）** | 当日最高价≥止盈目标 → 以目标价成交；当日最低价≤止损价 → 以止损价成交（止损优先）；更贴近实战挂委托单 |',
            '| **开盘卖出模式** | `sell_at_open`：满足T+1规则的第一日**开盘**即卖出 |',
            '| T+1 买入 | 次日**开盘价**买入（标准模式） |',
            '| T+2/T+3 | 延迟一/两日开盘买入 |',
            '| 近MA5 买入 | T+1~T+5内，等开盘价在MA5上方X%以内时买入（等不到则跳过） |',
            '| **T+1规则实现** | 买入日计为持仓第1天，`hold_days > 1` 才允许触发卖出，即最早在买入次日（T+2）卖出 ✅ |',
            '| 一字涨停 | 若买入日最高=最低，视为一字板，跳过不买 |',
            '| 去重 | 同一只股票在持仓期间若再次出现信号，跳过 |',
            '',
        ]

        # ── A. 入场时机对比 ────────────────────────────
        L += ['\n## 🕐 入场时机对比（统一：止盈5% / 止损5%）\n']
        entry_names = [
            'T+1开盘_5%止盈5%止损',
            'T+2开盘_5%止盈5%止损',
            'T+3开盘_5%止盈5%止损',
            'T+1~5_近MA5(5%以内)_5%止盈5%止损',
            'T+1~5_近MA5(2%以内)_5%止盈5%止损',
        ]
        L += [
            '| 策略 | 有效交易 | 跳过 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|------|--------|--------|--------|',
        ]
        for n in entry_names:
            if n in results:
                L.append(self._stats_row(results[n]))

        # ── B. 止盈止损参数矩阵 ────────────────────────
        L += ['\n## 🎯 止盈止损参数矩阵（T+1 开盘买入）\n',
              '表中数值为 **期望值(%)** ，括号内为胜率。✅ 正期望 / ⚠️ 负期望。\n']

        PROFIT_TARGETS = [3, 5, 8, 10, 15]
        STOP_LOSSES    = [3, 5, 8]

        header = '| 止盈↓ \\ 止损→ |' + ''.join(f' 止损{sl}% |' for sl in STOP_LOSSES)
        sep    = '|----------------|' + ''.join('---------|' for _ in STOP_LOSSES)
        L += [header, sep]

        best_ev, best_combo = -999.0, None
        for pt in PROFIT_TARGETS:
            row = f'| **止盈 {pt:2d}%** |'
            for sl in STOP_LOSSES:
                name = f'T+1_止盈{pt}%_止损{sl}%'
                if name in results and results[name].valid_trades > 0:
                    s  = results[name]
                    mk = '✅' if s.expected_value > 0 else '⚠️'
                    row += f' {mk}{s.expected_value:+.2f}% ({s.win_rate:.0f}%) |'
                    if s.expected_value > best_ev:
                        best_ev, best_combo = s.expected_value, (pt, sl)
                else:
                    row += ' - |'
            L.append(row)

        if best_combo:
            best_name = f'T+1_止盈{best_combo[0]}%_止损{best_combo[1]}%'
            best_s    = results.get(best_name)
            L.append(f'\n> **矩阵最优**: 止盈 **{best_combo[0]}%** + 止损 **{best_combo[1]}%**，'
                     f'期望值 **{best_ev:+.2f}%**，胜率 {best_s.win_rate:.1f}%，'
                     f'有效交易 {best_s.valid_trades} 笔\n')

        # 详细统计行（每个组合一行）
        L += ['\n<details><summary>展开完整参数表（含胜率/盈亏比等）</summary>\n',
              '| 参数组合 | 有效交易 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
              '|---------|----------|------|------|------|--------|--------|--------|']
        for pt in PROFIT_TARGETS:
            for sl in STOP_LOSSES:
                name = f'T+1_止盈{pt}%_止损{sl}%'
                if name in results:
                    s = results[name]
                    if s.valid_trades > 0:
                        ev_m = '✅' if s.expected_value > 0 else '⚠️'
                        L.append(f'| 止盈{pt}%/止损{sl}% | {s.valid_trades} | {s.win_rate:.1f}% | '
                                 f'+{s.avg_win:.2f}% | -{s.avg_loss:.2f}% | '
                                 f'{s.profit_loss_ratio:.2f} | {ev_m}{s.expected_value:+.2f}% | '
                                 f'{s.avg_hold_days:.1f}天 |')
        L.append('\n</details>\n')

        # ── C. 均线跟踪止损对比 ──────────────────────
        L += ['\n## 📈 均线跟踪止损对比（T+1 买入）\n']
        ma_names = [
            'T+1_MA5跟踪止损',
            'T+1_MA10跟踪止损',
            'T+1_MA20跟踪止损',
            'T+1_MA5跟踪+止损5%',
            'T+1_MA5跟踪+止损8%',
            'T+1_MA5跟踪+止盈8%',
            'T+1_MA5跟踪+止盈10%',
            'T+1_MA5跟踪_止盈8%止损5%',
            'T+1_MA5跟踪_止盈10%止损5%',
            'T+1_MA5跟踪_止盈8%止损8%',
        ]
        L += [
            '| 策略 | 有效交易 | 跳过 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|------|--------|--------|--------|',
        ]
        for n in ma_names:
            if n in results:
                L.append(self._stats_row(results[n]))

        # ── D. 入场质量优化（MA5距离过滤）──────────────
        L += ['\n## 🔬 入场质量优化（过滤追高入场）\n',
              '> **核心假设**：开盘价距MA5过远（>3%）的交易胜率仅40%、期望值为负，',
              '> 是"止损>止盈"表现好的原因——宽止损能容忍回调，但本质是入场质量不高。\n',
              '> 通过过滤掉追高入场（MA5距离上限），使止盈>止损的组合也能获得高胜率和高盈亏比。\n']

        # D1. T+1 MA5距离过滤 对比
        L += [
            '### 1. T+1入场 + MA5距离上限过滤\n',
            '| 策略 | 有效交易 | 跳过 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|------|--------|--------|--------|',
        ]
        for max_dist in [3.0, 5.0]:
            for pt, sl in [(5, 3), (8, 3), (8, 5), (10, 5)]:
                name = f'T+1_MA5≤{max_dist:.0f}%_止盈{pt}%止损{sl}%'
                if name in results:
                    L.append(self._stats_row(results[name]))
            L.append('| | | | | | | | | |')   # 分隔行

        # D2. 近MA5(2%) 等待买入 + 不同止盈止损
        L += [
            '\n### 2. 等待回踩MA5(2%以内)买入 + 不同止盈止损\n',
            '| 策略 | 有效交易 | 跳过 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|------|--------|--------|--------|',
        ]
        near_ma5_names = [
            'T+1~5_近MA5(2%以内)_5%止盈5%止损',   # 原基准
            '近MA5(2%)_止盈5%止损3%',
            '近MA5(2%)_止盈8%止损3%',
            '近MA5(2%)_止盈8%止损5%',
            '近MA5(2%)_止盈10%止损5%',
        ]
        for n in near_ma5_names:
            if n in results:
                L.append(self._stats_row(results[n]))

        # D3. T+2 入场 + MA5过滤
        L += [
            '\n### 3. T+2入场 + MA5距离过滤\n',
            '| 策略 | 有效交易 | 跳过 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|------|--------|--------|--------|',
        ]
        for max_dist in [3.0, 5.0]:
            for pt, sl in [(5, 3), (5, 5), (8, 5)]:
                name = f'T+2_MA5≤{max_dist:.0f}%_止盈{pt}%止损{sl}%'
                if name in results:
                    L.append(self._stats_row(results[name]))
            L.append('| | | | | | | | | |')

        # D4. 优化前后对比（让用户直观看到过滤效果）
        L += ['\n### 4. 优化前后对比（同参数，加过滤 vs 不加过滤）\n',
              '| 参数组合 | 过滤条件 | 有效交易 | 胜率 | 盈亏比 | 期望值 | 均持天 |',
              '|----------|----------|----------|------|--------|--------|--------|']
        compare_pairs = [
            ('T+1_止盈5%_止损3%', 'T+1_MA5≤3%_止盈5%止损3%', '无→MA5≤3%'),
            ('T+1_止盈5%_止损3%', 'T+1_MA5≤5%_止盈5%止损3%', '无→MA5≤5%'),
            ('T+1_止盈8%_止损5%', 'T+1_MA5≤3%_止盈8%止损5%', '无→MA5≤3%'),
            ('T+1_止盈8%_止损5%', 'T+1_MA5≤5%_止盈8%止损5%', '无→MA5≤5%'),
            ('T+1_止盈10%_止损5%', 'T+1_MA5≤3%_止盈10%止损5%', '无→MA5≤3%'),
        ]
        for base_name, filtered_name, label in compare_pairs:
            for name, cond_label in [(base_name, '无过滤'), (filtered_name, label.split('→')[1])]:
                if name in results and results[name].valid_trades > 0:
                    s    = results[name]
                    ev_m = '✅' if s.expected_value > 0 else '⚠️'
                    params = base_name.replace('T+1_', '')
                    L.append(f'| {params} | {cond_label} | {s.valid_trades} | '
                             f'{s.win_rate:.1f}% | {s.profit_loss_ratio:.2f} | '
                             f'{ev_m}{s.expected_value:+.2f}% | {s.avg_hold_days:.1f}天 |')
            L.append('| | | | | | | |')

        # ── E. 高周转策略专项对比 ──────────────────────
        L += ['\n## ⚡ 高周转策略专项对比\n',
              '> 目标：尽快出局，减少资金占用天数，提升年化周转率。\n',
              '> **盘中触发模式**：当日最低价触达止损价即以该价位成交，最高价触达止盈价即以该价位成交，',
              '> 不等收盘，更贴近实战挂委托单行为。止损优先（若同日止损止盈均被触及，按止损价成交）。\n']

        L += [
            '### 1. 开盘直接卖出（不等止盈止损，直接T+2/T+3开盘平仓）\n',
            '| 策略 | 有效交易 | 胜率 | 均盈 | 均亏 | 期望值 | 均持天 |',
            '|------|----------|------|------|------|--------|--------|',
        ]
        open_sell_names = [
            'T+1买入_T+2开盘卖出',
            'T+1买入_T+3开盘卖出',
            'T+2买入_T+3开盘卖出',
        ]
        for n in open_sell_names:
            if n in results and results[n].valid_trades > 0:
                s = results[n]
                ev_m = '✅' if s.expected_value > 0 else '⚠️'
                L.append(f'| {n} | {s.valid_trades} | {s.win_rate:.1f}% | '
                         f'+{s.avg_win:.2f}% | -{s.avg_loss:.2f}% | '
                         f'{ev_m}{s.expected_value:+.2f}% | {s.avg_hold_days:.1f}天 |')

        L += [
            '\n### 2. 盘中触发止盈止损（挂委托单模式）vs 收盘触发对比\n',
            '| 策略 | 模式 | 有效交易 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 |',
            '|------|------|----------|------|------|------|--------|--------|--------|',
        ]
        intraday_pairs = [(3, 3), (5, 3), (5, 5), (8, 5), (10, 5)]
        for pt, sl in intraday_pairs:
            # 收盘模式
            close_name = f'T+1_止盈{pt}%_止损{sl}%'
            intra_name = f'T+1买入_止盈{pt}%止损{sl}%(盘中触发)'
            for name, mode_label in [(close_name, '收盘成交'), (intra_name, '盘中挂单')]:
                if name in results and results[name].valid_trades > 0:
                    s    = results[name]
                    ev_m = '✅' if s.expected_value > 0 else '⚠️'
                    L.append(f'| 止盈{pt}%/止损{sl}% | {mode_label} | {s.valid_trades} | '
                             f'{s.win_rate:.1f}% | +{s.avg_win:.2f}% | -{s.avg_loss:.2f}% | '
                             f'{s.profit_loss_ratio:.2f} | {ev_m}{s.expected_value:+.2f}% | '
                             f'{s.avg_hold_days:.1f}天 |')
            L.append('| | | | | | | | | |')   # 分隔行

        L += [
            '\n> **说明**：盘中触发模式的均持天数往往更短（止损/止盈在盘中更早触及），',
            '> 若期望值接近但均持天数更少，则盘中挂单方式的**年化收益率更高**。\n',
        ]

        # 高周转综合排名（含均持天数权重打分）
        L += [
            '\n### 3. 高周转综合评分（期望值 ÷ 均持天数，越高越适合频繁交易）\n',
            '| 策略 | 期望值 | 均持天 | 日均期望(%) | 胜率 |',
            '|------|--------|--------|-------------|------|',
        ]
        turnaround_names = open_sell_names + [
            f'T+1买入_止盈{pt}%止损{sl}%(盘中触发)' for pt, sl in intraday_pairs
        ] + [
            'T+1~5_近MA5(2%)_止盈5%止损3%(盘中)',
            'T+1_止盈3%_止损3%',
            'T+1_止盈5%_止损3%',
            'T+1_止盈5%_止损5%',
        ]
        ta_rows = []
        for n in turnaround_names:
            if n in results and results[n].valid_trades > 0 and results[n].avg_hold_days > 0:
                s = results[n]
                daily_ev = s.expected_value / s.avg_hold_days
                ta_rows.append((n, s, daily_ev))
        ta_rows.sort(key=lambda x: x[2], reverse=True)
        for name, s, daily_ev in ta_rows[:15]:
            ev_m = '✅' if s.expected_value > 0 else '⚠️'
            L.append(f'| {name} | {ev_m}{s.expected_value:+.2f}% | {s.avg_hold_days:.1f}天 | '
                     f'{daily_ev:+.3f}% | {s.win_rate:.1f}% |')

        # ── F. 入场位置分析（MA5距离分桶）────────────────
        L += ['\n## 📍 入场位置分析（按MA5距离分桶）\n',
              '> 控制变量：T+1 开盘买入，固定止盈8% / 止损5%，比较"在MA5不同位置入场"的效果差异。\n',
              '> "盘中触发"列更贴近实战挂单行为。\n']

        ENTRY_BUCKETS = [
            ('MA5以下',   None,  0.0),
            ('MA5+0~3%',  0.0,   3.0),
            ('MA5+3~8%',  3.0,   8.0),
            ('MA5+8~15%', 8.0,  15.0),
            ('MA5>15%',  15.0,  None),
        ]
        L += [
            '| 入场区间 | 有效交易 | 胜率 | 均盈 | 均亏 | 盈亏比 | 期望值 | 均持天 | 盘中触发期望值 |',
            '|---------|----------|------|------|------|--------|--------|--------|----------------|',
        ]
        for label, lo, hi in ENTRY_BUCKETS:
            close_name  = f'T+1_入场{label}_止盈8%止损5%'
            intra_name  = f'T+1_入场{label}_止盈8%止损5%(盘中)'
            s = results.get(close_name)
            si = results.get(intra_name)
            if s and s.valid_trades > 0:
                ev_m = '✅' if s.expected_value > 0 else '⚠️'
                intra_ev = f'{ev_m}{si.expected_value:+.2f}%' if si and si.valid_trades > 0 else '-'
                L.append(f'| {label} | {s.valid_trades} | {s.win_rate:.1f}% | '
                         f'+{s.avg_win:.2f}% | -{s.avg_loss:.2f}% | {s.profit_loss_ratio:.2f} | '
                         f'{ev_m}{s.expected_value:+.2f}% | {s.avg_hold_days:.1f}天 | {intra_ev} |')
            else:
                L.append(f'| {label} | 0 | - | - | - | - | - | - | - |')

        L.append('\n> **结论参考**：期望值最高的桶即为最优入场区间；若 MA5以下 胜率高则说明回踩MA5后入场质量最优。\n')

        # ── G. 全策略排名（按期望值降序）────────────────
        L += ['\n## 🏆 全策略期望值排名\n']
        L += [
            '| 排名 | 策略 | 期望值 | 胜率 | 盈亏比 | 均持天 | 有效交易 |',
            '|------|------|--------|------|--------|--------|----------|',
        ]
        for rank, (name, s) in enumerate(ranked[:20], 1):
            mk = '✅' if s.expected_value > 0 else '⚠️'
            L.append(f'| {rank} | {name} | {mk}{s.expected_value:+.2f}% | '
                     f'{s.win_rate:.1f}% | {s.profit_loss_ratio:.2f} | '
                     f'{s.avg_hold_days:.1f}天 | {s.valid_trades} |')

        # ── E. 买入时MA5距离分析 ────────────────────────
        ref_name   = 'T+1_止盈5%_止损5%' if 'T+1_止盈5%_止损5%' in results else (ranked[0][0] if ranked else None)
        ref_trades = results[ref_name].trades if ref_name and ref_name in results else []

        if ref_trades:
            L += [f'\n## 📏 买入时距 MA5 远近 vs 结果（基于 `{ref_name}`）\n',
                  '分析买入当日开盘价相对 MA5 的距离与最终收益的关系：\n']

            ma5_ranges = [
                (-float('inf'), -5,  '远低MA5 (<-5%)'),
                (-5,            -2,  '低于MA5 (-5~-2%)'),
                (-2,             0,  '略低MA5 (-2~0%)'),
                ( 0,             3,  '略高MA5 (0~3%)'),
                ( 3,             7,  '高于MA5 (3~7%)'),
                ( 7,            12,  '明显偏高 (7~12%)'),
                (12, float('inf'),   '远超MA5 (>12%)'),
            ]
            tw = [t for t in ref_trades if t.ma5_at_buy > 0]
            if tw:
                L += [
                    '| MA5距离 | 交易数 | 胜率 | 均盈 | 均亏 | 期望值 | 均持天 |',
                    '|---------|--------|------|------|------|--------|--------|',
                ]
                for lo, hi, label in ma5_ranges:
                    grp = [t for t in tw if lo <= t.price_vs_ma5_pct < hi]
                    g   = self._calc_group(grp)
                    if g:
                        L.append(f'| {label} | {g["n"]} | {g["wr"]:.1f}% | '
                                 f'+{g["aw"]:.2f}% | -{g["al"]:.2f}% | '
                                 f'{g["ev"]:+.2f}% | '
                                 f'{sum(t.hold_days for t in grp)/len(grp):.1f}天 |')

            # 信号日距 MA5
            L += ['\n信号日收盘价相对 MA5 的距离：\n',
                  '| MA5距离(信号日) | 交易数 | 胜率 | 期望值 |',
                  '|----------------|--------|------|--------|']
            sig_ranges = [
                (-float('inf'), 0,   '低于MA5'),
                (0,             5,   '0~5%'),
                (5,            10,   '5~10%'),
                (10,           20,   '10~20%'),
                (20, float('inf'),   '>20%'),
            ]
            ts = [t for t in ref_trades if t.ma5_at_buy > 0]
            for lo, hi, label in sig_ranges:
                grp = [t for t in ts if lo <= t.signal_vs_ma5_pct < hi]
                g   = self._calc_group(grp)
                if g:
                    L.append(f'| {label} | {g["n"]} | {g["wr"]:.1f}% | {g["ev"]:+.2f}% |')

        # ── F. 持有天数分布 ─────────────────────────────
        if ref_trades:
            L += [f'\n## ⏱️ 持有天数分布（基于 `{ref_name}`）\n',
                  '| 持有天数 | 笔数 | 胜率 | 平均收益 |',
                  '|----------|------|------|----------|']
            by_days: Dict[int, List[Trade]] = defaultdict(list)
            for t in ref_trades:
                by_days[t.hold_days].append(t)
            for d in sorted(by_days):
                grp = by_days[d]
                g   = self._calc_group(grp)
                L.append(f'| {d}天 | {g["n"]} | {g["wr"]:.1f}% | {g["avg_p"]:+.2f}% |')

        # ── G. 每日信号统计 ─────────────────────────────
        if ref_trades:
            L += [f'\n## 📅 每日信号统计（基于 `{ref_name}`）\n',
                  '| 信号日期 | 触发笔 | 胜率 | 平均收益 |',
                  '|----------|--------|------|----------|']
            by_date: Dict[str, List[Trade]] = defaultdict(list)
            for t in ref_trades:
                by_date[t.signal_date].append(t)
            for dt in sorted(by_date):
                grp = by_date[dt]
                g   = self._calc_group(grp)
                fmt = f'{dt[:4]}-{dt[4:6]}-{dt[6:]}'
                L.append(f'| {fmt} | {g["n"]} | {g["wr"]:.1f}% | {g["avg_p"]:+.2f}% |')

        # ── H. 最优策略交易明细 ─────────────────────────
        top_name   = ranked[0][0] if ranked else None
        top_trades = results[top_name].trades if top_name else []

        if top_trades:
            L += [f'\n## 📋 交易明细（最优策略：`{top_name}`）\n',
                  '| 股票 | 信号日 | 买入日 | 卖出日 | 持有 | 买入价 | 卖出价 | 收益率 | 最大浮盈 | 最大浮亏 | 卖出原因 |',
                  '|------|--------|--------|--------|------|--------|--------|--------|----------|----------|----------|']
            for t in sorted(top_trades, key=lambda x: x.profit_pct, reverse=True):
                sig_d  = f'{t.signal_date[4:6]}/{t.signal_date[6:]}'
                buy_d  = f'{t.buy_date[4:6]}/{t.buy_date[6:]}'   if t.buy_date  else '-'
                sell_d = f'{t.sell_date[4:6]}/{t.sell_date[6:]}' if t.sell_date else '-'
                pct    = f'+{t.profit_pct:.2f}%' if t.profit_pct >= 0 else f'{t.profit_pct:.2f}%'
                L.append(
                    f'| {t.name}({t.code}) | {sig_d} | {buy_d} | {sell_d} | '
                    f'{t.hold_days}天 | {t.buy_price:.2f} | {t.sell_price:.2f} | '
                    f'{pct} | +{t.max_profit_pct:.2f}% | {t.max_loss_pct:.2f}% | {t.sell_reason} |'
                )

        # 写文件
        content = '\n'.join(L)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return report_path

    # ── 7. 结论生成 ────────────────────────────────────

    def _make_conclusions(self,
                          results: Dict[str, Stats],
                          signals: List[Signal],
                          ranked: List[Tuple[str, Stats]]) -> str:
        pts = []

        # 1. 整体有效性
        if ranked:
            top_name, top_s = ranked[0]
            if top_s.expected_value > 1:
                pts.append(f'1. **策略有效性** ✅: 最优参数下期望值 **{top_s.expected_value:+.2f}%** > 0，'
                           f'策略具有正期望，可以作为交易参考。')
            elif top_s.expected_value > 0:
                pts.append(f'1. **策略有效性** ⚠️: 最优参数期望值仅 {top_s.expected_value:+.2f}%，正期望但优势不明显，需谨慎。')
            else:
                pts.append(f'1. **策略有效性** ❌: 在当前样本下最优期望值 {top_s.expected_value:+.2f}% < 0，'
                           f'建议增加样本量后再做判断。')

        # 2. 最佳入场时机
        entry_names = ['T+1开盘_5%止盈5%止损',
                       'T+2开盘_5%止盈5%止损',
                       'T+3开盘_5%止盈5%止损']
        entry_evs = [(n, results[n].expected_value) for n in entry_names if n in results and results[n].valid_trades > 0]
        if entry_evs:
            best_entry = max(entry_evs, key=lambda x: x[1])
            worst_entry = min(entry_evs, key=lambda x: x[1])
            pts.append(f'2. **最佳入场时机**: `{best_entry[0]}` 期望值最高 ({best_entry[1]:+.2f}%)，'
                       f'`{worst_entry[0]}` 最低 ({worst_entry[1]:+.2f}%)。')

        # 3. MA5 等待买入
        t1_name   = 'T+1开盘_5%止盈5%止损'
        ma5_name  = 'T+1~5_近MA5(5%以内)_5%止盈5%止损'
        ma5_name2 = 'T+1~5_近MA5(2%以内)_5%止盈5%止损'
        if t1_name in results and ma5_name in results and results[ma5_name].valid_trades > 0:
            t1_ev  = results[t1_name].expected_value
            ma_ev  = results[ma5_name].expected_value
            ma_ev2 = results[ma5_name2].expected_value if ma5_name2 in results else None
            skipped_pct = results[ma5_name].skipped / len(signals) * 100
            if ma_ev > t1_ev:
                pts.append(f'3. **均线回踩买入** ✅: 等待近 MA5(5%以内) 买入期望值 {ma_ev:+.2f}% > '
                           f'直接 T+1 买入 {t1_ev:+.2f}%，'
                           f'**建议等候均线回踩**（但有 {skipped_pct:.0f}% 信号未等到入场机会而跳过）。')
            else:
                pts.append(f'3. **均线回踩买入**: 等待近 MA5 买入期望值 {ma_ev:+.2f}%，'
                           f'直接 T+1 买入 {t1_ev:+.2f}%，两者差异不显著或 T+1 更优，'
                           f'不必刻意等候回踩。')

        # 4. 最佳止盈止损
        pnl_list = [(n, s) for n, s in results.items()
                    if n.startswith('T+1_止盈') and s.valid_trades > 0]
        if pnl_list:
            best_pnl = max(pnl_list, key=lambda x: x[1].expected_value)
            pts.append(f'4. **最佳固定止盈止损**: `{best_pnl[0]}` 期望值 {best_pnl[1].expected_value:+.2f}%，'
                       f'胜率 {best_pnl[1].win_rate:.1f}%，盈亏比 {best_pnl[1].profit_loss_ratio:.2f}。')

        # 5. MA 跟踪 vs 固定
        ma_trail_name = 'T+1_MA5跟踪止损'
        if ma_trail_name in results and pnl_list:
            ma_ev   = results[ma_trail_name].expected_value
            best_ev = max(s.expected_value for _, s in pnl_list)
            if ma_ev > best_ev:
                pts.append(f'5. **均线跟踪止损更优** ✅: MA5跟踪止损期望值 {ma_ev:+.2f}% > '
                           f'最优固定止盈止损 {best_ev:+.2f}%，建议使用均线跟踪出场。')
            else:
                pts.append(f'5. **固定止盈止损更优**: 最优固定止盈止损期望值 {best_ev:+.2f}% >= '
                           f'MA5跟踪止损 {ma_ev:+.2f}%，建议使用固定参数出场。')

        # 6. 样本量提示
        n = results[t1_name].valid_trades if t1_name in results else 0
        if n < 30:
            pts.append(f'6. **⚠️ 样本量提醒**: 有效交易仅 **{n}** 笔，统计结论具有局限性，'
                       f'建议累积更多信号后复核。')
        else:
            pts.append(f'6. **样本量**: 有效交易 {n} 笔，具备一定统计参考价值。')

        return '\n\n'.join(pts)

    # ── 对外入口 ───────────────────────────────────────

    def run_and_report(self, suffix: str = '') -> str:
        signals, results = self.run_all()
        report_path = self.generate_report(signals, results, suffix)
        print(f'[OK] 回测报告已保存至: {report_path}')
        return report_path


# ──────────────────────────────────────────────────────
#  便捷函数
# ──────────────────────────────────────────────────────

def run_breakout_a_backtest(signal_file: str,
                            output_dir: str,
                            data_path: str = './data/astocks',
                            suffix: str = None) -> str:
    """
    爆量突破A策略回测入口。

    Args:
        signal_file: scan_simple_YYYYMMDD-YYYYMMDD.txt 路径
        output_dir:  报告输出目录
        data_path:   股票行情数据目录
        suffix:      报告文件名后缀，默认从文件名自动提取
                     如 scan_simple_20251220-20260227.txt → '_20251220-20260227'

    Returns:
        生成的报告文件路径
    """
    if suffix is None:
        import re
        m = re.search(r'scan_simple(_[\d\-]+)', os.path.basename(signal_file))
        suffix = m.group(1) if m else ''
    backtester = BreakoutABacktester(signal_file, output_dir, data_path)
    return backtester.run_and_report(suffix)


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    _signal_file = 'bin/candidate_stocks_breakout_a/scan_simple_20251220-20260227.txt'
    _output_dir  = 'bin/candidate_stocks_breakout_a/backtest'

    if os.path.exists(_signal_file):
        run_breakout_a_backtest(_signal_file, _output_dir, suffix='_20251220-20260227')
    else:
        print(f'信号文件不存在: {_signal_file}')

