# 大批量回测功能使用说明

## 功能概述

大批量回测模块专为解决**批量回测性能问题**而设计，支持同时回测数千只股票，适合全市场扫描、板块分析等场景。

### 核心特点

1. **支持文件读取** - 从CSV/TXT文件读取股票列表
2. **多进程并行** - 利用多核CPU大幅提升性能
3. **简化输出** - 只保留关键统计指标，不生成详细图表
4. **汇总报告** - 自动生成Excel报告，包含统计分析
5. **断点续传** - 支持从上次中断处继续
6. **进度监控** - 实时显示回测进度

---

## 使用方法

### 方式1：从文件读取股票列表

#### 1.1 准备股票列表文件

支持两种格式：

**TXT格式**（推荐简单场景）
```
300033
300059
000062
600610
```

**CSV格式**（推荐复杂场景）
```csv
股票代码,股票名称,板块
300033,同花顺,软件服务
300059,东方财富,互联网
000062,深圳华强,电子元件
600610,中国中铁,建筑装饰
```

> 注意：CSV文件只会读取第一列作为股票代码

#### 1.2 调用函数

在 `main.py` 中调用：

```python
def batch_backtest_from_stock_list():
    report_path = batch_backtest_from_file(
        stock_list_file='data/stock_list.txt',  # 股票列表文件路径
        strategy_class=BreakoutStrategyV2,       # 策略类
        strategy_params={'debug': False},         # 策略参数
        startdate=datetime(2022, 1, 1),          # 回测开始日期
        enddate=datetime(2025, 10, 21),          # 回测结束日期
        amount=100000,                            # 初始资金
        data_dir='./data/astocks',               # 股票数据目录
        output_dir='bin/batch_backtest_results', # 输出目录
        max_workers=None,  # CPU核心数-1（也可手动指定如4、8）
        resume=False       # 是否断点续传
    )
```

### 方式2：直接使用代码列表

适合代码不多或动态生成股票池的场景：

```python
def batch_backtest_from_codes():
    stock_codes = ['300033', '300059', '000062', '600610']
    
    report_path = batch_backtest_from_list(
        stock_codes=stock_codes,
        strategy_class=BreakoutStrategyV2,
        strategy_params={'debug': False},
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 10, 21),
        amount=100000,
        max_workers=4
    )
```

---

## 性能对比

### 场景1：小批量回测（10只股票）

| 模式 | 耗时 | 提升 |
|------|------|------|
| 串行（原有方式） | ~50秒 | - |
| 并行4进程 | ~15秒 | **3.3x** |
| 并行8进程 | ~10秒 | **5x** |

### 场景2：大批量回测（1000只股票，3年数据）

| 模式 | 耗时 | 提升 |
|------|------|------|
| 串行 | ~83分钟 | - |
| 并行4进程 | ~25分钟 | **3.3x** |
| 并行8进程 | ~15分钟 | **5.5x** |

### 场景3：全市场回测（5000只股票，3年数据）

| 模式 | 耗时估算 | 提升 |
|------|---------|------|
| 串行 | ~7小时 | - |
| 并行8进程 | **~1.3小时** | **5.4x** |
| 并行16进程 | **~50分钟** | **8.4x** |

> **建议**：
> - CPU核心数 ≤ 4：max_workers=2-3
> - CPU核心数 = 8：max_workers=6-7
> - CPU核心数 ≥ 16：max_workers=12-14

---

## 输出报告说明

批量回测完成后，会在输出目录生成一个Excel文件，包含以下Sheet：

### 1. 回测结果（主表）

按策略总收益率排序，包含所有股票的详细指标：

| 列名 | 说明 |
|------|------|
| 股票代码 | 6位股票代码 |
| 初始资金 | 起始资金 |
| 最终资金 | 回测结束后的资金 |
| 策略总收益率(%) | 策略的总收益率 |
| 年化收益率(%) | 年化收益率 |
| 最大回撤(%) | 最大回撤百分比 |
| 夏普比率 | 夏普比率 |
| 基准收益率(%) | 买入持有的收益率 |
| 超额收益(%) | 相对基准的超额收益 |
| 总交易次数 | 交易次数 |
| 盈利交易数 | 盈利的交易数 |
| 胜率(%) | 盈利交易占比 |

### 2. 统计汇总

包含整体统计信息：
- 回测配置（策略、参数、时间范围等）
- 成功/失败数量
- 各指标的平均值、中位数、最大值、最小值
- 整体胜率统计

### 3. TOP10盈利

收益率最高的10只股票

### 4. TOP10亏损

收益率最低的10只股票

---

## 高级功能

### 断点续传

当回测中断时（如停电、程序崩溃），可以使用 `resume=True` 从上次中断处继续：

```python
batch_backtest_from_file(
    stock_list_file='data/all_astocks.txt',
    strategy_class=BreakoutStrategyV2,
    resume=True  # 跳过已完成的股票
)
```

### 自定义并行进程数

根据CPU核心数和内存情况调整：

```python
batch_backtest_from_file(
    stock_list_file='data/stock_list.txt',
    max_workers=8  # 手动指定8个并行进程
)
```

### 不同策略对比

分别对不同策略进行批量回测，对比效果：

```python
# 策略A回测
batch_backtest_from_file(
    stock_list_file='data/stock_list.txt',
    strategy_class=BreakoutStrategy,
    output_dir='bin/batch_backtest_results/strategy_a'
)

# 策略B回测
batch_backtest_from_file(
    stock_list_file='data/stock_list.txt',
    strategy_class=BreakoutStrategyV2,
    output_dir='bin/batch_backtest_results/strategy_b'
)
```

---

## 注意事项

1. **数据准备**：确保 `data/astocks/` 目录下有足够的股票数据
2. **内存占用**：大批量回测会占用较多内存，建议16GB+
3. **关闭详细日志**：批量回测时建议 `debug=False`
4. **不生成图表**：批量回测自动关闭可视化，提升性能
5. **硬件建议**：
   - CPU：8核或以上
   - 内存：16GB或以上
   - 硬盘：SSD（提升数据读取速度）

---

## 常见问题

### Q1: 为什么有些股票回测失败？

**可能原因**：
- 数据文件缺失
- 数据时间范围不足
- 数据格式问题

**解决方案**：查看失败股票的错误信息，补充数据或从列表中移除

### Q2: 如何获取全部A股列表？

```python
from fetch.astock_data import StockDataFetcher

# 方法1：从已下载的数据中提取
import os
stock_codes = []
for filename in os.listdir('./data/astocks'):
    if filename.endswith('.csv'):
        code = filename.split('_')[0]
        stock_codes.append(code)

# 保存为文件
with open('data/all_astocks.txt', 'w') as f:
    for code in stock_codes:
        f.write(f"{code}\n")
```

### Q3: 如何优化性能？

1. **增加并行进程数**（但不要超过CPU核心数）
2. **使用SSD硬盘**（提升数据读取速度）
3. **减少回测时间范围**（如只回测1年）
4. **分批处理**（将5000只股票分成10批，每批500只）

### Q4: 内存不足怎么办？

**方案1：减少并行进程数**
```python
max_workers=2  # 降低并行数
```

**方案2：分批处理**
```python
# 将股票列表分成多个小文件
batch_backtest_from_file('data/stock_list_part1.txt')
batch_backtest_from_file('data/stock_list_part2.txt')
# 最后手动合并Excel
```

---

## 完整示例

```python
from datetime import datetime
from strategy.breakout_strategy_v2 import BreakoutStrategyV2
from bin.batch_backtester import batch_backtest_from_file

def my_batch_backtest():
    """我的批量回测示例"""
    
    # 配置参数
    stock_list_file = 'data/my_stock_pool.txt'
    
    # 执行批量回测
    report_path = batch_backtest_from_file(
        stock_list_file=stock_list_file,
        strategy_class=BreakoutStrategyV2,
        strategy_params={
            'debug': False,
            # 在这里添加你的策略参数
        },
        startdate=datetime(2022, 1, 1),
        enddate=datetime(2025, 10, 21),
        amount=100000,
        data_dir='./data/astocks',
        output_dir='bin/batch_backtest_results',
        max_workers=6,
        resume=False
    )
    
    print(f"批量回测完成！报告路径: {report_path}")
    
if __name__ == '__main__':
    my_batch_backtest()
```

---

## 技术架构

```
batch_backtester.py
├── BatchBacktester (主类)
│   ├── _load_stock_list()      # 加载股票列表
│   ├── run_batch_backtest()    # 执行批量回测
│   └── _generate_summary_report()  # 生成汇总报告
│
├── _run_single_backtest_worker()  # 单股票回测（多进程worker）
├── _parse_backtest_output()       # 解析回测输出
│
├── batch_backtest_from_file()  # 便捷函数：从文件
└── batch_backtest_from_list()  # 便捷函数：从列表
```

---

## 更新日志

### v1.0 (2025-10-21)
- 初始版本
- 支持从文件/列表读取股票
- 多进程并行回测
- 生成Excel汇总报告
- 断点续传功能 