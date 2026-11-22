/* ==========================================================================
 * bt_vol.js —— 成交量扩展回测（纯新增，不改任何现有文件）
 *
 * 目的：现有引擎完全不用成交量（lib.parseCsv 连量列都不解析）。
 *       本脚本在「信号已成立」的前提下，测三件事：
 *         1) 信号日的量能状态能不能区分好坏信号（分档）
 *         2) 加一条量能硬条件后，剩下那批是不是更好（过滤）
 *         3) 被砍掉那批是不是真的更差（反证）
 *
 * 口径与 bt_hold 完全一致：
 *   入场 = discT + 1 开盘；持有 x 天；扣双边费 0.1%
 *   超额 ex4 = 单笔 − 同标的/同季度/同价位分位±0.15 的对照日均值（≥8 个样本）
 *   只接受 lag = discT − readyK === 1
 *
 * 量能特征全部在 discT 收盘时可得，无未来数据：
 *   vr20   当日量 / 前 20 日均量（不含当日）        → 放量倍数
 *   vt5_60 近 5 日均量 / 近 60 日均量               → 短期量能趋势（<1 缩量）
 *   vlevel 20 日均量 / 过去 250 日 20 日均量中位数   → 量能相对水平（<1 低于常态）
 *
 * 用法：
 *   node bt_vol.js              # ETF 池
 *   STOCKS=1 node bt_vol.js     # 个股池
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const DIR = STOCKS ? L.DIR_S : L.DIR_D;
const MIN_DATE = STOCKS ? '2005-01-01' : '0000-00-00';

const FEE = 0.001;
const X = 20;
const PCT_WIN = 250;
const PCT_BAND4 = 0.15;
const B4_MIN = 8;

const packFile = path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json');
if (!fs.existsSync(packFile)) {
  console.error('缺 ' + packFile + '，先跑 ' + (STOCKS ? 'STOCKS=1 ' : '') + 'TF=daily node scan.js');
  process.exit(1);
}
const pack = JSON.parse(fs.readFileSync(packFile, 'utf8'));

/* ---------------------------------------------------------------- 工具 */
const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
function sd(a) {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}
const tStat = a => {
  if (a.length < 3) return null;
  const s = sd(a);
  return s ? mean(a) / (s / Math.sqrt(a.length)) : null;
};
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : (x > 0 ? '+' : '\u2212') + (100 * Math.abs(x)).toFixed(2) + 'pp';
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const pct = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(1) + '%';

/* ------------------------------------------------- 带量的 K 线加载器 */
/* lib.parseCsv 不解析成交量列，这里单独读第 6 列（成交量） */
function loadVol(code) {
  const file = path.join(DIR, code + '.csv');
  if (!fs.existsSync(file)) return null;
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  const iV = ix('成交量');
  if (ix('日期') < 0 || ix('收盘') < 0 || iV < 0) return null;
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const raw = String(c[ix('日期')] || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}/.test(raw)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')], h = +c[ix('最高')], l = +c[ix('最低')], v = +c[iV];
    rows.push({ date: raw.slice(0, 10), t: raw, o, c: cl, h, l, v, bad: !(o > 0 && cl > 0 && h > 0 && l > 0) || h < l });
  }
  rows.sort((x, y) => (x.t < y.t ? -1 : x.t > y.t ? 1 : 0));
  const out = [];
  for (const r of rows) if (!out.length || out[out.length - 1].t !== r.t) out.push(r);
  return MIN_DATE === '0000-00-00' ? out : out.filter(k => k.date >= MIN_DATE);
}

/* vma[i] = 近 20 日（含当日）均量 */
function volMAs(v, win) {
  const n = v.length, out = new Array(n).fill(null);
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += v[i];
    if (i >= win) sum -= v[i - win];
    if (i >= win - 1) out[i] = sum / win;
  }
  return out;
}

/* 三个量能特征，全部只用 [0..t] */
function volFeat(ks, vma20, t) {
  if (t < 260) return null;
  const v = ks.map(k => k.v);
  let base = 0, cnt = 0;
  for (let i = t - 20; i < t; i++) { base += v[i]; cnt++; }
  const base20 = base / cnt;
  if (!(base20 > 0)) return null;

  let s5 = 0; for (let i = t - 4; i <= t; i++) s5 += v[i];
  let s60 = 0; for (let i = t - 59; i <= t; i++) s60 += v[i];

  const cur = vma20[t];
  if (cur == null) return null;
  /* 量能相对水平：20 日均量 / 过去 250 日 20 日均量的中位数。
   * 不用分位数：A 股成交量长期增长，分位数常年贴近 1，切点会挤在 0.98/0.99 失去区分度。 */
  const win = [];
  for (let i = Math.max(0, t - 249); i <= t; i++) if (vma20[i] != null) win.push(vma20[i]);
  if (win.length < 120) return null;
  win.sort((a, b) => a - b);
  const med = win[win.length >> 1];
  return {
    vr20: v[t] / base20,
    vt5_60: s60 > 0 ? s5 / s60 * 12 : null,     // 5 日总量 / 60 日总量，×12 归一到 1 附近
    vlevel: med > 0 ? cur / med : null
  };
}

/* --------------------------------------------- 信号 + 超额（同 bt_hold） */
const rows = [];
let lagDrop = 0, noRoom = 0, noVol = 0, dropLimit = 0, dropHalt = 0;

for (const p of pack.packs) {
  const ks = loadVol(p.code);
  if (!ks) { noVol++; continue; }
  if (ks.length !== p.c.length) {
    /* 长度不一致说明切片口径不同，宁可跳过也不硬对 */
    noVol++;
    continue;
  }
  const n = ks.length, o = p.o, c = p.c;
  const vma20 = volMAs(ks.map(k => k.v), 20);

  /* 价格分位 */
  const pq = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) { if (c[j] < lo) lo = c[j]; if (c[j] > hi) hi = c[j]; }
    pq[i] = hi > lo ? (c[i] - lo) / (hi - lo) : null;
  }

  const months = p.dates.map(d => d.slice(0, 7));
  const quarters = months.map(m => m.slice(0, 4) + 'Q' + (Math.floor((+m.slice(5, 7) - 1) / 3) + 1));

  /* 每个可入场日的 x 日收益，按季度索引（供 B4） */
  const byQ = {};
  for (let t = p.warmup; t + X <= n - 1; t++) {
    if (p.bad[t]) continue;
    const q = quarters[t];
    (byQ[q] = byQ[q] || []).push({ r: o[t + X] / o[t] - 1 - FEE, pc: pq[t] });
  }

  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1) { lagDrop++; continue; }
    const e = b.discT + 1;
    if (e + X > n - 1) { noRoom++; continue; }
    if (p.bad[e]) continue;

    /* 个股：一字涨停 / 停牌复牌日买不进（与 bt_hold 一致） */
    if (STOCKS) {
      if (p.h[e] === p.l[e] && p.o[e] > p.c[e - 1] * 1.045) { dropLimit++; continue; }
      if ((Date.parse(p.dates[e]) - Date.parse(p.dates[e - 1])) / 86400000 > 15) { dropHalt++; continue; }
    }

    const ps = pq[e];
    if (ps == null) continue;
    const pool = (byQ[quarters[e]] || []).filter(z => z.pc != null && Math.abs(z.pc - ps) <= PCT_BAND4);
    if (pool.length < B4_MIN) continue;
    const B4 = mean(pool.map(z => z.r));

    /* 量能特征在 discT（信号确认日）收盘时点，入场是次日，无未来 */
    const vf = volFeat(ks, vma20, b.discT);
    if (!vf || vf.vt5_60 == null || vf.vlevel == null) continue;

    const r = o[e + X] / o[e] - 1 - FEE;
    rows.push({
      code: p.code, date: p.dates[e], ty: 'L' + b.level,
      r, ex4: r - B4,
      vr20: vf.vr20, vt5_60: vf.vt5_60, vlevel: vf.vlevel,
      dist: b.zsZG > 0 ? o[e] / b.zsZG - 1 : null
    });
  }
}

if (!rows.length) { console.error('无有效样本'); process.exit(1); }

/* ---------------------------------------------------------------- 统计 */
const FEATS = [
  { k: 'vr20', lab: '当日量/20日均量', note: '>1 放量' },
  { k: 'vt5_60', lab: '5日均量/60日均量', note: '<1 缩量' },
  { k: 'vlevel', lab: '20日均量/250日中位', note: '<1 量能低于常态' }
];
const TYS = [['L1', '一买'], ['L2', '二买'], ['L3', '三买'], ['ALL', '全部']];
const lines = [];
const say = m => { lines.push(m); console.log(m); };

function group(ty) { return ty === 'ALL' ? rows : rows.filter(z => z.ty === ty); }

/* 三分位切点（全样本，样本内描述用） */
function cuts3(arr, key) {
  const v = arr.map(z => z[key]).filter(x => x != null && isFinite(x)).sort((a, b) => a - b);
  if (v.length < 30) return null;
  const q = p => v[Math.floor((v.length - 1) * p)];
  return [q(1 / 3), q(2 / 3)];
}
function bucketOf(x, cuts) {
  if (x == null || !isFinite(x) || !cuts) return -1;
  return x <= cuts[0] ? 0 : (x <= cuts[1] ? 1 : 2);
}

say('=== 成交量在缠论信号里的作用（' + (STOCKS ? '个股' : 'ETF') + ' · 日线 · 持 ' + X + ' 天）===');
say('样本：' + pack.packs.length + ' 只，有效信号 ' + rows.length + ' 笔' +
  '（lag>1 剔除 ' + lagDrop + '，剩余天数不足 ' + noRoom + '，无量数据 ' + noVol + ' 只' +
  (STOCKS ? '，一字涨停 ' + dropLimit + '，停牌 ' + dropHalt : '') + '）');
say('超额口径：单笔 − 同标的/同季度/同价位分位±0.15 的对照均（≥' + B4_MIN + ' 个样本）；已扣双边费 0.1%');
say('量能特征全部取信号确认日（discT）收盘，入场在次日开盘，无未来数据');
say('');

/* ---------------- 表 1：分档 ---------------- */
say('【表 1】按量能分三档看超额（档内均值，* = t>2）');
for (const [ty, lab] of TYS) {
  const g = group(ty);
  if (g.length < 60) continue;
  const base = mean(g.map(z => z.ex4));
  say('');
  say(lab + '（基准 ' + g.length + ' 笔，超额 ' + pp(base) + '）');
  for (const f of FEATS) {
    const cuts = cuts3(g, f.k);
    if (!cuts) continue;
    const bk = [[], [], []];
    for (const z of g) { const i = bucketOf(z[f.k], cuts); if (i >= 0) bk[i].push(z.ex4); }
    const cell = a => {
      if (a.length < 20) return ' ' + '样本少'.padEnd(17);
      const t = tStat(a);
      return (pp(mean(a)) + '(' + a.length + ')' + (Math.abs(t) > 2 ? '*' : '')).padEnd(18);
    };
    say('  ' + f.lab.padEnd(22) + cell(bk[0]) + cell(bk[1]) + cell(bk[2]));
    say('  ' + ''.padEnd(22) + ('≤' + f2(cuts[0])).padEnd(18) + ('≤' + f2(cuts[1])).padEnd(18) + '>' + f2(cuts[1]));
  }
}

/* ---------------- 表 2：过滤规则 ---------------- */
/* 一买要缩量（vt5_60 低）、三买要放量（vr20 高）——方向按缠论位置语义设定，先验固定，不做事后择优 */
const RULES = [
  { ty: 'L1', lab: '一买 · 非缩量(当日 ≥0.8×)', f: z => z.vr20 >= 0.8 },
  { ty: 'L1', lab: '一买 · 非缩量(当日 ≥1.0×)', f: z => z.vr20 >= 1.0 },
  { ty: 'L1', lab: '一买 · 地量(相对量能 ≤0.9)', f: z => z.vlevel <= 0.9 },
  { ty: 'L1', lab: '一买 · 当日放量(≥1.5×)', f: z => z.vr20 >= 1.5 },
  { ty: 'L1', lab: '一买 · 量能高于常态(≥1.1)', f: z => z.vlevel >= 1.1 },
  { ty: 'L3', lab: '三买 · 非缩量(当日 ≥0.8×)', f: z => z.vr20 >= 0.8 },
  { ty: 'L3', lab: '三买 · 放量(当日 ≥ 1.2×)', f: z => z.vr20 >= 1.2 },
  { ty: 'L3', lab: '三买 · 放量(当日 ≥ 1.5×)', f: z => z.vr20 >= 1.5 },
  { ty: 'L3', lab: '三买 · 地量(≤0.9) 反向对照', f: z => z.vlevel <= 0.9 },
  { ty: 'ALL', lab: '统一：非缩量 ≥0.8×', f: z => z.vr20 >= 0.8 },
  { ty: 'ALL', lab: '统一：当日放量 ≥1.2×', f: z => z.vr20 >= 1.2 },
  { ty: 'ALL', lab: '统一：当日缩量 ≤0.8× 反向', f: z => z.vr20 <= 0.8 }
];

say('');
say('【表 2】加一条量能条件后：留下的 vs 砍掉的');
say('规则'.padEnd(30) + '保留n  留存   保留超额(t)      砍掉超额(t)     差值');
const ruleRows = [];
for (const ru of RULES) {
  const g = group(ru.ty);
  if (g.length < 100) continue;
  const keep = g.filter(ru.f), drop = g.filter(z => !ru.f(z));
  if (keep.length < 40 || drop.length < 40) continue;
  const ek = keep.map(z => z.ex4), ed = drop.map(z => z.ex4);
  const tk = tStat(ek), td = tStat(ed);
  const diff = mean(ek) - mean(ed);
  ruleRows.push({ rule: ru.lab, ty: ru.ty, keepN: keep.length, share: keep.length / g.length, keepEx: mean(ek), tk, dropEx: mean(ed), td, diff });
  say(ru.lab.padEnd(30) +
    String(keep.length).padStart(5) + '  ' + pct(keep.length / g.length).padStart(6) + '  ' +
    (pp(mean(ek)) + '(' + f2(tk) + ')').padStart(14) + '  ' +
    (pp(mean(ed)) + '(' + f2(td) + ')').padStart(14) + '  ' +
    pp(diff).padStart(9));
}
say('（读法：「差值」>0 说明这条量能条件确实把差的信号分出去了；接近 0 说明量能在这个位置没信息）');

/* ---------------- 表 3：时间稳定性 ---------------- */
say('');
say('【表 3】前后两段是否同向（防样本内巧合）');
const mid = '2019-01-01';
for (const ru of RULES) {
  const g = group(ru.ty);
  if (g.length < 200) continue;
  const A = g.filter(z => z.date < mid), B = g.filter(z => z.date >= mid);
  if (A.length < 80 || B.length < 80) continue;
  const dA = mean(A.filter(ru.f).map(z => z.ex4)) - mean(A.filter(z => !ru.f(z)).map(z => z.ex4));
  const dB = mean(B.filter(ru.f).map(z => z.ex4)) - mean(B.filter(z => !ru.f(z)).map(z => z.ex4));
  const ok = (dA > 0) === (dB > 0);
  say('  ' + ru.lab.padEnd(30) + '前段 ' + pp(dA).padStart(9) + '   后段 ' + pp(dB).padStart(9) +
    '   ' + (ok ? '同向' : '反向（不可信）'));
}


/* ---------------------------------------------------------------- 落盘 */
const outDir = path.join(__dirname, 'out');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'bt_vol' + TAG + '.txt'), lines.join('\n'));
fs.writeFileSync(path.join(outDir, 'bt_vol' + TAG + '.json'), JSON.stringify({
  pool: STOCKS ? 'stock' : 'etf', x: X, n: rows.length, fee: FEE,
  rows: rows.map(z => ({ code: z.code, date: z.date, ty: z.ty, r: z.r, ex4: z.ex4, vr20: z.vr20, vt5_60: z.vt5_60, vlevel: z.vlevel })),
  rules: ruleRows
}, null, 0));
console.log('\n产物：out/bt_vol' + TAG + '.txt / .json');
