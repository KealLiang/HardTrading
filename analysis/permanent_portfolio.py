"""
永久投资组合（Permanent Portfolio）回测与跟踪工具

标准结构（Harry Browne 4资产等权）：
  - 股票 ETF   25%
  - 长期国债 ETF 25%
  - 黄金 ETF   25%
  - 现金       25%（按银行活期利率按日计息，不使用 ETF）

再平衡规则：
  - 按指定周期（月度/季度/年度）在最后一个交易日收盘后强制拉回各 25%
  - 交易价格使用当日收盘价（复权价）
  - 若再平衡日无数据（非交易日），自动顺延至下一个交易日
"""

import os
import logging
import numpy as np
import pandas as pd
from typing import List

# 默认本地 ETF 数据目录
ETF_DATA_DIR = './data/etfs'


# ─────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────

def load_etf_prices(
    codes: List[str],
    start_date: str,
    end_date: str,
    data_dir: str = ETF_DATA_DIR,
) -> pd.DataFrame:
    """
    从本地 CSV 加载 ETF 收盘价，返回以日期为索引、代码为列的 DataFrame。
    只保留所有标的均有数据的交易日（取交集），避免不同上市时间造成 NaN。
    """
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    close_map = {}
    for code in codes:
        path = os.path.join(data_dir, f"{code}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"ETF {code} 数据文件不存在: {path}\n请先运行 get_etf_datas(['{code}']) 下载数据"
            )
        df = (
            pd.read_csv(path, parse_dates=['日期'])
            .sort_values('日期')
            .set_index('日期')
        )
        df = df.loc[start_dt:end_dt]
        if df.empty:
            raise ValueError(f"ETF {code} 在 {start_date}~{end_date} 无数据，请先下载")
        close_map[code] = df['收盘']

    price_df = pd.DataFrame(close_map).sort_index().dropna()
    logging.info(f"加载 {len(codes)} 只ETF价格，有效交易日 {len(price_df)} 天")
    return price_df


# ─────────────────────────────────────────────
# 交易日期工具
# ─────────────────────────────────────────────

def get_period_last_dates(trading_dates: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    """
    从已有交易日序列中，提取每个周期的最后一个交易日。

    由于直接对 trading_dates 做 groupby，天然处理「周期末非交易日自动顺延」问题。
    """
    s = pd.Series(trading_dates, index=trading_dates)

    if freq == 'monthly':
        grouped = s.groupby(s.dt.to_period('M')).last()
    elif freq == 'quarterly':
        grouped = s.groupby(s.dt.to_period('Q')).last()
    elif freq == 'yearly':
        grouped = s.groupby(s.dt.year).last()
    else:
        raise ValueError(f"不支持的再平衡频率: '{freq}'，可选 monthly / quarterly / yearly")

    return pd.DatetimeIndex(grouped.values)


# ─────────────────────────────────────────────
# 核心类
# ─────────────────────────────────────────────

class PermanentPortfolio:
    """
    永久投资组合回测与跟踪工具。

    资产构成：
      - N 只 ETF（由 etf_codes 指定）
      - 1 份现金（按 cash_annual_rate 年化利率按自然日计息）
      - 共 N+1 类资产，各占 1/(N+1) 目标仓位

    使用示例（标准4资产等权）：
        portfolio = PermanentPortfolio(
            etf_codes=['510300', '518880', '511010'],
            initial_capital=1_000_000,
            start_date='20200103',
            end_date='20260215',
            cash_annual_rate=0.0005,   # 0.05% 活期利率
        )
        result = portfolio.backtest()
        print(portfolio.generate_backtest_report(result))
    """

    def __init__(
        self,
        etf_codes: List[str],
        initial_capital: float,
        start_date: str,
        end_date: str,
        rebalance_freq: str = 'yearly',
        cash_annual_rate: float = 0.0005,   # 银行活期利率，年化 0.05%
        risk_free_rate: float = 0.0,
        transaction_cost: float = 0.0,
        data_dir: str = ETF_DATA_DIR,
    ):
        """
        :param etf_codes: ETF 代码列表（N 只），加上现金共 N+1 类资产等权配置
        :param initial_capital: 初始资金（元）
        :param start_date: 建仓日期
        :param end_date: 终止日期
        :param rebalance_freq: 再平衡频率 monthly / quarterly / yearly
        :param cash_annual_rate: 现金年化利率（自然日计息），默认 0.05% 活期利率
        :param risk_free_rate: 无风险年化利率，用于夏普比率计算，默认 0
        :param transaction_cost: ETF 单边交易成本比例，默认 0
        :param data_dir: 本地 ETF 数据目录
        """
        if not etf_codes:
            raise ValueError("etf_codes 不能为空")

        self.etf_codes = etf_codes
        self.n_etf = len(etf_codes)
        self.n_total = self.n_etf + 1          # ETF数量 + 1个现金
        self.target_weight = 1.0 / self.n_total  # 各资产目标仓位

        self.initial_capital = initial_capital
        self.start_date = start_date
        self.end_date = end_date
        self.rebalance_freq = rebalance_freq
        self.cash_annual_rate = cash_annual_rate
        self.risk_free_rate = risk_free_rate
        self.transaction_cost = transaction_cost

        self.prices = load_etf_prices(etf_codes, start_date, end_date, data_dir)
        self.trading_dates = self.prices.index

    # ── 内部工具 ──────────────────────────────────

    def _get_rebalance_dates(self) -> set:
        """返回再平衡日期集合（不含建仓首日）"""
        all_ends = get_period_last_dates(self.trading_dates, self.rebalance_freq)
        first = self.trading_dates[0]
        return set(d for d in all_ends if d > first)

    def _simulate(self):
        """
        核心模拟引擎（逐日推进）。

        现金处理：
          - 按两个相邻交易日之间的自然日数计息（calendar day interest）
          - 日利率 = cash_annual_rate / 365
          - 首个交易日建仓，现金不计当日利息（当天刚买入）

        ETF 处理：
          - 允许分数股（不考虑最小交易单位），以收盘价建仓与再平衡

        :return: (daily_df, rebalance_logs)
        """
        prices = self.prices
        dates = self.trading_dates
        rebalance_dates = self._get_rebalance_dates()

        # ── 建仓 ──
        first_p = prices.iloc[0]
        init_per = self.initial_capital * self.target_weight  # 每类资产初始金额

        # ETF 持仓（分数股）
        shares = {
            code: (init_per / (1 + self.transaction_cost)) / first_p[code]
            for code in self.etf_codes
        }
        # 现金持仓（元）
        cash = init_per

        # 建仓记录
        init_etf_vals = {code: shares[code] * first_p[code] for code in self.etf_codes}
        rebalance_logs = [{
            '日期': dates[0],
            '操作': '建仓',
            '总资产': round(sum(init_etf_vals.values()) + cash, 2),
            **{f'{c}_前市值': 0.0 for c in self.etf_codes},
            '现金_前市值': 0.0,
            **{f'{c}_后市值': round(init_etf_vals[c], 2) for c in self.etf_codes},
            '现金_后市值': round(cash, 2),
            **{f'{c}_调整金额': round(init_etf_vals[c], 2) for c in self.etf_codes},
            '现金_调整金额': round(cash, 2),
        }]

        daily_rows = []
        peak = self.initial_capital
        max_dd = 0.0
        prev_date = dates[0]  # 用于计算自然日利息

        for date in dates:
            p = prices.loc[date]

            # 现金按自然日计息（建仓首日不计息）
            if date != dates[0]:
                calendar_days = (date - prev_date).days
                cash *= (1 + self.cash_annual_rate / 365) ** calendar_days

            # 各资产当日市值
            etf_vals = {code: shares[code] * p[code] for code in self.etf_codes}
            total = sum(etf_vals.values()) + cash

            # 更新最大回撤
            peak = max(peak, total)
            dd = (peak - total) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

            # 记录当日数据（包含现金）
            row = {
                '日期': date,
                '总资产': total,
                '回撤': dd,
                '现金_市值': cash,
                '现金_占比': cash / total,
                **{f'{c}_市值': etf_vals[c] for c in self.etf_codes},
                **{f'{c}_占比': etf_vals[c] / total for c in self.etf_codes},
            }
            daily_rows.append(row)

            # ── 再平衡（非建仓首日） ──
            if date in rebalance_dates:
                target_per = total * self.target_weight

                # ETF 单边换手额（用于手续费计算）
                one_way = sum(max(0, target_per - etf_vals[c]) for c in self.etf_codes)
                fee = one_way * self.transaction_cost * 2  # 双边手续费
                net_total = total - fee
                net_target = net_total * self.target_weight

                rec = {
                    '日期': date,
                    '操作': '再平衡',
                    '总资产': round(net_total, 2),
                    '现金_前市值': round(cash, 2),
                    **{f'{c}_前市值': round(etf_vals[c], 2) for c in self.etf_codes},
                }

                # 调整 ETF 持仓
                for code in self.etf_codes:
                    new_val = net_target
                    shares[code] = new_val / p[code]
                    rec[f'{code}_后市值'] = round(new_val, 2)
                    rec[f'{code}_调整金额'] = round(new_val - etf_vals[code], 2)

                # 调整现金持仓
                rec['现金_后市值'] = round(net_target, 2)
                rec['现金_调整金额'] = round(net_target - cash, 2)
                cash = net_target

                rebalance_logs.append(rec)

            prev_date = date

        daily_df = pd.DataFrame(daily_rows).set_index('日期')
        return daily_df, rebalance_logs

    # ── 回测 ──────────────────────────────────────

    def backtest(self) -> dict:
        """
        执行完整回测。

        :return: 包含 daily_df、rebalance_logs、关键绩效指标的字典
        """
        daily_df, rebalance_logs = self._simulate()

        final = daily_df['总资产'].iloc[-1]
        years = (self.trading_dates[-1] - self.trading_dates[0]).days / 365.25

        cum_ret = (final - self.initial_capital) / self.initial_capital
        ann_ret = (1 + cum_ret) ** (1 / years) - 1 if years > 0 else 0.0
        max_dd = daily_df['回撤'].max()

        daily_ret = daily_df['总资产'].pct_change().dropna()
        daily_rf = self.risk_free_rate / 252
        sharpe = (
            (daily_ret.mean() - daily_rf) / daily_ret.std() * np.sqrt(252)
            if daily_ret.std() > 0 else 0.0
        )

        return {
            'daily_df': daily_df,
            'rebalance_logs': rebalance_logs,
            'final_value': final,
            'cumulative_return': cum_ret,
            'annualized_return': ann_ret,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'years': years,
        }

    def generate_backtest_report(self, result: dict) -> str:
        """生成 Markdown 格式回测报告（可直接保存为 .md 文件）"""
        freq_cn = {'monthly': '月度', 'quarterly': '季度', 'yearly': '年度'}.get(
            self.rebalance_freq, self.rebalance_freq
        )
        daily_df = result['daily_df']
        logs = result['rebalance_logs']
        all_assets = self.etf_codes + ['现金']  # 4类资产列表（ETF + 现金）

        lines = [
            '# 永久投资组合回测报告', '',
            '## 一、基础参数',
            '| 参数 | 值 |',
            '|------|-----|',
            f'| 初始资金 | {self.initial_capital:,.0f} 元 |',
            f'| 建仓日期 | {daily_df.index[0].strftime("%Y-%m-%d")} |',
            f'| 终止日期 | {daily_df.index[-1].strftime("%Y-%m-%d")} |',
            f'| 持仓时长 | {result["years"]:.2f} 年 |',
            f'| 再平衡频率 | {freq_cn} |',
            f'| ETF 标的 | {" / ".join(self.etf_codes)} |',
            f'| 现金利率（年化） | {self.cash_annual_rate:.4%} |',
            f'| 资产数量 | {self.n_total} 类，各 {self.target_weight:.1%} |',
            f'| 交易成本（单边） | {self.transaction_cost:.4%} |',
            '',
            '## 二、关键业绩指标',
            '| 指标 | 数值 |',
            '|------|------|',
            f'| 期末总资产 | {result["final_value"]:,.2f} 元 |',
            f'| 累计收益率 | {result["cumulative_return"]:+.2%} |',
            f'| 年化收益率 | {result["annualized_return"]:+.2%} |',
            f'| 最大回撤 | {result["max_drawdown"]:.2%} |',
            f'| 夏普比率 | {result["sharpe"]:.2f} |',
            '',
        ]

        # 年度收益明细
        lines += ['## 三、年度收益明细', '| 年份 | 期初资产 | 期末资产 | 年度收益率 |', '|------|---------|---------|-----------|']
        for year, grp in daily_df.groupby(daily_df.index.year):
            s = grp['总资产'].iloc[0]
            e = grp['总资产'].iloc[-1]
            r = (e - s) / s
            lines.append(f'| {year} | {s:,.2f} | {e:,.2f} | {r:+.2%} |')
        lines.append('')

        # 再平衡操作记录（含现金列）
        lines += ['## 四、再平衡操作记录', '']
        header = '| 日期 | 操作 | 总资产 |'
        sep = '|------|------|--------|'
        for a in all_assets:
            header += f' {a} 调整金额 |'
            sep += '---------|'
        lines += [header, sep]

        for rec in logs:
            date_s = pd.Timestamp(rec['日期']).strftime('%Y-%m-%d')
            row = f'| {date_s} | {rec["操作"]} | {rec["总资产"]:,.2f} |'
            for code in self.etf_codes:
                amt = rec.get(f'{code}_调整金额', 0)
                sign = '+' if amt >= 0 else ''
                row += f' {sign}{amt:,.2f} |'
            # 现金列
            cash_amt = rec.get('现金_调整金额', 0)
            sign = '+' if cash_amt >= 0 else ''
            row += f' {sign}{cash_amt:,.2f} |'
            lines.append(row)
        lines.append('')

        return '\n'.join(lines)

    # ── 跟踪模式 ─────────────────────────────────

    def track(self) -> dict:
        """
        跟踪模式：基于当前最新数据，计算持仓状态与再平衡操作建议。
        """
        daily_df, _ = self._simulate()

        current_date = daily_df.index[-1]
        all_period_ends = get_period_last_dates(self.trading_dates, self.rebalance_freq)

        past = [d for d in all_period_ends if d <= current_date]
        future = [d for d in all_period_ends if d > current_date]

        last_rebal = past[-1] if past else None
        next_rebal = future[0] if future else None

        last_row = daily_df.iloc[-1]
        total = last_row['总资产']

        # 构建各资产信息（ETF + 现金）
        asset_info = []
        for code in self.etf_codes:
            cur_val = last_row[f'{code}_市值']
            cur_wt = last_row[f'{code}_占比']
            adjust = total * self.target_weight - cur_val
            asset_info.append({
                'code': code,
                'asset_type': 'etf',
                'market_value': cur_val,
                'current_weight': cur_wt,
                'target_weight': self.target_weight,
                'adjust_amount': adjust,
            })
        # 现金
        cash_val = last_row['现金_市值']
        cash_wt = last_row['现金_占比']
        asset_info.append({
            'code': '现金',
            'asset_type': 'cash',
            'market_value': cash_val,
            'current_weight': cash_wt,
            'target_weight': self.target_weight,
            'adjust_amount': total * self.target_weight - cash_val,
        })

        years = (current_date - self.trading_dates[0]).days / 365.25
        cum_ret = (total - self.initial_capital) / self.initial_capital
        ann_ret = (1 + cum_ret) ** (1 / years) - 1 if years > 0 else 0.0
        max_dd = daily_df['回撤'].max()

        return {
            'current_date': current_date,
            'last_rebal_date': last_rebal,
            'next_rebal_date': next_rebal,
            'total_value': total,
            'asset_info': asset_info,
            'cumulative_return': cum_ret,
            'annualized_return': ann_ret,
            'max_drawdown': max_dd,
        }

    def generate_track_report(self, result: dict) -> str:
        """生成跟踪模式 Markdown 报告"""
        freq_cn = {'monthly': '月度', 'quarterly': '季度', 'yearly': '年度'}.get(
            self.rebalance_freq, self.rebalance_freq
        )
        last_r = result['last_rebal_date'].strftime('%Y-%m-%d') if result['last_rebal_date'] else '无'
        next_r = result['next_rebal_date'].strftime('%Y-%m-%d') if result['next_rebal_date'] else '暂无'

        lines = [
            '# 永久投资组合跟踪报告', '',
            f'> 当前日期：**{result["current_date"].strftime("%Y-%m-%d")}** | '
            f'再平衡频率：**{freq_cn}**',
            '',
            '## 一、再平衡时间节点',
            f'- **最近一次再平衡日**：{last_r}',
            f'- **下一次再平衡日**：{next_r}',
            '',
            '## 二、当前持仓与操作建议',
            f'**当前总资产**：{result["total_value"]:,.2f} 元',
            '',
            '| 资产 | 持仓市值 | 当前占比 | 目标占比 | 偏差 | 操作建议 |',
            '|------|---------|---------|---------|------|---------|',
        ]

        for info in result['asset_info']:
            dev = info['current_weight'] - info['target_weight']
            amt = info['adjust_amount']
            if info['asset_type'] == 'cash':
                action = f'存入 {amt:,.2f}' if amt >= 0 else f'取出 {abs(amt):,.2f}'
            else:
                action = f'买入 {amt:,.2f}' if amt >= 0 else f'卖出 {abs(amt):,.2f}'
            lines.append(
                f'| {info["code"]} | {info["market_value"]:,.2f} | '
                f'{info["current_weight"]:.2%} | {info["target_weight"]:.2%} | '
                f'{dev:+.2%} | {action} |'
            )

        lines += [
            '',
            '## 三、组合表现（自建仓以来）',
            '| 指标 | 数值 |',
            '|------|------|',
            f'| 累计收益率 | {result["cumulative_return"]:+.2%} |',
            f'| 年化收益率 | {result["annualized_return"]:+.2%} |',
            f'| 最大回撤 | {result["max_drawdown"]:.2%} |',
            '',
        ]

        return '\n'.join(lines)


# ─────────────────────────────────────────────
# 报告保存工具
# ─────────────────────────────────────────────

def save_report(report: str, output_dir: str, filename: str) -> str:
    """
    将报告内容保存为 Markdown 文件。

    :param report: Markdown 文本
    :param output_dir: 输出目录
    :param filename: 文件名（不含扩展名）
    :return: 文件路径
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f'{filename}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(report)
    return path
