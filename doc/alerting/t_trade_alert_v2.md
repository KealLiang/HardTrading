## 做T监控 V2（t_trade_alert_v2.py）设计说明

### 1. 目标与变化点
- 目标：在 1 分钟级别上对个股进行日内做T监控，输出买/卖预警
- 主要变化：
  1) 基于 MACD 背离，结合 KDJ 确认局部顶/底（核心）
  2) 移除双顶双底相关逻辑（降低复杂度与误报）
  3) 保留防重复机制

### 2. 输入与数据源
- 实时：pytdx get_security_bars(category=7, 1分钟)
- 回测：akshare stock_zh_a_minute(symbol=sh/szXXXXXX, period="1", adjust="qfq")
- 股票代码：6位数字（如 '600519'）。内部用 utils.stock_util.convert_stock_code 转换为 sh/sz 代码（回测路径）

### 3. 指标与参数
- MACD(12,26,9)：DIF=EMA12-EMA26，DEA=EMA(DIF,9)，MACD柱=2*(DIF-DEA)
- KDJ(9,3,3)：
  - RSV = (C - L9) / (H9 - L9) * 100（实现中显式使用 float 与 numpy.nan，避免 pandas 将来版本的 dtype 降级告警）
  - K = EMA(RSV,3), D = EMA(K,3), J = 3K - 2D
- 极值窗口 EXTREME_WINDOW：仅用过去 window 内数据判断“当前K是否为局部峰/谷”（默认120根）
- 滚动窗口 MAX_HISTORY_BARS：参与计算的最大K线数量（默认360）
- 背离阈值：
  - 价格创新高/低阈值：2%（PRICE_DIFF_{SELL|BUY}_THR）
  - MACD差异阈值：15%（MACD_DIFF_THR），以相对前极值 MACD 的比例衡量
- KDJ 确认：
  - 顶部：高位区（K>80 且 D>80）并在最近 KD_CROSS_LOOKBACK 根内发生死叉（K 下穿 D）或 J 高位回落
  - 底部：低位区（K<20 且 D<20）并在最近 KD_CROSS_LOOKBACK 根内发生金叉（K 上穿 D）或 J 低位反弹
  - KD_CROSS_LOOKBACK 默认 3 根
  - ALIGN_TOLERANCE：信号对齐容忍（单位：根K线），允许 KDJ 与 MACD 背离在 ±N 根内完成配对；默认 2 根
- 防重复：
  - 同日同价或同时间戳信号去重
  - 同方向同类型信号仅在价格偏离上次记录价超过 REPEAT_PRICE_CHANGE（默认5%）时允许重复

### 4. 触发规则（精简版）
- 局部峰（卖出关注）
  - 条件A：当前K为局部峰（HIGH 为最近 EXTREME_WINDOW 内最大值）
  - 条件B：与历史任一峰比较，价格新高超过 PRICE_DIFF_SELL_THR 且 MACD 未创新高（下降至少 MACD_DIFF_THR）
  - 条件C：KDJ 顶部确认（高位+死叉/回落在 KD_CROSS_LOOKBACK 内）
  - 触发：SELL-背离
- 局部谷（买入关注）
  - 条件A：当前K为局部谷（LOW 为最近 EXTREME_WINDOW 内最小值）
  - 条件B：与历史任一谷比较，价格新低超过 PRICE_DIFF_BUY_THR 且 MACD 未创新低（上升至少 MACD_DIFF_THR）
  - 条件C：KDJ 底部确认（低位+金叉/反弹在 KD_CROSS_LOOKBACK 内）
  - 触发：BUY-背离

### 5. 输出
- 输出：日志+蜂鸣，支持飞书推送
  - 日志模板：
    - 默认（DIAG=False）：
      【T警告】[股票名 代码] BUY/SELL信号！ 价格变动：x% MACD变动：y% KDJ(K,D,J) 现价：p [时间]
    - 调试（DIAG=True）：
      【T警告】[股票名 代码] BUY/SELL-背离 价格变动：x% MACD变动：y% KDJ(K,D,J) 现价：p [时间] | path=…
      其中 path 含义：
      - path=immediate MACD@t1->@t2：背离与KDJ确认在同一根/容忍回溯内即时满足（无待确认）；
      - path=pending MACD@t1 KDJ@t2 lag=n：t1 为检测到 MACD 背离的候选时刻，t2 为 KDJ 补确认时刻；n 为 (t2−t1) 的分钟数，且 0 ≤ n ≤ ALIGN_TOLERANCE。

- 统一格式日志：
  - 【T警告】[股票名 代码] BUY/SELL-背离 价格变动:xx% MACD变动:xx% 现价:xx.xx [时间]
- 蜂鸣：BUY=1500Hz，SELL=500Hz
- 推送：飞书（可选）

### 6. 接口与运行示例
- 脚本运行（__main__）：
  - IS_BACKTEST=True/False
  - 回测区间：backtest_start/end，例如 "2025-08-26 09:30" ~ "2025-08-26 15:00"
  - 支持两种方式指定标的：
    1) 直接传入列表：`symbols=['002536','600111']`
    2) 文本文件热加载：`symbols_file='watchlist.txt'`（每行一个6位代码，支持 `#` 注释）。文件变更将自动应用，无需重启。
- 库使用：
  ```python
  from alerting.t_trade_alert_v2 import MonitorManagerV2
  manager = MonitorManagerV2(['600519','000001'], is_backtest=False)
  manager.start()
  ```
  或使用热加载：
  ```python
  manager = MonitorManagerV2([], is_backtest=False, symbols_file='watchlist.txt')
  manager.start()
  ```

### 7. 关键实现要点（代码将按此实现）
- 结构：TMonitorConfigV2 / TMonitorV2 / MonitorManagerV2，与 v1 类似
- 指标计算：_calc_macd(df), _calc_kdj(df)
- 极值判定：_is_local_peak(i)/_is_local_trough(i) 只用过去 window 内数据
- 背离与KDJ确认：_confirm_top_by_kdj(df, i), _confirm_bottom_by_kdj(df, i)
- 信号检测：_detect_signals(df)：遍历 i>=window，若峰/谷 -> 背离 -> KDJ确认 -> 触发
- 防重复：同日同价/同时间戳去重 + 价格偏离阈值（REPEAT_PRICE_CHANGE）

### 8. 参数表（默认值）与调参指引（宽松 vs 收紧）
- EXTREME_WINDOW=120（窗口越大→更“收紧”：极值更严格，信号更少但更稳定；越小→更“宽松”）
- MAX_HISTORY_BARS=360（仅影响计算窗口长度，一般不需改）
- PRICE_DIFF_BUY_THR=0.02，PRICE_DIFF_SELL_THR=0.02（价格创新高/低要求；提高→收紧，降低→宽松）
- MACD_DIFF_THR=0.15（MACD 背离幅度；提高→收紧，降低→宽松）
- KD_HIGH=80，KD_LOW=20（KDJ 高/低位判定；提高 KD_HIGH/降低 KD_LOW → 收紧；反之→宽松）
- KD_CROSS_LOOKBACK=3（允许叉在近 N 根内出现；减小→收紧，增大→宽松）
- ALIGN_TOLERANCE=2（KDJ 与 MACD 背离对齐的容忍度；减小→收紧，增大→宽松；为0表示必须同K线）
- MAX_PEAK_LOOKBACK=60（仅在最近 M 个峰/谷内寻找参照；减小→收紧，增大→宽松；可按标的波动调节）
- REPEAT_PRICE_CHANGE=0.05（重复信号最小价格偏移；增大→更少重复，更收紧；减小→更频繁，更宽松）
- MACD/KDJ 基本参数（12/26/9、9/3/3）按你习惯即可，不在此赘述

### 9. 注意事项
- 1分钟级别噪声较大，建议结合成交额过滤（例如 amount 放量时信号权重更高）后续可扩展
- 回测与实时使用不同数据源，K线细节可能有差异，参数需要按交易标的和市场环境调优
- 若 pytdx 连接不稳定，HOSTS 里可配置多个服务器轮询



### 10. 优化建议（不改代码也能先按此口径人工参考）
- 成交量/额的“放量”建议（避免开收盘误判）
  - 使用“分钟内季节性校正”：为一天的每个分钟 t 建立基准 amount_baseline[t]（近N日同分钟成交额均值/中位数），定义 ratio = 当分钟成交额 / amount_baseline[t]。当 ratio>阈值（如1.5）视作“相对放量”。
  - 采用“加权”而非“硬过滤”：当 ratio 较高时提升信号权重（或建议更大仓位），而不是直接过滤掉非放量分钟，避免 9:30/15:00 的天然放量误伤信号。
  - 优先使用“成交额”而非“成交量”，不同价位的标的可比性更好；也可用当日滚动30分钟 z-score(amount) 做补充判断。
- 交易时段保护（意图说明）
  - 目的：规避开盘价差和收盘撮合前的极端波动/流动性问题，减少误触、保证可执行性。
  - 建议：默认忽略 9:30–9:33、13:00–13:02、14:57–15:00 的信号或对这些时段赋予较低权重；对 9:30–9:40 采用更严格阈值（“收紧”）。
- 辅助指标用于“仓位指导”（示例口径，可作为加权项）
  - 均线趋势框架（EMA5/EMA20，1分钟）：
    - BUY 信号：若 close>EMA5>EMA20，加 +0.25；若 close<EMA5<EMA20，加 -0.25。
    - SELL 信号：若 close<EMA5<EMA20，加 +0.25；若 close>EMA5>EMA20，加 -0.25。
  - VWAP 对齐：BUY 时 close≥VWAP 加 +0.2（趋势跟随口径）；若走均值回归风格可改为 close≤VWAP 加 +0.2。
  - 布林带（20,2）：BUY 且 close 接近下轨（或下穿后回到轨内）加 +0.2；SELL 且 close 接近上轨加 +0.2。
  - 波动与风险（ATR14，1分钟）：用 ATR 做“单位风险”，仓位 ≈ 目标风险/ATR，波动大则减仓，波动小则可加仓。
  - 成交额加权：使用前述 ratio 或 z-score(amount)；ratio>1.5 则 +0.1～+0.2，1.0～1.5 则 +0.05。

### 11. 可选增强：弱提示与仓位建议（Position Score）
- 开关
  - ENABLE_WEAK_HINTS（默认 True）：开启“高位/低位减速无背离”的弱提示
  - ENABLE_POSITION_SCORE（默认 True）：开启仓位建议（-1~1 映射到 10%/60%/100% 档位）
- 弱提示逻辑（简要）
  - SELL-减速：K、D 均处于高位区(K>D>KD_HIGH)，且 MACD 柱连续走弱或 DIF 接近/下穿 DEA；当根为局部峰但未满足背离阈值时提示
  - BUY-减速：K、D 均处于低位区(K<D<KD_LOW)，且 MACD 柱连续走强或 DIF 接近/上穿 DEA；当根为局部谷但未满足背离阈值时提示
  - 去重：为防止信号刷屏，增加动态冷却：在 N 根K线（WEAK_COOLDOWN_BARS，建议值10）的冷却期内，若价格重新触及短期均线（如反穿EMA5），则允许再次提示，否则将屏蔽。
  - 日志：【弱提示】[股票名 代码] SELL/BUY-减速 现价：p [时间]
- 仓位建议 Position Score（仅在强信号触发时计算）
  - 评分释义与仓位映射：`score≤0.2 → 10%`、`0.2<score≤0.5 → 60%`、`score>0.5 → 100%`
    - BUY 信号：百分比代表建议投入的仓位（如 60%）
    - SELL 信号：百分比代表建议卖出的现有仓位比例（如 100% 表示清仓）
  - 组成（默认权重，可在代码内修改）：
    - 趋势（EMA5/EMA20）：trend=+1(多头阶梯 close>EMA5>EMA20)，-1(空头阶梯)，否则0；W_TREND=0.4
    - 布林带位置（20,2）：bb_pos=(close−mid)/(upper−mid)，BUY取 −bb_pos，SELL取 +bb_pos；W_BB=0.3
    - 量能（可选）：若有 vol，则 vol_ratio=vol/mean(vol,30)，vol_score≈clip((ratio−1)/(1.5−1),0,1)；W_VOL=0.2
  - 汇总：`score = clip((W_TREND*trend + W_BB*bb + W_VOL*vol) * atr_factor, −1, 1)`

### 12. 自选股热加载
- 功能：通过文本文件（默认 `watchlist.txt`）维护待监控股票列表，支持热加载，无需重启。
- 位置：可传绝对路径；相对路径以项目根目录为基准（代码中通过 `parent_dir` 解析）。
- 文件格式：
  - 每行一个 6 位股票代码（如 `600519`）
  - 支持空行与以 `#` 开头的注释；支持行内注释（`600519  # 贵州茅台`）
- 生效时机：文件保存后 5 秒内自动检测到变化并应用（可通过 `reload_interval_sec` 调整）。
- 使用方式：
  - 直接运行脚本：默认会尝试读取项目根目录下的 `watchlist.txt`；若不存在则回退到 `symbols` 列表参数
  - 作为库：`MonitorManagerV2(symbols=[], symbols_file='watchlist.txt', is_backtest=False)`
- 限制：
  - 回测模式（is_backtest=True）不启用热加载
  - 动态增删标的会在下一轮轮询后生效；移除标的的线程将在最多 1 分钟内优雅退出
