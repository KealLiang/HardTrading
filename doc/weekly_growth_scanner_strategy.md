# 周成交量增长选股策略说明

## 📌 策略概述

**策略名称**: 周成交量增长 + 温和上涨选股策略

**策略文件**: `bin/weekly_growth_scanner.py`

**使用场景**: T日收盘后执行扫描，筛选候选股，T+1日开盘买入

**核心思想**: 选择量能放大、位置不高、近期表现温和的股票，捕捉刚启动但未爆发的投资机会

---

## 🎯 策略条件

### 可在扫描时实现的条件

以下条件基于T日及之前的历史数据，可在T日收盘后直接判断：

| # | 条件 | 参数值 | 说明 |
|---|------|--------|------|
| 1 | **周成交量环比增长率** | > 100% | 以5个交易日为周期，最近一周成交量较上一周翻倍以上 |
| 2 | **近3个月区间涨跌幅** | < 40.1% | 避免追高位股，选择涨幅相对温和的标的 |
| 3 | **T日未涨停** | - | T日收盘价严格小于涨停价 |
| 4 | **T日小幅上涨** | T日收盘 > T-1日收盘 | 排除下跌和平盘的股票 |
| 5 | **T日涨幅限制** | < 4.5% | 温和上涨，不追高，避免T日已被爆炒 |
| 6 | **非ST股** | - | 自动过滤ST、*ST等风险股 |

### ⚠️ 需在T+1日开盘时判断的条件

以下条件无法在T日扫描时实现，需要在T+1日开盘后人工或程序判断：

| # | 条件 | 参数值 | 判断时机 | 处理方式 |
|---|------|--------|---------|---------|
| 7 | **排除高开5%以上** | >= 5% | T+1日开盘时 | 若T+1日开盘相对T日收盘高开>=5%，则放弃买入 |

---

## 📊 数据时间点说明

### 时间线定义

- **T日**: 执行扫描的交易日
- **T-1日**: T日的前一个交易日
- **T+1日**: T日的下一个交易日（计划买入日）

### 数据映射关系

在T日收盘后执行扫描，数据文件最后一行是T日的完整数据：

```python
# 数据读取
df.iloc[-1]  # T日完整数据（开、高、低、收、量）
df.iloc[-2]  # T-1日完整数据

# 关键变量
prev_close = df['close'].iloc[-2]   # T-1日收盘价
today_open = df['open'].iloc[-1]    # T日开盘价
today_close = df['close'].iloc[-1]  # T日收盘价（"当前价"）
```

### 条件检查的数据来源

| 条件 | 检查公式 | 数据时间点 | 是否未来数据 |
|------|---------|-----------|------------|
| 周成交量环比 | `sum(最近5日) / sum(前5日) > 2.0` | 截至T日 | ❌ 否 |
| 3个月涨跌幅 | `(T日收盘 / 3月前收盘) - 1 < 0.401` | 截至T日 | ❌ 否 |
| T日未涨停 | `T日收盘 < round(T-1日收盘 * (1+涨停比例), 2)` | T日收盘 | ❌ 否 |
| T日小幅上涨 | `T日收盘 > T-1日收盘` | T日收盘 | ❌ 否 |
| T日涨幅限制 | `(T日收盘 - T-1日收盘) / T-1日收盘 < 0.045` | T日涨幅 | ❌ 否 |
| 排除高开5% | `(T+1日开盘 - T日收盘) / T日收盘 >= 0.05` | **T+1日开盘** | ⚠️ **在T日无法获取** |

**✅ 结论**: 所有扫描时判断的条件均不使用未来数据，策略回测可信度高。

---

## 🔧 配置参数

### 常量配置（位于文件开头）

```python
DATA_DIR = './data/astocks'                          # 股票数据目录
OUTPUT_FILE = './bin/candidate_stocks_weekly_growth.txt'  # 输出文件
MIN_DATA_LEN = 30                                    # 最少需要30个交易日数据
WEEK_WINDOW = 5                                      # 周期窗口：5个交易日为一周
```

### 可调整的策略参数

| 参数 | 代码位置 | 当前值 | 说明 |
|------|---------|--------|------|
| 周期窗口 | `WEEK_WINDOW` | 5 | 可改为3、7等其他交易日数 |
| 周成交量增长率 | `_passes_weekly_volume_growth()` | 100% (1.0) | 可调整为50%、150%等 |
| 3个月涨跌幅上限 | `_passes_three_month_return()` | 40.1% (0.401) | 可调整为30%、50%等 |
| 涨幅上限 | `_passes_today_constraints()` | 4.5% (0.045) | 可调整为3%、6%等 |
| 高开阈值 | 代码注释中 | 5% (0.05) | T+1日判断时使用 |

---

## ⏰ 时间偏移功能

### 功能说明

**时间偏移功能**允许您扫描历史日期的数据，用于验证策略有效性和回测分析。

**核心概念**：
- `offset_days=0`：以T日为基准（今天），使用截至T日的数据
- `offset_days=1`：以T-1日为基准（昨天），使用截至T-1日的数据  
- `offset_days=N`：以T-N日为基准，使用截至T-N日的数据

**⚠️ 重要**：扫描T-N日时，只使用截至T-N日的数据，**不使用未来数据**，确保回测真实性。

### 使用场景

1. **验证策略有效性**：扫描昨天的数据，看看筛选出的股票今天表现如何
2. **回测分析**：扫描过去一周/一月的数据，统计策略胜率
3. **对比分析**：对比不同日期筛选出的股票池

### 输出文件命名规则

输出文件名自动包含基准日期，避免覆盖：

```
./bin/candidate_stocks_weekly_growth_20251017.txt  # T日（offset_days=0）
./bin/candidate_stocks_weekly_growth_20251016.txt  # T-1日（offset_days=1）
./bin/candidate_stocks_weekly_growth_20251015.txt  # T-2日（offset_days=2）
```

**自动同步功能**：扫描完成后，会自动将最新结果复制到：
```
./bin/candidate_stocks_weekly_growth.txt  # 不带日期（供后续流程使用）
```

这样可以无缝衔接后续的 `strategy_scan` 和 `generate_comparison_charts` 流程。

---

## 🚀 使用方法

### 1. 基本用法（扫描当前数据）

在 `main.py` 中调用：

```python
# 扫描T日（今天）
find_candidate_stocks_weekly_growth()

# 或显式指定
find_candidate_stocks_weekly_growth(offset_days=0)
```

### 2. 使用时间偏移（扫描历史数据）

```python
# 扫描T-1日（昨天）
find_candidate_stocks_weekly_growth(offset_days=1)

# 扫描T-5日（5天前）
find_candidate_stocks_weekly_growth(offset_days=5)

# 批量扫描最近7天
for i in range(7):
    print(f"\n{'='*60}")
    print(f"扫描T-{i}日")
    print('='*60)
    find_candidate_stocks_weekly_growth(offset_days=i)
```

### 3. 直接运行脚本

```bash
# 激活虚拟环境
conda activate trading

# 扫描当前数据（默认）
python bin/weekly_growth_scanner.py

# 注意：命令行暂不支持offset_days参数，需在代码中修改
```

### 4. 代码中修改默认参数

如需修改 `weekly_growth_scanner.py` 的默认行为，编辑文件末尾：

```python
if __name__ == '__main__':
    run_filter(offset_days=1)  # 改为扫描T-1日
```

### 5. 输出结果

扫描完成后，候选股代码将保存至带日期的文件：

```
# offset_days=0（T日，假设今天是2025-10-17）
./bin/candidate_stocks_weekly_growth_20251017.txt

# offset_days=1（T-1日）
./bin/candidate_stocks_weekly_growth_20251016.txt
```

文件格式：每行一个股票代码
```
600000
000001
300001
...
```

**输出示例**：
```
⏰ 时间偏移: 1天 (扫描T-1日的数据)
开始扫描 5234 只股票...
扫描进度: 100%|██████████| 5234/5234
  [+] 候选: 600000 - ✓ 通过全部筛选条件
  [+] 候选: 000001 - ✓ 通过全部筛选条件

==================================================
📅 基准日期: 20251016
扫描完成！发现 15 只候选股票。
==================================================
候选股列表已保存到: ./bin/candidate_stocks_weekly_growth_20251016.txt
✓ 已同步到: ./bin/candidate_stocks_weekly_growth.txt (供strategy_scan使用)
```

**自动同步说明**：
- 带日期的文件：`candidate_stocks_weekly_growth_20251016.txt` - 历史记录，不会被覆盖
- 不带日期的文件：`candidate_stocks_weekly_growth.txt` - 最新结果，供后续流程使用

---

## 🔄 完整工作流

### 典型使用流程

```python
# 步骤1: 扫描候选股（自动同步到不带日期的文件）
find_candidate_stocks_weekly_growth()
# 或使用时间偏移
find_candidate_stocks_weekly_growth(offset_days=2)

# 步骤2: 对候选股应用策略扫描（读取不带日期的文件）
strategy_scan('b')

# 步骤3: 生成对比图表
generate_comparison_charts('b')
```

### 文件流转示意

```
find_candidate_stocks_weekly_growth(offset_days=2)
    ↓
生成两个文件：
    ├─ ./bin/candidate_stocks_weekly_growth_20251015.txt  (历史记录)
    └─ ./bin/candidate_stocks_weekly_growth.txt           (最新结果，自动同步)
    ↓
strategy_scan('b')  读取 → candidate_stocks_weekly_growth.txt
    ↓
生成策略信号文件
    ↓
generate_comparison_charts('b')
    ↓
生成对比图表
```

### 优势

✅ **无需手动复制**：自动将最新扫描结果同步到固定文件名  
✅ **历史可追溯**：带日期的文件保留所有历史扫描记录  
✅ **流程无缝**：后续流程直接使用固定文件名，无需修改  
✅ **灵活回测**：可使用 `offset_days` 回测历史数据

### 完整工作流演示脚本

提供了完整的演示脚本 `examples/weekly_growth_workflow_demo.py`：

```bash
# 演示当日完整工作流
python examples/weekly_growth_workflow_demo.py --demo current

# 演示历史数据验证
python examples/weekly_growth_workflow_demo.py --demo historical

# 演示批量分析
python examples/weekly_growth_workflow_demo.py --demo batch

# 查看文件流转说明
python examples/weekly_growth_workflow_demo.py --demo files
```

---

## ⚠️ 重要注意事项

### 1. 关于"排除高开5%以上"条件

**⚠️ 该条件无法在T日扫描时实现！**

- **原因**: 需要T+1日的开盘价，但在T日收盘后无法获取
- **解决方案**: 在T+1日开盘后（约9:30），人工或通过程序判断：
  ```python
  gap_open_pct = (next_day_open - today_close) / today_close
  if gap_open_pct >= 0.05:
      # 放弃买入该股票
      pass
  ```

### 2. 数据更新时机

- **最佳执行时间**: T日收盘后（15:15之后），确保T日数据已完整更新
- **数据来源**: `./data/astocks/` 目录下的CSV文件
- **数据格式**: 每行包含日期、代码、开高低收、成交量等字段

### 3. 周期窗口说明

- 使用**交易日**而非**自然日**计算周期
- 5个交易日 ≈ 1个自然周（但更灵活）
- 好处：任何交易日都能获取完整的5日数据，避免自然周在周中数据不完整的问题

### 4. 涨停价计算规则

按A股规则，涨停价 = `round(前日收盘价 * (1 + 涨停比例), 2)`
- 普通股票：10%
- 科创板/创业板：20%
- ST股票：5%

### 5. ST股过滤

通过文件名自动过滤ST、*ST股票，无需额外配置。

---

## 📈 策略逻辑流程图

```
T日收盘后执行扫描
    ↓
读取所有股票数据文件
    ↓
过滤ST股票（文件名判断）
    ↓
遍历每只股票，依次检查：
    ├─ 数据是否充足（≥30个交易日）？
    ├─ 周成交量环比 > 100%？
    ├─ 近3个月涨跌幅 < 40.1%？
    ├─ T日未涨停？
    ├─ T日收盘 > T-1日收盘？
    └─ T日涨幅 < 4.5%？
    ↓
通过所有条件 → 加入候选池
    ↓
输出候选股列表到文件
    ↓
T+1日开盘时（9:30）
    ↓
判断候选股是否高开 >= 5%
    ├─ 是 → 放弃买入
    └─ 否 → 可以买入
```

---

## 🎯 策略意图与适用场景

### 策略意图

1. **量能放大**: 成交量翻倍，说明市场关注度提升，资金开始介入
2. **位置不高**: 近3个月涨幅有限，避免追高位股
3. **温和上涨**: T日表现稳健（小幅上涨、未涨停），不是被爆炒的热门股
4. **刚启动未爆发**: 符合"早期发现"的投资理念，在爆发前介入

### 适用场景

✅ **适合**:
- 短线波段交易（持股2-10天）
- 趋势启动期的介入
- 量价配合的技术分析
- 自动化选股 + 人工确认

❌ **不适合**:
- 长期价值投资（未考虑基本面）
- 超短线T+0交易（策略是T+1买入）
- 追涨停板（策略排除涨停股）
- 抄底反弹（策略要求上涨趋势）

---

## 📝 代码维护建议

### 修改策略参数

1. 修改周期窗口：调整 `WEEK_WINDOW` 常量
2. 修改成交量增长率：修改 `_passes_weekly_volume_growth()` 中的 `1.0`
3. 修改涨跌幅限制：修改 `_passes_three_month_return()` 中的 `0.401`
4. 修改涨幅上限：修改 `_passes_today_constraints()` 中的 `0.045`

### 添加新的筛选条件

在 `analyze_stock()` 函数中添加新的检查函数调用：

```python
def analyze_stock(df: pd.DataFrame, code: str) -> tuple[bool, str]:
    # ... 现有条件 ...
    
    # 添加新条件
    if not _passes_your_new_condition(df):
        return False, '新条件不满足'
    
    return True, '✓ 通过全部筛选条件'
```

---

## 🔗 相关文件

- **策略文件**: `bin/weekly_growth_scanner.py`
- **主入口**: `main.py::find_candidate_stocks_weekly_growth(offset_days=0)`
- **数据目录**: `./data/astocks/`
- **输出文件**: `./bin/candidate_stocks_weekly_growth_YYYYMMDD.txt`（自动包含日期）
- **工具函数**: `utils/stock_util.py::stock_limit_ratio()`

---

## 📞 问题排查

### 常见问题

**Q: 扫描结果为空？**
- 检查数据目录是否存在且有数据文件
- 检查数据是否是最新的（包含T日数据）
- 如果使用offset_days，确保有足够的历史数据
- 尝试放宽筛选条件（如降低成交量增长率要求）

**Q: 数据读取错误？**
- 确认CSV文件格式正确（12列，无表头）
- 确认日期列可以被正确解析

**Q: 如何调整策略参数？**
- 参考"配置参数"章节，修改对应常量或阈值

**Q: 如何验证策略有效性？**
- 使用时间偏移功能，扫描历史数据：`find_candidate_stocks_weekly_growth(offset_days=1)`
- 对比筛选出的股票在后续几天的表现
- 建议批量扫描最近7-30天，统计胜率和平均收益

**Q: offset_days的数据会使用未来数据吗？**
- 不会！offset_days=N时，只使用截至T-N日的数据
- 相当于"穿越"到T-N日执行扫描，只能看到当时的数据
- 这确保了回测的真实性和可信度

---

## 📅 文档版本

- **版本**: v1.2
- **创建日期**: 2025-10-17
- **最后更新**: 2025-10-17
- **更新内容**: 
  - v1.1: 新增时间偏移功能，支持扫描历史数据验证策略
  - v1.2: 新增自动文件同步功能，无缝衔接后续工作流
- **维护者**: Trading Team 