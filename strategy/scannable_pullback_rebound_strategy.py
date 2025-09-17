import logging
from .pullback_rebound_strategy import PullbackReboundStrategy


class ScannablePullbackReboundStrategy(PullbackReboundStrategy):
    """
    可供扫描器使用的止跌反弹策略版本。
    通过继承扩展了原始策略，增加了信号发射和静默日志功能，
    而无需修改原始策略代码。
    """
    params = (
        # 继承并新增参数
        ('signal_callback', None),  # 用于发射信号的回调函数
        ('silent', False),          # 是否在扫描模式下关闭日志
    )

    def __init__(self):
        # 首先调用父类的__init__来构建所有基础指标
        super().__init__()
        # 从新的params中获取我们添加的参数
        self.signal_callback = self.p.signal_callback
        self.silent = self.p.silent

    def log(self, txt, dt=None):
        """重写log方法以支持静默模式"""
        if self.silent:
            return  # 在静默模式下，不记录日志
        # 调用父类的log方法，保持原有打印行为
        super().log(txt, dt=dt)

    def _execute_buy_signal(self):
        """重写买入信号执行，增加信号发射功能"""
        # 发射信号给扫描器
        if self.signal_callback:
            signal_info = {
                'date': self.datas[0].datetime.date(0),
                'type': '止跌反弹信号',
                'details': f'价格: {self.data.close[0]:.2f}, 主升浪高点: {self.uptrend_high_price:.2f}',
                'score': self._calculate_signal_score()
            }
            self.signal_callback(signal_info)
        
        # 调用父类的买入逻辑
        super()._execute_buy_signal()

    def _calculate_signal_score(self):
        """计算信号评分"""
        score = 0
        
        # 基础分：满足企稳信号
        score += 3
        
        # 回调幅度评分：回调越深，反弹潜力越大
        pullback_ratio = (self.uptrend_high_price - self.data.close[0]) / self.uptrend_high_price
        if pullback_ratio >= 0.10:
            score += 2
        elif pullback_ratio >= 0.05:
            score += 1
        
        # 成交量评分：量能萎缩越明显，企稳信号越强
        volume_ratio = self.data.volume[0] / self.volume_ma[0]
        if volume_ratio <= 0.4:
            score += 2
        elif volume_ratio <= 0.6:
            score += 1
        
        # 红K线强度评分
        candle_strength = (self.data.close[0] - self.data.open[0]) / self.data.open[0]
        if candle_strength >= 0.03:  # 涨幅超过3%
            score += 2
        elif candle_strength >= 0.01:  # 涨幅超过1%
            score += 1
        
        return min(score, 10)  # 最高10分
