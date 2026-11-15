/* ==========================================================================
 * diag3.js —— 三买到底有没有被冤枉：四个诊断
 *
 *   1) 入场位置画像：入场价比中枢上沿高多少、入场前已经涨了多少
 *   2) 路径画像：MFE / MAE、"先到 +10% 还是先到 -5%"
 *   3) 换基准：同价位 + 同动量（把"买涨"这个因子也扣掉）
 *   4) 对照：不用缠论，纯「60 日新高」突破入场，同样的超额口径
 *
 * 用法：STOCKS=1 node diag3.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json'), 'utf8'));

const PCT_WIN = 250, PCT_BAND = 0.15, MIN_POOL = 8, FEE = 0.001;
const XS = [20, 60];

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const sd = a => {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / (a.length - 1));
};
const tStat = a => { const s = sd(a); return (s && s > 0) ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const median = a => {
  if (!a.length) return null;
  const b = a.slice().sort((x, y) => x - y), h = b.length >> 1;
  return b.length % 2 ? b[h] : (b[h - 1] + b[h]) / 2;
};
const pct = v => v == null ? '—' : (100 * v).toFixed(2) + '%';
const pp = v => v == null ? '—' : (v >= 0 ? '+' : '') + (100 * v).toFixed(2) + 'pp';
const f2 = v => v == null ? '—' : v.toFixed(2);

function pctSeries(p) {
  const n = p.c.length, out = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) { if (p.c[j] < lo) lo = p.c[j]; if (p.c[j] > hi) hi = p.c[j]; }
    out[i] = hi > lo ? (p.c[i] - lo) / (hi - lo) : null;
  }
  return out;
}

/* 个股不可入场日：一字涨停（买不进）、停牌复牌（跳空） */
function tradableMask(p) {
  const n = p.o.length, ok = new Array(n).fill(true);
  if (!STOCKS) return ok;
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    const gap = (Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 86400000;
    if (gap > 15) ok[i] = false;
  }
  return ok;
}

/* 入场后先摸 +up 还是先摸 -dn（同一根都摸到时按先亏算，保守） */
function firstTouch(p, e, up, dn, horizon) {
  const base = p.o[e];
  for (let i = 1; i <= horizon && e + i < p.o.length; i++) {
    const hi = p.h[e + i] / base - 1, lo = p.l[e + i] / base - 1;
    if (lo <= -dn) return -1;
    if (hi >= up) return 1;
  }
  return 0;
}

/* ---------------- 逐标的预处理 ---------------- */
const rows = { L1: [], L2: [], L3: [], NEW60: [] };
const dayPool = [];            // 全部可入场日：用于「同价位同动量」对照与全局路径参照

for (const p of pack.packs) {
  const n = p.o.length, trad = tradableMask(p);
  const pq = pctSeries(p);
  const qs = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));
  const mom = new Array(n).fill(null);
  for (let i = 60; i < n; i++) if (p.c[i - 20] > 0) mom[i] = p.c[i] / p.c[i - 20] - 1;

  /* 全部可入场日（每个 x 都要能算出收益才算） */
  const days = { 20: {}, 60: {} };
  for (const x of XS) {
    const g = {};
    for (let t = p.warmup; t + x <= n - 1; t++) {
      if (!trad[t] || pq[t] == null || mom[t] == null) continue;
      const r = p.o[t + x] / p.o[t] - 1 - FEE;
      (g[qs[t]] = g[qs[t]] || []).push({ t, r, pc: pq[t], mom: mom[t] });
    }
    days[x] = g;
  }

  const push = (ty, b, e, extra) => {
    const rec = { code: p.code, date: p.dates[e], e, pct: pq[e], mom20: mom[e] };
    for (const x of XS) {
      if (e + x > n - 1) { rec['r' + x] = null; continue; }
      rec['r' + x] = p.o[e + x] / p.o[e] - 1 - FEE;
      /* 同价位 + 同动量 基准（B5）：同季度、分位 ±0.15、入场前 20 日涨幅 ±6pp */
      const pool = (days[x][qs[e]] || []).filter(z =>
        Math.abs(z.pc - pq[e]) <= PCT_BAND && Math.abs(z.mom - mom[e]) <= 0.06 && z.t !== e);
      rec['B5_' + x] = pool.length >= MIN_POOL ? mean(pool.map(z => z.r)) : null;
      /* 同价位基准（B4，与主报告一致），用来确认复现 */
      const pool4 = (days[x][qs[e]] || []).filter(z => Math.abs(z.pc - pq[e]) <= PCT_BAND && z.t !== e);
      rec['B4_' + x] = pool4.length >= MIN_POOL ? mean(pool4.map(z => z.r)) : null;
    }
    rec.mfe20 = null; rec.mae20 = null;
    if (e + 20 <= n - 1) {
      let mf = -Infinity, ma = Infinity;
      for (let i = 1; i <= 20; i++) { mf = Math.max(mf, p.h[e + i] / p.o[e] - 1); ma = Math.min(ma, p.l[e + i] / p.o[e] - 1); }
      rec.mfe20 = mf; rec.mae20 = ma;
    }
    rec.t53 = firstTouch(p, e, 0.05, 0.03, 20);
    rec.t105 = firstTouch(p, e, 0.10, 0.05, 20);
    if (extra) Object.assign(rec, extra);
    rows[ty].push(rec);
  };

  /* 三类买点 */
  for (const b of p.buy || []) {
    if (b.discT - b.readyK !== 1) continue;
    const e = b.discT + 1;
    if (e + XS[0] > n - 1 || !trad[e] || pq[e] == null || mom[e] == null) continue;
    const ty = 'L' + b.level;
    if (!rows[ty]) continue;
    const distZG = (b.zsZG && b.zsZG > 0) ? p.o[e] / b.zsZG - 1 : null;
    push(ty, b, e, { distZG, zsZG: b.zsZG });
  }

  /* 对照：不用缠论，收盘创 60 日新高 → 次日开盘买 */
  for (let t = p.warmup + 60; t + 60 <= n - 1; t++) {
    if (!trad[t] || pq[t] == null || mom[t] == null) continue;
    let mx = -Infinity;
    for (let j = t - 59; j <= t - 1; j++) if (p.c[j] > mx) mx = p.c[j];
    if (p.c[t] <= mx) continue;
    const e = t + 1;
    if (e + XS[0] > n - 1 || !trad[e]) continue;
    push('NEW60', null, e, {});
  }

  /* 全局参照：任意可入场日的 MFE/MAE */
  for (let t = p.warmup; t + 20 <= n - 1; t++) {
    if (!trad[t] || pq[t] == null) continue;
    let mf = -Infinity, ma = Infinity;
    for (let i = 1; i <= 20; i++) { mf = Math.max(mf, p.h[t + i] / p.o[t] - 1); ma = Math.min(ma, p.l[t + i] / p.o[t] - 1); }
    dayPool.push({ t, code: p.code, pct: pq[t], mfe: mf, mae: ma, t53: firstTouch(p, t, 0.05, 0.03, 20), t105: firstTouch(p, t, 0.10, 0.05, 20) });
  }
}

/* ---------------- 1) 入场位置画像 ---------------- */
console.log('=== 1) 入场时处在什么位置（个股，lag=1，可入场）===');
console.log('类型      笔数    250日分位中位   入场前20日涨幅均值   入场价距中枢上沿(中位)  >10%的占比');
for (const ty of ['L1', 'L2', 'L3', 'NEW60']) {
  const g = rows[ty];
  const m = g.map(z => z.mom20).filter(v => v != null);
  const d = ty === 'L3' ? g.map(z => z.distZG).filter(v => v != null) : [];
  console.log(ty.padEnd(7) + String(g.length).padStart(6) + '  ' +
    pct(median(g.map(z => z.pct))).padStart(12) + '  ' + pct(mean(m)).padStart(16) + '  ' +
    (d.length ? pct(median(d)).padStart(20) + '  ' + pct(d.filter(v => v > 0.10).length / d.length).padStart(9) : ' '.repeat(20) + '  ' + '—'.padStart(9)));
}

/* ---------------- 2) 路径画像 ---------------- */
console.log('\n=== 2) 入场后 20 根的路径（不是终点收益，是最有利/最不利波幅）===');
console.log('类型      MFE中位   MAE中位   MFE/MAE   先+5%后-3%   先+10%后-5%');
function pathLine(name, g) {
  const mf = g.map(z => z.mfe20 != null ? z.mfe20 : z.mfe).filter(v => v != null);
  const ma = g.map(z => z.mae20 != null ? z.mae20 : z.mae).filter(v => v != null);
  const a = g.map(z => z.t53).filter(v => v != null);
  const b = g.map(z => z.t105).filter(v => v != null);
  const w1 = a.filter(v => v === 1).length / a.length, w2 = b.filter(v => v === 1).length / b.length;
  console.log(name.padEnd(7) + pct(median(mf)).padStart(9) + pct(median(ma)).padStart(10) + '   ' +
    f2(median(mf) / Math.abs(median(ma))).padStart(6) + '   ' + pct(w1).padStart(9) + '   ' + pct(w2).padStart(10));
}
for (const ty of ['L1', 'L2', 'L3', 'NEW60']) pathLine(ty, rows[ty]);
pathLine('任意日', dayPool.map(z => ({ mfe20: z.mfe, mae20: z.mae, t53: z.t53, t105: z.t105 })));

/* ---------------- 3) 同价位 + 同动量 基准 ---------------- */
console.log('\n=== 3) 换基准：把「买涨」也扣掉（同季度 + 同价位 ±0.15 + 入场前20日涨幅 ±6pp）===');
console.log('类型     x     n    单笔       vs同价位(t)          vs同价位同动量(t)');
for (const ty of ['L1', 'L2', 'L3', 'NEW60']) {
  for (const x of XS) {
    const g = rows[ty].filter(z => z['r' + x] != null);
    const e4 = g.filter(z => z['B4_' + x] != null).map(z => z['r' + x] - z['B4_' + x]);
    const e5 = g.filter(z => z['B5_' + x] != null).map(z => z['r' + x] - z['B5_' + x]);
    console.log(ty.padEnd(7) + String(x).padStart(3) + String(g.length).padStart(6) + pct(mean(g.map(z => z['r' + x]))).padStart(9) +
      '   ' + (pp(mean(e4)) + '(' + f2(tStat(e4)) + ')').padStart(20) +
      '   ' + (pp(mean(e5)) + '(' + f2(tStat(e5)) + ')').padStart(22));
  }
}

/* ---------------- 4) 三买的「质量」分层：回踩越浅越好吗 ---------------- */
console.log('\n=== 4) 三买分层：距中枢上沿越近越好？(x=20) ===');
{
  const g = rows.L3.filter(z => z.distZG != null && z.r20 != null && z['B4_20'] != null);
  const buckets = [[-9, 0.02, '≤2%'], [0.02, 0.05, '2~5%'], [0.05, 0.10, '5~10%'], [0.10, 0.20, '10~20%'], [0.20, 9, '>20%']];
  console.log('距中枢上沿      n     单笔       vs同价位          vs同价位同动量');
  for (const [lo, hi, lab] of buckets) {
    const s = g.filter(z => z.distZG > lo && z.distZG <= hi);
    if (s.length < 20) { console.log(lab.padEnd(12) + String(s.length).padStart(5) + '  样本不足'); continue; }
    const e4 = s.map(z => z.r20 - z.B4_20), e5 = s.filter(z => z.B5_20 != null).map(z => z.r20 - z.B5_20);
    console.log(lab.padEnd(12) + String(s.length).padStart(5) + pct(mean(s.map(z => z.r20))).padStart(9) +
      '   ' + (pp(mean(e4)) + '(' + f2(tStat(e4)) + ')').padStart(16) + '   ' + (pp(mean(e5)) + '(' + f2(tStat(e5)) + ')').padStart(20));
  }
}

/* ---------------- 5) 三买 vs 一买：同一只票、同一时间窗内谁更强 ---------------- */
console.log('\n=== 5) 如果目标收益是「绝对赚钱」，三类买点的单笔均值排第几 ===');
for (const x of XS) {
  const line = ['L1', 'L2', 'L3', 'NEW60'].map(ty => {
    const g = rows[ty].filter(z => z['r' + x] != null);
    return ty + ' ' + pct(mean(g.map(z => z['r' + x])));
  }).join('   ');
  console.log('x=' + x + '  ' + line);
}
