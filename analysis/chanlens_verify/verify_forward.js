/* ==========================================================================
 * verify.js — 独立复核：三类买点的前瞻收益曲线
 *
 * 与 daily_study.js 的区别（本次刻意不复用其 harness）：
 *   1. Chan.analyze 每票每天只调一次，全部信号/基线都从这一次里取，后处理全是纯计算。
 *   2. 只做「测量一」——信号前瞻收益，不掺任何出场规则。这样三类买点之间
 *      是同一把尺子，可比。出场结构留到 verify_strategies.js 测。
 *   3. 持有期网格加密到 1/2/3/5/8/10/15/20/30/40 日 —— 用户的三条结论都跟
 *      「早 vs 晚」「拿久 vs 及时走」有关，5/10/20 三档太粗。
 *   4. 逐日切片口径（禁整段一次 analyze，口径不等价）。
 *
 * 无未来函数：t 日的 analyze 只喂 t 及以前的 K；执行价用 t+1 开盘。
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
const HZ = [1, 2, 3, 5, 8, 10, 15, 20, 30, 40];

/* ------------------------------------------------ 数据 */
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
  return [...map.values()].sort((a, b) => a.d < b.d ? -1 : 1);
}

/* ------------------------------------------------ 单只：跑一遍 analyze，出事件流 */
function harvest(code, daily) {
  // 基线：全部有效日的 N 日前瞻收益
  const base = [];
  for (let i = WIN - 1; i < daily.length - 1; i++) {
    const o = daily[i + 1].o;
    const row = { i, d: daily[i].d };
    for (const N of HZ) {
      const k = i + 1 + N;
      row['f' + N] = (k < daily.length) ? daily[k].c / o - 1 : null;
    }
    base.push(row);
  }
  // 信号：逐日切片
  const sigs = [];
  const seen = new Set();
  for (let i = WIN - 1; i < daily.length - 1; i++) {
    const off = Math.max(0, i - WIN + 1);
    const ks = daily.slice(off, i + 1).map(r => ({ t: r.d, o: r.o, h: r.h, l: r.l, c: r.c, v: 0 }));
    const res = Chan.analyze(ks, {});
    // 最后一个已确认信号（与 daily_study 同口径：类型>0 才有方向意义，这里全收）
    const sig = CLScanner.pickSignal(ks, res, { maxLag: MAXLAG });
    if (!sig || !sig.confirmed) continue;
    const p = res.points.find(q => q.readyK === sig.readyK && q.type === sig.type && q._k === sig.markK);
    if (!p) continue;
    const anchor = CLScanner.anchorOf(p);
    if (anchor == null) continue;
    const id = [sig.level, sig.type, sig.t, sig.price].join('|');
    const sid = code + '|' + id;
    if (seen.has(sid)) continue;
    seen.add(sid);
    // 只在有入场空间时才记（i+1 open 存在）
    if (!daily[i + 1]) continue;
    const row = {
      code, id: sid, level: sig.level, type: sig.type, note: sig.note, price: sig.price,
      readyDay: ks[sig.readyK] ? ks[sig.readyK].t.slice(0, 10) : '',
      entryDay: daily[i + 1].d, entryPrice: daily[i + 1].o, anchor,
      mfeH: Math.max(daily[i + 1].l, daily[i + 1].h)
    };
    for (const N of HZ) {
      const k = i + 1 + N;
      row['f' + N] = (k < daily.length) ? daily[k].c / daily[i + 1].o - 1 : null;
    }
    // 持有期内路径特征（用于验证「早 vs 晚」「什么时候该走」）
    let hi = -Infinity, lo = Infinity;
    for (let k = i + 1; k <= Math.min(i + 1 + 40, daily.length - 1); k++) {
      hi = Math.max(hi, daily[k].h); lo = Math.min(lo, daily[k].l);
    }
    row.mfe = hi / daily[i + 1].o - 1;
    row.mae = lo / daily[i + 1].o - 1;
    row.hitMfe5 = hi / daily[i + 1].o - 1 >= 0.05;
    row.hitMfe10 = hi / daily[i + 1].o - 1 >= 0.10;
    sigs.push(row);
  }
  return { base, sigs };
}

/* ------------------------------------------------ 统计 */
function mean(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : null; }
function stdev(a) { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1)); }
function vsT(a) { const sd = stdev(a); if (!sd) return null; return { exp: mean(a), t: mean(a) / (sd / Math.sqrt(a.length)), n: a.length, sd }; }

/* ------------------------------------------------ 主 */
(async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const allBase = [];
  const allSigs = [];
  const perCode = {};
  const t00 = Date.now();
  for (const code of CODES) {
    const daily = loadDaily(code);
    if (!daily || daily.length < WIN + 60) { console.log(`[skip] ${code}`); continue; }
    const r = harvest(code, daily);
    allBase.push(...r.base); allSigs.push(...r.sigs);
    perCode[code] = { base: r.base.length, sigs: r.sigs.length, from: daily[WIN].d, to: daily[daily.length - 1].d };
    console.log(`[ok] ${code} base=${r.base.length} sig=${r.sigs.length} ${perCode[code].from}~${perCode[code].to} ${((Date.now() - t00) / 1000).toFixed(0)}s`);
  }

  /* 基线 */
  const baseline = {};
  for (const N of HZ) {
    const v = allBase.map(r => r['f' + N]).filter(x => x != null);
    baseline[N] = { exp: mean(v), win: v.filter(x => x > 0).length / v.length, n: v.length, sd: stdev(v) };
  }

  /* 主分组 = note（真正的第几类买点）；type 只是方向符号，不能当分类用 */
  const byNote = {};
  for (const s of allSigs) (byNote[s.note] = byNote[s.note] || []).push(s);
  const BUY = /买/;
  const signal = {};
  for (const [note, rows] of Object.entries(byNote)) {
    const k = note;
    signal[k] = {
      note, n: rows.length, dir: rows[0].type > 0 ? 'buy' : 'sell',
      levels: [...new Set(rows.map(r => r.level))].sort(),
      codes: new Set(rows.map(r => r.code)).size, hz: {}
    };
    for (const N of HZ) {
      const v = rows.map(r => r['f' + N]).filter(x => x != null);
      const m = vsT(v);
      const bv = allBase.map(r => r['f' + N]).filter(x => x != null);
      const bsd = stdev(bv);
      signal[k].hz[N] = {
        n: m ? m.n : 0, exp: m ? m.exp : null, t: m ? m.t : null,
        win: v.length ? v.filter(x => x > 0).length / v.length : null,
        baseExp: mean(bv), baseWin: bv.filter(x => x > 0).length / bv.length,
        edge: m ? m.exp - mean(bv) : null,
        edgeT: (m && stdev(v) && bsd) ? (m.exp - mean(bv)) / Math.sqrt(m.sd * m.sd / m.n + bsd * bsd / bv.length) : null,
        med: v.length ? v.slice().sort((a, b) => a - b)[Math.floor(v.length / 2)] : null,
        medEdge: v.length ? v.slice().sort((a, b) => a - b)[Math.floor(v.length / 2)] - mean(bv) : null
      };
    }
    signal[k].mfe = vsT(rows.map(r => r.mfe).filter(x => x != null));
    signal[k].mae = vsT(rows.map(r => r.mae).filter(x => x != null));
    signal[k].hitMfe5 = rows.filter(r => r.hitMfe5).length / rows.length;
    signal[k].hitMfe10 = rows.filter(r => r.hitMfe10).length / rows.length;
  }

  /* 方向汇总（买 vs 卖） */
  const byDir = {};
  for (const s of allSigs) { const k = s.type > 0 ? 'buy' : 'sell'; (byDir[k] = byDir[k] || []).push(s); }
  const dirs = {};
  for (const [k, rows] of Object.entries(byDir)) {
    dirs[k] = { n: rows.length, hz: {} };
    for (const N of HZ) {
      const v = rows.map(r => r['f' + N]).filter(x => x != null);
      const bv = allBase.map(r => r['f' + N]).filter(x => x != null);
      dirs[k].hz[N] = { n: v.length, exp: mean(v), edge: v.length ? mean(v) - mean(bv) : null };
    }
  }

  fs.writeFileSync(path.join(OUT_DIR, 'forward.json'),
    JSON.stringify({ baseline, signal, dirs, perCode, sigs: allSigs }, null, 1));

  /* 打印 */
  const pct = x => x == null ? '  n/a' : (100 * x).toFixed(2) + '%';
  const pp = x => x == null ? ' n/a' : (100 * x).toFixed(2) + 'pp';
  console.log('\n===== 基线（全样本无条件，N 日持有）=====');
  for (const N of HZ) console.log(`${String(N).padStart(2)}d  exp=${pct(baseline[N].exp)}  win=${pct(baseline[N].win)}  n=${baseline[N].n}`);

  const order = ['一买·底背驰', '二买·回抽不破前低', '三买·回抽不入中枢', '一卖·顶背驰', '二卖·反抽不破前高', '三卖·反抽不入中枢'];
  for (const k of order.filter(x => signal[x])) {
    const s = signal[k];
    console.log(`\n===== ${k}  n=${s.n}  票数=${s.codes}  levels=${s.levels.join(',')} =====`);
    console.log('持有期   信号exp   基线exp    edge     t      胜率   中位数  中位edge');
    for (const N of HZ) {
      const x = s.hz[N];
      console.log(`${String(N).padStart(3)}d  ${pct(x.exp).padStart(8)}  ${pct(x.baseExp).padStart(8)}  ${pp(x.edge).padStart(8)}  ${(x.t == null ? 'n/a' : x.t.toFixed(2)).padStart(6)}  ${pct(x.win).padStart(6)}  ${pct(x.med).padStart(6)}  ${pp(x.medEdge).padStart(7)}`);
    }
    console.log(`  MFE=${pct(s.mfe.exp)}  MAE=${pct(s.mae.exp)}  涨超5%比例=${pct(s.hitMfe5)}  涨超10%比例=${pct(s.hitMfe10)}`);
  }

  console.log('\n===== 方向汇总（edge）=====');
  for (const N of HZ) console.log(`${String(N).padStart(3)}d  买=${pp(dirs.buy.hz[N].edge)}   卖=${pp(dirs.sell.hz[N].edge)}`);

  console.log(`\nDONE ${((Date.now() - t00) / 1000).toFixed(0)}s`);
})();
