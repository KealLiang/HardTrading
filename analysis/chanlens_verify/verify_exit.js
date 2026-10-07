/* ==========================================================================
 * verify_exit.js — 检验「三买赚了就要走别恋战」
 *
 * 用户结论之一：三买靠谱，但「出了之后要学会赚了就走别恋战」。
 * verify_forward 已显示三买固定持有：10d +0.22pp 显著，20d −0.21pp 转为负。
 * 但那是「死拿 N 日」的口径 —— 现实里人会不会止盈？止盈能不能救回 20 日的劣势？
 *
 * 这里对**同一批三买信号**跑不同出场，隔离出场结构的贡献：
 *   hold10 / hold20      固定持有（对照，已知结论）
 *   trailY               移动止盈：自入场起最高价回落 X% 即次日开盘出
 *   halfN                N 日时先卖一半，剩余用移动止盈
 *   failOnly             只用失效位（跌破信号低点/中枢 ZG 即出），无移动止盈
 *   failTrail            失效位 + 移动止盈（最接近真实用法）
 *
 * 无未来函数：入场 = 信号确认次日开盘；止盈判定用当日收盘触发、次日开盘成交；
 *   失效位来自信号本身（anchorOf），不用未来数据。
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
const OUT_DIR = 'D:/Trading/analysis/chanlens_verify';
const WIN = 800, MAXLAG = 10, FEE = 0.001;
const TRAILS = [0.03, 0.05, 0.08];      // 移动止盈回撤比例

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
    const d = String(c[ix('日期')] || c[0]).slice(0, 10);
    const o = num(c[ix('开盘')]), h = num(c[ix('最高')]), l = num(c[ix('最低')]), cl = num(c[ix('收盘')]);
    if (!isFinite(o) || !isFinite(h) || !isFinite(l) || !isFinite(cl) || !/^\d{4}-\d{2}-\d{2}$/.test(d)) continue;
    rows.push({ d, o, h, l, c: cl });
  }
  const map = new Map();
  for (const r of rows) map.set(r.d, r);
  return [...map.values()].sort((a, b) => (a.d < b.d ? -1 : 1));
}
function mean(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; }
function stdev(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }

/* 采集三买信号（含失效位） */
function harvest(code, daily) {
  const out = [];
  const seen = new Set();
  for (let i = WIN - 1; i < daily.length - 1; i++) {
    const off = Math.max(0, i - WIN + 1);
    const ks = daily.slice(off, i + 1).map(r => ({ t: r.d, o: r.o, h: r.h, l: r.l, c: r.c, v: 0 }));
    const res = Chan.analyze(ks, {});
    const sig = CLScanner.pickSignal(ks, res, { maxLag: MAXLAG });
    if (!sig || !sig.confirmed || sig.type <= 0) continue;
    if (sig.note.indexOf('三买') < 0) continue;
    const p = res.points.find(q => q.readyK === sig.readyK && q.type === sig.type && q._k === sig.markK);
    if (!p) continue;
    const anchor = CLScanner.anchorOf(p);
    if (anchor == null) continue;
    const id = [sig.level, sig.type, sig.t, sig.price].join('|');
    if (seen.has(id)) continue;
    seen.add(id);
    if (!daily[i + 1]) continue;
    out.push({ code, confIdx: i, entryDay: daily[i + 1].d, entry: daily[i + 1].o, anchor, note: sig.note });
  }
  return out;
}

/* 所有出场统一观察窗口 maxHold 天，窗口末强制按收盘平仓。
   这样「移动止盈」和「固定持有」的样本集合完全一致，可直接比较，
   也避免「只统计已离场单子」造成选择性样本（走了很久还没回撤的单子
   恰恰是最赚的，剔除它们会把移动止盈的优势算成假象）。 */
function simTrade(daily, sig, mode, param, maxHold) {
  const i = sig.confIdx;
  const entry = sig.entry;
  let hi = -Infinity;
  let px = null, reason = mode, heldAt = maxHold;
  for (let j = i + 1; j <= Math.min(i + maxHold, daily.length - 1); j++) {
    const d = daily[j];
    const h = d.h; if (h > hi) hi = h;
    const held = j - (i + 1);
    if (px == null) {
      if (mode === 'hold') { if (held + 1 >= param) { px = d.c; reason = 'hold'; heldAt = held + 1; } }
      else if (mode === 'trail') { if (hi / entry - 1 >= param && d.c < hi * (1 - param)) { px = d.c; reason = 'trail'; heldAt = held + 1; } }
      else if (mode === 'failOnly') { if (d.c < sig.anchor) { px = d.c; reason = 'fail'; heldAt = held + 1; } }
      else if (mode === 'failTrail') {
        if (d.c < sig.anchor) { px = d.c; reason = 'fail'; heldAt = held + 1; }
        else if (hi / entry - 1 >= param && d.c < hi * (1 - param)) { px = d.c; reason = 'trail'; heldAt = held + 1; }
      }
    }
    if (px == null && (held + 1 >= maxHold || j === daily.length - 1)) { px = d.c; reason = 'windowEnd'; heldAt = held + 1; }
  }
  const last = daily[daily.length - 1];
  if (px == null) return { code: sig.code, exitDay: last.d, ret: last.c / entry - 1 - FEE, held: maxHold, reason: 'eod' };
  return { code: sig.code, exitDay: last.d, ret: px / entry - 1 - FEE, held: heldAt, reason };
}

(async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const t00 = Date.now();
  const cache = {};
  const sigs = [];
  for (const code of CODES) {
    const d = loadDaily(code);
    if (!d || d.length < WIN + 60) continue;
    cache[code] = d;
    const s = harvest(code, d);
    sigs.push(...s);
    console.log(`[ok] ${code} 三买=${s.length} ${((Date.now() - t00) / 1000).toFixed(0)}s`);
  }
  console.log(`三买信号合计 ${sigs.length}\n`);

  const stat = rows => {
    const v = rows.map(x => x.ret).filter(x => x != null && isFinite(x));
    if (!v.length) return { n: 0 };
    const sd = stdev(v);
    const sv = v.slice().sort((x, y) => x - y);
    return {
      n: v.length, exp: mean(v),
      t: sd ? mean(v) / (sd / Math.sqrt(v.length)) : null,
      win: v.filter(x => x > 0).length / v.length,
      med: sv[Math.floor(v.length / 2)],
      p90: sv[Math.floor(v.length * 0.9)],
      held: mean(rows.map(x => x.held)),
      reasons: rows.reduce((m, x) => { m[x.reason] = (m[x.reason] || 0) + 1; return m; }, {})
    };
  };

  const cfgs = [
    { label: 'hold10', mode: 'hold', param: 10, max: 40 },
    { label: 'hold20', mode: 'hold', param: 20, max: 40 },
    { label: 'hold40', mode: 'hold', param: 40, max: 40 },
    { label: 'trail3', mode: 'trail', param: 0.03, max: 40 },
    { label: 'trail5', mode: 'trail', param: 0.05, max: 40 },
    { label: 'trail8', mode: 'trail', param: 0.08, max: 40 },
    { label: 'failOnly', mode: 'failOnly', param: null, max: 40 },
    { label: 'failTrail5', mode: 'failTrail', param: 0.05, max: 40 }
  ];
  const res = {};
  for (const c of cfgs) {
    const t = sigs.map(s => simTrade(cache[s.code], Object.assign({}, s), c.mode, c.param, c.max));
    res[c.label] = stat(t);
  }
  fs.writeFileSync(path.join(OUT_DIR, 'exit.json'), JSON.stringify({ res, sigs }, null, 1));

  const pct = x => x == null ? 'n/a' : (100 * x).toFixed(2) + '%';
  console.log('=== 同一批三买信号，不同出场（费后，统�� 40 日观察窗口，样本集完全一致）===');
  console.log('出场         n     exp       t    胜率   中位数   p90    平均持有  离场原因');
  for (const c of cfgs) {
    const r = res[c.label];
    console.log(`${c.label.padEnd(12)} ${String(r.n).padStart(4)}  ${pct(r.exp).padStart(7)}  ${r.t == null ? 'n/a' : r.t.toFixed(2).padStart(6)}  ${pct(r.win)}  ${pct(r.med)}  ${pct(r.p90)}  ${r.held.toFixed(1).padStart(6)}   ${JSON.stringify(r.reasons)}`);
  }
  console.log('\n注：所有出场用同一批 355 个信号、同一 40 日窗口，窗口末统一按收盘平仓，样本集一致可直接比。');
  console.log(`\nDONE ${((Date.now() - t00) / 1000).toFixed(0)}s`);
  console.log(`\nDONE ${((Date.now() - t00) / 1000).toFixed(0)}s`);
})();
