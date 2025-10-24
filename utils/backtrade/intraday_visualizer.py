"""
日内交易可视化工具（1分钟K线）
用于可视化做T监控系统的回测结果
"""
import os
from datetime import datetime

# 设置非交互式后端，避免多线程警告
import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.font_manager import FontProperties

plt.rcParams['axes.unicode_minus'] = False


class IntradayVisualizer:
    """日内交易可视化器（1分钟K线）"""

    def __init__(self, output_dir='alerting/backtest_results'):
        """
        初始化可视化器
        :param output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.style = self._setup_style()

    @staticmethod
    def _get_font_properties():
        """获取中文字体"""
        font_path = 'fonts/微软雅黑.ttf'
        if os.path.exists(font_path):
            return FontProperties(fname=font_path)

        # 备用字体
        import matplotlib.font_manager as fm
        font_paths = ['msyh.ttc', 'SimHei.ttf', 'PingFang.ttc']
        for font_name in font_paths:
            found_path = fm.findfont(font_name, fallback_to_default=True)
            if found_path and os.path.basename(found_path).lower() in font_name.lower():
                return FontProperties(fname=found_path)

        return None

    def _setup_style(self):
        """设置图表样式"""
        font_prop = self._get_font_properties()

        mc = mpf.make_marketcolors(
            up='red', down='green',
            edge={'up': 'red', 'down': 'green'},
            wick={'up': 'red', 'down': 'green'},
            volume='inherit'
        )

        rc_params = {'font.family': font_prop.get_name()} if font_prop else {}
        return mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mc,
            rc=rc_params
        )

    def plot_backtest_result(self, df_1m, signals, symbol, stock_name=None,
                             backtest_start=None, backtest_end=None, **kwargs):
        """
        绘制回测结果（通用接口）
        
        :param df_1m: 1分钟K线数据 DataFrame
                     必须包含: datetime, open, high, low, close, vol
        :param signals: 信号列表 list of dict
                       每个dict包含: type, price, time, reason, strength
        :param symbol: 股票代码
        :param stock_name: 股票名称（可选）
        :param backtest_start: 回测开始时间
        :param backtest_end: 回测结束时间
        :param kwargs: 其他参数（如技术指标）
        :return: 输出文件路径
        """
        if df_1m is None or df_1m.empty:
            print(f"警告: {symbol} 无数据，跳过可视化")
            return None

        if not signals:
            print(f"警告: {symbol} 无信号，跳过可视化")
            return None

        # 准备K线数据
        chart_df = self._prepare_chart_data(df_1m)
        if chart_df.empty:
            print(f"警告: {symbol} 数据准备失败，跳过可视化")
            return None

        # 添加信号标记
        addplots = self._create_signal_markers(chart_df, signals)

        # 生成标题
        title = self._generate_title(
            symbol, stock_name, signals,
            backtest_start, backtest_end
        )

        # 绘制图表
        output_path = self._plot_chart(
            chart_df, addplots, title, symbol,
            backtest_start, backtest_end
        )

        return output_path

    def _prepare_chart_data(self, df_1m):
        """准备绘图数据"""
        df = df_1m.copy()

        # 确保datetime为索引
        if 'datetime' in df.columns:
            df = df.set_index('datetime')

        # 重命名列以符合mplfinance要求
        rename_map = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'vol': 'Volume'
        }
        df = df.rename(columns=rename_map)

        # 确保索引为DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # 移除时区信息（如果有）
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # 只保留必要的列
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        df = df[[col for col in required_cols if col in df.columns]]

        # 清理无效数据
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

        return df

    def _create_signal_markers(self, chart_df, signals):
        """创建信号标记"""
        buy_markers = [float('nan')] * len(chart_df)
        sell_markers = [float('nan')] * len(chart_df)

        has_buy = False
        has_sell = False

        for signal in signals:
            signal_time = signal['time']
            signal_type = signal['type']

            # 确保时间格式一致
            if isinstance(signal_time, str):
                signal_time = pd.to_datetime(signal_time)
            elif hasattr(signal_time, 'tz') and signal_time.tz is not None:
                signal_time = signal_time.tz_localize(None)

            # 查找最接近的K线
            try:
                idx = chart_df.index.searchsorted(signal_time, side='right') - 1
                if idx >= 0 and idx < len(chart_df):
                    if signal_type == 'BUY':
                        # 买入信号标记在K线下方
                        buy_markers[idx] = chart_df.iloc[idx]['Low'] * 0.998
                        has_buy = True
                    elif signal_type == 'SELL':
                        # 卖出信号标记在K线上方
                        sell_markers[idx] = chart_df.iloc[idx]['High'] * 1.002
                        has_sell = True
            except Exception as e:
                print(f"警告: 信号标记失败 {signal_time}: {e}")
                continue

        # 创建addplot列表（只添加有信号的标记）
        addplots = []

        # 买入信号：绿色向上箭头（仅在有买入信号时添加）
        if has_buy:
            addplots.append(
                mpf.make_addplot(
                    buy_markers,
                    type='scatter',
                    marker='^',
                    color='lime',
                    markersize=100,
                    label='买入信号'
                )
            )

        # 卖出信号：红色向下箭头（仅在有卖出信号时添加）
        if has_sell:
            addplots.append(
                mpf.make_addplot(
                    sell_markers,
                    type='scatter',
                    marker='v',
                    color='red',
                    markersize=100,
                    label='卖出信号'
                )
            )

        return addplots

    def _generate_title(self, symbol, stock_name, signals,
                        backtest_start, backtest_end):
        """生成图表标题"""
        # 统计信号
        buy_signals = [s for s in signals if s['type'] == 'BUY']
        sell_signals = [s for s in signals if s['type'] == 'SELL']

        # 统计强度分布
        strong_signals = [s for s in signals if s.get('strength', 0) >= 85]
        medium_signals = [s for s in signals if 65 <= s.get('strength', 0) < 85]
        weak_signals = [s for s in signals if s.get('strength', 0) < 65]

        stock_display = f"{symbol} {stock_name}" if stock_name else symbol

        title = (
            f"做T回测结果 - {stock_display}\n"
            f"信号统计: {len(buy_signals)}买 / {len(sell_signals)}卖 "
            f"(强:{len(strong_signals)} 中:{len(medium_signals)} 弱:{len(weak_signals)})"
        )

        if backtest_start and backtest_end:
            title += f"\n回测区间: {backtest_start} ~ {backtest_end}"

        return title

    def _plot_chart(self, chart_df, addplots, title, symbol,
                    backtest_start, backtest_end):
        """绘制并保存图表"""
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"backtest_{symbol}_{timestamp}.png"
        output_path = os.path.join(self.output_dir, filename)

        # 创建图表（关闭数据量警告）
        fig, axes = mpf.plot(
            chart_df,
            type='candle',
            style=self.style,
            ylabel='价格',
            volume=True,
            ylabel_lower='成交量',
            addplot=addplots,
            figsize=(20, 10),
            returnfig=True,
            tight_layout=True,
            warn_too_much_data=len(chart_df) + 1000  # 关闭数据量警告
        )

        # 设置标题
        axes[0].set_title(title, loc='left', fontweight='bold', fontsize=12)

        # 添加图例
        axes[0].legend(loc='upper left', fontsize=10)

        # 优化X轴显示 - 每30根K线显示一个刻度
        from matplotlib.ticker import FuncFormatter

        num_bars = len(chart_df)

        # 自定义格式化函数：将数值索引转换为实际日期
        def format_date(x, pos=None):
            """将mplfinance的数值索引转换为日期时间字符串"""
            idx = int(x)
            if idx < 0 or idx >= len(chart_df):
                return ''
            dt = chart_df.index[idx]
            # 统一显示完整日期时间：月-日 时:分
            return dt.strftime('%m-%d %H:%M')

        # 设置主刻度位置：每30根K线一个刻度
        tick_spacing = 30
        tick_positions = list(range(0, num_bars, tick_spacing))

        # 确保第一个和最后一个位置有刻度
        if 0 not in tick_positions:
            tick_positions.insert(0, 0)
        if num_bars - 1 not in tick_positions:
            tick_positions.append(num_bars - 1)

        # 应用到主图
        axes[0].set_xticks(tick_positions)
        axes[0].xaxis.set_major_formatter(FuncFormatter(format_date))

        # 应用到成交量副图
        if len(axes) > 1:
            axes[1].set_xticks(tick_positions)
            axes[1].xaxis.set_major_formatter(FuncFormatter(format_date))

        fig.autofmt_xdate(rotation=45)

        # 保存图表
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        print(f"✓ 已生成回测图表: {output_path}")
        return output_path

    def plot_multiple_stocks(self, backtest_results):
        """
        批量绘制多个股票的回测结果
        
        :param backtest_results: list of dict, 每个dict包含:
                                {
                                    'symbol': 股票代码,
                                    'stock_name': 股票名称,
                                    'df_1m': 1分钟K线数据,
                                    'signals': 信号列表,
                                    'backtest_start': 回测开始时间,
                                    'backtest_end': 回测结束时间
                                }
        :return: 输出文件路径列表
        """
        output_paths = []

        for result in backtest_results:
            try:
                path = self.plot_backtest_result(
                    df_1m=result['df_1m'],
                    signals=result['signals'],
                    symbol=result['symbol'],
                    stock_name=result.get('stock_name'),
                    backtest_start=result.get('backtest_start'),
                    backtest_end=result.get('backtest_end')
                )
                if path:
                    output_paths.append(path)
            except Exception as e:
                print(f"错误: 绘制 {result.get('symbol', 'unknown')} 时失败: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n批量可视化完成，共生成 {len(output_paths)} 个图表")
        return output_paths


def plot_intraday_backtest(df_1m, signals, symbol, stock_name=None,
                           backtest_start=None, backtest_end=None,
                           output_dir='alerting/backtest_results'):
    """
    快速函数：绘制单个股票的日内回测结果
    
    :param df_1m: 1分钟K线数据
    :param signals: 信号列表
    :param symbol: 股票代码
    :param stock_name: 股票名称
    :param backtest_start: 回测开始时间
    :param backtest_end: 回测结束时间
    :param output_dir: 输出目录
    :return: 输出文件路径
    """
    visualizer = IntradayVisualizer(output_dir=output_dir)
    return visualizer.plot_backtest_result(
        df_1m=df_1m,
        signals=signals,
        symbol=symbol,
        stock_name=stock_name,
        backtest_start=backtest_start,
        backtest_end=backtest_end
    )
