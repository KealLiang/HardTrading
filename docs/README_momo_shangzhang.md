# 【默默上涨】功能完整说明

## 功能概述

【默默上涨】是一个完整的股票筛选和分析系统，包含数据获取、处理和天梯图展示三个部分：

1. **数据获取**：通过 `fupan.py` 获取符合条件的股票数据
2. **数据处理**：通过 `momo_shangzhang_processor.py` 处理和筛选数据
3. **天梯图展示**：集成到天梯图系统中进行可视化分析

## 第一部分：数据获取（fupan.py）

### 查询条件

- **30天涨幅大于等于55%**
- **30天无涨停**
- **非ST股票**
- **非近新股**

### 数据特性
- **不能查历史数据**：此查询只能获取当前数据，无法指定历史日期
- **实时性强**：反映当前市场中符合条件的股票

### 时间逻辑
- **0点~9点30或非交易日**：使用前一个交易日日期
- **9点30后且是交易日**：使用当前交易日日期

### 数据格式
- 与其他复盘数据格式保持一致
- 单元格内容用分号（`;`）分隔
- 包含：股票代码、股票简称、最新价、最新涨跌幅、区间涨跌幅、区间成交额、区间振幅、上市交易日天数

### 存储位置
- 保存到 `./excel/fupan_stocks.xlsx` 的"默默上涨"sheet
- 不区分主板/非主板，统一保存所有符合条件的股票

### 数据获取使用方法

#### 方法1：单独查询数据

```python
from fetch.tonghuashun.fupan import get_silently_increase_stocks

# 查询默默上涨数据（不区分主板/非主板）
df = get_silently_increase_stocks()
```

#### 方法2：保存到Excel

```python
from fetch.tonghuashun.fupan import daily_fupan

# 保存默默上涨数据
daily_fupan('默默上涨', None, None, "", "../excel/fupan_stocks.xlsx")
```

#### 方法3：集成到完整复盘
```python
from fetch.tonghuashun.fupan import all_fupan

# 运行所有复盘类型（包括默默上涨）
all_fupan(start_date='20250905', types=['all'])  # 主板配置（包含默默上涨）
all_fupan(start_date='20250905', types=['else'])  # 非主板配置（不包含默默上涨）
```

## 第二部分：数据处理（momo_shangzhang_processor.py）

### 核心功能

1. **数据加载**: 从Excel读取【默默上涨】数据
2. **股票筛选**: 基于时间范围和去重逻辑筛选股票
3. **跟踪判断**: 判断股票是否应继续跟踪

### 关键参数

```python
# 【默默上涨】入选前跟踪的最大天数
MAX_TRACKING_DAYS_BEFORE_ENTRY_MOMO = 10

# 【默默上涨】持续跟踪的跌幅阈值
MOMO_DECLINE_THRESHOLD = -25.0

# 【默默上涨】入选的月数范围
MOMO_ENTRY_MONTHS = 3
```

### 核心函数

```python
def load_momo_shangzhang_data(start_date, end_date):
    """加载【默默上涨】数据"""

def identify_momo_shangzhang_stocks(momo_df, start_date, end_date):
    """识别【默默上涨】股票"""

def check_momo_tracking_condition(stock_code, current_date, entry_date):
    """检查跟踪条件"""
```

## 第三部分：天梯图集成（ladder_chart.py）

### 集成特点

1. **独立分组**: 作为"默默上涨"分组出现在【涨停梯队 按概念分组】sheet中
2. **格式一致**: 保持与连板股票相同的上色逻辑和单元格处理
3. **完整计算**: 包括【近10日/近30日】列和【异动预警】列

### 特殊显示

1. **入选日期**: 显示"默默上涨 XX%"，紫色背景(#9966FF)，白色字体
2. **其他日期**: 显示日涨跌幅，与连板股票格式一致
3. **概念列**: 显示"成交额:XX 涨幅:XX%"

### 使用方法

#### 命令行使用

```bash
# 启用【默默上涨】功能
python analysis/ladder_chart.py --start_date 20230501 --end_date 20230531 --enable_momo_shangzhang

# 结合其他功能使用
python analysis/ladder_chart.py --start_date 20230501 --end_date 20230531 --show_period_change --enable_momo_shangzhang
```

#### 程序调用

```python
from analysis.ladder_chart import build_ladder_chart

# 启用【默默上涨】功能
build_ladder_chart(
    start_date="20230501",
    end_date="20230531",
    output_file="./output/ladder_chart_with_momo.xlsx",
    enable_momo_shangzhang=True
)
```

#### 测试脚本

```bash
# 运行测试脚本
python test_momo_shangzhang.py
```

## 数据示例

### Excel中保存的数据格式：
```
股票代码; 股票简称; 最新价; 最新涨跌幅; 区间涨跌幅; 区间成交额; 区间振幅; 上市交易日天数
688610.SH; 埃科光电; 45.32; 2.15%; 68.5%; 12.5亿; 45.2%; 1250
300308.SZ; 中际旭创; 407; 10.3%; 119.7%; 4277.89亿; 142.4%; 2100
```

### 天梯图中的显示效果：
- **股票代码列**: 688610.SH
- **股票名称列**: 埃科光电
- **概念列**: 成交额:12.5亿 涨幅:68.5%
- **入选日期列**: "默默上涨 68.5%" (紫色背景)
- **其他日期列**: 显示日涨跌幅

## 技术实现细节

### 数据获取部分

#### 新增函数
1. `get_momo_shangzhang_stocks(board_suffix="")` - 查询默默上涨数据
2. `get_current_trading_date()` - 获取当前应使用的交易日期

#### 修改函数
1. `daily_fupan()` - 添加对"默默上涨"类型的特殊处理
2. `all_fupan()` - 在复盘类型列表中添加"默默上涨"

#### 数据处理
- 自动识别返回数据的列名（因为日期会动态变化）
- 格式化涨跌幅为百分比
- 格式化成交额为亿元单位
- 按区间涨跌幅降序排列

### 天梯图集成部分

#### 核心文件修改

1. **`analysis/momo_shangzhang_processor.py`** - 新增核心处理模块
2. **`analysis/loader/fupan_data_loader.py`** - 集成数据加载
3. **`analysis/ladder_chart.py`** - 主程序集成

#### 关键函数

```python
def format_momo_entry_cell(ws, row, col, pure_stock_code, current_date_obj, stock):
    """格式化【默默上涨】入选日期单元格"""

def process_daily_cell(ws, row_idx, col_idx, formatted_day, board_days, found_in_shouban, ...):
    """处理每日单元格（包含【默默上涨】逻辑）"""
```

## 维护说明

### 参数调整

根据市场情况，可以调整以下参数：
- `MOMO_DECLINE_THRESHOLD`: 跟踪阈值，市场波动大时可适当放宽
- `MOMO_ENTRY_MONTHS`: 入选时间范围，可根据分析需要调整
- `MAX_TRACKING_DAYS_BEFORE_ENTRY_MOMO`: 入选前跟踪天数

### 数据质量保证

1. **数据获取**：确保 `config.ths_cookie` 配置正确
2. **数据格式**：确保Excel中数据格式正确（分号分隔）
3. **日期格式**：确保日期格式统一（YYYY年MM月DD日）

### 性能优化

- 使用`@lru_cache`缓存重复计算
- 批量处理数据以提高效率
- 避免重复的文件IO操作

## 注意事项

### 数据获取注意事项

1. **网络依赖**：需要访问同花顺数据接口
2. **Cookie配置**：确保 `config.ths_cookie` 配置正确
3. **数据更新**：每次运行都会获取最新数据
4. **重复运行**：同一日期的数据会被跳过，避免重复保存

### 天梯图集成注意事项

1. **独立性**: 【默默上涨】功能完全独立，不影响现有连板分析逻辑
2. **性能**: 使用了缓存机制，重复运行时性能较好
3. **兼容性**: 与现有的所有功能（周期涨跌幅、异动预警等）完全兼容
4. **排序**: 【默默上涨】分组通常排在概念分组的最后，优先级较低
5. **颜色标识**: 使用紫色(#9966FF)作为【默默上涨】的专用标识色

## 完整使用流程

### 1. 数据获取
```bash
# 获取最新的【默默上涨】数据
python fetch/tonghuashun/fupan.py
```

### 2. 天梯图分析
```bash
# 生成包含【默默上涨】的天梯图
python analysis/ladder_chart.py --start_date 20230501 --end_date 20230531 --enable_momo_shangzhang --show_period_change
```

### 3. 结果查看
- 打开生成的Excel文件
- 查看【涨停梯队 按概念分组】sheet
- 找到"默默上涨"分组
- 观察紫色标记的入选日期和后续跟踪情况

## 故障排除

### 常见问题

1. **数据加载失败**
   - 检查`excel/fupan_stocks.xlsx`是否存在【默默上涨】sheet
   - 确认数据格式是否正确（分号分隔）

2. **显示异常**
   - 检查日期格式是否统一
   - 确认股票代码格式是否正确

3. **网络问题**
   - 检查网络连接
   - 确认同花顺Cookie是否有效

### 调试方法

```python
# 检查数据获取
from fetch.tonghuashun.fupan import get_silently_increase_stocks
df = get_silently_increase_stocks()
print(f"获取数据: {len(df)}条")

# 检查数据处理
from analysis.momo_shangzhang_processor import load_momo_shangzhang_data
momo_df = load_momo_shangzhang_data("20230501", "20230531")
print(f"处理数据: {len(momo_df)}条")

# 检查天梯图集成
python test_momo_shangzhang.py
```
