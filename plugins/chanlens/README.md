# ChanLens 缠论透镜

自绘 K 线 + 缠论结构叠层的浏览器扩展。**所有源码都在你手里**，觉得哪条规则不对，直接改。

## 为什么是"自绘"而不是"叠加在原图上"

StructGuide 那类插件把结构画在网站自己的 canvas 上，坐标要靠"数格子"反推，
网站一改版、DPR 一变、缩放一动就会错位。本插件反过来：**K 线也是我们自己画的**，
每个像素坐标都是自己算出来的，物理上不可能错位。

代价：和原网站自带指标不能共存。收益：坐标永远准、想加什么指标自己加、
多级别联动（叠加方案根本做不到）成为可能。

## 安装（Chrome / Edge）

1. 打开 `chrome://extensions`（Edge 是 `edge://extensions`）
2. 右上角打开「开发者模式」
3. 点「加载已解压的扩展程序」，选择本目录 `D:\Trading\plugins\chanlens`
4. 打开任意支持站点的个股页面，右下角出现蓝色「缠」按钮即成功

支持站点：雪球 / 新浪财经 / 东方财富 / 同花顺 / TradingView（自动从 URL 识别股票代码，
识别不到会弹窗让你手输 6 位代码）。

## 功能

| 功能 | 说明 |
|------|------|
| 缠论结构 | 包含处理 → 分型 → 笔 → 线段 → 中枢，实线=已确认，虚线=待确认 |
| 背驰 | 相邻两笔同向走势力度对比（MACD 柱面积），标注比值 |
| 三类买卖点 | 一类(背驰极值) / 二类(回抽不破) / 三类(回抽不入中枢) |
| 多级别联动 | 最多三个周期同屏，**共享时间轴**，任意一张缩放/平移，其余同步 |
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
│   ├── datasource.js        content 侧行情请求 + 时间戳标准化 + 导出
│   └── content.js           主入口：串起 拉数据→引擎→渲染→面板
├── core/
│   ├── indicators.js        EMA / MACD / 区间力度
│   └── chan.js              ★ 缠论引擎（纯函数、无 DOM，Node 可直接测）
├── chart/
│   └── renderer.js          K 线 + 叠层 canvas 渲染、缩放/平移/十字光标
├── ui/
│   ├── panel.js             控制面板（参数表驱动，加参数=加一行 schema）
│   └── panel.css
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
| 多级别联动 | 无 | 三周期同屏时间轴联动 |
| 参数 | 只有图层开关 | 全部算法参数可视化 |
| 回测接入 | 无 | JSON 导出 + 同算法 Python 引擎 |
