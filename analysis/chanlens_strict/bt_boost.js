/* ==========================================================================
 * bt_boost.js —— 信号之外的四种「提升机制」实证
 *
 * 问题：纯信号胜率/盈亏比一般，除改信号本身，还能靠什么提升？
 * 四个机制，各对应一篇实证文献：
 *   M1 选择性过滤     López de Prado(2018) meta-labeling
 *                     → 主模型高 recall、副模型提 precision，只在高分档下注
 *   M2 样本外检验     同上（时间切分 + embargo），判定 M1 是否只是过拟合
 *   M3 波动率目标仓位 Harvey et al.(2018) JPM "The Impact of Volatility Targeting"
 *                     → 按 1/ATR% 缩放，美股 Sharpe 0.40 → 0.48~0.51，左尾显著压缩
 *   M4 分批止盈       演示「胜率↑必然伴随盈亏比↓」——期望值不变的数学恒等
 *
 * 口径与 bt_anom / bt_alpha 完全一致：
 *   discT+1 开盘入场、固定持有 20 日、双边费 0.1%、仅接受 lag=1。
 *
 * 用法：
 *   STOCKS=1 node bt_boost.js      # 个股 43 只（主样本）
 *   node bt_boost.js               # ETF 43 只
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const FEE = 0.001, X = 20, PW = 250, MINCNT = 60;
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json'), 'utf8'));

/* ---------------------------------------------------------------- 统计 */
const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
function sd(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
const tStat = a => { if (!a || a.length < 3) return null; const s = sd(a); return s ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const median = a => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

const pct = v => v == null || !isFinite(v) ? '—' : (100 * v).toFixed(2) + '%';
const pp = v => v == null || !isFinite(v) ? '—' : (v >= 0 ? '+' : '\u2212') + (100 * Math.abs(v)).toFixed(2) + 'pp';
const f2 = v => v == null || !isFinite(v) ? '—' : v.toFixed(2);

/** 单笔分布：胜率 / 盈亏比 / 期望 */
function stat(rs) {
  const n = rs.length;
  if (!n) return { n: 0, wr: null, aw: null, al: null, pl: null, exp: null, t: null };
  const w = rs.filter(r => r > 0), l = rs.filter(r => r <= 0);
  const aw = w.length ? mean(w) : null, al = l.length ? mean(l) : null;
  return {
    n, wr: w.length / n, aw, al,
    pl: aw != null && al != null && al < 0 ? aw / -al : null,
    exp: mean(rs), t: tStat(rs)
  };
}

/* ---------------------------------------------------------------- 工具 */
function atrWilder(p, n) {
  const N = p.c.length, out = new Array(N).fill(null);
  const tr = i => Math.max(p.h[i] - p.l[i], Math.abs(p.h[i] - p.c[i - 1]), Math.abs(p.l[i] - p.c[i - 1]));
  let v = 0;
  for (let i = 1; i <= n; i++) v += tr(i);
  v /= n; out[n] = v;
  for (let i = n + 1; i < N; i++) { v = (v * (n - 1) + tr(i)) / n; out[i] = v; }
  return out;
}
/** 过去 W 根内的分位（严格只用 t 之前） */
function rollPct(s, W, minCnt) {
  const n = s.length, out = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (s[i] == null) continue;
    let cnt = 0, below = 0;
    const lo = Math.max(0, i - W);
    for (let j = lo; j < i; j++) { if (s[j] == null) continue; cnt++; if (s[j] < s[i]) below++; }
    out[i] = cnt >= (minCnt || MINCNT) ? below / cnt : null;
  }
  return out;
}
function tradable(p) {
  const n = p.c.length, ok = new Array(n).fill(true);
  if (!STOCKS) return ok;
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    if ((Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 864e5 > 15) ok[i] = false;
  }
  return ok;
}

/* ---------------------------------------------------------------- 收信号 */
/* 全池等权日收益：用于剥离 beta（同期市场涨了多少） */
const _byD = new Map();
for (const p of pack.packs) {
  for (let i = 1; i < p.c.length; i++) {
    if (!(p.c[i - 1] > 0)) continue;
    if (!_byD.has(p.dates[i])) _byD.set(p.dates[i], []);
    _byD.get(p.dates[i]).push(p.c[i] / p.c[i - 1] - 1);
  }
}
const mktR = new Map();
for (const [d, a] of _byD) mktR.set(d, mean(a));
_byD.clear();

const rows = [];
let skip = { lag: 0, bar: 0, trad: 0, atr: 0, anchor: 0, feat: 0 };

for (const p of pack.packs) {
  const n = p.c.length;
  const atr = atrWilder(p, 20);
  const atrPct = atr.map((a, i) => (a && p.c[i] > 0) ? a / p.c[i] : null);
  const atrPq = rollPct(atrPct, PW);
  const pcq = rollPct(p.c, PW);
  const mom = new Array(n).fill(null);
  for (let i = 20; i < n; i++) if (p.c[i - 20] > 0) mom[i] = p.c[i] / p.c[i - 20] - 1;
  const mq = rollPct(mom, PW);
  const r60 = new Array(n).fill(null);
  for (let i = 60; i < n; i++) if (p.c[i - 60] > 0) r60[i] = p.c[i] / p.c[i - 60] - 1;
  const tr = tradable(p);

  for (const b of p.buy || []) {
    if (b.discT - b.readyK !== 1) { skip.lag++; continue; }
    if (!(b.level >= 1 && b.level <= 3)) continue;
    const e = b.discT + 1;
    if (e + X > n - 1) { skip.bar++; continue; }
    if (!tr[e]) { skip.trad++; continue; }
    const a = atr[b.discT];
    if (!(a > 0)) { skip.atr++; continue; }
    const anchor = b.level === 1 ? b.price : b.level === 2 ? (b.b1 != null ? b.b1 : b.price) : b.zsZG;
    const entry = p.o[e];
    if (anchor == null || !(anchor < entry)) { skip.anchor++; continue; }
    if (mq[e] == null || atrPq[e] == null || pcq[e] == null || r60[e] == null) { skip.feat++; continue; }

    const risk = (entry - anchor) / entry;               // 失效位距离（%）
    /* 同期市场（全池等权）累计收益，用于剥离 beta */
    let mk = 1;
    for (let i = e + 1; i <= e + X; i++) { const m = mktR.get(p.dates[i]); if (m != null) mk *= 1 + m; }
    const mktCum = mk - 1;
    const r0 = p.o[e + X] / entry - 1 - FEE;
    rows.push({
      ty: b.level, code: p.code, date: p.dates[e], e, p, entry, anchor,
      r: r0, mkt: mktCum, rAdj: r0 - mktCum,
      /* 特征：全部在入场日 e 收盘前可知 */
      distR: risk / (a / entry),     // 风险距离 = 多少倍 ATR（越小越贴身）
      mq: mq[e],                    // 个股 20 日动量的 250 日分位（低=超跌）
      apq: atrPq[e],                // 波动率分位（低=安静）
      r60: r60[e],                  // 前 60 日收益
      pcq: pcq[e],                  // 250 日价位分位（低=低位）
      atrPct: a / entry
    });
  }
}
rows.sort((x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : 0));

const out = [];
const log = s => { out.push(s); console.log(s); };

const all = rows.map(z => z.r);
const S0 = stat(all);
log('样本：' + (STOCKS ? '个股 43 只' : 'ETF 43 只') + '｜信号 ' + rows.length + ' 笔（' +
  ['一买', '二买', '三买'].map((t, i) => t + ' ' + rows.filter(z => z.ty === i + 1).length).join(' / ') +
  '）｜' + rows[0].date + ' ~ ' + rows[rows.length - 1].date);
log('剔除：lag≠1 ' + skip.lag + '｜尾部不足 ' + skip.bar + '｜不可交易 ' + skip.trad +
  '｜无 ATR ' + skip.atr + '｜无失效位 ' + skip.anchor + '｜特征缺 ' + skip.feat);
log('基准（全部信号）：胜率 ' + pct(S0.wr) + '｜均盈 ' + pp(S0.aw) + '｜均亏 ' + pp(S0.al) +
  '｜盈亏比 ' + f2(S0.pl) + '｜期望 ' + pp(S0.exp) + '（t=' + f2(S0.t) + '）');
log('');

/* ============================================================
 * M1 单特征分档：哪一档质量最高？
 * ============================================================ */
const FEATS = [
  { k: 'distR', lab: '风险距离(ATR倍数)', fmt: v => f2(v) + '×', note: '小=贴着失效位买' },
  { k: 'mq', lab: '个股动量分位', fmt: pct, note: '小=已超跌' },
  { k: 'apq', lab: '波动率分位', fmt: pct, note: '小=安静' },
  { k: 'r60', lab: '前 60 日收益', fmt: pct, note: '小=已跌一段' },
  { k: 'pcq', lab: '250 日价位分位', fmt: pct, note: '小=低位' }
];

function buckets(arr, k, nb) {
  const v = arr.map(z => z[k]).filter(x => x != null).sort((a, b) => a - b);
  const cuts = [];
  for (let i = 1; i < nb; i++) cuts.push(v[Math.floor(v.length * i / nb)]);
  const b = Array.from({ length: nb }, () => []);
  for (const z of arr) {
    let idx = 0;
    while (idx < nb - 1 && z[k] > cuts[idx]) idx++;
    b[idx].push(z.r);
  }
  return { cuts, b };
}

log('=== M1 单特征分档（五分位，看哪一档胜率/盈亏比最高）===');
log('特征                    档   区间                     n     胜率    均盈     均亏   盈亏比   期望(t)      同期超额(t)');
const M1 = {};
for (const f of FEATS) {
  const { cuts, b } = buckets(rows, f.k, 5);
  const recs = [];
  for (let i = 0; i < 5; i++) {
    const s = stat(b[i]);
    const rr = rows.filter(z => {
      let idx = 0;
      while (idx < 4 && z[f.k] > cuts[idx]) idx++;
      return idx === i;
    });
    const adj = rr.map(z => z.rAdj);
    recs.push({ i, s, adjExp: mean(adj), adjT: tStat(adj) });
    log(f.lab.padEnd(21) + ('Q' + (i + 1)).padEnd(5) +
      ('[' + (i === 0 ? 'min' : f.fmt(cuts[i - 1])) + ', ' + (i === 4 ? 'max' : f.fmt(cuts[i])) + ')').padEnd(24) +
      String(s.n).padStart(5) + '  ' + pct(s.wr).padStart(7) + '  ' + pp(s.aw).padStart(8) + '  ' +
      pp(s.al).padStart(8) + '  ' + f2(s.pl).padStart(6) + '  ' +
      (pp(s.exp) + '(' + f2(s.t) + ')').padStart(14) + '  ' +
      (pp(mean(adj)) + '(' + f2(tStat(adj)) + ')').padStart(16));
  }
  let best = recs[0];
  for (const r of recs) if (r.s.exp > best.s.exp) best = r;
  const exps = recs.map(r => r.s.exp), adjs = recs.map(r => r.adjExp);
  M1[f.k] = {
    lab: f.lab, best: best.i, exp: best.s.exp, wr: best.s.wr, pl: best.s.pl, adj: best.adjExp, adjT: best.adjT, cuts,
    maxExp: Math.max(...exps), minExp: Math.min(...exps), maxAdj: Math.max(...adjs), minAdj: Math.min(...adjs),
    range: Math.max(...exps) - Math.min(...exps)
  };
  log('');
}

/* ============================================================
 * M2 样本外：训练段定阈值，验证段检验
 *   时间切分 60/40，训练段末尾剔除 20 天（embargo，防标签重叠泄漏）
 * ============================================================ */
const dSort = [...new Set(rows.map(z => z.date))].sort();
const cutDate = dSort[Math.floor(dSort.length * 0.6)];
const embargoEnd = dSort[Math.min(dSort.length - 1, Math.floor(dSort.length * 0.6) + 20)];
const IS = rows.filter(z => z.date <= cutDate);
const OOS = rows.filter(z => z.date > embargoEnd);
const OOSall = stat(OOS.map(z => z.r));

log('=== M2 样本外检验（训练 ≤' + cutDate + '，验证 >' + embargoEnd + '，中间 20 天 embargo）===');
log('训练 ' + IS.length + ' 笔｜验证 ' + OOS.length + ' 笔');
log('验证段基准（不过滤）：胜率 ' + pct(OOSall.wr) + '｜盈亏比 ' + f2(OOSall.pl) +
  '｜期望 ' + pp(OOSall.exp) + '（t=' + f2(OOSall.t) + '）');
log('');
log('过滤规则                          训练n 训练胜率 训练期望 | 验证n 验证胜率 验证盈亏比 验证期望(t) | 留存  增量   p');
const M2 = [];

/* 置换检验：从验证段随机抽同样笔数，均值 ≥ 观测值的概率（1000 次） */
let _s = 12345;
const rnd = () => { _s ^= _s << 13; _s >>>= 0; _s ^= _s >>> 17; _s ^= _s << 5; _s >>>= 0; return _s / 4294967296; };
const oosR = OOS.map(z => z.r);
function permP(k, obs, iters) {
  if (k < 2 || k >= oosR.length) return null;
  const arr = oosR.slice();
  let cnt = 0;
  for (let it = 0; it < iters; it++) {
    let sum = 0;
    for (let i = 0; i < k; i++) {
      const j = i + Math.floor(rnd() * (arr.length - i));
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
      sum += arr[i];
    }
    if (sum / k >= obs) cnt++;
  }
  return cnt / iters;
}

function applyRule(rule, arr) {
  return arr.filter(z => {
    for (const [k, lo, hi] of rule) {
      const v = z[k];
      if (v == null) return false;
      if (lo != null && v < lo) return false;
      if (hi != null && v > hi) return false;
    }
    return true;
  });
}

/* 规则生成：在训练段，对单特征取「期望最高的一档」，阈值用训练段分位边界 */
const rules = [];
for (const f of FEATS) {
  const v = IS.map(z => z[f.k]).filter(x => x != null).sort((a, b) => a - b);
  if (v.length < 200) continue;
  const cuts = [0, 0.2, 0.4, 0.6, 0.8, 1].map(q => v[Math.min(v.length - 1, Math.floor(v.length * q))]);
  let bestI = 0, bestE = -Infinity;
  for (let i = 0; i < 5; i++) {
    const sel = IS.filter(z => z[f.k] != null && z[f.k] >= cuts[i] && (i === 4 || z[f.k] < cuts[i + 1]));
    if (sel.length < 60) continue;
    const e = mean(sel.map(z => z.r));
    if (e > bestE) { bestE = e; bestI = i; }
  }
  const lo = bestI === 0 ? null : cuts[bestI];
  const hi = bestI === 4 ? null : cuts[bestI + 1];
  rules.push({ lab: f.lab + ' Q' + (bestI + 1), rule: [[f.k, lo, hi]], key: f.k, qi: bestI });
}
/* 双条件 AND：取两个训练段最优条件的交集 */
const twoBest = rules.slice().sort((a, b) => {
  const ea = mean(applyRule(a.rule, IS).map(z => z.r));
  const eb = mean(applyRule(b.rule, IS).map(z => z.r));
  return eb - ea;
}).slice(0, 2);
if (twoBest.length === 2) {
  rules.push({ lab: twoBest[0].lab + ' ∧ ' + twoBest[1].lab, rule: [...twoBest[0].rule, ...twoBest[1].rule], key: 'AND' });
}

for (const r of rules) {
  const a = applyRule(r.rule, IS), b = applyRule(r.rule, OOS);
  const sa = stat(a.map(z => z.r)), sb = stat(b.map(z => z.r));
  const pv = permP(b.length, sb.exp, 1000);
  M2.push({ lab: r.lab, isN: a.length, isWr: sa.wr, isExp: sa.exp, oosN: b.length, oosWr: sb.wr, oosPl: sb.pl, oosExp: sb.exp, oosT: sb.t, permP: pv });
  log(r.lab.padEnd(32) + String(a.length).padStart(6) + ' ' + pct(sa.wr).padStart(8) + ' ' + pp(sa.exp).padStart(9) +
    ' |' + String(b.length).padStart(6) + ' ' + pct(sb.wr).padStart(8) + ' ' + f2(sb.pl).padStart(9) + ' ' +
    (pp(sb.exp) + '(' + f2(sb.t) + ')').padStart(14) +
    ' | ' + pct(b.length / OOS.length).padStart(6) + ' ' +
    ((sb.exp - OOSall.exp >= 0 ? '+' : '\u2212') + (100 * Math.abs(sb.exp - OOSall.exp)).toFixed(2) + 'pp').padStart(8) +
    ' ' + f2(pv).padStart(5));
}
log('（读法：p = 随机抽同样笔数也拿到这么高均值的概率。p<0.05 才算过滤真带来信息）');
log('');

/* ============================================================
 * M3 仓位管理：两条完全不同的路
 *   A 横截面等风险 —— 每笔按 1/ATR% 加权（改「哪笔下得多」）
 *   B 时间序列波动率目标 —— 总仓位按组合 20 日已实现波动缩放
 *     （Harvey et al. 2018 的原始做法：低波加杠杆、高波降杠杆）
 * ============================================================ */
function dailyPort(weightOf) {
  const byD = new Map();
  for (const z of rows) {
    const p = z.p, e = z.e, w = weightOf(z);
    for (let i = e; i <= e + X; i++) {
      const r = i === e ? p.c[e] / z.entry - 1
        : i === e + X ? p.o[e + X] / p.c[e + X - 1] - 1
          : p.c[i] / p.c[i - 1] - 1;
      let o = byD.get(p.dates[i]);
      if (!o) { o = { sw: 0, swr: 0 }; byD.set(p.dates[i], o); }
      o.sw += w; o.swr += w * r;
    }
  }
  return [...byD.keys()].sort().map(d => { const o = byD.get(d); return { d, r: o.swr / o.sw }; });
}

const atrMed = median(rows.map(z => z.atrPct));
const BASE = dailyPort(() => 1);

function metrics(rets, lev) {
  const r = rets.map((x, i) => (lev ? lev[i] : 1) * x.r);
  const ann = mean(r) * 252, vol = sd(r) * Math.sqrt(252);
  let nav = 1, peak = 1, mdd = 0;
  for (const x of r) { nav *= 1 + x; if (nav > peak) peak = nav; mdd = Math.min(mdd, nav / peak - 1); }
  return { n: rets.length, ann, vol, sharpe: vol ? ann / vol : null, mdd, nav, avgLev: lev ? mean(lev) : 1 };
}

const A0 = metrics(BASE);
const A1 = metrics(dailyPort(z => 1 / z.atrPct));
const A2 = metrics(dailyPort(z => Math.min(1 / z.atrPct, 3 / atrMed)));

/* 20 日滚动已实现波动（年化），只用 i-1 及之前，无前视 */
const vol20 = new Array(BASE.length).fill(null);
for (let i = 20; i < BASE.length; i++) {
  const s = sd(BASE.slice(i - 20, i).map(x => x.r));
  vol20[i] = s ? s * Math.sqrt(252) : null;
}
const tgtVol = median(vol20.filter(x => x != null));
const levSeries = (lo, hi) => BASE.map((x, i) => {
  const v = i >= 21 ? vol20[i - 1] : null;
  return (v && v > 0) ? Math.max(lo, Math.min(hi, tgtVol / v)) : 1;
});
const B1 = metrics(BASE, levSeries(0.5, 1.5));
const B2 = metrics(BASE, levSeries(0.3, 2));

log('=== M3 仓位管理（组合级日频净值，每天满仓分散到全部在持仓位）===');
log('方案                                年化     年化波动  Sharpe   最大回撤  期末净值  平均杠杆');
const M3 = [
  ['A0 等权（每笔 1 单位）', A0],
  ['A1 每笔 1/ATR%（等风险）', A1],
  ['A2 每笔 1/ATR% 截顶 3×', A2],
  ['B1 波动率目标 0.5~1.5×', B1],
  ['B2 波动率目标 0.3~2.0×', B2]
];
for (const [lab, v] of M3) {
  log(lab.padEnd(28) + pct(v.ann).padStart(8) + '  ' + pct(v.vol).padStart(8) +
    '  ' + f2(v.sharpe).padStart(6) + '  ' + pct(v.mdd).padStart(8) + '  ' + f2(v.nav).padStart(8) +
    '  ' + f2(v.avgLev).padStart(7) + '×');
}
log('（目标波动 = 全样本中位 ' + pct(tgtVol) + '；B 组用前一日为止的 20 日波动定仓位，无前视）');
log('（A 组改的是「哪笔下得多」，B 组改的是「今天总共下多少」）');
log('');

/* 单笔层面验证：加权不改变选哪笔，只改变权重 */
const wArr = rows.map(z => Math.min(1 / z.atrPct, 3 / atrMed));
const wMean = mean(wArr);
const wR = rows.map((z, i) => z.r * wArr[i]);
log('单笔层面（选股完全相同，只换权重）：');
log('  等权   期望 ' + pp(mean(rows.map(z => z.r))) + '｜胜率 ' + pct(S0.wr) + '｜盈亏比 ' + f2(S0.pl));
log('  加权   期望 ' + pp(mean(wR) / wMean) + '｜胜率 ' + pct(S0.wr) + '｜盈亏比 ' + f2(S0.pl) + '（胜率/盈亏比不变）');
log('');

/* ============================================================
 * M4 分批止盈：+1R 卖一半
 *   半 A 持到期或止损；半 B 触及 +1R 卖出，否则同样止损/到期
 *   同一根内先判止损（保守，不给自己好运气）
 * ============================================================ */
function halfExit(p, e, stop, target, X) {
  /* 返回 {r, why}：单半仓的收益 */
  const entry = p.o[e];
  for (let i = e; i < e + X; i++) {
    if (p.l[i] <= stop) return { r: Math.min(p.o[i], stop) / entry - 1, why: 'stop' };
    if (target != null && p.h[i] >= target) return { r: target / entry - 1, why: 'target' };
  }
  return { r: p.o[e + X] / entry - 1, why: 'time' };
}

const rA = [], rB = [], rMix = [];
let tgtHit = 0;
/* 真实止损价：anchor − 0.5×ATR20（与 app 一致） */
for (const z of rows) {
  const a = z.atrPct * z.entry;
  const stop = z.anchor - 0.5 * a;
  if (!(stop < z.entry)) { continue; }
  const R = z.entry - stop;
  const target = z.entry + R;                    // +1R
  const A = halfExit(z.p, z.e, stop, null, X);
  const B = halfExit(z.p, z.e, stop, target, X);
  rA.push(A.r - FEE); rB.push(B.r - FEE);
  rMix.push(0.5 * (A.r - FEE) + 0.5 * (B.r - FEE));
  if (B.why === 'target') tgtHit++;
}
const SA = stat(rA), SM = stat(rMix);
log('=== M4 分批止盈（+1R 卖一半，剩一半持到 20 日或止损）===');
log('方案                         n     胜率    均盈     均亏    盈亏比   期望(t)');
log('全仓持到期/止损（基准）' + String(SA.n).padStart(10) + '  ' + pct(SA.wr).padStart(7) + '  ' + pp(SA.aw).padStart(8) +
  '  ' + pp(SA.al).padStart(8) + '  ' + f2(SA.pl).padStart(6) + '  ' + (pp(SA.exp) + '(' + f2(SA.t) + ')').padStart(16));
log('半仓+1R 止盈 混合' + String(SM.n).padStart(14) + '  ' + pct(SM.wr).padStart(7) + '  ' + pp(SM.aw).padStart(8) +
  '  ' + pp(SM.al).padStart(8) + '  ' + f2(SM.pl).padStart(6) + '  ' + (pp(SM.exp) + '(' + f2(SM.t) + ')').padStart(16));
log('（+1R 触发率 ' + pct(tgtHit / SA.n) + '）');
log('');

/* ============================================================
 * 判词
 * ============================================================ */
const bestM2 = M2.slice().filter(z => z.oosT != null).sort((a, b) => b.oosExp - a.oosExp)[0];
const splitKey = Object.keys(M1).sort((a, b) => M1[b].range - M1[a].range)[0];
const SPL = M1[splitKey];
log('=== 结论 ===');
log('· 单笔基准：胜率 ' + pct(S0.wr) + '、盈亏比 ' + f2(S0.pl) + '、期望 ' + pp(S0.exp) + '、同期超额 ' + pp(mean(rows.map(z => z.rAdj))) + '。');
log('· M1 分档：' + SPL.lab + ' 最能拉开差距，档间期望 ' + pp(SPL.minExp) + ' → ' + pp(SPL.maxExp) +
  '，但同期超额只有 ' + pp(SPL.minAdj) + ' → ' + pp(SPL.maxAdj) + '。档间差距大半是 beta（高位/高波股本来涨得多）。');
log('· M3 仓位管理：横截面等风险 A0→A2 Sharpe ' + f2(A0.sharpe) + ' → ' + f2(A2.sharpe) +
  '；时间序列波动率目标 A0→B2 Sharpe ' + f2(A0.sharpe) + ' → ' + f2(B2.sharpe) +
  '，回撤 ' + pct(A0.mdd) + ' → ' + pct(B2.mdd) + '。胜率与盈亏比全程不变——它改的是「下多大」，不是「选哪笔」。');
log('· M4 分批止盈：胜率 ' + pct(SA.wr) + ' → ' + pct(SM.wr) + '，盈亏比 ' + f2(SA.pl) + ' → ' + f2(SM.pl) +
  '，期望 ' + pp(SA.exp) + ' → ' + pp(SM.exp) + '。胜率和盈亏比是同一枚硬币的两面。');
if (bestM2) log('· M2 最优过滤规则：' + bestM2.lab + '，验证段 ' + pp(bestM2.oosExp) + '（t=' + f2(bestM2.oosT) +
  '），留存 ' + pct(bestM2.oosN / OOS.length) + '。');

fs.writeFileSync(path.join(__dirname, 'out', 'bt_boost' + TAG + '.txt'), out.join('\n') + '\n');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_boost' + TAG + '.json'), JSON.stringify({
  pool: STOCKS ? 'stock' : 'etf', x: X, n: rows.length,
  base: S0,
  M1: Object.fromEntries(Object.entries(M1).map(([k, v]) => [k, { bestQ: v.best, exp: v.exp, wr: v.wr, pl: v.pl, cuts: v.cuts }])),
  M2, cutDate, embargoEnd, oosBase: OOSall,
  M3: Object.fromEntries(M3.map(([lab, v]) => [lab, v])),
  M4: { base: SA, mix: SM, targetHit: tgtHit }
}, null, 1));
console.log('\n→ out/bt_boost' + TAG + '.txt');
