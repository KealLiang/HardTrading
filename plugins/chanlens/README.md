# ChanLens 缠论透镜

自绘 K 线 + 缠论结构叠层的浏览器扩展。**所有源码都在你手里**，觉得哪条规则不对，直接改。

## 为什么是"自绘"而不是"叠加在原图上"

StructGuide 那类插件把结构画在网站自己的 canvas 上，坐标要靠"数格子"反推，
网站一改版、DPR 一变、缩放一动就会错位。本插件反过来：**K 线也是我们自己画的**，
每个像素坐标都是自己算出来的，物理上不可能错位。

代价：和原网站自带指标不能共存。收益：坐标永远准、想加什么指标自己加、
多级别联动（叠加方案根本做不到）成为可能。

## 形态：不是站点叠加，而是独立 App

因为 K 线是自绘的，一旦不需要"盖在原图上"，"必须在某个网站里打开"就失去了意义。
所以本插件的主形态是**扩展自己的全屏页面**（`chrome-extension://…/app/app.html`）：
不依赖任何网站，不需要起本地服务器，同时因为扩展页面的 origin 为 null，
拿数据依旧不受 CORS 限制。

站点注入脚本只保留一个用途：你在东财/雪球看盘时，右下角点一下「缠」，
把当前这只股票带进 App。

数据层在 `core/market.js`（纯 fetch、无 chrome 依赖），App 页面**直连**它
（扩展页面有 `host_permissions`，天然免 CORS）；background 只做缓存与
content script 的代理兜底，App 不再依赖消息转发，不会因 service worker
的休眠/重启窗口卡住界面。

## 安装（Chrome / Edge）

1. 打开 `chrome://extensions`（Edge 是 `edge://extensions`）
2. 右上角打开「开发者模式」
3. 点「加载已解压的扩展程序」，选择本目录 `D:\Trading\plugins\chanlens`
4. **点击浏览器工具栏的 ChanLens 图标**打开 App（建议把它固定到工具栏）
   - 若当前正好在个股页面（东财/雪球/新浪/同花顺），会自动带上该只股票
   - 在个股页面也可以点右下角浮动的「缠」按钮进入

App 打开后：顶栏输入代码或拼音/汉字（如 `600519` / `茅台`）搜索，
回车或点选即加入自选；左侧自选股列表点击秒切，**Alt + ↑/↓** 在自选股间循环，
列表项上右键删除。也可直接用 `chrome-extension://<扩展ID>/app/app.html?code=600519` 直达。

**批量导入自选**：顶栏「批量导入」按钮，粘贴一整段即可：

```
600519
SH600036
000001, 300750
601318 中国平安
```

支持一行一个、逗号/空格/分号分隔、`sh/sz` 前缀与点号写法，自动**去重**；
`代码 名称` 混写会带上名称，其余缺失名称在后台并发自动补全。
另外在搜索框直接粘贴含多个代码的文本，会**自动转成批量导入**，`Ctrl+Enter` 确认。

**批量删除自选**：自选栏右上「批量删除」打开弹窗，默认全选，可逐项取消或一键全选/全不选，
点「删除 (Ctrl+Enter)」二次确认后执行，`Esc`/点遮罩关闭。
列表项的名称在获取后会写回本地存储，重启浏览器不丢失；旧数据里缺失/退化为代码的名称，
打开 App 时会自动补全。

## 功能

| 功能 | 说明 |
|------|------|
| 缠论结构 | 包含处理 → 分型 → 笔 → 线段 → 中枢，实线=已确认，虚线=待确认 |
| 背驰 | 相邻两笔同向走势力度对比（MACD 柱面积），标注比值 |
| 三类买卖点 | 一类(背驰极值) / 二类(回抽不破) / 三类(回抽不入中枢) |
| 多级别联动 | 最多三个周期同屏，任意一张缩放/平移，其余**按同比同步**（各周期数据跨度差几十倍，同步绝对时间窗口会跳变，故同步缩放倍数与相对位移）；顶栏「**全览**」按钮一键显示完整区间 |
| 全参数可调 | 笔间隔、线段算法、中枢口径、背驰阈值、MACD 参数……全在右侧面板 |
| 导出 | 一键导出结构 JSON（含笔/线段/中枢/背驰/买卖点），喂给本地 Python 回测 |
| 截图 | 保存当前主图 PNG |

## 目录结构

```
chanlens/
├── manifest.json            MV3 清单
├── background/
│   └── service_worker.js    行情代理（绕开页面 CORS），东财主源 + 新浪备用
├── content/
│   ├── adapters.js          站点适配：从 URL/DOM 识别股票代码
│   ├── datasource.js        行情请求 + 时间戳标准化 + 导出（App 与 content 共用）
│   ├── launcher.js          站点内的浮动入口：识别代码 → 跳 App
│   └── content_legacy.js    旧模式（页面内直接画图）入口，已不从 manifest 引用
├── app/
│   ├── app.html             ★ 主界面：扩展自己的全屏 App 页
│   ├── app.css              外壳布局（顶栏/搜索/自选侧栏）
│   └── app.js               搜索、自选股批量导入与快速切换、串起面板与渲染
├── core/
│   ├── indicators.js        EMA / MACD / 区间力度
│   ├── chan.js              ★ 缠论引擎（纯函数、无 DOM，Node 可直接测）
│   └── market.js            数据层：东财 K线(主)+新浪(备)、搜索、名称反查（SW 与 App 共用）
├── chart/
│   └── renderer.js          K 线 + 叠层 canvas 渲染、缩放/平移/十字光标、zoomBy/panBy/zoomFull
├── ui/
│   ├── panel.js             控制面板（参数表驱动，加参数=加一行 schema）
│   ├── panel.css            面板样式，含嵌入模式（App 外壳使用）
│   └── launcher.css         站点浮动按钮样式
├── python/
│   ├── chan_engine.py       ★ 同一套算法的 Python 版（给 D:\Trading 回测用）
│   └── test_chan_engine.py  与 JS 引擎交叉验证
├── tests/
│   └── test_chan.js         引擎单元测试（node 直接跑）
├── tools/
│   ├── fetch_testdata.py    拉真实行情生成离线 fixture
│   ├── debug_dump.js        打印每一层中间结果（改参数后排查为什么）
│   ├── compare.js           对比不同参数组合的产出 + 背驰诊断
│   └── make_icons.py        生成图标
└── icons/
```

## 常用命令

```bash
# 跑引擎测试（41 项）
node tests/test_chan.js

# 用真实数据打印每一层结构
node tools/debug_dump.js tools/testdata/600519_daily.json
# 带参数
node tools/debug_dump.js tools/testdata/600519_daily.json minFxGap=2 segAlgo=\"feature\"

# 拉新数据做 fixture（股票:周期）
python tools/fetch_testdata.py 600519:daily 000001:30m

# Python 引擎测试（含与 JS 的交叉验证）
python python/test_chan_engine.py
```

## 二次开发指南

**改判定规则** → 全部在 `core/chan.js`，每个函数都有注释说明它实现的是缠论哪一条。
改完先跑 `node tests/test_chan.js`，确认没破坏不变量（笔首尾相接、中枢 ZD<ZG、背驰必然力度衰减）。

**加一个参数** → 在 `ui/panel.js` 的 `PARAM_SCHEMA` 里加一行，UI 和持久化自动生效；
引擎侧在 `core/chan.js` 的 `DEFAULTS` 里加同名字段即可。

**加一个网站** → 在 `content/adapters.js` 的 `SITES` 和 `fromUrl()` 里加一条正则。
因为我们是自绘，适配工作只有"识别股票代码"这一件事。

**接入回测** → 页面点「导出JSON」，或在 Python 里直接：
```python
import sys; sys.path.insert(0, r'D:\Trading\plugins\chanlens\python')
from chan_engine import analyze_df
r = analyze_df(df)          # df 来自 fetch.astock_data
print(r['stats'])
```

## 已知边界（诚实声明）

- **线段算法有两种**：默认 `simple`（回调破前低即终结，切分均衡），
  可切换 `feature`（特征序列法，教科书标准，但需要 6 笔以上才能确认第一段，所以线段会很长、末段经常"待确认"——这不是 bug，是缠论本身的性质）。
- **中枢默认用笔算**（`zsSource:'bi'`），颗粒度接近主流工具；教科书口径请切 `seg`。
- **背驰默认滚动三笔比较**（稳定、一定有信号）；`divMode:'zs'` 是严格的
  "被同一中枢隔开的连接波"模式，但中枢首尾相接时它一个信号都不会给。
- 中枢扩展/扩张（中枢升级）尚未实现，只做了延伸。
- 数据来自东方财富/新浪公开接口，仅用于研究与复盘，**不构成任何投资建议**。

## 与 StructGuide 的对比

| | StructGuide | ChanLens |
|---|---|---|
| 源码 | 闭源，无法调整 | 全部源码在本目录 |
| 画在哪 | 叠在网站 canvas 上（可能错位） | 自绘（坐标不可能错） |
| 背驰/买卖点 | 无 | 有，阈值可调 |
| 多级别联动 | 无 | 三周期同屏同比联动 + 「全览」按钮 |
| 参数 | 只有图层开关 | 全部算法参数可视化 |
| 回测接入 | 无 | JSON 导出 + 同算法 Python 引擎 |
