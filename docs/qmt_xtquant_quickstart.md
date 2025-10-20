# QMT/XtQuant 接入快速指南（自动下单/撤单/查询）

> 面向熟悉 Python、但首次使用 QMT 的工程师。只讲如何接入与调用接口，直接可用。

## 0. 前置准备

- 安装并登录 QMT（极速/mini 版），保持客户端常驻在线。
- 找到 QMT 的 `userdata_mini` 路径（示例：`D:\迅投极速交易终端 睿智融科版\userdata_mini`）。
- 确认资金账号（示例：`1000000365`）。
- 股票代码需带交易所后缀：`600000.SH`, `000001.SZ`。
- 建议在本项目虚拟环境中运行：`conda activate trading`。

## 1. 最小可运行示例（同步下单 + 撤单 + 查询）

```python
# qmt_quickstart.py
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant
import time

class TraderCb(XtQuantTraderCallback):
    def on_disconnected(self):
        print('disconnected')
    def on_stock_order(self, order):
        print('order_cb:', order.account_id, order.stock_code, order.order_status, order.order_id)
    def on_stock_trade(self, trade):
        print('trade_cb:', trade.account_id, trade.stock_code, trade.traded_volume, trade.traded_price)
    def on_order_error(self, err):
        print('order_err:', err.order_id, err.error_id, err.error_msg)
    def on_cancel_error(self, err):
        print('cancel_err:', err.order_id, err.error_id, err.error_msg)
    def on_order_stock_async_response(self, resp):
        print('async_resp:', resp.account_id, resp.order_id, resp.seq)

# 1) 创建交易会话并连接
QMT_USERDATA_PATH = r'D:\迅投极速交易终端 睿智融科版\userdata_mini'  # 修改为你的路径
SESSION_ID = 1001  # 同一台机器不同策略需使用不同的 session_id
ACCOUNT_ID = '1000000365'  # 修改为你的资金账号

xt = XtQuantTrader(QMT_USERDATA_PATH, SESSION_ID)
cb = TraderCb()
xt.register_callback(cb)
xt.start()  # 启动交易线程

ret = xt.connect()  # 0 表示成功
print('connect:', ret)

acc = StockAccount(ACCOUNT_ID)
ret = xt.subscribe(acc)  # 0 表示成功（订阅后才能收到主推回报）
print('subscribe:', ret)

# 2) 查询资产/持仓/委托/成交
asset = xt.query_stock_asset(acc)
print('cash:', getattr(asset, 'cash', None))

positions = xt.query_stock_positions(acc)
print('positions_cnt:', 0 if not positions else len(positions))

orders = xt.query_stock_orders(acc)
print('orders_cnt:', 0 if not orders else len(orders))

trades = xt.query_stock_trades(acc)
print('trades_cnt:', 0 if not trades else len(trades))

# 3) 同步限价下单（返回 order_id）
code = '600000.SH'
price = 10.50
qty = 200  # A股常见最小申报单位为 100 的整数倍

order_id = xt.order_stock(
    acc,
    code,
    xtconstant.STOCK_BUY,      # 买入：STOCK_BUY；卖出：STOCK_SELL
    qty,
    xtconstant.FIX_PRICE,      # 限价单
    price,
    'strategy_demo',
    'remark'
)
print('order_id:', order_id)

# 4) 撤单（使用上一步返回的 order_id）
if isinstance(order_id, int) and order_id > 0:
    time.sleep(1)  # 给柜台一点处理时间
    cancel_ret = xt.cancel_order_stock(acc, order_id)
    print('cancel_ret:', cancel_ret)  # 0 成功，-1 下发失败

# 5) 阻塞接收回报（可根据需要保留/删除）
# xt.run_forever()
```

运行方式（Windows PowerShell）：

```bash
conda activate trading
python qmt_quickstart.py
```

## 2. 必用接口速查（XtQuantTrader）

- 连接与订阅
  - `start()`：启动交易线程
  - `connect() -> int`：建立交易连接（0 成功）
  - `subscribe(account) -> int`：订阅交易回报（0 成功）
  - `register_callback(callback)`：注册回调（见上文 `TraderCb`）
  - `run_forever()`：阻塞接收回报

- 下单/撤单（股票）
  - `order_stock(account, stock_code, side, volume, price_type, price, strategy, remark) -> int(order_id)`
    - `side`: `xtconstant.STOCK_BUY` / `xtconstant.STOCK_SELL`
    - `price_type`: `xtconstant.FIX_PRICE`（限价）等
  - `order_stock_async(...) -> int(seq)`：异步下单，结果在 `on_order_stock_async_response` 回调中给出 `order_id`
  - `cancel_order_stock(account, order_id) -> int`：撤单（0 成功）

- 查询（当日）
  - `query_stock_asset(account) -> XtAsset`
  - `query_stock_positions(account) -> list[XtPosition]`
  - `query_stock_position(account, stock_code) -> XtPosition | None`
  - `query_stock_orders(account, onlyCancelable: bool=False) -> list[XtOrder]`
  - `query_stock_order(account, order_id) -> XtOrder | None`
  - `query_stock_trades(account) -> list[XtTrade]`

- 回调（重写 `XtQuantTraderCallback` 方法）
  - `on_stock_order(order: XtOrder)`：委托回报
  - `on_stock_trade(trade: XtTrade)`：成交回报
  - `on_order_error(err)` / `on_cancel_error(err)`：下单/撤单失败
  - `on_order_stock_async_response(resp)`：异步下单反馈
  - `on_disconnected()`：断连通知（可在此实现重连）

## 3. 常见参数与返回值

- `connect()`/`subscribe()`：返回 0 表示成功；非 0 表示失败。
- `order_stock()`：返回 `order_id > 0` 表示成功；否则失败（结合 `on_order_error` 查看原因）。
- `cancel_order_stock()`：返回 0 表示撤单指令下发成功；-1 表示失败。
- 价格/数量校验：
  - 价格需符合最小价位变动；
  - 数量需符合最小申报单位（常见 100 的整数倍）；
  - 不得越过涨跌停价。

## 4. 实战建议（最小闭环）

- 启动顺序：`start()` -> `connect()` -> `subscribe()` -> `query_*`（重建镜像） -> `order`/`cancel`。
- 断线重连：实现 `on_disconnected()`，调用 `connect()` 并重新 `subscribe()`；随后 `query_*` 对齐状态。
- 幂等与去重：用本地 `clientOrderId` 自管，柜台以 `order_id` 为准；回报去重依靠回报内唯一键。
- 市价兼容：A 股市价类型在沪深存在差异；若不熟悉，优先使用限价单（`FIX_PRICE`）。

## 5. 多账户与扩展

- 多账户：创建多个 `StockAccount` 并分别 `subscribe()`；各自下单/撤单/查询。
- 异步下单：高并发建议使用 `order_stock_async`，通过 `on_order_stock_async_response` 获取 `order_id` 后入订单簿。
- 行情获取：可另用 `xtdata/xtquant` 行情接口或项目现有行情源；执行层非必需。

## 6. 故障排查

- `connect != 0`：检查 QMT 是否登录/解锁；`userdata_mini` 路径是否正确；同机是否被占用。
- 下单失败：查看 `on_order_error` 的 `error_id/error_msg`；自查价格/数量/权限/涨跌停。
- 收不到回报：是否 `subscribe()` 成功；是否阻塞/存活；是否被防火墙杀掉。

---
以上即为 QMT/XtQuant 接入的可运行最小集。按此整合进你项目的执行层，即可完成“自动买/卖/撤 + 查询”的落地。 