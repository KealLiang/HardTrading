"""
盘中情绪分析器

专门用于分析盘中市场情绪强度，通过"六联动"信号快速感知市场状态：
1. 涨停数量 - 做多情绪强度
2. 跌停数量 - 恐慌情绪程度  
3. 连板高度 - 持续性和强度
4. 炸板率 - 资金分歧程度
5. 成交量 - 参与度和活跃度
6. 换手率 - 资金流动性

输出简洁的情绪报告和直观的图表，便于盘中快速决策。

作者：Trading System
创建时间：2025-01-14
"""

import os
import sys

sys.path.append('.')

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import logging
from typing import Dict, Tuple
import argparse

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

from fetch.auction_fengdan_data import AuctionFengdanCollector
from utils.date_util import get_current_or_prev_trading_day


class MoodAnalyzer:
    """盘中情绪分析器"""

    def __init__(self):
        """初始化分析器"""
        self.collector = AuctionFengdanCollector()
        self.logger = logging.getLogger(__name__)

        # 注意：AUCTION_TIMES和INTRADAY_TIMES已移至auction_scheduler中管理

        # akshare字段映射（解决字段名不匹配问题）
        self.FIELD_MAPPING = {
            # akshare字段名 -> 标准字段名
            '代码': '股票代码',
            '名称': '股票名称',
            '涨跌幅': '涨幅',
            '现价': '现价',
            '成交额': '成交额',
            '流通市值': '流通市值',
            '总市值': '总市值',
            '换手率': '换手率',
            '连板数': '连板数',
            '首次封板时间': '首次封板时间',
            '最后封板时间': '最后封板时间',
            '封板资金': '封板资金',
            '炸板次数': '炸板次数',
            '炸板时间': '炸板时间',
            '封单资金': '封单资金'  # 跌停和部分炸板数据使用
        }

        # 情绪阈值
        self.MOOD_THRESHOLDS = {
            90: ("极度狂热", "🔥🔥🔥🔥🔥"),
            70: ("高度活跃", "🔥🔥🔥🔥"),
            50: ("温和乐观", "🔥🔥🔥"),
            30: ("谨慎观望", "🔥🔥"),
            0: ("恐慌情绪", "🔥")
        }

        # 确保输出目录存在
        self.base_dir = "reports/mood"
        os.makedirs(self.base_dir, exist_ok=True)

    def _map_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        映射akshare字段名到标准字段名

        Args:
            df: 原始DataFrame

        Returns:
            映射后的DataFrame
        """
        if df.empty:
            return df

        # 创建副本避免修改原数据
        df_mapped = df.copy()

        # 应用字段映射
        for akshare_field, standard_field in self.FIELD_MAPPING.items():
            if akshare_field in df_mapped.columns:
                df_mapped = df_mapped.rename(columns={akshare_field: standard_field})

        # 记录映射信息
        mapped_fields = []
        for akshare_field, standard_field in self.FIELD_MAPPING.items():
            if akshare_field in df.columns:
                mapped_fields.append(f"{akshare_field}->{standard_field}")

        if mapped_fields:
            self.logger.debug(f"字段映射: {', '.join(mapped_fields)}")

        return df_mapped

    def get_mood_level(self, score: int) -> Tuple[str, str]:
        """根据评分获取情绪等级"""
        for threshold, (level, emoji) in sorted(self.MOOD_THRESHOLDS.items(), reverse=True):
            if score >= threshold:
                return level, emoji
        return "恐慌情绪", "🔥"

    def calculate_mood_score(self, data: Dict) -> int:
        """
        计算情绪强度评分 (0-100分)

        Args:
            data: 分析数据字典

        Returns:
            情绪评分
        """
        score = 40  # 基础分数

        # 1. 涨停贡献 (最高25分)
        zt_count = data.get('涨停数量', 0)
        score += min(25, zt_count * 1.2)

        # 2. 跌停影响 (最多-15分)
        dt_count = data.get('跌停数量', 0)
        score -= min(15, dt_count * 6)

        # 3. 炸板影响 (最多-15分) - 新增
        zhaban_count = data.get('炸板数量', 0)
        score -= min(15, zhaban_count * 3)

        # 4. 连板高度 (最高15分)
        max_lianban = data.get('最高连板', 0)
        lianban_3_plus = data.get('三板以上', 0)
        score += min(15, max_lianban * 2.5 + lianban_3_plus * 1.5)

        # 5. 炸板率影响 (最多-12分) - 基于涨停中的炸板比例
        zhaban_rate = data.get('炸板率', 0)
        score -= zhaban_rate * 12

        # 6. 成交量 (最高8分)
        volume_ratio = data.get('成交量比', 1.0)
        if volume_ratio > 1:
            score += min(8, (volume_ratio - 1) * 16)
        else:
            score -= (1 - volume_ratio) * 8

        # 7. 换手率 (最高4分)
        avg_turnover = data.get('平均换手率', 0)
        score += min(4, avg_turnover * 0.25)

        # 8. 封板金额强度 (最高8分)
        avg_fengdan = data.get('平均封板金额', 0)  # 亿元
        if avg_fengdan > 0:
            score += min(8, avg_fengdan * 1.6)  # 每亿元加1.6分

        return max(0, min(100, int(score)))

    def analyze_auction_mood(self, date_str: str = None, time_point: str = "0925") -> Dict:
        """
        分析竞价阶段情绪
        
        Args:
            date_str: 日期字符串
            time_point: 时间点
            
        Returns:
            情绪分析结果
        """
        if not date_str:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            date_str = get_current_or_prev_trading_day(today)

        try:
            # 获取竞价阶段数据（这才是竞价分析应该用的数据）
            auction_data = self.collector.get_auction_period_stocks(date_str)

            # 应用字段映射
            auction_data = self._map_fields(auction_data)

            # 从竞价数据中分离涨停和跌停
            if not auction_data.empty and '涨跌类型' in auction_data.columns:
                zt_data = auction_data[auction_data['涨跌类型'] == '涨停']
                dt_data = auction_data[auction_data['涨跌类型'] == '跌停']
            else:
                # 如果没有涨跌类型字段，按涨幅判断
                zt_data = auction_data[auction_data[
                                           '涨幅'] > 9.5] if not auction_data.empty and '涨幅' in auction_data.columns else pd.DataFrame()
                dt_data = auction_data[auction_data[
                                           '涨幅'] < -9.5] if not auction_data.empty and '涨幅' in auction_data.columns else pd.DataFrame()

            # 基础指标
            zt_count = len(zt_data)
            dt_count = len(dt_data)
            auction_count = len(auction_data)

            # 连板分析
            max_lianban = 0
            lianban_3_plus = 0
            if not zt_data.empty and '连板数' in zt_data.columns:
                max_lianban = zt_data['连板数'].max()
                lianban_3_plus = len(zt_data[zt_data['连板数'] >= 3])

            # 换手率分析
            avg_turnover = 0
            if not zt_data.empty and '换手率' in zt_data.columns:
                avg_turnover = zt_data['换手率'].mean()

            # 封板金额分析
            avg_fengban = 0
            if not zt_data.empty and '封板资金' in zt_data.columns:
                avg_fengban = zt_data['封板资金'].mean() / 1e8  # 转换为亿元
            elif not dt_data.empty and '封板资金' in dt_data.columns:
                avg_fengban = dt_data['封板资金'].mean() / 1e8

            # 构建分析数据
            analysis_data = {
                '涨停数量': zt_count,
                '跌停数量': dt_count,
                '竞价封板': auction_count,
                '最高连板': max_lianban,
                '三板以上': lianban_3_plus,
                '炸板率': 0,  # 竞价阶段无炸板
                '成交量比': 1.0,  # 竞价阶段无成交量
                '平均换手率': avg_turnover,
                '平均封板金额': avg_fengban,
                '净涨停': zt_count - dt_count
            }

            # 计算情绪评分
            mood_score = self.calculate_mood_score(analysis_data)
            mood_level, mood_emoji = self.get_mood_level(mood_score)

            return {
                'date': date_str,
                'time': time_point,
                'type': 'auction',
                'score': mood_score,
                'level': mood_level,
                'emoji': mood_emoji,
                'data': analysis_data,
                'raw_data': {
                    'zt_data': zt_data,
                    'dt_data': dt_data,
                    'auction_data': auction_data
                }
            }

        except Exception as e:
            self.logger.error(f"竞价情绪分析失败: {e}")
            return {}

    def analyze_intraday_mood(self, date_str: str = None, time_point: str = "1000") -> Dict:
        """
        分析盘中情绪
        
        Args:
            date_str: 日期字符串
            time_point: 时间点
            
        Returns:
            情绪分析结果
        """
        if not date_str:
            from datetime import datetime
            today = datetime.now().strftime('%Y%m%d')
            date_str = get_current_or_prev_trading_day(today)

        try:
            # 获取当前数据（包含炸板数据）
            zt_data = self.collector.get_zt_fengdan_data(date_str)
            dt_data = self.collector.get_dt_fengdan_data(date_str)
            zhaban_data = self.collector.get_zhaban_fengdan_data(date_str)

            # 应用字段映射
            zt_data = self._map_fields(zt_data)
            dt_data = self._map_fields(dt_data)
            zhaban_data = self._map_fields(zhaban_data)

            # 基础指标
            zt_count = len(zt_data)
            dt_count = len(dt_data)
            zhaban_count_total = len(zhaban_data)  # 独立炸板数据

            # 连板和炸板分析
            max_lianban = 0
            lianban_3_plus = 0
            zhaban_count_in_zt = 0  # 涨停中的炸板数量
            zhaban_rate = 0

            if not zt_data.empty:
                if '连板数' in zt_data.columns:
                    max_lianban = zt_data['连板数'].max()
                    lianban_3_plus = len(zt_data[zt_data['连板数'] >= 3])

                if '炸板次数' in zt_data.columns:
                    # 炸板次数是每只股票的炸板次数，需要统计有炸板的股票数量
                    zhaban_stocks = zt_data[zt_data['炸板次数'] > 0]
                    zhaban_count_in_zt = len(zhaban_stocks)
                    zhaban_rate = zhaban_count_in_zt / zt_count if zt_count > 0 else 0

            # 换手率分析
            avg_turnover = 0
            if not zt_data.empty and '换手率' in zt_data.columns:
                avg_turnover = zt_data['换手率'].mean()

            # 封板金额分析
            avg_fengban = 0
            if not zt_data.empty and '封板资金' in zt_data.columns:
                avg_fengban = zt_data['封板资金'].mean() / 1e8  # 转换为亿元
            elif not dt_data.empty and '封板资金' in dt_data.columns:
                avg_fengban = dt_data['封板资金'].mean() / 1e8

            # 成交量分析 (简化处理，实际应该获取实时成交量数据)
            volume_ratio = 1.2  # 模拟值，实际应该从行情数据获取

            # 构建分析数据
            analysis_data = {
                '涨停数量': zt_count,
                '跌停数量': dt_count,
                '炸板数量': zhaban_count_total,  # 使用独立炸板数据总数
                '最高连板': max_lianban,
                '三板以上': lianban_3_plus,
                '炸板率': zhaban_rate,  # 基于涨停中的炸板比例
                '成交量比': volume_ratio,
                '平均换手率': avg_turnover,
                '平均封板金额': avg_fengban,
                '净涨停': zt_count - dt_count
            }

            # 计算情绪评分
            mood_score = self.calculate_mood_score(analysis_data)
            mood_level, mood_emoji = self.get_mood_level(mood_score)

            return {
                'date': date_str,
                'time': time_point,
                'type': 'intraday',
                'score': mood_score,
                'level': mood_level,
                'emoji': mood_emoji,
                'data': analysis_data,
                'raw_data': {
                    'zt_data': zt_data,
                    'dt_data': dt_data,
                    'zhaban_data': zhaban_data
                }
            }

        except Exception as e:
            self.logger.error(f"盘中情绪分析失败: {e}")
            return {}

    def generate_mood_report(self, analysis: Dict) -> str:
        """
        生成情绪分析报告

        Args:
            analysis: 分析结果

        Returns:
            报告文件路径
        """
        if not analysis:
            return ""

        date_str = analysis['date']
        time_point = analysis['time']
        report_type = analysis['type']

        # 创建日期目录
        date_dir = os.path.join(self.base_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)

        # 生成报告内容
        if report_type == 'auction':
            content = self._generate_auction_report(analysis)
            filename = f"{time_point}_auction_mood.md"
        else:
            content = self._generate_intraday_report(analysis)
            filename = f"{time_point}_intraday_mood.md"

        # 保存报告
        report_path = os.path.join(date_dir, filename)
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return report_path

    def _generate_auction_report(self, analysis: Dict) -> str:
        """生成竞价阶段报告"""
        data = analysis['data']

        # 操作建议
        score = analysis['score']
        if score >= 70:
            suggestion = "**积极参与**：情绪高涨，适合追涨强势股"
        elif score >= 50:
            suggestion = "**谨慎乐观**：情绪良好，可关注优质标的"
        elif score >= 30:
            suggestion = "**观望为主**：情绪一般，等待更好机会"
        else:
            suggestion = "**规避风险**：情绪低迷，建议空仓观望"

        # 情绪信号
        signals = []
        if data['涨停数量'] >= 10:
            signals.append("✅ 涨停数量充足，做多情绪强烈")
        elif data['涨停数量'] >= 5:
            signals.append("⚠️ 涨停数量一般，情绪温和")
        else:
            signals.append("❌ 涨停数量偏少，做多意愿不强")

        if data['最高连板'] >= 3:
            signals.append("✅ 连板高度可观，持续性良好")
        elif data['最高连板'] >= 2:
            signals.append("⚠️ 连板高度一般，持续性待观察")
        else:
            signals.append("❌ 缺乏连板，持续性不足")

        if data['跌停数量'] > 0:
            signals.append("⚠️ 出现跌停，需关注市场分化")

        if data['竞价封板'] >= 5:
            signals.append("✅ 竞价封板较多，开盘强势")

        content = f"""# 竞价阶段情绪分析 ({analysis['time'][:2]}:{analysis['time'][2:]})

## 情绪强度：{analysis['emoji']} ({analysis['score']}分 - {analysis['level']})

### 核心指标
- 涨停：{data['涨停数量']}只 | 跌停：{data['跌停数量']}只 | 净涨停：{data.get('净涨停', data['涨停数量'] - data['跌停数量'])}只
- 连板：最高{data['最高连板']}板，3板以上{data['三板以上']}只
- 竞价封板：{data['竞价封板']}只 {'(强势)' if data['竞价封板'] >= 5 else '(一般)' if data['竞价封板'] >= 2 else '(偏弱)'}

### 七维情绪数据
| 维度 | 数值 | 权重贡献 |
|------|------|----------|
| 🔴 涨停数量 | {data['涨停数量']}只 | +{min(25, data['涨停数量'] * 1.2):.1f}分 |
| 🟢 跌停数量 | {data['跌停数量']}只 | -{min(15, data['跌停数量'] * 6):.1f}分 |
| � 炸板数量 | {data.get('炸板数量', 0)}只 | -{min(15, data.get('炸板数量', 0) * 3):.1f}分 |
| �🔗 连板高度 | 最高{data['最高连板']}板 | +{min(15, data['最高连板'] * 2.5 + data['三板以上'] * 1.5):.1f}分 |
| � 炸板率 | {data.get('炸板率', 0):.1%} | -{data.get('炸板率', 0) * 12:.1f}分 |
| 📊 成交量比 | {data.get('成交量比', 1.0):.1f}倍 | {'+' if data.get('成交量比', 1.0) > 1 else ''}{min(8, (data.get('成交量比', 1.0) - 1) * 16) if data.get('成交量比', 1.0) > 1 else -(1 - data.get('成交量比', 1.0)) * 8:.1f}分 |
| 🔄 换手率 | {data.get('平均换手率', 0):.1f}% | +{min(4, data.get('平均换手率', 0) * 0.25):.1f}分 |
| � 封板金额 | {data.get('平均封板金额', 0):.1f}亿元 | +{min(8, data.get('平均封板金额', 0) * 1.6):.1f}分 |

### 情绪信号
{chr(10).join(signals)}

### 操作建议
{suggestion}

---
*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        return content

    def _generate_intraday_report(self, analysis: Dict) -> str:
        """生成盘中报告"""
        data = analysis['data']

        # 操作建议
        score = analysis['score']
        if score >= 70:
            suggestion = "**积极参与**：情绪高涨，可追涨强势股"
        elif score >= 50:
            suggestion = "**谨慎乐观**：情绪良好，选股要求提高"
        elif score >= 30:
            suggestion = "**观望为主**：情绪降温，等待机会"
        else:
            suggestion = "**规避风险**：情绪低迷，建议减仓"

        # 炸板率评价
        zhaban_rate = data['炸板率']
        if zhaban_rate <= 0.2:
            zhaban_desc = "低炸板率，封板坚决"
        elif zhaban_rate <= 0.4:
            zhaban_desc = "适中炸板率，分歧不大"
        else:
            zhaban_desc = "高炸板率，分歧较大"

        content = f"""# 盘中情绪分析 ({analysis['time'][:2]}:{analysis['time'][2:]})

## 情绪强度：{analysis['emoji']} ({analysis['score']}分 - {analysis['level']})

### 核心指标
- 涨停：{data['涨停数量']}只 | 跌停：{data['跌停数量']}只 | 炸板：{data['炸板数量']}只
- 连板维持：最高{data['最高连板']}板，3板以上{data['三板以上']}只
- 成交量比：{data['成交量比']:.1f}倍 | 平均换手率：{data['平均换手率']:.1f}%

### 七维情绪数据
| 维度 | 数值 | 权重贡献 |
|------|------|----------|
| 🔴 涨停数量 | {data['涨停数量']}只 | +{min(25, data['涨停数量'] * 1.2):.1f}分 |
| 🟢 跌停数量 | {data['跌停数量']}只 | -{min(15, data['跌停数量'] * 6):.1f}分 |
| 💥 炸板数量 | {data.get('炸板数量', 0)}只 | -{min(15, data.get('炸板数量', 0) * 3):.1f}分 |
| 🔗 连板高度 | 最高{data['最高连板']}板 | +{min(15, data['最高连板'] * 2.5 + data['三板以上'] * 1.5):.1f}分 |
| 💥 炸板率 | {zhaban_rate:.1%} | -{zhaban_rate * 12:.1f}分 |
| 📊 成交量比 | {data['成交量比']:.1f}倍 | {'+' if data['成交量比'] > 1 else ''}{min(8, (data['成交量比'] - 1) * 16) if data['成交量比'] > 1 else -(1 - data['成交量比']) * 8:.1f}分 |
| 🔄 换手率 | {data['平均换手率']:.1f}% | +{min(4, data['平均换手率'] * 0.25):.1f}分 |
| 💰 封板金额 | {data.get('平均封板金额', 0):.1f}亿元 | +{min(8, data.get('平均封板金额', 0) * 1.6):.1f}分 |

### 情绪变化
- 📊 炸板率：{zhaban_rate:.1%} ({zhaban_desc})
- 📈 成交量：{'放量' if data['成交量比'] > 1.2 else '缩量' if data['成交量比'] < 0.8 else '温和'}
- 🔄 换手率：{'活跃' if data['平均换手率'] > 5 else '一般' if data['平均换手率'] > 2 else '低迷'}

### 操作建议
{suggestion}

---
*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        return content

    def plot_mood_chart(self, analysis: Dict) -> str:
        """
        生成情绪图表

        Args:
            analysis: 分析结果

        Returns:
            图表文件路径
        """
        if not analysis:
            return ""

        date_str = analysis['date']
        time_point = analysis['time']
        report_type = analysis['type']

        # 创建日期目录
        date_dir = os.path.join(self.base_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)

        # 生成图表
        if report_type == 'auction':
            chart_path = self._plot_auction_chart(analysis, date_dir)
        else:
            chart_path = self._plot_intraday_chart(analysis, date_dir)

        return chart_path

    def _plot_auction_chart(self, analysis: Dict, date_dir: str) -> str:
        """绘制竞价阶段图表"""
        data = analysis['data']
        time_point = analysis['time']

        # 创建2x2图表 - 优化尺寸
        fig, axes = plt.subplots(2, 2, figsize=(12, 9))
        fig.suptitle(f'竞价阶段情绪分析 ({time_point[:2]}:{time_point[2:]})', fontsize=14, fontweight='bold', y=0.96)

        # 1. 情绪强度仪表盘
        self._plot_mood_gauge(axes[0, 0], analysis['score'], analysis['level'])

        # 2. 涨跌停对比
        categories = ['涨停', '跌停']
        counts = [data['涨停数量'], data['跌停数量']]
        colors = ['red', 'green']

        bars = axes[0, 1].bar(categories, counts, color=colors, alpha=0.7)
        axes[0, 1].set_title('涨跌停对比', fontsize=12, fontweight='bold')
        axes[0, 1].set_ylabel('股票数量', fontsize=10)
        axes[0, 1].tick_params(axis='both', which='major', labelsize=9)

        # 显示数值
        for i, count in enumerate(counts):
            axes[0, 1].text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold', fontsize=10)

        # 3. 量价联动分析
        self._plot_volume_price_analysis(axes[1, 0], analysis)

        # 4. 封板强度分析
        self._plot_fengban_strength_analysis(axes[1, 1], analysis)

        plt.tight_layout(rect=[0, 0.02, 1, 0.94])  # 为标题留出空间，更紧凑

        # 保存图表 - 优化文件大小
        chart_path = os.path.join(date_dir, f"{time_point}_auction_mood.png")
        plt.savefig(chart_path, dpi=120, bbox_inches='tight', facecolor='white',
                    edgecolor='none', format='png')
        plt.close()

        return chart_path

    def _plot_intraday_chart(self, analysis: Dict, date_dir: str) -> str:
        """绘制盘中图表"""
        data = analysis['data']
        time_point = analysis['time']

        # 创建2x2图表 - 优化尺寸
        fig, axes = plt.subplots(2, 2, figsize=(12, 9))
        fig.suptitle(f'盘中情绪分析 ({time_point[:2]}:{time_point[2:]})', fontsize=14, fontweight='bold', y=0.96)

        # 1. 情绪强度仪表盘
        self._plot_mood_gauge(axes[0, 0], analysis['score'], analysis['level'])

        # 2. 涨跌停炸板对比
        categories = ['涨停', '跌停', '炸板']
        counts = [data['涨停数量'], data['跌停数量'], data['炸板数量']]
        colors = ['red', 'green', 'orange']

        bars = axes[0, 1].bar(categories, counts, color=colors, alpha=0.7)
        axes[0, 1].set_title('涨跌停炸板对比', fontsize=12, fontweight='bold')
        axes[0, 1].set_ylabel('股票数量', fontsize=10)
        axes[0, 1].tick_params(axis='both', which='major', labelsize=9)

        # 显示数值
        for i, count in enumerate(counts):
            axes[0, 1].text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold', fontsize=10)

        # 3. 量价联动分析
        self._plot_volume_price_analysis(axes[1, 0], analysis)

        # 4. 封板强度分析
        self._plot_fengban_strength_analysis(axes[1, 1], analysis)

        plt.tight_layout(rect=[0, 0.02, 1, 0.94])  # 为标题留出空间，更紧凑

        # 保存图表 - 优化文件大小
        chart_path = os.path.join(date_dir, f"{time_point}_intraday_mood.png")
        plt.savefig(chart_path, dpi=120, bbox_inches='tight', facecolor='white',
                    edgecolor='none', format='png')
        plt.close()

        return chart_path

    def _plot_mood_gauge(self, ax, score: int, level: str):
        """绘制情绪强度仪表盘"""
        # 创建半圆仪表盘
        theta = np.linspace(0, np.pi, 100)

        # 背景扇形
        colors = ['red', 'orange', 'yellow', 'lightgreen', 'green']
        thresholds = [0, 30, 50, 70, 90, 100]

        for i in range(len(colors)):
            start_angle = np.pi * (1 - thresholds[i + 1] / 100)
            end_angle = np.pi * (1 - thresholds[i] / 100)
            theta_section = np.linspace(start_angle, end_angle, 20)
            x = np.cos(theta_section)
            y = np.sin(theta_section)
            ax.fill_between(x, 0, y, color=colors[i], alpha=0.3)

        # 指针
        needle_angle = np.pi * (1 - score / 100)
        needle_x = [0, 0.8 * np.cos(needle_angle)]
        needle_y = [0, 0.8 * np.sin(needle_angle)]
        ax.plot(needle_x, needle_y, 'k-', linewidth=3)
        ax.plot(0, 0, 'ko', markersize=8)

        # 设置坐标轴
        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-0.1, 1.1)
        ax.set_aspect('equal')
        ax.axis('off')

        # 添加标签
        ax.text(0, -0.3, f'{score}分', ha='center', va='center', fontsize=14, fontweight='bold')
        ax.text(0, -0.45, level, ha='center', va='center', fontsize=10)
        ax.set_title('情绪强度', fontsize=12, fontweight='bold', pad=10)

    def _plot_volume_price_analysis(self, ax, analysis: Dict):
        """绘制量价联动分析散点图"""
        try:
            if 'raw_data' not in analysis:
                ax.text(0.5, 0.5, '无原始数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
                return

            # 获取涨停数据
            zt_data = analysis['raw_data'].get('zt_data')
            if zt_data is None or zt_data.empty:
                ax.text(0.5, 0.5, '无涨停数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
                return

            # 提取数据
            x_data = []  # 换手率
            y_data = []  # 涨幅
            colors = []  # 颜色映射（连板数）
            sizes = []  # 点大小（封板金额）

            for _, row in zt_data.iterrows():
                turnover = row.get('换手率', 0)
                change = row.get('涨幅', 0)
                lianban = row.get('连板数', 1)
                fengban = row.get('封板资金', 0) / 1e8  # 转换为亿元

                if pd.notna(turnover) and pd.notna(change) and change > 0:  # 确保涨幅大于0
                    x_data.append(turnover)
                    y_data.append(change)
                    colors.append(lianban)
                    sizes.append(max(20, min(100, fengban * 20)))  # 根据封板金额调整点大小

            if not x_data:
                ax.text(0.5, 0.5, '无有效数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
                return

            # 绘制散点图
            scatter = ax.scatter(x_data, y_data, c=colors, s=sizes, cmap='Reds', alpha=0.6, edgecolors='black',
                                 linewidth=0.5)

            # 设置标签和标题
            ax.set_xlabel('换手率 (%)', fontsize=10)
            ax.set_ylabel('涨幅 (%)', fontsize=10)
            ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)

            # 添加颜色条
            if len(set(colors)) > 1:
                cbar = plt.colorbar(scatter, ax=ax)
                cbar.set_label('连板数', fontsize=9)
                cbar.ax.tick_params(labelsize=8)

            # 添加说明文字
            ax.text(0.02, 0.98, '点大小=封板金额', transform=ax.transAxes, fontsize=8,
                    verticalalignment='top', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))

            # 调整刻度字体大小
            ax.tick_params(axis='both', which='major', labelsize=8)

        except Exception as e:
            ax.text(0.5, 0.5, f'绘图错误: {str(e)}', ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_title('量价联动分析', fontsize=12, fontweight='bold')

    def _plot_fengban_strength_analysis(self, ax, analysis: Dict):
        """绘制封板强度分析 - 按涨跌幅等级分组的柱状图"""
        try:
            # 导入stock_util
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from utils.stock_util import stock_limit_ratio

            if 'raw_data' not in analysis:
                ax.text(0.5, 0.5, '无原始数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('封板强度分析', fontsize=12, fontweight='bold')
                return

            # 获取涨停和跌停数据
            zt_data = analysis['raw_data'].get('zt_data')
            dt_data = analysis['raw_data'].get('dt_data')

            # 按涨跌幅等级分组统计
            limit_groups = {
                '10%限制': {'涨停': [], '跌停': []},
                '20%限制': {'涨停': [], '跌停': []},
                '30%限制': {'涨停': [], '跌停': []}
            }

            # 处理涨停数据
            if zt_data is not None and not zt_data.empty:
                for _, row in zt_data.iterrows():
                    stock_code = str(row.get('股票代码', '000001'))
                    fengban_amount = row.get('封板资金', 0) / 1e8  # 转换为亿元

                    try:
                        limit_ratio = stock_limit_ratio(stock_code)
                        if limit_ratio == 0.1:
                            limit_groups['10%限制']['涨停'].append(fengban_amount)
                        elif limit_ratio == 0.2:
                            limit_groups['20%限制']['涨停'].append(fengban_amount)
                        elif limit_ratio == 0.3:
                            limit_groups['30%限制']['涨停'].append(fengban_amount)
                    except:
                        # 默认归为10%限制
                        limit_groups['10%限制']['涨停'].append(fengban_amount)

            # 处理跌停数据
            if dt_data is not None and not dt_data.empty:
                for _, row in dt_data.iterrows():
                    stock_code = str(row.get('股票代码', '600001'))
                    fengban_amount = row.get('封板资金', 0) / 1e8  # 转换为亿元

                    try:
                        limit_ratio = stock_limit_ratio(stock_code)
                        if limit_ratio == 0.1:
                            limit_groups['10%限制']['跌停'].append(fengban_amount)
                        elif limit_ratio == 0.2:
                            limit_groups['20%限制']['跌停'].append(fengban_amount)
                        elif limit_ratio == 0.3:
                            limit_groups['30%限制']['跌停'].append(fengban_amount)
                    except:
                        # 默认归为10%限制
                        limit_groups['10%限制']['跌停'].append(fengban_amount)

            # 计算每组的平均封板金额
            group_names = []
            zt_amounts = []
            dt_amounts = []

            for group_name, group_data in limit_groups.items():
                if group_data['涨停'] or group_data['跌停']:
                    group_names.append(group_name)
                    zt_avg = np.mean(group_data['涨停']) if group_data['涨停'] else 0
                    dt_avg = np.mean(group_data['跌停']) if group_data['跌停'] else 0
                    zt_amounts.append(zt_avg)
                    dt_amounts.append(dt_avg)

            if not group_names:
                ax.text(0.5, 0.5, '无封板数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('封板强度分析', fontsize=12, fontweight='bold')
                return

            # 绘制分组柱状图
            x = np.arange(len(group_names))
            width = 0.35

            bars1 = ax.bar(x - width / 2, zt_amounts, width, label='涨停', color='red', alpha=0.7)
            bars2 = ax.bar(x + width / 2, dt_amounts, width, label='跌停', color='green', alpha=0.7)

            # 设置标签和标题
            ax.set_xlabel('涨跌幅限制', fontsize=10)
            ax.set_ylabel('平均封板金额 (亿元)', fontsize=10)
            ax.set_title('封板强度分析', fontsize=12, fontweight='bold')
            ax.set_xticks(x)
            ax.set_xticklabels(group_names)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3, axis='y')

            # 在柱子上显示数值
            for bar in bars1:
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2., height + 0.05,
                            f'{height:.1f}', ha='center', va='bottom', fontsize=8)

            for bar in bars2:
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2., height + 0.05,
                            f'{height:.1f}', ha='center', va='bottom', fontsize=8)

            # 调整刻度字体大小
            ax.tick_params(axis='both', which='major', labelsize=8)

        except Exception as e:
            ax.text(0.5, 0.5, f'绘图错误: {str(e)}', ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_title('封板强度分析', fontsize=12, fontweight='bold')

    def run_analysis(self, date_str: str = None, time_point: str = "0925", analysis_type: str = "auction"):
        """
        运行完整的情绪分析

        Args:
            date_str: 日期字符串
            time_point: 时间点
            analysis_type: 分析类型 ('auction' 或 'intraday')
        """
        print(f"🔍 开始{analysis_type}情绪分析...")

        # 执行分析
        if analysis_type == "auction":
            analysis = self.analyze_auction_mood(date_str, time_point)
        else:
            analysis = self.analyze_intraday_mood(date_str, time_point)

        if not analysis:
            print("❌ 分析失败")
            return

        # 生成报告
        print("📝 生成情绪报告...")
        report_path = self.generate_mood_report(analysis)

        # 生成图表
        print("📊 生成情绪图表...")
        chart_path = self.plot_mood_chart(analysis)

        # 输出结果
        print(f"\n✅ 情绪分析完成！")
        print(f"📅 分析日期: {analysis['date']}")
        print(f"⏰ 分析时间: {time_point[:2]}:{time_point[2:]}")
        print(f"🎯 情绪强度: {analysis['emoji']} {analysis['score']}分 - {analysis['level']}")
        print(f"📄 分析报告: {report_path}")
        print(f"📊 分析图表: {chart_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='盘中情绪分析器')
    parser.add_argument('--date', type=str, help='分析日期 (YYYYMMDD)')
    parser.add_argument('--time', type=str, default='0925', help='时间点 (HHMM)')
    parser.add_argument('--type', type=str, choices=['auction', 'intraday'], default='auction', help='分析类型')

    args = parser.parse_args()

    # 设置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # 创建分析器
    analyzer = MoodAnalyzer()

    # 运行分析
    analyzer.run_analysis(args.date, args.time, args.type)


if __name__ == "__main__":
    main()
