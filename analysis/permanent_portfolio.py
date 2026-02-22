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

import matplotlib
# 使用非交互式后端，避免多线程问题
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 默认本地 ETF 数据目录
ETF_DATA_DIR = './data/etfs'

# ── 常见ETF代码对应资产类型标签 ──────────────────
# 格式：代码 -> 资产类型名，最终显示为「类型(代码)」
_ETF_TYPE_LABELS = {
    # 股票类
    '510300': '股票',   # 沪深300ETF
    '510500': '股票',   # 中证500ETF
    '510050': '股票',   # 上证50ETF
    '159919': '股票',   # 沪深300ETF（深交所）
    '159901': '股票',   # 深证100ETF
    # 黄金类
    '518880': '黄金',   # 黄金ETF（华安）
    '518800': '黄金',   # 黄金ETF（国泰）
    '159934': '黄金',   # 黄金ETF（易方达）
    # 国债类
    '511010': '国债',   # 国债ETF（上交所）
    '511020': '国债',   # 国债ETF
    '511260': '国债',   # 十年国债ETF
    '159792': '国债',   # 国债ETF（深交所）
    '511090': '国债',   # 30年国债ETF
    # 货币类
    '511880': '货币',   # 银华日利ETF
    '511990': '货币',   # 华宝添益ETF
}


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

    # ── 资产标签工具 ──────────────────────────────

    def _get_asset_label(self, code: str) -> str:
        """
        获取资产显示名称，格式：类型(代码)
        例：'510300' -> '股票(510300)'，未知代码返回代码本身
        """
        asset_type = _ETF_TYPE_LABELS.get(code, code)
        return f'{asset_type}({code})'

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
        # 单独追踪利息累计（不含再平衡流入流出），用于区分利息与再平衡效果
        cash_interest_total = 0.0

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
                interest = cash * ((1 + self.cash_annual_rate / 365) ** calendar_days - 1)
                cash += interest
                cash_interest_total += interest

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
        return daily_df, rebalance_logs, cash_interest_total

    # ── 回测 ──────────────────────────────────────

    def backtest(self) -> dict:
        """
        执行完整回测。

        :return: 包含 daily_df、rebalance_logs、关键绩效指标的字典
        """
        daily_df, rebalance_logs, cash_interest_total = self._simulate()

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

        # ── 各资产表现统计 ──
        init_per = self.initial_capital * self.target_weight
        asset_perf = []

        for code in self.etf_codes:
            label = self._get_asset_label(code)
            start_price = self.prices[code].iloc[0]
            end_price = self.prices[code].iloc[-1]
            price_ret = (end_price / start_price) - 1        # 纯价格涨跌幅（不含再平衡效果）

            final_val = daily_df[f'{code}_市值'].iloc[-1]
            pnl = final_val - init_per                        # 持仓盈亏（含再平衡效果）
            holding_ret = final_val / init_per - 1

            asset_perf.append({
                'label': label,
                'code': code,
                'asset_type': 'etf',
                'init_val': init_per,
                'final_val': final_val,
                'pnl': pnl,
                'holding_ret': holding_ret,
                'price_ret': price_ret,
                'start_price': start_price,
                'end_price': end_price,
            })

        # 现金
        cash_final = daily_df['现金_市值'].iloc[-1]
        cash_pnl = cash_final - init_per
        cash_ret = cash_final / init_per - 1
        # 纯利息收益率：仅计算利息积累，不含再平衡流入流出
        cash_interest_ret = cash_interest_total / init_per
        asset_perf.append({
            'label': '现金',
            'code': '现金',
            'asset_type': 'cash',
            'init_val': init_per,
            'final_val': cash_final,
            'pnl': cash_pnl,
            'holding_ret': cash_ret,
            'price_ret': cash_interest_ret,   # 现金仅显示纯利息收益率
            'start_price': None,
            'end_price': None,
        })

        return {
            'daily_df': daily_df,
            'rebalance_logs': rebalance_logs,
            'final_value': final,
            'cumulative_return': cum_ret,
            'annualized_return': ann_ret,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'years': years,
            'asset_perf': asset_perf,
        }

    def generate_backtest_report(self, result: dict, chart_filename: str = None) -> str:
        """
        生成 Markdown 格式回测报告（可直接保存为 .md 文件）。

        :param result: backtest() 返回的结果字典
        :param chart_filename: 若提供，则在报告末尾嵌入图片引用（仅文件名，不含路径）
        """
        freq_cn = {'monthly': '月度', 'quarterly': '季度', 'yearly': '年度'}.get(
            self.rebalance_freq, self.rebalance_freq
        )
        daily_df = result['daily_df']
        logs = result['rebalance_logs']
        asset_perf = result['asset_perf']
        all_assets = self.etf_codes + ['现金']  # 4类资产列表（ETF + 现金）

        # 资产标签列表（用于表头）
        asset_labels = [self._get_asset_label(c) for c in self.etf_codes] + ['现金']

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
            f'| 资产配置 | {" / ".join(asset_labels)} |',
            f'| 现金利率（年化） | {self.cash_annual_rate:.4%} |',
            f'| 资产权重 | 各 {self.target_weight:.1%} |',
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

        # ── 各资产表现明细 ──
        lines += [
            '## 三、各资产表现明细',
            '',
            '> 说明：「价格涨跌幅」为标的纯价格变化（不含再平衡效果）；「持仓收益率」为实际持仓盈亏（含再平衡买卖效果）；现金的「价格涨跌幅」仅代表纯利息累计收益，持仓收益率高于此值的部分均来自再平衡流入。',
            '',
            '| 资产 | 初始配置 | 期末市值 | 持仓盈亏(元) | 持仓收益率 | 标的价格涨跌幅 |',
            '|------|---------|---------|------------|-----------|--------------|',
        ]
        for ap in asset_perf:
            price_ret_str = f'{ap["price_ret"]:+.2%}' if ap['price_ret'] is not None else '-'
            lines.append(
                f'| {ap["label"]} | {ap["init_val"]:,.2f} | {ap["final_val"]:,.2f} | '
                f'{ap["pnl"]:+,.2f} | {ap["holding_ret"]:+.2%} | {price_ret_str} |'
            )
        lines.append('')

        # ── 年度收益明细 ──
        lines += ['## 四、年度收益明细', '| 年份 | 期初资产 | 期末资产 | 年度收益率 |', '|------|---------|---------|-----------|']
        for year, grp in daily_df.groupby(daily_df.index.year):
            s = grp['总资产'].iloc[0]
            e = grp['总资产'].iloc[-1]
            r = (e - s) / s
            lines.append(f'| {year} | {s:,.2f} | {e:,.2f} | {r:+.2%} |')
        lines.append('')

        # ── 再平衡操作记录（含现金列）──
        lines += ['## 五、再平衡操作记录', '']
        header = '| 日期 | 操作 | 总资产 |'
        sep = '|------|------|--------|'
        for label in asset_labels:
            header += f' {label} 调整金额 |'
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

        # ── 可选：嵌入图表引用 ──
        if chart_filename:
            lines += [
                '## 六、回测图表',
                '',
                f'![永久投资组合回测图表]({chart_filename})',
                '',
            ]

        return '\n'.join(lines)

    # ── 回测可视化 ─────────────────────────────────

    def plot_backtest_results(self, result: dict, save_dir: str, filename: str) -> str:
        """
        绘制回测结果图表：
          - 左Y轴：组合总资产曲线（元）
          - 右Y轴：各成员累计收益率曲线（%），包含组合整体收益率

        竖虚线标记每次再平衡日期，避免坐标比例悬殊压缩折线。

        :param result: backtest() 返回的结果字典
        :param save_dir: 图片保存目录
        :param filename: 文件名（不含扩展名）
        :return: 图片文件路径
        """
        # 设置中文字体（与 fupan_statistics_plot.py 保持一致）
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False

        daily_df = result['daily_df']
        dates = daily_df.index

        fig, ax1 = plt.subplots(figsize=(16, 8))

        # ── 左Y轴：总资产（元）──
        ax1.fill_between(dates, daily_df['总资产'], alpha=0.08, color='#2980b9')
        ax1.plot(dates, daily_df['总资产'], color='#2980b9', linewidth=2.5,
                 label='总资产（左轴）', zorder=3)
        ax1.set_xlabel('日期', fontsize=12)
        ax1.set_ylabel('总资产（元）', color='#2980b9', fontsize=12)
        ax1.tick_params(axis='y', labelcolor='#2980b9')

        # ── 右Y轴：各成员累计收益率（%）──
        ax2 = ax1.twinx()

        # 颜色方案（与 fupan_statistics_plot.py 类似的配色）
        etf_colors = ['#e74c3c', '#f39c12', '#27ae60', '#8e44ad', '#16a085']

        # 各 ETF 纯价格累计收益曲线（不受再平衡影响，反映标的本身表现）
        for i, code in enumerate(self.etf_codes):
            prices_series = self.prices[code]
            cum_ret = (prices_series / prices_series.iloc[0] - 1) * 100
            label = self._get_asset_label(code)
            ax2.plot(dates, cum_ret, linestyle='--', linewidth=1.8,
                     color=etf_colors[i % len(etf_colors)], label=label, alpha=0.85)

        # 现金累计收益曲线（从 daily_df 取，反映实际利息积累）
        cash_cum_ret = (daily_df['现金_市值'] / daily_df['现金_市值'].iloc[0] - 1) * 100
        ax2.plot(dates, cash_cum_ret, linestyle=':', linewidth=1.5,
                 color='#7f8c8d', label='现金', alpha=0.85)

        # 组合整体累计收益率曲线（实线，便于和各成员对比）
        portfolio_cum_ret = (daily_df['总资产'] / daily_df['总资产'].iloc[0] - 1) * 100
        ax2.plot(dates, portfolio_cum_ret, linestyle='-.', linewidth=2.0,
                 color='#2980b9', label='组合收益率（右轴）', alpha=0.75)

        ax2.axhline(y=0, color='#bdc3c7', linestyle='-', linewidth=0.8, alpha=0.6)
        ax2.set_ylabel('累计收益率（%）', color='#27ae60', fontsize=12)
        ax2.tick_params(axis='y', labelcolor='#27ae60')

        # ── 标记再平衡日期（灰色竖虚线）──
        logs = result['rebalance_logs']
        rebal_dates = [pd.Timestamp(r['日期']) for r in logs if r['操作'] == '再平衡']
        for rd in rebal_dates:
            ax1.axvline(x=rd, color='#bdc3c7', linestyle=':', linewidth=0.9, alpha=0.7, zorder=1)
        # 图例只添加一条再平衡标注线
        if rebal_dates:
            ax1.axvline(x=rebal_dates[0], color='#bdc3c7', linestyle=':',
                        linewidth=0.9, alpha=0.7, label='再平衡日', zorder=1)

        # ── 标题与图例 ──
        freq_cn = {'monthly': '月度', 'quarterly': '季度', 'yearly': '年度'}.get(
            self.rebalance_freq, self.rebalance_freq
        )
        start_d = daily_df.index[0].strftime('%Y-%m-%d')
        end_d = daily_df.index[-1].strftime('%Y-%m-%d')
        plt.title(
            f'永久投资组合回测结果（{freq_cn}再平衡，{start_d} ~ {end_d}）',
            fontsize=14, pad=15
        )

        # 合并两个轴的图例
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10)

        ax1.grid(True, alpha=0.2)
        plt.tight_layout()

        os.makedirs(save_dir, exist_ok=True)
        img_path = os.path.join(save_dir, f'{filename}.png')
        plt.savefig(img_path, dpi=150, bbox_inches='tight')
        plt.close()

        return img_path

    # ── 跟踪模式 ─────────────────────────────────

    def track(self) -> dict:
        """
        跟踪模式：基于当前最新数据，计算持仓状态与再平衡操作建议。
        """
        daily_df, _, _cash_interest = self._simulate()

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
                'label': self._get_asset_label(code),
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
            'label': '现金',
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
                f'| {info["label"]} | {info["market_value"]:,.2f} | '
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

# ─────────────────────────────────────────────
# 动态现金比例优化模块（PE估值驱动）
# ─────────────────────────────────────────────

def _get_period_first_dates(trading_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每月第一个交易日（用于触发估值分位检查）"""
    s = pd.Series(trading_dates, index=trading_dates)
    grouped = s.groupby(s.dt.to_period('M')).first()
    return pd.DatetimeIndex(grouped.values)


def compute_pe_quantile(
    pe_series: pd.Series,
    mode: str = 'full_history',
    window_years: int = 10,
) -> pd.Series:
    """
    计算 PE 历史分位数（无未来函数，以当日为基准向前看）。

    :param pe_series: 以日期为索引的 PE 序列
    :param mode: 'full_history'=全历史分位 / 'rolling'=滚动N年分位
    :param window_years: 滚动模式下的窗口年数
    :return: 与 pe_series 等长的分位数序列（0~1）
    """
    if mode == 'full_history':
        # expanding rank：截至当日历史数据的排名（无未来偏差）
        quantile = pe_series.expanding().rank(pct=True)
    elif mode == 'rolling':
        window = window_years * 252
        quantile = pe_series.rolling(window, min_periods=252).rank(pct=True)
    else:
        raise ValueError(f"不支持的估值分位模式 '{mode}'，可选 full_history / rolling")
    return quantile


def _get_valuation_zone(quantile: float) -> str:
    """
    根据 PE 百分位判断估值区间。

    :return: 'low'（低估）/ 'neutral'（中性）/ 'high'（高估）/ 'unknown'（无数据）
    """
    if pd.isna(quantile):
        return 'unknown'
    if quantile < 0.30:
        return 'low'
    if quantile <= 0.70:
        return 'neutral'
    return 'high'


class DynamicCashPortfolio(PermanentPortfolio):
    """
    动态现金比例永久投资组合（PE估值驱动）。

    在 PermanentPortfolio 基础上新增动态调仓逻辑：
      - 每月第一个交易日检查沪深300 PE 分位
      - 若分位区间变化（低估/中性/高估），立即调整股票与现金仓位
      - 债券与黄金始终保持 25% 目标权重不变
      - 周期末再平衡使用最新目标权重

    仓位规则：
      ┌─────────────────────┬──────┬──────┬──────┬──────┐
      │ PE 分位              │ 股票 │ 黄金 │ 国债 │ 现金 │
      ├─────────────────────┼──────┼──────┼──────┼──────┤
      │ 0–30%（低估）        │  35% │  25% │  25% │  15% │
      │ 30–70%（中性）       │  25% │  25% │  25% │  25% │
      │ 70–100%（高估）      │  15% │  25% │  25% │  35% │
      └─────────────────────┴──────┴──────┴──────┴──────┘

    注意：
      - 动态调整「局部再平衡」仅涉及股票和现金（债券/黄金当日市值不变）
      - 周期末「完整再平衡」对所有资产按最新目标权重执行
      - 若 PE 数据缺失（回测起点早于 PE 数据），自动使用中性权重（25%）
    """

    # 三种估值区间对应的股票/现金权重（债券/黄金固定 25%）
    _ZONE_WEIGHTS = {
        'low':     {'stock': 0.35, 'cash': 0.15},
        'neutral': {'stock': 0.25, 'cash': 0.25},
        'high':    {'stock': 0.15, 'cash': 0.35},
        'unknown': {'stock': 0.25, 'cash': 0.25},  # 无PE数据时退回等权
    }
    _FIXED_WEIGHT = 0.25  # 债券和黄金固定权重

    def __init__(
        self,
        etf_codes: List[str],
        initial_capital: float,
        start_date: str,
        end_date: str,
        rebalance_freq: str = 'yearly',
        cash_annual_rate: float = 0.0005,
        risk_free_rate: float = 0.0,
        transaction_cost: float = 0.0,
        data_dir: str = ETF_DATA_DIR,
        # ── 动态现金新增参数 ──
        dynamic_cash_switch: bool = True,
        valuation_calc_mode: str = 'rolling',    # 'full_history' 或 'rolling'
        pe_data_dir: str = './data/pe',
        stock_etf_code: str = None,              # 股票ETF代码（自动识别，可手动指定）
    ):
        """
        :param dynamic_cash_switch: True=开启动态现金，False=退化为等权策略
        :param valuation_calc_mode: PE分位模式，'full_history'=全历史 / 'rolling'=滚动10年
        :param pe_data_dir: PE数据目录
        :param stock_etf_code: 股票ETF代码（默认从 _ETF_TYPE_LABELS 自动识别）
        """
        super().__init__(
            etf_codes=etf_codes,
            initial_capital=initial_capital,
            start_date=start_date,
            end_date=end_date,
            rebalance_freq=rebalance_freq,
            cash_annual_rate=cash_annual_rate,
            risk_free_rate=risk_free_rate,
            transaction_cost=transaction_cost,
            data_dir=data_dir,
        )

        self.dynamic_cash_switch = dynamic_cash_switch
        self.valuation_calc_mode = valuation_calc_mode
        self.pe_data_dir = pe_data_dir

        # ── 识别股票ETF ──
        if stock_etf_code:
            if stock_etf_code not in etf_codes:
                raise ValueError(f"stock_etf_code '{stock_etf_code}' 不在 etf_codes 中")
            self.stock_code = stock_etf_code
        else:
            # 从标签映射中自动查找股票类ETF
            found = [c for c in etf_codes if _ETF_TYPE_LABELS.get(c) == '股票']
            if not found:
                raise ValueError(
                    "无法自动识别股票ETF，请通过 stock_etf_code 参数手动指定\n"
                    f"当前 etf_codes: {etf_codes}，已知标签: {_ETF_TYPE_LABELS}"
                )
            self.stock_code = found[0]

        # ── 加载并预处理PE数据 ──
        if dynamic_cash_switch:
            self._pe_quantiles = self._load_pe_quantiles()
        else:
            self._pe_quantiles = None

    def _load_pe_quantiles(self) -> pd.Series:
        """
        加载沪深300 PE 数据，计算历史分位数序列。
        无未来函数：expanding/rolling rank 确保每个时间点只用到过去数据。
        """
        from fetch.pe_data import load_csi300_pe
        pe_df = load_csi300_pe(os.path.join(self.pe_data_dir, '000300_pe.csv'))
        pe_series = pe_df['PE'].dropna().sort_index()

        quantiles = compute_pe_quantile(pe_series, mode=self.valuation_calc_mode)
        logging.info(
            f"PE分位计算完成（{self.valuation_calc_mode}），"
            f"覆盖 {pe_series.index[0].date()} ~ {pe_series.index[-1].date()}"
        )
        return quantiles

    def _get_current_target_weights(self, date: pd.Timestamp) -> dict:
        """
        查询指定日期对应的各资产目标权重。
        非股票/现金资产固定 25%，股票/现金根据 PE 分位动态调整。

        :return: {code: weight} 字典，'现金' 也包含在内
        """
        # 默认权重（等权或无PE数据时）
        default_w = {c: self.target_weight for c in self.etf_codes}
        default_w['现金'] = self.target_weight

        if not self.dynamic_cash_switch or self._pe_quantiles is None:
            return default_w

        # 查找当日或最近一个有效PE分位
        valid = self._pe_quantiles.loc[:date].dropna()
        if valid.empty:
            return default_w

        quantile = valid.iloc[-1]
        zone = _get_valuation_zone(quantile)
        zone_w = self._ZONE_WEIGHTS[zone]

        weights = {}
        for code in self.etf_codes:
            if code == self.stock_code:
                weights[code] = zone_w['stock']
            else:
                weights[code] = self._FIXED_WEIGHT  # 债券/黄金固定25%
        weights['现金'] = zone_w['cash']
        return weights

    def _simulate(self):
        """
        动态现金版本的核心模拟引擎。

        在原版基础上新增两个触发点：
          1. 月首检查：若 PE 区间变化 → 立即对股票和现金做局部再平衡
          2. 周期末再平衡：使用最新目标权重对所有资产完整再平衡

        返回: (daily_df, rebalance_logs, cash_interest_total)
        """
        if not self.dynamic_cash_switch:
            # 关闭开关时，完全复用父类逻辑
            return super()._simulate()

        prices = self.prices
        dates = self.trading_dates
        rebalance_dates = self._get_rebalance_dates()
        monthly_first_dates = set(_get_period_first_dates(dates))

        # ── 建仓（使用初始目标权重，一般为等权 25%）──
        first_p = prices.iloc[0]
        init_weights = self._get_current_target_weights(dates[0])

        # 建仓份额
        shares = {
            code: (self.initial_capital * init_weights[code]
                   / (1 + self.transaction_cost)) / first_p[code]
            for code in self.etf_codes
        }
        cash = self.initial_capital * init_weights['现金']
        cash_interest_total = 0.0

        # 记录当前估值区间（避免重复调整）
        first_valid_pe = self._pe_quantiles.loc[:dates[0]].dropna()
        current_zone = _get_valuation_zone(
            first_valid_pe.iloc[-1] if not first_valid_pe.empty else float('nan')
        )

        # 建仓记录
        init_etf_vals = {code: shares[code] * first_p[code] for code in self.etf_codes}
        rebalance_logs = [{
            '日期': dates[0],
            '操作': '建仓',
            '总资产': round(sum(init_etf_vals.values()) + cash, 2),
            '估值区间': current_zone,
            **{f'{c}_前市值': 0.0 for c in self.etf_codes},
            '现金_前市值': 0.0,
            **{f'{c}_后市值': round(init_etf_vals[c], 2) for c in self.etf_codes},
            '现金_后市值': round(cash, 2),
            **{f'{c}_调整金额': round(init_etf_vals[c], 2) for c in self.etf_codes},
            '现金_调整金额': round(cash, 2),
        }]

        daily_rows = []
        peak = self.initial_capital
        prev_date = dates[0]

        for date in dates:
            p = prices.loc[date]

            # ── 现金计息 ──
            if date != dates[0]:
                calendar_days = (date - prev_date).days
                interest = cash * ((1 + self.cash_annual_rate / 365) ** calendar_days - 1)
                cash += interest
                cash_interest_total += interest

            etf_vals = {code: shares[code] * p[code] for code in self.etf_codes}
            total = sum(etf_vals.values()) + cash

            # ── 月首估值检查：若区间变化则局部再平衡（股票+现金）──
            if date in monthly_first_dates and date != dates[0]:
                target_w = self._get_current_target_weights(date)
                new_zone = _get_valuation_zone(
                    self._pe_quantiles.loc[:date].dropna().iloc[-1]
                    if not self._pe_quantiles.loc[:date].dropna().empty else float('nan')
                )

                if new_zone != current_zone:
                    # 仅调整股票和现金，债券/黄金按原持仓不动
                    target_stock_val = total * target_w[self.stock_code]
                    target_cash_val = total * target_w['现金']

                    stock_diff = target_stock_val - etf_vals[self.stock_code]
                    cash_diff = target_cash_val - cash

                    # 执行调整（交易费用）
                    fee = abs(stock_diff) * self.transaction_cost
                    net_stock_val = target_stock_val - (fee if stock_diff > 0 else -fee)
                    shares[self.stock_code] = net_stock_val / p[self.stock_code]
                    cash = target_cash_val

                    # 重新计算总资产
                    etf_vals = {code: shares[code] * p[code] for code in self.etf_codes}
                    total = sum(etf_vals.values()) + cash

                    rebalance_logs.append({
                        '日期': date,
                        '操作': f'估值调整({current_zone}→{new_zone})',
                        '总资产': round(total, 2),
                        '估值区间': new_zone,
                        '现金_前市值': round(cash - cash_diff, 2),
                        **{f'{c}_前市值': round(etf_vals[c] - (stock_diff if c == self.stock_code else 0), 2)
                           for c in self.etf_codes},
                        '现金_后市值': round(cash, 2),
                        **{f'{c}_后市值': round(etf_vals[c], 2) for c in self.etf_codes},
                        '现金_调整金额': round(cash_diff, 2),
                        **{f'{c}_调整金额': round(stock_diff if c == self.stock_code else 0.0, 2)
                           for c in self.etf_codes},
                    })
                    current_zone = new_zone

            # ── 周期末完整再平衡 ──
            elif date in rebalance_dates:
                target_w = self._get_current_target_weights(date)
                target_per = {code: total * target_w[code] for code in self.etf_codes}
                target_per['现金'] = total * target_w['现金']

                one_way = sum(max(0, target_per[c] - etf_vals[c]) for c in self.etf_codes)
                fee = one_way * self.transaction_cost * 2
                net_total = total - fee

                # 重新用扣费后的总资产计算目标
                net_target = {code: net_total * target_w[code] for code in self.etf_codes}
                net_target['现金'] = net_total * target_w['现金']

                rec = {
                    '日期': date,
                    '操作': '再平衡',
                    '总资产': round(net_total, 2),
                    '估值区间': current_zone,
                    '现金_前市值': round(cash, 2),
                    **{f'{c}_前市值': round(etf_vals[c], 2) for c in self.etf_codes},
                }
                for code in self.etf_codes:
                    new_val = net_target[code]
                    shares[code] = new_val / p[code]
                    rec[f'{code}_后市值'] = round(new_val, 2)
                    rec[f'{code}_调整金额'] = round(new_val - etf_vals[code], 2)

                rec['现金_后市值'] = round(net_target['现金'], 2)
                rec['现金_调整金额'] = round(net_target['现金'] - cash, 2)
                cash = net_target['现金']

                rebalance_logs.append(rec)

                # 更新 etf_vals 和 total（再平衡后）
                etf_vals = {code: shares[code] * p[code] for code in self.etf_codes}
                total = sum(etf_vals.values()) + cash

            # ── 更新最大回撤 ──
            peak = max(peak, total)
            dd = (peak - total) / peak if peak > 0 else 0.0

            # ── 查询当日PE分位（用于记录）──
            pe_valid = self._pe_quantiles.loc[:date].dropna()
            cur_pe_q = float(pe_valid.iloc[-1]) if not pe_valid.empty else float('nan')

            row = {
                '日期': date,
                '总资产': total,
                '回撤': dd,
                '估值区间': current_zone,
                'PE分位': cur_pe_q,
                '现金_市值': cash,
                '现金_占比': cash / total,
                **{f'{c}_市值': etf_vals[c] for c in self.etf_codes},
                **{f'{c}_占比': etf_vals[c] / total for c in self.etf_codes},
            }
            daily_rows.append(row)
            prev_date = date

        daily_df = pd.DataFrame(daily_rows).set_index('日期')
        return daily_df, rebalance_logs, cash_interest_total

    def backtest(self) -> dict:
        """
        执行回测，并在开启动态现金时同步运行静态对照组。

        :return: 结果字典，dynamic_cash_switch=True 时额外含 'baseline' 键
        """
        result = super().backtest()  # 先运行动态版本（_simulate 已被重写）

        if self.dynamic_cash_switch:
            # ── 运行静态对照组（关闭动态，等权策略）──
            baseline_portfolio = PermanentPortfolio(
                etf_codes=self.etf_codes,
                initial_capital=self.initial_capital,
                start_date=self.start_date,
                end_date=self.end_date,
                rebalance_freq=self.rebalance_freq,
                cash_annual_rate=self.cash_annual_rate,
                risk_free_rate=self.risk_free_rate,
                transaction_cost=self.transaction_cost,
            )
            result['baseline'] = baseline_portfolio.backtest()

            # ── 统计各估值区间的组合表现 ──
            daily_df = result['daily_df']
            zone_stats = {}
            for zone in ['low', 'neutral', 'high']:
                mask = daily_df['估值区间'] == zone
                zone_df = daily_df[mask]
                if len(zone_df) < 2:
                    zone_stats[zone] = {'days': 0, 'return': 0.0}
                    continue
                # 使用对数收益率累计
                zone_rets = zone_df['总资产'].pct_change().dropna()
                cumret = (1 + zone_rets).prod() - 1
                zone_stats[zone] = {
                    'days': len(zone_df),
                    'return': cumret,
                }
            result['zone_stats'] = zone_stats

        return result

    def generate_backtest_report(self, result: dict, chart_filename: str = None) -> str:
        """生成回测报告，动态开关开启时追加对比分析板块"""
        # 调用父类生成基础报告
        base_report = super().generate_backtest_report(result, chart_filename)

        if not self.dynamic_cash_switch or 'baseline' not in result:
            return base_report

        # ── 追加动态现金优化分析板块 ──
        baseline = result['baseline']
        zone_stats = result.get('zone_stats', {})
        mode_cn = '全历史' if self.valuation_calc_mode == 'full_history' else '滚动10年'
        stock_label = self._get_asset_label(self.stock_code)

        extra_lines = [
            '',
            '---',
            '## 七、动态现金优化分析',
            '',
            f'> 股票标的：**{stock_label}** | PE分位模式：**{mode_cn}** | '
            f'动态规则：低估→股票35%/现金15%，中性→各25%，高估→股票15%/现金35%',
            '',
            '### 7.1 策略对比（动态 vs 等权）',
            '| 指标 | 动态现金策略 | 原等权策略 | 差值 |',
            '|------|------------|----------|------|',
        ]
        for key, label in [
            ('cumulative_return', '累计收益率'),
            ('annualized_return', '年化收益率'),
            ('max_drawdown', '最大回撤'),
            ('sharpe', '夏普比率'),
        ]:
            dyn_v = result[key]
            bas_v = baseline[key]
            if key == 'max_drawdown':
                diff_str = f'{dyn_v - bas_v:+.2%}'
                extra_lines.append(
                    f'| {label} | {dyn_v:.2%} | {bas_v:.2%} | {diff_str} |'
                )
            elif key == 'sharpe':
                diff_str = f'{dyn_v - bas_v:+.2f}'
                extra_lines.append(
                    f'| {label} | {dyn_v:.2f} | {bas_v:.2f} | {diff_str} |'
                )
            else:
                diff_str = f'{dyn_v - bas_v:+.2%}'
                extra_lines.append(
                    f'| {label} | {dyn_v:+.2%} | {bas_v:+.2%} | {diff_str} |'
                )
        extra_lines.append(
            f'| 期末资产 | {result["final_value"]:,.2f} 元 | {baseline["final_value"]:,.2f} 元 | '
            f'{result["final_value"] - baseline["final_value"]:+,.2f} 元 |'
        )
        extra_lines.append('')

        # ── 各估值区间表现统计 ──
        zone_cn = {'low': '低估(0–30%)', 'neutral': '中性(30–70%)', 'high': '高估(70–100%)'}
        extra_lines += [
            '### 7.2 各估值区间组合表现',
            '| 估值区间 | 交易日数 | 区间累计收益 |',
            '|---------|--------|------------|',
        ]
        for zone in ['low', 'neutral', 'high']:
            stats = zone_stats.get(zone, {'days': 0, 'return': 0.0})
            extra_lines.append(
                f'| {zone_cn[zone]} | {stats["days"]} 天 | {stats["return"]:+.2%} |'
            )
        extra_lines.append('')

        # ── 估值调整操作记录 ──
        logs = result['rebalance_logs']
        adjust_logs = [r for r in logs if r.get('操作', '').startswith('估值调整')]
        extra_lines += ['### 7.3 估值调整操作记录', '']
        if adjust_logs:
            stock_label_short = self._get_asset_label(self.stock_code)
            extra_lines += [
                f'| 日期 | 操作 | 总资产 | {stock_label_short} 调整 | 现金调整 |',
                '|------|------|--------|---------|---------|',
            ]
            for rec in adjust_logs:
                date_s = pd.Timestamp(rec['日期']).strftime('%Y-%m-%d')
                stock_adj = rec.get(f'{self.stock_code}_调整金额', 0)
                cash_adj = rec.get('现金_调整金额', 0)
                extra_lines.append(
                    f'| {date_s} | {rec["操作"]} | {rec["总资产"]:,.2f} | '
                    f'{stock_adj:+,.2f} | {cash_adj:+,.2f} |'
                )
        else:
            extra_lines.append('> 回测期间内无估值区间变化，未触发估值调整。')
        extra_lines.append('')

        return base_report + '\n'.join(extra_lines)

    def plot_backtest_results(self, result: dict, save_dir: str, filename: str) -> str:
        """
        绘制动态现金回测图表。
        相比父类，额外绘制静态对照组的总资产曲线和各估值区间背景色。
        """
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False

        daily_df = result['daily_df']
        dates = daily_df.index

        fig, ax1 = plt.subplots(figsize=(16, 8))

        # ── 左Y轴：总资产对比 ──
        ax1.fill_between(dates, daily_df['总资产'], alpha=0.08, color='#2980b9')
        ax1.plot(dates, daily_df['总资产'], color='#2980b9', linewidth=2.5,
                 label='动态现金策略（左轴）', zorder=3)

        # 叠加静态对照组
        if self.dynamic_cash_switch and 'baseline' in result:
            bl_df = result['baseline']['daily_df']
            ax1.plot(bl_df.index, bl_df['总资产'], color='#95a5a6', linewidth=1.5,
                     linestyle='--', label='原等权策略（左轴）', zorder=2)

        ax1.set_xlabel('日期', fontsize=12)
        ax1.set_ylabel('总资产（元）', color='#2980b9', fontsize=12)
        ax1.tick_params(axis='y', labelcolor='#2980b9')

        # ── 右Y轴：各成员累计收益率 ──
        ax2 = ax1.twinx()
        etf_colors = ['#e74c3c', '#f39c12', '#27ae60', '#8e44ad', '#16a085']

        for i, code in enumerate(self.etf_codes):
            prices_series = self.prices[code]
            cum_ret = (prices_series / prices_series.iloc[0] - 1) * 100
            label = self._get_asset_label(code)
            ax2.plot(dates, cum_ret, linestyle='--', linewidth=1.8,
                     color=etf_colors[i % len(etf_colors)], label=label, alpha=0.85)

        cash_cum_ret = (daily_df['现金_市值'] / daily_df['现金_市值'].iloc[0] - 1) * 100
        ax2.plot(dates, cash_cum_ret, linestyle=':', linewidth=1.5, color='#7f8c8d',
                 label='现金', alpha=0.85)

        portfolio_cum_ret = (daily_df['总资产'] / daily_df['总资产'].iloc[0] - 1) * 100
        ax2.plot(dates, portfolio_cum_ret, linestyle='-.', linewidth=2.0, color='#2980b9',
                 label='组合收益率（右轴）', alpha=0.75)

        ax2.axhline(y=0, color='#bdc3c7', linestyle='-', linewidth=0.8, alpha=0.6)
        ax2.set_ylabel('累计收益率（%）', color='#27ae60', fontsize=12)
        ax2.tick_params(axis='y', labelcolor='#27ae60')

        # ── 估值区间背景色（低估=浅绿，高估=浅红）──
        if self.dynamic_cash_switch and '估值区间' in daily_df.columns:
            zone_colors = {'low': '#d5f5e3', 'high': '#fadbd8'}
            for zone, color in zone_colors.items():
                mask = daily_df['估值区间'] == zone
                if mask.any():
                    # 找连续区段并填充背景色
                    starts = dates[mask & ~mask.shift(1, fill_value=False)]
                    ends = dates[mask & ~mask.shift(-1, fill_value=False)]
                    for s, e in zip(starts, ends):
                        ax1.axvspan(s, e, alpha=0.25, color=color, zorder=0)

        # ── 标记再平衡日（垂直虚线）──
        logs = result['rebalance_logs']
        rebal_dates = [pd.Timestamp(r['日期']) for r in logs if r['操作'] == '再平衡']
        for rd in rebal_dates:
            ax1.axvline(x=rd, color='#bdc3c7', linestyle=':', linewidth=0.9, alpha=0.7, zorder=1)
        if rebal_dates:
            ax1.axvline(x=rebal_dates[0], color='#bdc3c7', linestyle=':', linewidth=0.9,
                        alpha=0.7, label='再平衡日', zorder=1)

        # ── 标题与图例 ──
        freq_cn = {'monthly': '月度', 'quarterly': '季度', 'yearly': '年度'}.get(
            self.rebalance_freq, self.rebalance_freq
        )
        mode_cn = '全历史' if self.valuation_calc_mode == 'full_history' else '滚动10年'
        start_d = daily_df.index[0].strftime('%Y-%m-%d')
        end_d = daily_df.index[-1].strftime('%Y-%m-%d')
        plt.title(
            f'永久投资组合回测（动态现金/{mode_cn}PE分位，{freq_cn}再平衡，{start_d}~{end_d}）',
            fontsize=13, pad=15
        )

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9)
        ax1.grid(True, alpha=0.2)
        plt.tight_layout()

        os.makedirs(save_dir, exist_ok=True)
        img_path = os.path.join(save_dir, f'{filename}.png')
        plt.savefig(img_path, dpi=150, bbox_inches='tight')
        plt.close()
        return img_path


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
