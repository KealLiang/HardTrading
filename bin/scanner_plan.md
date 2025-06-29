# 股票选股器 (Stock Scanner) 开发方案

## 1. 总体目标与核心思想

构建一个独立的选股器脚本 `bin/scanner.py`，它能够根据用户指定的策略（如 `BreakoutStrategy`），在给定的日期范围内，从特定的股票池中筛选出所有触发了"买入"信号的股票。

对于筛选出的每一只候选股，我们将调用现有的回测和可视化流程，生成一张包含 K 线、信号日、预期买入点和预期卖出点的分析图表，以供人工复核。

## 2. 功能需求与实现方案

### 2.1. 灵活的股票池管理

*   **需求**: 默认读取 `bin/candidate_stocks.txt`，也可扫描全市场或自定义列表。
*   **实现**:
    1.  在 `scanner.py` 中创建一个函数 `get_stock_pool(source=None)`。
    2.  如果 `source` 为 `None` (默认)，则读取 `bin/candidate_stocks.txt` 文件，解析出股票代码列表。
    3.  如果 `source` 是一个 Python 列表，则直接使用该列表。
    4.  如果 `source` 是一个特定字符串（如 `'all'`），则遍历 `data/astocks/` 目录，从所有 `.csv` 文件名中提取股票代码。
    5.  该函数将返回一个清洗过的股票代码列表，用于后续扫描。

### 2.2. 无侵入式的策略信号捕获

*   **需求**: 以通用方式捕获策略信号，不修改原始策略代码。
*   **实现**:
    1.  我们将采用 **"运行时动态替换方法"（Monkey Patching）** 的技术。这是一种高级技巧，可以在不改变源代码的情况下，临时改变一个对象（这里指策略实例）的行为。
    2.  在 `scanner.py` 的单股票扫描函数中，当创建策略实例后，我们会动态地用一个自定义的"信号记录器"函数替换掉该实例的 `buy` 方法。
    3.  这个"信号记录器"函数被调用时，它**不会执行实际的买入操作**，而是将当前的日期、价格等信号信息记录到一个列表中。
    4.  **优点**: 此方法完全符合你的要求。它将信号捕获逻辑完全隔离在 `scanner.py` 中，`BreakoutStrategy` 或任何其他策略的源文件都无需任何修改。

### 2.3. 可自定义的扫描时间范围

*   **需求**: 扫描时需指定 `start_date` (必需) 和 `end_date` (可选, 默认为今天)。
*   **实现**:
    1.  `scanner.py` 的主扫描函数 `run_scan` 将接受 `start_date` 和 `end_date` 参数。
    2.  在对单只股票进行扫描时，我们会加载其完整的历史数据，以确保策略中的指标（如均线）有足够的"预热期"。
    3.  在 `backtrader` 运行结束后，我们会从"信号记录器"捕获的信号列表中，筛选出所有日期在 `[start_date, end_date]` 区间内的信号。

### 2.4. 直观的可视化结果

*   **需求**: 为每个选股结果生成类似现有回测的图表，包含信号日、买入日、卖出日三个标记。
*   **实现**:
    1.  **分阶段执行**：扫描归扫描，可视化归可视化。`scanner.py` 的核心职责是产出一个候选股列表，格式为 `[{'code': '000062', 'signal_date': '2020-06-08'}, ...]`。
    2.  **改造可视化流程**:
        *   修改 `simulator.go_trade` 函数，增加一个可选参数 `signal_dates=None`。
        *   修改 `utils/backtrade/visualizer.py` 中的 `analyze_and_visualize_trades` 和 `_plot_single_trade` 函数，使其能够接收并处理这个 `signal_dates` 列表。
        *   在 `_plot_single_trade` 中，除了绘制原有的买卖点（绿色买入、品红卖出），额外增加逻辑：遍历 `signal_dates` 列表，在对应的日期上用**青色圆圈**绘制"信号日"标记。
    3.  **串联流程**:
        *   在 `main.py` 中创建一个新的主函数，例如 `scan_and_visualize()`。
        *   此函数首先调用 `scanner.run_scan()` 得到候选股列表。
        *   然后，遍历这个列表。对于每一个候选股 `result`，调用 `simulator.go_trade()`，并传入 `code=result['code']` 和 `signal_dates=[result['signal_date']]`。
        *   `go_trade` 会像之前一样执行一次完整的、独立的交易回测和分析，但因为我们传入了 `signal_dates`，最终生成的图表会自动包含那个额外的"信号日"标记，完美复现你的需求。

## 3. 数据与文件结构

*   **输入数据**:
    *   股票池: `bin/candidate_stocks.txt`
    *   日线数据: `data/astocks/*.csv`
*   **源代码**:
    *   **新建**: `bin/scanner.py` (核心扫描逻辑)
    *   **修改**:
        *   `main.py` (添加调用扫描和可视化任务的入口函数)
        *   `bin/simulator.py` (修改 `go_trade` 函数以接受 `signal_dates`)
        *   `utils/backtrade/visualizer.py` (修改绘图函数以绘制信号点)
*   **输出结果**:
    *   日志: 控制台打印候选股列表。
    *   图表: `strategy/post_analysis/scanner_results/{股票代码}_{日期范围}/trade_*.png`

## 4. 执行计划

1.  **第一步**: 实现 `bin/scanner.py`，完成股票池读取和核心的"猴子补丁"扫描逻辑。
2.  **第二步**: 修改 `bin/simulator.py` 和 `utils/backtrade/visualizer.py`，打通 `signal_dates` 的传递和绘制通道。
3.  **第三步**: 在 `main.py` 中整合上述功能，创建最终的 `scan_and_visualize()` 入口函数。

---

这份方案将扫描、回测、可视化三个环节清晰地解耦，同时又巧妙地复用了现有能力，确保了代码的健壮性和可维护性。

如果确认此方案，我将开始着手开发。

---

## 5. 第二阶段：重构与优化 (根据用户反馈)

### 5.1. 目标

根据用户提出的新需求，对现有实现进行重构，以提升模块化、易用性和输出结果的清晰度。

### 5.2. 具体需求与实现方案

1.  **逻辑封装到Scanner**:
    *   **需求**: 将 `main.py` 中的扫描和可视化编排逻辑完全移入 `bin/scanner.py`。
    *   **实现**:
        *   在 `bin/scanner.py` 中创建一个新的顶层函数，例如 `run_scanner_and_visualize()`。
        *   此函数将接收所有【扫描配置】作为参数（策略、起止日期、股票池等）。
        *   原先在 `main.py` 中用于循环调用 `simulator.go_trade` 的逻辑将全部迁移到这个新函数中。
        *   `main.py` 中只保留对这个新函数的单行调用，并传入配置字典，保持入口的整洁。

2.  **统一日期格式**:
    *   **需求**: 所有面向用户的日期参数统一使用 `YYYYMMDD` 格式。
    *   **实现**:
        *   `run_scanner_and_visualize()` 函数的 `start_date` 和 `end_date` 参数将接收 `YYYYMMDD` 格式的字符串。
        *   在函数内部，会负责将这些字符串转换为 `datetime` 对象或 `YYYY-MM-DD` 格式，以兼容 `pandas` 和其他底层函数。

3.  **集中化输出目录**:
    *   **需求**: 所有扫描相关的输出（图表、日志）都保存到 `bin/candidate_stocks_result/` 目录下。
    *   **实现**:
        *   修改 `bin/simulator.py` 中的 `go_trade` 函数。
        *   硬编码修改其输出路径逻辑，将所有分析图表的根目录从 `strategy/post_analysis/` 或 `strategy/scanner_results/` 统一改为 `bin/candidate_stocks_result/`。
        *   子目录的命名规则保持不变，以便区分每次扫描或回测的结果。

4.  **增加文本日志**:
    *   **需求**: 在输出目录中生成一个 `.txt` 日志文件，快速汇总所有发现的信号。
    *   **实现**:
        *   在 `run_scanner_and_visualize()` 函数中，扫描完成后、开始可视化之前：
        *   在 `bin/candidate_stocks_result/` 目录下创建一个名为 `scan_summary_{start_date}_{end_date}.txt` 的文件。
        *   将所有扫描到的信号（如：`股票代码: 000062, 信号日期: 2025-06-20`）逐行写入该文件。

5.  **智能默认结束日期**:
    *   **需求**: 当 `end_date` 参数未提供时，默认使用最近的一个A股交易日。
    *   **实现**:
        *   在 `run_scanner_and_visualize()` 函数的开头：
        *   检查 `end_date` 是否为 `None`。
        *   如果是，则调用 `utils.date_util.get_current_or_prev_trading_day()` 函数获取最新的交易日，并将其作为扫描的结束日期。 