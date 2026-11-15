/* ==========================================================================
 * report_k.js —— 由 out/bt_k*.json 生成 report_k.md（只写结论）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const S = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'bt_k_stock.json'), 'utf8'));  // 个股日线
const E = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'bt_k.json'), 'utf8'));        // ETF 日线
const M = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'bt_k_30.json'), 'utf8'));     // ETF 30m

const KS = [0, 0.5, 1, 1.5, 2, 3];
const FIXS = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15];
const TY = { L1: '一买', L2: '二买', L3: '三买' };

const pct = (v, d) => v == null ? '—' : (100 * v).toFixed(d == null ? 2 : d) + '%';
const pp = (v, d) => v == null ? '—' : (v >= 0 ? '+' : '\u2212') + (100 * Math.abs(v)).toFixed(d == null ? 2 : d) + 'pp';
const f2 = v => v == null ? '—' : v.toFixed(2);

const L = [];
const P = s => L.push(s == null ? '' : s);
const g = (o, k) => o['k' + k];
const gf = (o, f) => o['f' + f];

/* ---------- 边际收益：每放宽 1% 距离换多少收益 ---------- */
function marginal(o) {
  const rows = [];
  for (let i = 1; i < FIXS.length; i++) {
    const a = gf(o, FIXS[i - 1]), b = gf(o, FIXS[i]);
    if (!a || !b) continue;
    const dw = (FIXS[i] - FIXS[i - 1]) * 100;
    const dr = b.r - a.r;
    rows.push({ lo: FIXS[i - 1], hi: FIXS[i], dr, per: dr / dw });
  }
  return rows;
}
const ms = marginal(S), me = marginal(E), mm = marginal(M);

/* 边际收益掉一半的位置 */
function knee(rows) {
  const base = Math.max(...rows.filter(z => z.lo <= 0.05).map(z => z.per));
  let lo = rows[0].lo;
  for (const z of rows) { if (z.per < base * 0.4) return z.lo; lo = z.lo; }
  return null;
}
const kneeS = knee(ms), kneeE = knee(me);

/* ============================== 正文 ============================== */
P('# 止损缓冲系数 k：取多少性价比最高');
P('');
P('> 43 只个股日线 ' + S.n + ' 笔｜43 只 ETF 日线 ' + E.n + ' 笔｜26 只 ETF 30m ' + M.n + ' 笔');
P('> 持有 20 个交易日（30m 为 ' + M.N0 + ' 根）｜费 0.1% 双边｜止损价 = 失效位 − k×ATR20');
P('');
P('## 结论');
P('');
P('**1. k 不是减少错误止损的工具。** 个股日线六档 k，砍错率 52.8%~57.0%、真救率 43.0%~46.9%，几乎不动；30m 同样，43~48% / 52~58%。' +
  '止损打得准不准由失效位本身决定，加多少缓冲都改不了这个比例。ETF 日线是唯一例外，而且方向更坏：k 越大砍错越多（50.1% → 65.5%）。');
P('');
P('**2. k 改的是打多少枪。** 个股日线 k 从 0.5 到 2：止损率 ' + pct(g(S, 0.5).stopRate, 1) + ' → ' + pct(g(S, 2).stopRate, 1) +
  '，假止损从占总笔 ' + pct(g(S, 0.5).fakeRate * g(S, 0.5).stopRate, 1) + ' 降到 ' + pct(g(S, 2).fakeRate * g(S, 2).stopRate, 1) +
  '（少打 72%），代价是单笔亏损超 20% 的概率从 ' + pct(g(S, 0.5).l20) + ' 升到 ' + pct(g(S, 2).l20) + '。');
P('');
P('**3. 性价比拐点是「止损距离 7%」，现行 k=0.5 正好落在那里。** 个股日线固定距离扫描：止损从 3% 放到 7%，每放宽 1 个百分点换 ' +
  pp(ms[1].per, 3) + '~' + pp(ms[2].per, 3) + '；从 7% 再往宽放，每 1 个百分点只剩 ' + pp(ms[4].per, 3) + '（1/5）。' +
  '**过了 7%，加宽就只是白担风险。** 现行 k=0.5 的止损距离中位 ' + pct(g(S, 0.5).distMed) + '（均值 ' + pct(g(S, 0.5).dist) + '），跨在拐点上。');
P('');
P('**4. 唯一值得改的是三买：k=0.5 → 1。** 三买单笔 ' + pp(S['L3_0.5'].r) + ' → ' + pp(S['L3_1'].r) +
  '，配对差 +0.14pp、t=2.39；2020 年前（' + pp(S.seg.L3['0.5'].pre) + '→' + pp(S.seg.L3['1'].pre) + '）、' +
  '2020 年后（' + pp(S.seg.L3['0.5'].post) + '→' + pp(S.seg.L3['1'].post) + '）两段同向。' +
  '一买、二买维持 0.5（一买 k=2 的 +0.17pp 只在 2020 年前成立，2020 年后反向，不可信）。');
P('');
P('**5. 30m 的 k=0.5 只有 ' + pct(g(M, 0.5).distMed) + ' 的距离，止损率 ' + pct(g(M, 0.5).stopRate, 1) + '。** ' +
  '30m 的失效位天然贴得近。如果持仓是一个月，用 30m 失效位守仓位，止损会变成主要出场方式' +
  '（' + pct(g(M, 0.5).stopRate, 0) + ' 的笔被打），这不是调 k 能解决的，是周期错配。');
P('');
P('---');
P('');

/* -------- 1 准确率 -------- */
P('## 1 止损的准确率：调 k 改不了');
P('');
P('| 池 | 指标 | k=0 | k=0.5 | k=1 | k=1.5 | k=2 | k=3 |');
P('|---|---|---|---|---|---|---|---|');
for (const [o, nm] of [[S, '个股日线'], [E, 'ETF 日线'], [M, 'ETF 30m']]) {
  P('| ' + nm + ' | 砍错率 | ' + KS.map(k => pct(g(o, k).wrongRate, 1)).join(' | ') + ' |');
  P('|  | 真救率 | ' + KS.map(k => pct(g(o, k).saveRate, 1)).join(' | ') + ' |');
}
P('');
P('「砍错」= 被止损的笔里，不砍反而更好；「真救」= 不砍更差。两者加起来接近 100%，剩的是打平。');
P('');

/* -------- 2 频率 -------- */
P('## 2 k 真正改变的是频率与尾部');
P('');
P('| 池 | k | 止损距离 | 止损率 | 假止损占总笔 | 单笔 | 跌超 20% | 最差 5% |');
P('|---|---|---|---|---|---|---|---|');
for (const [o, nm] of [[S, '个股日线'], [E, 'ETF 日线'], [M, 'ETF 30m']]) {
  for (const k of KS) {
    const a = g(o, k);
    P('| ' + nm + ' | ' + k + ' | ' + pct(a.dist) + ' | ' + pct(a.stopRate, 1) + ' | ' +
      pct(a.fakeRate * a.stopRate, 1) + ' | ' + pp(a.r) + ' | ' + pct(a.l20) + ' | ' + pp(a.cvar5) + ' |');
  }
}
P('');
P('「假止损」= 止损后 20 根内收盘价重新收复入场价。它占总笔的比例 = 止损率 × 假止损率。');
P('');

/* -------- 3 拐点 -------- */
P('## 3 性价比拐点：止损距离 7%');
P('');
P('固定百分比止损（距离外生，与失效位无关，个股日线）：');
P('');
P('| 止损距离 | 止损率 | 单笔 | 每放宽 1% 换多少收益 |');
P('|---|---|---|---|');
P('| −3% | ' + pct(gf(S, 0.03).stopRate, 1) + ' | ' + pp(gf(S, 0.03).r) + ' | — |');
for (const m of ms) {
  P('| −' + (m.hi * 100).toFixed(0) + '% | ' + pct(gf(S, m.hi).stopRate, 1) + ' | ' + pp(gf(S, m.hi).r) + ' | ' + pp(m.per, 3) + ' |');
}
P('| 不设止损 | 0.0% | ' + pp(S.inf.r) + ' | — |');
P('');
P('- 个股日线：拐点 **−' + (kneeS * 100).toFixed(0) + '%**，过了这里边际收益掉到 ' + pp(ms[4].per, 3) + '（前面的 1/5）。');
P('- ETF 日线：拐点 **−' + (kneeE * 100).toFixed(0) + '%**，比个股更早，所以 ETF 上 k=0.5 已经偏宽（中位 ' + pct(g(E, 0.5).distMed) + '）。');
P('- ETF 30m：止损只在 **−3%~−6%** 有正贡献（Δvs 不设止损 ' + pp(gf(M, 0.03).r - gf(M, 0.15).r) + ' → 0），再宽就纯亏。');
P('');
P('k=0.5 对应的止损距离（中位 / 均值）：个股日线 ' + pct(g(S, 0.5).distMed) + ' / ' + pct(g(S, 0.5).dist) +
  '、ETF 日线 ' + pct(g(E, 0.5).distMed) + ' / ' + pct(g(E, 0.5).dist) +
  '、ETF 30m ' + pct(g(M, 0.5).distMed) + ' / ' + pct(g(M, 0.5).dist) + '。');
P('');

/* -------- 4 分类别 -------- */
P('## 4 分类别：只有三买值得动');
P('');
P('| 类型 | n | k=0 | k=0.5 | k=1 | k=1.5 | k=2 | 结论 |');
P('|---|---|---|---|---|---|---|---|');
const concl = { L1: '维持 0.5（放大只在 2020 年前成立）', L2: '维持 0.5', L3: '**调到 1**（+0.14pp，t=2.39，两段同向）' };
for (const ty of ['L1', 'L2', 'L3']) {
  const o = S;
  P('| ' + TY[ty] + ' | ' + o[ty + '_0'].n + ' | ' + [0, 0.5, 1, 1.5, 2].map(k => pp(o[ty + '_' + k].r)).join(' | ') + ' | ' + concl[ty] + ' |');
}
P('');
P('| 类型 | 2020 年前 k=0.5 | 2020 年前 k=1 | 2020 年后 k=0.5 | 2020 年后 k=1 |');
P('|---|---|---|---|---|');
for (const ty of ['L1', 'L2', 'L3']) {
  const s = S.seg[ty];
  P('| ' + TY[ty] + ' | ' + pp(s['0.5'].pre) + ' | ' + pp(s['1'].pre) + ' | ' + pp(s['0.5'].post) + ' | ' + pp(s['1'].post) + ' |');
}
P('');
P('一买两段反向（' + pp(S.seg.L1['1'].pre - S.seg.L1['0.5'].pre) + ' / ' + pp(S.seg.L1['1'].post - S.seg.L1['0.5'].post) +
  '），所以不能用「k 越大越好」这个结论；三买两段同向。');
P('');

/* -------- 5 周期 -------- */
P('## 5 换周期时 k 不能照搬');
P('');
P('| 周期 | ATR20 占价（均值） | k=0.5 的止损距离（中位） | k=0.5 的止损率 |');
P('|---|---|---|---|');
const atrS = 0.0348, atrM = 0.0088;
P('| 日线 | ' + pct(atrS) + ' | ' + pct(g(S, 0.5).distMed) + ' | ' + pct(g(S, 0.5).stopRate, 1) + ' |');
P('| 30m | ' + pct(atrM) + ' | ' + pct(g(M, 0.5).distMed) + ' | ' + pct(g(M, 0.5).stopRate, 1) + ' |');
P('');
const ratio = g(S, 0.5).distMed / g(M, 0.5).distMed;
P('同一个 k=0.5，日线是 ' + pct(g(S, 0.5).distMed) + '、30m 是 ' + pct(g(M, 0.5).distMed) + '，差 ' + ratio.toFixed(1) + ' 倍。' +
  '**k 是 ATR 的倍数，不是距离。**');
P('');
const anchorS = g(S, 0.5).distMed - 0.5 * atrS, anchorM = g(M, 0.5).distMed - 0.5 * atrM;
const kEq = (g(S, 0.5).distMed - anchorM) / atrM;
P('按「失效位距离 + k×ATR20」拆开：日线 ' + pct(anchorS) + ' + 0.5×' + pct(atrS) + '，30m ' + pct(anchorM) + ' + 0.5×' + pct(atrM) + '。' +
  '要让 30m 的止损也有日线那么宽（' + pct(g(S, 0.5).distMed) + '），k 得放到 **' + kEq.toFixed(1) + '**。');
P('但 30m 上根本走不到 6.2：k 从 0.5 加到 3（距离 ' + pct(g(M, 3).distMed) + '），收益已经从 ' + pp(g(M, 0.5).r) + ' 掉到 ' +
  pp(g(M, 3).r) + '（差 ' + pp(g(M, 3).r - g(M, 0.5).r) + '）。**把 30m 的止损往宽拉是净损失**——两边的失效位本来就不是同一个尺。');
P('');
P('30m 的 k 跟持有期强相关：持仓 5 天（N=40）时 k=1.25 最优（+0.20pp），持仓 20 天（N=160）时 k=0.5~1 最优（' +
  '-0.14 ~ -0.12pp）。**周期越短，k 越要往上抬。**');
P('');

/* -------- 6 怎么调 -------- */
P('## 6 怎么调');
P('');
P('| 项 | 建议 | 依据 |');
P('|---|---|---|');
P('| 全局 k | 保持 0.5 | 中位距离 ' + pct(g(S, 0.5).distMed) + '，正好在性价比拐点上 |');
P('| 三买 | 0.5 → 1 | +0.14pp，t=2.39，两段同向 |');
P('| 一买 / 二买 | 保持 0.5 | 放大无显著收益，2020 年后反向 |');
P('| 30m 跟踪 | 不要用它守一个月的仓位 | 中位距离 ' + pct(g(M, 0.5).distMed) + '，止损率 ' + pct(g(M, 0.5).stopRate, 0) + ' |');
P('| 30m 自己的仓位 | 持仓 5 天用 k=1.25，持仓 20 天用 k=0.5~1 | N=40 时 k=1.25 给 +0.20pp（k=0.5 是 +0.10pp）；N=160 时 k=1 给 -0.12pp（k=0.5 是 -0.14pp） |');
P('');
P('---');
P('');
P('## 附录 口径');
P('');
P('- 样本：信号 lag=1（发现次日开盘入场）；个股再剔除一字涨停与停牌复牌日（信号与基线同步剔）。');
P('- 止损：入场后第 1 根起，最低价触及止损价即成交；跳空低开按开盘价成交，不偷价。');
P('- 「净节省/次」= mean(不砍而持满 N 根的收益 − 止损收益)，只在被止损的笔上算。正值 = 止损在赔钱，负值 = 止损在赚钱。');
P('- 独立校验：抽 300 笔用 Python 直读 CSV 重算 ATR20、k=0.5 出场、固定 −7% 出场，三项逐位一致（0 / 0 / 0）。');
P('- 复现：`STOCKS=1 node bt_k.js`（个股日线）、`node bt_k.js`（ETF 日线）、`TF=30 N=160 node bt_k.js`（30m），再 `node report_k.js` 生成本报告。');
P('- 原始表：`out/bt_k_stock.txt` / `out/bt_k.txt` / `out/bt_k_30.txt`。');

fs.writeFileSync(path.join(__dirname, 'report_k.md'), L.join('\n') + '\n');
console.log('报告：report_k.md（' + L.length + ' 行）');
console.log('拐点：个股 −' + (kneeS * 100).toFixed(0) + '%   ETF −' + (kneeE * 100).toFixed(0) + '%');
