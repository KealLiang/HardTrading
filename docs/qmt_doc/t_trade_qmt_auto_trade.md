# V5 做T信号 → QMT/纸面自动交易（本次实现）

> 对应代码目录：`execution/t_trade_qmt/`  
> **不修改** `alerting/t_trade_alert_v5.py`。  
> 注意：仓库里已有的 `docs/qmt_xtquant_quickstart.md` 是更早的通用 QMT API 速查，**不是**本文档。

---

## 1. QMT 是什么

| 概念 | 含义 |
|------|------|
| QMT / MiniQMT | 迅投的量化交易客户端（Windows），登录券商账号后常驻 |
| xtquant | QMT 对外的 Python SDK（下单/撤单/查资金持仓） |
| 关系 | 你的 Python 脚本 ↔ xtquant ↔ 本机已登录的 QMT ↔ 券商柜台 |

没有安装并登录 QMT 时，**无法真下单**。  
本包用 `dry_run=True` + `DryRunBroker`，在本地记账，**不依赖 QMT/xtquant**。

---

## 2. 本次实现解决什么问题

把 V5「出信号 → 飞书手动下单」扩展为可选的：

```
V5 信号 →（可选）飞书照旧 → 风控 → DryRun纸面 / 真实QMT 下单
```

插拔方式：子类覆盖 `_trigger_signal`，原 V5 入口完全不动。

```
MonitorManagerV5 / TMonitorV5          ← 原飞书监控
        ↑ 继承
QmtAutoManagerV5 / QmtAutoMonitorV5    ← 新入口：飞书 + 自动执行
```

---

## 3. 目录与入口

| 路径 | 作用 |
|------|------|
| `trade_config.py` | 账号、本金、干跑、仓位/频控（勿命名为 config.py） |
| `broker.py` | `DryRunBroker`（纸面）/ `QmtBroker`（真盘） |
| `risk.py` | 疑似跳过、同向防抖、日内上限 |
| `executor.py` | 信号 → 风控 → 下单 |
| `auto_monitor.py` | V5 子类钩子 |
| `symbols.py` | `600000` ↔ `600000.SH` |
| `demo_dry_run.py` | **链路冒烟**：假信号验证下单/风控 |
| `demo_paper_backtest.py` | **收益模拟**：V5 历史信号 + 10 万纸面账户 |
| `run_with_v5.py` | **实时监控挂接**（默认可 dry_run） |

---

## 4. 依赖装了吗？（你没装 QMT 客户端）

当前 `conda` 环境 `trading`（Python **3.11.13 64 位**）：

| 依赖 | 是否必需 | 当前状态 |
|------|----------|----------|
| Python 3.6–3.12 64 位 | 真连 QMT 时需要 | 已满足 |
| 项目原有包（pandas 等） | V5 / 纸面回测需要 | 沿用现有环境 |
| **xtquant** | 仅真连 QMT | **未安装**（`ModuleNotFoundError`） |
| **QMT 客户端** | 仅真连 QMT | **未安装**（按你的说明） |

结论：

- **纸面模拟 / dry_run：可以跑，不需要 QMT、不需要 xtquant。**
- **真自动下单：还不行**，需安装 MiniQMT → 登录 → 配置 `userdata_path` / `account_id`，并把 xtquant 加入环境（QMT 自带或 pip）。

---

## 5. 三种「模拟」分别是什么（容易混）

| 模式 | 命令 | 是不是回测 | 要不要 QMT | 能不能看收益 |
|------|------|------------|------------|--------------|
| A. 链路冒烟 | `python -m execution.t_trade_qmt.demo_dry_run` | 否（假信号） | 否 | 否（只验证买卖记账） |
| B. 纸面收益回测 | `python -m execution.t_trade_qmt.demo_paper_backtest` | **是**（V5 历史信号） | 否 | **是**（默认 10 万本金） |
| C. 实时监控 dry_run | `python -m execution.t_trade_qmt.run_with_v5` | 否（实时行情） | 否（dry_run） | 过程记账，非完整区间报告 |
| D. 真盘 LIVE | 同上，`dry_run=False` | 否 | **要** | 实盘成交 |

本次第一版 `demo_dry_run` 只做了 **A**。  
你问的「假设 10 万、按信号看最终收益」对应 **B**（已补上）。

补充：

- **B = 策略回测信号 + 本地纸面成交**，不是 QMT 仿真柜台。
- **C = 实时监控模拟下单**，信号来自盘中，不是历史区间收益回测。
- V5 自己的 `is_backtest=True` 会打印信号/画图；本包的 B 是在那之后把信号灌进纸面账户算权益。

---

## 6. 怎么跑

```powershell
conda activate trading

# A. 链路冒烟（假信号）
python -m execution.t_trade_qmt.demo_dry_run

# B. 10 万本金 + V5 历史信号 → 期末收益
python -m execution.t_trade_qmt.demo_paper_backtest

# C. 挂到实时 V5（默认 dry_run，仍会飞书）
python -m execution.t_trade_qmt.run_with_v5
```

**PyCharm 直接 Run 脚本也可以**：入口文件开头已把项目根加入 `sys.path`。

> 曾用文件名 `config.py`，会与项目根 `config/`（`config.holder`）冲突；已改名为 `trade_config.py`。

纸面回测可在 `demo_paper_backtest.py` 的 `main()` 里改：

- `symbols`
- `backtest_start` / `backtest_end`
- `initial_cash=100000`
- `order_volume`

数据源与 V5 回测相同。`demo_paper_backtest.py` 默认用 **akshare** + 近期区间（本机通达信超时也可跑）；可改回 `tdx`。

---

## 7. 纸面回测规则（B 模式）

- 初始现金：默认 `100_000`
- 每笔固定股数：默认 `100`（可改）
- **T+1**：当日买入，次日才可卖
- 空仓遇到 `SELL`：拒绝（做 T 实盘通常要有底仓；纯空仓跟信号会少成交）
- 期末权益 = 现金 + 残留持仓按回测末日收盘价估值
- 未计：佣金、印花税、滑点冲击（可后续加）

---

## 8. 接到真 QMT（可选）

1. 安装并登录 MiniQMT，保持在线解锁  
2. 配置 `QmtTradeConfig`：
   - `userdata_path`（如 `...\userdata_mini`）
   - `account_id`
   - `xtquant_site_packages`（若 pip 未装 xtquant）
   - `dry_run=False`
3. 先用最小资金 / 仿真权限验证，再考虑实盘

通用 API 说明仍可参考：`docs/qmt_xtquant_quickstart.md`。

---

## 9. 安全默认值

- 默认 `dry_run=True`，不会真下单  
- `skip_suspicious=True`：实时自动交易默认跳过「疑似」信号（纸面回测脚本里为统计完整性默认关闭）  
- 同向防抖、日内笔数上限可在 `config.py` 调整  

---

## 10. 与原监控的关系

| 入口 | 行为 |
|------|------|
| `python alerting/t_trade_alert_v5.py` | 仅监控 + 飞书（原样） |
| `python -m execution.t_trade_qmt.run_with_v5` | 监控 + 飞书 + 自动执行层 |
| `python -m execution.t_trade_qmt.demo_paper_backtest` | 历史信号纸面收益，不启实时监控 |
