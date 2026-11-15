/* ==========================================================================
 * bt_decay.js —— 回答两个可证伪的问题：
 *   1) 一买/二买的超额（alpha）会不会随时间衰减？—— 按年看趋势
 *   2) 这个 alpha 是「免费的钱」还是「风险补偿」？—— 看它和同期市场收益的相关性
 *
 * 口径与 bt_hold.js 完全一致：lag=1、entry=discT+1 开盘、扣双边费 0.1%、
 * 超额 = 单笔收益 − 同标的同季度同价位（|Δpct|≤0.15，≥8 个对照日）均值
 *
 * 用法：STOCKS=1 node bt_decay.js   或   node bt_decay.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const FEE = 0.001, X = 20, PCT_WIN = 250, BAND4 = 0.15, MIN_POOL = 8;
const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json'), 'utf8'));

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
function sd(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
const tStat = a => { if (a.length < 3) return null; const s = sd(a); return s ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const f2 = v => v == null ? '—' : v.toFixed(2);
const pp = v => v == null ? '—' : (v >= 0 ? '+' : '\u2212') + (100 * Math.abs(v)).toFixed(2) + 'pp';
const pct = v => v == null ? '—' : (100 * v).toFixed(2) + '%';

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

const recs = [];      // 每笔信号
const mkt = {};       // 季度 -> 全池「随便买 20 天」的平均收益（市场环境代理）

for (const p of pack.packs) {
  const n = p.c.length, o = p.o;
  const pq = pctSeries(p), tr = tradMask(p);
  const qs = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));

  const byQ = {};
  for (let t = p.warmup; t + X <= n - 1; t++) {
    if (!tr[t] || pq[t] == null) continue;
    const q = qs[t];
    (byQ[q] = byQ[q] || []).push({ t, r: o[t + X] / o[t] - 1 - FEE, pc: pq[t] });
  }
  for (const q in byQ) (mkt[q] = mkt[q] || []).push(mean(byQ[q].map(z => z.r)));

  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1) continue;
    const e = b.discT + 1;
    if (e + X > n - 1 || !tr[e] || pq[e] == null) continue;
    const pool = (byQ[qs[e]] || []).filter(z => z.t !== e && Math.abs(z.pc - pq[e]) <= BAND4);
    if (pool.length < MIN_POOL) continue;
    const r = o[e + X] / o[e] - 1 - FEE;
    recs.push({ ty: 'L' + b.level, date: p.dates[e], q: qs[e], r, ex: r - mean(pool.map(z => z.r)) });
  }
}

const quarters = Object.keys(mkt).sort().map(q => ({ q, m: mean(mkt[q]) }));
const qmap = new Map(quarters.map(z => [z.q, z.m]));
const out = [];
const log = s => { out.push(s); console.log(s); };

log('样本：' + (STOCKS ? '个股' : 'ETF') + '｜x=' + X + ' 日｜可配对信号 ' + recs.length + ' 笔｜季度数 ' + quarters.length);
log('');

/* ---------- 表 1：按年 ---------- */
log('=== 表 1 超额按入场年份 ===');
log('年份  一买n   一买超额(t)         二买n   二买超额            三买n   三买超额');
const years = [...new Set(recs.map(z => z.date.slice(0, 4)))].sort();
const yrStat = {};
for (const y of years) {
  const line = [y];
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = recs.filter(z => z.ty === ty && z.date.startsWith(y)).map(z => z.ex);
    yrStat[y] = yrStat[y] || {};
    yrStat[y][ty] = { n: s.length, m: mean(s), t: tStat(s) };
    line.push(String(s.length).padStart(5), (pp(mean(s)) + '(' + f2(tStat(s)) + ')').padStart(19));
  }
  log(line.join(' '));
}

/* ---------- 表 2：衰减回归（超额 ~ 年份） ---------- */
function ols(pts) {
  const n = pts.length, mx = mean(pts.map(z => z.x)), my = mean(pts.map(z => z.y));
  let sxy = 0, sxx = 0;
  for (const z of pts) { sxy += (z.x - mx) * (z.y - my); sxx += (z.x - mx) * (z.x - mx); }
  const b = sxy / sxx, a = my - b * mx;
  const res = pts.map(z => z.y - (a + b * z.x));
  const se = sd(res) / Math.sqrt(sxx);
  return { b, t: se ? b / se : null };
}
log('');
log('=== 表 2 每 10 年超额衰减多少（按年回归，加权=逐年均值）===');
for (const ty of ['L1', 'L2', 'L3']) {
  const pts = years.map(y => ({ x: +y - 2005, y: yrStat[y][ty].m })).filter(z => z.y != null);
  const o = ols(pts);
  const first = mean(pts.slice(0, 8).map(z => z.y)), last = mean(pts.slice(-6).map(z => z.y));
  log('  ' + ty + '：斜率 ' + pp(o.b * 10) + '/10年（t=' + f2(o.t) + '）｜2005-2012 均值 ' + pp(first) +
    ' → 2021-2026 均值 ' + pp(last) + '｜差 ' + pp(last - first));
}

/* ---------- 表 3：alpha 是免费的钱还是风险补偿 ---------- */
log('');
log('=== 表 3 超额与同期市场环境的关系（按季度，x=' + X + '）===');
log('市场环境 = 全池「随便买 20 天」的季度均值');
for (const ty of ['L1', 'L2', 'L3']) {
  const pts = quarters.map(z => {
    const s = recs.filter(r => r.ty === ty && r.q === z.q).map(r => r.ex);
    return s.length >= 3 ? { x: z.m, y: mean(s), n: s.length } : null;
  }).filter(Boolean);
  if (pts.length < 8) { log('  ' + ty + '：季度样本不足'); continue; }
  const mx = mean(pts.map(z => z.x)), my = mean(pts.map(z => z.y));
  let sxy = 0, sxx = 0, syy = 0;
  for (const z of pts) { sxy += (z.x - mx) * (z.y - my); sxx += (z.x - mx) ** 2; syy += (z.y - my) ** 2; }
  const corr = sxy / Math.sqrt(sxx * syy);
  const mid = pts.slice().sort((a, b) => a.x - b.x);
  const half = Math.floor(mid.length / 2);
  const down = mean(mid.slice(0, half).map(z => z.y)), up = mean(mid.slice(half).map(z => z.y));
  const dn = mean(mid.slice(0, half).map(z => z.x)), upp = mean(mid.slice(half).map(z => z.x));
  log('  ' + ty + '：季度数 ' + pts.length + '｜相关系数 ' + f2(corr) +
    '｜市场差那半段 ' + pp(down) + '（市场 ' + pp(dn) + '）｜市场好那半段 ' + pp(up) + '（市场 ' + pp(upp) + '）');
}

/* ---------- 表 4：alpha 与成本 ---------- */
log('');
log('=== 表 4 超额规模 vs 成本 ===');
const a1 = recs.filter(z => z.ty === 'L1').map(z => z.ex);
const perYear = X === 20 ? 12.5 : 250 / X;
log('  一买 20 日超额 ' + pp(mean(a1)) + '（t=' + f2(tStat(a1)) + '）→ 满仓滚动折算年化约 ' +
  pp(mean(a1) * perYear) + '；双边费已扣 0.1%，若滑点再加 0.2% 则年化剩 ' +
  pp((mean(a1) - 0.002) * perYear));

fs.writeFileSync(path.join(__dirname, 'out', 'bt_decay' + TAG + '.txt'), out.join('\n') + '\n');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_decay' + TAG + '.json'),
  JSON.stringify({ pool: STOCKS ? 'stock' : 'etf', x: X, n: recs.length, yr: yrStat, quarters }, null, 1));
console.log('\n→ out/bt_decay' + TAG + '.txt');
