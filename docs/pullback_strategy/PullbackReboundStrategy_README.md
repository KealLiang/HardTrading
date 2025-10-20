# 止跌反弹策略 (PullbackReboundStrategy)

## 策略概述

止跌反弹策略是一个专门用于捕捉A股市场主升浪后回调企稳反弹机会的交易策略。该策略通过识别经历量价齐升主升浪后的回调过程中的企稳信号，在最佳时机介入，主要吃反弹段的利润。

## 策略逻辑

### 核心思想
1. **主升浪识别**：股价经过一段量价齐升的主升浪，涨到一定高度
2. **回调等待**：主升浪后出现下跌回调
3. **企稳信号**：在回调过程中出现企稳信号并开始反弹
4. **精准入场**：在红K线尾盘买入
5. **简单止盈止损**：主要吃反弹段利润

### 企稳信号三要素 (ABC)
- **A. 量价背离**：下跌中出现上涨并缩量
- **B. 量窒息**：进一步缩量，成交量萎缩到极低水平
- **C. 收红K线**：开始上涨，当日收盘价高于开盘价

## 策略状态机

策略运行过程中有四个主要状态：

1. **SCANNING（扫描状态）**
   - 扫描市场寻找主升浪机会
   - 判断条件：涨幅、放量、均线位置

2. **WAITING_PULLBACK（等待回调状态）**
   - 跟踪主升浪高点
   - 等待回调开始

3. **MONITORING_STABILIZATION（监控企稳状态）**
   - 监控企稳信号ABC
   - 判断买入时机

4. **POSITION_HELD（持仓状态）**
   - 执行止盈止损逻辑
   - 管理风险

## 技术指标

### 主要指标
- **简单移动平均线 (SMA)**：判断趋势方向
- **成交量移动平均线**：判断放量缩量
- **价格高低点跟踪**：识别主升浪和回调

### 关键参数
- `uptrend_period`: 主升浪判断周期（默认20天）
- `uptrend_min_gain`: 主升浪最小涨幅（默认30%）
- `pullback_max_ratio`: 最大回调幅度（默认15%）
- `volume_dry_ratio`: 量窒息阈值（默认60%）

## 买入条件

### 前置条件
1. 经历过主升浪（涨幅≥30%，放量，价格在均线之上）
2. 开始回调（从高点回落≥3%）
3. 回调幅度和时间在合理范围内

### 企稳信号
1. **量价背离**：最近几日价格创新低但成交量萎缩
2. **量窒息**：当日成交量低于均量的60%
3. **红K线**：当日收盘价高于开盘价

### 买入时机
同时满足所有企稳信号时，在红K线尾盘买入

## 卖出条件

### 止盈
- 盈利达到12%时止盈

### 止损
- 亏损达到5%时止损

### 时间止损
- 持有时间超过10个交易日时止损

## 使用方法

### 1. 基本回测
```python
from strategy.pullback_rebound_strategy import PullbackReboundStrategy
from bin import simulator
from datetime import datetime

# 单个股票回测
simulator.go_trade(
    code='300059',
    amount=100000,
    startdate=datetime(2022, 1, 1),
    enddate=datetime(2025, 8, 22),
    strategy=PullbackReboundStrategy,
    strategy_params={'debug': True},
    log_trades=True,
    visualize=True,
    interactive_plot=True,
)
```

### 2. 批量扫描
```python
from strategy.scannable_pullback_rebound_strategy import ScannablePullbackReboundStrategy
from bin.scanner_analyzer import scan_and_visualize_analyzer

# 批量扫描
scan_and_visualize_analyzer(
    scan_strategy=ScannablePullbackReboundStrategy,
    scan_start_date='20250630',
    scan_end_date=None,
    stock_pool=None,
    signal_patterns=['止跌反弹信号'],
    details_after_date='20250820',
    candidate_model='a'
)
```

### 3. 参数配置
```python
from strategy.strategy_params.pullback_rebound_strategy_param import get_params

# 使用预设参数
aggressive_params = get_params('aggressive')  # 激进型参数
conservative_params = get_params('conservative')  # 保守型参数

# 自定义参数
custom_params = {
    'uptrend_min_gain': 0.25,      # 降低主升浪要求
    'pullback_max_ratio': 0.18,    # 增加回调容忍度
    'profit_target': 0.10,         # 降低止盈目标
    'debug': True,                 # 开启详细日志
}
```

## 参数调优建议

### 强势市场
- 降低主升浪要求 (`uptrend_min_gain`: 0.25)
- 增加回调容忍度 (`pullback_max_ratio`: 0.20)
- 提高止盈目标 (`profit_target`: 0.15)

### 震荡市场
- 提高主升浪要求 (`uptrend_min_gain`: 0.35)
- 严格企稳信号 (`volume_dry_ratio`: 0.5)
- 降低止盈目标 (`profit_target`: 0.08)

### 短线交易
- 缩短观察周期 (`uptrend_period`: 15)
- 快进快出 (`max_hold_days`: 6)
- 严格止损 (`stop_loss`: 0.04)

## 风险提示

1. **市场风险**：策略依赖技术分析，无法预测突发事件
2. **回调风险**：回调可能超出预期范围
3. **假突破风险**：企稳信号可能是假信号
4. **流动性风险**：小盘股可能存在流动性问题

## 策略优势

1. **逻辑清晰**：基于经典的技术分析理论
2. **风险可控**：有明确的止盈止损机制
3. **适应性强**：可通过参数调整适应不同市场环境
4. **可扩展性**：支持批量回测和扫描

## 注意事项

1. 建议在使用前进行充分的历史回测
2. 根据市场环境调整参数配置
3. 注意资金管理，控制单笔交易风险
4. 定期评估策略表现，及时调整

## 文件结构

```
strategy/
├── pullback_rebound_strategy.py              # 主策略文件
├── scannable_pullback_rebound_strategy.py    # 可扫描版本
├── strategy_params/
│   └── pullback_rebound_strategy_param.py    # 参数配置文件
└── PullbackReboundStrategy_README.md         # 策略说明文档
```

## 更新日志

- **v1.0.0** (2025-09-17): 初始版本发布
  - 实现基本的止跌反弹策略逻辑
  - 支持回测和批量扫描
  - 提供多种参数配置预设
