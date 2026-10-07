/* ==========================================================================
 * verify_proxy.js — B−A 的方向代理体检
 *
 * verify_ba.js 发现问题：用「20 日涨幅前 30%」当方向条件，A 臂本身显著为负
 * （10 日 -0.16%，t=-3.22）→ 说明这个代理在 ETF 上是反向的，追强势反而跌。
 * 建在反向代理上的 B−A 没有意义。
 *
 * 这里一次试多个代理，各算 A 臂自身的 exp 和 t：
 *   A 臂显著为正 → 代理可用，B−A 才有意义
 *   A 臂显著为负 → 代理反向，弃用
 *
 * 代理候选：
 *   m20        过去20日涨幅前30%      （原方案）
 *   m60        过去60日涨幅前30%
 *   ma20       收盘 > MA20
 *   ma60       收盘 > MA60
 *   ma20_60    收盘 > MA20 且 MA20 > MA60  （多头排列）
 *   none       无条件（=基线）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');
const CLScanner = require('D:/Trading/plugins/chanlens/core/scanner.js').CLScanner;

const CODES = ['512880', '512800', '512480', '513260', '159995', '159857', '512980', '159819', '515880', '513050', '562500',
               '159869', '515700', '159928', '159992', '512660', '159825', '512200', '515220', '159949', '510300', '512890',
               '518880', '511010'];
const DAILY_DIR = 'D:/Trading/data/etfs';
const WIN = 800, MAXLAG = 10, FEE = 0.001;
const HOLD = [10, 20];
const NAMES = ['m20', 'm60', 'ma20', 'ma60', 'ma20_60', 'none'];

function loadDaily(code) {
  const f = path.join(DAILY_DIR, code + '.csv');
  if (!fs.existsSync(f)) return null;
  const lines = fs.readFileSync(f, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/).filter(l => l.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const d = String(c[ix('日期')] || c[0]).slice(0, 10);
    const o = num(c[ix('开盘')]), h = num(c[ix('最高')]), l = num(c[ix('最低')]), cl = num(c[ix('收盘')]);
    if (!isFinite(o) || !isFinite(h) || !isFinite(l) || !isFinite(cl) || !/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
    rows.push({ d, o, h, l, c: cl });
  }
  const map = new Map();
  for (const r of rows) map.set(r.d, r);
  return [...map.values()].sort((a, b) => (a.d < b.d ? -1 : 1));   // 必须比 b.d，原写成 a.d<b 是字符串比较 → 数据倒序
}
function num(v) { const x = parseFloat(v); return isFinite(x) ? x : NaN; }
function mean(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; }
function stdev(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
function sma(c, i, n) { if (i < n - 1) return null; let s = 0; for (let k = i - n + 1; k <= i; k++) s += c[k]; return s / n; }

function harvest(code, daily) {
  const c = daily.map(r => r.c);
  const cond = { m20: new Array(daily.length).fill(null), m60: new Array(daily.length).fill(null), ma20: new Array(daily.length).fill(null), ma60: new Array(daily.length).fill(null), ma20_60: new Array(daily.length).fill(null), none: new Array(daily.length).fill(true) };
  for (let i = 60; i < daily.length; i++) {
    cond.m20[i] = c[i] / c[i - 20] - 1;
    cond.m60[i] = c[i] / c[i - 60] - 1;
    const a20 = sma(c, i, 20), a60 = sma(c, i, 60);
    cond.ma20[i] = a20 == null ? null : c[i] > a20;
    cond.ma60[i] = a60 == null ? null : c[i] > a60;
    cond.ma20_60[i] = (a20 == null || a60 == null) ? null : (c[i] > a20 && a20 > a60);
  }
  const buys = new Set();
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
    buys.add(i);
  }
  return { code, daily, cond, buys };
}

(async function main() {
  const rows = [];
  for (const code of CODES) { const d = loadDaily(code); if (d && d.length >= WIN + 60) rows.push(harvest(code, d)); }

  // 动量类代理需要跨票分位数
  const cut = {};
  for (const key of ['m20', 'm60']) {
    const dayMap = new Map();
    for (const r of rows) for (let i = 0; i < r.daily.length; i++) {
      if (r.cond[key][i] == null) continue;
      let a = dayMap.get(r.daily[i].d); if (!a) { a = []; dayMap.set(r.daily[i].d, a); }
      a.push(r.cond[key][i]);
    }
    const m = new Map();
    for (const [d, a] of dayMap) { const s = a.slice().sort((x, y) => x - y); m.set(d, s[Math.min(s.length - 1, Math.floor(s.length * 0.7))]); }
    cut[key] = m;
  }
  const ok = (r, key, i) => {
    if (key === 'none') return true;
    if (key === 'm20' || key === 'm60') {
      const v = r.cond[key][i], t = cut[key].get(r.daily[i].d);
      return v != null && t != null && v >= t;
    }
    return r.cond[key][i] === true;
  };

  const out = { NAMES, arms: {} };
  const pct = x => x == null ? 'n/a' : (100 * x).toFixed(2) + '%';
  const stat = v => { if (!v.length) return { n: 0 }; const sd = stdev(v); return { n: v.length, exp: mean(v), t: sd ? mean(v) / (sd / Math.sqrt(v.length)) : null, win: v.filter(x => x > 0).length / v.length }; };

  for (const key of NAMES) {
    out.arms[key] = {};
    for (const N of HOLD) {
      const A = [], B = [], C = [];
      for (const r of rows) {
        for (let i = WIN; i < r.daily.length - 1; i++) {
          const k = i + 1 + N; if (k >= r.daily.length) continue;
          const ret = r.daily[k].c / r.daily[i + 1].o - 1 - FEE;
          const o = ok(r, key, i);
          if (o) A.push(ret);
          if (o && r.buys.has(i)) B.push(ret);
          if (!o && r.buys.has(i)) C.push(ret);
        }
      }
      out.arms[key][N] = { A: stat(A), B: stat(B), C: stat(C),
        BA: stat(B).exp != null && stat(A).exp != null ? stat(B).exp - stat(A).exp : null };
    }
  }
  fs.writeFileSync(path.join(__dirname, 'proxy.json'), JSON.stringify(out, null, 1));

  console.log('代理体检：A 臂自身表现（方向条件成立后无条件进，固定持有 N 日）');
  console.log('A 臂显著为正 → 代理可用；显著为负 → 代理反向，弃用\n');
  for (const key of NAMES) {
    console.log(`[${key}]`);
    for (const N of HOLD) {
      const a = out.arms[key][N].A, b = out.arms[key][N].B, c = out.arms[key][N].C;
      console.log(`  ${String(N).padStart(2)}d  A: n=${String(a.n).padStart(5)} exp=${pct(a.exp).padStart(7)} t=${a.t == null ? 'n/a' : a.t.toFixed(2).padStart(6)} win=${pct(a.win)}`);
      console.log(`      B: n=${String(b.n).padStart(5)} exp=${pct(b.exp).padStart(7)} t=${b.t == null ? 'n/a' : b.t.toFixed(2).padStart(6)}   C: n=${String(c.n).padStart(5)} exp=${pct(c.exp).padStart(7)}   B−A=${pct(out.arms[key][N].BA)}`);
    }
  }
})();
