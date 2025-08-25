"""
参数优化配置管理器
负责解析YAML配置文件、参数验证、组合生成等功能
"""

import os
import yaml
import itertools
from datetime import datetime
from typing import Dict, List, Any, Tuple
import logging


class ConfigManager:
    """参数优化配置管理器"""

    def __init__(self, config_dir: str = "bin/optimization_configs"):
        self.config_dir = config_dir
        self.ensure_config_dir()

    def ensure_config_dir(self):
        """确保配置目录存在"""
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(os.path.join(self.config_dir, "user_configs"), exist_ok=True)

    def generate_default_template(self, template_name: str = "default_config.yaml") -> str:
        """生成默认配置模板"""
        template_content = {
            'experiment_name': 'breakout_strategy_optimization',
            'description': 'BreakoutStrategy参数优化实验',

            'backtest_config': {
                'stock_pool': ['300033', '300059', '000062', '300204', '600610'],
                # 新增单行字符串形式，和列表形式不冲突，运行时会合并去重
                'stock_pool_inline': '300033,300059,000062,300204,600610',
                'time_range': {
                    'start_date': '2022-01-01',
                    'end_date': '2025-07-04'
                },
                'initial_amount': 100000
            },

            'parameter_strategy': {
                'type': 'manual',  # manual | grid_search | random_search
                'max_combinations': 20
            },

            'parameter_sets': {
                'manual_sets': [
                    {
                        'name': 'baseline',
                        'description': '基准参数',
                        'params': {
                            'debug': False,
                            'bband_period': 20,
                            'atr_multiplier': 2.0,
                            'volume_ma_period': 20
                        }
                    },
                    {
                        'name': 'aggressive',
                        'description': '激进参数',
                        'params': {
                            'debug': False,
                            'bband_period': 15,
                            'atr_multiplier': 2.5,
                            'volume_ma_period': 15
                        }
                    }
                ],

                'grid_search': {
                    'bband_period': [15, 20, 25],
                    'atr_multiplier': [1.5, 2.0, 2.5],
                    'volume_ma_period': [15, 20, 25]
                }
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

        template_path = os.path.join(self.config_dir, template_name)
        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(template_content, f, default_flow_style=False,
                     allow_unicode=True, indent=2)

        return template_path

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        # 读取原始文件内容并预处理，避免YAML八进制解析问题
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()

        # 预处理：在stock_pool部分的数字前后加引号，避免YAML八进制解析
        import re

        # 只在stock_pool部分进行替换
        lines = raw_content.split('\n')
        in_stock_pool = False
        processed_lines = []

        for line in lines:
            if 'stock_pool:' in line:
                in_stock_pool = True
                processed_lines.append(line)
            elif in_stock_pool and line.strip() and not line.startswith(' ') and not line.startswith('-'):
                # 离开stock_pool部分
                in_stock_pool = False
                processed_lines.append(line)
            elif in_stock_pool and re.match(r'^\s*-\s*\d+\s*$', line):
                # 在stock_pool中的数字项，添加引号
                processed_line = re.sub(r'(\s*-\s*)(\d+)(\s*)$', r'\1"\2"\3', line)
                processed_lines.append(processed_line)
            else:
                processed_lines.append(line)

        processed_content = '\n'.join(processed_lines)

        # 解析处理后的YAML内容
        config = yaml.safe_load(processed_content)

        # 规范化/合并股票池配置，支持列表和逗号分隔字符串两种形式
        self._normalize_backtest_config(config)

        # 验证配置
        self._validate_config(config)
        return config
    def _normalize_backtest_config(self, config: Dict[str, Any]) -> None:
        """支持 stock_pool 同时从列表和逗号分隔字符串合并，去重并保持顺序。
        允许以下几种写法：
        backtest_config.stock_pool: ["300033", "300059"]
        backtest_config.stock_pool: "300033,300059,000062"
        backtest_config.stock_pool_inline: "300033,300059,000062"
        三者会合并去重为最终的 stock_pool(list[str])。
        """
        bt = config.get('backtest_config', {})
        list_part = bt.get('stock_pool', [])
        inline1 = bt.get('stock_pool_inline')
        inline2 = None

        # 兼容旧字段名：如果用户直接把字符串给到 stock_pool，我们也能识别
        if isinstance(list_part, str):
            inline2 = list_part
            list_part = []

        # 收集所有来源
        parts: List[str] = []
        if isinstance(list_part, list):
            parts.extend([str(x).strip() for x in list_part if str(x).strip()])
        if isinstance(inline1, str) and inline1.strip():
            parts.extend([p.strip() for p in inline1.split(',') if p.strip()])
        if isinstance(inline2, str) and inline2.strip():
            parts.extend([p.strip() for p in inline2.split(',') if p.strip()])

        # 规范化：只保留数字，左侧补零到6位
        def norm(code: str) -> str:
            c = ''.join(ch for ch in code if ch.isdigit())
            return c.zfill(6) if c else ''

        normalized = [norm(p) for p in parts]
        normalized = [p for p in normalized if p]

        # 去重且保持首次出现顺序
        seen = set()
        deduped: List[str] = []
        for c in normalized:
            if c not in seen:
                seen.add(c)
                deduped.append(c)

        bt['stock_pool'] = deduped
        config['backtest_config'] = bt


    def _validate_config(self, config: Dict[str, Any]):
        """验证配置文件格式"""
        # 基础必需字段
        required_keys = ['experiment_name', 'backtest_config']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"配置文件缺少必需字段: {key}")

        # 验证回测配置
        backtest_config = config['backtest_config']
        if 'stock_pool' not in backtest_config or not backtest_config['stock_pool']:
            raise ValueError("stock_pool不能为空")

        if 'time_range' not in backtest_config:
            raise ValueError("缺少time_range配置")

        # 验证参数策略配置
        strategy_type = config.get('parameter_strategy', {}).get('type', 'manual')

        if strategy_type == 'param_files':
            # param_files 类型需要 param_files 字段
            if 'param_files' not in config.get('parameter_strategy', {}):
                raise ValueError("param_files策略需要param_files配置")
        else:
            # 其他类型需要 parameter_sets 字段
            if 'parameter_sets' not in config:
                raise ValueError(f"配置文件缺少必需字段: parameter_sets")

            param_sets = config['parameter_sets']
            if strategy_type == 'manual' and 'manual_sets' not in param_sets:
                raise ValueError("manual策略需要manual_sets配置")
            elif strategy_type == 'grid_search' and 'grid_search' not in param_sets:
                raise ValueError("grid_search策略需要grid_search配置")

    def generate_parameter_combinations(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """根据配置生成参数组合"""
        strategy_type = config.get('parameter_strategy', {}).get('type', 'manual')
        max_combinations = config.get('parameter_strategy', {}).get('max_combinations', 50)

        if strategy_type == 'manual':
            return self._generate_manual_combinations(config)
        elif strategy_type == 'grid_search':
            return self._generate_grid_combinations(config, max_combinations)
        elif strategy_type == 'param_files':
            return self._generate_param_files_combinations(config)
        else:
            raise ValueError(f"不支持的参数策略: {strategy_type}")

    def _generate_manual_combinations(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成手动定义的参数组合"""
        manual_sets = config['parameter_sets']['manual_sets']
        combinations = []

        for param_set in manual_sets:
            combination = {
                'name': param_set['name'],
                'description': param_set.get('description', ''),
                'params': param_set['params']
            }
            combinations.append(combination)

        return combinations

    def _generate_param_files_combinations(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从参数文件生成参数组合"""
        import importlib.util
        import os

        param_files = config['parameter_strategy']['param_files']
        combinations = []

        for i, param_file in enumerate(param_files):
            if not os.path.exists(param_file):
                raise FileNotFoundError(f"参数文件不存在: {param_file}")

            # 动态导入参数文件
            spec = importlib.util.spec_from_file_location(f"params_{i}", param_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 提取参数
            if hasattr(module, 'params'):
                params_tuple = module.params
                # 将元组转换为字典
                params_dict = dict(params_tuple)

                # 生成参数组合名称
                file_name = os.path.splitext(os.path.basename(param_file))[0]
                # 简化名称生成逻辑
                if 'v2' in file_name.lower():
                    combo_name = 'params_v2'
                elif 'v3' in file_name.lower():
                    combo_name = 'params_v3'
                else:
                    combo_name = file_name.replace('breakout_strategy_param', 'params').replace('_param', '')

                combination = {
                    'name': combo_name,
                    'description': f'从文件 {param_file} 加载的参数',
                    'params': params_dict
                }
                combinations.append(combination)
            else:
                raise ValueError(f"参数文件 {param_file} 中未找到 'params' 变量")

        return combinations

    def _generate_grid_combinations(self, config: Dict[str, Any], max_combinations: int) -> List[Dict[str, Any]]:
        """生成网格搜索参数组合"""
        grid_config = config['parameter_sets']['grid_search']

        # 获取所有参数的可能值
        param_names = list(grid_config.keys())
        param_values = [grid_config[name] for name in param_names]

        # 生成所有组合
        all_combinations = list(itertools.product(*param_values))

        # 限制组合数量
        if len(all_combinations) > max_combinations:
            logging.warning(f"参数组合数量({len(all_combinations)})超过限制({max_combinations})，将随机采样")
            import random
            all_combinations = random.sample(all_combinations, max_combinations)

        # 转换为标准格式
        combinations = []
        for i, combination in enumerate(all_combinations):
            params = dict(zip(param_names, combination))
            # 添加默认的debug参数
            params['debug'] = False

            combination_dict = {
                'name': f'grid_{i+1:03d}',
                'description': f'网格搜索组合{i+1}: {params}',
                'params': params
            }
            combinations.append(combination_dict)

        return combinations

    def get_default_strategy_params(self) -> Dict[str, Any]:
        """获取BreakoutStrategy的默认参数"""
        # 这些是从strategy/breakout_strategy.py中提取的默认参数
        return {
            'debug': False,
            'bband_period': 20,
            'bband_devfactor': 2.0,
            'volume_ma_period': 20,
            'ma_macro_period': 60,
            'consolidation_lookback': 5,
            'consolidation_ma_proximity_pct': 0.02,
            'consolidation_ma_max_slope': 1.05,
            'squeeze_period': 60,
            'observation_period': 15,
            'confirmation_lookback': 5,
            'probation_period': 5,
            'pocket_pivot_lookback': 10,
            'breakout_proximity_pct': 0.03,
            'pullback_from_peak_pct': 0.07,
            'context_period': 7,
            'psq_pattern_weight': 1.0,
            'psq_momentum_weight': 1.0,
            'overheat_threshold': 1.99,
            'psq_summary_period': 3,
            'vcp_lookback': 60,
            'vcp_macro_ma_period': 90,
            'vcp_absorption_lookback': 20,
            'vcp_absorption_zone_pct': 0.07,
            'vcp_macro_roc_period': 20,
            'vcp_optimal_ma_roc': 1.03,
            'vcp_max_ma_roc': 1.15,
            'vcp_optimal_price_pos': 1.05,
            'vcp_max_price_pos': 1.30,
            'vcp_squeeze_exponent': 1.5,
            'vcp_weight_macro': 0.35,
            'vcp_weight_squeeze': 0.40,
            'vcp_weight_absorption': 0.25,
            'initial_stake_pct': 0.90,
            'atr_period': 14,
            'atr_multiplier': 2.0,
            'atr_ceiling_multiplier': 4.0
        }

    def merge_with_defaults(self, custom_params: Dict[str, Any]) -> Dict[str, Any]:
        """将自定义参数与默认参数合并"""
        default_params = self.get_default_strategy_params()
        merged_params = default_params.copy()
        merged_params.update(custom_params)
        return merged_params


if __name__ == '__main__':
    # 测试代码
    config_manager = ConfigManager()

    # 生成默认模板
    template_path = config_manager.generate_default_template()
    print(f"默认配置模板已生成: {template_path}")

    # 加载并验证配置
    config = config_manager.load_config(template_path)
    print(f"配置加载成功: {config['experiment_name']}")

    # 生成参数组合
    combinations = config_manager.generate_parameter_combinations(config)
    print(f"生成了 {len(combinations)} 个参数组合")

    for combo in combinations:
        print(f"- {combo['name']}: {combo['description']}")
