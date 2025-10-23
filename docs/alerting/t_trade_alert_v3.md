# T+0监控 V3 - RSI+布林带+量价

> **版本**: v3 纯信号模式 | **更新**: 2025-10-24

---

## 设计思想

**定位**: 纯信号发生器，为未来多策略评分系统提供基础信号

**核心原则**:
1. 不预测市场状态（不判断主升浪/主跌浪）
2. 对称参数设计，保证买卖平衡
3. 量价硬确认，每个信号都必须量价验证
4. 输出0-100分强度评分

---

## 信号逻辑

### 买入信号
```
RSI < 30 
AND 价格 ≤ 下轨×1.003 
AND 近2根放量 ≥ 前3根×1.2
AND K线企稳（阳线 OR 长下影 OR 十字星）
```

### 卖出信号
```
RSI > 70 
AND 价格 ≥ 上轨×0.997
AND (当前放量 ≥ 5根均值×1.3 OR 量价背离)
```

**量价背离**: 价涨≥1.5% 且 量缩≥25%

---

## 参数配置

| 参数 | 默认值 | 说明 | 调整影响 |
|------|--------|------|----------|
| `RSI_OVERSOLD` | 30 | 超卖阈值 | ↓减少信号 ↑增加信号 |
| `RSI_OVERBOUGHT` | 70 | 超买阈值 | ↑减少信号 ↓增加信号 |
| `RSI_EXTREME_OVERSOLD` | 20 | 极度超卖（评分） | 仅影响评分 |
| `RSI_EXTREME_OVERBOUGHT` | 80 | 极度超买（评分） | 仅影响评分 |
| `BB_PERIOD` | 20 | 布林带周期 | - |
| `BB_STD` | 2 | 标准差倍数 | - |
| `BB_TOLERANCE` | 1.003 | 触及容差0.3% | ↑放宽 ↓收紧 |
| `VOLUME_CONFIRM_BUY` | 1.2 | 买入量能倍数 | ↓增加买入 ↑减少买入 |
| `VOLUME_CONFIRM_SELL` | 1.3 | 卖出量能倍数 | ↓增加卖出 ↑减少卖出 |
| `DIVERGENCE_PRICE_CHANGE` | 0.015 | 背离价格阈值1.5% | ↑减少卖出 |
| `DIVERGENCE_VOLUME_CHANGE` | -0.25 | 背离量能阈值-25% | 绝对值↑减少卖出 |
| `SIGNAL_COOLDOWN_SECONDS` | 180 | 冷却时间（秒） | ↑减少重复信号 |
| `REPEAT_PRICE_CHANGE` | 0.015 | 重复信号价差1.5% | ↑减少重复 |

---

## 调整示例

### 场景1: 信号过多
```python
RSI_OVERSOLD = 25           # 30→25
RSI_OVERBOUGHT = 75         # 70→75
SIGNAL_COOLDOWN_SECONDS = 300
```

### 场景2: 卖出信号过多（买卖比1:2）
```python
VOLUME_CONFIRM_BUY = 1.15        # 买入放宽
VOLUME_CONFIRM_SELL = 1.35       # 卖出收紧
DIVERGENCE_PRICE_CHANGE = 0.02   # 背离门槛提高
```

### 场景3: 买入信号过多（买卖比2:1）
```python
VOLUME_CONFIRM_BUY = 1.25        # 买入收紧
VOLUME_CONFIRM_SELL = 1.25       # 卖出放宽
# 修改企稳逻辑，去掉"十字星"条件
```

### 场景4: 信号太少
```python
VOLUME_CONFIRM_BUY = 1.1
VOLUME_CONFIRM_SELL = 1.2
BB_TOLERANCE = 1.005
SIGNAL_COOLDOWN_SECONDS = 120
```

---

## 信号评分

```
总分 = 50 + RSI加分(0-30) + 布林带加分(0-20)
```

| 条件 | 买入加分 | 卖出加分 |
|------|----------|----------|
| RSI极值 | <20:+30, <25:+20, <30:+10 | >80:+30, >75:+20, >70:+10 |
| BB偏离 | 跌破>1%:+20, 触及:+10 | 突破>1%:+20, 触及:+10 |

**分级**: ⭐⭐⭐强(80-100) | ⭐⭐中(60-79) | ⭐弱(0-59)

---

## 使用方法

### 回测
```python
from alerting.t_trade_alert_v3 import MonitorManagerV3

manager = MonitorManagerV3(
    symbols=['603153'],
    is_backtest=True,
    backtest_start="2025-10-20 09:30",
    backtest_end="2025-10-23 15:00"
)
manager.start()
```

### 实时监控
```python
manager = MonitorManagerV3(
    symbols=['603153'],
    is_backtest=False,
    symbols_file='watchlist.txt'
)
manager.start()
```

### 修改参数
编辑 `alerting/t_trade_alert_v3.py` 中 `TMonitorConfig` 类：
```python
class TMonitorConfig:
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    VOLUME_CONFIRM_BUY = 1.2
    VOLUME_CONFIRM_SELL = 1.3
    # ...
```

---

## 性能数据

**回测时段**: 2025-10-20至2025-10-23

| 股票 | 信号总数 | 买入 | 卖出 | 买卖比 |
|------|---------|------|------|--------|
| 上海建科 603153 | 47 | 24 | 23 | 1:0.96 |
| 哈焊华通 301137 | 22 | 9 | 13 | 1:1.4 |

---

**最后更新**: 2025-10-24 