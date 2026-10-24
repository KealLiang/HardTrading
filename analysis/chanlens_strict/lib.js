/* ==========================================================================
 * lib.js —— chanlens_strict 公共库
 * 数据加载（日线 / 30m / 30m合成60m）、统计、ATR、随机数
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const DIR_D = 'D:/Trading/data/etfs';
const DIR_30 = 'D:/Trading/data/etfs_bt_30m';           // 30m 原始（不复权）
const DIR_30_ADJ = 'D:/Trading/data/etfs_bt_30m_adj';   // 30m 前复权（对齐日线）
const DIR_60 = 'D:/Trading/data/etfs_bt_60m_adj';   // 真实 60m（新浪源，前复权对齐日线）
const DIR_60_RAW = 'D:/Trading/data/etfs_bt_60m';   // 真实 60m（原始不复权，仅排查用）

/* ---------------------------------------------------------------- 随机 */
function makeRng(seed) {
  let s = (seed >>> 0) || 1;
  return function () {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;  s >>>= 0;
    return s / 4294967296;
  };
}
function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

/* ---------------------------------------------------------------- 统计 */
const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
function sd(a) {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}
function median(a) {
  if (!a.length) return null;
  const s = a.slice().sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function quantile(a, q) {
  if (!a.length) return null;
  const s = a.slice().sort((x, y) => x - y);
  const pos = (s.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (pos - lo);
}
function welchT(a, b) {
  if (!a || !b || a.length < 2 || b.length < 2) return null;
  const va = sd(a) ** 2, vb = sd(b) ** 2;
  const se = Math.sqrt(va / a.length + vb / b.length);
  return se ? (mean(a) - mean(b)) / se : null;
}
const compact = a => a.filter(x => x != null && isFinite(x));

/* ---------------------------------------------------------------- 数据 */
function parseCsv(file, dateCol) {
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  for (const col of [dateCol, '开盘', '收盘', '最高', '最低'])
    if (ix(col) < 0) throw new Error('表头缺列 ' + col + ' → ' + file);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const raw = String(c[ix(dateCol)] || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}/.test(raw)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')], h = +c[ix('最高')], l = +c[ix('最低')];
    const bad = !(o > 0 && cl > 0 && h > 0 && l > 0) || h < l;
    rows.push({ date: raw.slice(0, 10), t: raw, o, c: cl, h, l, bad });
  }
  rows.sort((x, y) => (x.t < y.t ? -1 : x.t > y.t ? 1 : 0));
  const out = [];
  for (const r of rows) if (!out.length || out[out.length - 1].t !== r.t) out.push(r);
  return out;
}
const loadDaily = code => parseCsv(path.join(DIR_D, code + '.csv'), '日期');
/** 30m：默认优先前复权版（与日线同口径）；RAW_MIN=1 时用原始不复权版 */
const load30 = code => {
  const p = process.env.RAW_MIN === '1' ? path.join(DIR_30, code + '.csv') : path.join(DIR_30_ADJ, code + '.csv');
  const q = fs.existsSync(p) ? p : path.join(DIR_30, code + '.csv');
  return parseCsv(q, '时间');
};
/** 真实 60m（新浪源，已前复权对齐日线）；无文件时返回 null */
const load60 = code => {
  const p = path.join(DIR_60, code + '.csv');
  return fs.existsSync(p) ? parseCsv(p, '时间') : null;
};

/** 30m → 60m：日内相邻两根合并，跨日不合并（边界 bar 原样保留） */
function to60(ks30) {
  const out = [];
  let i = 0;
  while (i < ks30.length) {
    const a = ks30[i];
    const b = i + 1 < ks30.length && ks30[i + 1].date === a.date ? ks30[i + 1] : null;
    if (!b) { out.push({ ...a }); i++; continue; }
    out.push({
      date: a.date, t: a.t, o: a.o, c: b.c,
      h: Math.max(a.h, b.h), l: Math.min(a.l, b.l),
      bad: a.bad || b.bad
    });
    i += 2;
  }
  return out;
}

function listCodes() {
  return fs.readdirSync(DIR_D).filter(f => f.endsWith('.csv')).map(f => f.replace('.csv', '')).sort();
}

/** ATR(period)，返回与 ks 等长数组（前 period 根为 null） */
function atrSeries(ks, period) {
  period = period || 14;
  const tr = new Array(ks.length).fill(null);
  for (let i = 1; i < ks.length; i++) {
    if (ks[i].bad || ks[i - 1].bad) continue;
    tr[i] = Math.max(ks[i].h - ks[i].l, Math.abs(ks[i].h - ks[i - 1].c), Math.abs(ks[i].l - ks[i - 1].c));
  }
  const out = new Array(ks.length).fill(null);
  let sum = 0, cnt = 0;
  for (let i = 1; i < ks.length; i++) {
    if (tr[i] == null) continue;
    sum += tr[i]; cnt++;
    if (cnt > period) { sum -= tr[i - period]; cnt = period; }
    if (cnt === period) out[i] = sum / period;
  }
  return out;
}

/* ---------------------------------------------------------------- 格式化 */
const pc = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : (x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp';
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const f1 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(1);

module.exports = {
  makeRng, hashSeed, mean, sd, median, quantile, welchT, compact,
  loadDaily, load30, load60, to60, listCodes, atrSeries,
  pc, pp, f2, f1, DIR_D, DIR_30, DIR_30_ADJ, DIR_60, DIR_60_RAW
};
