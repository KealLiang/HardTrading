# ChanLens 缠论透镜 —— 项目背景与现状（交接文档）

> 面向其他对话中的 AI / 开发者。读完本文即可直接动手，无需询问项目背景。
> 最后更新：2026-10-07（版本 v28 / 1.9.0 已打包）
> 事实依据：代码仓库实读 + `D:/Coding/apps/.workbuddy/memory/` 工作日志 + `D:/Trading` git 记录（最近提交 `632f56c fix chan three buy issue`）。

---

## 1. 项目概述

### 1.1 定位

自研缠论（缠中说禅）技术分析工具，**源码完全可控、无未来函数、参数全可调**。两种形态，同一份核心代码：

| 形态 | 目录 | 说明 |
|---|---|---|
| Chrome MV3 插件 | `D:/Trading/plugins/chanlens/` | 在行情站点（雪球/新浪/东财/同花顺/TradingView）注入悬浮按钮打开全屏页 |
| Android App（WebView 壳） | `D:/Trading/android/ChanLens/` | 主力形态，手机上离线可用；资产从插件目录**同步**而来，不复制第二份 |

### 1.2 目标用户与痛点

- **用户本人**：A 股短线交易者，缠论体系实践者，持仓周期单股 ≤1 个月，风格为「已启动趋势股回调买入」（即三买型）。
- **解决的痛点**：市面缠论工具源码不可见、参数黑盒、信号画在图上但无法回答「我现在该做什么、什么时候做、错了怎么认」。本项目把**信号 → 计划 → 持续跟踪 → 失效提醒**做成闭环。
- **核心心法（不可违背）**：**日线定方向，30 分钟定时机**。追踪恒按日线级别，30 分钟只负责择时入场。

### 1.3 技术栈与运行环境

- **纯前端、零依赖、无构建**：原生 JS（ES5 风格 IIFE + 全局命名空间）、Canvas 2D 渲染、MV3、`chrome.storage.local`。
- **安卓壳**：单 Activity 全屏 WebView + `@JavascriptInterface` 桥（`CLAndroid`），Kotlin，Gradle。
- **行情数据源**：东方财富 `push2his`（K 线）、新浪/腾讯（报价），多源自动切换 + 45s 本地缓存 + 10min 修复守卫。
- **Node.js（仅开发期）**：跑单测与 Playwright 冒烟测试。托管版路径
  `C:/Users/KealLiang/.workbuddy/binaries/node/versions/22.22.2-3/node.exe`。
- **打包**：`python D:/Coding/apps/Android/tools/build.py D:/Trading/android/ChanLens release` → `sign_release.py`（签名密码 `changeit`）。

---

## 2. 迭代历程

| 阶段 | 版本 | 主要改动 | 解决的问题 / 效果 |
|---|---|---|---|
| 引擎奠基 | — | `core/chan.js`：分型→笔→线段→中枢→背驰→三类买卖点；`chart/renderer.js` 多图联动 | 打通缠论完整结构识别 |
| 插件形态 | 1.0–1.4 | MV3 注入 + 全屏页 + 参数面板 + 自选扫描 | 从工具变成日常可用产品 |
| 安卓移植 | 1.1–1.5 | WebView 壳 + `sync_web.py` 资产同步 + 触摸适配 + 全屏/快捷条 | 手机可用；**单份代码双端生效** |
| K 线与显示 | 1.5.x | 缠论 K 线（`mergedview.js`，含包处理后显示层变换）、光标横线价格轴标注 | 与引擎判定口径解耦，显示可独立演化 |
| 追踪模式 | 1.6.0 | `core/track.js` 落库 + 三句话作战卡（我做什么 / 我错了的标记 / 我打算怎么走） | 从「看图」到「有计划」 |
| 方向自动化 | 1.7.0 | 方向跟信号走（买点=多、卖点=空），删掉用户选方向的菜单 | 消除「看多看空给同一张图」的老 bug |
| 级别跟随 → 固定 | 1.7.1–1.7.3 | 曾按主图级别切换追踪，跨级别守卫/改追；**后被推翻** | 1.8.0 判定：太灵活失去缠论意义，改为固定日线 |
| 跟踪重构 | 1.8.0 | 抽出 `CLScanner.refsFor`（动盈/目标只认方向不认信号）、`updateTiming`、`trackStatusHtml` 状态区三分（已定/在等/动态）+ 左上角摘要点按开卡 + 卡内「已报」行 | 修复「行情走好后跟踪线冻结」致命缺陷；动态跟踪全链路模拟验证 |
| 补漏 | 1.8.1 | 日线反向信号提醒（`updateReverse`）、30 分时机失效（`failTiming`）；参数面板版本脚注 | 补上唯二漏报项 |
| **回测落地** | **1.9.0（当前）** | 反向提醒降级为纯提示；`pickSignal` 同 K 三买优先；三买徽标「回测验证」金色高亮 + 一/二买标「参考」；`reloadData()` 测试钩子 | 落地回测结论：翻转清仓是价值毁灭者，离场只认失效位/动盈 |

### 2.1 支撑决策的 ETF 回测（2026-10-01，勿轻易推翻）

产物在 `D:/Trading/analysis/etf_fail_bt/` 与 `etf_daily_study/`，26 只 ETF、日线全历史逐日切片、零未来函数。

1. **三买是唯一有统计优势的信号**：信号后 10 日 +0.76%（t=2.54），20 日衰减 → 优势短促，**必须配结构出场**。
2. **一/二买与随机买入无差异**（二买最差 -0.61%/笔）→ 只作结构参照，不作开仓依据。
3. **「日线翻转清仓」是价值毁灭者**：占 85% 换手、82% 离场后创新高。去掉它、只用结构出场 → +0.54%/笔（CI [0.02, 1.06] 显著为正）。
4. **失效位冗余**：严格执行最优，加容忍带单调变差 → **不加任何冗余参数**。

> ⚠️ 作废结论：「冗余 ≤0.5% 有效」基于缺三买的旧信号集，已被三买 bug 修复后的重跑推翻，禁止引用。

---

## 3. 当前功能清单

### 3.1 缠论引擎（`core/`，CommonJS + 全局导出，可直接 `require`）

| 模块 | 行数 | 职责 | 导出 |
|---|---|---|---|
| `core/indicators.js` | 85 | MACD / K 线包含处理 | `CLIndicators` |
| `core/chan.js` | 792 | 分型→笔→线段→中枢→背驰→一/二/三类买卖点 | `ChanEngine.analyze(klines, params)` |
| `core/market.js` | 393 | 格式化、周期换算 | `CLMarket` |
| `core/scanner.js` | 291 | 自选批量扫描 + 信号挑选 + 失效位/动盈/目标计算 | `CLScanner` |
| `core/track.js` | 248 | 追踪记录存储 + 三句话计划 + 状态机（纯函数） | `CLTrack` |

**关键接口**（回测/测试直接复用同一份，保证口径一致）：

```js
ChanEngine.analyze(klines, params)          // params 见 DEFAULTS（chan.js:33-57）
CLScanner.pickSignal(klines, res, { maxLag: 10 })   // 挑「正在形成」的信号
CLScanner.refsFor(klines, res, dir, entry, markK)   // 动盈 + 目标（只认方向）
CLScanner.anchorOf(point)                          // 各类信号的失效基准
CLTrack.buildPlan(sig, dir, period, { fmtPrice })  // 三句话作战卡
CLTrack.updateTiming(rec, sig) / failTiming / updateReverse / advanceTrail / refreshTarget / check
```

### 3.2 图表（`chart/`）

- `renderer.js`（803 行）：主图 + 副图（MACD / 成交量）多图联动，滚轮缩放（各图同比）、拖拽平移、十字光标、价格轴标注。
  - **追踪叠加**：`planLines`（目标/失效/动盈三条结构线 + 标签避让）、`planNote` / `planNote2`（左上角两行摘要，含命中矩形 `_noteRect` 供点按开卡）。
- `mergedview.js`（82 行）：缠论 K 线显示视图（含包处理后的显示层变换，**不改判定**）。

### 3.3 自选与扫描（`app/app.js` + `core/scanner.js`）

- 自选管理：分组、拖拽排序、批量导入、删除、名称补全（`mobile/names.js`）。
- 批量扫描：并发 3、每只 200 根、`freshMs` 30 分钟增量、结果持久化（重开页面零请求）。
- 徽标：买红卖绿（A股习惯），**三买金色高亮 `prime`** + title「★ 回测验证」，一/二买 title 标「参考」；虚线边框 = 未确认。
- 行情：10 分钟兜底刷新（页面可见时才刷）+ `refreshQuotes` 手动刷新。

### 3.4 缠论追踪（核心差异化功能，1.6.0–1.9.0）

**触发**：长按自选列表项 → 菜单「追踪（日线 · X买/X卖）」→ 作战卡 → 确认建卡。

**状态区四分法**（`trackStatusHtml`）：

| 分区 | 含义 | 内容 |
|---|---|---|
| **已定** | 建卡定死，永不变 | 方向 · 日线 · 信号 · 参考价 · 失效位 |
| **在等 / 时机** | 等待中 | 30 分同向买点（入场时机）；已到则显示信号名+时间；动盈启动 |
| **动态** | 跟踪演化 | 目标（无参照时写「前高已过，等新结构」）｜ 动盈（只朝有利方向移） |
| **已报** | 提醒留档 | 时机失效 / 已到目标 / 已破失效位 / 已触发动盈 |
| 反向 | 1.9.0 降级为**纯提示** | 日线方向转空/转多（信号名 + 时间）· 仅提示，离场看失效/动盈 |

**失效位规则**（严格缠论语义，全部取自已定型结构）：

- 一买/二买 → 跌破一买低点（卖点对称：升破一卖高点）
- 三买/三卖 → 跌回中枢 ZG / 升回中枢 ZD

**离场只有两条结构线**：失效位、动盈/移动止盈。**没有「日线出卖点就清仓」这条规则**（回测已证明它是价值毁灭者）。

**盯梢提醒**（`CLTrack.check`，只报触发、从不报解除，天然防横跳）：

- 优先级：失效（认错离场）> 目标（减 1/3）> 动盈（落袋）。
- 每类只报一次，`alertedStop/Target/Trail` 置位后永不复位。
- 动盈位只在**上移**时重新允许提醒（语义正确的新跟踪位）。

**去重状态机**：

- 30 分时机：`updateTiming` key = `级别|文案`，同信号不重报，换新信号才报。
- 时机失效：`failTiming` 报完即清 timing → 天然去重；新时机成立后才允许再报。
- 日线反向：`updateReverse` key 去重 + 存档不随消失/同向清除（防横跳）。

### 3.5 安卓壳（`android/ChanLens/`）

- `MainActivity.kt`：单 Activity 全屏 WebView 托管 `assets/index.html`，`addJavascriptInterface(bridge, "CLAndroid")`，支持 CDP 远程调试、`onBackPressed` 交给 JS 拦截。
- `JsBridge.kt`：`httpGet` / `storeGet` / `storeSet` / `saveFile` / `setBackIntercepted` / `setLastCode` / `toast` / `setImmersive`。
- `mobile/` 适配层 11 个模块：`patch`（补 app.js 移动端缺口）、`touch`（K 线手势）、`mark`（跨周期标记）、`ui`（外壳）、`names`（名称）、`cats`（分类）、`fullscreen`、`quickbar`、`bridge`（fetch/area 垫片）。

### 3.6 参数面板（`ui/panel.js`，442 行）

分组可调：K 线形态、笔/线段、中枢、背驰（模式/力度度量/MACD 参数）、买卖点、扫描周期、数据源。全部自动保存（`chanlens.settings.v1`）。**面板底部有版本脚注**（发版时手工维护，见 §6）。

---

## 4. 当前架构与数据流

### 4.1 目录职责

```
D:/Trading/plugins/chanlens/        ← 插件（源码唯一真身）
├── core/          引擎 + 扫描 + 追踪（纯逻辑，无 DOM 依赖，可 node require）
├── chart/         Canvas 渲染
├── ui/panel.*     参数面板（HTML/CSS/JS）
├── app/           全屏主应用（app.html / app.js / app.css）
├── content/       datasource.js（多源行情）、adapters/launcher（站点注入，仅插件）
├── background/    service_worker.js（仅插件）
├── tests/         test_chan 41 / test_market 32 / test_track 95 断言
├── tools/         testdata/（真实切片）、compare、point_audit、walkforward
└── manifest.json  MV3（version 字段停留在 1.0.0，非发布依据）

D:/Trading/android/ChanLens/         ← 安卓壳
├── app/src/main/assets/            ← 由 sync_web.py 同步生成，勿手改
├── app/src/main/java/com/keal/chanlens/  MainActivity / JsBridge / DebugSwitch
├── tools/         sync_web.py、check_web.js、smoke.js、acceptance.js
└── dist/          签名 APK 产物
```

### 4.2 脚本加载顺序（`assets/index.html:189-222`，顺序有依赖，勿随意调整）

```
mobile/bridge.js → core/indicators → core/chan → core/market
→ chart/renderer → chart/mergedview → ui/panel
→ core/scanner → core/track
→ mobile/patch → mobile/mark → content/datasource → app/app
→ mobile/ui → mobile/names → mobile/touch → mobile/cats
→ mobile/fullscreen → mobile/quickbar
```

全局命名空间：`CLIndicators` / `ChanEngine`（`chan.js:18`）/ `CLMarket` / `CLRenderer` / `CLMergedView` / `CLScanner` / `CLTrack` / `CLDataSource` / `ChanLensApp`（测试钩子集中出口）。

### 4.3 核心数据流

```
自选代码
  ├─ CLDataSource.getKlines(code, period, limit, adjust)   45s 本地缓存 → 多源切换
  │     └─ CLDataSource.withTimestamps(data)              补时间戳（渲染/CSV 依赖）
  ├─ ChanEngine.analyze(klines, params) → res { bis, segs, zss, points }
  │     └─ res.points[] 每个点带 _k(标记位) / readyK(确立位) / confirmed / extra{zs,zsZG,zsZD,b1}
  ├─ CLScanner.pickSignal(klines, res, {maxLag:10})        筛 readyK 距末尾 ≤10 的最新点
  ├─ CLScanner.refsFor(klines, res, dir, entry, markK)    动盈/目标（只认方向）
  └─ CLRenderer.create(canvas, {...}) → view.draw()        图表 + 追踪叠加层

追踪链路：
  建卡 → CLTrack.set(trackMap, code, rec)  →  chrome.storage.local['chanlens.track.v1']
  rebuild 尾部 → checkTrackAlerts + advanceTrackTrail + refreshTarget
             → checkTimingAll(force)  拉 30m×200 根现算 → updateTiming / failTiming / updateReverse
```

### 4.4 状态与存储

全部 `chrome.storage.local`（插件）/ 经 `CLAndroid.storeSet` 落到 SharedPreferences（安卓），键名固定：

| KEY | 内容 | 位置 |
|---|---|---|
| `chanlens.watchlist.v1` | 自选列表 | `app/app.js:14` |
| `chanlens.watchcats.v1` | 自选分组 | `app/app.js:86` |
| `chanlens.extra.v1` | 「额外」显隐开关 | `app/app.js:40` |
| `chanlens.track.v1` | 追踪记录 | `core/track.js:35` |
| `chanlens.scan.v1` | 扫描缓存（按 `周期\|代码` 分桶） | `core/scanner.js:17` |
| `chanlens.settings.v1` | 参数面板状态 | `ui/panel.js:13` |

**内存态**：`trackMap`（追踪记录）、`signals`（扫描结果）、`datasets`（各周期 K 线）、`sigCache`（追踪现算信号）、`quotes`（报价）、`views`。

### 4.5 关键常量（改动需谨慎）

```js
// app/app.js:182-189
SCAN  = { period:'daily', limit:200, maxLag:10, freshMs: 30*60*1000 }
TRACK_LIMIT = 800      // 追踪现算取数根数，与看图一致，笔/中枢才对得上
TRACK_PERIOD = 'daily' // 追踪恒日线（1.8.0 起不再跟随主图级别）
TIMING_PERIOD = '30m'
TIMING_FRESH_MS = 2*60*1000
// content/datasource.js
LOCAL_TTL = 45*1000        // 行情本地缓存
FIX_GUARD_MS = 10*60*1000  // 数据源修复守卫
```

---

## 5. 已知问题与待办

### 5.1 缺陷 / 技术债

| # | 问题 | 影响 | 位置 |
|---|---|---|---|
| 1 | 作战卡「三句话」文本是**建卡时的快照**，价格数字不随重算改写 | 与状态区的实时值可能不一致（状态区「动态」行才是实时值） | `core/track.js:62 buildPlan` |
| 2 | 自选列表信号徽标按**扫描周期**（`SCAN.period`）走，可能显示 30m 信号而追踪恒日线 | 徽标与追踪口径可能不同源 | `app/app.js:470` |
| 3 | 提醒只在 App 页面处于前台时发生（WebView 无后台 service） | 锁屏/未打开时错过提醒 | 形态固有约束 |
| 4 | `sigCache` 无 TTL，切片/行情变化后可能读到过期现算信号 | 测试环境已暴露（需手动 `clearSigCache`），真实场景轻微 | `app/app.js:190` |
| 5 | `loadPeriod` 按 code 缓存 `datasets`，不校验数据新鲜度 | 同一会话内行情更新后需 `reloadData()` | `app/app.js:758-760` |
| 6 | `manifest.json` version 停留在 `1.0.0`；`README.md` 停留在 1.5.2 | 文档/元信息与实际版本脱节 | 打包不依赖它们，但易误导 |
| 7 | 三处版本号需手工同步：`build.gradle.kts`、`panel.js` 脚注、dist 文件名 | 漏改导致脚注与实际版本不符（冒烟有断言可兜底 panel.js） | — |

### 5.2 下一步候选需求（按价值排序）

1. **中枢升级为按线段**（ orthodox 缠论路径）：`zsSource: 'seg'` 选项**已存在但未验证**；三买已可用，升级后可能进一步提高三买质量。
2. 更新 `README.md` 与 `manifest.json` 版本，抹平 §5.1 #6。
3. 三句话快照 vs 状态区实时值的口径统一（§5.1 #1），或明确文案标注「建卡时快照」。
4. 徽标与追踪口径统一（§5.1 #2），让徽标恒按日线。
5. `sigCache` 加 TTL 或版本号（§5.1 #4）。
6. 继续回测方向：**只做多 + 费后 + 日线全历史**（当前结论中收益集中于强势行业 beta，需进一步剥离）。

---

## 6. 开发注意事项

### 6.1 铁律（破坏即回归）

1. **严禁未来函数**。信号确认 = 分型右侧 3 根 K 走完（`confirmed`）；回测入场一律「确认次日开盘」。任何新逻辑必须能用「逐日切片」重放验证。
2. **引擎口径不可漂移**：`maxLag = 10`、确认规则、失效位锚点（`anchorOf`）、入场 t+1 —— 改任一项都要重跑回测，否则前后结论不可比。
3. **跟踪推进只认方向，不认信号**。`advanceTrackTrail` 必须调 `CLScanner.refsFor(klines, res, dir, entry, markK)`；**绝不能改回依赖 `pickSignal`**（实测 600519 建卡后 8 根 K 日线即从一买转一卖，跟信号走会导致多头跟踪线冻结）。
4. **`refsFor` 的 `markK` 参数不可丢**：漏掉会把建卡前的高位回撤笔当成动盈（曾导致 `trail=1619.55` 而非正确值）。
5. **离场只有失效位 + 动盈/目标**。新增任何「反向信号即清仓」逻辑前，先看 §2.1 回测结论 3。
6. **UI**：按钮保持单行、控件紧凑、同一行控件 ≤4 个（超出收进「更多」浮层）。

### 6.2 易踩坑点（均为实测踩过）

| 坑 | 说明 |
|---|---|
| **双端代码漂移** | 改完插件**必须**先 `python tools/sync_web.py`（在 `D:/Trading/android/ChanLens` 下跑），否则 assets 还是旧代码；`check_web.js` 会检出漂移并报错 |
| **触摸 vs 鼠标两条路径** | `mobile/touch.js` 在 `touchstart` 里 `preventDefault`，WebView **不合成鼠标事件**。桌面 click（在 `renderer.js`）与触摸 tap（在 `touch.js`）必须各写一份，改一处容易漏另一处 |
| **playwright evaluate 单参数** | `page.evaluate(fn, a, b)` 只支持 1 个参数，多参要包成对象传 |
| **引用 Node 侧常量** | `page.evaluate` 内引用 Node 上下文的常量（如 `M30.length`）会 `ReferenceError`，要么传参要么写死 |
| **vm 作用域隔离** | Node 探针里 `vm.runInContext` 的模块作用域与 global 不共享，必须用 `ctx.CLScanner` 接住 |
| **合成数据扫不出信号** | 锯齿状合成 K 线很难扫出买卖点（一买需「创新低 + 力度衰减」）。**用真实数据切片造剧本**，便宜得多 |
| **引擎改动会打乱冒烟剧本** | 改 `chan.js` 后必须用探针重新扫真实测试数据的信号时间线，再校准 `smoke.js` 的切片游标。例：三买修复后 600519 变为 747-754 一买 / 755-764 二买 / **765 null** / 766-770 三买 / 771-776 一卖 / 777-786 二卖 / 787+ null |
| **冒烟切换切片需两个钩子** | `window.ChanLensApp.reloadData()`（清 datasets 强制重拉）+ `window.ChanLensApp.clearSigCache()`（作废跨切片残留的现算缓存） |
| **发版三处同步** | `build.gradle.kts`（versionCode/versionName）+ `ui/panel.js` 版本脚注 + dist 文件名 |

### 6.3 测试与验证（改完必跑）

```bash
# 1. 静态检查（检出 assets 漂移 / 结构问题）
cd D:/Trading/android/ChanLens && python tools/sync_web.py && node tools/check_web.js

# 2. 单元测试（当前基线：41 / 32 / 95 全过）
cd D:/Trading/plugins/chanlens
node tests/test_chan.js && node tests/test_market.js && node tests/test_track.js

# 3. 端到端冒烟（当前基线：155 项全过，Playwright 驱动真实页面）
cd D:/Trading/android/ChanLens && node tools/smoke.js
```

- 冒烟 §19f 是**动态跟踪模拟**：打桩 `CLDataSource.getKlines` 按游标 `window.__dyn.n` / `__setM` 返回**真实数据切片**，切 tab 或调 `reloadData()` 触发真实 rebuild，全程真引擎零注入。改动追踪逻辑时优先扩展这一段。
- 打包：`python D:/Coding/apps/Android/tools/build.py D:/Trading/android/ChanLens release` → `sign_release.py D:/Trading/android/ChanLens "" chanlens changeit` → 拷 `dist/ChanLens-<version>-release.apk` → `aapt dump badging` 复核。

### 6.4 用户协作偏好

- **AI 只做分析与修复，不直接执行代码**；测试脚本用于验证是可接受的（用户自己跑）。
- 需求沟通方式：小步快跑迭代，先「只回答不动任何东西」做只读分析，再决定改不改代码。
- 交付偏好：言简意赅、客观全面；报告给固定在线链接或直接给产物文件路径（用户自行覆盖安装，设备从未 adb 连接）。
