"""
参数优化器主控制器
协调整个参数优化流程，包括配置管理、批量回测、结果分析等
"""

import os
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any
import logging
from pathlib import Path

from bin.config_manager import ConfigManager
from bin.multi_comparison_analyzer import MultiComparisonAnalyzer
from bin.experiment_runner import run_batch_backtest
from strategy.breakout_strategy import BreakoutStrategy


class ParameterOptimizer:
    """参数优化器主控制器"""

    def __init__(self, base_dir: str = "bin"):
        self.base_dir = base_dir
        self.config_manager = ConfigManager(os.path.join(base_dir, "optimization_configs"))
        self.results_base_dir = os.path.join(base_dir, "optimization_results")
        self.cache_dir = os.path.join(base_dir, "optimization_cache")

        # 确保目录存在
        os.makedirs(self.results_base_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        # 延迟日志初始化，避免无意义的空日志文件
        self.logger = logging.getLogger(__name__)
        self._file_handler = None

    def _setup_logging(self):
        """设置日志配置（在真正运行优化时再初始化文件日志）。"""
        if self._file_handler is not None:
            # 已经设置过文件日志
            return
        log_dir = os.path.join(self.base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, f"parameter_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        # 使用 delay=True，只有首次写入日志时才创建文件，避免空日志
        file_handler = logging.FileHandler(log_file, encoding='utf-8', delay=True)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.INFO)
        self._file_handler = file_handler

    def run_optimization(self, config_path: str) -> str:
        """运行完整的参数优化流程"""
        self.logger.info(f"开始参数优化流程，配置文件: {config_path}")

        try:
            # 初始化日志（延迟到真正运行时）
            self._setup_logging()

            # 1. 加载配置
            config = self.config_manager.load_config(config_path)
            self.logger.info(f"配置加载成功: {config['experiment_name']}")

            # 2. 生成参数组合
            parameter_combinations = self.config_manager.generate_parameter_combinations(config)
            self.logger.info(f"生成了 {len(parameter_combinations)} 个参数组合")

            # 3. 创建结果目录
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            experiment_dir = os.path.join(self.results_base_dir, f"{config['experiment_name']}_{timestamp}")
            os.makedirs(experiment_dir, exist_ok=True)

            # 4. 批量回测
            result_files = self._run_batch_backtests(config, parameter_combinations, experiment_dir)

            # 5. 生成对比报告
            report_path = self._generate_comparison_report(config, parameter_combinations, result_files, experiment_dir)

            self.logger.info(f"参数优化完成！报告保存在: {report_path}")
            return report_path

        except Exception as e:
            self.logger.error(f"参数优化过程中发生错误: {e}", exc_info=True)
            raise

    def _run_batch_backtests(self, config: Dict[str, Any],
                           parameter_combinations: List[Dict[str, Any]],
                           experiment_dir: str) -> List[str]:
        """运行批量回测"""
        self.logger.info("开始批量回测...")

        backtest_config = config['backtest_config']
        stock_pool = backtest_config['stock_pool']
        time_range = backtest_config['time_range']
        initial_amount = backtest_config.get('initial_amount', 100000)

        # 转换日期格式
        start_date = datetime.strptime(time_range['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(time_range['end_date'], '%Y-%m-%d')

        result_files = []

        for i, combo in enumerate(parameter_combinations, 1):
            self.logger.info(f"[{i}/{len(parameter_combinations)}] 回测参数组合: {combo['name']}")

            # 检查缓存
            cache_key = self._generate_cache_key(combo, stock_pool, time_range)
            cached_result = self._get_cached_result(cache_key)

            # 生成结果文件路径
            result_file = os.path.join(experiment_dir, f"backtest_{combo['name']}.txt")

            if cached_result:
                self.logger.info(f"使用缓存结果: {combo['name']}")
                # 复制缓存文件到当前实验目录，使用正确的文件名
                import shutil
                shutil.copy2(cached_result, result_file)
                result_files.append(result_file)
                continue

            # 合并参数（自定义参数 + 默认参数）
            merged_params = self.config_manager.merge_with_defaults(combo['params'])

            try:
                # 运行回测
                run_batch_backtest(
                    strategy_class=BreakoutStrategy,
                    strategy_params=merged_params,
                    stock_codes=stock_pool,
                    summary_filepath=result_file,
                    startdate=start_date,
                    enddate=end_date,
                    amount=initial_amount
                )

                result_files.append(result_file)

                # 缓存结果
                self._cache_result(cache_key, result_file)

                self.logger.info(f"参数组合 {combo['name']} 回测完成")

            except Exception as e:
                self.logger.error(f"参数组合 {combo['name']} 回测失败: {e}")
                continue

        self.logger.info(f"批量回测完成，成功 {len(result_files)} 个，失败 {len(parameter_combinations) - len(result_files)} 个")
        return result_files

    def _generate_cache_key(self, combo: Dict[str, Any], stock_pool: List[str], time_range: Dict[str, str]) -> str:
        """生成缓存键"""
        cache_data = {
            'params': combo['params'],
            'stock_pool': sorted(stock_pool),
            'time_range': time_range
        }

        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> str:
        """获取缓存结果"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.txt")
        if os.path.exists(cache_file):
            return cache_file
        return None

    def _cache_result(self, cache_key: str, result_file: str):
        """缓存结果"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.txt")
        try:
            # 复制结果文件到缓存目录
            import shutil
            shutil.copy2(result_file, cache_file)
        except Exception as e:
            self.logger.warning(f"缓存结果失败: {e}")

    def _generate_comparison_report(self, config: Dict[str, Any],
                                  parameter_combinations: List[Dict[str, Any]],
                                  result_files: List[str],
                                  experiment_dir: str) -> str:
        """生成对比报告"""
        self.logger.info("开始生成对比报告...")

        # 创建分析器
        analyzer = MultiComparisonAnalyzer(experiment_dir)

        # 解析所有结果，并传递参数组合信息以便正确映射名称
        analyzer.parse_all_results(result_files, parameter_combinations)

        # 生成综合报告
        report_content = analyzer.generate_comprehensive_report(config, parameter_combinations)

        # 保存报告
        report_file = os.path.join(experiment_dir, f"{config['experiment_name']}_optimization_report.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)

        # 如果配置了生成Excel报告
        if config.get('output_config', {}).get('generate_excel_report', False):
            excel_file = self._generate_excel_report(analyzer, experiment_dir, config['experiment_name'])
            self.logger.info(f"Excel报告已生成: {excel_file}")

        self.logger.info(f"对比报告生成完成: {report_file}")
        return report_file

    def _generate_excel_report(self, analyzer: MultiComparisonAnalyzer,
                             experiment_dir: str, experiment_name: str) -> str:
        """生成Excel格式的详细报告"""
        try:
            import pandas as pd

            excel_file = os.path.join(experiment_dir, f"{experiment_name}_detailed_results.xlsx")

            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                # 汇总表
                summary_data = []
                for combo_name, combo_results in analyzer.results_data.items():
                    avg_metrics = analyzer._calculate_average_metrics(combo_results)
                    summary_data.append({
                        '参数组合': combo_name,
                        **avg_metrics
                    })

                if summary_data:
                    summary_df = pd.DataFrame(summary_data)
                    summary_df.to_excel(writer, sheet_name='汇总', index=False)

                # 详细数据表
                for combo_name, combo_results in analyzer.results_data.items():
                    detail_data = []
                    for stock_code, metrics in combo_results.items():
                        detail_data.append({
                            '股票代码': stock_code,
                            **metrics
                        })

                    if detail_data:
                        detail_df = pd.DataFrame(detail_data)
                        # Excel工作表名称长度限制
                        sheet_name = combo_name[:30] if len(combo_name) > 30 else combo_name
                        detail_df.to_excel(writer, sheet_name=sheet_name, index=False)

            return excel_file

        except ImportError:
            self.logger.warning("pandas或openpyxl未安装，跳过Excel报告生成")
            return None
        except Exception as e:
            self.logger.error(f"生成Excel报告失败: {e}")
            return None

    def generate_config_template(self, template_type: str = "default",
                                strategy_class=None,
                                test_params: list = None,
                                step_percent: float = 0.1,
                                num_points: int = 4) -> str:
        """生成配置模板

        Args:
            template_type: 模板类型 ("default", "quick", "grid")
            strategy_class: 策略类，用于提取默认参数值（grid模式时使用）
            test_params: 要测试的参数名列表（grid模式时使用）
            step_percent: 步长百分比，默认0.1（10%）
            num_points: 测试点数量，quick/default=2，grid时使用传入值
        """
        # 根据模板类型调整参数
        if template_type == "quick":
            actual_num_points = 2  # quick固定2个参数组合
        else:
            actual_num_points = num_points

        # 如果提供了策略类和参数，使用自动生成（grid和quick都支持）
        if template_type in ["grid", "quick"] and strategy_class and test_params:
            return self._generate_auto_template(strategy_class, test_params, step_percent, actual_num_points, template_type)

        # 传统模式（只有default使用）
        if template_type == "quick":
            template_name = "quick_test_config.yaml"
        elif template_type == "grid":
            template_name = "grid_search_config.yaml"
        else:
            template_name = "default_config.yaml"

        template_path = self.config_manager.generate_default_template(template_name)

        # 如果是网格搜索模板，修改配置
        if template_type == "grid":
            self._customize_grid_template(template_path)
        elif template_type == "quick":
            self._customize_quick_template(template_path)

        return template_path

    def _generate_auto_template(self, strategy_class, test_params: list,
                               step_percent: float, num_points: int, template_type: str) -> str:
        """自动生成基于策略参数的配置模板"""
        import yaml

        # 提取策略默认参数
        default_params = self._extract_strategy_defaults(strategy_class)

        # 生成测试参数
        if template_type == "grid":
            # grid模式：生成网格搜索配置
            grid_config = {}
            for param_name in test_params:
                if param_name not in default_params:
                    raise ValueError(f"参数 '{param_name}' 在策略 {strategy_class.__name__} 中不存在")

                default_value = default_params[param_name]
                test_values = self._generate_test_values(default_value, step_percent, num_points)
                grid_config[param_name] = test_values

            config_content = {
                'experiment_name': f'{strategy_class.__name__.lower()}_grid_search',
                'description': f'自动生成的{strategy_class.__name__}网格搜索配置',

                'backtest_config': {
                    'stock_pool': ['300033', '300059', '000062'],
                    'stock_pool_inline': '300033,300059,000062',
                    'time_range': {
                        'start_date': '2024-01-01',
                        'end_date': '2025-08-22'
                    },
                    'initial_amount': 100000
                },

                'parameter_strategy': {
                    'type': 'grid_search',
                    'max_combinations': 100
                },

                'parameter_sets': {
                    'grid_search': grid_config
                },

                'analysis_config': {
                    'enable_sensitivity_analysis': True,
                    'enable_stability_analysis': True,
                    'enable_risk_analysis': True
                },

                'output_config': {
                    'generate_markdown_report': True,
                    'generate_excel_report': False,
                    'generate_charts': False
                }
            }
            template_name = "grid_search_config.yaml"

        elif template_type == "quick":
            # quick模式：生成2个manual_sets参数组合
            manual_sets = []

            # 生成第一个组合（默认值）
            baseline_params = {}
            for param_name in test_params:
                if param_name not in default_params:
                    raise ValueError(f"参数 '{param_name}' 在策略 {strategy_class.__name__} 中不存在")
                baseline_params[param_name] = default_params[param_name]

            manual_sets.append({
                'name': 'baseline',
                'description': '基准参数（默认值）',
                'params': baseline_params
            })

            # 生成第二个组合（调整后的值）
            adjusted_params = {}
            for param_name in test_params:
                default_value = default_params[param_name]
                test_values = self._generate_test_values(default_value, step_percent, 3)  # 生成3个值
                # 选择非默认值作为调整参数
                adjusted_value = test_values[1] if len(test_values) > 1 and test_values[1] != default_value else test_values[-1]
                adjusted_params[param_name] = adjusted_value

            manual_sets.append({
                'name': 'adjusted',
                'description': '调整参数',
                'params': adjusted_params
            })

            config_content = {
                'experiment_name': f'{strategy_class.__name__.lower()}_quick_test',
                'description': f'自动生成的{strategy_class.__name__}快速测试配置',

                'backtest_config': {
                    'stock_pool': ['300033', '300059'],
                    'stock_pool_inline': '300033,300059',
                    'time_range': {
                        'start_date': '2024-01-01',
                        'end_date': '2025-08-22'
                    },
                    'initial_amount': 100000
                },

                'parameter_strategy': {
                    'type': 'manual',
                    'max_combinations': 2
                },

                'parameter_sets': {
                    'manual_sets': manual_sets
                },

                'analysis_config': {
                    'enable_sensitivity_analysis': True,
                    'enable_stability_analysis': True,
                    'enable_risk_analysis': True
                },

                'output_config': {
                    'generate_markdown_report': True,
                    'generate_excel_report': False,
                    'generate_charts': False
                }
            }
            template_name = "quick_test_config.yaml"

        # 保存配置文件
        template_path = os.path.join(self.config_manager.config_dir, template_name)

        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_content, f, default_flow_style=False,
                     allow_unicode=True, indent=2)

        return template_path

    def _extract_strategy_defaults(self, strategy_class) -> dict:
        """从策略类中提取默认参数值"""
        defaults = {}

        # 方法1: 尝试从源代码中解析params
        try:
            import inspect
            import ast

            source = inspect.getsource(strategy_class)
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == 'params':
                            if isinstance(node.value, ast.Tuple):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                                        if isinstance(elt.elts[0], ast.Constant):
                                            param_name = elt.elts[0].value
                                            if isinstance(elt.elts[1], ast.Constant):
                                                default_value = elt.elts[1].value
                                                defaults[param_name] = default_value

            if defaults:
                return defaults

        except Exception as e:
            print(f"从源代码解析参数失败: {e}")

        # 方法2: 尝试访问backtrader的params对象
        try:
            if hasattr(strategy_class, 'params'):
                params_obj = strategy_class.params
                # 尝试获取参数名和默认值
                for attr_name in dir(params_obj):
                    if not attr_name.startswith('_'):
                        try:
                            default_value = getattr(params_obj, attr_name)
                            defaults[attr_name] = default_value
                        except:
                            pass
        except Exception as e:
            print(f"从backtrader params对象解析参数失败: {e}")

        return defaults

    def _generate_test_values(self, default_value, step_percent: float, num_points: int) -> list:
        """围绕默认值生成测试值

        Args:
            default_value: 默认值
            step_percent: 步长百分比（如0.1表示10%）
            num_points: 测试点数量

        Returns:
            测试值列表，例如：[默认值, +10%, -10%, +20%]
        """
        if not isinstance(default_value, (int, float)):
            # 对于非数值参数，只返回默认值
            return [default_value]

        test_values = [default_value]  # 总是包含默认值

        # 生成正负梯度值
        for i in range(1, (num_points + 1) // 2 + 1):
            step = step_percent * i

            # 正向步长
            if len(test_values) < num_points:
                pos_value = default_value * (1 + step)
                # 对于整数参数，保持整数
                if isinstance(default_value, int):
                    pos_value = int(round(pos_value))
                else:
                    # 浮点数保留2位小数
                    pos_value = round(pos_value, 2)
                test_values.append(pos_value)

            # 负向步长
            if len(test_values) < num_points:
                neg_value = default_value * (1 - step)
                # 确保不为负数（对于大多数策略参数）
                if neg_value > 0:
                    if isinstance(default_value, int):
                        neg_value = int(round(neg_value))
                    else:
                        # 浮点数保留2位小数
                        neg_value = round(neg_value, 2)
                    test_values.append(neg_value)

        # 去重并排序
        test_values = sorted(list(set(test_values)))
        return test_values

    def _customize_grid_template(self, template_path: str):
        """自定义网格搜索模板"""
        import yaml

        with open(template_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 修改为网格搜索配置
        config['experiment_name'] = 'breakout_strategy_grid_search'
        config['parameter_strategy']['type'] = 'grid_search'
        config['parameter_strategy']['max_combinations'] = 27  # 3x3x3

        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)

    def _customize_quick_template(self, template_path: str):
        """自定义快速测试模板"""
        import yaml

        with open(template_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 修改为快速测试配置
        config['experiment_name'] = 'breakout_strategy_quick_test'
        # 只测试2只股票；为保证新老两种stock_pool格式一致，这里同步设置两者
        config['backtest_config']['stock_pool'] = ['300033', '300059']
        config['backtest_config']['stock_pool_inline'] = '300033,300059'
        config['backtest_config']['time_range']['start_date'] = '2024-01-01'  # 缩短时间范围

        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)

    def list_cached_results(self) -> List[str]:
        """列出所有缓存的结果"""
        if not os.path.exists(self.cache_dir):
            return []

        cache_files = [f for f in os.listdir(self.cache_dir) if f.endswith('.txt')]
        return cache_files

    def clear_cache(self):
        """清空缓存"""
        if os.path.exists(self.cache_dir):
            import shutil
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir, exist_ok=True)
            self.logger.info("缓存已清空")


if __name__ == '__main__':
    # 测试代码
    optimizer = ParameterOptimizer()

    # 生成默认配置模板
    template_path = optimizer.generate_config_template("default")
    print(f"配置模板已生成: {template_path}")

    # 运行优化（需要先编辑配置文件）
    # result_path = optimizer.run_optimization(template_path)
    # print(f"优化完成，报告: {result_path}")
