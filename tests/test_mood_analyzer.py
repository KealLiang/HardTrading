"""
盘中情绪分析器测试

测试竞价和盘中情绪分析功能，生成示例报告和图表。
包含完整的mock数据，确保图表有丰富的数据展示。

使用方法：
python tests/test_mood_analyzer.py
"""

import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict
from datetime import datetime
sys.path.append('.')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False


class MockMoodAnalyzer:
    """带mock数据的情绪分析器"""

    def __init__(self):
        # 不调用父类初始化，避免依赖外部API
        self.base_dir = "alerting/mood"
        self.logger = self._setup_logger()

    def _setup_logger(self):
        """设置日志"""
        import logging
        logger = logging.getLogger('MockMoodAnalyzer')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def calculate_mood_score(self, data: Dict) -> int:
        """计算情绪评分"""
        score = 40  # 基础分数

        # 1. 涨停贡献 (最高25分)
        zt_count = data.get('涨停数量', 0)
        score += min(25, zt_count * 1.2)

        # 2. 跌停影响 (最多-15分)
        dt_count = data.get('跌停数量', 0)
        score -= min(15, dt_count * 6)

        # 3. 连板高度 (最高15分)
        max_lianban = data.get('最高连板', 0)
        lianban_3_plus = data.get('三板以上', 0)
        score += min(15, max_lianban * 2.5 + lianban_3_plus * 1.5)

        # 4. 炸板率影响 (最多-12分)
        zhaban_rate = data.get('炸板率', 0)
        score -= zhaban_rate * 12

        # 5. 成交量 (最高8分)
        volume_ratio = data.get('成交量比', 1.0)
        if volume_ratio > 1:
            score += min(8, (volume_ratio - 1) * 16)
        else:
            score -= (1 - volume_ratio) * 8

        # 6. 换手率 (最高4分)
        avg_turnover = data.get('平均换手率', 0)
        score += min(4, avg_turnover * 0.25)

        # 7. 封板金额强度 (最高8分)
        avg_fengdan = data.get('平均封板金额', 0)  # 亿元
        if avg_fengdan > 0:
            score += min(8, avg_fengdan * 1.6)  # 每亿元加1.6分

        return max(0, min(100, int(score)))

    def get_mood_level(self, score: int) -> tuple:
        """获取情绪等级"""
        if score >= 80:
            return "极度狂热", "🔥🔥🔥🔥🔥"
        elif score >= 65:
            return "高度活跃", "🔥🔥🔥🔥"
        elif score >= 50:
            return "温和乐观", "🔥🔥🔥"
        elif score >= 35:
            return "谨慎观望", "🔥🔥"
        else:
            return "恐慌情绪", "🔥"

    def create_mock_auction_data(self, scenario: str = "normal") -> Dict:
        """创建竞价阶段模拟数据"""
        from utils.stock_util import stock_limit_ratio

        if scenario == "hot":
            # 极热市场：大量涨停，高连板，大封单
            zt_stocks = []
            stock_codes = ['600001', '600036', '600519', '000001', '000002', '002415',
                          '688001', '688036', '688088', '300001', '300036', '300750']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'热门股{i+1}',
                    '换手率': np.random.uniform(8, 35),
                    '涨幅': np.random.uniform(limit_ratio*100-0.2, limit_ratio*100+0.1),
                    '连板数': np.random.choice([1, 2, 3, 4, 5, 6], p=[0.1, 0.2, 0.3, 0.2, 0.15, 0.05]),
                    '封板资金': np.random.uniform(3e8, 15e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600901'],
                '股票名称': ['跌停股1'],
                '换手率': [2.1],
                '涨幅': [-10.01],
                '封板资金': [1.2e8]
            })

        elif scenario == "cold":
            # 冷淡市场：少量涨停，较多跌停
            zt_stocks = []
            stock_codes = ['600001', '600036', '000001', '000002']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'普通股{i+1}',
                    '换手率': np.random.uniform(1, 8),
                    '涨幅': np.random.uniform(limit_ratio*100-0.15, limit_ratio*100+0.05),
                    '连板数': 1,
                    '封板资金': np.random.uniform(0.5e8, 3e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600801', '600802', '000801', '000802', '002801', '300801'],
                '股票名称': ['跌停股1', '跌停股2', '跌停股3', '跌停股4', '跌停股5', '跌停股6'],
                '换手率': [0.8, 1.5, 2.1, 1.2, 3.5, 2.8],
                '涨幅': [-10.02, -9.99, -10.01, -9.98, -10.00, -19.95],
                '封板资金': [0.3e8, 0.8e8, 1.2e8, 0.6e8, 1.5e8, 2.1e8]
            })

        else:  # normal
            # 正常市场：适中的涨停数量
            zt_stocks = []
            stock_codes = ['600001', '600036', '600519', '000001', '000002', '002415',
                          '688001', '688036', '300001', '300036']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'正常股{i+1}',
                    '换手率': np.random.uniform(3, 18),
                    '涨幅': np.random.uniform(limit_ratio*100-0.1, limit_ratio*100+0.05),
                    '连板数': np.random.choice([1, 2, 3, 4], p=[0.4, 0.35, 0.2, 0.05]),
                    '封板资金': np.random.uniform(1e8, 8e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600901', '000901', '002901'],
                '股票名称': ['跌停股1', '跌停股2', '跌停股3'],
                '换手率': [1.8, 2.5, 3.2],
                '涨幅': [-10.02, -9.99, -10.01],
                '封板资金': [0.9e8, 1.3e8, 0.7e8]
            })

        zt_data = pd.DataFrame(zt_stocks)

        # 计算指标
        zt_count = len(zt_data)
        dt_count = len(dt_data)
        max_lianban = zt_data['连板数'].max()
        lianban_3_plus = len(zt_data[zt_data['连板数'] >= 3])
        avg_turnover = zt_data['换手率'].mean()
        avg_fengban = zt_data['封板资金'].mean() / 1e8

        analysis_data = {
            '涨停数量': zt_count,
            '跌停数量': dt_count,
            '竞价封板': max(1, int(zt_count * 0.6)),  # 60%竞价封板
            '最高连板': max_lianban,
            '三板以上': lianban_3_plus,
            '炸板率': 0,  # 竞价阶段无炸板
            '成交量比': 1.0,  # 竞价阶段无成交量
            '平均换手率': avg_turnover,
            '平均封板金额': avg_fengban,
            '净涨停': zt_count - dt_count
        }

        return {
            'data': analysis_data,
            'raw_data': {
                'zt_data': zt_data,
                'dt_data': dt_data,
                'auction_data': zt_data.head(analysis_data['竞价封板'])
            }
        }

    def create_mock_intraday_data(self, scenario: str = "normal") -> Dict:
        """创建盘中模拟数据"""
        from utils.stock_util import stock_limit_ratio

        if scenario == "hot":
            # 极热市场
            zt_stocks = []
            stock_codes = ['600001', '600036', '600519', '000001', '000002', '002415',
                          '688001', '688036', '688088', '300001', '300036', '300750', '300059', '002594']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'热门股{i+1}',
                    '换手率': np.random.uniform(10, 40),
                    '涨幅': np.random.uniform(limit_ratio*100-0.25, limit_ratio*100+0.15),
                    '连板数': np.random.choice([1, 2, 3, 4, 5, 6], p=[0.1, 0.2, 0.3, 0.2, 0.15, 0.05]),
                    '炸板次数': np.random.choice([0, 1, 2], p=[0.8, 0.15, 0.05]),
                    '封板资金': np.random.uniform(5e8, 20e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600901', '000901'],
                '股票名称': ['跌停股1', '跌停股2'],
                '换手率': [3.1, 4.5],
                '涨幅': [-10.01, -9.98],
                '封板资金': [2.2e8, 1.8e8]
            })

            volume_ratio = 2.5

        elif scenario == "cold":
            # 冷淡市场
            zt_stocks = []
            stock_codes = ['600001', '600036', '000001']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'普通股{i+1}',
                    '换手率': np.random.uniform(0.8, 5),
                    '涨幅': np.random.uniform(limit_ratio*100-0.1, limit_ratio*100+0.02),
                    '连板数': 1,
                    '炸板次数': np.random.choice([1, 2, 3], p=[0.4, 0.4, 0.2]),
                    '封板资金': np.random.uniform(0.3e8, 2e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600801', '600802', '000801', '000802', '002801', '300801', '300802', '688801'],
                '股票名称': ['跌停股1', '跌停股2', '跌停股3', '跌停股4', '跌停股5', '跌停股6', '跌停股7', '跌停股8'],
                '换手率': [0.5, 1.2, 1.8, 0.9, 2.5, 1.6, 3.1, 4.2],
                '涨幅': [-10.02, -9.99, -10.01, -9.98, -10.00, -19.95, -19.98, -20.01],
                '封板资金': [0.2e8, 0.6e8, 0.9e8, 0.4e8, 1.2e8, 1.8e8, 2.5e8, 3.1e8]
            })

            volume_ratio = 0.4

        else:  # normal
            # 正常市场
            zt_stocks = []
            stock_codes = ['600001', '600036', '600519', '000001', '000002', '002415',
                          '688001', '688036', '300001', '300036', '300059']

            for i, code in enumerate(stock_codes):
                limit_ratio = stock_limit_ratio(code)
                zt_stocks.append({
                    '股票代码': code,
                    '股票名称': f'正常股{i+1}',
                    '换手率': np.random.uniform(4, 20),
                    '涨幅': np.random.uniform(limit_ratio*100-0.12, limit_ratio*100+0.06),
                    '连板数': np.random.choice([1, 2, 3, 4], p=[0.4, 0.35, 0.2, 0.05]),
                    '炸板次数': np.random.choice([0, 1, 2], p=[0.6, 0.3, 0.1]),
                    '封板资金': np.random.uniform(1.5e8, 10e8)
                })

            dt_data = pd.DataFrame({
                '股票代码': ['600901', '000901', '002901', '300901'],
                '股票名称': ['跌停股1', '跌停股2', '跌停股3', '跌停股4'],
                '换手率': [1.8, 2.5, 3.2, 4.1],
                '涨幅': [-10.02, -9.99, -10.01, -19.98],
                '封板资金': [0.9e8, 1.3e8, 0.7e8, 2.1e8]
            })

            volume_ratio = 1.4

        zt_data = pd.DataFrame(zt_stocks)

        # 计算指标
        zt_count = len(zt_data)
        dt_count = len(dt_data)
        max_lianban = zt_data['连板数'].max()
        lianban_3_plus = len(zt_data[zt_data['连板数'] >= 3])
        zhaban_count = len(zt_data[zt_data['炸板次数'] > 0])
        zhaban_rate = zhaban_count / zt_count if zt_count > 0 else 0
        avg_turnover = zt_data['换手率'].mean()
        avg_fengban = zt_data['封板资金'].mean() / 1e8

        analysis_data = {
            '涨停数量': zt_count,
            '跌停数量': dt_count,
            '炸板数量': zhaban_count,
            '最高连板': max_lianban,
            '三板以上': lianban_3_plus,
            '炸板率': zhaban_rate,
            '成交量比': volume_ratio,
            '平均换手率': avg_turnover,
            '平均封板金额': avg_fengban,
            '净涨停': zt_count - dt_count
        }

        return {
            'data': analysis_data,
            'raw_data': {
                'zt_data': zt_data,
                'dt_data': dt_data
            }
        }

    def analyze_auction_mood(self, date_str: str = None, time_point: str = "0925") -> Dict:
        """分析竞价阶段情绪 - 使用mock数据"""
        if not date_str:
            date_str = datetime.now().strftime('%Y%m%d')

        # 根据时间点选择不同场景
        if time_point in ["0915"]:
            scenario = "cold"
        elif time_point in ["0925"]:
            scenario = "hot"
        else:
            scenario = "normal"

        mock_data = self.create_mock_auction_data(scenario)
        score = self.calculate_mood_score(mock_data['data'])
        level, emoji = self.get_mood_level(score)

        return {
            'date': date_str,
            'time': time_point,
            'type': 'auction',
            'score': score,
            'level': level,
            'emoji': emoji,
            'data': mock_data['data'],
            'raw_data': mock_data['raw_data']
        }

    def analyze_intraday_mood(self, date_str: str = None, time_point: str = "1000") -> Dict:
        """分析盘中情绪 - 使用mock数据"""
        if not date_str:
            date_str = datetime.now().strftime('%Y%m%d')

        # 根据时间点选择不同场景
        if time_point in ["1000", "1430"]:
            scenario = "hot"
        elif time_point in ["1100"]:
            scenario = "cold"
        else:
            scenario = "normal"

        mock_data = self.create_mock_intraday_data(scenario)
        score = self.calculate_mood_score(mock_data['data'])
        level, emoji = self.get_mood_level(score)

        return {
            'date': date_str,
            'time': time_point,
            'type': 'intraday',
            'score': score,
            'level': level,
            'emoji': emoji,
            'data': mock_data['data'],
            'raw_data': mock_data['raw_data']
        }

    def generate_mood_report(self, analysis: Dict) -> str:
        """生成情绪分析报告"""
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
        score = analysis['score']
        level = analysis['level']
        emoji = analysis['emoji']

        # 操作建议
        if score >= 70:
            suggestion = "**积极参与**：情绪高涨，适合追涨强势股"
        elif score >= 50:
            suggestion = "**谨慎乐观**：情绪良好，可关注优质标的"
        elif score >= 35:
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

## 情绪强度：{emoji} ({score}分 - {level})

### 核心指标
- 涨停：{data['涨停数量']}只 | 跌停：{data['跌停数量']}只 | 净涨停：{data.get('净涨停', data['涨停数量'] - data['跌停数量'])}只
- 连板：最高{data['最高连板']}板，3板以上{data['三板以上']}只
- 竞价封板：{data['竞价封板']}只 {'(强势)' if data['竞价封板'] >= 5 else '(一般)' if data['竞价封板'] >= 2 else '(偏弱)'}
- 封板金额：平均{data['平均封板金额']:.1f}亿元

### 七维情绪数据
| 维度 | 数值 | 权重贡献 |
|------|------|----------|
| 🔴 涨停数量 | {data['涨停数量']}只 | +{min(25, data['涨停数量'] * 1.2):.1f}分 |
| 🟢 跌停数量 | {data['跌停数量']}只 | -{min(15, data['跌停数量'] * 6):.1f}分 |
| 🔗 连板高度 | 最高{data['最高连板']}板 | +{min(15, data['最高连板'] * 2.5 + data['三板以上'] * 1.5):.1f}分 |
| 💥 炸板率 | {data.get('炸板率', 0):.1%} | -{data.get('炸板率', 0) * 12:.1f}分 |
| 📊 成交量比 | {data.get('成交量比', 1.0):.1f}倍 | {'+'if data.get('成交量比', 1.0) > 1 else ''}{min(8, (data.get('成交量比', 1.0) - 1) * 16) if data.get('成交量比', 1.0) > 1 else -(1 - data.get('成交量比', 1.0)) * 8:.1f}分 |
| 🔄 换手率 | {data.get('平均换手率', 0):.1f}% | +{min(4, data.get('平均换手率', 0) * 0.25):.1f}分 |
| 💰 封板金额 | {data.get('平均封板金额', 0):.1f}亿元 | +{min(8, data.get('平均封板金额', 0) * 1.6):.1f}分 |

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
        score = analysis['score']
        level = analysis['level']
        emoji = analysis['emoji']

        # 操作建议
        if score >= 70:
            suggestion = "**积极参与**：情绪高涨，可追涨强势股"
        elif score >= 50:
            suggestion = "**谨慎乐观**：情绪良好，选股要求提高"
        elif score >= 35:
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

## 情绪强度：{emoji} ({score}分 - {level})

### 核心指标
- 涨停：{data['涨停数量']}只 | 跌停：{data['跌停数量']}只 | 炸板：{data['炸板数量']}只
- 连板维持：最高{data['最高连板']}板，3板以上{data['三板以上']}只
- 成交量比：{data['成交量比']:.1f}倍 | 平均换手率：{data['平均换手率']:.1f}%
- 封板金额：平均{data['平均封板金额']:.1f}亿元

### 七维情绪数据
| 维度 | 数值 | 权重贡献 |
|------|------|----------|
| 🔴 涨停数量 | {data['涨停数量']}只 | +{min(25, data['涨停数量'] * 1.2):.1f}分 |
| 🟢 跌停数量 | {data['跌停数量']}只 | -{min(15, data['跌停数量'] * 6):.1f}分 |
| 🔗 连板高度 | 最高{data['最高连板']}板 | +{min(15, data['最高连板'] * 2.5 + data['三板以上'] * 1.5):.1f}分 |
| 💥 炸板率 | {zhaban_rate:.1%} | -{zhaban_rate * 12:.1f}分 |
| 📊 成交量比 | {data['成交量比']:.1f}倍 | {'+'if data['成交量比'] > 1 else ''}{min(8, (data['成交量比'] - 1) * 16) if data['成交量比'] > 1 else -(1 - data['成交量比']) * 8:.1f}分 |
| 🔄 换手率 | {data['平均换手率']:.1f}% | +{min(4, data['平均换手率'] * 0.25):.1f}分 |
| 💰 封板金额 | {data['平均封板金额']:.1f}亿元 | +{min(8, data['平均封板金额'] * 1.6):.1f}分 |

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
        """生成情绪图表"""
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
            return self._plot_auction_chart(analysis, date_dir)
        else:
            return self._plot_intraday_chart(analysis, date_dir)

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

        for i, count in enumerate(counts):
            axes[0, 1].text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold', fontsize=10)

        # 3. 量价联动分析
        self._plot_volume_price_analysis(axes[1, 0], analysis)

        # 4. 封板强度分析
        self._plot_fengban_strength_analysis(axes[1, 1], analysis)

        plt.tight_layout(rect=[0, 0.02, 1, 0.94])  # 更紧凑

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

        # 2. 涨跌停对比
        categories = ['涨停', '跌停', '炸板']
        counts = [data['涨停数量'], data['跌停数量'], data['炸板数量']]
        colors = ['red', 'green', 'orange']

        bars = axes[0, 1].bar(categories, counts, color=colors, alpha=0.7)
        axes[0, 1].set_title('涨跌停炸板对比', fontsize=12, fontweight='bold')
        axes[0, 1].set_ylabel('股票数量', fontsize=10)
        axes[0, 1].tick_params(axis='both', which='major', labelsize=9)

        for i, count in enumerate(counts):
            axes[0, 1].text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold', fontsize=10)

        # 3. 量价联动分析
        self._plot_volume_price_analysis(axes[1, 0], analysis)

        # 4. 封板强度分析
        self._plot_fengban_strength_analysis(axes[1, 1], analysis)

        plt.tight_layout(rect=[0, 0.02, 1, 0.94])  # 更紧凑

        # 保存图表 - 优化文件大小
        chart_path = os.path.join(date_dir, f"{time_point}_intraday_mood.png")
        plt.savefig(chart_path, dpi=120, bbox_inches='tight', facecolor='white',
                   edgecolor='none', format='png')
        plt.close()

        return chart_path

    def _plot_mood_gauge(self, ax, score: int, level: str):
        """绘制情绪强度仪表盘"""
        theta = np.linspace(0, np.pi, 100)
        colors = ['red', 'orange', 'yellow', 'lightgreen', 'green']
        thresholds = [0, 30, 50, 70, 90, 100]

        for i in range(len(colors)):
            start_angle = np.pi * (1 - thresholds[i+1]/100)
            end_angle = np.pi * (1 - thresholds[i]/100)
            theta_section = np.linspace(start_angle, end_angle, 20)
            x = np.cos(theta_section)
            y = np.sin(theta_section)
            ax.fill_between(x, 0, y, color=colors[i], alpha=0.3)

        # 指针
        needle_angle = np.pi * (1 - score/100)
        needle_x = [0, 0.8 * np.cos(needle_angle)]
        needle_y = [0, 0.8 * np.sin(needle_angle)]
        ax.plot(needle_x, needle_y, 'k-', linewidth=3)
        ax.plot(0, 0, 'ko', markersize=8)

        ax.set_xlim(-1.1, 1.1)
        ax.set_ylim(-0.1, 1.1)
        ax.set_aspect('equal')
        ax.axis('off')

        ax.text(0, -0.3, f'{score}分', ha='center', va='center', fontsize=14, fontweight='bold')
        ax.text(0, -0.45, level, ha='center', va='center', fontsize=10)
        ax.set_title('情绪强度', fontsize=12, fontweight='bold', pad=10)

    def _plot_volume_price_analysis(self, ax, analysis: Dict):
        """绘制量价联动分析"""
        try:
            if 'raw_data' not in analysis or 'zt_data' not in analysis['raw_data']:
                ax.text(0.5, 0.5, '无原始数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
                return

            # 获取涨停数据
            zt_data = analysis['raw_data'].get('zt_data')
            if zt_data is None or zt_data.empty:
                ax.text(0.5, 0.5, '无涨停数据', ha='center', va='center', transform=ax.transAxes, fontsize=10)
                ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
                return

            x_data = zt_data['换手率'].tolist()
            y_data = zt_data['涨幅'].tolist()
            colors = zt_data['连板数'].tolist()
            sizes = [(row['封板资金'] / 1e8 * 15) for _, row in zt_data.iterrows()]
            sizes = [max(15, min(80, s)) for s in sizes]

            scatter = ax.scatter(x_data, y_data, c=colors, s=sizes, cmap='Reds', alpha=0.6, edgecolors='black', linewidth=0.5)

            ax.set_xlabel('换手率 (%)', fontsize=10)
            ax.set_ylabel('涨幅 (%)', fontsize=10)
            ax.set_title('量价联动分析', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)

            if len(set(colors)) > 1:
                cbar = plt.colorbar(scatter, ax=ax)
                cbar.set_label('连板数', fontsize=9)
                cbar.ax.tick_params(labelsize=8)

            ax.text(0.02, 0.98, '点大小=封板金额', transform=ax.transAxes, fontsize=8,
                   verticalalignment='top', bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))

            ax.tick_params(axis='both', which='major', labelsize=8)

        except Exception as e:
            ax.text(0.5, 0.5, f'绘图错误: {str(e)}', ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_title('量价联动分析', fontsize=12, fontweight='bold')

    def _plot_fengban_strength_analysis(self, ax, analysis: Dict):
        """绘制封板强度分析 - 按涨跌幅等级分组的柱状图"""
        try:
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
                    stock_code = str(row['股票代码'])
                    fengban_amount = row['封板资金'] / 1e8

                    try:
                        limit_ratio = stock_limit_ratio(stock_code)
                        if limit_ratio == 0.1:
                            limit_groups['10%限制']['涨停'].append(fengban_amount)
                        elif limit_ratio == 0.2:
                            limit_groups['20%限制']['涨停'].append(fengban_amount)
                        elif limit_ratio == 0.3:
                            limit_groups['30%限制']['涨停'].append(fengban_amount)
                    except:
                        limit_groups['10%限制']['涨停'].append(fengban_amount)

            # 处理跌停数据
            if dt_data is not None and not dt_data.empty:
                for _, row in dt_data.iterrows():
                    stock_code = str(row['股票代码'])
                    fengban_amount = row['封板资金'] / 1e8

                    try:
                        limit_ratio = stock_limit_ratio(stock_code)
                        if limit_ratio == 0.1:
                            limit_groups['10%限制']['跌停'].append(fengban_amount)
                        elif limit_ratio == 0.2:
                            limit_groups['20%限制']['跌停'].append(fengban_amount)
                        elif limit_ratio == 0.3:
                            limit_groups['30%限制']['跌停'].append(fengban_amount)
                    except:
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

            bars1 = ax.bar(x - width/2, zt_amounts, width, label='涨停', color='red', alpha=0.7)
            bars2 = ax.bar(x + width/2, dt_amounts, width, label='跌停', color='green', alpha=0.7)

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
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                           f'{height:.1f}', ha='center', va='bottom', fontsize=8)

            for bar in bars2:
                height = bar.get_height()
                if height > 0:
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.05,
                           f'{height:.1f}', ha='center', va='bottom', fontsize=8)

            ax.tick_params(axis='both', which='major', labelsize=8)

        except Exception as e:
            ax.text(0.5, 0.5, f'绘图错误: {str(e)}', ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_title('封板强度分析', fontsize=12, fontweight='bold')


def test_mood_analyzer():
    """测试情绪分析器 - 使用丰富的mock数据"""
    print("=" * 60)
    print("🧪 盘中情绪分析器测试 (Mock数据版)")
    print("=" * 60)

    # 创建mock分析器
    analyzer = MockMoodAnalyzer()

    # 测试日期
    test_date = datetime.now().strftime('%Y%m%d')

    print(f"📅 测试日期: {test_date}")
    print("📊 使用丰富的mock数据，确保图表有完整展示效果")

    # 1. 测试竞价阶段情绪分析
    print("\n1️⃣ 测试竞价阶段情绪分析...")

    # 测试不同时间点和场景
    auction_scenarios = [
        ("0915", "冷淡开盘"),
        ("0920", "正常竞价"),
        ("0925", "热烈封板")
    ]

    for time_point, desc in auction_scenarios:
        print(f"\n   📈 {desc} - {time_point[:2]}:{time_point[2:]}")

        # 执行分析
        analysis = analyzer.analyze_auction_mood(test_date, time_point)

        if analysis:
            print(f"      情绪评分: {analysis['score']}分 ({analysis['level']})")
            print(f"      涨停数量: {analysis['data']['涨停数量']}只")
            print(f"      跌停数量: {analysis['data']['跌停数量']}只")
            print(f"      竞价封板: {analysis['data']['竞价封板']}只")
            print(f"      最高连板: {analysis['data']['最高连板']}板")
            print(f"      封板金额: {analysis['data']['平均封板金额']:.1f}亿元")

            # 检查数据完整性
            zt_data = analysis['raw_data']['zt_data']
            if not zt_data.empty:
                print(f"      涨幅范围: {zt_data['涨幅'].min():.2f}% - {zt_data['涨幅'].max():.2f}%")

            # 生成报告和图表
            report_path = analyzer.generate_mood_report(analysis)
            chart_path = analyzer.plot_mood_chart(analysis)

            # 检查文件大小
            if os.path.exists(chart_path):
                chart_size = os.path.getsize(chart_path) / 1024
                print(f"      ✅ 报告: {os.path.basename(report_path)}")
                print(f"      ✅ 图表: {os.path.basename(chart_path)} ({chart_size:.0f}KB)")
            else:
                print(f"      ❌ 图表生成失败")
        else:
            print("      ❌ 分析失败")

    # 2. 测试盘中情绪分析
    print("\n2️⃣ 测试盘中情绪分析...")

    # 测试不同时间点和场景
    intraday_scenarios = [
        ("1000", "热烈开盘"),
        ("1100", "冷淡调整"),
        ("1330", "正常午后"),
        ("1430", "热烈尾盘")
    ]

    for time_point, desc in intraday_scenarios:
        print(f"\n   📊 {desc} - {time_point[:2]}:{time_point[2:]}")

        # 执行分析
        analysis = analyzer.analyze_intraday_mood(test_date, time_point)

        if analysis:
            print(f"      情绪评分: {analysis['score']}分 ({analysis['level']})")
            print(f"      涨停数量: {analysis['data']['涨停数量']}只")
            print(f"      跌停数量: {analysis['data']['跌停数量']}只")
            print(f"      炸板数量: {analysis['data']['炸板数量']}只")
            print(f"      炸板率: {analysis['data']['炸板率']:.1%}")
            print(f"      成交量比: {analysis['data']['成交量比']:.1f}倍")
            print(f"      换手率: {analysis['data']['平均换手率']:.1f}%")
            print(f"      封板金额: {analysis['data']['平均封板金额']:.1f}亿元")

            # 检查数据完整性
            zt_data = analysis['raw_data']['zt_data']
            if not zt_data.empty:
                print(f"      涨幅范围: {zt_data['涨幅'].min():.2f}% - {zt_data['涨幅'].max():.2f}%")

            # 生成报告和图表
            report_path = analyzer.generate_mood_report(analysis)
            chart_path = analyzer.plot_mood_chart(analysis)

            # 检查文件大小
            if os.path.exists(chart_path):
                chart_size = os.path.getsize(chart_path) / 1024
                print(f"      ✅ 报告: {os.path.basename(report_path)}")
                print(f"      ✅ 图表: {os.path.basename(chart_path)} ({chart_size:.0f}KB)")
            else:
                print(f"      ❌ 图表生成失败")
        else:
            print("      ❌ 分析失败")
    
    # 3. 查看生成的文件
    print("\n3️⃣ 查看生成的文件...")
    
    mood_dir = f"alerting/mood/{test_date}"
    if os.path.exists(mood_dir):
        files = os.listdir(mood_dir)
        files.sort()
        
        print(f"\n   📁 输出目录: {mood_dir}")
        print("   📄 生成的文件:")
        
        for file in files:
            file_path = os.path.join(mood_dir, file)
            file_size = os.path.getsize(file_path)
            
            if file.endswith('.md'):
                icon = "📝"
            elif file.endswith('.png'):
                icon = "📊"
            else:
                icon = "📄"
            
            print(f"     {icon} {file} ({file_size} bytes)")
    else:
        print(f"   ❌ 输出目录不存在: {mood_dir}")
    
    # 4. 展示报告内容示例
    print("\n4️⃣ 展示报告内容示例...")
    
    # 显示最新的竞价报告
    auction_report = f"{mood_dir}/0925_auction_mood.md"
    if os.path.exists(auction_report):
        print(f"\n   📝 竞价报告内容 ({auction_report}):")
        print("   " + "-" * 50)
        with open(auction_report, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只显示前10行
            lines = content.split('\n')[:10]
            for line in lines:
                print(f"   {line}")
        print("   " + "-" * 50)
    
    # 显示最新的盘中报告
    intraday_report = f"{mood_dir}/1000_intraday_mood.md"
    if os.path.exists(intraday_report):
        print(f"\n   📝 盘中报告内容 ({intraday_report}):")
        print("   " + "-" * 50)
        with open(intraday_report, 'r', encoding='utf-8') as f:
            content = f.read()
            # 只显示前10行
            lines = content.split('\n')[:10]
            for line in lines:
                print(f"   {line}")
        print("   " + "-" * 50)
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("\n📊 总结:")
    print("   - 竞价阶段分析：专注开盘情绪，关注竞价封板")
    print("   - 盘中分析：关注炸板率、成交量变化")
    print("   - 情绪评分：0-100分，自动判断情绪等级")
    print("   - 报告简洁：便于盘中快速决策")
    print("   - 图表直观：仪表盘+对比图+分布图")
    print("\n🎯 使用建议:")
    print("   - 竞价阶段：关注开盘强度，制定当日策略")
    print("   - 盘中阶段：跟踪情绪变化，及时调整仓位")
    print("   - 情绪强度：>70分积极参与，<30分规避风险")
    print("=" * 60)


def test_specific_analysis():
    """测试特定分析功能"""
    print("\n🔬 测试特定分析功能...")

    analyzer = MockMoodAnalyzer()

    # 测试情绪评分算法
    test_data = {
        '涨停数量': 15,
        '跌停数量': 2,
        '竞价封板': 8,
        '最高连板': 4,
        '三板以上': 3,
        '炸板率': 0.2,
        '成交量比': 1.3,
        '平均换手率': 6.5,
        '平均封板金额': 5.2,
        '净涨停': 13
    }

    score = analyzer.calculate_mood_score(test_data)
    level, emoji = analyzer.get_mood_level(score)

    print(f"   测试数据: {test_data}")
    print(f"   计算结果: {score}分 - {level} {emoji}")

    # 测试不同情绪等级
    test_scores = [95, 75, 55, 35, 15]
    print(f"\n   情绪等级测试:")
    for score in test_scores:
        level, emoji = analyzer.get_mood_level(score)
        print(f"     {score}分 → {level} {emoji}")


if __name__ == "__main__":
    test_mood_analyzer()
    test_specific_analysis()
