## 封单变化监控（fengdan_alert.py）

### 1. 代码简介
- 用途：盘中监控个股在涨停/跌停附近的一档盘口封单（买一/卖一）金额变化
- 当价格接近涨停价且买一额较上一笔显著减少，或接近跌停价且卖一额显著减少时，触发预警（日志、蜂鸣、飞书）
- 依赖数据源：pytdx 实时行情（默认服务器 202.96.138.90:7709），股票基础信息使用 akshare

### 2. 使用说明
- 环境准备（Windows）
  - 激活虚拟环境：`.venv-3.11\\Scripts\\activate`
  - 安装依赖（若未安装）：`pip install pytdx akshare`
  - 配置飞书机器人：编辑 `alerting/push/feishu_msg.py`，设置 `webhoook_url`
- 运行方式
  - 直接脚本运行（使用脚本内的示例列表）
    - 从项目根目录：`python alerting\\fengdan_alert.py`
    - 或从 alerting 目录：`python fengdan_alert.py`
  - 以库方式调用
    - Python 交互式/脚本：
      ```python
      from alerting.fengdan_alert import monitor_multiple_stocks
      monitor_multiple_stocks(['600519', '000001'], decrease_ratio=0.08, push_msg=True)
      ```

#### 参数说明
- LimitMonitor(stock_code, decrease_ratio=0.05, trade_date=None, push_msg=True)
  - stock_code：6位股票代码字符串，如 '600519'
  - decrease_ratio：封单减少触发阈值占比，0.05 表示减少≥5%触发
  - trade_date：交易日期，默认当天（字符串 yyyyMMdd），当前逻辑仅用于初始化
  - push_msg：是否发送飞书通知（同时会蜂鸣）
- 全局/内部参数
  - tdx_host：行情服务器地址，默认 '202.96.138.90'（端口 7709）
  - price_threshold：认定“接近涨跌停价”的价差阈值（默认为 0.01 元）
- monitor_multiple_stocks(stock_codes, decrease_ratio=0.05, push_msg=True)
  - stock_codes：股票代码列表
  - decrease_ratio：同上
  - push_msg：同上

#### 简单举例
- 监控单只：买一额在涨停附近减少≥10%告警，并推送飞书
  ```python
  from alerting.fengdan_alert import LimitMonitor
  LimitMonitor('600519', decrease_ratio=0.10, push_msg=True).start_monitoring()
  ```
- 监控多只：
  ```python
  from alerting.fengdan_alert import monitor_multiple_stocks
  monitor_multiple_stocks(['600519','000001'], decrease_ratio=0.06, push_msg=False)
  ```

### 3. 实现思路（简要）
- 用 pytdx 周期性拉取 Level1 五档中的一档数据（买一价/量、卖一价/量、现价）
- 计算买一额/卖一额（价×量），与上一笔对比：
  - 若当前价格接近涨停价且买一额相对上一笔减少比例≥阈值，则触发“买一封单减少”预警
  - 若当前价格接近跌停价且卖一额相对上一笔减少比例≥阈值，则触发“卖一封单减少”预警
- 每隔若干次循环输出一条行情摘要日志；触发时蜂鸣并（可选）通过飞书推送

### 注意事项
- 需确保 pytdx 行情服务器连通；可用内置 `test_pytdx_connection()` 做连通性检查
- akshare 仅用于获取股票简称；行情全由 pytdx 提供
- Windows 下使用 winsound 蜂鸣；其他系统可自行替换
- 建议在 9:30–15:00 交易时段运行；间隔默认 3s，可按需修改

