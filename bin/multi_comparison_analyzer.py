"""
多维对比分析器
负责解析多个回测结果文件，生成综合对比报告和参数敏感性分析
"""

import os
import re
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Tuple
import logging
from pathlib import Path


class MultiComparisonAnalyzer:
    """多维对比分析器"""

    def __init__(self, results_dir: str):
        self.results_dir = results_dir
        self.results_data = {}
        self.parameter_combinations = []

    def parse_all_results(self, result_files: List[str], parameter_combinations: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """解析所有回测结果文件"""
        all_results = {}

        # 创建文件名到参数组合名称的映射
        file_to_combo_name = {}
        if parameter_combinations:
            for combo in parameter_combinations:
                combo_name = combo['name']
                expected_filename = f"backtest_{combo_name}.txt"
                file_to_combo_name[expected_filename] = combo_name

        for file_path in result_files:
            if not os.path.exists(file_path):
                logging.warning(f"结果文件不存在: {file_path}")
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 从文件名提取参数组合名称
                file_name = os.path.basename(file_path)

                # 优先使用映射表中的名称，否则从文件名解析
                if file_name in file_to_combo_name:
                    combo_name = file_to_combo_name[file_name]
                else:
                    combo_name = file_name.replace('backtest_', '').replace('.txt', '')

                # 解析单个文件的结果
                parsed_results = self._parse_single_result(content)
                if parsed_results:
                    all_results[combo_name] = parsed_results

            except Exception as e:
                logging.error(f"解析结果文件 {file_path} 时出错: {e}")

        self.results_data = all_results
        return all_results

    def _parse_single_result(self, content: str) -> Dict[str, Dict[str, Any]]:
        """解析单个回测结果文件"""
        # 复用experiment_runner.py中的解析逻辑
        stock_sections = re.split(r'--- 开始回测股票: (.*?) ---', content)
        results = {}

        if len(stock_sections) < 2:
            return results

        for i in range(1, len(stock_sections), 2):
            stock_code = stock_sections[i].strip()
            section_content = stock_sections[i + 1]

            metrics = self._extract_metrics(section_content)
            if metrics:
                results[stock_code] = metrics

        return results

    def _extract_metrics(self, content: str) -> Dict[str, Any]:
        """从内容中提取关键指标"""
        metrics = {}
        patterns = {
            'final_value': r'回测结束后资金:\s*([\d\.,\-]+)',
            'max_drawdown': r'最大回撤:\s*([\d\.\-]+)%',
            'annualized_return': r'年化收益率:\s*([\d\.\-]+)%',
            'sharpe_ratio': r'夏普比率:\s*([\d\.\-]+)',
            'total_return': r'策略总收益率:\s*([\d\.\-]+)%',
            'alpha': r'超额收益:\s*([\d\.\-]+)%',
            'trade_count': r'总交易次数:\s*(\d+)',
            'win_trades': r'盈利交易数:\s*(\d+)',
            'win_rate': r'胜率:\s*([\d\.\-]+)%',
            'max_trade_return': r'最大单笔收益率:\s*([\d\.\-]+)%',
            'min_trade_return': r'最小单笔收益率:\s*([\d\.\-]+)%',
            'stock_name': r'股票名称:\s*(.*)'
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                try:
                    value = float(match.group(1).replace(',', ''))
                    metrics[key] = value
                except (ValueError, AttributeError):
                    metrics[key] = 'N/A'
            else:
                metrics[key] = 'N/A'

        return metrics

    def generate_comprehensive_report(self, config: Dict[str, Any],
                                    parameter_combinations: List[Dict[str, Any]]) -> str:
        """生成综合对比报告"""
        self.parameter_combinations = parameter_combinations

        report_lines = []
        report_lines.append(f"# {config['experiment_name']} - 参数优化报告")
        report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**实验描述**: {config.get('description', 'N/A')}")
        report_lines.append(f"**参数组合数量**: {len(parameter_combinations)}")
        report_lines.append(f"**股票池**: {', '.join(config['backtest_config']['stock_pool'])}")

        time_range = config['backtest_config']['time_range']
        report_lines.append(f"**回测时间范围**: {time_range['start_date']} 至 {time_range['end_date']}")

        # 1. 执行摘要
        report_lines.append("\n## 1. 执行摘要")
        best_combo = self._find_best_combination()
        if best_combo:
            report_lines.append(f"\n**推荐参数组合**: {best_combo['name']}")
            report_lines.append(f"**推荐理由**: {best_combo['reason']}")
            report_lines.append(f"**关键指标**:")
            for metric, value in best_combo['key_metrics'].items():
                report_lines.append(f"- {metric}: {value}")

        # 2. 详细对比表
        report_lines.append("\n## 2. 详细对比表")
        comparison_table = self._generate_comparison_table()
        report_lines.append(comparison_table)

        # 3. 参数敏感性分析
        if config.get('analysis_config', {}).get('enable_sensitivity_analysis', False):
            report_lines.append("\n## 3. 参数敏感性分析")
            sensitivity_analysis = self._generate_sensitivity_analysis()
            report_lines.append(sensitivity_analysis)

        # 4. 稳定性分析
        if config.get('analysis_config', {}).get('enable_stability_analysis', False):
            report_lines.append("\n## 4. 稳定性分析")
            stability_analysis = self._generate_stability_analysis()
            report_lines.append(stability_analysis)

        # 5. 风险分析
        if config.get('analysis_config', {}).get('enable_risk_analysis', False):
            report_lines.append("\n## 5. 风险分析")
            risk_analysis = self._generate_risk_analysis()
            report_lines.append(risk_analysis)

        # 附录：按参数组合的每只股票统计表
        report_lines.append("\n## 附录：每只股票统计表（按参数组合）")
        appendix = self._generate_per_stock_stats_by_combo(config)
        report_lines.append(appendix if isinstance(appendix, str) else ('' if appendix is None else str(appendix)))

        # 保底：确保所有元素为字符串
        report_lines = [x if isinstance(x, str) else ('' if x is None else str(x)) for x in report_lines]
        return '\n'.join(report_lines)

    def _find_best_combination(self) -> Dict[str, Any]:
        """找到最佳参数组合"""
        if not self.results_data:
            return None

        # 计算每个组合的综合评分
        combo_scores = {}

        for combo_name, combo_results in self.results_data.items():
            # 计算平均指标
            avg_metrics = self._calculate_average_metrics(combo_results)

            # 综合评分算法（可以根据需要调整权重）
            score = 0
            if avg_metrics.get('annualized_return', 'N/A') != 'N/A':
                score += avg_metrics['annualized_return'] * 0.4  # 年化收益权重40%
            if avg_metrics.get('sharpe_ratio', 'N/A') != 'N/A':
                score += avg_metrics['sharpe_ratio'] * 10 * 0.3  # 夏普比率权重30%
            if avg_metrics.get('max_drawdown', 'N/A') != 'N/A':
                score -= abs(avg_metrics['max_drawdown']) * 0.3  # 最大回撤权重30%（负向）

            combo_scores[combo_name] = {
                'score': score,
                'metrics': avg_metrics
            }

        # 找到最高分的组合
        if not combo_scores:
            return None

        best_combo_name = max(combo_scores.keys(), key=lambda x: combo_scores[x]['score'])
        best_metrics = combo_scores[best_combo_name]['metrics']

        return {
            'name': best_combo_name,
            'reason': f"综合评分最高 ({combo_scores[best_combo_name]['score']:.2f})",
            'key_metrics': {
                '年化收益率': f"{best_metrics.get('annualized_return', 'N/A'):.2f}%" if best_metrics.get('annualized_return') != 'N/A' else 'N/A',
                '夏普比率': f"{best_metrics.get('sharpe_ratio', 'N/A'):.2f}" if best_metrics.get('sharpe_ratio') != 'N/A' else 'N/A',
                '最大回撤': f"{best_metrics.get('max_drawdown', 'N/A'):.2f}%" if best_metrics.get('max_drawdown') != 'N/A' else 'N/A'
            }
        }

    def _calculate_average_metrics(self, combo_results: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
        """计算组合的平均指标"""
        metrics_sum = {}
        valid_count = {}

        for stock_code, stock_metrics in combo_results.items():
            for metric, value in stock_metrics.items():
                if value != 'N/A' and isinstance(value, (int, float)):
                    if metric not in metrics_sum:
                        metrics_sum[metric] = 0
                        valid_count[metric] = 0
                    metrics_sum[metric] += value
                    valid_count[metric] += 1

        # 计算平均值
        avg_metrics = {}
        for metric in metrics_sum:
            if valid_count[metric] > 0:
                avg_metrics[metric] = metrics_sum[metric] / valid_count[metric]
            else:
                avg_metrics[metric] = 'N/A'

        return avg_metrics

    def _generate_comparison_table(self) -> str:
        """生成对比表格"""
        if not self.results_data:
            return "无可用数据生成对比表格"

        # 准备表格数据
        table_data = []

        for combo_name, combo_results in self.results_data.items():
            avg_metrics = self._calculate_average_metrics(combo_results)

            row = {
                '参数组合': combo_name,
                '年化收益率(%)': f"{avg_metrics.get('annualized_return', 'N/A'):.2f}" if avg_metrics.get('annualized_return') != 'N/A' else 'N/A',
                '夏普比率': f"{avg_metrics.get('sharpe_ratio', 'N/A'):.2f}" if avg_metrics.get('sharpe_ratio') != 'N/A' else 'N/A',
                '最大回撤(%)': f"{avg_metrics.get('max_drawdown', 'N/A'):.2f}" if avg_metrics.get('max_drawdown') != 'N/A' else 'N/A',
                '总收益率(%)': f"{avg_metrics.get('total_return', 'N/A'):.2f}" if avg_metrics.get('total_return') != 'N/A' else 'N/A',
                '超额收益(%)': f"{avg_metrics.get('alpha', 'N/A'):.2f}" if avg_metrics.get('alpha') != 'N/A' else 'N/A'
            }
            table_data.append(row)

        # 转换为DataFrame并生成Markdown表格
        df = pd.DataFrame(table_data)

        # 按年化收益率排序
        try:
            df['年化收益率_数值'] = pd.to_numeric(df['年化收益率(%)'], errors='coerce')
            df = df.sort_values('年化收益率_数值', ascending=False, na_position='last')
            df = df.drop('年化收益率_数值', axis=1)
        except:
            pass

        return df.to_markdown(index=False)

    def _generate_per_stock_stats(self, config: Dict[str, Any]) -> str:
        """汇总每只股票跨参数组合的统计数据表。
        字段：最大收益、最小收益（亏损）、盈利交易数、总交易数、成功率（盈利/总数）、超额收益率（平均）。
        同时附加：平均年化收益率、平均最大回撤（辅助判断稳定性）。
        """
        if not self.results_data:
            return "无可用数据生成每只股票统计表"

        # 聚合每只股票
        per_stock = {}
        for combo_name, combo_results in self.results_data.items():
            for stock, metrics in combo_results.items():
                s = per_stock.setdefault(stock, {
                    'max_trade_return_list': [],
                    'min_trade_return_list': [],
                    'win_trades': 0,
                    'total_trades': 0,
                    'alpha_list': [],
                    'annualized_return_list': [],
                    'max_drawdown_list': [],
                })
                # 交易统计
                if isinstance(metrics.get('win_trades'), (int, float)):
                    s['win_trades'] += int(metrics['win_trades'])
                if isinstance(metrics.get('trade_count'), (int, float)):
                    s['total_trades'] += int(metrics['trade_count'])
                # 单笔收益率
                if isinstance(metrics.get('max_trade_return'), (int, float)):
                    s['max_trade_return_list'].append(metrics['max_trade_return'])
                if isinstance(metrics.get('min_trade_return'), (int, float)):
                    s['min_trade_return_list'].append(metrics['min_trade_return'])
                # 超额收益、年化、回撤
                if isinstance(metrics.get('alpha'), (int, float)):
                    s['alpha_list'].append(metrics['alpha'])
                if isinstance(metrics.get('annualized_return'), (int, float)):
                    s['annualized_return_list'].append(metrics['annualized_return'])
                if isinstance(metrics.get('max_drawdown'), (int, float)):
                    s['max_drawdown_list'].append(metrics['max_drawdown'])

        # 形成表格
        rows = []
        for stock, agg in per_stock.items():
            max_ret = max(agg['max_trade_return_list']) if agg['max_trade_return_list'] else None
            min_ret = min(agg['min_trade_return_list']) if agg['min_trade_return_list'] else None
            win = agg['win_trades']
            total = agg['total_trades']
            win_rate = (win / total * 100.0) if total > 0 else None
            avg_alpha = np.mean(agg['alpha_list']) if agg['alpha_list'] else None
            avg_ann = np.mean(agg['annualized_return_list']) if agg['annualized_return_list'] else None
            avg_dd = np.mean(agg['max_drawdown_list']) if agg['max_drawdown_list'] else None
            rows.append({
                '股票代码': stock,
                '最大单笔收益(%)': f"{max_ret:.2f}" if max_ret is not None else 'N/A',
                '最小单笔收益(%)': f"{min_ret:.2f}" if min_ret is not None else 'N/A',
                '盈利交易数': win,
                '总交易数': total,
                '成功率(%)': f"{win_rate:.2f}" if win_rate is not None else 'N/A',
                '平均超额收益(%)': f"{avg_alpha:.2f}" if avg_alpha is not None else 'N/A',
                '平均年化收益(%)': f"{avg_ann:.2f}" if avg_ann is not None else 'N/A',
                '平均最大回撤(%)': f"{avg_dd:.2f}" if avg_dd is not None else 'N/A',
            })

        import pandas as pd
        df = pd.DataFrame(rows)
        # 排序：优先按成功率降序，然后平均超额收益降序
        try:
            df['成功率_num'] = pd.to_numeric(df['成功率(%)'], errors='coerce')
            df['平均超额_num'] = pd.to_numeric(df['平均超额收益(%)'], errors='coerce')
            df = df.sort_values(['成功率_num', '平均超额_num'], ascending=[False, False], na_position='last')
            df = df.drop(columns=['成功率_num', '平均超额_num'])
        except Exception:
            pass
        return df.to_markdown(index=False)
    def _generate_per_stock_stats_by_combo(self, config: Dict[str, Any]) -> str:
        """按参数组合分别生成每只股票统计表，追加股票名称列。
        输出结构：为每个参数组合生成一个小节和表格。
        """
        if not self.results_data:
            return "无可用数据生成附录"

        lines = []
        import pandas as pd

        # 遍历每个参数组合
        for combo_name, combo_results in self.results_data.items():
            rows = []
            for stock_code, metrics in combo_results.items():
                # 尝试从本地CSV文件名中解析股票名称
                stock_name = self._infer_stock_name(stock_code)
                # 取该组合对应股票的指标
                total_trades = metrics.get('trade_count') if isinstance(metrics.get('trade_count'), (int, float)) else None
                win_trades = metrics.get('win_trades') if isinstance(metrics.get('win_trades'), (int, float)) else None
                win_rate = None
                if isinstance(metrics.get('win_rate'), (int, float)):
                    win_rate = metrics.get('win_rate')
                elif total_trades not in (None, 0) and isinstance(win_trades, (int, float)):
                    win_rate = win_trades / total_trades * 100.0
                row = {
                    '股票代码': stock_code,
                    '股票名称': stock_name or '',
                    '最大单笔收益(%)': self._fmt(metrics.get('max_trade_return')),
                    '最小单笔收益(%)': self._fmt(metrics.get('min_trade_return')),
                    '盈利交易数': int(win_trades) if isinstance(win_trades, (int, float)) else 0,
                    '总交易数': int(total_trades) if isinstance(total_trades, (int, float)) else 0,
                    '成功率(%)': self._fmt(win_rate),
                    '超额收益(%)': self._fmt(metrics.get('alpha')),
                    '年化收益率(%)': self._fmt(metrics.get('annualized_return')),
                    '最大回撤(%)': self._fmt(metrics.get('max_drawdown')),
                }
                rows.append(row)
            df = pd.DataFrame(rows)
            # 按股票代码排序，便于对比
            try:
                df = df.sort_values('股票代码')
            except Exception:
                pass
            lines.append(f"\n### 参数组合：{combo_name}")
            lines.append(df.to_markdown(index=False))

        return '\n'.join(lines)
    def _infer_stock_name(self, stock_code: str) -> str | None:
        """从 data/astocks 目录中根据文件名推断股票名称。文件命名通常为 000001_平安银行.csv"""
        import os
        data_dir = os.path.join('data', 'astocks')
        try:
            for filename in os.listdir(data_dir):
                if filename.startswith(str(stock_code)) and filename.endswith('.csv'):
                    parts = filename.split('_', 1)
                    if len(parts) == 2:
                        return parts[1].rsplit('.', 1)[0]
                    break
        except Exception:
            return None
        return None

    @staticmethod
    def _fmt(v):
        if v is None or v == 'N/A':
            return 'N/A'
        try:
            return f"{float(v):.2f}"
        except Exception:
            return 'N/A'

    def _generate_sensitivity_analysis(self) -> str:
        """生成参数敏感性分析"""
        if not self.parameter_combinations:
            return "无参数组合数据，无法进行敏感性分析"

        # 这里实现参数敏感性分析的逻辑
        # 分析每个参数对结果的影响程度
        analysis_lines = []
        analysis_lines.append("\n### 参数影响力分析")
        analysis_lines.append("分析各参数对年化收益率的影响程度：")

        # 简化版本的敏感性分析
        param_impact = self._calculate_parameter_impact()

        if param_impact:
            analysis_lines.append("\n| 参数名称 | 影响程度 | 说明 |")
            analysis_lines.append("|---------|---------|------|")

            for param, impact in sorted(param_impact.items(), key=lambda x: x[1], reverse=True):
                impact_level = "高" if impact > 5 else "中" if impact > 2 else "低"
                analysis_lines.append(f"| {param} | {impact_level} ({impact:.2f}) | 该参数变化对收益率影响较{'大' if impact > 5 else '小'} |")
        else:
            analysis_lines.append("\n暂无足够数据进行参数敏感性分析")

        return '\n'.join(analysis_lines)

    def _calculate_parameter_impact(self) -> Dict[str, float]:
        """计算参数影响力（简化版本）"""
        # 这里实现简化的参数影响力计算
        # 实际应用中可以使用更复杂的统计方法
        param_impact = {}

        # 收集所有参数及其对应的收益率
        param_returns = {}

        for combo in self.parameter_combinations:
            combo_name = combo['name']
            if combo_name not in self.results_data:
                continue

            avg_metrics = self._calculate_average_metrics(self.results_data[combo_name])
            annual_return = avg_metrics.get('annualized_return')

            if annual_return == 'N/A':
                continue

            for param_name, param_value in combo['params'].items():
                if param_name not in param_returns:
                    param_returns[param_name] = []
                param_returns[param_name].append((param_value, annual_return))

        # 计算每个参数的影响力（使用标准差作为简单指标）
        for param_name, value_return_pairs in param_returns.items():
            if len(value_return_pairs) < 2:
                continue

            returns = [pair[1] for pair in value_return_pairs]
            impact = np.std(returns) if len(returns) > 1 else 0
            param_impact[param_name] = impact

        return param_impact

    def _generate_stability_analysis(self) -> str:
        """生成稳定性分析"""
        analysis_lines = []
        analysis_lines.append("\n### 不同股票表现一致性")

        # 计算每个参数组合在不同股票上的表现一致性
        consistency_scores = {}

        for combo_name, combo_results in self.results_data.items():
            returns = []
            for stock_code, metrics in combo_results.items():
                if metrics.get('annualized_return') != 'N/A':
                    returns.append(metrics['annualized_return'])

            if len(returns) > 1:
                # 使用变异系数衡量一致性（标准差/均值）
                mean_return = np.mean(returns)
                std_return = np.std(returns)
                cv = std_return / abs(mean_return) if mean_return != 0 else float('inf')
                consistency_scores[combo_name] = cv

        if consistency_scores:
            # 找到最稳定的组合（变异系数最小）
            most_stable = min(consistency_scores.keys(), key=lambda x: consistency_scores[x])
            analysis_lines.append(f"\n**最稳定的参数组合**: {most_stable}")
            analysis_lines.append(f"**变异系数**: {consistency_scores[most_stable]:.3f}")
            analysis_lines.append("\n变异系数越小表示在不同股票上的表现越一致")
        else:
            analysis_lines.append("\n暂无足够数据进行稳定性分析")

        return '\n'.join(analysis_lines)

    def _generate_risk_analysis(self) -> str:
        """生成风险分析"""
        analysis_lines = []
        analysis_lines.append("\n### 风险收益权衡分析")

        # 计算风险调整后收益
        risk_adjusted_scores = {}

        for combo_name, combo_results in self.results_data.items():
            avg_metrics = self._calculate_average_metrics(combo_results)

            annual_return = avg_metrics.get('annualized_return')
            max_drawdown = avg_metrics.get('max_drawdown')

            if annual_return != 'N/A' and max_drawdown != 'N/A':
                # 简单的风险调整收益 = 年化收益率 / 最大回撤
                risk_adjusted_return = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0
                risk_adjusted_scores[combo_name] = risk_adjusted_return

        if risk_adjusted_scores:
            # 找到风险调整后收益最高的组合
            best_risk_adjusted = max(risk_adjusted_scores.keys(), key=lambda x: risk_adjusted_scores[x])
            analysis_lines.append(f"\n**最佳风险调整收益组合**: {best_risk_adjusted}")
            analysis_lines.append(f"**风险调整收益**: {risk_adjusted_scores[best_risk_adjusted]:.3f}")
            analysis_lines.append("\n风险调整收益 = 年化收益率 / 最大回撤，数值越高越好")
        else:
            analysis_lines.append("\n暂无足够数据进行风险分析")

        return '\n'.join(analysis_lines)


if __name__ == '__main__':
    # 测试代码
    analyzer = MultiComparisonAnalyzer("bin/post_analysis")
    print("多维对比分析器初始化完成")
