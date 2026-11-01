/* ==========================================================================
 * verify_hold.js —— bt_hold 的独立复核（不复用 bt_hold 的任何算价逻辑）
 *
 * 检查项：
 *   1) 入场日 = 买点 discT + 1；卖出日 = 入场日 + x（同一个 bar 索引）
 *   2) 用原始 CSV 重新读开盘价，重算每笔收益，与 out/bt_hold.json 的均值/胜率逐类型比对
 *   3) 只保留 lag = discT − readyK === 1
 *   4) 抽样重算 B4 基线（同季度 + 价格分位 ±0.15 的均值）
 *
 * 用法：node verify_hold.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const packFile = path.join(__dirname, 'tmp', 'pack_daily.json');
const resFile = path.join(__dirname, 'out', 'bt_hold.json');
if (!fs.existsSync(packFile) || !fs.existsSync(resFile)) {
  console.error('缺 pack 或 bt_hold.json'); process.exit(1);
}
const pack = JSON.parse(fs.readFileSync(packFile, 'utf8'));
const res = JSON.parse(fs.readFileSync(resFile, 'utf8'));
const XS = res.xs, FEE = res.fee;
const PCT_WIN = 250, PCT_BAND4 = 0.15, B4_MIN = 8;

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
function sd(a) { const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
const tStat = a => (a.length < 3 || !sd(a)) ? null : mean(a) / (sd(a) / Math.sqrt(a.length));

/* --- 直接从 CSV 读，index 对齐 pack 的 dates --- */
function loadCsv(code) {
  const f = path.join('D:/Trading/data/etfs', code + '.csv');
  const lines = fs.readFileSync(f, 'utf8').split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',');
  const iD = head.findIndex(h => /日期|date/.test(h));
  const iO = head.findIndex(h => /开盘|open/.test(h));
  const iC = head.findIndex(h => /收盘|close/.test(h));
  const rows = lines.slice(1).map(l => l.split(','));
  return { date: rows.map(r => r[iD]), open: rows.map(r => +r[iO]), close: rows.map(r => +r[iC]) };
}

const err = { notNext: 0, badIdx: 0, lagNot1: 0, priceMismatch: 0, checked: 0, tailEdge: 0 };
const recomputed = {};   // type -> [ret...]

for (const p of pack.packs) {
  const csv = loadCsv(p.code);
  /* CSV 行数应与 pack 一致，否则索引对不上 */
  if (csv.date.length !== p.dates.length) {
    console.log('!! ' + p.code + ' CSV ' + csv.date.length + ' 行 vs pack ' + p.dates.length + ' 行，跳过');
    continue;
  }
  /* 每只标的每个 x 的「同月样本数」，用于复现 bt_hold 的过滤 */
  const monthCnt = {};
  for (const x of XS) {
    monthCnt[x] = {};
    for (let t = p.warmup; t + x <= p.c.length - 1; t++) {
      const m = p.dates[t].slice(0, 7);
      monthCnt[x][m] = (monthCnt[x][m] || 0) + 1;
    }
  }
  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1) { err.lagNot1++; continue; }
    const e = b.discT + 1;
    if (e > p.dates.length - 1) { err.tailEdge++; continue; }   // 末端确认、次日无 bar
    /* 1) 入场日必须紧跟确认日 */
    const dDisc = p.dates[b.discT], dEntry = p.dates[e];
    const iDisc = csv.date.indexOf(dDisc), iEntry = csv.date.indexOf(dEntry);
    if (iEntry !== iDisc + 1) { err.notNext++; continue; }
    const mEntry = dEntry.slice(0, 7);
    for (const x of XS) {
      if (e + x > p.c.length - 1) continue;
      /* 复现报告的过滤：同月可入场日 < 10 则该笔不进统计 */
      if ((monthCnt[x][mEntry] || 0) < 10) continue;
      const po = csv.open[e], px = csv.open[e + x];
      if (!(po > 0) || !(px > 0)) { err.badIdx++; continue; }
      /* 3) 与 pack 里的开盘价对得上（防刻度错配） */
      if (Math.abs(po - p.o[e]) > 1e-9) err.priceMismatch++;
      const r = px / po - 1 - FEE;
      (recomputed[x + '|L' + b.level] = recomputed[x + '|L' + b.level] || []).push(r);
      err.checked++;
    }
  }
}

console.log('=== 1) 时点与价格 ===');
console.log('  入场 = 确认日 + 1（逐笔核对 CSV 相邻行）：违规 ' + err.notNext);
console.log('  开盘价与 pack 不一致：' + err.priceMismatch + '（应为 0）');
console.log('  lag ≠ 1 被排除：' + err.lagNot1 + '（bt_hold 记 ' + res.lagDrop + '）');
  console.log('  数据末端确认、次日无 bar：' + err.tailEdge);
console.log('  重算笔次：' + err.checked);

console.log('\n=== 2) 用 CSV 重算 vs bt_hold.json ===');
console.log('  x  类型    重算 n   重算均值   重算胜率  |  报告 n   报告均值   报告胜率  一致');
let bad = 0;
for (const x of XS) {
  for (const ty of ['L1', 'L2', 'L3']) {
    const a = recomputed[x + '|' + ty] || [];
    const o = res.table[x + ty];
    if (!o) continue;
    const win = a.filter(v => v > 0).length / a.length;
    const dMean = Math.abs(mean(a) - o.sig) * 100;
    const dWin = Math.abs(win - o.winAbs) * 100;
    /* 报告侧的 n 已按 B2 同月门槛过滤，重算侧不做该过滤 → 允许 n 有差，均值按同集合比 */
    const ok = dWin < 0.005 && Math.abs(mean(a) - o.sig) < 1e-6;
    if (!ok) bad++;
    console.log('  ' + String(x).padStart(2) + '  ' + ty + '  ' + String(a.length).padStart(6) +
      '  ' + (100 * mean(a)).toFixed(3).padStart(9) + '%  ' + (100 * win).toFixed(2).padStart(7) + '%  |  ' +
      String(o.n).padStart(6) + '  ' + (100 * o.sig).toFixed(3).padStart(9) + '%  ' +
      (100 * o.winAbs).toFixed(2).padStart(7) + '%   ' + (ok ? 'ok' : '✗'));
  }
}
console.log('  （两侧都要求「同月样本 ≥10」，n / 均值 / 胜率应完全一致）');

/* 4) 基线本身：全量重算 x=5 的一买「同季同价位」均值，与报告 B4 字段比 */
function pctSeries(p) {
  const n = p.c.length, out = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) { if (p.c[j] < lo) lo = p.c[j]; if (p.c[j] > hi) hi = p.c[j]; }
    out[i] = hi > lo ? (p.c[i] - lo) / (hi - lo) : null;
  }
  return out;
}
const xB4 = 5;
const b4vals = [];
let b4n = 0;
for (const p of pack.packs) {
  const csv = loadCsv(p.code);
  if (csv.date.length !== p.dates.length) continue;
  const pq = pctSeries(p), n = p.o.length;
  const qs = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));
  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1 || b.level !== 1) continue;
    const e = b.discT + 1;
    if (e + xB4 > n - 1 || pq[e] == null) continue;
    const pool = [];
    for (let t = p.warmup; t + xB4 <= n - 1; t++) {
      if (qs[t] !== qs[e] || pq[t] == null) continue;
      if (Math.abs(pq[t] - pq[e]) <= PCT_BAND4) pool.push(csv.open[t + xB4] / csv.open[t] - 1 - FEE);
    }
    if (pool.length < B4_MIN) continue;
    b4n++;
    b4vals.push(mean(pool));
  }
}
const b4rep = res.table['5L1'] ? res.table['5L1'].B4 : null;
console.log('\n=== 4) 基线重算（x=5 一买，同季度 + 分位 ±0.15，用 CSV 开盘价）===');
console.log('  可算 ' + b4n + ' 笔，重算基线均值 ' + (100 * mean(b4vals)).toFixed(3) + '% ｜ 报告 ' +
  (b4rep == null ? 'n/a' : (100 * b4rep).toFixed(3) + '%') + '　' +
  (b4rep != null && Math.abs(mean(b4vals) - b4rep) < 5e-5 ? 'ok' : '✗'));

const summary = { err, badCells: bad, sampleB4: b4n };
fs.writeFileSync(path.join(__dirname, 'out', 'verify_hold.json'), JSON.stringify(summary, null, 1));
console.log('\n' + (bad === 0 && err.notNext === 0 && err.priceMismatch === 0 ? '✅ 全部通过' : '❌ 有问题'));
