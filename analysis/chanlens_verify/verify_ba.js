/* ==========================================================================
 * verify_ba.js — 方向判断 × 等待信号的交互效应（B−A）
 *
 * 问题：用户实际打法是「先看好方向，再等信号」。而 verify_forward 测的是
 *      「无条件等信号」。两者不是一回事：
 *        B−A > 0 → 即使方向已选对，信号仍让你买得更便宜，值得等
 *        B−A ≈ 0 → 方向判断吃掉全部优势，信号只是让你少买
 *
 * 做法（A/B/C 三臂共用同一条客观方向规则，出场规则完全一致）：
 *   先算一条可计算的「方向条件」：过去 20 日该标相对全样本中位数的强度排名，
 *   排名前 30% 视为「方向成立」。注意这只是让比较干净的可计算代理，
 *   不代表复现用户本人的判断力，B−A 的量级不能外推实盘。
 *   A 臂：方向成立 → 次日开盘进
 *   B 臂：方向成立 → 等三买信号，信号后次日开盘进（等不到就作废）
 *   C 臂：方向不成立 → 等三买信号（对照组，信号本身的效力）
 *   B−A 即「方向已定后信号的边际价值」
 *
 * 出场统一：固定 N 日（默认 10/20），同一天进同天数出，费后 0.1%。
 * 无未来函数：逐日切片，t 日 analyze 只用 t 及以前；执行用 t+1 开盘。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');
const CLScanner = require('D:/Trading/plugins/chanlens/core/scanner.js').CLScanner;

const CODES = (process.env.V_CODES ? process.env.V_CODES.split(',') : ['512880', '512800', '512480', '513260', '159995', '159857',
               '512980', '159819', '515880', '513050', '562500', '159869',
               '515700', '159928', '159992', '512660', '159825', '512200',
               '515220', '159949', '510300', '159353', '512890', '159207',
               '518880', '511010']);
const DAILY_DIR = 'D:/Trading/data/etfs';
const OUT_DIR = 'D:/Trading/analysis/chanlens_verify';
const WIN = 800;
const MAXLAG = 10;
const FEE = 0.001;
const HOLD = (process.env.V_HOLD || '10,20').split(',').map(Number);
const STRENGTH = 20;      // 方向条件的回看长度
const PCTILE = 0.7;        // 强度排名前 30% → 方向成立

function num(v) { const x = parseFloat(v); return isFinite(x) ? x : NaN; }
function loadDaily(code) {
  const f = path.join(DAILY_DIR, code + '.csv');
  if (!fs.existsSync(f)) return null;
  const lines = fs.readFileSync(f, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/).filter(l => l.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const o = num(c[ix('开盘')]), h = num(c[ix('最高')]), l = num(c[ix('最低')]), cl = num(c[ix('收盘')]);
    const d = String(c[ix('日期')] || c[0]).slice(0, 10);
    if (!isFinite(o) || !isFinite(h) || !isFinite(l) || !isFinite(cl) || cl <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
    rows.push({ d, o, h, l, c: cl });
  }
  const map = new Map();
  for (const r of rows) map.set(r.d, r);
  return [...map.values()].sort((a, b) => (a.d < b.d ? -1 : 1));   // 必须比 b.d，否则字符串比较导致倒序
}
function mean(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; }
function stdev(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }

/* 每只票跑一遍，产出「三买事件流」+「方向条件序列」 */
function harvest(code, daily) {
  // 强度序列：过去 STRENGTH 日累计涨幅
  const strength = new Array(daily.length).fill(null);
  for (let i = STRENGTH; i < daily.length; i++) strength[i] = daily[i].c / daily[i - STRENGTH].c - 1;
  // 三买事件
  const buys = [];       // {confIdx, readyDay}
  const seen = new Set();
  for (let i = WIN - 1; i < daily.length - 1; i++) {
    const off = Math.max(0, i - WIN + 1);
    const ks = daily.slice(off, i + 1).map(r => ({ t: r.d, o: r.o, h: r.h, l: r.l, c: r.c, v: 0 }));
    const res = Chan.analyze(ks, {});
    const sig = CLScanner.pickSignal(ks, res, { maxLag: MAXLAG });
    if (!sig || !sig.confirmed || sig.type <= 0) continue;
    const p = res.points.find(q => q.readyK === sig.readyK && q.type === sig.type && q._k === sig.markK);
    if (!p || CLScanner.anchorOf(p) == null) continue;
    const id = [sig.level, sig.type, sig.t, sig.price].join('|');
    if (seen.has(id)) continue;
    seen.add(id);
    buys.push({ i, note: sig.note, readyDay: ks[sig.readyK] ? ks[sig.readyK].t.slice(0, 10) : '' });
  }
  return { code, strength, buys, daily };
}

/* 三臂 */
function runArms(rows) {
  // rows: [{code, daily, strength, buys}]
  // 方向成立判定需要跨票中位数 → 先收集某日全部 strength 再定
  const dayMap = new Map();
  for (const r of rows) r.daily.forEach((d, i) => {
    if (r.strength[i] == null) return;
    let a = dayMap.get(d.d); if (!a) { a = []; dayMap.set(d.d, a); }
    a.push(r.strength[i]);
  });
  const dayCut = new Map();
  for (const [d, a] of dayMap) {
    const s = a.slice().sort((x, y) => x - y);
    dayCut.set(d, s[Math.min(s.length - 1, Math.floor(s.length * PCTILE))]);
  }
  const dirOk = (r, i) => r.strength[i] != null && dayCut.get(r.daily[i].d) != null && r.strength[i] >= dayCut.get(r.daily[i].d);

  // 每臂收集「入场事件」：{code, entryIdx, dirOk}
  const arms = { A: [], B: [], C: [] };
  for (const r of rows) {
    const { daily, buys } = r;
    const buyIdx = new Map();
    for (const b of buys) if (!buyIdx.has(b.i)) buyIdx.set(b.i, b);
    for (let i = WIN; i < daily.length - 1; i++) {
      const ok = dirOk(r, i);
      // A 臂：方向成立 → 次日开盘进（仅在无持仓概念下按固定持有期计，超额信号层面不做仓位）
      if (ok) arms.A.push({ code: r.code, i, kind: 'A' });
      // B 臂：方向成立 且 当日出现三买 → 次日开盘进
      if (ok && buyIdx.has(i)) arms.B.push({ code: r.code, i, kind: 'B' });
      // C 臂：方向不成立 且 当日出现三买 → 次日开盘进
      if (!ok && buyIdx.has(i)) arms.C.push({ code: r.code, i, kind: 'C' });
    }
  }
  return arms;
}

/* 按固定持有期算收益 */
function ret(rows, ev, N) {
  const out = [];
  for (const e of ev) {
    const daily = rows.find(r => r.code === e.code).daily;
    const k = e.i + 1 + N;
    if (k >= daily.length) continue;
    const r = daily[k].c / daily[e.i + 1].o - 1 - FEE;
    out.push({ code: e.code, day: daily[e.i + 1].d, ret: r });
  }
  return out;
}
function stat(v) {
  const a = v.map(x => x.ret);
  if (!a.length) return { n: 0 };
  const sd = stdev(a);
  return { n: a.length, exp: mean(a), sd, t: sd ? mean(a) / (sd / Math.sqrt(a.length)) : null, win: a.filter(x => x > 0).length / a.length, med: a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)] };
}

(async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const t00 = Date.now();
  const rows = [];
  for (const code of CODES) {
    const daily = loadDaily(code);
    if (!daily || daily.length < WIN + 60) { console.log(`[skip] ${code}`); continue; }
    rows.push(harvest(code, daily));
    console.log(`[ok] ${code} 三买=${rows[rows.length - 1].buys.length} ${((Date.now() - t00) / 1000).toFixed(0)}s`);
  }
  const arms = runArms(rows);
  const out = { hold: HOLD, strength: STRENGTH, pctile: PCTILE, arms: {} };
  for (const k of ['A', 'B', 'C']) {
    out.arms[k] = {};
    for (const N of HOLD) out.arms[k][N] = stat(ret(rows, arms[k], N));
  }
  // 关键差值
  out.diff = {};
  for (const N of HOLD) {
    const A = out.arms.A[N], B = out.arms.B[N], C = out.arms.C[N];
    out.diff[N] = {
      BA: (A && B) ? B.exp - A.exp : null,
      CB: (B && C) ? B.exp - C.exp : null,
      // B−A 的 t：两臂样本独立，用各自 sd 估
      BAt: (A && B && A.sd && B.sd) ? (B.exp - A.exp) / Math.sqrt(B.sd * B.sd / B.n + A.sd * A.sd / A.n) : null
    };
  }
  fs.writeFileSync(path.join(OUT_DIR, 'ba.json'), JSON.stringify({ out, rows: rows.map(r => ({ code: r.code, buys: r.buys })) }, null, 1));

  const pct = x => x == null ? 'n/a' : (100 * x).toFixed(2) + '%';
  const pp = x => x == null ? 'n/a' : (100 * x).toFixed(2) + 'pp';
  console.log(`\n方向条件：过去 ${STRENGTH} 日涨幅排名前 ${((1 - PCTILE) * 100).toFixed(0)}% → 方向成立`);
  console.log('臂定义：A=方向成立直接进  B=方向成立且等三买  C=方向不成立但有三买');
  for (const N of HOLD) {
    console.log(`\n--- 固定持有 ${N} 日 ---`);
    for (const k of ['A', 'B', 'C']) {
      const s = out.arms[k][N];
      console.log(`  ${k}  n=${String(s.n).padStart(5)}  exp=${pct(s.exp).padStart(7)}  t=${s.t == null ? 'n/a' : s.t.toFixed(2)}  win=${pct(s.win)}  med=${pct(s.med)}`);
    }
    console.log(`  B−A = ${pp(out.diff[N].BA)}  (t=${out.diff[N].BAt == null ? 'n/a' : out.diff[N].BAt.toFixed(2)})`);
    console.log(`  B−C = ${pp(out.diff[N].CB)}`);
  }
  console.log(`\nDONE ${((Date.now() - t00) / 1000).toFixed(0)}s`);
})();
