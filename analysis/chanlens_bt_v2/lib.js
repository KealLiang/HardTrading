/* ==========================================================================
 * lib.js —— 回测框架公共库
 *
 * 设计原则（针对此前三轮的错误）：
 *   1. 脏数据在加载期就标记，不在收益计算期临时过滤（避免漏改某处）
 *   2. 统计量全部基于「两组均值差」，不做「收益≠0」的检验
 *   3. 所有随机过程使用固定种子，完全可复现
 * ========================================================================== */
'use strict';
const fs = require('fs');

/* ------------------------------------------------------------------ 随机 */
function makeRng(seed) {
  let s = (seed >>> 0) || 1;
  return function () {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;  s >>>= 0;
    return s / 4294967296;
  };
}

/* ------------------------------------------------------------------ 统计 */
const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
function sd(a) {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}
/* Welch t 检验：检验「两组均值是否有差异」，不假设等方差 */
function welchT(a, b) {
  if (!a || !b || a.length < 2 || b.length < 2) return null;
  const va = sd(a) ** 2, vb = sd(b) ** 2;
  const se = Math.sqrt(va / a.length + vb / b.length);
  if (!se) return null;
  return (mean(a) - mean(b)) / se;
}
/* 差值的 95% 置信区间（正态近似） */
function ci95(a, b) {
  if (!a || !b || a.length < 2 || b.length < 2) return null;
  const d = mean(a) - mean(b);
  const se = Math.sqrt(sd(a) ** 2 / a.length + sd(b) ** 2 / b.length);
  const z = 1.96 * se;
  return { d: d, lo: d - z, hi: d + z, se: se };
}
function stat(a) {
  if (!a || !a.length) return { n: 0 };
  const m = mean(a), s = sd(a);
  return { n: a.length, exp: m, sd: s, t: s ? m / (s / Math.sqrt(a.length)) : null };
}
/* 把带 null 的数组压紧 */
const compact = a => a.filter(x => x != null && isFinite(x));

/* ------------------------------------------------------------ 数据加载器 */
/**
 * ETF CSV 加载。返回 { code, ks, badCount }。
 * ks[i] = { t, o, c, h, l, v, bad }
 *   bad=true 表示该根 K 线不可用于入场（open<=0 或非有限），
 *   典型来源：停牌日 open=0（科创板/部分ETF），作分母会产生 Infinity。
 *   注意：标记而非删除，保持索引与原始 K 线一一对应。
 */
function loadETF(file) {
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  for (const col of ['日期', '开盘', '收盘', '最高', '最低']) {
    if (ix(col) < 0) throw new Error('表头缺列 ' + col + ' → ' + head.join('|'));
  }
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const d = String(c[ix('日期')] || '').trim().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')];
    const h = +c[ix('最高')], l = +c[ix('最低')];
    const v = +c[ix('成交量')] || 0;
    // 价格必须为有限正数才进序列；否则整根标记为 bad（保留索引）
    const bad = !(o > 0 && isFinite(o)) || !(cl > 0 && isFinite(cl)) ||
                !(h > 0 && isFinite(h)) || !(l > 0 && isFinite(l)) ||
                h < l;
    rows.push({ t: d, o: o, c: cl, h: h, l: l, v: v, bad: bad });
  }
  rows.sort((x, y) => (x.t < y.t ? -1 : x.t > y.t ? 1 : 0));
  const out = [];
  for (const r of rows) if (!out.length || out[out.length - 1].t !== r.t) out.push(r);
  return { ks: out, badCount: out.filter(r => r.bad).length };
}

/* 收益计算：所有收益都必须走这里，保证口径统一 + 脏数据防护 */
function retAt(ks, entryIdx, holdDays, fee) {
  if (entryIdx < 0 || entryIdx >= ks.length) return null;
  const e = ks[entryIdx];
  if (e.bad || !(e.o > 0)) return null;
  const j = entryIdx + holdDays;
  if (j >= ks.length) return null;
  const x = ks[j];
  if (x.bad || !(x.c > 0)) return null;
  const r = x.c / e.o - 1 - fee;
  return isFinite(r) ? r : null;
}

/* --------------------------------------------------------------- 格式化 */
const pc = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : ((x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp');
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);

module.exports = {
  makeRng, mean, sd, welchT, ci95, stat, compact,
  loadETF, retAt, pc, pp, f2
};