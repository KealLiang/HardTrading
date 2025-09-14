## 做T监控（t_trade_alert.py）

### 1. 代码简介
- 用途：对个股 1 分钟K线进行“背离/双顶双底/连续趋势”监控，实时或回测模式均可
- 指标：自实现 MACD（12,26,9），在局部极值上检测顶/底背离与双顶/双底；可选记录当日内的连续趋势
- 数据来源：
  - 实时模式：pytdx 分钟K（get_security_bars）
  - 回测模式：akshare 分钟数据（stock_zh_a_minute, period="1"）
- 推送：日志+蜂鸣，支持飞书推送

### 2. 使用说明
- 环境准备（Windows）
  - 激活虚拟环境：`.venv-3.11\\Scripts\\activate`
  - 安装依赖（若未安装）：`pip install pytdx akshare pandas tqdm`
  - 配置飞书机器人：`alerting/push/feishu_msg.py` 设置 `webhoook_url`

#### 运行方式
- 从项目根目录：`python alerting\\t_trade_alert.py`
- 从 alerting 目录：`python t_trade_alert.py`
- 也可作为库使用（见下）

#### 脚本内主要开关（__main__）
- IS_BACKTEST：是否回测模式（True/False）
- backtest_start / backtest_end：回测区间，字符串，例："2025-08-27 09:30"
- symbols：监控股票代码列表（6位，不带交易所前缀），例：['002536','600111']
- is_calc_trend：是否启用“连续趋势”日志（通过 MonitorManager 构造注入）

示例：回测两只股票
```bash
python alerting\\t_trade_alert.py
# 在文件内设置：
IS_BACKTEST = True
backtest_start = "2025-08-26 09:30"
backtest_end   = "2025-08-26 15:00"
symbols = ['002536','600111']
```

作为库使用（实时模式，更灵活地传参）：
```python
from alerting.t_trade_alert import MonitorManager
symbols = ['600519','000001']
manager = MonitorManager(symbols, is_backtest=False, is_calc_trend=True)
manager.start()
```

#### 关键参数与含义（TMonitorConfig）
- HOSTS：pytdx 行情主机列表
- MACD_FAST/SLOW/SIGNAL：MACD 参数（默认 12/26/9）
- EXTREME_WINDOW：局部极值判断窗口（默认 120 根K）
- PRICE_DIFF_BUY_THRESHOLD / PRICE_DIFF_SELL_THRESHOLD：价格创新高/低判定阈值（默认 2%）
- MACD_DIFF_THRESHOLD：MACD 背离幅度阈值（默认 15%）
- DOUBLE_EXTREME_PRICE_THRESHOLD：双顶/双底价格相似度阈值（默认 0.5%）
- DOUBLE_EXTREME_MIN/MAX_TIME_WINDOW：双极值间的最小/最大间隔（K线数，10~30）
- KLINE_CATEGORY：pytdx K线类别（7=1分钟）
- MAX_HISTORY_BARS：滚动窗口长度（默认 360 根）
- 趋势相关：
  - TREND_WINDOW：连续极值计数（默认 3）
  - TREND_PRICE_RATIO：连续创新高/低的最小涨跌幅（默认 0.1%）
  - TREND_LOG_COOLDOWN：同向趋势日志冷却窗口（秒，默认 300）
  - TREND_PRICE_CHANGE：同一冷却窗口内，价格变化超过该比例才重复记录（默认 5%）

#### 触发规则（简要）
- 顶背离（SELL-背离）：新峰价格明显创新高且 MACD 未同步创新高（并且当前位置是 MACD 顶部转折）
- 双顶（SELL-双顶）：新峰价格与旧峰接近，时间间隔在阈值内，但 MACD 有明显下降
- 底背离（BUY-背离）：新谷价格明显创新低且 MACD 未同步创新低（并且当前位置是 MACD 底部转折）
- 双底（BUY-双底）：新谷价格与旧谷接近，时间间隔在阈值内，但 MACD 有明显上升
- 防重复：同日同价/同时间戳的信号去重

### 3. 实现思路（简要）
- 滚动窗口：实时/回测均以固定窗口长度（MAX_HISTORY_BARS）参与指标计算，保证一致性
- MACD：基于收盘价的 EMA 计算 DIF/DEA/MACD
- 极值识别：每根新K，只用过去 window 内数据判断当前是否为“局部峰/谷”；检测背离与双顶/双底
- 趋势识别（可选）：当日内最近 n 个极值连续创新高/低，触发趋势日志；同向日志按冷却窗口+最小价差去重
- 预警输出：日志 + winsound 蜂鸣 + 飞书推送（可关）

### 注意事项
- 回测使用 akshare 分钟数据；若数据不足或无数据会直接跳过
- 实时模式需能连接 pytdx 服务器；失败会重试并写日志
- 飞书推送需先配置 webhook；Windows 下的蜂鸣频率：BUY=1500Hz，SELL=500Hz
- K 线时间请使用交易时段；EXTREME_WINDOW 设置过大将延迟信号、过小易造成噪声

