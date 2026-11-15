/* ==========================================================================
 * bt_alpha.js —— 追问：一买的超额是「买点判断」还是「短期反转因子」？
 *
 * 做法：三层剥离
 *   B4 同季度 + 同价位（|Δpct|≤0.15）            ← 已做过
 *   B5 B4 再叠加 同 20 日动量（|Δmom|≤0.06）      ← 把「跌多了」这个因子也锁住
 *   R  纯反转策略（不做缠论，个股自身 mom20 处于低位就买）的超额
 *   M  纯动量策略（mom20 处于高位）作对照
 *
 * 如果 一买 在 B5 下还有正超额 → 买点有增量的判断力；
 * 如果 一买 ≈ 纯反转的数值 → 一买赚的是反转因子，不是缠论。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const FEE = 0.001, X = 20, PCT_WIN = 250, BAND4 = 0.15, BAND5 = 0.06, MIN_POOL = 8;
const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json'), 'utf8'));

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
function sd(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
const tStat = a => { if (a.length < 3) return null; const s = sd(a); return s ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const f2 = v => v == null ? '—' : v.toFixed(2);
const pp = v => v == null ? '—' : (v >= 0 ? '+' : '\u2212') + (100 * Math.abs(v)).toFixed(2) + 'pp';
const pctS = v => v == null ? '—' : (100 * v).toFixed(2) + '%';

function pctSeries(p) {
  const n = p.c.length, out = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) { if (p.c[j] < lo) lo = p.c[j]; if (p.c[j] > hi) hi = p.c[j]; }
    out[i] = hi > lo ? (p.c[i] - lo) / (hi - lo) : null;
  }
  return out;
}
function tradMask(p) {
  const n = p.c.length, ok = new Array(n).fill(true);
  if (!STOCKS) return ok;
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    if ((Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 864e5 > 15) ok[i] = false;
  }
  return ok;
}

const sig = { L1: [], L2: [], L3: [] };   // {ex4, ex5}
const dumb = { rev: [], mom: [], mid: [] };

for (const p of pack.packs) {
  const n = p.c.length, o = p.o;
  const pq = pctSeries(p), tr = tradMask(p);
  const qs = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));
  const mom = new Array(n).fill(null);
  for (let i = 20; i < n; i++) if (p.c[i - 20] > 0) mom[i] = p.c[i] / p.c[i - 20] - 1;
  /* 个股自身 mom20 的滚动分位（过去 250 日），用于定义「跌多了」 */
  const mq = new Array(n).fill(null);
  for (let i = 20 + 60; i < n; i++) {
    const lo = Math.max(20, i - PCT_WIN);
    let cnt = 0, below = 0;
    for (let j = lo; j < i; j++) if (mom[j] != null) { cnt++; if (mom[j] < mom[i]) below++; }
    mq[i] = cnt >= 60 ? below / cnt : null;
  }

  const byQ = {};
  for (let t = p.warmup; t + X <= n - 1; t++) {
    if (!tr[t] || pq[t] == null || mom[t] == null) continue;
    const q = qs[t];
    (byQ[q] = byQ[q] || []).push({ t, r: o[t + X] / o[t] - 1 - FEE, pc: pq[t], m: mom[t], mq: mq[t] });
  }
  /* 把同一季度的候选池按动量排好，供 B5 快速筛 */
  for (const q in byQ) byQ[q].sort((a, b) => a.m - b.m);
  const take = (q, t, pc, ps, m, mm) => {
    const pool = (byQ[q] || []).filter(z => z.t !== t && Math.abs(z.pc - pc) <= BAND4);
    if (pool.length < MIN_POOL) return null;
    const b4 = mean(pool.map(z => z.r));
    const p5 = pool.filter(z => Math.abs(z.m - m) <= BAND5);
    const b5 = p5.length >= MIN_POOL ? mean(p5.map(z => z.r)) : null;
    return { r: o[t + X] / o[t] - 1 - FEE, b4, b5 };
  };

  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1) continue;
    const e = b.discT + 1;
    if (e + X > n - 1 || !tr[e] || pq[e] == null || mom[e] == null) continue;
    const z = take(qs[e], e, pq[e], pq[e], mom[e]);
    if (!z) continue;
    const ty = 'L' + b.level;
    if (sig[ty]) sig[ty].push({ y: p.dates[e].slice(0, 4), ex4: z.r - z.b4, ex5: z.b5 == null ? null : z.r - z.b5 });
  }

  /* 纯反转 / 纯动量：不看结构，只看个股自身 mom20 的滚动分位 */
  for (let t = p.warmup; t + X <= n - 1; t++) {
    if (!tr[t] || pq[t] == null || mom[t] == null || mq[t] == null) continue;
    let bucket = null;
    if (mq[t] <= 0.10) bucket = 'rev'; else if (mq[t] >= 0.90) bucket = 'mom';
    else if (mq[t] > 0.45 && mq[t] < 0.55) bucket = 'mid';
    if (!bucket) continue;
    const z = take(qs[t], t, pq[t], pq[t], mom[t]);
    if (!z) continue;
    dumb[bucket].push({ y: p.dates[t].slice(0, 4), ex4: z.r - z.b4, r: z.r });
  }
}

const out = [];
const log = s => { out.push(s); console.log(s); };

log('样本：' + (STOCKS ? '个股 43 只' : 'ETF 43 只') + '｜x=' + X + ' 日｜扣双边费 0.1%');
log('');
log('=== 表 1 逐层剥离：超额还剩多少 ===');
log('类型      n     ex4 同季同价位(t)        ex5 再加同动量(t)       动量解释掉的比例');
for (const ty of ['L1', 'L2', 'L3']) {
  const a = sig[ty].map(z => z.ex4), b = sig[ty].filter(z => z.ex5 != null).map(z => z.ex5);
  log(ty.padEnd(6) + String(a.length).padStart(5) + '  ' + (pp(mean(a)) + '(' + f2(tStat(a)) + ')').padStart(22) +
    '  ' + (pp(mean(b)) + '(' + f2(tStat(b)) + ')').padStart(22) + '  ' +
    pctS(1 - mean(b) / mean(a)).padStart(12));
}
log('');
log('=== 表 2 不做缠论，只按「个股自身 20 日动量分位」买卖（同样扣费、同样 20 天） ===');
log('策略                          信号数   单笔收益    ex4 同季同价位(t)');
for (const [k, lab] of [['rev', '动量分位 ≤10%（跌多了）'], ['mid', '动量分位 45~55%（中间）'], ['mom', '动量分位 ≥90%（创高期）']]) {
  const s = dumb[k], e = s.map(z => z.ex4);
  log(lab.padEnd(30) + String(s.length).padStart(6) + '   ' + pp(mean(s.map(z => z.r))).padStart(9) +
    '   ' + (pp(mean(e)) + '(' + f2(tStat(e)) + ')').padStart(20));
}
log('');
log('=== 表 3 逐年：一买超额 vs 纯反转超额（看谁在衰减） ===');
log('年份  一买n  一买ex4    一买ex5    纯反转n  纯反转ex4');
const yrs = [...new Set([].concat(sig.L1.map(z => z.y), dumb.rev.map(z => z.y)))].sort();
const yrRows = [];
for (const y of yrs) {
  const a = sig.L1.filter(z => z.y === y), b = a.filter(z => z.ex5 != null);
  const d = dumb.rev.filter(z => z.y === y);
  if (a.length < 10 || d.length < 50) continue;
  const v = { y, e4: mean(a.map(z => z.ex4)), e5: mean(b.map(z => z.ex5)), d4: mean(d.map(z => z.ex4)) };
  yrRows.push(v);
  log(y + String(a.length).padStart(6) + pp(v.e4).padStart(10) + pp(v.e5).padStart(11) +
    String(d.length).padStart(9) + pp(v.d4).padStart(11));
}
const olsT = (arr, key) => {
  const pts = arr.map((z, i) => ({ x: +z.y - 2005, y: z[key] })).filter(z => z.y != null);
  const mx = mean(pts.map(z => z.x)), my = mean(pts.map(z => z.y));
  let sxy = 0, sxx = 0; for (const z of pts) { sxy += (z.x - mx) * (z.y - my); sxx += (z.x - mx) ** 2; }
  const bb = sxy / sxx, aa = my - bb * mx, res = pts.map(z => z.y - (aa + bb * z.x));
  const se = sd(res) / Math.sqrt(sxx);
  return { b: bb, t: se ? bb / se : null };
};
const r1 = olsT(yrRows, 'e4'), r2 = olsT(yrRows, 'd4');
log('');
log('斜率：一买 ' + pp(r1.b * 10) + '/10年（t=' + f2(r1.t) + '）｜纯反转 ' + pp(r2.b * 10) + '/10年（t=' + f2(r2.t) + '）');
log('');
log('（读法：ex5 掉到不显著 = 一买只是反转因子；两者斜率都接近 0 = 没有被套利掉。）');

fs.writeFileSync(path.join(__dirname, 'out', 'bt_alpha' + TAG + '.txt'), out.join('\n') + '\n');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_alpha' + TAG + '.json'), JSON.stringify({
  pool: STOCKS ? 'stock' : 'etf', x: X,
  sig: Object.fromEntries(['L1', 'L2', 'L3'].map(t => [t, {
    n: sig[t].length, ex4: mean(sig[t].map(z => z.ex4)), t4: tStat(sig[t].map(z => z.ex4)),
    ex5: mean(sig[t].filter(z => z.ex5 != null).map(z => z.ex5)),
    t5: tStat(sig[t].filter(z => z.ex5 != null).map(z => z.ex5))
  }])),
  dumb: Object.fromEntries(Object.keys(dumb).map(k => [k, {
    n: dumb[k].length, r: mean(dumb[k].map(z => z.r)),
    ex4: mean(dumb[k].map(z => z.ex4)), t4: tStat(dumb[k].map(z => z.ex4))
  }]))
}, null, 1));
console.log('\n→ out/bt_alpha' + TAG + '.txt');
