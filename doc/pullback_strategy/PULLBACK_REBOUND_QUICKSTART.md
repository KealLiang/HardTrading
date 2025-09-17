# 止跌反弹策略快速入门指南

## 🚀 快速开始

### 1. 基本回测（推荐新手）

在 `main.py` 中取消注释以下行：
```python
# pullback_rebound_simulate()  # 止跌反弹策略回测
```

然后运行：
```bash
conda activate trading
python main.py
```

### 2. 自定义股票回测

修改 `main.py` 中的 `pullback_rebound_simulate()` 函数：
```python
def pullback_rebound_simulate():
    stock_code = '你的股票代码'  # 例如：'000001'
    simulator.go_trade(
        code=stock_code,
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

### 3. 批量扫描信号

在 `main.py` 中取消注释：
```python
# pullback_rebound_scan('a')  # 止跌反弹策略扫描
```

## 📊 策略核心逻辑

### 买入信号
1. **主升浪后回调**：股价经历30%以上涨幅后回调
2. **企稳信号ABC**：
   - A: 量价背离（价格新低但成交量萎缩）
   - B: 量窒息（成交量低于均量60%）
   - C: 红K线（收盘价>开盘价）
3. **买入时机**：同时满足ABC时买入

### 卖出信号
- **止盈**：盈利12%
- **止损**：亏损5%
- **时间止损**：持有10天

## ⚙️ 参数调整

### 快速参数配置
```python
from strategy.strategy_params.pullback_rebound_strategy_param import get_params

# 激进型（适合强势市场）
aggressive_params = get_params('aggressive')

# 保守型（适合震荡市场）
conservative_params = get_params('conservative')

# 短线型（快进快出）
short_term_params = get_params('short_term')
```

### 常用参数说明
| 参数 | 默认值 | 说明 | 调整建议 |
|------|--------|------|----------|
| `uptrend_min_gain` | 0.30 | 主升浪最小涨幅 | 强势市场可降至0.25 |
| `pullback_max_ratio` | 0.15 | 最大回调幅度 | 震荡市场可降至0.12 |
| `profit_target` | 0.12 | 止盈目标 | 短线可降至0.08 |
| `stop_loss` | 0.05 | 止损比例 | 保守可降至0.04 |

## 🔧 常见问题

### Q1: 策略没有触发买入信号？
**A**: 尝试以下调整：
- 降低主升浪要求：`uptrend_min_gain: 0.20`
- 增加回调容忍度：`pullback_max_ratio: 0.20`
- 放宽量窒息要求：`volume_dry_ratio: 0.8`

### Q2: 信号太多，质量不高？
**A**: 提高筛选标准：
- 提高主升浪要求：`uptrend_min_gain: 0.35`
- 严格量窒息要求：`volume_dry_ratio: 0.5`
- 缩短回调容忍度：`pullback_max_ratio: 0.12`

### Q3: 如何查看详细日志？
**A**: 设置 `debug: True`：
```python
strategy_params={'debug': True}
```

## 📈 使用示例

### 示例1：测试单个股票
```python
from bin import simulator
from strategy.pullback_rebound_strategy import PullbackReboundStrategy
from datetime import datetime

simulator.go_trade(
    code='300059',  # 东方财富
    amount=100000,
    startdate=datetime(2023, 1, 1),
    enddate=datetime(2025, 8, 22),
    strategy=PullbackReboundStrategy,
    strategy_params={
        'debug': True,
        'uptrend_min_gain': 0.25,  # 降低要求
        'profit_target': 0.10,     # 降低止盈
    },
    log_trades=True,
    visualize=True,
    interactive_plot=True,
)
```

### 示例2：批量测试多个股票
```python
test_stocks = ['300059', '002415', '000858']
test_params = {
    'debug': False,  # 批量测试时关闭详细日志
    'uptrend_min_gain': 0.20,
    'pullback_max_ratio': 0.18,
}

for stock in test_stocks:
    print(f"测试股票: {stock}")
    simulator.go_trade(
        code=stock,
        amount=100000,
        startdate=datetime(2023, 1, 1),
        enddate=datetime(2025, 8, 22),
        strategy=PullbackReboundStrategy,
        strategy_params=test_params,
        log_trades=True,
        visualize=False,  # 批量测试时不生成图表
        interactive_plot=False,
    )
```

## 🎯 最佳实践

### 1. 参数优化流程
1. 先用默认参数测试
2. 根据结果调整关键参数
3. 在不同市场环境下验证
4. 记录最佳参数组合

### 2. 风险控制
- 单笔交易风险不超过总资金的2%
- 同时持仓不超过3只股票
- 定期评估策略表现

### 3. 市场适应性
- **牛市**：使用激进型参数
- **熊市**：使用保守型参数
- **震荡市**：使用短线型参数

## 📁 相关文件

- `strategy/pullback_rebound_strategy.py` - 主策略文件
- `strategy/scannable_pullback_rebound_strategy.py` - 扫描版本
- `strategy/strategy_params/pullback_rebound_strategy_param.py` - 参数配置
- `examples/pullback_rebound_example.py` - 使用示例
- `test_pullback_rebound.py` - 测试脚本

## 🆘 获取帮助

如果遇到问题：
1. 查看详细日志（设置 `debug: True`）
2. 检查股票数据是否存在
3. 尝试调整参数降低触发门槛
4. 参考示例代码和文档

---

**支付宝到账一百万元** 🎉
