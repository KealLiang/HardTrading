#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试完整的daily_routine（跳过前面耗时的步骤）
"""

import sys
import os
sys.path.append('..')

from main import execute_routine, draw_ths_fupan, fupan_statistics_to_excel, fupan_statistics_excel_plot

def test_last_three_steps():
    """测试最后三个步骤，包括之前有问题的步骤"""
    # 从绘制涨跌高度图开始测试
    test_steps = [
        (draw_ths_fupan, "绘制涨跌高度图"),
        (fupan_statistics_to_excel, "生成统计数据"),
        (fupan_statistics_excel_plot, "生成统计图表"),
    ]
    
    print("开始测试最后三个步骤...")
    execute_routine(test_steps, "test_last_three_steps")

if __name__ == "__main__":
    test_last_three_steps()
