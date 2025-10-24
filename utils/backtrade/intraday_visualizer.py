"""
日内交易可视化工具（1分钟K线）
用于可视化做T监控系统的回测结果
"""
import os
import logging
from datetime import datetime
import warnings

# 设置非交互式后端，避免多线程警告
import matplotlib

matplotlib.use('Agg')

# 抑制matplotlib字体警告
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.font_manager import FontProperties

plt.rcParams['axes.unicode_minus'] = False


class IntradayVisualizer:
    """日内交易可视化器（1分钟K线）"""

    def __init__(self, output_dir='backtest_results'):
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
        # 尝试多个可能的字体路径
        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        
        font_candidates = [
            'fonts/微软雅黑.ttf',  # 当前工作目录
            os.path.join(project_root, 'fonts/微软雅黑.ttf'),  # 项目根目录
            os.path.join(os.getcwd(), 'fonts/微软雅黑.ttf'),  # 绝对路径
        ]
        
        for font_path in font_candidates:
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
        addplots, annotation_info = self._create_signal_markers(chart_df, signals)

        # 生成标题
        title = self._generate_title(
            symbol, stock_name, signals,
            backtest_start, backtest_end
        )

        # 绘制图表
        output_path = self._plot_chart(
            chart_df, addplots, title, symbol,
            backtest_start, backtest_end, annotation_info
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
        """创建信号标记（根据评分强度使用不同颜色）"""
        # 检查是否所有信号都有评分（向后兼容）
        has_scoring = all('strength' in s and s['strength'] is not None for s in signals)
        
        if not has_scoring:
            # 无评分模式：使用原始逻辑（完全兼容旧版本）
            return self._create_signal_markers_legacy(chart_df, signals)
        
        # 有评分模式：按强度分层显示
        # 分别为不同强度创建标记数组
        buy_strong = [float('nan')] * len(chart_df)   # 强买入
        buy_medium = [float('nan')] * len(chart_df)   # 中买入
        buy_weak = [float('nan')] * len(chart_df)     # 弱买入
        
        sell_strong = [float('nan')] * len(chart_df)  # 强卖出
        sell_medium = [float('nan')] * len(chart_df)  # 中卖出
        sell_weak = [float('nan')] * len(chart_df)    # 弱卖出

        has_buy_strong = False
        has_buy_medium = False
        has_buy_weak = False
        has_sell_strong = False
        has_sell_medium = False
        has_sell_weak = False
        
        # 用于存储标注信息（时间索引 -> 信号信息）
        annotation_info = {}

        for signal in signals:
            signal_time = signal['time']
            signal_type = signal['type']
            signal_strength = signal['strength']

            # 确保时间格式一致
            if isinstance(signal_time, str):
                signal_time = pd.to_datetime(signal_time)
            elif hasattr(signal_time, 'tz') and signal_time.tz is not None:
                signal_time = signal_time.tz_localize(None)

            # 查找最接近的K线
            try:
                idx = chart_df.index.searchsorted(signal_time, side='right') - 1
                if idx >= 0 and idx < len(chart_df):
                    # 根据信号强度分类
                    if signal_strength >= 85:
                        strength_level = 'strong'
                    elif signal_strength >= 65:
                        strength_level = 'medium'
                    else:
                        strength_level = 'weak'
                    
                    if signal_type == 'BUY':
                        # 买入信号标记在K线下方
                        marker_pos = chart_df.iloc[idx]['Low'] * 0.998
                        if strength_level == 'strong':
                            buy_strong[idx] = marker_pos
                            has_buy_strong = True
                        elif strength_level == 'medium':
                            buy_medium[idx] = marker_pos
                            has_buy_medium = True
                        else:
                            buy_weak[idx] = marker_pos
                            has_buy_weak = True
                        
                        # 记录标注信息（买入标注在下方）
                        annotation_info[idx] = {
                            'type': 'BUY',
                            'strength': signal_strength,
                            'price': chart_df.iloc[idx]['Low'],
                            'time': chart_df.index[idx]
                        }
                        
                    elif signal_type == 'SELL':
                        # 卖出信号标记在K线上方
                        marker_pos = chart_df.iloc[idx]['High'] * 1.002
                        if strength_level == 'strong':
                            sell_strong[idx] = marker_pos
                            has_sell_strong = True
                        elif strength_level == 'medium':
                            sell_medium[idx] = marker_pos
                            has_sell_medium = True
                        else:
                            sell_weak[idx] = marker_pos
                            has_sell_weak = True
                        
                        # 记录标注信息（卖出标注在上方）
                        annotation_info[idx] = {
                            'type': 'SELL',
                            'strength': signal_strength,
                            'price': chart_df.iloc[idx]['High'],
                            'time': chart_df.index[idx]
                        }
                        
            except Exception as e:
                print(f"警告: 信号标记失败 {signal_time}: {e}")
                continue

        # 创建addplot列表
        addplots = []

        # 买入信号 - 按强度分层（使用文字而非星号，避免字体警告）
        if has_buy_strong:
            addplots.append(
                mpf.make_addplot(
                    buy_strong,
                    type='scatter',
                    marker='^',
                    color='#00FF00',  # 亮绿色（强）
                    markersize=150,
                    label='买入[强]'
                )
            )
        
        if has_buy_medium:
            addplots.append(
                mpf.make_addplot(
                    buy_medium,
                    type='scatter',
                    marker='^',
                    color='#90EE90',  # 浅绿色（中）
                    markersize=120,
                    label='买入[中]'
                )
            )
        
        if has_buy_weak:
            addplots.append(
                mpf.make_addplot(
                    buy_weak,
                    type='scatter',
                    marker='^',
                    color='#98FB98',  # 更浅绿色（弱）
                    markersize=100,
                    label='买入[弱]'
                )
            )

        # 卖出信号 - 按强度分层
        if has_sell_strong:
            addplots.append(
                mpf.make_addplot(
                    sell_strong,
                    type='scatter',
                    marker='v',
                    color='#FF0000',  # 亮红色（强）
                    markersize=150,
                    label='卖出[强]'
                )
            )
        
        if has_sell_medium:
            addplots.append(
                mpf.make_addplot(
                    sell_medium,
                    type='scatter',
                    marker='v',
                    color='#FF6B6B',  # 浅红色（中）
                    markersize=120,
                    label='卖出[中]'
                )
            )
        
        if has_sell_weak:
            addplots.append(
                mpf.make_addplot(
                    sell_weak,
                    type='scatter',
                    marker='v',
                    color='#FFA07A',  # 更浅红色（弱）
                    markersize=100,
                    label='卖出[弱]'
                )
            )

        return addplots, annotation_info

    def _create_signal_markers_legacy(self, chart_df, signals):
        """创建信号标记（旧版兼容模式 - 无评分）"""
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

        # 买入信号：绿色向上箭头
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

        # 卖出信号：红色向下箭头
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

        return addplots, {}  # 返回空的annotation_info

    def _generate_title(self, symbol, stock_name, signals,
                        backtest_start, backtest_end):
        """生成图表标题"""
        # 统计信号
        buy_signals = [s for s in signals if s['type'] == 'BUY']
        sell_signals = [s for s in signals if s['type'] == 'SELL']

        stock_display = f"{symbol} {stock_name}" if stock_name else symbol
        
        # 检查是否有评分
        has_scoring = all('strength' in s and s['strength'] is not None for s in signals)
        
        if has_scoring:
            # 有评分模式：统计强度分布
            strong_signals = [s for s in signals if s.get('strength', 0) >= 85]
            medium_signals = [s for s in signals if 65 <= s.get('strength', 0) < 85]
            weak_signals = [s for s in signals if s.get('strength', 0) < 65]

            title = (
                f"做T回测结果 - {stock_display}\n"
                f"信号统计: {len(buy_signals)}买 / {len(sell_signals)}卖 "
                f"(强:{len(strong_signals)} 中:{len(medium_signals)} 弱:{len(weak_signals)})"
            )
        else:
            # 无评分模式：简化显示
            title = (
                f"做T回测结果 - {stock_display}\n"
                f"信号统计: {len(buy_signals)}买 / {len(sell_signals)}卖"
            )

        if backtest_start and backtest_end:
            title += f"\n回测区间: {backtest_start} ~ {backtest_end}"

        return title

    def _plot_chart(self, chart_df, addplots, title, symbol,
                    backtest_start, backtest_end, annotation_info):
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
        
        # 添加评分标注
        if annotation_info:
            self._add_score_annotations(axes[0], chart_df, annotation_info)

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
        
        # 等待图片完全写入磁盘
        import time
        time.sleep(0.5)
        
        plt.close(fig)

        print(f"✓ 已生成回测图表: {output_path}")
        return output_path
    
    def _add_score_annotations(self, ax, chart_df, annotation_info):
        """
        在信号箭头旁添加评分标注
        
        :param ax: matplotlib轴对象
        :param chart_df: K线数据
        :param annotation_info: 标注信息字典 {idx: {'type': 'BUY/SELL', 'strength': score, ...}}
        """
        # 获取字体属性
        font_prop = self._get_font_properties()
        font_params = {'fontproperties': font_prop} if font_prop else {}
        
        for idx, info in annotation_info.items():
            signal_type = info['type']
            strength = info['strength']
            
            # 根据评分强度设置颜色
            if strength >= 85:
                text_color = '#4B0082'  # 靛青（强）
                bg_color = '#FFEFD5' if signal_type == 'BUY' else '#E1FFFF'
            elif strength >= 65:
                text_color = '#483D8B'  # 岩色（中）
                bg_color = '#FFDEAD' if signal_type == 'BUY' else '#F0FFFF'
            else:
                text_color = '#696969'  # 灰色（弱）
                bg_color = '#FAFAFA'
            
            # 计算标注位置
            if signal_type == 'BUY':
                # 买入标注在箭头下方
                y_offset = -0.015  # 向下偏移1.5%
                va = 'top'
            else:
                # 卖出标注在箭头上方
                y_offset = 0.015  # 向上偏移1.5%
                va = 'bottom'
            
            # 获取价格范围用于计算偏移
            price_range = chart_df['High'].max() - chart_df['Low'].min()
            y_pos = info['price'] * (1 + y_offset)
            
            # 添加评分文本（带背景框）
            ax.text(
                idx, y_pos,
                f"{int(strength)}",
                fontsize=9,
                fontweight='bold',
                color=text_color,
                ha='center',
                va=va,
                bbox=dict(
                    boxstyle='round,pad=0.3',
                    facecolor=bg_color,
                    edgecolor=text_color,
                    linewidth=1,
                    alpha=0.8
                ),
                zorder=10,  # 确保在最上层显示
                **font_params
            )

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
                           output_dir=None):
    """
    快速函数：绘制单个股票的日内回测结果
    
    :param df_1m: 1分钟K线数据
    :param signals: 信号列表
    :param symbol: 股票代码
    :param stock_name: 股票名称
    :param backtest_start: 回测开始时间
    :param backtest_end: 回测结束时间
    :param output_dir: 输出目录（默认为项目根目录下的 alerting/backtest_results）
    :return: 输出文件路径
    """
    # 智能路径解析：确保无论从哪里运行都保存到正确位置
    if output_dir is None:
        current_file = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
        output_dir = os.path.join(project_root, 'alerting', 'backtest_results')
    
    visualizer = IntradayVisualizer(output_dir=output_dir)
    return visualizer.plot_backtest_result(
        df_1m=df_1m,
        signals=signals,
        symbol=symbol,
        stock_name=stock_name,
        backtest_start=backtest_start,
        backtest_end=backtest_end
    )
