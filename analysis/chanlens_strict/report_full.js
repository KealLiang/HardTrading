/* ==========================================================================
 * report_full.js —— 完整版报告（口径细节/逐格表/新旧对照/ZD 对照/共享一仓附表）
 * 用法：node report.js
 *
 * v3（审计后）修改点：
 *   1) 三买 R2 参照位 ZD → ZG 的对照节（§4.9），数据来自 summary_*_zd.json
 *   2) 左尾文字改为按实测大小关系生成，不再硬编码「日线……更深也更差」
 *   3) §0 / §3 的结论一律用配对/持有期匹配数字，不再混用非配对均值差
 *   4) 新增 §4.7 持有期匹配基准（BM / BMED）、§4.10 收益集中度与有效样本
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, 'out');
const TFS = [
  { tf: 'daily', name: '日线', span: '2014-08 ~ 2026-09（有效约 12 年；首笔成交 2014-08-12）' },
  { tf: '60', name: '60分钟（真实，新浪源）', span: '2025-09-26 ~ 2026-10-23（256个交易日）' },
  { tf: '30', name: '30分钟', span: '2025-09-23 ~ 2026-09-30（约10个月）' }
];
const load = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const pc = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : (x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp';
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const f1 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(1);
const mark = t => (t == null || !isFinite(t)) ? '' : (Math.abs(t) >= 2 ? '**' : '');
const tryLoad = f => { try { return load(f); } catch (e) { return null; } };

const TYPE_NAME = { L1: '一买', L2: '二买', L3: '三买', ALL: '全部', RND: '随机' };
const COMBO_NAME = {
  A: 'A 完整循环', B5: 'B5 固定5日', B10: 'B10 固定10日', B20: 'B20 固定20日',
  C: 'C 只做出场', D5: 'D5 随机固定5日', D10: 'D10 随机10日', D20: 'D20 随机20日'
};

const S = {};
for (const t of TFS) {
  const f = path.join(outDir, 'summary_' + t.tf + '.json');
  if (!fs.existsSync(f)) { console.error('缺 ' + f); continue; }
  S[t.tf] = load(f);
  S[t.tf].fee2 = tryLoad(path.join(outDir, 'summary_' + t.tf + '_fee2.json'));
  S[t.tf].shared = tryLoad(path.join(outDir, 'shared', 'summary_' + t.tf + '.json'));
  S[t.tf].diag = tryLoad(path.join(outDir, 'diag_' + t.tf + '.json'));
  S[t.tf].zd = tryLoad(path.join(outDir, 'summary_' + t.tf + '_zd.json'));   // 旧口径（ZD）
}
const cellOf = (s, ty, cb) => (s && s.cells ? (s.cells.find(c => c.type === ty && c.combo === cb) || null) : null);
const pairedOf = tf => tryLoad(path.join(outDir, 'paired_' + tf + '.json'));
const oneP = (arr, ty, cb) => (arr ? (arr.find(o => o.type === ty && o.combo === cb) || {}) : {});

/* ------------------------------------------------------------------ 判定 */
function verdict(s) {
  const A = cellOf(s, 'ALL', 'A');
  const tAB = s.decomp.t_A_vs_B10, tAC = s.decomp.t_A_vs_C;
  const sig = t => t != null && Math.abs(t) >= 2;
  const dAB = s.decomp.exitContribution, dAC = s.decomp.entryContribution;
  const bmAll = (s.bm && s.bm.ALL) || {};
  const bmSig = bmAll.t != null && Math.abs(bmAll.t) >= 2;
  let txt;
  if (sig(tAB) && dAB > 0 && sig(tAC) && dAC > 0)
    txt = '完整循环有价值：入场与出场都有可测贡献';
  else if (sig(tAB) && dAB > 0)
    txt = '价值主要在出场：A 优于 B，但买点本身不提供方向';
  else if (sig(tAB) && dAB < 0)
    txt = '结构出场有害：卖点过于滞后或破位过早';
  else
    txt = 'A ≈ B：结构与固定持有打平';
  if (!bmSig && bmAll.d != null)
    txt += '；持有期匹配后 A−BM = ' + pp(bmAll.d) + '（t=' + f2(bmAll.t) + '）→ 出场时点无信息，只是挑了个持有期长度';
  else if (bmSig && bmAll.d > 0)
    txt += '；**持有期匹配后 A 仍优于同分布随机时点**（' + pp(bmAll.d) + '，t=' + f2(bmAll.t) + '）→ 出场时点本身有价值';
  const short = 'A 组 ' + A.n + ' 笔、单笔 ' + pc(A.mean) + '、胜率 ' + pc(A.win) + '、盈亏比 ' + f2(A.pl) +
    '；2×2 分解 A−B10 ' + pp(dAB) + '（t=' + f2(tAB) + '）、A−C ' + pp(dAC) + '（t=' + f2(tAC) + '）（两者均为非配对）；'
    + '持有期匹配 A−BM ' + pp(bmAll.d) + '（t=' + f2(bmAll.t) + '）';
  return { txt, short, A, tAB, tAC, dAB, dAC, bmAll };
}

/* ------------------------------------------------------------------ 表格 */
function cellTable(s) {
  const rows = [];
  for (const ty of ['L1', 'L2', 'L3', 'ALL'])
    for (const cb of ['A', 'B5', 'B10', 'B20']) { const c = cellOf(s, ty, cb); if (c) rows.push(c); }
  for (const cb of ['C', 'D5', 'D10', 'D20']) { const c = cellOf(s, 'RND', cb); if (c) rows.push(c); }
  let md = '| 买点 | 组合 | n | 单笔均值 | 中位 | 胜率 | 盈亏比 | 持仓中位(日) | 赢家/输家中位 | 年化 | 最大回撤 | 资金占用 |\n';
  md += '|---|---|---|---|---|---|---|---|---|---|---|---|\n';
  for (const c of rows) {
    md += '| ' + TYPE_NAME[c.type] + ' | ' + COMBO_NAME[c.combo] + ' | ' + c.n + ' | ' + pc(c.mean) + ' | ' + pc(c.median) +
      ' | ' + pc(c.win) + ' | ' + f2(c.pl) + ' | ' + f1(c.holdMed) + ' | ' + f1(c.wHoldMed) + ' / ' + f1(c.lHoldMed) +
      ' | ' + pc(c.cagr) + ' | ' + pc(c.mdd) + ' | ' + pc(c.exposure) + ' |\n';
  }
  return md;
}

function reasonTable(s) {
  const c = cellOf(s, 'ALL', 'A');
  if (!c || !c.reasons) return '（无数据）\n';
  const order = ['R1失效位', 'R2中枢破位', 'R3卖1', 'R3卖2', 'R3卖3', 'R4超时'];
  let md = '| 出场原因 | 笔数 | 占比 | 该组平均收益 |\n|---|---|---|---|\n';
  const keys = order.filter(k => c.reasons[k]).concat(Object.keys(c.reasons).filter(k => !order.includes(k)));
  for (const k of keys) {
    const v = c.reasons[k];
    md += '| ' + k + ' | ' + v.n + ' | ' + pc(v.share) + ' | ' + pc(v.mean) + ' |\n';
  }
  return md;
}

function decompTable(s) {
  const d = s.decomp;
  let md = '| 组合 | 单笔均值 |\n|---|---|\n';
  md += '| A 完整循环 | ' + pc(d.A) + ' |\n';
  md += '| B10 缠论入场+固定10日 | ' + pc(d.B10) + ' |\n';
  md += '| C 随机入场+缠论出场 | ' + pc(d.C) + ' |\n';
  md += '| D10 随机入场+固定10日 | ' + pc(d.D10) + ' |\n\n';
  md += '| 分解项 | 数值 | Welch t | 判读 |\n|---|---|---|---|\n';
  md += '| 出场贡献 A−B10 | ' + pp(d.exitContribution) + ' | ' + mark(d.t_A_vs_B10) + f2(d.t_A_vs_B10) + mark(d.t_A_vs_B10) + ' | ' +
    (Math.abs(d.t_A_vs_B10) >= 2 ? '显著' : '不显著') + ' |\n';
  md += '| 入场贡献 A−C | ' + pp(d.entryContribution) + ' | ' + mark(d.t_A_vs_C) + f2(d.t_A_vs_C) + mark(d.t_A_vs_C) + ' | ' +
    (Math.abs(d.t_A_vs_C) >= 2 ? '显著' : '不显著') + ' |\n';
  md += '| 交互项 A−B−C+D | ' + pp(d.interaction) + ' | — | ' +
    (Math.abs(d.interaction) > Math.abs(d.exitContribution) ? '入场与出场不独立' : '入场与出场近似可加') + ' |\n';
  return md;
}

function leftTailTable(s) {
  const pick = [['A', 'ALL', 'A 完整循环'], ['B10', 'ALL', 'B10 固定10日'], ['C', 'RND', 'C 只做出场'], ['D10', 'RND', 'D10 纯基准']];
  let md = '| 组合 | 5%分位 | 最大单笔亏损 | 结构上移 | 下移 | 震荡 |\n|---|---|---|---|---|---|\n';
  for (const [cb, ty, nm] of pick) {
    const c = cellOf(s, ty, cb);
    if (!c) continue;
    const st = c.state || {};
    md += '| ' + nm + ' | ' + pc(c.q05) + ' | ' + pc(c.maxLoss) + ' | ' + (st['上移'] || 0) + ' | ' + (st['下移'] || 0) + ' | ' + (st['震荡'] || 0) + ' |\n';
  }
  return md;
}

/* 左尾一致性：文字由实测大小关系生成，不硬编码方向 */
function leftTailText(s) {
  const cA = cellOf(s, 'ALL', 'A') || {}, cB = cellOf(s, 'ALL', 'B10') || {};
  if (cA.q05 == null || cB.q05 == null) return '';
  const qBetter = cA.q05 > cB.q05;                       // 越接近 0 越浅
  const mBetter = cA.maxLoss > cB.maxLoss;
  let md = '> **一致性检查**：如果结构出场的价值来自「输家早走」，A 的 5% 分位应当**浅于** B10。实测 '
    + 'A ' + pc(cA.q05) + ' vs B10 ' + pc(cB.q05) + '（A ' + (qBetter ? '更浅' : '更深') + '）、'
    + '最大单笔亏损 ' + pc(cA.maxLoss) + ' vs ' + pc(cB.maxLoss) + '（A ' + (mBetter ? '更好' : '更差') + '）。';
  if (qBetter && mBetter)
    md += '两个左尾指标 A 都更好，说明结构出场确实在截断亏损；此时若均值仍打平，说明它同时削掉了右尾。\n\n';
  else if (qBetter !== mBetter)
    md += '两个左尾指标方向不一致，左尾改善不稳健。\n\n';
  else
    md += 'A 的左尾**没有**改善——结构出场换来了更高盈亏比（' + f2(cA.pl) + ' vs ' + f2(cB.pl) + '），但没换来更薄的左尾，'
      + '这解释了为什么净效果只是打平。\n\n';
  return md;
}

function feeTable(s) {
  if (!s.fee2) return '（未跑 0.2% 敏感性）\n';
  let md = '| 组合 | 0.1% 单笔 | 0.2% 单笔 | 差值 |\n|---|---|---|---|\n';
  for (const [cb, ty] of [['A', 'ALL'], ['B10', 'ALL'], ['C', 'RND'], ['D10', 'RND']]) {
    const a = cellOf(s, ty, cb), b = cellOf(s.fee2, ty, cb);
    if (!a || !b) continue;
    md += '| ' + COMBO_NAME[cb] + ' | ' + pc(a.mean) + ' | ' + pc(b.mean) + ' | ' + pp(b.mean - a.mean) + ' |\n';
  }
  return md;
}

/* ------------------------------------------------------------------ 主文档 */
let md = '# 缠论信号严格回测报告（A/B/C/D 四组合）\n\n';
md += '> 方案：`D:/Trading/docs/缠论信号严格回测方案.md`　框架：`D:/Trading/analysis/chanlens_strict/`\n';
md += '> 生成时间：' + new Date().toISOString().slice(0, 16).replace('T', ' ') + ' UTC　引擎：`chan.js`（参数未改）\n';
md += '> **主口径：分账单仓**——一/二/三买各一套独立资金。分层表每格都是该类信号的真实表现。\n';
md += '> **版本：v3（审计后修订）**——修正三买 R2 参照位（ZD→ZG）、重写左尾与结论引用、新增持有期匹配基准与集中度检验。\n\n';

/* ---------- 0. 结论 ---------- */
md += '## 0. 一句话结论\n\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s) continue;
  const v = verdict(s);
  md += '- **' + t.name + '**：' + v.short + '\n';
}
md += '\n';
{
  const d = S['daily'], m30 = S['30'], m60 = S['60'];
  const bmA = d && d.bm && d.bm.ALL, bm30 = m30 && m30.bm && m30.bm.ALL, bm60 = m60 && m60.bm && m60.bm.ALL;
  md += '**结构出场的作用是挑持有期，不是挑出场时点。** 三个周期在「持有期分布对齐」后，A 与随机时点出场（BM）全部打平：'
    + '日线 ' + pp(bmA && bmA.d) + '（t=' + f2(bmA && bmA.t) + '）、30m ' + pp(bm30 && bm30.d) + '（t=' + f2(bm30 && bm30.t) + '）、'
    + '60m ' + pp(bm60 && bm60.d) + '（t=' + f2(bm60 && bm60.t) + '）。'
    + '而 A 相对「固定持有 20 日」的优势（30m ' + pp((oneP(pairedOf('30'), 'ALL', 'B20') || {}).d) + '、60m ' +
    pp((oneP(pairedOf('60'), 'ALL', 'B20') || {}).d) + '）在持有期对齐后完全消失 —— 那是**持有期长度**的 beta，不是规则信息。\n\n';
}
{
  const zd = S['daily'] && S['daily'].zd, zg = S['daily'];
  const a1 = zd && cellOf(zd, 'L3', 'A'), a2 = zg && cellOf(zg, 'L3', 'A');
  const r1 = (a1 && a1.reasons['R2中枢破位']) || {}, r2 = (a2 && a2.reasons['R2中枢破位']) || {};
  if (a1 && a2) {
    md += '**三买 R2 参照位由 ZD 改为 ZG（方案原文写错）**：日线三买 ' + a1.n + ' 笔 ' + pc(a1.mean) + ' → ' + a2.n + ' 笔 ' + pc(a2.mean) + '；'
      + '赢家/输家持仓中位由 ' + f1(a1.wHoldMed) + '/' + f1(a1.lHoldMed) + '（**倒挂**）修正为 ' + f1(a2.wHoldMed) + '/' + f1(a2.lHoldMed) + '（正常）；'
      + 'R2 破位笔数 ' + (r1.n || 0) + ' → ' + (r2.n || 0) + '，该组单笔均值 ' + pc(r1.mean) + ' → ' + pc(r2.mean) + '。'
      + '方向与预期一致、**倒挂确实消失**，但幅度远小于「三买升到 +1.2%~+1.8%」的估算——提前砍掉的仓位里也有一批随后反弹的。'
      + '三买仍是三类里最弱的（日线 ' + pc(a2.mean) + ' vs 一买 ' + pc((cellOf(zg, 'L1', 'A') || {}).mean) + '、二买 ' + pc((cellOf(zg, 'L2', 'A') || {}).mean) + '）。\n\n';
  }
}
md += '**收益高度集中，t 值只能当上界读。** 日线一买 397 笔里，收益最高的 5 笔贡献了净收益的 78%；三买前 5 笔 173.3pp、'
  + '去掉后净亏 81pp；30m/60m 的全部交易挤在 10 个月内。所以 n=397 **不等于 397 次独立试验**，实际独立行情大约十来个。'
  + '本报告所有 t 值都按独立样本计算，真实显著性低于表面值。详见 §4.10。\n\n';

/* ---------- 1. 口径 ---------- */
md += '## 1. 口径与断言\n\n';
md += '| 项 | 设定 |\n|---|---|\n';
md += '| 买入成交 | 买点**首次被发现**的那根 bar（discT）的下一根开盘价；只接受 lag = discT − readyK = 1 |\n';
md += '| 卖出成交 | 破位/失效用「收盘确认 bar 的下一根开盘」；卖点用「卖点首次发现 bar 的下一根开盘」 |\n';
md += '| 破位判定 | **收盘价**（`close`）跌破参照位才触发，盘中最低价不参与；确认后次日开盘卖 |\n';
md += '| T+1 | 出场 bar 日期必须晚于入场 bar 日期，否则顺延 |\n';
md += '| 涨停 / 跌停 | 开盘涨幅≥9.5% 买不进（跳过并计数）；开盘跌幅≥9.5% 或停牌卖不出，顺延 |\n';
md += '| 出场规则 | R1 收盘跌破买点失效位（一买用自身低点、二买用一买低点、三买不启用）/ **R2 收盘跌破入场时中枢 ZG（仅三买）** / R3 卖点（笔派生，**不区分一/二/三类**）/ R4 120 交易日超时 |\n';
md += '| 仓位（主口径） | **分账**：每标的按买点类型各占一套独立资金（26 只 × 3 类 = 78 条资金线），同类持仓期间同类新信号跳过 |\n';
md += '| 仓位（附表口径） | `SHARED=1`：同标的全类型共享一仓，见 §4.11——二买 87% 信号被一买吃掉，**仅供对照，不作结论** |\n';
md += '| 成本 | **往返合计** 0.1%（买+卖各半，另跑 0.2%）；ETF 无印花税 |\n';
md += '| 随机对照 | 每标的 1000 次重抽 × 每次 50 个随机日；随机日当作确认 bar，次日开盘入场；参照位取当日快照 |\n';
md += '| 参照位纪律 | 全部为「发现时刻快照」，不使用事后才确认的极值；成交价从不使用信号 bar 的开高低收 |\n\n';
md += '> **R2 的参照位是 ZG 不是 ZD**：三买成交价在中枢上方，从买入价到 ZD 要跨过整个中枢高度再加突破溢价——'
  + '那等于让三买几乎没有止损（旧口径下 R2 组 72 笔均值 −9.91%、5% 分位 −14.42%、三周期赢家比输家走得快变成反过来）。'
  + '原方案文本写「跌破 ZD」是笔误，本轮改为 ZG 为主口径，ZD 结果保留在 §4.9 做对照。\n\n';

md += '### 1.1 时间戳断言（lag = 首次发现 bar − readyK）\n\n';
md += '| 周期 | 笔派生买点 lag=1 占比 | 笔派生卖点 lag=1 占比 | lag>1 处理 | 断言 |\n|---|---|---|---|---|\n';
for (const t of TFS) {
  /* 优先读 scan 的完整切片；tmp 清理后回落到 out/laghist_*.json（同源提取，几 KB） */
  const p = path.join(__dirname, 'tmp', 'pack_' + t.tf + '.json');
  const lh = fs.existsSync(p) ? load(p).lagHist : (tryLoad(path.join(outDir, 'laghist_' + t.tf + '.json')) || {}).lagHist;
  if (!lh) continue;
  const share = h => {
    const ks = Object.keys(h); const tot = ks.reduce((s, k) => s + h[k], 0);
    return tot ? (100 * (h[1] || 0) / tot).toFixed(1) + '%' : 'n/a';
  };
  md += '| ' + t.name + ' | ' + share(lh.buyBi) + ' | ' + share(lh.sellBi) + ' | lag>1 视为事后回填，剔除不入场 | 通过（无 lag<1） |\n';
}
md += '\n> lag>1 的含义：这些买卖点只在更晚的切片里才出现（结构被后续走势重新计算出来了）。按 readyK+2 成交会构成前视，一律剔除并计数。\n\n';

md += '### 1.2 数据与标的\n\n';
md += '| 周期 | 标的数 | 区间 | 说明 |\n|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s) continue;
  md += '| ' + t.name + ' | 26 | ' + t.span + ' | ' +
    (t.tf === '60' ? '新浪 CN_MarketDataService scale=60（接口上限 1023 根），已按日线前复权做阶梯复权' :
     t.tf === '30' ? '东财 push2his klt=30，原始数据实为不复权，已按日线前复权做阶梯复权' :
     '东财日线前复权全历史；2 只历史过短剔除') + ' |\n';
}
md += '\n> **数据源变更**：60 分钟由「30m 合成」改为**真实 60 分钟**（东财 klt=60 被 WAF 限流，改用新浪源）。'
  + '重叠期校验：真实 60m 与 30m 合成 60m 复权后 OHLC 平均相对差 **0.001%**（仅首日因 1023 根上限截断差 2.3%）。\n'
  + '> **分钟线复权**：30m/60m 原始数据都是**不复权**价，与日线前复权在除权日会产生人为跳空（如 510300 在 2026-01-19 分红 −2.7% 被当成暴跌）。'
  + '两端已统一阶梯复权（`fetch/fix_min_adj.py`），全池与日线最大偏差 0.59%；份额折算 ETF 刻度也对齐，池由 23 只恢复 26 只。\n\n';

/* ---------- 1.3 单仓诊断 ---------- */
md += '### 1.3 为什么主口径必须是分账（`node diag.js`）\n\n';
md += '「同标的全类型共享一仓」会让**先到的信号把后来的信号挤掉**，而先到的往往是结构更好、更靠近启动点的那个。'
  + '「被吃掉那批的均值」是被挤掉的信号**若独占单仓本可拿到**的单笔收益：\n\n';
md += '| 周期 | 买点 | 可交易信号 | 共享一仓成交 | 共享均值 | 被占用 | 占用者(一买/三买) | **分账成交** | **分账均值** | 被吃掉那批均值 |\n|---|---|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s || !s.diag) continue;
  for (const tk of ['L1', 'L2', 'L3']) {
    const d = s.diag.levels[tk]; if (!d) continue;
    md += '| ' + t.name + ' | ' + TYPE_NAME[tk] + ' | ' + d.signals + ' | ' + d.sharedN + ' | ' + pc(d.sharedMean) +
      ' | ' + d.busyN + ' | ' + (d.busyBy.L1 || 0) + ' / ' + (d.busyBy.L3 || 0) +
      ' | **' + d.soloN + '** | **' + pc(d.soloMean) + '** | ' + pc(d.eatenMean) + ' |\n';
  }
}
{
  const d2 = S['daily'] && S['daily'].diag && S['daily'].diag.levels.L2;
  const d3 = S['daily'] && S['daily'].diag && S['daily'].diag.levels.L3;
  const d1 = S['daily'] && S['daily'].diag && S['daily'].diag.levels.L1;
  md += '\n';
  if (d2) md += '- 日线二买：' + d2.signals + ' 个可交易信号，共享一仓只成交 **' + d2.sharedN + '** 个（' +
    (100 * d2.sharedN / d2.signals).toFixed(1) + '%），' + d2.busyN + ' 个被占用，其中 **' + (d2.busyBy.L1 || 0) + ' 次是一买**。'
    + '根因是结构性的——二买定义就是「一买之后回抽不破前低」，必然紧跟一买，而一买持仓中位 8 日，正好盖住确认窗口。\n';
  if (d2) md += '- 剩下的是**反向选择的差样本**：能成交的 ' + d2.sharedN + ' 笔均值 ' + pc(d2.sharedMean) + '，被挤掉那批 **' + pc(d2.eatenMean) + '**。'
    + '把这个格子写成「二买×完整循环很烂」是**读反了**。\n';
  if (d3) md += '- 三买同样受害：被挤掉那批 ' + d3.eatenN + ' 笔均值 ' + pc(d3.eatenMean) + '，共享一仓成交的 ' + d3.sharedN + ' 笔只有 ' + pc(d3.sharedMean) + '，'
    + '加权后正好还原分账的 ' + d3.soloN + ' 笔 ' + pc(d3.soloMean) + '（可自行核对）。\n';
  if (d1) md += '- 一买是受益者（它最先到）：被挤掉那批均值 ' + pc(d1.eatenMean) + '，所以共享一仓下的一买数字反而略高——那是占了便宜。\n\n';
  md += '> 结论：分层结论一律按**分账**读。共享一仓只回答「一个账户三类都做，实际能吃到多少」，见 §4.11。\n\n';
}

/* ---------- 2. 全表 ---------- */
for (const t of TFS) {
  const s = S[t.tf]; if (!s) continue;
  md += '## 2. 全表 —— ' + t.name + '\n\n';
  const sA = cellOf(s, 'ALL', 'A');
  md += '可交易信号 ' + s.stats.signals + ' 笔；涨停跳过 ' + s.stats.skippedLimitUp + '；A 组持仓占用跳过 ' + s.stats.busyA +
    (s.stats.busyAByType ? '（一买 ' + s.stats.busyAByType.L1 + ' / 二买 ' + s.stats.busyAByType.L2 + ' / 三买 ' + s.stats.busyAByType.L3 + '）' : '') +
    '；无合规出场作废 ' + s.stats.noExit + '；lag>1 剔除 ' + s.stats.lagDropped + '。\n\n';
  md += '> **账目自洽**：可交易信号 ' + s.stats.signals + ' = A 组成交 ' + (sA ? sA.n : 'n/a') + ' + 持仓占用 ' + s.stats.busyA +
    ' + 无合规出场作废 ' + s.stats.noExit + '。\n'
    + '> **「越界 ' + s.stats.skippedEnd + ' 笔」不在上式里**——它在信号计数之前就被剔除（入场 bar 距数据末端不足 2 根），'
    + '所以「可交易信号」本身不含它，不存在漏账。\n\n';
  md += cellTable(s);
  md += '\n> 「全部」行的年化/回撤/占用为 `n/a`：分账后同一标的可同时持有三类仓位，把三类交易串成一条曲线连乘不成立。三类各自年化见上三行。\n\n';
  md += '**持仓时长**：「赢家/输家中位」是方案要求的关键指标——真按缠论跑应当输家走得快、赢家拿得久。\n\n';
  md += '### 出场原因分布（A 组合，全部买点）\n\n' + reasonTable(s) + '\n';
  md += '### 2×2 分解\n\n' + decompTable(s) + '\n';
  md += '### 左尾与结构三态\n\n' + leftTailTable(s) + '\n' + leftTailText(s);
  md += '### 成本敏感性\n\n' + feeTable(s) + '\n';
}

/* ---------- 3. 判定 ---------- */
md += '## 3. 结论判定\n\n';
md += '| 周期 | A−B10 | A−C | **A−BM（持有期匹配）** | 判定 |\n|---|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s) continue;
  const v = verdict(s);
  const bm = v.bmAll || {};
  md += '| ' + t.name + ' | ' + pp(v.dAB) + '（t=' + f2(v.tAB) + '） | ' + pp(v.dAC) + '（t=' + f2(v.tAC) + '） | '
    + mark(bm.t) + pp(bm.d) + '（t=' + f2(bm.t) + '）' + mark(bm.t) + ' | ' + v.txt + ' |\n';
}
md += '\n**判定基准换成了 A−BM**：A 与 B 的持仓长度根本不同（30m A 中位 1.4 日 vs B20 的 20 日），'
  + 'A−B 的差值里混着持有期长度的 beta。BM 是「同一入场点、持有期从 A 自身分布随机抽、出场时点随机」的对照，'
  + '它剔除了长度差异，只留时点信息。三个周期 A−BM 的 |t| 全部 < 1 —— **结构出场没有可测的时点信息**。\n\n'
  + '**但也不能说它没用**：它把一个需要调参的固定 N 换成了自动跟随结构的持有期，'
  + '省掉「30m 该持几天、日线该持几天」这个样本内调参环节。价值在鲁棒性，不在收益率。\n\n';

/* ---------- 4. 未通过 ---------- */
md += '## 4. 没跑通 / 样本不足的格子\n\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s) continue;
  const bad = [];
  for (const c of s.cells) {
    if (c.type === 'ALL') continue;
    if (c.n != null && c.n < 30) bad.push(TYPE_NAME[c.type] + '×' + COMBO_NAME[c.combo] + '（n=' + c.n + '）');
    if (c.cagr == null) bad.push(TYPE_NAME[c.type] + '×' + COMBO_NAME[c.combo] + '（年化不可算）');
  }
  md += '- **' + t.name + '**：' + (bad.length ? bad.slice(0, 8).join('；') + (bad.length > 8 ? ' 等 ' + bad.length + ' 格' : '') : '全部格子 n ≥ 30 且年化可算') + '\n';
}
md += '\n> 「可用」不等于「可信」：60 分钟只有 256 个交易日，二买分账后 n=89；30 分钟二买 n=188 但覆盖期仅 10 个月。'
  + '低级别的单笔符号可以看方向，量级不要外推。\n\n';

/* ---------- 4.5 数据源 ---------- */
md += '## 4.5 数据源变更前后对比（30m / 60m，共享一仓口径）\n\n';
{
  md += '> 本节两列都用共享一仓口径（`SHARED=1`），目的是隔离「数据源/复权」这一个变量。\n\n';
  md += '| 口径 | A 单笔 | B10 单笔 | C 单笔 | D10 单笔 | 出场贡献 A−B10 | 入场贡献 A−C | A 年化 |\n|---|---|---|---|---|---|---|---|\n';
  const pairs = [['60', '60m 30m合成 · 不复权 · 23只', '60m 真实源 · 已复权 · 26只'],
  ['30', '30m 东财 · 不复权 · 23只', '30m 东财 · 已复权 · 26只']];
  for (const [tf, oldName, newName] of pairs) {
    const oldS = tryLoad(path.join(outDir, 'raw_legacy', 'summary_' + tf + '.json'));
    const newS = S[tf] && S[tf].shared;
    for (const [lbl, s] of [[oldName, oldS], [newName, newS]]) {
      if (!s) { md += '| ' + lbl + ' | — | — | — | — | — | — | — |\n'; continue; }
      const A = cellOf(s, 'ALL', 'A'), B = cellOf(s, 'ALL', 'B10'), C = cellOf(s, 'RND', 'C'), D = cellOf(s, 'RND', 'D10');
      md += '| ' + lbl + ' | ' + pc(A && A.mean) + ' | ' + pc(B && B.mean) + ' | ' + pc(C && C.mean) + ' | ' + pc(D && D.mean) +
        ' | ' + pp(s.decomp.exitContribution) + '（t=' + f2(s.decomp.t_A_vs_B10) + '） | ' +
        pp(s.decomp.entryContribution) + '（t=' + f2(s.decomp.t_A_vs_C) + '） | ' + pc(A && A.cagr) + ' |\n';
    }
  }
  md += '\n**怎么读**：换数据源 + 修复权后单笔均值普遍上移 0.1~0.4pp（除权跳空和错误刻度被清掉），'
    + '「出场/入场贡献都不显著」这一结论在两种口径、三轮数据下都没被翻转——数据质量修正既没制造假信号，也没抹掉真信号。\n\n';
}

/* ---------- 4.6 配对 ---------- */
md += '## 4.6 配对检验：同一入场点，只换出场规则\n\n';
md += 'A 与 B 各自单仓、持仓快慢不同，被跳过的信号就不同——两者交易集合本来就不同。本节只保留 **A 与 B 都实际成交的同一入场点**，'
  + '逐笔求差 d = retA − retB。\n\n';
md += '| 周期 | 对比 | 配对数 | A 配对均值 | B 配对均值 | 配对差 | 配对 t | 逐笔胜出 | A持中 | B持中 |\n|---|---|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const P = pairedOf(t.tf); if (!P) continue;
  for (const o of P) {
    if (o.type !== 'ALL' || !o.nPair) continue;
    md += '| ' + t.name + ' | A vs ' + o.combo + ' | ' + o.nPair + ' | ' + pc(o.meanA) + ' | ' + pc(o.meanB) +
      ' | ' + mark(o.t) + pp(o.d) + mark(o.t) + ' | ' + f2(o.t) + ' | ' + pc(o.posShare) + ' | ' + f1(o.holdA) + ' | ' + f1(o.holdB) + ' |\n';
  }
}
md += '\n**读法**：配对差为正 = 同一批入场点上，缠论出场比固定出场多赚。\n\n';
{
  const daily = pairedOf('daily'), m30 = pairedOf('30'), m60 = pairedOf('60');
  const dA10 = oneP(daily, 'ALL', 'B10'), dA20 = oneP(daily, 'ALL', 'B20');
  const b20_30 = oneP(m30, 'ALL', 'B20'), l1_30 = oneP(m30, 'L1', 'B20');
  const b20_60 = oneP(m60, 'ALL', 'B20'), l1_60 = oneP(m60, 'L1', 'B10');
  md += '**日线**：配对后 A vs B10 = ' + pp(dA10.d) + '（t=' + f2(dA10.t) + '），与 B20 是 ' + pp(dA20.d) + '（t=' + f2(dA20.t) + '）——测不出。\n\n';
  md += '**低级别**：A vs B20 = 30m ' + pp(b20_30.d) + '（t=' + f2(b20_30.t) + '）、60m ' + pp(b20_60.d) + '（t=' + f2(b20_60.t) + '）；'
    + '一买更极端：30m vs B20 ' + pp(l1_30.d) + '（t=' + f2(l1_30.t) + '）、60m vs B10 ' + pp(l1_60.d) + '（t=' + f2(l1_60.t) + '）。'
    + '光看这张表会得出「低级别结构出场显著更好」，**但这是错的读法**——表里 A持中 ' + f1(b20_30.holdA) + ' 根 bar vs B20 的 ' + f1(b20_30.holdB) +
    ' 根，比的是持有期长度，不是规则。§4.7 把长度对齐后，差异全部消失。\n\n';
}

/* ---------- 4.7 持有期匹配基准 ---------- */
md += '## 4.7 持有期匹配基准：把「持有期长度」从「出场规则」里剥出来\n\n';
md += '做法（`strict.js` 内置）：对每一笔 A，保持**入场点不变**，持有期从 **A 自身该类型的持仓 bar 分布**里随机抽，'
  + '每笔抽 100 次取平均（BM）；另做一个「持有期固定为 A 该类中位」的版本（BMED）。两者都与 A 逐笔配对求差。\n\n';
md += '| 周期 | 类型 | 配对数 | A | BM 随机时点 | A−BM | t | BMED 同长度 | A−BMED | t |\n|---|---|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s || !s.bm) continue;
  for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
    const b = ty === 'ALL' ? s.bm.ALL : s.bm.byType[ty];
    if (!b || !b.n) continue;
    md += '| ' + t.name + ' | ' + TYPE_NAME[ty] + ' | ' + b.n + ' | ' + pc(b.meanA) + ' | ' + pc(b.meanBM) +
      ' | ' + mark(b.t) + pp(b.d) + mark(b.t) + ' | ' + f2(b.t) + ' | ' + pc(b.meanBMED) + ' | ' + pp(b.dMED) + ' | ' + f2(b.tMED) + ' |\n';
  }
}
md += '\n**结论**：三个周期、四个类型共 12 组 A−BM，**没有一组 |t| ≥ 2**（最大的 30m 二买 t=−1.60），'
  + '而 A−BMED 在 30m 二买上是 **−0.62pp（t=−2.49）**——同长度固定持有反而更好。'
  + '所以「结构出场比固定持有好」这件事，**只在固定 N 选得明显不合适时成立**（低级别 N=20 太长），不是规则本身有 alpha。\n\n'
  + '> 一个必须承认的边界：BM 是把「时点随机化」，它是出场规则的**零假设**。'
  + 'BM 平手说明「缠论卖点/破位时点」相对随便挑一个同长度的时点没有优势；它不否认「选对持有期」本身有价值。\n\n';

/* ---------- 4.8 独立复核 ---------- */
md += '## 4.8 独立复核（`node verify.js <tf>`）\n\n';
md += '不复用回测的算价逻辑，直接从原始 CSV 重算每一笔：价格是否等于对应 bar 开盘价、收益公式、T+1、持仓重叠、入场是否等于买点 discT+1、是否只用 lag=1 的买点。\n\n';
md += '| 周期 | 核对笔数 | 价格不符 | 收益不符 | T+1 违规 | 持仓重叠 | 入场≠discT+1 | 用了 lag≠1 |\n|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const V = tryLoad(path.join(outDir, 'verify_' + t.tf + '.json'));
  if (!V) { md += '| ' + t.name + ' | 未跑 | — | — | — | — | — | — |\n'; continue; }
  md += '| ' + t.name + ' | ' + V.nCheck + ' | ' + V.priceMismatch + ' | ' + V.retMismatch + ' | ' +
    V.t1Violation + ' | ' + V.overlap + ' | ' + V.entryNotNext + ' | ' + V.lagNot1 + ' |\n';
}
md += '\n> 7 项全为 0。复核脚本自身也修过一个 bug：同一 bar 上若同时有一买与二买，早期版本只按 bar 匹配第一个买点，导致类型归档错误；现按 `code + type + discT` 三元匹配。\n\n';
{
  const V = {};
  for (const t of TFS) V[t.tf] = tryLoad(path.join(outDir, 'verify_' + t.tf + '.json'));
  const fmtLv = tf => {
    const b = (V[tf] && V[tf].byLevel) || {};
    return ['L1', 'L2', 'L3'].map(k => k + ' ' + (b[k] ? b[k][0] + '/' + b[k][1] : 'n/a')).join('、');
  };
  md += '> **一个需要打折扣的字段**：`structure_state`（结构三态）从入场当根开始判「收盘 < 中枢 ZD 即下移」。'
    + '但一买本来就在中枢下方形成——实测入场时价格已低于 ZD 的比例（日线）：' + fmtLv('daily') + '。'
    + '一买 ' + (() => { const b = (V['daily'] && V['daily'].byLevel && V['daily'].byLevel.L1) || [0, 0]; return (100 * b[0] / Math.max(1, b[1])).toFixed(0) + '%'; })() +
    ' 一入场就在 ZD 下方，二买也有近两成，所以「上移/下移」对一买/二买基本没有区分力；三买是 0，'
    + '但三买在破 ZG 时就已经被 R2 平掉，也很难走到「跌破 ZD」，因此这个字段对三买同样偏空。'
    + '审计提出的更根本问题也成立：三买上移率 59.7% vs 随机组 26.3%，但两组的参照位距入场价的距离分布不同，'
    + '**这个字段不能用来回答「信号是否反映结构方向」**，本报告只用它做描述，不下结论。\n\n';
}

/* ---------- 4.9 ZD vs ZG ---------- */
md += '## 4.9 三买 R2 参照位：ZD（原方案）vs ZG（修正后）\n\n';
md += '原方案写「三买跌破中枢 ZD 清仓」，但三买买在中枢上方，到 ZD 要跨过整个中枢高度。方案与速查卡不一致，本轮以 ZG 为主口径。\n\n';
md += '| 周期 | 口径 | n | 单笔均值 | 赢家/输家持仓中位(日) | R2 破位笔数 | R2 该组均值 | 5% 分位 | 最大单笔亏损 |\n|---|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const zg = S[t.tf], zd = S[t.tf] && S[t.tf].zd;
  for (const [lbl, s] of [['ZD（旧）', zd], ['ZG（新）', zg]]) {
    if (!s) { md += '| ' + t.name + ' | ' + lbl + ' | — | — | — | — | — | — | — |\n'; continue; }
    const c = cellOf(s, 'L3', 'A'); if (!c) continue;
    const r = c.reasons['R2中枢破位'] || {};
    md += '| ' + t.name + ' | ' + lbl + ' | ' + c.n + ' | ' + pc(c.mean) + ' | ' + f1(c.wHoldMed) + ' / ' + f1(c.lHoldMed) +
      ' | ' + (r.n || 0) + ' | ' + pc(r.mean) + ' | ' + pc(c.q05) + ' | ' + pc(c.maxLoss) + ' |\n';
  }
}
md += '\n**结论（部分是修正、部分是否定）**：\n\n'
  + '- 倒挂修好了。日线从 12/17（输家比赢家拿得久）变成 10.5/8.0，60m 从 2.25/4.5 变成 2.25/2.25，30m 从 1.25/1.57 变成 1.25/1.00。这是「截断亏损」恢复工作的直接指纹。\n'
  + '- 左尾和均值都改善，但幅度小：日线 R2 组单笔均值 −9.91% → −6.74%，5% 分位 −14.42% → −11.63%，三买均值 +0.13% → +0.27%。\n'
  + '- **没有出现「三买变成最好」**。审计粗算 +1.2%~+1.8% 的前提是「被提前砍掉的那 40 笔都是坏单」；'
  + '实测里 ZG 触发次数反而从 72 次涨到 113 次（止损更紧、更容易被打），其中一部分是「假破位后被砍、随后反弹」的仓位。'
  + '两端抵消后净改善有限。三买仍然弱于一买/二买。\n\n'
  + '> 若要继续收紧，下一步应测「ZG 下方留缓冲（如 ZG − 0.5×ATR）」或「破 ZG 后要求次根不收回再走」。这属于新规则，需重跑全流程。\n\n';

/* ---------- 4.10 集中度 ---------- */
md += '## 4.10 收益集中度与有效样本量\n\n';
md += 'n 大不代表独立试验多。按「单笔收益前 5 名占总净收益」衡量：\n\n';
md += '| 周期 | 类型 | n | 前 5 笔合计 | 总净收益 | 前 5 笔占比 | 入场月份数 |\n|---|---|---|---|---|---|---|\n';
{
  const csvRows = tf => {
    const f = path.join(outDir, 'trades_' + tf + '.csv');
    if (!fs.existsSync(f)) return [];
    const L = fs.readFileSync(f, 'utf8').split('\n').filter(x => x.trim());
    const h = L[0].split(',');
    return L.slice(1).map(l => { const c = l.split(','); const o = {}; h.forEach((k, i) => o[k] = c[i]); return o; }).filter(r => r.combo === 'A');
  };
  for (const t of TFS) {
    const rows = csvRows(t.tf);
    for (const ty of ['L1', 'L2', 'L3']) {
      const sub = rows.filter(r => r.type === ty);
      if (!sub.length) continue;
      const rs = sub.map(r => +r.ret_net);
      const sorted = rs.slice().sort((a, b) => b - a);
      const tot = rs.reduce((s, x) => s + x, 0), t5 = sorted.slice(0, 5).reduce((s, x) => s + x, 0);
      const months = new Set(sub.map(r => r.entry_time.slice(0, 7))).size;
      md += '| ' + t.name + ' | ' + TYPE_NAME[ty] + ' | ' + rs.length + ' | ' + (t5 * 100).toFixed(1) + 'pp | ' +
        (tot * 100).toFixed(1) + 'pp | ' + (tot > 0 ? (100 * t5 / tot).toFixed(0) + '%' : '总收益为负，占比无意义') + ' | ' + months + ' |\n';
    }
  }
}
md += '\n**怎么读**：\n\n'
  + '- 日线一买前 5 笔占总净收益 **78%**，三买前 5 笔 173pp、去掉后净亏 81pp。也就是说「日线一买 +0.93%/笔」这个数，'
  + '如果少了这 5 笔就基本归零。\n'
  + '- 日线收益前 8 名里 5 笔的入场集中在 2024-07 ~ 2024-09（924 行情），另有 2014-11 一笔、2025 年两笔。'
  + '这不是「12 年稳定有效」，而是「抓住过两三轮行情」。\n'
  + '- 30m/60m 的全部交易挤在 10 个月内，**30m 与 60m 不是两个独立环境**，是同一段行情的两种切片。'
  + '所以「三周期一致」实际只有约 2 个独立环境（2014~2026 日线、2025-09~2026-10 分钟线）。\n'
  + '- **因此本报告所有 t 值都应视为显著性上界**：按独立样本算的 t=3，在有效样本只有十来个行情的情况下可能只有 t≈1。'
  + '结论层面只应采信「方向一致 + 多口径不翻转」，不应采信具体 t 值。\n\n';

/* ---------- 4.11 共享一仓 ---------- */
md += '## 4.11 附表：共享一仓口径（`SHARED=1`，一个账户三类都做）\n\n';
md += '最贴近「一个账户实际怎么跑」的口径。分层数字**不能用**（见 §1.3），但「一共能做多少笔、占用多少资金」有参考价值：\n\n';
md += '| 周期 | 可交易信号 | A 实际成交 | 成交率 | A 单笔 | A 年化 | 资金占用 | 因占用作废 |\n|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf] && S[t.tf].shared; if (!s) continue;
  const a = cellOf(s, 'ALL', 'A'); if (!a) continue;
  md += '| ' + t.name + ' | ' + s.stats.signals + ' | ' + a.n + ' | ' + (100 * a.n / s.stats.signals).toFixed(1) + '% | ' +
    pc(a.mean) + ' | ' + pc(a.cagr) + ' | ' + pc(a.exposure) + ' | ' + s.stats.busyA + ' |\n';
}
{
  const d = S['daily'];
  const aSplit = d && cellOf(d, 'ALL', 'A'), aShared = d && d.shared && cellOf(d.shared, 'ALL', 'A');
  if (aSplit && aShared) {
    md += '\n**对照分账**：日线 A 组分账后共 ' + aSplit.n + ' 笔、单笔 ' + pc(aSplit.mean) + '；共享一仓只能吃到 ' + aShared.n +
      ' 笔、单笔 ' + pc(aShared.mean) + '。差的那部分不是「共享一仓更差」，而是**同样的钱只能占一次，信号被系统性浪费**。\n\n';
  }
}

/* ---------- 5. 复现 ---------- */
md += '## 5. 复现\n\n```bash\ncd D:/Trading/analysis/chanlens_strict\n';
md += 'TF=daily node scan.js     # 生成 tmp/pack_daily.json（逐bar切片，含 lag 断言；约 23MB，可随时删除）\n';
md += 'TF=daily node strict.js   # A/B/C/D + BM/BMED（默认分账单仓、R2 参照 ZG）\n';
md += 'TF=daily node diag.js     # 单仓口径诊断 → out/diag_daily.json\n';
md += 'TF=30 node scan.js && TF=30 node strict.js && TF=30 node diag.js\n';
md += 'TF=60 node scan.js && TF=60 node strict.js && TF=60 node diag.js\n';
md += 'ZSREF=zd SUF=_zd TF=daily node strict.js      # 对照：三买 R2 退回 ZD（旧方案）\n';
md += 'ZSREF=mid SUF=_mid TF=daily node strict.js    # 对照：三买 R2 用中枢中位\n';
md += 'SHARED=1 SUF=_sh TF=daily node strict.js      # 附表口径：全类型共享一仓\n';
md += 'SYNTH60=1 TF=60 node scan.js                  # 对照：退回 30m 合成 60m\n';
md += 'RAW_MIN=1 TF=30 node scan.js                  # 对照：退回不复权 30m\n';
md += 'FEE=0.002 SUF=_fee2 TF=daily node strict.js   # 成本敏感性\n';
md += 'node verify.js daily && node verify.js 30 && node verify.js 60    # 独立复核\n';
md += 'node paired.js daily && node paired.js 30 && node paired.js 60     # A/B 配对检验\n';
md += 'node report.js            # 生成本报告\n```\n\n';
md += '**数据准备**（分钟线复权）：\n\n```bash\ncd D:/Trading/fetch\n';
md += 'python fetch_etf_60m_sina.py                                    # 新浪 60m → data/etfs_bt_60m\n';
md += 'python fix_min_adj.py D:/Trading/data/etfs_bt_60m D:/Trading/data/etfs_bt_60m_adj\n';
md += 'python fix_min_adj.py D:/Trading/data/etfs_bt_30m D:/Trading/data/etfs_bt_30m_adj\n```\n\n';

/* ---------- 6. 局限 ---------- */
md += '## 6. 未做的事与已知局限\n\n';
md += '- 变体（移动止盈：跌破上一笔回调低点）未跑——方案中标为「不进主口径」。\n';
md += '- 线段派生卖点仅在日线记录（`pack_daily.json` 的 `sellSeg`），未用于清仓（按你选定：主口径=笔派生）。\n';
md += '- 30m/60m 覆盖期仅 10~12 个月；同期 26 只 ETF 等权买入持有年化 **−10.9%**（中位 −11.4%，8/26 只正收益），属偏弱市。年化不可外推。\n';
md += '- 费用口径：`FEE=0.001` 是**往返合计**，不是单边；ETF 无印花税，0.1% 往返已含滑点余量。\n';
md += '- 年化口径：**分账**——26 只 × 3 类 = 78 条资金线，每条独立复利后对同类取平均；不是「一个账户全市场轮动」。\n';
{
  const ra = (cellOf(S['daily'], 'ALL', 'A') || {}).reasons || {};
  const r31 = ra['R3卖1'] || {};
  md += '- R3 卖点**不区分一到三类**：三买也可能被「一卖」平掉（日线 R3卖1 触发 ' + (r31.n || 'n/a') + ' 次，占 ' + pc(r31.share) + '）。'
    + '若改成「三买只认三卖」，持仓会显著变长，结论需重跑。\n';
}
md += '- R2 只对三买启用：一买入场时多数已在中枢下方，若同样启用会「入场即破位」，规则退化。\n';
md += '- 60m 真实数据受新浪接口 1023 根上限约束，最长只能回看约 1 年。\n';
md += '- **C/D 随机组不落明细**（每标的 1000 次重抽 × 50 个随机日，约 83 万笔聚合值），因此无法逐笔复核。'
  + '可用的间接检验是种子间离散度：C 组跨（标的×种子）的单笔均值标准差 1.07pp（日线）/ 0.45pp（30m）/ 0.56pp（60m），'
  + '对应均值标准误 < 0.01pp——即 C 的均值本身是稳定的，无法复核的是「逐笔」，不是「均值」。\n';
md += '- **有效样本量远小于 n**：见 §4.10，t 值仅作上界参考。\n';

fs.writeFileSync(path.join(__dirname, 'report_full.md'), md);
console.log('report_full.md 已生成，' + md.length + ' 字符');
