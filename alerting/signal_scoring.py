"""
信号评分系统

基于量价关系和技术指标的多维度信号强度评分系统。
可供各版本监控策略共用。

评分维度（总100分）：
1. 技术指标超买/超卖程度（20分）：RSI/MACD/KDJ等
2. 价格位置（30分）：相对近期高低点的位置
3. 趋势偏离程度（15分）：布林带/均线偏离
4. 量能形态+动量（35分）：量价关系+拉升/下跌期判断

评分阈值：
- ⭐⭐⭐强: 85+分
- ⭐⭐中:   65-84分
- ⭐弱:     <65分

作者：基于v3版本的评分逻辑抽取
日期：2025-10-24
"""

import pandas as pd
from enum import Enum


class SignalStrength(Enum):
    """信号强度分级"""
    STRONG = '⭐⭐⭐强'
    MEDIUM = '⭐⭐中'
    WEAK = '⭐弱'


class SignalScorer:
    """信号评分器（通用）"""
    
    # 评分阈值
    STRONG_THRESHOLD = 85
    MEDIUM_THRESHOLD = 65
    
    # 价格位置窗口
    POSITION_WINDOW = 60  # 使用60根K线判断价格位置
    
    # 动量判断阈值
    MOMENTUM_WINDOW = 10  # 观察近10根K线判断动量
    MOMENTUM_THRESHOLD = 0.02  # 2%涨跌幅算快速拉升/下跌
    
    # 拉升/下跌期修正参数
    MOMENTUM_PENALTY_MID = 0.45  # 中途降级45%
    MOMENTUM_PENALTY_EXTREME = 0.15  # 极端位置仅降级15%
    
    @staticmethod
    def calc_signal_strength(df, i, signal_type, 
                            indicator_score=None,
                            bb_upper=None, bb_lower=None,
                            vol_ma_period=20):
        """
        计算信号强度（通用评分）
        
        Args:
            df: DataFrame，必须包含 close, high, low, vol 列
            i: 当前K线索引
            signal_type: 'BUY' or 'SELL'
            indicator_score: 技术指标得分（0-20分），如果为None则不计入
            bb_upper: 布林带上轨列名或Series，用于计算偏离度
            bb_lower: 布林带下轨列名或Series，用于计算偏离度
            vol_ma_period: 成交量均线周期，默认20
            
        Returns:
            score: 0-100分数
            strength: SignalStrength枚举
        """
        if i < SignalScorer.MOMENTUM_WINDOW:
            return 50, SignalStrength.MEDIUM
        
        try:
            # 确保数据为数值类型
            df_work = df.iloc[max(0, i-SignalScorer.POSITION_WINDOW):i+1].copy()
            df_work['vol'] = pd.to_numeric(df_work['vol'], errors='coerce')
            
            close = df_work['close'].iloc[-1]
            
            # 计算量能均值
            df_vol_20 = df_work.iloc[-vol_ma_period:] if len(df_work) >= vol_ma_period else df_work
            current_vol = df_vol_20['vol'].iloc[-1]
            vol_ma = df_vol_20['vol'].mean()
            vol_ratio = current_vol / (vol_ma + 1e-6)
            
            # 计算价格位置（60根窗口）
            recent_high = df_work['high'].max()
            recent_low = df_work['low'].min()
            price_position = (close - recent_low) / (recent_high - recent_low + 1e-6)
            
            # 基础分
            score = 40
            
            if signal_type == 'BUY':
                score += SignalScorer._calc_buy_score(
                    df_work, price_position, vol_ratio, close,
                    indicator_score, bb_lower
                )
            else:  # SELL
                score += SignalScorer._calc_sell_score(
                    df_work, price_position, vol_ratio, close,
                    indicator_score, bb_upper
                )
            
            final_score = min(100, max(0, score))
            strength = SignalScorer._score_to_strength(final_score)
            
            return final_score, strength
            
        except Exception as e:
            return 50, SignalStrength.MEDIUM
    
    @staticmethod
    def _calc_buy_score(df, price_position, vol_ratio, close,
                       indicator_score, bb_lower):
        """计算买入信号评分"""
        score = 0
        
        # 1. 技术指标得分（20分）- 外部传入
        if indicator_score is not None:
            score += min(20, max(0, indicator_score))
        
        # 2. 价格位置（30分）
        if price_position < 0.08:
            score += 30
        elif price_position < 0.15:
            score += 20
        elif price_position < 0.25:
            score += 10
        elif price_position < 0.35:
            score += 3
        else:
            score -= 10  # 高位抄底扣分
        
        # 3. 布林带偏离（15分）
        if bb_lower is not None:
            try:
                bb_lower_val = bb_lower.iloc[-1] if hasattr(bb_lower, 'iloc') else bb_lower
                bb_dist = (close - bb_lower_val) / bb_lower_val
                if bb_dist < -0.015:
                    score += 15
                elif bb_dist < -0.008:
                    score += 10
                elif bb_dist < 0:
                    score += 5
            except:
                pass
        
        # 4. 量能形态+下跌期判断（35分）
        score += SignalScorer._calc_buy_volume_score(df, price_position, vol_ratio)
        
        return score
    
    @staticmethod
    def _calc_sell_score(df, price_position, vol_ratio, close,
                        indicator_score, bb_upper):
        """计算卖出信号评分"""
        score = 0
        
        # 1. 技术指标得分（20分）
        if indicator_score is not None:
            score += min(20, max(0, indicator_score))
        
        # 2. 价格位置（30分）
        if price_position > 0.96:  # 极度高位
            score += 30
        elif price_position > 0.92:  # 很高位
            score += 22
        elif price_position > 0.85:  # 高位
            score += 15
        elif price_position > 0.75:  # 中高位
            score += 8
        elif price_position > 0.65:  # 中位偏上
            score += 3
        else:
            score -= 10  # 半山腰扣分
        
        # 3. 布林带偏离（15分）
        if bb_upper is not None:
            try:
                bb_upper_val = bb_upper.iloc[-1] if hasattr(bb_upper, 'iloc') else bb_upper
                bb_dist = (close - bb_upper_val) / bb_upper_val
                if bb_dist > 0.015:
                    score += 15
                elif bb_dist > 0.008:
                    score += 10
                elif bb_dist > 0:
                    score += 5
            except:
                pass
        
        # 4. 量能形态+拉升期判断（35分）
        score += SignalScorer._calc_sell_volume_score(df, price_position, vol_ratio)
        
        return score
    
    @staticmethod
    def _calc_buy_volume_score(df, price_position, vol_ratio):
        """买入信号的量能评分（识别洗盘 vs 主跌浪）"""
        score = 0
        
        if len(df) < SignalScorer.MOMENTUM_WINDOW:
            # 数据不足时简化评分
            if vol_ratio > 2.5:
                score += 10
            elif 1.2 <= vol_ratio <= 2.0 and price_position < 0.15:
                score += 20
            elif vol_ratio > 1.2:
                score += 12
            else:
                score += 8
            return score
        
        # 检查下跌动量
        recent_closes = df['close'].iloc[-SignalScorer.MOMENTUM_WINDOW:].values
        price_change = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
        is_falling = price_change < -SignalScorer.MOMENTUM_THRESHOLD
        
        # 量能形态评分
        if vol_ratio > 2.5:
            # 巨量：极低位非下跌期才给高分
            if price_position < 0.04 and not is_falling:
                score += 35  # 恐慌盘出尽
            elif price_position < 0.10:
                score += 20
            elif price_position < 0.25:
                score += 12
            else:
                score += 5
        
        elif 1.2 <= vol_ratio <= 2.0:
            # 温和放量：企稳反弹信号
            if price_position < 0.15 and not is_falling:
                score += 30  # 低位放量企稳
            elif price_position < 0.15:
                score += 15
            else:
                score += 12
        
        elif vol_ratio < 1.2:
            # 缩量
            if price_position < 0.10 and vol_ratio < 0.5:
                score += 28  # 极低位缩量见底
            elif is_falling and vol_ratio < 0.8:
                score += 18  # 价跌量缩，洗盘特征
            else:
                score += 8
        
        else:
            score += 10
        
        # 下跌期修正
        if is_falling:
            if price_position < 0.05:
                # 极低位下跌：轻微降级
                penalty = int(score * SignalScorer.MOMENTUM_PENALTY_EXTREME)
                score -= penalty
            else:
                # 下跌中途：大幅降级
                penalty = int(score * SignalScorer.MOMENTUM_PENALTY_MID)
                score -= penalty
        
        return score
    
    @staticmethod
    def _calc_sell_volume_score(df, price_position, vol_ratio):
        """卖出信号的量能评分（识别有效大涨 vs 拉升中途）"""
        score = 0
        
        if len(df) < SignalScorer.MOMENTUM_WINDOW:
            # 数据不足时简化评分
            if vol_ratio > 3.0:
                score += 10
            elif vol_ratio > 1.5 and price_position > 0.85:
                score += 20
            elif vol_ratio > 1.3:
                score += 12
            else:
                score += 8
            return score
        
        # 检查拉升动量
        recent_closes = df['close'].iloc[-SignalScorer.MOMENTUM_WINDOW:].values
        price_change = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
        is_surging = price_change > SignalScorer.MOMENTUM_THRESHOLD
        
        # 量能形态评分（巨量需要特别处理）
        if vol_ratio > 3.0:
            # 巨量：需要配合位置+非拉升期
            if price_position > 0.96 and not is_surging:
                score += 35  # 极高位+巨量+非拉升期
            elif price_position > 0.92 and not is_surging:
                score += 25  # 极高位（92-96%）+巨量
            elif price_position > 0.90:
                score += 12  # 高位+巨量（保守）
            elif price_position > 0.75:
                score += 8   # 中高位+巨量
            else:
                score += 5   # 低位巨量
        
        elif 1.3 <= vol_ratio <= 2.5:
            # 温和放量
            if price_position > 0.85 and not is_surging:
                score += 30
            elif price_position > 0.85:
                score += 15
            else:
                score += 12
        
        elif vol_ratio < 1.3 and price_position > 0.85:
            # 缩量+高位：量价背离
            score += 28
        
        else:
            score += 10
        
        # 拉升期修正（统一处理，不分巨量）
        if is_surging:
            if price_position > 0.95:
                # 极高位拉升：轻微降级
                penalty = int(score * SignalScorer.MOMENTUM_PENALTY_EXTREME)
                score -= penalty
            else:
                # 拉升中途：大幅降级
                penalty = int(score * SignalScorer.MOMENTUM_PENALTY_MID)
                score -= penalty
        
        return score
    
    @staticmethod
    def _score_to_strength(score):
        """分数转换为强度等级"""
        if score >= SignalScorer.STRONG_THRESHOLD:
            return SignalStrength.STRONG
        elif score >= SignalScorer.MEDIUM_THRESHOLD:
            return SignalStrength.MEDIUM
        else:
            return SignalStrength.WEAK


# ============ 便捷函数 ============

def calc_rsi_indicator_score(rsi, signal_type):
    """
    基于RSI计算技术指标得分（0-20分）
    
    Args:
        rsi: RSI值
        signal_type: 'BUY' or 'SELL'
    
    Returns:
        score: 0-20分
    """
    if signal_type == 'BUY':
        if rsi < 15:
            return 20
        elif rsi < 20:
            return 14
        elif rsi < 25:
            return 8
        elif rsi < 30:
            return 3
    else:  # SELL
        if rsi > 85:
            return 20
        elif rsi > 80:
            return 14
        elif rsi > 75:
            return 8
        elif rsi > 70:
            return 3
    return 0


def calc_macd_indicator_score(macd, signal, signal_type):
    """
    基于MACD计算技术指标得分（0-20分）
    
    Args:
        macd: MACD DIF值
        signal: MACD DEA值
        signal_type: 'BUY' or 'SELL'
    
    Returns:
        score: 0-20分
    """
    diff = macd - signal
    
    if signal_type == 'BUY':
        # 金叉且在零轴下方
        if diff > 0 and macd < 0:
            if macd < -0.5:
                return 20  # 深度超卖
            elif macd < -0.2:
                return 14
            else:
                return 8
        elif macd < -0.5:
            return 10  # 即使未金叉，深度超卖也有分
    else:  # SELL
        # 死叉且在零轴上方
        if diff < 0 and macd > 0:
            if macd > 0.5:
                return 20  # 高位超买
            elif macd > 0.2:
                return 14
            else:
                return 8
        elif macd > 0.5:
            return 10
    return 0


def calc_kdj_indicator_score(k, d, signal_type):
    """
    基于KDJ计算技术指标得分（0-20分）
    
    Args:
        k: K值
        d: D值
        signal_type: 'BUY' or 'SELL'
    
    Returns:
        score: 0-20分
    """
    if signal_type == 'BUY':
        if k < 20 and d < 20:
            return 20  # 双低
        elif k < 30 and d < 30:
            return 14
        elif k < 40:
            return 8
    else:  # SELL
        if k > 80 and d > 80:
            return 20  # 双高
        elif k > 70 and d > 70:
            return 14
        elif k > 60:
            return 8
    return 0 