#!/usr/bin/env node
/* ============================================================
 * verify_vol_rev.js — 反向验证「极端缩量的一买更差」这个结论
 *
 * 五项检验（如果结论是真的，五项都应通过）：
 *   1. 反向完整统计：地量组 vs 其余组 的期望/胜率/盈亏比/t/p
 *   2. 分时间段：每个子区间方向是否一致
 *   3. 逐票符号检验：43 只票里多少只地量更差（防单票拉动均值）
 *   4. 阈值扫描：0.45~0.90 是否连续，还是只有一个点成立
 *   5. 剔除贡献票：删掉最极端的一只票后是否还成立
 *
 * 用法：node verify_vol_rev.js
 * 输入：out/bt_vol_stock.json、out/bt_vol.json
 * ============================================================ */
'use strict';

const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'out');
const Q = 0.65;          // 地量阈值
const QMAP = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90];

const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const sd = a => {
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1));
};
const tstat = a => (a.length > 2 ? mean(a) / (sd(a) / Math.sqrt(a.length)) : null);
const P = x => (x == null || Number.isNaN(x)) ? '\u2014' : (x > 0 ? '+' : '\u2212') + (100 * Math.abs(x)).toFixed(2) + 'pp';
const F = (x, n = 2) => (x == null || Number.isNaN(x) ? '\u2014' : x.toFixed(n));

function st(arr) {
  const r = arr.map(z => z.ex4);
  if (!r.length) return null;
  const win = r.filter(x => x > 0), los = r.filter(x => x <= 0);
  return {
    n: r.length, mean: mean(r), t: tstat(r),
    wr: win.length / r.length,
    aw: win.length ? mean(win) : null,
    al: los.length ? mean(los) : null,
    pl: win.length && los.length ? mean(win) / Math.abs(mean(los)) : null
  };
}

/* 二项检验（符号检验），双尾 */
function binomTwoSided(k, n) {
  if (!n) return null;
  const C = (a, b) => {
    let r = 1;
    for (let i = 0; i < b; i++) r = r * (a - i) / (i + 1);
    return r;
  };
  let tail = 0;
  for (let i = 0; i <= Math.min(k, n - k); i++) tail += C(n, i);
  return Math.min(1, 2 * tail / Math.pow(2, n));
}

/* 固定种子置换检验：随机抽同样笔数，p = 随机差值 <= 观测差值的比例
   （这里是单向「更差」，所以用 <=） */
let seed = 20261122;
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x80000000; };
function permLow(vals, k, obs, B = 5000) {
  const n = vals.length;
  if (k < 20 || n - k < 20) return null;
  const idx = [...Array(n).keys()];
  let hit = 0;
  for (let b = 0; b < B; b++) {
    for (let i = 0; i < k; i++) {
      const j = i + Math.floor(rnd() * (n - i));
      const t = idx[i]; idx[i] = idx[j]; idx[j] = t;
    }
    let s = 0, sr = 0;
    for (let i = 0; i < k; i++) s += vals[idx[i]];
    for (let i = k; i < n; i++) sr += vals[idx[i]];
    if (s / k - sr / (n - k) <= obs) hit++;
  }
  return hit / B;
}

let pass = 0, total = 0;
const check = (ok, msg) => { total++; if (ok) pass++; console.log('  ' + (ok ? '\u2713' : '\u2717') + ' ' + msg); };

for (const file of ['bt_vol_stock.json', 'bt_vol.json']) {
  const fp = path.join(OUT, file);
  if (!fs.existsSync(fp)) { console.error('缺少 ' + fp); process.exitCode = 1; continue; }
  const d = JSON.parse(fs.readFileSync(fp, 'utf8'));
  const L1 = d.rows.filter(z => z.ty === 'L1' && z.ex4 != null && z.vr20 != null);
  seed = 20261122;

  console.log('\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 ' + d.pool + ' 一买 n=' + L1.length + ' \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550');
  pass = 0; total = 0;

  /* ---- 1. 完整反向统计 ---- */
  const low = L1.filter(z => z.vr20 < Q);
  const rest = L1.filter(z => z.vr20 >= Q);
  const a = st(low), b = st(rest);
  const obsDiff = a.mean - b.mean;
  const p = permLow(L1.map(z => z.ex4), low.length, obsDiff);

  console.log('\n【1】完整反向统计（地量 <' + Q + ' vs 其余）');
  console.log('  组别        n     期望       t      胜率     均盈      均亏    盈亏比');
  const row = (lab, s) => console.log('  ' + lab.padEnd(10) + String(s.n).padStart(4) + '  ' +
    P(s.mean).padStart(9) + '  ' + F(s.t).padStart(6) + '  ' + (100 * s.wr).toFixed(1) + '%  ' +
    P(s.aw).padStart(8) + '  ' + P(s.al).padStart(8) + '  ' + F(s.pl));
  row('地量组', a); row('其余组', b);
  console.log('  差值 ' + P(obsDiff) + '   单向置换 p=' + F(p, 3) + '（B=5000）');
  console.log('  → 若结论成立：地量组期望显著低于其余组。');
  check(obsDiff < 0 && p != null && p < 0.05, '地量组显著更差');

  /* ---- 2. 分时间段 ---- */
  console.log('\n【2】分时间段（地量组 − 其余组的差值，应为负）');
  const SEGS = [['2000-01-01', '2010-01-01'], ['2010-01-01', '2015-01-01'],
    ['2015-01-01', '2019-01-01'], ['2019-01-01', '2023-01-01'], ['2023-01-01', '2030-01-01']];
  let negSeg = 0, validSeg = 0;
  for (const [s0, s1] of SEGS) {
    const L = L1.filter(z => z.date >= s0 && z.date < s1 && z.vr20 < Q);
    const R = L1.filter(z => z.date >= s0 && z.date < s1 && z.vr20 >= Q);
    if (L.length < 15 || R.length < 15) { console.log('  ' + s0.slice(0, 4) + '-' + s1.slice(0, 4) + '  样本不足 (' + L.length + '/' + R.length + ')'); continue; }
    const dm = mean(L.map(z => z.ex4)) - mean(R.map(z => z.ex4));
    validSeg++; if (dm < 0) negSeg++;
    console.log('  ' + s0.slice(0, 4) + '-' + s1.slice(0, 4) + '  地量 n=' + String(L.length).padStart(4) + ' 其余 n=' + String(R.length).padStart(4) +
      '  差值 ' + P(dm) + (dm < 0 ? '' : '  \u2190 反向'));
  }
  check(validSeg > 0 && negSeg === validSeg, '所有有效分段均为负（' + negSeg + '/' + validSeg + '）');

  /* ---- 3. 逐票符号检验 ---- */
  console.log('\n【3】逐票检验（每只票单独算地量 vs 其余，防单票拉均值）');
  const byCode = new Map();
  for (const z of L1) {
    if (!byCode.has(z.code)) byCode.set(z.code, []);
    byCode.get(z.code).push(z);
  }
  let worse = 0, better = 0, skipped = 0;
  const perCode = [];
  for (const [code, arr] of byCode) {
    const L = arr.filter(z => z.vr20 < Q), R = arr.filter(z => z.vr20 >= Q);
    if (L.length < 5 || R.length < 10) { skipped++; continue; }
    const dm = mean(L.map(z => z.ex4)) - mean(R.map(z => z.ex4));
    perCode.push({ code, dm, nl: L.length, nr: R.length });
    if (dm < 0) worse++; else better++;
  }
  perCode.sort((x, y) => x.dm - y.dm);
  const nValid = worse + better;
  const pb = binomTwoSided(worse, nValid);
  console.log('  有效票 ' + nValid + ' 只（样本不足剔除 ' + skipped + ' 只）：地量更差 ' + worse + ' 只，更好 ' + better + ' 只');
  console.log('  符号检验 p=' + F(pb, 3) + '（若结论成立，p 应显著）');
  console.log('  最差 3 只：' + perCode.slice(0, 3).map(x => x.code + ' ' + P(x.dm)).join(' | '));
  console.log('  最好 3 只：' + perCode.slice(-3).map(x => x.code + ' ' + P(x.dm)).join(' | '));
  check(pb != null && pb < 0.05, '多数票方向一致（' + worse + '/' + nValid + '）');

  /* ---- 4. 阈值扫描 ---- */
  console.log('\n【4】阈值扫描（不是挑出来的单点）');
  let negCnt = 0, validQ = 0;
  for (const q of QMAP) {
    const L = L1.filter(z => z.vr20 < q), R = L1.filter(z => z.vr20 >= q);
    if (L.length < 30 || R.length < 30) { console.log('  阈值 ' + q.toFixed(2) + '  样本不足'); continue; }
    const dm = mean(L.map(z => z.ex4)) - mean(R.map(z => z.ex4));
    validQ++; if (dm < 0) negCnt++;
    console.log('  阈值 ' + q.toFixed(2) + '  地量 n=' + String(L.length).padStart(4) + '  差值 ' + P(dm) + (dm < 0 ? '' : '  \u2190 反向'));
  }
  check(validQ > 0 && negCnt === validQ, '所有阈值的差值均为负（' + negCnt + '/' + validQ + '）');

  /* ---- 5. 剔除贡献票 ---- */
  console.log('\n【5】剔除贡献票（删掉对效应贡献最大的 3 只票，看是否还成立）');
  const codes = [...byCode.keys()];
  const contrib = codes.map(c => {
    const arr = byCode.get(c);
    const L = arr.filter(z => z.vr20 < Q);
    const share = L.length * (mean(L.map(z => z.ex4)) - mean(arr.filter(z => z.vr20 >= Q).map(z => z.ex4)) || 0);
    return { c, share: Number.isFinite(share) ? share : 0 };
  }).filter(x => x.share < 0).sort((x, y) => x.share - y.share).slice(0, 3).map(x => x.c);
  const remain = L1.filter(z => !contrib.includes(z.code));
  const L2 = remain.filter(z => z.vr20 < Q), R2 = remain.filter(z => z.vr20 >= Q);
  const dm2 = mean(L2.map(z => z.ex4)) - mean(R2.map(z => z.ex4));
  console.log('  剔除 ' + contrib.join(', '));
  console.log('  剩余 n=' + remain.length + '（地量 ' + L2.length + '）差值 ' + P(dm2));
  check(dm2 < 0, '剔除后仍为负');

  console.log('\n  小结：' + pass + '/' + total + ' 项通过');
  console.log('');
}

/* 附加：验证「1.3 这条线」是否真的没意义（Q4 vs Q5） */
console.log('\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 附加：量比 1.3 以上是否更好 \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550');
for (const file of ['bt_vol_stock.json', 'bt_vol.json']) {
  const fp = path.join(OUT, file);
  if (!fs.existsSync(fp)) continue;
  const d = JSON.parse(fs.readFileSync(fp, 'utf8'));
  const L1 = d.rows.filter(z => z.ty === 'L1' && z.ex4 != null && z.vr20 != null);
  const hi = L1.filter(z => z.vr20 >= 1.3), mid = L1.filter(z => z.vr20 >= 0.65 && z.vr20 < 1.3);
  if (hi.length < 30 || mid.length < 30) { console.log(d.pool + '  样本不足'); continue; }
  const dm = mean(hi.map(z => z.ex4)) - mean(mid.map(z => z.ex4));
  const s = st(hi);
  console.log(d.pool.padEnd(6) + ' 高量比(≥1.3) n=' + String(hi.length).padStart(4) + ' ' + P(s.mean) + ' t=' + F(s.t) +
    '   中量比 n=' + String(mid.length).padStart(4) + ' ' + P(mean(mid.map(z => z.ex4))) + '   差 ' + P(dm));
}
