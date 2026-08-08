# 量化交易与分析项目

## 概述

本项目是面向中国 A 股的量化交易与复盘分析平台：覆盖行情拉取、题材复盘、天梯/龙头跟踪、形态选股、策略扫描与回测、参数优化等。  
**所有功能入口统一在 `main.py`**，在文件底部 `__main__` 中取消对应函数注释即可运行。

## 运行方式

```bash
conda activate trading
python main.py
```

按需在 `main.py` 的 `if __name__ == '__main__':` 中开关各入口函数；日常一键流程对应 `daily_routine()`。

---

## 功能介绍

### 1. 一键流程

| 入口 | 说明 |
|------|------|
| `daily_routine()` | 日常复盘流水线：拉 A 股/指数 → 同花顺复盘 → 题材归类 → 天梯 → 涨跌高度图/HTML → 龙头与默默上涨 HTML → 复盘统计与词云 |
| `full_scan_routine(candidate_model)` | 策略扫描流水线：突破策略扫描 → 对比图 → 写入候选历史 |
| `execute_routine(steps, name)` | 通用分步执行器（写日志、计时、重定向 print） |

### 2. 数据获取与维护

| 入口 | 说明 |
|------|------|
| `get_stock_datas()` | 拉取/增量更新 A 股日线（支持实时接口） |
| `repair_truncated_stock_datas()` | 修复仅 1 行有效数据的残缺 CSV |
| `clean_duplicate_stock_datas()` | 扫描/清理日线重复行情 |
| `get_stock_minute_datas()` | 拉取分钟线（如 15 分钟） |
| `get_index_data()` | 拉取主要指数数据 |
| `get_etf_datas(etf_list, ...)` | 拉取 ETF 日线到 `data/etfs/` |
| `get_pe_data()` | 下载沪深 300 历史 PE（永久组合估值用） |
| `fetch_stock_concept_map()` | 更新概念–股票映射 |
| `get_stock_concept_and_industry()` | 按概念/行业名单拉取成分并导出 Excel |
| `fetch_ths_fupan()` / `clean_ths_fupan()` | 拉取同花顺复盘数据；清理历史以控制文件体积 |
| `get_lhb_datas()` / `fetch_and_filter_top_yybph()` / `get_top_yyb_trades()` | 龙虎榜、营业部排行与顶级游资交易 |

### 3. 复盘与题材分析

| 入口 | 说明                                                                                             |
|------|------------------------------------------------------------------------------------------------|
| `whimsical_fupan_analyze()` | 涨停原因归类（同义词/题材）                                                                                 |
| `generate_ladder_chart()` | 生成涨停天梯 Excel（概念分组、龙头 sheet、量能 sheet 等）                                                         |
| `draw_ths_fupan()` / `draw_ths_fupan_html()` | 涨跌高度图（PNG / 交互 HTML）                                                                           |
| `fupan_statistics_to_excel()` / `fupan_statistics_excel_plot()` | 复盘统计表与图表                                                                                       |
| `get_hot_clouds()` | 热门概念词云                                                                                         |
| `update_synonym_groups()` / `clean_synonym_groups()` | 同义词分组更新与过期词清理（使用sentence-transformers 编码 + K-Means 聚类；模型paraphrase-multilingual-MiniLM-L12-v2） |
| `dejavu_fupan_analyze()` | 连板「似曾相识」类复盘                                                                                    |
| `daily_group_analyze()` | 按热点题材聚类找股                                                                                      |
| `analyze_advanced_on()` | 涨停晋级/成功率统计                                                                                     |
| `auction_fengdan_analyze()` | 集合竞价封单复盘（定时采集见 `alerting/auction_scheduler.py`）                                                |

### 4. 天梯 / 龙头 / HTML 图表

| 入口 | 说明 |
|------|------|
| `generate_leader_sheet_html_charts()` | 龙头 sheet 交互 HTML 走势图 |
| `analyze_leader_performance_stats()` | 龙头候选绩效统计（T 开盘买、持有观测，Markdown） |
| `generate_momo_concept_group_html_charts()` | 「默默上涨」概念分组 HTML |
| `generate_momo_html_charts(...)` | 新入选默默上涨简化 HTML（可在 routine 中启用） |
| `launch_custom_stock_chart_app()` | 自选股粘贴代码生成 HTML 小工具 |
| `generate_virtual_kline_simulation_html()` | 虚拟 K 线仿真（叠加未来假想 K 线看均线变化） |
| `erban_longtou_analysis()` | 二板定龙头：晋级率、胜率、题材与量价报告 |

### 5. 策略扫描与选股

| 入口 | 说明 |
|------|------|
| `strategy_scan(candidate_model, enable_vcp_filter)` | 突破策略全市场/池扫描，输出候选与摘要 |
| `pullback_rebound_scan(candidate_model)` | 止跌反弹策略扫描 |
| `find_candidate_stocks()` | 韧性/形态初筛（`resilience_scanner`） |
| `find_candidate_stocks_weekly_growth()` | 周成交量增长选股 |
| `find_candidate_stocks_volume_surge()` | 成交量金叉（平稳股价 + 量能金叉）选股 |
| `candidate_hot_concept_stocks(concepts)` | 按热门概念生成候选股列表 |
| `generate_comparison_charts()` / `generate_rebound_comparison_charts()` | 扫描信号日对比图 |
| `generate_strategy_scan_html_charts()` | 突破扫描结果交互 HTML |
| `record_scan_to_history()` / `review_history()` | 扫描结果入历史；事后回顾走势对比图 |
| `analyze_weekly_growth_win_rate()` / `batch_analyze_weekly_growth_win_rate()` | 周增长策略胜率（单文件 / 批量汇总） |

### 6. 策略回测与参数优化

| 入口 | 说明 |
|------|------|
| `backtrade_simulate()` | 单标的突破策略回测（可视化/交互图） |
| `pullback_rebound_simulate()` | 止跌反弹策略单标回测 |
| `weekly_volume_momentum_simulate()` | 周量能放大（扬帆起航）策略回测 |
| `batch_backtest_from_stock_list()` / `batch_backtest_from_codes()` | 多进程大批量回测（文件列表或代码列表） |
| `generate_stock_lists()` / `generate_fupan_candidates()` | 生成全市场/复盘热门股回测候选列表 |
| `breakout_strategy_backtest(file_name)` | 对突破扫描结果做专项回测报告 |
| `vcp_score_analysis(scan_file, backtest_file)` | VCP 分数与盈亏相关性分析 |
| `backtest_strategy(summary_csv_path, ...)` | 通用信号 CSV 回测（开盘/涨停买、走强持有规则） |
| `analyze_open_minutes_pattern(...)` | 建仓日开盘前 15 分钟形态 vs 胜率赔率 |
| `run_psq_analysis()` | PSQ 综合分析报告 |
| `run_parameter_optimization(config_name)` | 按 YAML 跑参数优化 |
| `generate_optimization_templates()` | 生成 default/quick/grid/compare 配置模板 |

### 7. 形态与市场扫描分析

| 入口 | 说明 |
|------|------|
| `analyze_lianban_stocks(...)` | 连板股筛选 + K 线/汇总（连续板/最高板/非连续板） |
| `analyze_volume_surge_pattern(...)` | 「爆量分歧转一致」形态扫描与 HTML |
| `analyze_gap_up_stocks(...)` | 跳空高开扫描与图表 |
| `find_dragon()` | 龙头股筛选 |
| `find_yidong()` | 严重异动股区间扫描 |
| `find_similar_trends()` | 相似走势检索（加权/DTW 等） |
| `stocks_time_sharing_price()` | 异动股分时分析 |
| `plot_stock_daily_prices()` | 多股日线对比图 |

### 8. 永久投资组合（ETF）

| 入口 | 说明 |
|------|------|
| `permanent_portfolio_backtest()` | 股票/黄金/国债 ETF + 现金等权或 PE 动态现金回测，输出 Markdown + 图 |
| `permanent_portfolio_track()` | 跟踪模式：当前持仓与再平衡建议 |

---

## 项目结构

| 目录 | 作用 |
|------|------|
| `analysis/` | 复盘统计、天梯、形态分析、HTML 图表、永久组合、回测分析等 |
| `alerting/` | 交易/竞价等预警与定时任务（如集合竞价调度） |
| `bin/` | 扫描器、批量回测、参数优化、候选股输出与历史 |
| `data/` | A 股/ETF/指数/龙虎榜/复盘缓存等本地数据 |
| `fetch/` | 行情与复盘数据拉取（含同花顺等） |
| `filters/` | 异动、龙头等过滤逻辑 |
| `strategy/` | 突破、止跌反弹、周量能等策略实现 |
| `excel/` | 复盘天梯、龙头归档、HTML 图表输出等 |
| `utils/` | 日志、日期、同义词、回测可视化等工具 |
| `decorators/` | 自定义装饰器 |
| `labs/` | 实验性代码 |
| `roles/` | LangGPT 角色 Prompt |
| `fonts/` / `images/` / `svg/` / `wordclouds/` / `kline_charts/` | 字体、图片、词云、K 线图表资源 |

## 主要文件

- `main.py`：全部功能入口（见上文）。
- `config.ini`：API 密钥等配置。
- `README.md`：本说明。

## 环境与依赖

- **语言**: Python  
- **系统**: Windows 11（主要开发环境）  
- **虚拟环境**: `conda activate trading`  
- **常用库**: Pandas、NumPy、Matplotlib、数据源相关库等（以环境已装依赖为准）

## todo

- [x] 根据涨停原因对个股分组
- [x] 形态选股区分创业版
- [x] 根据分组叠加日内分时图
- [x] 对非主板股同样获取每日复盘数据
- [x] whimsical归类使用近义词
- [x] 直观展示每日涨停梯队，非主板可以日内跳跃
- [ ] 近义词自动归类优化
- [ ] 拉取每日数据临界区优化
- [ ] 拉取每日数据自动处理反爬
- [ ] 把关注度和涨幅纳入天梯入选条件中
- [ ] 统计二板定龙头的胜率和盈亏比
