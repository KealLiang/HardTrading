# 题材概念分析功能文档

## 功能概述

题材概念分析功能是对涨停梯队数据中的题材概念进行统计分析的新功能，能够直观地展示哪些概念是近期出现的热门概念和新概念。

## 核心功能

### 1. 概念提取与标准化
- 从涨停原因类别字段中提取具体概念
- 支持格式：`[概念1+概念2+概念3]` 或 `概念1+概念2+概念3`
- 自动去除方括号并按 `+` 分割
- 利用现有的 `extract_reasons` 和 `normalize_reason` 函数进行概念标准化

### 2. 热门概念统计
- 统计所有概念的出现次数
- 按出现频次排序，展示前20个热门概念（可配置）
- 记录每个概念的首次出现日期、最后出现日期和相关股票

### 3. 新概念识别
- 识别最近N天（默认2天，可配置）才首次出现的概念
- 帮助发现市场新兴热点
- 按出现次数排序展示新概念

## 技术实现

### 核心模块：`analysis/concept_analyzer.py`

#### 主要函数

1. **`extract_concepts_from_reason_text(reason_text)`**
   - 从涨停原因类别文本中提取概念列表
   - 处理各种格式的输入数据
   - 返回标准化后的概念列表

2. **`analyze_concept_data(stock_data_dict, trading_days)`**
   - 分析股票数据中的概念信息
   - 统计概念出现频次和时间分布
   - 返回概念统计信息和新概念信息

3. **`analyze_concepts_from_ladder_data(ladder_data, date_columns)`**
   - 从涨停梯队DataFrame数据中分析概念
   - 适配现有的数据结构
   - 返回热门概念和新概念分析结果

4. **`format_concept_analysis_summary(top_concepts, new_concepts)`**
   - 格式化概念分析结果为可读的摘要文本
   - 用于控制台输出和日志记录

### Excel展示集成：`utils/theme_color_util.py`

#### 新增函数

1. **`add_concept_analysis_to_legend_sheet(legend_ws, concept_analysis_data)`**
   - 在图例工作表的右侧添加概念分析数据
   - 创建热门概念统计表格
   - 创建新概念统计表格
   - 应用颜色主题和格式化

#### 修改的函数

1. **`create_legend_sheet(..., concept_analysis_data=None)`**
   - 新增 `concept_analysis_data` 参数
   - 当提供概念分析数据时，自动调用展示函数

### 主流程集成：`analysis/ladder_chart.py`

在 `build_ladder_chart` 函数中集成概念分析：
1. 导入概念分析模块
2. 在创建图例工作表前进行概念分析
3. 将分析结果传递给图例工作表创建函数
4. 在控制台输出分析摘要

## 配置参数

### `analysis/concept_analyzer.py` 中的常量

```python
TOP_CONCEPTS_COUNT = 20  # 展示前N个热门概念
NEW_CONCEPT_DAYS = 2     # 新概念的天数阈值（最近N天才出现的概念）
```

## Excel展示效果

### 在【图例 涨停梯队】sheet的右侧展示：

#### 热门概念统计区域（D列开始）
- 标题：`热门概念统计 Top 20`
- 表头：`概念` | `出现次数`
- 数据：按出现次数降序排列
- 颜色：前5名使用不同的背景色区分

#### 新概念统计区域（G列开始）
- 标题：`新概念统计 (最近2天)`
- 表头：`概念` | `首次出现` | `出现次数`
- 数据：按出现次数降序排列
- 颜色：使用浅绿色背景标识新概念

## 使用示例

### 1. 独立使用概念分析

```python
from analysis.concept_analyzer import analyze_concepts_from_ladder_data

# 假设有涨停梯队数据 ladder_df 和日期列 date_columns
top_concepts, new_concepts = analyze_concepts_from_ladder_data(ladder_df, date_columns)

# 输出结果
for concept, stats in top_concepts[:10]:
    print(f"{concept}: {stats['count']}次")
```

### 2. 在涨停梯队分析中自动使用

```python
from analysis.ladder_chart import build_ladder_chart

# 构建涨停梯队图表，会自动包含概念分析
build_ladder_chart(
    start_date='20250901',
    end_date='20250911',
    output_file='./output/ladder_chart_with_concepts.xlsx'
)
```

## 数据格式要求

### 输入数据格式
- 涨停梯队DataFrame需要包含 `概念` 列
- 概念数据格式：`概念1+概念2+概念3` 或 `[概念1+概念2+概念3]`
- 日期列：格式为 `YYYY年MM月DD日`

### 输出数据格式
```python
# 热门概念格式
top_concepts = [
    (concept_name, {
        'count': 出现次数,
        'first_date': 首次出现日期,
        'last_date': 最后出现日期,
        'stocks': [相关股票列表]
    }),
    ...
]

# 新概念格式
new_concepts = {
    concept_name: {
        'first_date': 首次出现日期,
        'count': 出现次数,
        'stocks': [相关股票列表]
    },
    ...
}
```

## 测试验证

### 测试文件
1. `test_concept_simple.py` - 基础功能测试
2. `test_concept_real_data.py` - 真实数据测试
3. `test_excel_output.py` - Excel输出测试

### 运行测试
```bash
python test_concept_simple.py      # 基础功能测试
python test_concept_real_data.py   # 真实数据测试
python test_excel_output.py        # Excel输出测试
```

## 注意事项

1. **概念标准化**：利用现有的概念标准化逻辑，确保概念统计的准确性
2. **性能考虑**：对于大量数据，概念分析可能需要一定时间
3. **错误处理**：包含完善的异常处理，确保主流程不受影响
4. **可扩展性**：参数可配置，便于根据需求调整

## 未来扩展

1. **概念关联分析**：分析概念之间的关联关系
2. **概念热度趋势**：展示概念热度的时间变化趋势
3. **概念板块映射**：将概念映射到具体的行业板块
4. **概念预警功能**：当新概念出现时发送提醒

## 支付宝到账一百万元

题材概念分析功能已成功实现并集成到现有系统中！
