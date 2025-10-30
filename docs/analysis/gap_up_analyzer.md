# 跳空高开股票分析工具

## 功能简介

扫描指定时间段内跳空高开的股票，生成K线图便于分析走势特征。同一只股票的多次跳空会合并在一张图上。

## 主要特性

- 全市场扫描所有股票数据
- 支持跳空幅度范围过滤
- 支持前期涨幅过滤（可选）
- 同一只股票多次跳空合并在一张图上
- 以最早和最晚跳空日期为基准生成K线图
- 自动生成CSV汇总报告

## 使用方法

在 `main.py` 中调用：

```python
# 基本用法：寻找跳空1%-6%的股票
analyze_gap_up_stocks('20250901', '20251027', min_gap=1.0, max_gap=6.0)

# 启用前期涨幅过滤：寻找前20日涨幅10%-50%且跳空1%-6%的股票
analyze_gap_up_stocks(
    '20250901', '20251027',
    min_gap=1.0, max_gap=6.0,
    filter_enabled=True,
    filter_days=20,
    filter_min_change=10.0,
    filter_max_change=50.0
)
```

## 配置参数

### 方法参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| start_date | - | 开始日期（YYYYMMDD） |
| end_date | - | 结束日期（YYYYMMDD） |
| min_gap | 1.0 | 最小跳空幅度（%） |
| max_gap | 6.0 | 最大跳空幅度（%） |
| filter_enabled | False | 是否启用前期涨幅过滤 |
| filter_days | 5 | 前x个交易日 |
| filter_min_change | 10.0 | 前期最小涨幅（%） |
| filter_max_change | 100.0 | 前期最大涨幅（%） |

### 全局配置（在 gap_up_analyzer.py 中）

```python
CHART_BEFORE_DAYS = 30  # 最早跳空日前显示的交易日数
CHART_AFTER_DAYS = 10   # 最晚跳空日后显示的交易日数
```

这两个参数不常变动，如需调整请直接修改 `gap_up_analyzer.py` 文件中的全局变量。

## 输出结果

- **K线图**：保存在 `./analysis/gap_up_charts/{日期范围}/` 目录
  - 文件名格式：`{股票名称}_{最早日期}至{最晚日期}_{跳空次数}次跳空.png`
  - 同一只股票的多次跳空标记在同一张图上
- **汇总报告**：`summary.csv`，包含每次跳空的详细信息
- **标记**：每个跳空日用黄色向上三角标记，显示跳空幅度

## 日志说明

扫描完成后会输出以下统计信息：
- 扫描的股票总数
- 成功处理和出错的股票数
- 符合条件的股票数和跳空记录数
- 跳空次数最多的前10只股票

示例日志：
```
扫描完成：处理 5900 只股票，116 只出错
筛选结果：共 850 只股票符合条件，产生 5377 次跳空记录
跳空次数最多的股票（前10）：
  300502 新易盛: 35次跳空
  688981 中芯集成: 28次跳空
  ...
```

## 应用场景示例

```python
# 场景1：强势加速信号（前期已有涨幅）
analyze_gap_up_stocks(
    '20250901', '20251027',
    min_gap=1.0, max_gap=6.0,
    filter_enabled=True, filter_days=20,
    filter_min_change=10.0, filter_max_change=50.0
)

# 场景2：突发利好（大幅跳空）
analyze_gap_up_stocks(
    '20250901', '20251027',
    min_gap=5.0, max_gap=15.0,
    filter_enabled=False
)

# 场景3：启动信号（前期涨幅小）
analyze_gap_up_stocks(
    '20250901', '20251027',
    min_gap=2.0, max_gap=8.0,
    filter_enabled=True, filter_days=10,
    filter_min_change=-5.0, filter_max_change=5.0
)
```

## 更新日志

v1.1 (2025-10-30)：
- 同一只股票的多次跳空合并在一张图上，减少图片数量
- 图表时间范围自动根据最早和最晚跳空日期调整
- 日志输出更清晰，显示股票数和跳空次数的统计信息
- `CHART_BEFORE_DAYS` 和 `CHART_AFTER_DAYS` 改为全局变量，简化参数
- 合并工具函数到主文件，简化项目结构 