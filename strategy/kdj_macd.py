import backtrader as bt
import numpy as np


class KDJ_MACD_Strategy(bt.Strategy):
    params = (
        ('kdj_fast', 3),  # KDJ 快速周期
        ('kdj_slow', 3),  # KDJ 慢速周期
        ('kdj_signal', 9),  # KDJ 信号周期
        ('macd_short', 6),  # MACD 快速周期
        ('macd_long', 13),  # MACD 慢速周期
        ('macd_signal', 9),  # MACD 信号周期
        ('order_percentage', 0.25),  # 每次交易使用账户资金的x%
    )

    def __init__(self):
        # KDJ 指标
        # KDJ 指标: 使用 Stochastic 指标的 slowk 和 slowd
        self.kdj = bt.indicators.Stochastic(self.data,
                                            period_dfast=self.params.kdj_fast,
                                            period_dslow=self.params.kdj_slow,
                                            period=self.params.kdj_signal)
        # MACD 指标
        self.macd = bt.indicators.MACD(self.data.close,
                                       period_me1=self.params.macd_short,
                                       period_me2=self.params.macd_long,
                                       period_signal=self.params.macd_signal)
        # MACD 缩放
        self.macd.plotinfo.scale = 10  # 设置缩放比例

        self.order = None  # 当前订单
        self.buyprice = None  # 买入价格
        self.buycomm = None  # 买入手续费

    def log(self, txt, dt=None):
        """日志打印函数，默认打印当前时间和信息"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def notify_order(self, order):
        """处理订单状态变化"""
        if order.status in [order.Submitted, order.Accepted]:
            # 订单已提交或已接受，暂不处理
            return

        # 订单已完成
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f'BUY 买入: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            elif order.issell():
                self.log(
                    f'SELL 卖出: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')

        # 订单被取消、拒绝或出错
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单失败')

        # 清除订单
        self.order = None

    def notify_trade(self, trade):
        """处理交易状态变化"""
        if not trade.isclosed:
            return
        self.log(f'交易盈亏: 毛收益 {trade.pnl:.2f}, 净收益 {trade.pnlcomm:.2f}')

    def next(self):
        if self.order:
            return

        # 线性拟合
        x = [0, 1, 2]
        y = 3

        kdj_cross_down, kdj_cross_up = self.kdj_condition(x, y)
        macd_cross_down, macd_cross_up = self.macd_condition(x, y)

        cash = self.broker.get_cash()
        size = cash * self.params.order_percentage // self.data.close[0]

        # 如果 KDJ 和 MACD 即将金叉，执行买入
        if kdj_cross_up and macd_cross_up and not self.position:
            self.order = self.buy(size=size)
            # self.log(f'即将金叉买入信号: 当前收盘价 {self.data.close[0]:.2f}')

        # 如果 KDJ 和 MACD 即将死叉，执行卖出
        elif kdj_cross_down and macd_cross_down and self.position:
            self.order = self.sell(size=self.position.size)
            # self.log(f'即将死叉卖出信号: 当前收盘价 {self.data.close[0]:.2f}')

    def kdj_condition(self, x, y):
        # 获取当前和过去几天的 KDJ 和 MACD 的数据
        kdj_k = self.kdj.lines.percK.get(size=y)
        kdj_d = self.kdj.lines.percD.get(size=y)
        # 计算过去3天的 KDJ 斜率（通过线性回归）
        kdj_k_slope = np.polyfit(x, kdj_k, 1)[0]  # 计算 KDJ K 线的斜率
        kdj_d_slope = np.polyfit(x, kdj_d, 1)[0]  # 计算 KDJ D 线的斜率

        # 判断即将金叉的条件
        kdj_cross_up = kdj_k_slope > 0 and kdj_k_slope > kdj_d_slope and kdj_k[0] <= kdj_d[0]  # KDJ 斜率向上
        # 判断即将死叉的条件
        kdj_cross_down = kdj_k_slope < 0 and kdj_k_slope < kdj_d_slope and kdj_k[0] >= kdj_d[0]  # KDJ 斜率向下
        return kdj_cross_down, kdj_cross_up

    def macd_condition(self, x, y):
        # return True, True
        # 获取当前的 MACD 和 Signal 数据
        macd_val = self.macd.lines.macd.get(size=y)
        macd_signal = self.macd.lines.signal.get(size=y)
        # 计算 MACD 和 Signal 的斜率
        macd_slope = np.polyfit(x, macd_val, 1)[0]
        macd_signal_slope = \
            np.polyfit(x, macd_signal, 1)[0]
        macd_cross_up = macd_slope > 0 and macd_slope > macd_signal_slope  # MACD 斜率向上
        macd_cross_down = macd_slope < 0 and macd_slope < macd_signal_slope  # MACD 斜率向下
        return macd_cross_down, macd_cross_up

    def stop(self):
        """回测结束后输出最终账户价值"""
        self.log(f'回测结束: 最终账户价值 {self.broker.getvalue():.2f}')
