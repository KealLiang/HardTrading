# 周成交量增长策略 - 胜率分析工具

## 📌 工具概述

**工具名称**: 胜率分析工具 (Win Rate Analyzer)

**功能**: 分析历史扫描结果的实际表现，统计胜率、收益率等关键指标

**文件**: `bin/weekly_growth_win_rate_analyzer.py`

---

## 🎯 核心功能

### 1. 交易模拟

**交易逻辑**（可配置）：
- **T日**: 收盘后扫描，生成候选股列表
- **T+1日**: 以开盘价全仓买入
- **T+2日**: 
  - 在当日最高价卖出 1/4 仓位（默认）
  - 在收盘价卖出 3/4 仓位（默认）

**计算公式**：
```python
加权卖出价 = T+2最高价 × 0.25 + T+2收盘价 × 0.75
收益率 = (加权卖出价 - T+1开盘价) / T+1开盘价
```

### 2. 统计指标

| 指标 | 说明 |
|------|------|
| **胜率** | 盈利交易数量 / 总有效交易数量 |
| **平均收益率** | 所有交易的平均收益率 |
| **平均盈利** | 盈利交易的平均收益率 |
| **平均亏损** | 亏损交易的平均亏损率 |
| **最大收益** | 单笔最大收益率 |
| **最大亏损** | 单笔最大亏损率 |
| **中位数收益** | 收益率的中位数 |
| **收益率标准差** | 收益率波动程度 |
| **盈亏比** | 平均盈利 / 平均亏损 |

### 3. 输出报告

- **控制台报告**: 清晰的统计信息
- **Markdown报告**: 灵活的文本格式，包含完整的统计数据和交易明细

---

## 🚀 使用方法

### 方式1: 在main.py中调用（推荐）

```python
# 分析最新的扫描文件（使用默认策略）
analyze_weekly_growth_win_rate()

# 分析指定文件
analyze_weekly_growth_win_rate(
    scan_file='bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt'
)

# 自定义卖出策略
analyze_weekly_growth_win_rate(
    high_ratio=0.3,   # 高点卖30%
    close_ratio=0.7   # 收盘卖70%
)

# 批量分析所有历史文件（默认只分析weekly_growth格式）
batch_analyze_weekly_growth_win_rate()

# 批量分析，自定义正则匹配
batch_analyze_weekly_growth_win_rate(
    pattern=r'candidate_stocks_.*_\d{8}\.txt$'  # 匹配所有类型的候选股文件
)
```

### 方式2: 直接运行脚本

```bash
conda activate trading

# 分析最新文件（默认）
python bin/weekly_growth_win_rate_analyzer.py

# 分析指定文件
python bin/weekly_growth_win_rate_analyzer.py --file bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt

# 批量分析（默认只分析weekly_growth格式）
python bin/weekly_growth_win_rate_analyzer.py --batch

# 批量分析，自定义正则匹配
python bin/weekly_growth_win_rate_analyzer.py --batch --pattern "candidate_stocks_.*_\d{8}\.txt$"

# 自定义卖出策略
python bin/weekly_growth_win_rate_analyzer.py --high-ratio 0.3 --close-ratio 0.7

# 指定目录
python bin/weekly_growth_win_rate_analyzer.py --batch --dir bin/candidate_temp
```

---

## 📊 输出示例

### 控制台输出

```
分析文件: candidate_stocks_weekly_growth_20251015.txt
基准日期: 20251015
候选股数量: 23
卖出策略: T+2日高点卖25%，收盘卖75%

分析进度: 100%|██████████████████████████| 23/23

================================================================================
📊 胜率分析报告
================================================================================

【基本信息】
总数量: 23
有效交易: 21
数据错误: 2

【胜率统计】
盈利数量: 14 (66.67%)
亏损数量: 6 (28.57%)
持平数量: 1 (4.76%)
✨ 胜率: 66.67%

【收益率统计】
平均收益率: 3.45%
平均盈利: 6.23%
平均亏损: -3.12%
最大收益: 15.80%
最大亏损: -8.50%
中位数收益: 2.80%
收益率标准差: 5.67%
盈亏比: 2.00

================================================================================

✅ 报告已保存到: bin/candidate_temp/candidate_stocks_weekly_growth_20251015_analysis.md
```

### Markdown报告示例

```markdown
# 胜率分析报告

**生成时间**: 2025-10-17 15:30:00

## 📊 基本信息

| 指标 | 数值 |
|------|------|
| 总数量 | 23 |
| 有效交易 | 21 |
| 数据错误 | 2 |

## 🎯 胜率统计

| 指标 | 数量 | 占比 |
|------|------|------|
| 盈利数量 | 14 | 66.67% |
| 亏损数量 | 6 | 28.57% |
| 持平数量 | 1 | 4.76% |
| **✨ 胜率** | **14** | **66.67%** |

## 💰 收益率统计

| 指标 | 数值 |
|------|------|
| 平均收益率 | 3.45% |
| 平均盈利 | 6.23% |
| 平均亏损 | -3.12% |
| 最大收益 | 15.80% |
| 最大亏损 | -8.50% |
| 中位数收益 | 2.80% |
| 收益率标准差 | 5.67% |
| 盈亏比 | 2.00 |

## 📋 交易明细

| 股票代码 | 基准日期 | 买入价 | 卖出价 | 收益率 | 状态 |
|---------|---------|--------|--------|--------|------|
| 600000 | 20251015 | 10.50 | 10.85 | 3.33% | ✅ 盈利 |
| 000001 | 20251015 | 15.20 | 14.95 | -1.64% | ❌ 亏损 |
...
```

---

## ⚙️ 卖出策略配置

### 默认策略

```python
SellStrategy(
    high_ratio=0.25,    # 高点卖1/4
    close_ratio=0.75,   # 收盘卖3/4
    description="T+2日高点卖1/4，收盘卖3/4"
)
```

### 自定义策略示例

**策略1: 保守策略（更多收盘卖出）**
```python
SellStrategy(
    high_ratio=0.1,     # 高点卖10%
    close_ratio=0.9,    # 收盘卖90%
)
```

**策略2: 激进策略（更多高点卖出）**
```python
SellStrategy(
    high_ratio=0.5,     # 高点卖50%
    close_ratio=0.5,    # 收盘卖50%
)
```

**策略3: 全部收盘卖出（最保守）**
```python
SellStrategy(
    high_ratio=0.0,     # 高点不卖
    close_ratio=1.0,    # 收盘全部卖出
)
```

---

## 📈 使用场景

### 场景1: 验证策略有效性

```python
# 步骤1: 扫描历史数据（例如扫描5天前）
find_candidate_stocks_weekly_growth(offset_days=5)

# 步骤2: 分析胜率
analyze_weekly_growth_win_rate()
```

### 场景2: 对比不同卖出策略

```python
# 策略A: 默认策略
analyze_weekly_growth_win_rate(
    scan_file='bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt',
    high_ratio=0.25,
    close_ratio=0.75
)

# 策略B: 全部收盘卖出
analyze_weekly_growth_win_rate(
    scan_file='bin/candidate_temp/candidate_stocks_weekly_growth_20251015.txt',
    high_ratio=0.0,
    close_ratio=1.0
)
```

### 场景3: 批量回测

```python
# 批量分析最近一个月的所有扫描结果
batch_analyze_weekly_growth_win_rate(
    directory='bin/candidate_temp'
)
```

---

## 🔧 核心类说明

### TradeResult (交易结果)

```python
@dataclass
class TradeResult:
    code: str                  # 股票代码
    base_date: str            # 基准日期（T日）
    buy_date: str             # 买入日期（T+1日）
    sell_date: str            # 卖出日期（T+2日）
    buy_price: float          # 买入价格
    sell_price: float         # 加权卖出价格
    return_rate: float        # 收益率
    is_profitable: bool       # 是否盈利
    error_msg: str            # 错误信息
```

### SellStrategy (卖出策略)

```python
@dataclass
class SellStrategy:
    high_ratio: float = 0.25    # 高点卖出比例
    close_ratio: float = 0.75   # 收盘卖出比例
    description: str            # 策略描述
    
    def calculate_sell_price(self, t2_high, t2_close):
        return t2_high * self.high_ratio + t2_close * self.close_ratio
```

### AnalysisReport (分析报告)

```python
@dataclass
class AnalysisReport:
    total_count: int          # 总数量
    valid_count: int          # 有效交易数量
    profitable_count: int     # 盈利数量
    win_rate: float           # 胜率
    avg_return: float         # 平均收益率
    # ... 更多统计指标
    trade_results: List[TradeResult]  # 详细交易记录
```

---

## ⚠️ 注意事项

### 1. 数据要求

- 需要有完整的T+1和T+2日数据
- 数据文件格式与扫描器一致
- 文件名格式：`candidate_stocks_weekly_growth_YYYYMMDD.txt`

### 2. 错误处理

以下情况会被标记为数据错误：
- 股票数据文件不存在
- T+1或T+2日数据缺失（如停牌）
- 基准日期不在数据中

### 3. 卖出策略说明

**高点卖出比例的含义**：
- 假设 `high_ratio=0.25`，表示在T+2日的最高价卖出25%
- 这是一个**理想化简化**，实际无法精确预判最高价
- 用于快速评估策略的理论收益上限

**收盘卖出比例的含义**：
- 假设 `close_ratio=0.75`，表示在T+2日收盘价卖出75%
- 这是**更现实**的卖出方式
- 收盘价是确定的，可实际操作

**建议**：
- 初期使用默认配置（0.25/0.75）快速验证
- 后期可调整为更保守的配置（如0.0/1.0，全部收盘卖出）

### 4. 性能考虑

- 使用缓存机制，重复读取同一股票数据时会更快
- 批量分析时可能较慢，请耐心等待
- 建议在非交易时段运行

---

## 🎉 完整工作流示例

```python
# === 完整流程 ===

# 1. 扫描最近7天的数据（生成历史记录）
for i in range(7):
    find_candidate_stocks_weekly_growth(offset_days=i)

# 2. 批量分析所有扫描结果
batch_analyze_weekly_growth_win_rate()

# 3. 查看汇总统计
# 会自动显示整体胜率、平均收益率等

# 4. 查看详细报告
# 每个扫描文件都会生成对应的Markdown报告
```

---

## 🎨 正则匹配说明

### 默认匹配模式

```python
pattern = r'candidate_stocks_weekly_growth_\d{8}\.txt$'
```

- 只匹配 `candidate_stocks_weekly_growth_YYYYMMDD.txt` 格式
- 避免混杂其他类型的候选股文件

### 自定义匹配模式示例

**匹配所有类型的候选股**：
```python
batch_analyze_weekly_growth_win_rate(
    pattern=r'candidate_stocks_.*_\d{8}\.txt$'
)
```

**只匹配特定日期范围**：
```python
batch_analyze_weekly_growth_win_rate(
    pattern=r'candidate_stocks_weekly_growth_202510\d{2}\.txt$'  # 只分析10月份
)
```

**匹配特定前缀**：
```python
batch_analyze_weekly_growth_win_rate(
    pattern=r'candidate_stocks_rebound_\d{8}\.txt$'  # 只分析rebound类型
)
```

---

## 📞 常见问题

**Q: 为什么有些股票显示"数据错误"？**
- 可能是T+1或T+2日停牌，导致数据缺失
- 可能是股票数据文件不完整

**Q: 胜率是否准确？**
- 胜率基于历史数据模拟，具有参考价值
- 但实际操作中可能因滑点、涨跌停等因素有所差异

**Q: 如何调整卖出策略？**
- 使用 `high_ratio` 和 `close_ratio` 参数
- 确保两者之和为1.0（代表100%仓位）

**Q: 可以分析单个股票吗？**
- 当前工具针对批量分析设计
- 如需分析单股，可创建只包含该股票代码的txt文件

**Q: 批量分析时如何避免不同类型候选股混杂？**
- 使用 `pattern` 参数指定正则匹配模式
- 默认只匹配 `weekly_growth` 格式，不会混杂其他类型

**Q: 为什么使用Markdown而不是Excel？**
- Markdown更灵活轻便，易于版本控制
- 可直接在IDE/编辑器中查看，无需额外软件
- 便于自动化处理和文本搜索

---

## 📅 版本信息

- **版本**: v1.1
- **创建日期**: 2025-10-17
- **最后更新**: 2025-10-17
- **更新内容**:
  - v1.0: 初始版本
  - v1.1: 优化架构（简化main.py）、添加正则匹配、改用Markdown输出
- **维护者**: Trading Team 