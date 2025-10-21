# 批量回测快速开始指南

## 3步快速上手

### 第1步：生成股票列表

运行以下命令，从已有数据中提取股票列表：

```bash
conda activate trading
cd D:\Trading
python bin/generate_stock_list.py
```

这将在 `data/` 目录生成：
- `all_astocks.txt` - 全部A股列表（TXT格式）
- `all_astocks.csv` - 全部A股列表（CSV格式，含名称）
- `sh_stocks.txt/csv` - 沪市股票
- `sz_stocks.txt/csv` - 深市股票
- `main_stocks.txt/csv` - 主板股票
- `chinext_stocks.txt/csv` - 创业板股票
- `star_stocks.txt/csv` - 科创板股票

### 第2步：配置回测参数

在 `main.py` 中修改 `batch_backtest_from_stock_list()` 函数：

```python
def batch_backtest_from_stock_list():
    stock_list_file = 'data/all_astocks.txt'  # 修改为你的股票列表文件
    
    report_path = batch_backtest_from_file(
        stock_list_file=stock_list_file,
        strategy_class=BreakoutStrategyV2,  # 修改为你的策略
        strategy_params={'debug': False},
        startdate=datetime(2022, 1, 1),     # 修改回测起始日期
        enddate=datetime(2025, 10, 21),     # 修改回测结束日期
        amount=100000,
        max_workers=6  # 根据你的CPU核心数调整（建议为核心数-2）
    )
```

### 第3步：运行批量回测

在 `main.py` 的 `__main__` 部分，启用批量回测：

```python
if __name__ == '__main__':
    # 注释掉单股回测
    # backtrade_simulate()
    
    # 启用批量回测
    batch_backtest_from_stock_list()
```

然后运行：

```bash
conda activate trading
python main.py
```

---

## 查看回测结果

回测完成后，在 `bin/batch_backtest_results/` 目录下会生成一个Excel文件：

`batch_summary_BreakoutStrategyV2_YYYYMMDD_HHMMSS.xlsx`

该Excel包含4个Sheet：
1. **回测结果** - 所有股票的完整回测数据（按收益率排序）
2. **统计汇总** - 整体统计数据（平均值、中位数、胜率等）
3. **TOP10盈利** - 收益率最高的10只股票
4. **TOP10亏损** - 收益率最低的10只股票

---

## 常见场景

### 场景1：回测特定板块（如创业板）

```python
# 1. 先生成创业板列表
python bin/generate_stock_list.py  # 会自动生成 data/chinext_stocks.txt

# 2. 使用创业板列表回测
batch_backtest_from_file(
    stock_list_file='data/chinext_stocks.txt',
    strategy_class=BreakoutStrategyV2
)
```

### 场景2：回测自选股

创建 `data/my_stocks.txt`，内容如下：
```
300033
300059
600610
```

然后：
```python
batch_backtest_from_file(
    stock_list_file='data/my_stocks.txt',
    strategy_class=BreakoutStrategyV2
)
```

### 场景3：小批量快速测试

```python
# 直接用代码列表，无需创建文件
batch_backtest_from_list(
    stock_codes=['300033', '300059', '600610'],
    strategy_class=BreakoutStrategyV2,
    max_workers=2
)
```

### 场景4：全市场回测（5000只股票）

```python
batch_backtest_from_file(
    stock_list_file='data/all_astocks.txt',
    strategy_class=BreakoutStrategyV2,
    max_workers=8,  # 使用8个并行进程
    startdate=datetime(2023, 1, 1),  # 缩短时间范围提升速度
    enddate=datetime(2025, 10, 21)
)
```

**预计耗时**：
- 8核CPU并行：约1-2小时
- 16核CPU并行：约30-60分钟

---

## 性能优化技巧

### 1. 调整并行进程数

根据CPU核心数调整 `max_workers`：
- 4核CPU：`max_workers=2-3`
- 8核CPU：`max_workers=6-7`
- 16核CPU：`max_workers=12-14`

### 2. 缩短回测时间范围

```python
# 只回测1年
startdate=datetime(2024, 1, 1)
enddate=datetime(2025, 1, 1)
```

### 3. 分批处理

将5000只股票分成10批，每批500只：

```python
# 手动分割文件或使用代码
import pandas as pd

# 读取全部列表
with open('data/all_astocks.txt') as f:
    all_codes = [line.strip() for line in f]

# 分成10批
batch_size = 500
for i in range(0, len(all_codes), batch_size):
    batch_codes = all_codes[i:i+batch_size]
    
    # 回测这一批
    batch_backtest_from_list(
        stock_codes=batch_codes,
        strategy_class=BreakoutStrategyV2,
        output_dir=f'bin/batch_backtest_results/batch_{i//batch_size+1}'
    )
```

### 4. 断点续传

如果回测中断，可以继续：

```python
batch_backtest_from_file(
    stock_list_file='data/all_astocks.txt',
    resume=True  # 跳过已完成的股票
)
```

---

## 故障排查

### 问题1：内存不足

**解决方案**：
- 减少 `max_workers`（如从8降到4）
- 分批处理
- 关闭其他占用内存的程序

### 问题2：某些股票回测失败

**原因**：数据文件缺失或格式问题

**解决方案**：
- 查看失败股票列表
- 补充缺失数据
- 或从列表中移除这些股票

### 问题3：回测速度仍然很慢

**检查清单**：
- ✅ 是否使用了SSD硬盘？
- ✅ `max_workers` 是否合理（不要超过CPU核心数）？
- ✅ `debug` 是否设置为 `False`？
- ✅ 回测时间范围是否过长？

---

## 更多帮助

- 详细文档：`bin/batch_backtest_README.md`
- 问题反馈：检查日志文件，查看具体错误信息 