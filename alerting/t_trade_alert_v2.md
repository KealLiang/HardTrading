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
- 统一格式日志：
  - 【T警告】[股票名 代码] BUY/SELL-背离 价格变动:xx% MACD变动:xx% 现价:xx.xx [时间]
- 蜂鸣：BUY=1500Hz，SELL=500Hz
- 推送：飞书（可选）

### 6. 接口与运行示例
- 脚本运行（__main__）：
  - IS_BACKTEST=True/False
  - 回测区间：backtest_start/end，例如 "2025-08-26 09:30" ~ "2025-08-26 15:00"
  - symbols=['002536','600111']
- 库使用：
  ```python
  from alerting.t_trade_alert_v2 import MonitorManagerV2
  manager = MonitorManagerV2(['600519','000001'], is_backtest=False)
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
- REPEAT_PRICE_CHANGE=0.05（重复信号最小价格偏移；增大→更少重复，更收紧；减小→更频繁，更宽松）
- MACD/KDJ 基本参数（12/26/9、9/3/3）按你习惯即可，不在此赘述

### 9. 注意事项
- 1分钟级别噪声较大，建议结合成交额过滤（例如 amount 放量时信号权重更高）后续可扩展
- 回测与实时使用不同数据源，K线细节可能有差异，参数需要按交易标的和市场环境调优
- 若 pytdx 连接不稳定，HOSTS 里可配置多个服务器轮询

