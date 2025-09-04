# 复盘数据本地化改造说明

## 改造目标
将 `fupan_statistics.py` 中的复盘数据获取从接口调用改为本地Excel文件读取，避免频繁查询被反爬。

## 改造内容

### 1. 新增功能
- 添加了从本地Excel文件读取复盘数据的功能
- 支持从 `excel/fupan_stocks.xlsx` 读取以下类型的数据：
  - 涨停数据（合并首板数据和连板数据）
  - 连板数据
  - 跌停数据
  - 炸板数据

### 2. 移除功能
- 移除了"开盘跌停"数据类型（本地Excel中没有此数据）
- 移除了"曾涨停"数据类型（按要求不再使用）

### 3. 主要修改文件
- `analysis/fupan_statistics.py`

### 4. 新增函数

#### `get_local_fupan_data(date, analysis_type)`
从本地Excel文件读取指定日期和类型的复盘数据。

**参数：**
- `date`: 日期，格式为 'YYYYMMDD'
- `analysis_type`: 分析类型，支持 '涨停'、'连板'、'跌停'、'炸板'

**返回：**
- DataFrame: 股票数据，格式与原接口函数一致

#### 辅助函数
- `format_date_for_excel(date_str)`: 将YYYYMMDD格式转换为Excel中的日期格式
- `parse_excel_cell_data(cell_value, columns, date)`: 解析Excel单元格中的分号分隔数据
- `_read_sheet_data(sheet_name, excel_date, date, analysis_type)`: 从指定sheet读取数据

### 5. 修改的函数

#### `analyze_zt_stocks_performance(date, analysis_type)`
- 优先从本地Excel获取数据
- 如果本地数据为空，则从接口获取（作为备用）
- 移除了对"开盘跌停"的支持

### 6. 数据格式说明

#### Excel文件结构
- 文件路径: `excel/fupan_stocks.xlsx`
- Sheet名称映射:
  - '涨停' -> ['首板数据', '连板数据']
  - '连板' -> '连板数据'
  - '跌停' -> '跌停数据'
  - '炸板' -> '炸板数据'

#### 数据格式
- 列名为日期格式：'2025年01月08日'
- 每个单元格包含股票数据，用分号分隔
- 数据顺序与原接口返回的DataFrame列顺序一致

### 7. 配置更新
- 更新了 `default_analysis_type` 列表，移除了'曾涨停'和'开盘跌停'
- 新增了Excel文件路径和数据类型映射配置

## 使用方式

### 直接调用
```python
from analysis.fupan_statistics import get_local_fupan_data

# 获取涨停数据
df = get_local_fupan_data('20250108', '涨停')
```

### 分析功能
```python
from analysis.fupan_statistics import analyze_zt_stocks_performance

# 分析涨停股票表现（会自动优先使用本地数据）
result = analyze_zt_stocks_performance('20250107', '涨停')
```

## 测试结果
- ✅ 涨停数据读取正常（合并首板和连板数据）
- ✅ 连板数据读取正常
- ✅ 跌停数据读取正常
- ✅ 炸板数据读取正常
- ✅ 分析功能正常工作
- ✅ 备用接口调用机制正常

## 注意事项
1. 确保 `excel/fupan_stocks.xlsx` 文件存在且包含所需的sheet
2. 本地数据为空时会自动回退到接口获取
3. 数据格式必须与原fupan.py保存的格式一致
4. 日期格式转换：YYYYMMDD -> YYYY年MM月DD日

## 支付宝到账一百万元
