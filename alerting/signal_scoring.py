"""
信号评分系统

基于量价关系和技术指标的多维度信号强度评分系统。
可供各版本监控策略共用。

评分维度（总100分 + 做T适用性调整）：
1. 技术指标超买/超卖程度（20分）：RSI/MACD/KDJ等
2. 价格位置（30分）：相对近期高低点的位置
3. 趋势偏离程度（15分）：布林带/均线偏离
4. 量能形态+动量（35分）：量价关系+拉升/下跌期判断
5. 🆕 做T适用性调整（-55到+10）：
   - 趋势惩罚（0-30扣分）：强趋势中逆向操作风险高
   - 波动率评估（-10到+10）：波动适中时做T机会好
   - 横盘惩罚（0-15扣分）：价格变动小时的密集信号
6. 🔧 放量拉升总分降级（保留25-40%）：拉升中途放量=主力推升，不应卖

评分阈值：
- ⭐⭐⭐强: 85+分
- ⭐⭐中:   65-84分
- ⭐弱:     <65分

作者：基于v3版本的评分逻辑抽取
版本历史：
- v1.0: 基础评分系统
- v1.1: 新增做T适用性评估（趋势+波动率）
- v1.2: 新增横盘密集信号惩罚
- v1.3: 修正放量拉升评分BUG（2025-10-25）
  * 问题：放量拉升时卖出信号得分过高（如301137急涨期）
  * 修复：量能分修正 + 总分降级（拉升中途保留25%，极高位保留40%）
  * 效果：卖出信号减少58%，买卖比从21:43优化到21:18
- v1.4: 平衡极端拉升和反弹卖点（2025-10-25）
  * 问题：v1.3过度降级，误伤反弹逃命点（如600078 10:37）
  * 修复：提高降级阈值（涨幅>3%，量比>3x，位置>95%），统一降级30%
  * 效果：只对极端强势拉升降级，保留温和拉升/反弹卖点
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
    
    # 🆕 做T适用性评估参数
    TREND_WINDOW_SHORT = 30  # 短期趋势窗口（30分钟）
    TREND_WINDOW_MID = 60    # 中期趋势窗口（60分钟）
    TREND_STRONG_THRESHOLD = 0.06  # 强趋势阈值（6%）
    TREND_MODERATE_THRESHOLD = 0.03  # 温和趋势阈值（3%）
    
    # 横盘密集信号惩罚参数
    CONSOLIDATION_WINDOW = 10  # 横盘检测窗口（10根K线）
    CONSOLIDATION_RANGE_EXTREME = 0.01  # 极窄幅横盘（1%）
    CONSOLIDATION_RANGE_NARROW = 0.015  # 窄幅横盘（1.5%）
    CONSOLIDATION_RANGE_MILD = 0.025    # 轻微横盘（2.5%）
    CONSOLIDATION_DIRECTION_THRESHOLD = 0.3  # 方向一致性阈值（30%）
    CONSOLIDATION_PENALTY_EXTREME = 15  # 极窄幅横盘扣分
    CONSOLIDATION_PENALTY_NARROW = 10   # 窄幅横盘扣分
    CONSOLIDATION_PENALTY_MILD = 5      # 轻微横盘扣分
    
    @staticmethod
    def _calc_trend_penalty(df, signal_type):
        """
        计算趋势惩罚（做T风险评估）
        
        原理：做T适合震荡行情，在强趋势中逆向操作风险高
        - 下跌趋势抄底：可能继续下跌
        - 上涨趋势卖出：可能错过后续涨幅
        
        返回: 0-30的扣分
        """
        if len(df) < SignalScorer.TREND_WINDOW_MID:
            return 0
        
        try:
            # 计算30根和60根K线的趋势
            close_series = df['close'].values
            recent_30 = close_series[-SignalScorer.TREND_WINDOW_SHORT:]
            recent_60 = close_series[-SignalScorer.TREND_WINDOW_MID:]
            
            trend_30 = (recent_30[-1] - recent_30[0]) / recent_30[0]
            trend_60 = (recent_60[-1] - recent_60[0]) / recent_60[0]
            
            # 计算趋势一致性（单向运动的K线占比）
            price_changes = pd.Series(recent_30).diff().dropna()
            
            if signal_type == 'BUY':
                # 评估下跌趋势风险
                if trend_30 < -SignalScorer.TREND_STRONG_THRESHOLD and trend_60 < -SignalScorer.TREND_STRONG_THRESHOLD:
                    # 短中期都在强势下跌（30根-6%，60根-6%）
                    falling_ratio = (price_changes < 0).sum() / len(price_changes)
                    if falling_ratio > 0.65:  # 65%以上K线下跌
                        return 25  # 强下跌趋势，抄底风险很高
                    else:
                        return 15  # 虽在下跌但有反弹
                
                elif trend_30 < -SignalScorer.TREND_MODERATE_THRESHOLD or trend_60 < -SignalScorer.TREND_MODERATE_THRESHOLD:
                    # 温和下跌（3%-6%）
                    falling_ratio = (price_changes < 0).sum() / len(price_changes)
                    if falling_ratio > 0.60:
                        return 12
                    else:
                        return 6
            
            else:  # SELL
                # 评估上涨趋势风险
                if trend_30 > SignalScorer.TREND_STRONG_THRESHOLD and trend_60 > SignalScorer.TREND_STRONG_THRESHOLD:
                    # 短中期都在强势上涨
                    rising_ratio = (price_changes > 0).sum() / len(price_changes)
                    if rising_ratio > 0.65:  # 65%以上K线上涨
                        return 20  # 强上涨趋势，过早卖出风险高
                    else:
                        return 12  # 虽在上涨但有回调
                
                elif trend_30 > SignalScorer.TREND_MODERATE_THRESHOLD or trend_60 > SignalScorer.TREND_MODERATE_THRESHOLD:
                    # 温和上涨
                    rising_ratio = (price_changes > 0).sum() / len(price_changes)
                    if rising_ratio > 0.60:
                        return 10
                    else:
                        return 5
            
            return 0  # 震荡行情，做T友好
            
        except Exception:
            return 0
    
    @staticmethod
    def _calc_volatility_bonus(df, signal_type):
        """
        计算波动率加分（做T机会评估）
        
        原理：做T需要足够的短期波动才能获利
        - 波动过小：无利可图
        - 波动适中：做T机会好
        - 波动过大：风险高
        
        返回: -10到+10的调整分
        """
        if len(df) < 20:
            return 0
        
        try:
            recent_20 = df['close'].iloc[-20:].values
            
            # 计算20根K线的波动率（标准差/均值）
            volatility = pd.Series(recent_20).std() / pd.Series(recent_20).mean()
            
            # 计算当前价格相对MA20的偏离度
            ma_20 = recent_20.mean()
            current = recent_20[-1]
            deviation = abs(current - ma_20) / ma_20
            
            if signal_type == 'BUY':
                # 买入信号：希望价格已偏离均线（有回归空间），且波动适中
                if deviation > 0.03 and 0.01 < volatility < 0.04:
                    # 偏离3%以上 + 适中波动
                    return 8
                elif deviation > 0.02 and 0.01 < volatility < 0.05:
                    return 5
                elif volatility < 0.008:
                    # 波动太小，做T无意义
                    return -8
                elif volatility > 0.06:
                    # 波动太大，风险过高
                    return -5
                else:
                    return 0
            
            else:  # SELL
                # 卖出信号：希望价格已偏离均线（有回调压力），且波动适中
                if deviation > 0.03 and 0.01 < volatility < 0.04:
                    return 8
                elif deviation > 0.02 and 0.01 < volatility < 0.05:
                    return 5
                elif volatility < 0.008:
                    return -8
                elif volatility > 0.06:
                    return -5
                else:
                    return 0
        
        except Exception:
            return 0
    
    @staticmethod
    def _calc_consolidation_penalty(df, signal_type):
        """
        计算横盘密集信号惩罚（价格变动小时的重复信号）
        
        原理：价格在小范围内横盘时，频繁触发的信号做T价值很低
        - 检查最近N根K线的价格波动幅度
        - 如果波动很小（横盘），则扣分
        
        返回: 0-15的扣分
        """
        if len(df) < SignalScorer.CONSOLIDATION_WINDOW:
            return 0
        
        try:
            recent_n = df['close'].iloc[-SignalScorer.CONSOLIDATION_WINDOW:].values
            
            # 计算N根K线的价格波动幅度（极差/均值）
            price_range = (recent_n.max() - recent_n.min()) / recent_n.mean()
            
            # 计算价格变动趋势（是否单边移动）
            price_changes = pd.Series(recent_n).diff().dropna()
            direction_consistency = abs(price_changes.sum()) / (abs(price_changes).sum() + 1e-6)
            
            # 横盘判断：波动小 + 无明显方向
            is_consolidating = (price_range < SignalScorer.CONSOLIDATION_RANGE_NARROW and 
                              direction_consistency < SignalScorer.CONSOLIDATION_DIRECTION_THRESHOLD)
            
            if is_consolidating:
                # 极窄幅横盘
                if price_range < SignalScorer.CONSOLIDATION_RANGE_EXTREME:
                    return SignalScorer.CONSOLIDATION_PENALTY_EXTREME
                # 窄幅横盘
                elif price_range < SignalScorer.CONSOLIDATION_RANGE_NARROW:
                    return SignalScorer.CONSOLIDATION_PENALTY_NARROW
                else:
                    return SignalScorer.CONSOLIDATION_PENALTY_MILD
            
            # 轻微横盘（波动范围稍大但无明显方向）
            elif (price_range < SignalScorer.CONSOLIDATION_RANGE_MILD and 
                  direction_consistency < 0.4):
                return SignalScorer.CONSOLIDATION_PENALTY_MILD
            
            return 0
        
        except Exception:
            return 0
    
    @staticmethod
    def calc_signal_strength(df, i, signal_type, 
                            indicator_score=None,
                            bb_upper=None, bb_lower=None,
                            vol_ma_period=20,
                            enable_trend_filter=True):
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
            enable_trend_filter: 是否启用做T适用性评估（趋势+波动率），默认True
            
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
            
            # 🆕 做T适用性调整
            if enable_trend_filter:
                # 趋势惩罚（0-30扣分）- 强趋势中逆向操作风险高
                trend_penalty = SignalScorer._calc_trend_penalty(df_work, signal_type)
                score -= trend_penalty
                
                # 波动率评估（-10到+10）- 波动适中时做T机会好
                volatility_bonus = SignalScorer._calc_volatility_bonus(df_work, signal_type)
                score += volatility_bonus
                
                # 🆕 横盘密集信号惩罚（0-15扣分）- 价格变动小时的重复信号
                consolidation_penalty = SignalScorer._calc_consolidation_penalty(df_work, signal_type)
                score -= consolidation_penalty
            
            # 🔧 强势拉升期总分降级（只对极端强势拉升降级，避免误伤）
            if signal_type == 'SELL' and len(df_work) >= SignalScorer.MOMENTUM_WINDOW:
                recent_closes = df_work['close'].iloc[-SignalScorer.MOMENTUM_WINDOW:].values
                price_change_10 = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
                
                # 只对"极端强势拉升"降级（涨幅大+巨量+创新高）
                # 温和拉升、拉升失败等场景保持原样，由其他评分维度处理
                is_extreme_surge = (
                    price_change_10 > 0.03 and      # 10根涨幅>3%（而非2%）
                    vol_ratio > 3.0 and              # 巨量>3倍（而非1.5倍）
                    price_position > 0.95            # 创新高>95%
                )
                
                if is_extreme_surge:
                    # 极端强势拉升：主力大举推升，明确不应该卖
                    score = int(score * 0.30)  # 保留30%
            
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
        """
        卖出信号的量能评分（修正版：放量拉升=主力推升，不应加分）
        
        核心原则：
        1. 只有"非拉升期 + 高位 + 放量"才是出货信号（高分）
        2. "拉升期 + 放量"是主力推升，不应卖（低分）
        3. "缩量 + 高位"是量价背离，见顶信号（高分）
        """
        score = 0
        
        if len(df) < SignalScorer.MOMENTUM_WINDOW:
            # 数据不足时保守评分
            if vol_ratio < 1.3 and price_position > 0.85:
                score += 28  # 缩量+高位：量价背离
            elif vol_ratio > 1.5 and price_position > 0.85:
                score += 15  # 高位放量（保守给分）
            else:
                score += 8
            return score
        
        # 检查拉升动量
        recent_closes = df['close'].iloc[-SignalScorer.MOMENTUM_WINDOW:].values
        price_change = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
        is_surging = price_change > SignalScorer.MOMENTUM_THRESHOLD
        
        # === 核心逻辑：根据"价格动作+量能+位置"综合评分 ===
        
        # 情况1：缩量 + 高位 = 量价背离（无论是否拉升期都是见顶信号）
        if vol_ratio < 1.3 and price_position > 0.85:
            score += 30  # 涨不放量，典型见顶
        
        # 情况2：非拉升期 + 高位 + 放量 = 放量滞涨/出货
        elif not is_surging and price_position > 0.85:
            if vol_ratio > 3.0:
                # 巨量滞涨（不涨反而放巨量）
                if price_position > 0.96:
                    score += 35  # 极高位+巨量滞涨
                elif price_position > 0.92:
                    score += 30  # 很高位+巨量滞涨
                else:
                    score += 25  # 高位+巨量滞涨
            elif vol_ratio >= 1.3:
                # 温和放量滞涨
                score += 30
            else:
                score += 10  # 量能中性
        
        # 情况3：拉升期（无论放量还是缩量都不是好卖点）
        elif is_surging:
            if vol_ratio > 2.0:
                # 放量拉升 = 主力推升，不应该卖
                score += 5  # 极低分
            elif vol_ratio < 1.0:
                # 缩量拉升 = 可能拉升末期，稍微加分
                if price_position > 0.90:
                    score += 15  # 高位缩量拉升
                else:
                    score += 8
            else:
                # 正常量能拉升
                score += 10
        
        # 情况4：非高位（无论什么量能都不是卖点）
        else:
            score += 8  # 低基础分
        
        # === 拉升期额外惩罚（针对残留的基础分）===
        if is_surging:
            if price_position > 0.95:
                # 极高位拉升：轻微降级（可能是最后冲顶）
                penalty = int(score * 0.30)
            else:
                # 拉升中途：大幅降级（明确不应该卖）
                penalty = int(score * 0.70)
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