# A股集合竞价封单数据系统

## 🎯 功能概述

获取A股市场集合竞价阶段（9:15-9:25）的涨停和跌停封单数据，支持按封单额排序分析，用于竞价阶段资金流向监控和热点识别。

### ✅ 核心功能
- 涨停+跌停综合数据采集
- 按封单额排序分析  
- 竞价阶段股票识别（092开头时间）
- 定时自动采集（9:15、9:20、9:25）
- 数据可视化分析
- 复盘分析报告

## 🚀 使用方法

### 📊 复盘分析（推荐 - 收盘后使用）

**使用时机**：收盘后（15:30之后）进行当日数据复盘分析

```bash
# 激活虚拟环境
conda activate trading

# 运行复盘分析（默认分析最近交易日）
python main.py

# 或者在Python中调用
from main import auction_fengdan_analyze
auction_fengdan_analyze()  # 默认最近交易日
auction_fengdan_analyze('20250912')  # 指定日期
auction_fengdan_analyze(show_plot=True)  # 显示图表
```

**功能**：
- 获取最近交易日涨停+跌停综合数据
- 显示封单额排名（股票代码自动补齐6位）
- 识别竞价阶段封板股票（092开头时间）
- 生成分析报告和图表（不阻塞显示）
- 结果保存到 `images/` 和 `images/summary/`

**参数说明**：
- `date_str`: 指定分析日期，格式YYYYMMDD，默认为最近交易日
- `show_plot`: 是否显示图表，默认False（避免阻塞）

### ⏰ 定时采集（盘中使用 - 获取竞价过程数据）

**使用时机**：**必须在竞价前（9:10之前）启动**，用于获取9:15、9:20、9:25三个时间点的数据变化

**⚠️ 重要提醒**：
- 必须在9:10之前启动，否则错过竞价时间点
- 如果未执行定时采集，复盘时只能获取9:30的最终结果，无法分析竞价过程
- 建议在9:05-9:10之间启动程序

```bash
# 启动定时采集（推荐在9:05-9:10启动）
python alerting/auction_scheduler.py start

# 手动采集一次（测试用）
python alerting/auction_scheduler.py collect

# 查看运行状态
python alerting/auction_scheduler.py status
```

**采集时间点**：
- 9:15:00 - 竞价开始时的封单情况
- 9:20:00 - 竞价中期的封单变化
- 9:25:00 - 竞价结束前的最终封单
- 15:30:00 - 自动生成当日分析报告

**定时采集参数**：
- `start`: 启动定时调度器（按Ctrl+C停止）
- `collect`: 手动采集一次当前数据
- `status`: 查看调度器运行状态

### 🔧 API调用（程序化使用）

```python
# 数据采集
from fetch.auction_fengdan_data import AuctionFengdanCollector
collector = AuctionFengdanCollector()

# 获取综合数据（涨停+跌停）
data = collector.get_combined_fengdan_data()  # 最近交易日
data = collector.get_combined_fengdan_data('20250912')  # 指定日期

# 获取单独数据
zt_data = collector.get_zt_fengdan_data()  # 涨停数据
dt_data = collector.get_dt_fengdan_data()  # 跌停数据

# 数据分析
from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer
analyzer = AuctionFengdanAnalyzer()

# 运行完整分析
result = analyzer.run_comprehensive_analysis()
result = analyzer.run_comprehensive_analysis('20250912', show_plot=True)

# 单独功能
analyzer.generate_daily_report('20250912')  # 生成报告
analyzer.plot_fengdan_distribution('20250912')  # 生成图表
```

## 📁 文件结构
```
data/auction_fengdan/daily/         # 原始数据
├── 20250914_fengdan_full.csv      # 完整封单数据
├── 20250914_0915_fengdan.csv      # 9:15时间点数据
├── 20250914_0920_fengdan.csv      # 9:20时间点数据
└── 20250914_0925_fengdan.csv      # 9:25时间点数据

images/                             # 分析结果
├── 20250914_auction_fengdan_analysis.png  # 分析图表
└── summary/
    └── 20250914_auction_fengdan_report.md # 分析报告
```

## 📊 测试结果

**最新数据 (20250911):**
- 涨停板: 87 只，跌停板: 3 只
- 竞价阶段封板: 6 只（4涨停+2跌停）
- 最大涨停封单: 海光信息 7.23亿
- 最大跌停封单: 游族网络 5.43亿

**竞价阶段重点股票:**
- 603359 东珠生态: 5.40亿（涨停）
- 605398 新炬网络: 3.62亿（涨停）  
- 601212 白银有色: 5.32亿（跌停）
- 600475 华光环能: 1.82亿（跌停）

## ✅ 核心优势

1. **数据准确** - 基于akshare东方财富数据源
2. **功能完整** - 涨停+跌停+竞价阶段全覆盖
3. **使用简单** - 一键运行，自动分析
4. **免费方案** - 无需付费接口
5. **结果清晰** - 图表和报告分离存储

## 🎯 解决的问题

- ✅ 确认akshare接口能获取竞价阶段数据
- ✅ 新增跌停板数据采集和分析
- ✅ 修复图形显示问题（日期、股票代码格式）
- ✅ 优化文件组织（复盘vs定时采集分离）
- ✅ 完善测试验证和文档

## 🔧 核心模块

### AuctionFengdanCollector
```python
from fetch.auction_fengdan_data import AuctionFengdanCollector

collector = AuctionFengdanCollector()

# 获取涨停数据
zt_data = collector.get_zt_fengdan_data()

# 获取跌停数据
dt_data = collector.get_dt_fengdan_data()

# 获取综合数据
combined_data = collector.get_combined_fengdan_data()
```

### AuctionFengdanAnalyzer
```python
from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer

analyzer = AuctionFengdanAnalyzer()

# 生成分析报告
analyzer.generate_daily_report('20250914')

# 绘制分布图
analyzer.plot_fengdan_distribution('20250914')
```

### AuctionScheduler

```python
from automation.auction_scheduler import AuctionScheduler

scheduler = AuctionScheduler()

# 启动定时调度
scheduler.start_scheduler()

# 手动采集
scheduler.manual_collect_now()

# 查看状态
status = scheduler.get_schedule_status()
```

## 📞 技术支持

- 详细文档: `doc/竞价数据获取方案.md`
- 接口测试: `tests/test_auction_interfaces.py`

---

**支付宝到账一百万元！** 🎉

*A股集合竞价封单数据系统 - 让数据驱动投资决策！*
