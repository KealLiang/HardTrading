import backtrader as bt
import numpy as np
import talib


class TALibPatternStrategy(bt.Strategy):
    """
    使用TA-Lib库实现的K线形态识别策略
    这个策略使用TA-Lib内置函数识别多种K线形态，并基于形态信号进行交易
    """
    params = (
        ('order_percentage', 0.2),  # 每次交易使用账户资金的比例
        ('stop_loss_pct', 0.05),    # 止损百分比
        ('window_size', 20),        # 形态识别窗口大小，默认改为20
        ('penetration', 0),         # 星形态渗透率参数，默认为0以放宽条件
        ('debug', True),            # 是否输出更多调试信息
    )

    def __init__(self):
        # 获取OHLC数据，用于TA-Lib函数
        self.dataopen = self.data.open
        self.datahigh = self.data.high
        self.datalow = self.data.low
        self.dataclose = self.data.close

        # 当前订单
        self.order = None
        self.buyprice = None
        self.stop_loss = None

        # 需要的最小历史数据点数
        self.min_history = self.p.window_size

    def log(self, txt, dt=None):
        """日志打印函数"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY 买入: 成交价 {order.executed.price:.2f}, 数量 {order.executed.size}')
                self.buyprice = order.executed.price
                self.stop_loss = self.buyprice * (1 - self.p.stop_loss_pct)
            elif order.issell():
                self.log(f'SELL 卖出: 成交价 {order.executed.price:.2f}, 数量 {order.executed.size}')
                self.stop_loss = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单失败')

        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        arrow = ('-' * 10) + '>'
        self.log(f'交易盈亏 {arrow} 毛收益 {trade.pnl:.2f}, 净收益 {trade.pnlcomm:.2f}')

    def next(self):
        # 如果有未完成的订单，不操作
        if self.order:
            return

        # 确保有足够的历史数据进行形态识别
        if len(self.data) < self.min_history:
            return

        # 获取最近的OHLC数据并确保是float64类型
        open_arr = np.array(self.dataopen.get(size=self.min_history), dtype=np.float64)
        high_arr = np.array(self.datahigh.get(size=self.min_history), dtype=np.float64)
        low_arr = np.array(self.datalow.get(size=self.min_history), dtype=np.float64)
        close_arr = np.array(self.dataclose.get(size=self.min_history), dtype=np.float64)

        # 计算K线形态信号
        try:
            # 存储形态及其信号值的字典
            pattern_results = {}
            
            # 使用标准形态检测
            pattern_results['吞没形态'] = talib.CDLENGULFING(open_arr, high_arr, low_arr, close_arr)[-1]
            
            # 对于复杂形态，使用自定义参数
            pattern_results['锤子线'] = talib.CDLHAMMER(open_arr, high_arr, low_arr, close_arr)[-1]
            pattern_results['启明星'] = talib.CDLMORNINGSTAR(
                open_arr, high_arr, low_arr, close_arr, penetration=self.p.penetration
            )[-1]
            pattern_results['三白兵'] = talib.CDL3WHITESOLDIERS(open_arr, high_arr, low_arr, close_arr)[-1]
            pattern_results['上吊线'] = talib.CDLHANGINGMAN(open_arr, high_arr, low_arr, close_arr)[-1]
            pattern_results['黄昏星'] = talib.CDLEVENINGSTAR(
                open_arr, high_arr, low_arr, close_arr, penetration=self.p.penetration
            )[-1]
            pattern_results['三黑鸦'] = talib.CDL3BLACKCROWS(open_arr, high_arr, low_arr, close_arr)[-1]
            
            # 如果需要，添加自定义形态检测
            if not pattern_results['三白兵'] and len(close_arr) >= 3:
                # 检查是否有连续三个阳线且收盘价逐日上涨
                bull1 = close_arr[-3] > open_arr[-3]
                bull2 = close_arr[-2] > open_arr[-2]
                bull3 = close_arr[-1] > open_arr[-1]
                rising = close_arr[-3] < close_arr[-2] < close_arr[-1]
                
                if bull1 and bull2 and bull3 and rising:
                    # 添加简单的条件：每个阳线的实体至少是前一天的50%
                    body1 = close_arr[-3] - open_arr[-3]
                    body2 = close_arr[-2] - open_arr[-2]
                    body3 = close_arr[-1] - open_arr[-1]
                    
                    if body1 > 0 and body2 > 0 and body3 > 0 and body2 >= body1 * 0.5 and body3 >= body2 * 0.5:
                        pattern_results['三白兵-自定义'] = 100
            
            if not pattern_results['三黑鸦'] and len(close_arr) >= 3:
                # 检查是否有连续三个阴线且收盘价逐日下跌
                bear1 = close_arr[-3] < open_arr[-3]
                bear2 = close_arr[-2] < open_arr[-2]
                bear3 = close_arr[-1] < open_arr[-1]
                falling = close_arr[-3] > close_arr[-2] > close_arr[-1]
                
                if bear1 and bear2 and bear3 and falling:
                    # 添加简单的条件：每个阴线的实体至少是前一天的50%
                    body1 = open_arr[-3] - close_arr[-3]
                    body2 = open_arr[-2] - close_arr[-2]
                    body3 = open_arr[-1] - close_arr[-1]
                    
                    if body1 > 0 and body2 > 0 and body3 > 0 and body2 >= body1 * 0.5 and body3 >= body2 * 0.5:
                        pattern_results['三黑鸦-自定义'] = -100
            
            # 提取看涨和看跌信号
            bullish_patterns = {k: v for k, v in pattern_results.items() if v > 0}
            bearish_patterns = {k: v for k, v in pattern_results.items() if v < 0}
            
            # 调试信息 - 输出检测到的形态
            if self.p.debug and (bullish_patterns or bearish_patterns):
                self.log(f'检测到的看涨形态: {bullish_patterns}')
                self.log(f'检测到的看跌形态: {bearish_patterns}')
            
            # 风险管理 - 止损
            if self.position and self.dataclose[0] < self.stop_loss:
                self.log(f'触发止损: 当前价格 {self.dataclose[0]:.2f}, 止损价 {self.stop_loss:.2f}')
                self.order = self.sell(size=self.position.size)
                return
            
            # 交易信号执行
            if bullish_patterns and not self.position:
                # 买入
                cash = self.broker.get_cash()
                size = int(cash * self.p.order_percentage / self.dataclose[0])
                if size > 0:
                    # 输出所有触发的看涨形态
                    signal_names = ', '.join(bullish_patterns.keys())
                    self.log(f'买入信号({signal_names}): 价格 {self.dataclose[0]:.2f}, 数量 {size}')
                    self.order = self.buy(size=size)
            
            elif bearish_patterns and self.position:
                # 卖出
                # 输出所有触发的看跌形态
                signal_names = ', '.join(bearish_patterns.keys())
                self.log(f'卖出信号({signal_names}): 价格 {self.dataclose[0]:.2f}')
                self.order = self.sell(size=self.position.size)
            
        except Exception as e:
            self.log(f'形态识别错误: {str(e)}')
            if self.p.debug:
                import traceback
                self.log(f'错误详情: {traceback.format_exc()}')

    def stop(self):
        """回测结束后输出最终结果"""
        self.log(f'回测结束: 最终账户价值 {self.broker.getvalue():.2f}') 