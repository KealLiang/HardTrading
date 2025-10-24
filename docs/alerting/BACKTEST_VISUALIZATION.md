# 做T回测可视化使用指南

## 概述

为所有版本的做T监控系统（V1/V2/V3）添加了统一的回测可视化功能，可以自动生成包含买卖信号标注的K线图表。

## 功能特性

- ✅ **自动生成**：回测完成后自动生成图表
- ✅ **统一接口**：V1/V2/V3使用相同的可视化工具
- ✅ **不影响实时**：仅回测模式生成图表，实时监控不受影响
- ✅ **清晰标注**：绿色买入↑、红色卖出↓信号一目了然
- ✅ **完整时间轴**：X轴显示完整日期时间，每30分钟一个刻度

## 使用方法

### 默认使用（推荐）

回测时自动生成可视化图表，无需额外配置：

```python
# V1版本
from alerting.t_trade_alert import MonitorManager

manager = MonitorManager(
    symbols=['300852'],
    is_backtest=True,
    backtest_start="2025-10-20 09:30",
    backtest_end="2025-10-23 15:00",
    is_calc_trend=False
    # enable_visualization=True  # 默认开启
)
manager.start()

# V2版本
from alerting.t_trade_alert_v2 import MonitorManagerV2

manager = MonitorManagerV2(
    symbols=['300852'],
    is_backtest=True,
    backtest_start="2025-10-20 09:30",
    backtest_end="2025-10-23 15:00"
    # enable_visualization=True  # 默认开启
)
manager.start()

# V3版本
from alerting.t_trade_alert_v3 import MonitorManagerV3

manager = MonitorManagerV3(
    symbols=['300852'],
    is_backtest=True,
    backtest_start="2025-10-20 09:30",
    backtest_end="2025-10-23 15:00"
    # enable_visualization=True  # 默认开启
)
manager.start()
```

### 禁用可视化

大批量回测时可以关闭可视化以提升速度：

```python
manager = MonitorManager(
    symbols=['300852', '600519', '000001'],  # 多个股票
    is_backtest=True,
    backtest_start="2025-10-01 09:30",
    backtest_end="2025-10-23 15:00",
    enable_visualization=False  # 禁用可视化
)
```

## 输出说明

### 文件位置

回测完成后，图表保存在：
```
alerting/backtest_results/backtest_{股票代码}_{时间戳}.png
```

例如：
```
alerting/backtest_results/backtest_300852_20251024_153045.png
```

### 图表内容

生成的图表包含：

1. **K线图**：红涨绿跌（A股习惯），1分钟级别
2. **成交量**：下方副图显示成交量变化
3. **买入信号**：绿色向上箭头 ▲（标注在K线下方）
4. **卖出信号**：红色向下箭头 ▼（标注在K线上方）
5. **标题信息**：
   - 股票代码和名称
   - 信号统计（买入/卖出数量）
   - V3版本额外显示信号强度分布（强⭐⭐⭐/中⭐⭐/弱⭐）
   - 回测时间区间

### 信号标识

- **V1版本**：MACD背离信号
- **V2版本**：MACD+KDJ背离信号
- **V3版本**：RSI+布林带+量价确认信号（带强度评分）

## 技术说明

### 实时监控不受影响

可视化代码仅在满足以下条件时执行：
```python
if self.is_backtest and self.enable_visualization and total_signals > 0:
    # 生成图表
```

实时监控时 `is_backtest=False`，可视化逻辑不会运行。

### 数据缓存

回测过程中系统会自动：
- 缓存完整的1分钟K线数据
- 记录所有触发的买卖信号
- 回测结束后统一生成图表

### X轴时间显示

- 每30根K线（约30分钟）显示一个刻度
- 统一格式：`月-日 时:分`（如：`10-20 09:30`）
- 自动对齐，清晰可读

### 性能考虑

- 单个股票图表生成：1-3秒
- 内存占用：约10-20MB（生成后释放）
- 文件大小：约200-500KB/图

## 常见问题

**Q: 回测没有生成图表？**
A: 检查是否触发了信号。如果没有信号，不会生成图表。

**Q: 图表中文显示乱码？**
A: 确保项目根目录下有 `fonts/微软雅黑.ttf`，或系统已安装中文字体。

**Q: 想要修改信号标记样式？**
A: 编辑 `utils/backtrade/intraday_visualizer.py` 中的 `_create_signal_markers()` 方法。

**Q: 大批量回测太慢？**
A: 设置 `enable_visualization=False` 跳过图表生成。

## 版本差异

| 功能 | V1 | V2 | V3 |
|------|----|----|-----|
| 信号类型 | MACD背离 | MACD+KDJ背离 | RSI+布林带+量价 |
| 信号强度 | ✗ | ✗ | ✓（强/中/弱） |
| 可视化 | ✓ | ✓ | ✓ |
| 统一接口 | ✓ | ✓ | ✓ |

## 独立使用可视化工具

如需更灵活的控制，可以直接调用底层API：

```python
from utils.backtrade.intraday_visualizer import plot_intraday_backtest

# 准备数据
df_1m = pd.DataFrame({...})  # 1分钟K线
signals = [...]  # 信号列表

# 生成图表
plot_intraday_backtest(
    df_1m=df_1m,
    signals=signals,
    symbol='300852',
    stock_name='鹏辉能源',
    backtest_start='2025-10-20 09:30',
    backtest_end='2025-10-23 15:00',
    output_dir='custom/path'  # 自定义输出路径
)
```

详细数据格式要求请参考 `utils/backtrade/README_intraday_viz.md`。

## 更新日志

### v1.1 (2025-10-24)
- ✅ 修复多线程警告（使用非交互式后端）
- ✅ 关闭数据量警告
- ✅ 优化X轴刻度显示（每30根K线一个刻度）
- ✅ 统一显示完整日期时间

### v1.0 (2025-10-24)
- ✅ 创建独立可视化模块
- ✅ 集成到V1/V2/V3版本
- ✅ 自动生成回测图表 