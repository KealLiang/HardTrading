#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试daily_routine中的多线程问题修复
"""

import sys
import os
sys.path.append('..')

from main import execute_routine, fupan_statistics_to_excel, fupan_statistics_excel_plot

def test_problematic_steps():
    """测试有问题的步骤"""
    # 只测试报错的步骤
    test_steps = [
        (fupan_statistics_to_excel, "生成统计数据"),
        (fupan_statistics_excel_plot, "生成统计图表"),
    ]
    
    print("开始测试有问题的步骤...")
    execute_routine(test_steps, "test_routine")

if __name__ == "__main__":
    test_problematic_steps()
