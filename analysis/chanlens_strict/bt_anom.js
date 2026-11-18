/* ==========================================================================
 * bt_anom.js —— 把论文里的公开异象放在同一个池子、同一套口径上重测
 *
 * 两部分：
 *  A. 个股内择时（与 bt_alpha.js / 一买 完全同一口径）
 *     信号取该股自身过去 250 日的分位，只买最有利的那 10% 日子，持 20 天
 *     超额 = 单笔 − 同股同季同价位对照日均值（≥8 个对照日），扣双边费 0.1%
 *     → 直接和「一买 +1.18pp」对照
 *  B. 横截面多空（与论文一致）
 *     每月末按信号排序，多前 20% / 空后 20%，等权持 1 个月（21 根）
 *     扣 0.1%/腿/月 → 得出「月均多空 %」，与 McLean-Pontiff 的 0.58%/0.26% 对照
 *
 * 用法：STOCKS=1 node bt_anom.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const FEE = 0.001, X = 20, PCT_WIN = 250, BAND4 = 0.15, BAND5 = 0.06, MIN_POOL = 8, DEC = 0.10;
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

/* ---------- 全池等权日收益（用于算特异波动） ---------- */
const byDate = new Map();   // date -> [{code, r}]
for (const p of pack.packs) {
  for (let i = 1; i < p.c.length; i++) {
    if (!(p.c[i - 1] > 0)) continue;
    const r = p.c[i] / p.c[i - 1] - 1;
    if (!byDate.has(p.dates[i])) byDate.set(p.dates[i], []);
    byDate.get(p.dates[i]).push({ code: p.code, r });
  }
}
const mktRet = new Map();
for (const [d, arr] of byDate) mktRet.set(d, mean(arr.map(z => z.r)));
byDate.clear();

/* ---------- 各信号（数值越大 = 越看多，已做方向翻转） ---------- */
const SIG = {
  REV1M: { lab: '短期反转 1M（Jegadeesh 1990）', f: (p, i) => i >= 20 && p.c[i - 20] > 0 ? -(p.c[i] / p.c[i - 20] - 1) : null },
  REV1W: { lab: '短期反转 1W', f: (p, i) => i >= 5 && p.c[i - 5] > 0 ? -(p.c[i] / p.c[i - 5] - 1) : null },
  MOM121: { lab: '动量 12-1（Jegadeesh-Titman 1993）', f: (p, i) => i >= 252 && p.c[i - 252] > 0 ? p.c[i - 21] / p.c[i - 252] - 1 : null },
  HIGH52: { lab: '距 52 周新高（George-Hwang 2004）', f: (p, i) => { if (i < 250) return null; let hi = 0; for (let j = i - 249; j <= i; j++) if (p.h[j] > hi) hi = p.h[j]; return hi > 0 ? p.c[i] / hi : null; } },
  MAX5: { lab: '低彩票需求 MAX5（Bali 2011）', f: (p, i) => { if (i < 20) return null; const a = []; for (let j = i - 19; j <= i; j++) if (p.c[j - 1] > 0) a.push(p.c[j] / p.c[j - 1] - 1); if (a.length < 20) return null; a.sort((x, y) => y - x); return -mean(a.slice(0, 5)); } },
  LOWVOL: { lab: '低波动 60D（Ang 2006）', f: (p, i) => { if (i < 61) return null; const a = []; for (let j = i - 59; j <= i; j++) if (p.c[j - 1] > 0) a.push(p.c[j] / p.c[j - 1] - 1); return a.length >= 60 ? -sd(a) : null; } },
  IVOL: {
    lab: '特异波动 60D（Ang 2006）', f: (p, i) => {
      if (i < 61) return null;
      const a = [];
      for (let j = i - 59; j <= i; j++) {
        if (!(p.c[j - 1] > 0)) continue;
        const m = mktRet.get(p.dates[j]);
        if (m == null) continue;
        a.push(p.c[j] / p.c[j - 1] - 1 - m);
      }
      return a.length >= 50 ? -sd(a) : null;
    }
  }
};
const KEYS = Object.keys(SIG);

/* ================= A. 个股内择时（同一买口径） ================= */
const resA = {}; for (const k of KEYS) resA[k] = [];
for (const p of pack.packs) {
  const n = p.c.length, o = p.o;
  const pq = pctSeries(p), tr = tradMask(p);
  const qs = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));

  const mom = new Array(n).fill(null);
  for (let i = 20; i < n; i++) if (p.c[i - 20] > 0) mom[i] = p.c[i] / p.c[i - 20] - 1;
  const byQ = {};
  for (let t = p.warmup; t + X <= n - 1; t++) {
    if (!tr[t] || pq[t] == null || mom[t] == null) continue;
    const q = qs[t];
    (byQ[q] = byQ[q] || []).push({ t, r: o[t + X] / o[t] - 1 - FEE, pc: pq[t], m: mom[t] });
  }

  for (const k of KEYS) {
    const f = SIG[k].f;
    const ser = new Array(n).fill(null);
    for (let i = 0; i < n; i++) ser[i] = f(p, i);
    for (let t = p.warmup; t + X <= n - 1; t++) {
      if (!tr[t] || pq[t] == null || ser[t] == null || mom[t] == null) continue;
      /* 自身过去 250 日的分位（严格用 t 之前，无前视） */
      let cnt = 0, below = 0;
      for (let j = Math.max(0, t - PCT_WIN); j < t; j++) if (ser[j] != null) { cnt++; if (ser[j] < ser[t]) below++; }
      if (cnt < 120) continue;
      if (below / cnt < 1 - DEC) continue;
      const pool = (byQ[qs[t]] || []).filter(z => z.t !== t && Math.abs(z.pc - pq[t]) <= BAND4);
      if (pool.length < MIN_POOL) continue;
      const p5 = pool.filter(z => Math.abs(z.m - mom[t]) <= BAND5);
      const r = o[t + X] / o[t] - 1 - FEE;
      resA[k].push({
        y: p.dates[t].slice(0, 4), r,
        ex: r - mean(pool.map(z => z.r)),
        ex5: p5.length >= MIN_POOL ? r - mean(p5.map(z => z.r)) : null
      });
    }
  }
}

/* ================= B. 横截面多空（每月末） ================= */
/* 取全池所有月末交易日（每月最后一个出现过交易的日期） */
const lastOfMonth = new Map();
for (const p of pack.packs) for (const d of p.dates) {
  const m = d.slice(0, 7);
  if (!lastOfMonth.has(m) || d > lastOfMonth.get(m)) lastOfMonth.set(m, d);
}
const rebal = [...lastOfMonth.values()].sort();
const idxOf = new Map();   // code -> Map(date -> i)
for (const p of pack.packs) { const m = new Map(); p.dates.forEach((d, i) => m.set(d, i)); idxOf.set(p.code, m); }

const resB = {}; for (const k of KEYS) resB[k] = [];
for (const d of rebal) {
  for (const k of KEYS) {
    const f = SIG[k].f, arr = [];
    for (const p of pack.packs) {
      const i = idxOf.get(p.code).get(d);
      if (i == null || i < 252 || i + 21 > p.c.length - 1) continue;
      const v = f(p, i);
      if (v == null) continue;
      arr.push({ code: p.code, v, fwd: p.c[i + 21] / p.c[i] - 1 });
    }
    if (arr.length < 20) continue;
    arr.sort((a, b) => b.v - a.v);
    const qn = Math.max(3, Math.round(arr.length * 0.2));
    const top = arr.slice(0, qn), bot = arr.slice(-qn);
    const gross = mean(top.map(z => z.fwd)) - mean(bot.map(z => z.fwd));
    resB[k].push({ d, n: arr.length, gross, net: gross - 2 * 2 * FEE });   // 两腿 × 开平
  }
}

/* ================= 输出 ================= */
const out = [];
const log = s => { out.push(s); console.log(s); };

log('样本：' + (STOCKS ? '43 只个股' : '43 只 ETF') + '｜A 段持有 ' + X + ' 日｜B 段月度调仓｜成本：A 双边 0.1%，B 每腿每月 0.1%');
log('');
log('=== 表 A 个股内择时（与「一买 +1.18pp」同一口径）===');
log('异象                              信号数   单笔       ex4(t)              ex5 同季同价位同动量(t)   与一买差');
const REF = STOCKS ? 0.0118 : 0.0130;      // 一买 ex5 参考值
for (const k of KEYS) {
  const s = resA[k], e = s.map(z => z.ex), e5 = s.filter(z => z.ex5 != null).map(z => z.ex5);
  log(SIG[k].lab.padEnd(32) + String(s.length).padStart(7) + '  ' + pp(mean(s.map(z => z.r))).padStart(8) +
    '  ' + (pp(mean(e)) + '(' + f2(tStat(e)) + ')').padStart(16) +
    '  ' + (pp(mean(e5)) + '(' + f2(tStat(e5)) + ')').padStart(24) +
    '  ' + (mean(e5) >= REF ? '更强 ' + pp(mean(e5) - REF) : '更弱 ' + pp(mean(e5) - REF)).padStart(12));
}
log('（一买 ex5 = ' + pp(REF) + '，t=7.02。全部按 ex5 同口径比较。）');
log('');
log('=== 表 B 横截面多空（每月多前 20% / 空后 20%，扣成本）===');
log('异象                              月数   月均毛     月均净     年化净    t(净)   2016前     2016后');
const resBsum = {};
for (const k of KEYS) {
  const s = resB[k];
  if (s.length < 24) { log(SIG[k].lab.padEnd(32) + '  样本不足 ' + s.length); continue; }
  const net = s.map(z => z.net);
  const pre = s.filter(z => z.d < '2016-01-01').map(z => z.net);
  const post = s.filter(z => z.d >= '2016-01-01').map(z => z.net);
  resBsum[k] = { n: s.length, gross: mean(s.map(z => z.gross)), net: mean(net), t: tStat(net), pre: mean(pre), post: mean(post), preN: pre.length, postN: post.length };
  log(SIG[k].lab.padEnd(32) + String(s.length).padStart(5) + '  ' + pp(mean(s.map(z => z.gross))).padStart(8) +
    '  ' + pp(mean(net)).padStart(9) + '  ' + pp(mean(net) * 12).padStart(8) +
    '  ' + f2(tStat(net)).padStart(6) + '  ' + pp(mean(pre)).padStart(8) + '  ' + pp(mean(post)).padStart(8));
}
log('');
log('（文献参考：97 个已发表因子，多空月均 样本内 0.58% / 样本外 0.40% / 发表后 0.26%）');

fs.writeFileSync(path.join(__dirname, 'out', 'bt_anom' + TAG + '.txt'), out.join('\n') + '\n');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_anom' + TAG + '.json'), JSON.stringify({
  pool: STOCKS ? 'stock' : 'etf', x: X,
  A: Object.fromEntries(KEYS.map(k => [k, {
    lab: SIG[k].lab, n: resA[k].length, r: mean(resA[k].map(z => z.r)),
    ex: mean(resA[k].map(z => z.ex)), t: tStat(resA[k].map(z => z.ex))
  }])),
  B: resBsum
}, null, 1));
console.log('\n→ out/bt_anom' + TAG + '.txt');
