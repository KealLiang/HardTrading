#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BreakoutStrategy 参数优化系统演示
"""

import sys
import os
import yaml
sys.path.append('.')

def create_demo_config():
    """创建演示配置"""
    config = {
        'experiment_name': 'breakout_demo',
        'description': 'BreakoutStrategy参数优化演示',
        
        'backtest_config': {
            'stock_pool': ['300033', '300059'],  # 只用2只股票快速演示
            'time_range': {
                'start_date': '2024-01-01',
                'end_date': '2024-06-30'  # 半年数据快速演示
            },
            'initial_amount': 100000
        },
        
        'parameter_strategy': {
            'type': 'manual',
            'max_combinations': 3
        },
        
        'parameter_sets': {
            'manual_sets': [
                {
                    'name': 'baseline',
                    'description': '基准参数',
                    'params': {
                        'debug': False,
                        'bband_period': 20,
                        'atr_multiplier': 2.0
                    }
                },
                {
                    'name': 'aggressive',
                    'description': '激进参数',
                    'params': {
                        'debug': False,
                        'bband_period': 15,
                        'atr_multiplier': 2.5
                    }
                },
                {
                    'name': 'conservative',
                    'description': '保守参数',
                    'params': {
                        'debug': False,
                        'bband_period': 25,
                        'atr_multiplier': 1.5
                    }
                }
            ]
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
    
    os.makedirs('bin/optimization_configs', exist_ok=True)
    config_path = 'bin/optimization_configs/demo_config.yaml'
    
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
    
    return config_path

def main():
    print("🎯 BreakoutStrategy 参数优化系统演示")
    print("=" * 50)
    
    try:
        # 创建演示配置
        config_path = create_demo_config()
        print(f"✅ 演示配置已创建: {config_path}")
        
        # 导入优化器
        from bin.parameter_optimizer import ParameterOptimizer
        optimizer = ParameterOptimizer()
        print("✅ 参数优化器初始化成功")
        
        print(f"\n📋 演示配置:")
        print("  - 测试股票: 300033, 300059")
        print("  - 时间范围: 2024-01-01 至 2024-06-30")
        print("  - 参数组合: 3个 (基准、激进、保守)")
        
        # 询问是否继续
        user_input = input(f"\n🤔 是否开始演示？(y/n): ").strip().lower()
        if user_input not in ['y', 'yes', '是']:
            print("👋 演示已取消")
            return
        
        # 运行优化
        print(f"\n⏳ 开始参数优化...")
        report_path = optimizer.run_optimization(config_path)
        
        print(f"\n✅ 参数优化完成！")
        print(f"📄 报告保存在: {report_path}")
        
        # 显示报告摘要
        if os.path.exists(report_path):
            with open(report_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            print(f"\n📊 报告摘要 (前15行):")
            print("-" * 50)
            for i, line in enumerate(lines[:15]):
                print(f"{i+1:2d}: {line.rstrip()}")
            print("-" * 50)
            
            print(f"\n🎉 演示完成！")
            print(f"📚 完整使用说明: 参数优化系统使用说明.md")
        
    except Exception as e:
        print(f"❌ 演示过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
