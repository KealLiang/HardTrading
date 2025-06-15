import backtrader as bt
import numpy as np


class PatternDetector:
    """K线形态检测器"""

    def __init__(self, pattern_types=None):
        """
        初始化K线形态检测器
        
        参数:
            pattern_types: 要检测的形态类型列表
        """
        self.pattern_types = pattern_types if pattern_types else [
            'hammer', 'engulfing', 'doji_star', 'three_soldiers', 'three_crows',
            'morning_star', 'evening_star'
        ]

    def detect(self, data, idx=0):
        """
        检测当前K线是否形成特定形态
        
        参数:
            data: 行情数据
            idx: 当前位置索引，默认为0（最新数据点）
        
        返回:
            dict: 包含各种形态的检测结果和买卖信号
        """
        patterns = {
            'buy_signal': False,
            'sell_signal': False,
            'patterns': [],
            'score': 0
        }
        
        bullish_patterns = 0
        bearish_patterns = 0
        
        # 检查所有启用的形态
        if 'hammer' in self.pattern_types:
            hammer = self._is_hammer(data, idx)
            if hammer['is_bullish']:
                patterns['patterns'].append({'name': 'hammer', 'type': 'bullish', 'score': hammer['score']})
                bullish_patterns += 1
            elif hammer['is_bearish']:  # 上吊线
                patterns['patterns'].append({'name': 'hanging_man', 'type': 'bearish', 'score': hammer['score']})
                bearish_patterns += 1
        
        if 'engulfing' in self.pattern_types:
            engulfing = self._is_engulfing(data, idx)
            if engulfing['is_bullish']:
                patterns['patterns'].append({'name': 'bullish_engulfing', 'type': 'bullish', 'score': engulfing['score']})
                bullish_patterns += 1
            elif engulfing['is_bearish']:
                patterns['patterns'].append({'name': 'bearish_engulfing', 'type': 'bearish', 'score': engulfing['score']})
                bearish_patterns += 1
        
        if 'doji_star' in self.pattern_types:
            doji = self._is_doji_star(data, idx)
            if doji['is_bullish']:
                patterns['patterns'].append({'name': 'bullish_doji', 'type': 'bullish', 'score': doji['score']})
                bullish_patterns += 1
            elif doji['is_bearish']:
                patterns['patterns'].append({'name': 'bearish_doji', 'type': 'bearish', 'score': doji['score']})
                bearish_patterns += 1
        
        if 'three_soldiers' in self.pattern_types and self._is_three_white_soldiers(data, idx):
            patterns['patterns'].append({'name': 'three_soldiers', 'type': 'bullish', 'score': 85})
            bullish_patterns += 1
        
        if 'three_crows' in self.pattern_types and self._is_three_black_crows(data, idx):
            patterns['patterns'].append({'name': 'three_crows', 'type': 'bearish', 'score': 85})
            bearish_patterns += 1
        
        if 'morning_star' in self.pattern_types:
            morning_star = self._is_morning_star(data, idx)
            if morning_star['is_pattern']:
                patterns['patterns'].append({'name': 'morning_star', 'type': 'bullish', 'score': morning_star['score']})
                bullish_patterns += 1
        
        if 'evening_star' in self.pattern_types:
            evening_star = self._is_evening_star(data, idx)
            if evening_star['is_pattern']:
                patterns['patterns'].append({'name': 'evening_star', 'type': 'bearish', 'score': evening_star['score']})
                bearish_patterns += 1
        
        # 计算总分数
        if patterns['patterns']:
            total_score = sum(p['score'] for p in patterns['patterns'])
            patterns['score'] = total_score / len(patterns['patterns'])
        
        # 确定买卖信号
        if bullish_patterns > 0 and bullish_patterns > bearish_patterns:
            patterns['buy_signal'] = True
        elif bearish_patterns > 0 and bearish_patterns > bullish_patterns:
            patterns['sell_signal'] = True
            
        return patterns
    
    def _is_hammer(self, data, idx=0):
        """检测锤子线或上吊线"""
        result = {'is_bullish': False, 'is_bearish': False, 'score': 0}
        
        # 获取当前K线数据
        open_price = data.open[idx]
        high = data.high[idx]
        low = data.low[idx]
        close = data.close[idx]
        
        body_size = abs(open_price - close)
        total_size = high - low
        
        if total_size == 0:
            return result
            
        body_ratio = body_size / total_size
        lower_shadow = min(open_price, close) - low
        lower_shadow_ratio = lower_shadow / total_size
        upper_shadow = high - max(open_price, close)
        upper_shadow_ratio = upper_shadow / total_size
        
        # 这是一个锤子线的基本定义
        if (body_ratio < 0.3 and lower_shadow_ratio > 0.6 and upper_shadow_ratio < 0.1):
            # 检查是否是看涨锤子线（在下跌趋势之后）
            if self._is_downtrend(data, idx, lookback=5):
                result['is_bullish'] = True
                result['score'] = 75
            # 检查是否是看跌上吊线（在上涨趋势之后）
            elif self._is_uptrend(data, idx, lookback=5):
                result['is_bearish'] = True
                result['score'] = 75
                
        return result
    
    def _is_engulfing(self, data, idx=0):
        """检测吞没形态"""
        result = {'is_bullish': False, 'is_bearish': False, 'score': 0}
        
        if idx + 1 >= len(data):
            return result
        
        # 当前K线
        curr_open = data.open[idx]
        curr_close = data.close[idx]
        curr_body_size = abs(curr_close - curr_open)
        
        # 前一根K线
        prev_open = data.open[idx-1]
        prev_close = data.close[idx-1]
        prev_body_size = abs(prev_close - prev_open)
        
        # 看涨吞没：当前阳线，前一天阴线，当前实体完全吞没前一天实体
        if (curr_close > curr_open and prev_close < prev_open and   # 当前阳线，前一天阴线
            curr_open <= prev_close and curr_close >= prev_open and # 完全吞没
            curr_body_size > prev_body_size):                       # 当前实体更大
            
            if self._is_downtrend(data, idx, lookback=5):
                result['is_bullish'] = True
                result['score'] = 80
        
        # 看跌吞没：当前阴线，前一天阳线，当前实体完全吞没前一天实体
        elif (curr_close < curr_open and prev_close > prev_open and  # 当前阴线，前一天阳线
              curr_open >= prev_close and curr_close <= prev_open and # 完全吞没
              curr_body_size > prev_body_size):                       # 当前实体更大
            
            if self._is_uptrend(data, idx, lookback=5):
                result['is_bearish'] = True
                result['score'] = 80
                
        return result
    
    def _is_doji_star(self, data, idx=0):
        """检测十字星形态"""
        result = {'is_bullish': False, 'is_bearish': False, 'score': 0}
        
        if idx + 1 >= len(data):
            return result
        
        # 当前K线
        open_price = data.open[idx]
        high = data.high[idx]
        low = data.low[idx]
        close = data.close[idx]
        
        body_size = abs(open_price - close)
        total_size = high - low
        
        # 十字星的主体很小
        is_doji = (total_size > 0 and body_size / total_size < 0.1)
        
        if is_doji:
            # 看涨十字星（下跌趋势后出现在低位）
            if self._is_downtrend(data, idx, lookback=5) and close < data.close[idx-1]:
                result['is_bullish'] = True
                result['score'] = 70
            
            # 看跌十字星（上涨趋势后出现在高位）
            elif self._is_uptrend(data, idx, lookback=5) and close > data.close[idx-1]:
                result['is_bearish'] = True
                result['score'] = 70
        
        return result
    
    def _is_three_white_soldiers(self, data, idx=0):
        """检测三白兵形态"""
        if idx + 2 >= len(data):
            return False
        
        # 确保三根K线都是阳线
        for i in range(3):
            if data.close[idx-i] <= data.open[idx-i]:
                return False
        
        # 确保每根K线的收盘价都高于前一根
        if not (data.close[idx] > data.close[idx-1] > data.close[idx-2]):
            return False
        
        # 确保每根K线的开盘价都在前一根实体的中部以上
        for i in range(2):
            prev_body_mid = (data.open[idx-i-1] + data.close[idx-i-1]) / 2
            if data.open[idx-i] < prev_body_mid:
                return False
                
        return True
    
    def _is_three_black_crows(self, data, idx=0):
        """检测三只乌鸦形态"""
        if idx + 2 >= len(data):
            return False
        
        # 确保三根K线都是阴线
        for i in range(3):
            if data.close[idx-i] >= data.open[idx-i]:
                return False
        
        # 确保每根K线的收盘价都低于前一根
        if not (data.close[idx] < data.close[idx-1] < data.close[idx-2]):
            return False
        
        # 确保每根K线的开盘价都在前一根实体的中部以下
        for i in range(2):
            prev_body_mid = (data.open[idx-i-1] + data.close[idx-i-1]) / 2
            if data.open[idx-i] > prev_body_mid:
                return False
                
        return True
    
    def _is_morning_star(self, data, idx=0):
        """检测启明星形态"""
        result = {'is_pattern': False, 'score': 0}
        
        if idx + 2 >= len(data):
            return result
        
        # 第一天：大阴线
        first_day_bearish = data.close[idx-2] < data.open[idx-2]
        first_day_body = abs(data.close[idx-2] - data.open[idx-2])
        
        # 第二天：小实体（可能是十字星）
        second_day_body = abs(data.close[idx-1] - data.open[idx-1])
        second_day_small = second_day_body < first_day_body * 0.3
        
        # 第三天：大阳线，收盘价至少超过第一天实体的中点
        third_day_bullish = data.close[idx] > data.open[idx]
        first_day_mid = (data.open[idx-2] + data.close[idx-2]) / 2
        third_day_closes_high = data.close[idx] > first_day_mid
        third_day_body = abs(data.close[idx] - data.open[idx])
        third_day_large = third_day_body > second_day_body * 2
        
        # 缺口检查
        gap_down = max(data.close[idx-2], data.open[idx-2]) > min(data.close[idx-1], data.open[idx-1])
        gap_up = min(data.close[idx], data.open[idx]) > max(data.close[idx-1], data.open[idx-1])
        
        if (first_day_bearish and second_day_small and third_day_bullish and 
            third_day_closes_high and third_day_large and
            (gap_down or gap_up) and
            self._is_downtrend(data, idx-2, lookback=5)):
            
            result['is_pattern'] = True
            result['score'] = 90 if (gap_down and gap_up) else 80
            
        return result
    
    def _is_evening_star(self, data, idx=0):
        """检测黄昏星形态"""
        result = {'is_pattern': False, 'score': 0}
        
        if idx + 2 >= len(data):
            return result
        
        # 第一天：大阳线
        first_day_bullish = data.close[idx-2] > data.open[idx-2]
        first_day_body = abs(data.close[idx-2] - data.open[idx-2])
        
        # 第二天：小实体（可能是十字星）
        second_day_body = abs(data.close[idx-1] - data.open[idx-1])
        second_day_small = second_day_body < first_day_body * 0.3
        
        # 第三天：大阴线，收盘价至少低于第一天实体的中点
        third_day_bearish = data.close[idx] < data.open[idx]
        first_day_mid = (data.open[idx-2] + data.close[idx-2]) / 2
        third_day_closes_low = data.close[idx] < first_day_mid
        third_day_body = abs(data.close[idx] - data.open[idx])
        third_day_large = third_day_body > second_day_body * 2
        
        # 缺口检查
        gap_up = min(data.close[idx-2], data.open[idx-2]) > max(data.close[idx-1], data.open[idx-1])
        gap_down = max(data.close[idx], data.open[idx]) < min(data.close[idx-1], data.open[idx-1])
        
        if (first_day_bullish and second_day_small and third_day_bearish and 
            third_day_closes_low and third_day_large and
            (gap_up or gap_down) and
            self._is_uptrend(data, idx-2, lookback=5)):
            
            result['is_pattern'] = True
            result['score'] = 90 if (gap_up and gap_down) else 80
            
        return result
    
    def _is_uptrend(self, data, idx=0, lookback=5):
        """检查是否处于上升趋势"""
        if idx + lookback >= len(data):
            lookback = len(data) - idx - 1
            
        if lookback < 3:
            return False
            
        prices = [data.close[idx-i] for i in range(lookback)]
        slope, _, _, _, _ = np.polyfit(range(len(prices)), prices, 1, full=True)
        
        return slope > 0
    
    def _is_downtrend(self, data, idx=0, lookback=5):
        """检查是否处于下降趋势"""
        if idx + lookback >= len(data):
            lookback = len(data) - idx - 1
            
        if lookback < 3:
            return False
            
        prices = [data.close[idx-i] for i in range(lookback)]
        slope, _, _, _, _ = np.polyfit(range(len(prices)), prices, 1, full=True)
        
        return slope < 0
    
    def _is_volume_confirmation(self, data, idx=0, threshold=1.5):
        """检查成交量确认信号"""
        if idx + 5 >= len(data):
            return False
            
        # 计算前5天的平均成交量
        avg_volume = sum(data.volume[idx-i] for i in range(1, 6)) / 5
        
        # 当前成交量是否显著高于平均值
        return data.volume[idx] > avg_volume * threshold


class CandlestickPatternStrategy(bt.Strategy):
    params = (
        ('pattern_types', ['hammer', 'engulfing', 'doji_star', 'three_soldiers', 'three_crows',
                          'morning_star', 'evening_star']),
        ('confirmation_days', 1),
        ('volume_threshold', 1.5),
        ('order_percentage', 0.2),
        ('min_pattern_score', 70),  # 最小形态可信度分数
        ('stop_loss_pct', 0.05),    # 止损百分比
        ('trailing_stop', 0.03),    # 追踪止损百分比
        ('max_drawdown_pct', 0.15), # 最大回撤限制
        ('profit_target_pct', 0.1), # 目标盈利百分比
    )

    def __init__(self):
        # 初始化形态检测器
        self.pattern_detector = PatternDetector(self.params.pattern_types)
        
        # 初始化止损/止盈跟踪器
        self.stop_loss = None
        self.trailing_stop = None
        self.profit_target = None
        
        # 跟踪交易状态
        self.order = None
        self.buyprice = None
        self.buycomm = None
        
        # 保存每日形态识别结果
        self.pattern_history = []
        
        # 添加成交量指标
        self.volume_ma5 = bt.indicators.SMA(self.data.volume, period=5)

    def log(self, txt, dt=None):
        """日志打印函数"""
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
                self.log(f'BUY 买入: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
                
                # 设置止损价和目标价
                self.stop_loss = self.buyprice * (1 - self.params.stop_loss_pct)
                self.trailing_stop = self.buyprice * (1 - self.params.trailing_stop)
                self.profit_target = self.buyprice * (1 + self.params.profit_target_pct)
                
            elif order.issell():
                self.log(f'SELL 卖出: 成交价 {order.executed.price:.2f}, 成交量 {order.executed.size}, 手续费 {order.executed.comm:.2f}')
                
                # 重置止损和目标价
                self.stop_loss = None
                self.trailing_stop = None
                self.profit_target = None

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
        # 如果有未完成的订单，等待
        if self.order:
            return
            
        # 检测当前K线形态
        patterns = self.pattern_detector.detect(self.data)
        
        # 保存形态识别结果以便后续分析
        self.pattern_history.append({
            'date': self.data.datetime.date(0),
            'patterns': patterns['patterns'],
            'buy_signal': patterns['buy_signal'],
            'sell_signal': patterns['sell_signal'],
            'score': patterns['score']
        })
        
        # 风险管理
        self._manage_risk()
        
        # 交易信号生成与执行
        if not self.position:  # 没有持仓时考虑买入信号
            if patterns['buy_signal'] and patterns['score'] >= self.params.min_pattern_score:
                # 检查成交量确认（当前成交量大于5日平均成交量的threshold倍）
                volume_confirmed = self.data.volume[0] > self.volume_ma5[0] * self.params.volume_threshold
                
                if volume_confirmed or not self.params.volume_threshold:
                    self._enter_long()
        
        elif self.position:  # 有持仓时考虑卖出信号
            if patterns['sell_signal'] and patterns['score'] >= self.params.min_pattern_score:
                # 检查成交量确认
                volume_confirmed = self.data.volume[0] > self.volume_ma5[0] * self.params.volume_threshold
                
                if volume_confirmed or not self.params.volume_threshold:
                    self._exit_position()
    
    def _enter_long(self):
        """执行买入操作"""
        cash = self.broker.get_cash()
        price = self.data.close[0]
        size = int(cash * self.params.order_percentage / price)
        
        if size > 0:
            self.log(f'BUY 买入信号: 价格 {price:.2f}, 数量 {size}')
            self.order = self.buy(size=size)
    
    def _exit_position(self):
        """执行卖出操作"""
        self.log(f'SELL 卖出信号: 价格 {self.data.close[0]:.2f}, 数量 {self.position.size}')
        self.order = self.sell(size=self.position.size)
    
    def _manage_risk(self):
        """风险管理"""
        if not self.position:
            return
            
        current_price = self.data.close[0]
        
        # 止损检查
        if self.stop_loss and current_price < self.stop_loss:
            self.log(f'触发止损: 当前价格 {current_price:.2f}, 止损价 {self.stop_loss:.2f}')
            self.order = self.sell(size=self.position.size)
            return
            
        # 追踪止损检查
        if self.trailing_stop:
            # 更新追踪止损价格（如果价格继续上涨）
            if current_price > self.buyprice:
                new_trailing_stop = current_price * (1 - self.params.trailing_stop)
                if new_trailing_stop > self.trailing_stop:
                    self.trailing_stop = new_trailing_stop
                    
            # 触发追踪止损
            if current_price < self.trailing_stop:
                self.log(f'触发追踪止损: 当前价格 {current_price:.2f}, 止损价 {self.trailing_stop:.2f}')
                self.order = self.sell(size=self.position.size)
                return
                
        # 盈利目标检查
        if self.profit_target and current_price > self.profit_target:
            self.log(f'达到盈利目标: 当前价格 {current_price:.2f}, 目标价 {self.profit_target:.2f}')
            self.order = self.sell(size=self.position.size)
            return
            
        # 计算当前回撤
        if self.buyprice:
            drawdown = (self.buyprice - current_price) / self.buyprice
            if drawdown > self.params.max_drawdown_pct:
                self.log(f'达到最大回撤限制: 当前回撤 {drawdown:.2%}, 限制 {self.params.max_drawdown_pct:.2%}')
                self.order = self.sell(size=self.position.size)
    
    def stop(self):
        """回测结束后输出统计信息"""
        self.log(f'回测结束: 最终账户价值 {self.broker.getvalue():.2f}')
        
        # 输出形态识别统计
        if self.pattern_history:
            total_days = len(self.pattern_history)
            buy_signals = sum(1 for day in self.pattern_history if day['buy_signal'])
            sell_signals = sum(1 for day in self.pattern_history if day['sell_signal'])
            
            self.log(f'形态识别统计: 总天数: {total_days}, 买入信号: {buy_signals}, 卖出信号: {sell_signals}')
            
            # 输出检测到的各种形态及其频率
            pattern_counts = {}
            for day in self.pattern_history:
                for pattern in day['patterns']:
                    name = pattern['name']
                    if name not in pattern_counts:
                        pattern_counts[name] = 0
                    pattern_counts[name] += 1
            
            if pattern_counts:
                self.log('形态检测频率:')
                for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
                    self.log(f'  {pattern}: {count} 次 ({count/total_days:.2%})')