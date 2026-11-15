/* ==========================================================================
 * bt_k.js —— 止损缓冲系数 k 的「性价比」扫描
 *
 * 与 bt_stop.js 的分工：
 *   bt_stop.js 回答「k 要不要改」（配对检验、移动止损、固定百分比对比）
 *   bt_k.js    回答「k 取多少时止损打得最准」——重点是假止损与兑换率
 *
 * 用法：
 *   node bt_k.js                    # 日线 ETF
 *   STOCKS=1 node bt_k.js           # 日线 个股（43 只）
 *   TF=30 node bt_k.js              # 30m ETF
 *
 * 三个核心度量：
 *   假止损  —— 止损后 M 根内，收盘价重新收复入场价（不砍本可以不亏）
 *   真救    —— 不砍而持满 N 根，收益比止损更差
 *   兑换率  —— 每放弃 1pp 期望，换来多少「假止损笔数 / 总笔数」的下降
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const STOCKS = process.env.STOCKS === '1';
const TF = process.env.TF || 'daily';
const IS30 = TF === '30';
if (STOCKS && IS30) { console.error('个股没有 30m 数据'); process.exit(1); }

const packFile = IS30 ? 'pack_30.json' : ('pack_daily' + (STOCKS ? '_stock' : '') + '.json');
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', packFile), 'utf8'));

const FEE = 0.001;
const KS = (process.env.KS || '0,0.25,0.5,0.75,1,1.25,1.5,2,2.5,3').split(',').map(Number);
const FIXS = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15];
const N0 = +(process.env.N || (IS30 ? 160 : 20));   // 主持有期：30m 一天 8 根，160 根 ≈ 20 个交易日
const M0 = N0;                                       // 止损后观察窗，与持有期等长
const TY = { L1: '一买', L2: '二买', L3: '三买' };

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const med = a => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const sd = a => { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / (a.length - 1)); };
const tStat = a => { const s = sd(a); return (s && s > 0) ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const pct = v => v == null ? '—' : (100 * v).toFixed(2) + '%';
const pp = v => v == null ? '—' : (v >= 0 ? '+' : '') + (100 * v).toFixed(2) + 'pp';
const f2 = v => v == null ? '—' : v.toFixed(2);

/* ---------- ATR：与 core/indicators.js 同一套 Wilder 平滑 ---------- */
function atrWilder(ks, n) {
  const N = ks.length, out = new Array(N).fill(null);
  if (N <= n) return out;
  const tr = i => Math.max(ks[i].h - ks[i].l, Math.abs(ks[i].h - ks[i - 1].c), Math.abs(ks[i].l - ks[i - 1].c));
  let v = 0;
  for (let i = 1; i <= n; i++) v += tr(i);
  v /= n;
  out[n] = v;
  for (let i = n + 1; i < N; i++) { v = (v * (n - 1) + tr(i)) / n; out[i] = v; }
  return out;
}

function tradable(p) {
  const n = p.o.length, ok = new Array(n).fill(true);
  if (!STOCKS) return ok;
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    if ((Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 86400000 > 15) ok[i] = false;
  }
  return ok;
}

/* ---------- 主模拟：止损（N 根内） + 止损后 M 根的反事实 ---------- */
function simDiag(p, e, stop, N, M) {
  const n = p.o.length, entry = p.o[e];
  const last = Math.min(e + N - 1, n - 1);
  let si = -1;
  for (let i = e; i <= last; i++) if (stop != null && p.l[i] <= stop) { si = i; break; }

  /* 不设止损、持满 N 根（同一根入场） */
  const noStop = (e + N <= n - 1) ? p.o[e + N] / entry - 1 - FEE : p.c[n - 1] / entry - 1 - FEE;

  if (si < 0) return { ex: 'time', r: noStop, noStop, bars: N, si: null };

  const fill = Math.min(p.o[si], stop);
  const r = fill / entry - 1 - FEE;

  /* 止损后 M 根：价格有没有回去 */
  const end = Math.min(si + M, n - 1);
  let maxH = -Infinity, maxC = -Infinity;
  for (let i = si + 1; i <= end; i++) { if (p.h[i] > maxH) maxH = p.h[i]; if (p.c[i] > maxC) maxC = p.c[i]; }
  /* 假止损后继续持到 si+M 能拿到什么 */
  const holdM = end > si ? p.c[end] / entry - 1 - FEE : null;

  return { ex: 'stop', r, noStop, fill, bars: si - e + 1, si, maxH, maxC, holdM, end };
}

/* ---------- 收集信号 ---------- */
const rows = [];
let skipAnchor = 0, skipAtr = 0, skipBar = 0, skipTrad = 0;
const MAXBUF = Math.max(N0, 0);

for (const p of pack.packs) {
  const n = p.o.length;
  const ks = p.dates.map((d, i) => ({ date: d, o: p.o[i], c: p.c[i], h: p.h[i], l: p.l[i] }));
  const atr = atrWilder(ks, 20);
  const tr = tradable(p);

  for (const b of p.buy || []) {
    if (b.discT - b.readyK !== 1) continue;
    if (!(b.level >= 1 && b.level <= 3)) continue;
    const e = b.discT + 1;
    if (e + MAXBUF > n - 1) { skipBar++; continue; }
    if (!tr[e]) { skipTrad++; continue; }
    const a = atr[b.discT];
    if (!(a > 0)) { skipAtr++; continue; }
    const anchor = b.level === 1 ? b.price
      : b.level === 2 ? (b.b1 != null ? b.b1 : b.price)
        : b.zsZG;
    const entry = p.o[e];
    if (anchor == null || !(anchor < entry)) { skipAnchor++; continue; }

    rows.push({ ty: 'L' + b.level, code: p.code, date: p.dates[e], entry, atr: a,
      atrPct: a / entry, distPct: (entry - anchor) / entry, p, e, anchor });
  }
}

/* ---------- 逐笔算各 k ---------- */
for (const r of rows) {
  r.res = {};
  for (const k of KS) {
    const stop = r.anchor - k * r.atr;
    const risk = (r.entry - stop) / r.entry;
    r.res[k] = simDiag(r.p, r.e, stop, N0, M0);
    r.res[k].risk = risk;
    r.res[k].R = risk > 0 ? r.res[k].r / risk : null;
  }
  r.res.inf = { ex: 'time', r: (r.e + N0 <= r.p.o.length - 1) ? r.p.o[r.e + N0] / r.entry - 1 - FEE : r.p.c[r.p.o.length - 1] / r.entry - 1 - FEE };
  /* 固定百分比止损：距离由外部指定，与失效位无关 —— 用来单独回答「止损设多宽」 */
  for (const f of FIXS) {
    const stop = r.entry * (1 - f);
    r.res['f' + f] = simDiag(r.p, r.e, stop, N0, M0);
    r.res['f' + f].risk = f;
    r.res['f' + f].R = r.res['f' + f].r / f;
  }
}

/* ---------- 汇总 ---------- */
const L1 = rows.filter(z => z.ty === 'L1'), L2 = rows.filter(z => z.ty === 'L2'), L3 = rows.filter(z => z.ty === 'L3');

/** 每档 k 的决策质量 */
function stat(sel, k) {
  const v = sel.map(z => z.res[k]).filter(Boolean);
  const r = v.map(x => x.r);
  const stops = v.filter(x => x.ex === 'stop');
  const rs = r.slice().sort((a, b) => a - b);
  const cut = Math.max(1, Math.floor(r.length * 0.05));
  /* 真救 / 砍错 / 打平：看「不砍而持满 N 根」 */
  const save = stops.filter(x => x.noStop < x.r - 1e-9);
  const wrong = stops.filter(x => x.noStop > x.r + 1e-9);
  const flat = stops.length - save.length - wrong.length;
  /* 假止损：止损后 M 根内收盘收复入场价 —— 需要 entry，用闭包外的 sel 取 */
  let fakeC = 0, fakeH = 0;
  for (let i = 0; i < v.length; i++) {
    const x = v[i]; if (x.ex !== 'stop') continue;
    const entry = sel[i].entry;
    if (x.maxC >= entry) fakeC++;
    if (x.maxH >= entry * 1.02) fakeH++;
  }
  return {
    n: v.length,
    r: mean(r), rmed: med(r), R: mean(v.map(x => x.R).filter(x => x != null)),
    win: r.filter(x => x > 0).length / (r.length || 1),
    sd: sd(r), cvar5: mean(rs.slice(0, cut)), worst: rs[0],
    l10: r.filter(x => x < -0.10).length / r.length,
    l20: r.filter(x => x < -0.20).length / r.length,
    nStop: stops.length,
    stopRate: stops.length / v.length,
    /* 被止损笔的反事实：不砍能拿多少 */
    atStop: mean(stops.map(x => x.r)),
    atHold: mean(stops.map(x => x.noStop)),
    /* 净节省/次：正 = 止损救对了 */
    netPerStop: stops.length ? mean(stops.map(x => x.noStop - x.r)) : null,
    saveRate: save.length / (stops.length || 1),
    wrongRate: wrong.length / (stops.length || 1),
    flat,
    /* 假止损（分母 = 全部止损笔） */
    fakeC, fakeH,
    fakeRate: fakeC / (stops.length || 1),
    fakeRateH: fakeH / (stops.length || 1),
    /* 假止损的冤枉钱：这些笔不砍能拿多少 */
    fakeCost: (() => { const f = []; for (let i = 0; i < v.length; i++) { const x = v[i]; if (x.ex === 'stop' && x.maxC >= sel[i].entry) f.push(x.noStop - x.r); } return f.length ? mean(f) : null; })(),
    dist: mean(v.map(x => x.risk)),          // 止损距离（入场价到止损）
    distMed: med(v.map(x => x.risk)),
    bars: mean(stops.map(x => x.bars))
  };
}

const out = [];
const log = s => { out.push(s); console.log(s); };

const title = (STOCKS ? '个股日线' : (IS30 ? 'ETF 30m' : 'ETF 日线'));
log('# ' + title + '｜样本 ' + rows.length + ' 笔（' + pack.packs.length + ' 只）｜N=' + N0 + '（' + (IS30 ? '≈20 个交易日' : '≈一个月') + '）｜M=' + M0);
log('# 剔除：lag≠1 / 不可交易 / 取不到参照位 / ATR 缺失 —— ' + skipBar + ' / ' + skipTrad + ' / ' + skipAnchor + ' / ' + skipAtr);
log('');

/* ---------- 表 1：止损距离 ---------- */
log('=== 表 1 止损距离（入场价 → 止损价，中位 / 均值）===');
log('k       一买          二买          三买          合计          ATR20占价');
for (const k of KS) {
  const a = stat(rows, k);
  const line = ('k=' + k).padEnd(8) +
    [L1, L2, L3, rows].map(s => {
      const v = s.map(z => z.res[k].risk);
      return (pct(med(v)) + '/' + pct(mean(v))).padEnd(14);
    }).join('') + pct(mean(rows.map(z => z.atrPct)));
  log(line);
}
log('');

/* ---------- 表 2：决策质量（核心） ---------- */
log('=== 表 2 止损决策质量（全样本）===');
log('k      止损次数  止损率   真救率   砍错率   净节省/次  假止损率(收盘收复)  假止损率(高点+2%)  冤枉钱/次');
for (const k of KS) {
  const a = stat(rows, k);
  log(('k=' + k).padEnd(8) + String(a.nStop).padStart(7) + '  ' + pct(a.stopRate).padStart(7) +
    '  ' + pct(a.saveRate).padStart(7) + '  ' + pct(a.wrongRate).padStart(7) +
    '  ' + pp(a.netPerStop).padStart(9) + '  ' + pct(a.fakeRate).padStart(18) +
    '  ' + pct(a.fakeRateH).padStart(18) + '  ' + pp(a.fakeCost).padStart(9));
}
log('');
log('（真救 = 不砍而持满 N 根反而更差；砍错 = 不砍本来能赚更多；净节省 = 不砍收益 − 止损收益 的均值）');
log('');

/* ---------- 表 3：三类分开 ---------- */
for (const ty of ['L1', 'L2', 'L3']) {
  const sel = rows.filter(z => z.ty === ty);
  log('=== 表 3-' + ty + ' ' + TY[ty] + '（n=' + sel.length + '）===');
  log('k       单笔     止损率   真救率   砍错率   净节省/次   假止损率   均值(N根)');
  for (const k of KS) {
    const a = stat(sel, k);
    log(('k=' + k).padEnd(8) + pp(a.r).padStart(8) + '  ' + pct(a.stopRate).padStart(7) +
      '  ' + pct(a.saveRate).padStart(7) + '  ' + pct(a.wrongRate).padStart(7) +
      '  ' + pp(a.netPerStop).padStart(9) + '  ' + pct(a.fakeRate).padStart(9) + '  ' + pp(a.r).padStart(9));
  }
  const inf = sel.map(z => z.res.inf.r);
  log(('不设止损').padEnd(8) + pp(mean(inf)).padStart(8) + '  ' + '0.00%'.padStart(7) + '  ' + '—'.padStart(7) + '  ' + '—'.padStart(7) + '  ' + '—'.padStart(9) + '  ' + '—'.padStart(9));
  log('');
}

/* ---------- 表 4：兑换率（相邻 k） ---------- */
log('=== 表 4 兑换率：加宽 k 的边际收益 ===');
log('区间          Δ期望(配对)     t       Δ假止损笔占比   Δ真救率   Δ止损率   兑换率(少1次假止损/1pp期望)');
for (let i = 1; i < KS.length; i++) {
  const k0 = KS[i - 1], k1 = KS[i];
  const d = rows.map(z => z.res[k1].r - z.res[k0].r);
  const a0 = stat(rows, k0), a1 = stat(rows, k1);
  const dFake = (a1.fakeRate * a1.stopRate) - (a0.fakeRate * a0.stopRate);   // 占总笔的比例
  const cost = Math.abs(mean(d));
  const eff = cost > 1e-9 ? (-dFake * 100) / (cost * 100) : null;           // 每 1pp 期望代价换来的假止损点下降
  log((k0 + '→' + k1).padEnd(13) + pp(mean(d)).padStart(11) + '  ' + f2(tStat(d)).padStart(6) +
    '  ' + pp(dFake).padStart(15) + '  ' + pp(a1.saveRate - a0.saveRate).padStart(9) +
    '  ' + pp(a1.stopRate - a0.stopRate).padStart(9) + '  ' + f2(eff).padStart(24));
}
log('（兑换率 > 1 表示：换来 1pp 的假止损下降，只花不到 1pp 的期望；越大越划算）');
log('');

/* ---------- 表 5：尾部 vs 期望（性价比前沿） ---------- */
log('=== 表 5 性价比前沿（全样本）===');
log('k      期望      Δ期望(vs 0.5)   CVaR5      ΔCVaR5    跌超20%   最差单笔   夏普(均值/σ)  收益/尾部损失');
const b05 = stat(rows, 0.5);
for (const k of KS.concat(['inf'])) {
  const a = k === 'inf'
    ? (() => { const r = rows.map(z => z.res.inf.r); const rs = r.slice().sort((x, y) => x - y); const cut = Math.max(1, Math.floor(r.length * 0.05));
        return { n: r.length, r: mean(r), cvar5: mean(rs.slice(0, cut)), l20: r.filter(x => x < -0.20).length / r.length, worst: rs[0], sd: sd(r) }; })()
    : stat(rows, k);
  const dR = a.r - b05.r;
  const dC = a.cvar5 - b05.cvar5;
  const sharp = a.r / a.sd;
  const eff = a.r / Math.abs(a.cvar5);          // 每单位尾部损失换多少收益
  log((k === 'inf' ? '不设止损' : 'k=' + k).padEnd(9) + pp(a.r).padStart(8) + '  ' + pp(dR).padStart(12) +
    '  ' + pp(a.cvar5).padStart(9) + '  ' + pp(dC).padStart(9) + '  ' + pct(a.l20).padStart(7) +
    '  ' + pp(a.worst).padStart(9) + '  ' + f2(sharp).padStart(9) + '  ' + f2(eff).padStart(11));
}
log('');

/* ---------- 表 6：稳健性 —— 按标的 / 按时间段 ---------- */
log('=== 表 6 净节省/次 的稳健性（只统计被止损的笔）===');
log('k      全体      2020前     2020后     一买     二买     三买');
const in2020 = z => z.date >= '2020-01-01';
for (const k of KS) {
  const g = sel => { const s = sel.filter(z => z.res[k].ex === 'stop'); return s.length ? mean(s.map(x => x.res[k].noStop - x.res[k].r)) : null; };
  log(('k=' + k).padEnd(8) + [rows, rows.filter(z => !in2020(z)), rows.filter(in2020), L1, L2, L3]
    .map(s => pp(g(s)).padStart(9)).join(''));
}
log('');

/* ---------- 表 7：固定百分比止损 —— 剥离失效位，只看「距离」本身 ---------- */
log('=== 表 7 固定百分比止损（距离由外部给定，与失效位无关）===');
const tailOf = sel => { const r = sel.map(z => z.res.inf.r); const rs = r.slice().sort((a, b) => a - b); const cut = Math.max(1, Math.floor(r.length * 0.05)); return { r: mean(r), cvar5: mean(rs.slice(0, cut)) }; };
const infAll = tailOf(rows);
log('止损距离  止损率   真救率   砍错率   净节省/次  假止损率  单笔      Δvs无止   CVaR5     收益/尾部');
for (const f of FIXS) {
  const a = stat(rows, 'f' + f);
  log(('−' + (f * 100).toFixed(0) + '%').padEnd(9) + pct(a.stopRate).padStart(7) + '  ' + pct(a.saveRate).padStart(7) +
    '  ' + pct(a.wrongRate).padStart(7) + '  ' + pp(a.netPerStop).padStart(9) + '  ' + pct(a.fakeRate).padStart(8) +
    '  ' + pp(a.r).padStart(8) + '  ' + pp(a.r - infAll.r).padStart(8) + '  ' + pp(a.cvar5).padStart(9) +
    '  ' + f2(a.r / Math.abs(a.cvar5)).padStart(9));
}
log(('不设止损').padEnd(9) + '0.00%'.padStart(7) + '  ' + '—'.padStart(7) + '  ' + '—'.padStart(7) + '  ' + '—'.padStart(9) +
  '  ' + '—'.padStart(8) + '  ' + pp(infAll.r).padStart(8) + '  ' + '+0.00pp'.padStart(8) + '  ' + pp(infAll.cvar5).padStart(9) +
  '  ' + f2(infAll.r / Math.abs(infAll.cvar5)).padStart(9));
log('');

/* 表 7b：三类各自的最优距离 */
log('=== 表 7b 分类别：单笔最好的固定距离 vs 现行 k=' + (0.5) + ' ===');
log('类型      最优距离   单笔(最优)   单笔(k=0.5)   差额     k=0.5 的实际中位距离');
for (const ty of ['L1', 'L2', 'L3']) {
  const sel = rows.filter(z => z.ty === ty);
  let best = null;
  for (const f of FIXS) { const a = stat(sel, 'f' + f); if (!best || a.r > best.r) best = { f, r: a.r }; }
  const cur = stat(sel, 0.5);
  const dmed = med(sel.map(z => z.res[0.5].risk));
  log(TY[ty].padEnd(9) + ('−' + (best.f * 100).toFixed(0) + '%').padStart(9) + '  ' + pp(best.r).padStart(10) +
    '  ' + pp(cur.r).padStart(11) + '  ' + pp(best.r - cur.r).padStart(8) + '  ' + pct(dmed).padStart(18));
}
log('');

/* ---------- 落盘 ---------- */
fs.mkdirSync(path.join(__dirname, 'out'), { recursive: true });
const tag = STOCKS ? '_stock' : (IS30 ? '_30' : '');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_k' + tag + '.txt'), out.join('\n') + '\n');
console.log('\n原始表：out/bt_k' + tag + '.txt');

/* 供报告脚本复用 */
const J = { title, N0, M0, n: rows.length, packs: pack.packs.length, ks: KS };
for (const k of KS) J['k' + k] = stat(rows, k);
for (const f of FIXS) J['f' + f] = stat(rows, 'f' + f);
for (const ty of ['L1', 'L2', 'L3']) for (const k of KS) J[ty + '_' + k] = stat(rows.filter(z => z.ty === ty), k);
J.pair = {};
for (let i = 1; i < KS.length; i++) {
  const k0 = KS[i - 1], k1 = KS[i];
  const d = rows.map(z => z.res[k1].r - z.res[k0].r);
  J.pair[k0 + '->' + k1] = { d: mean(d), t: tStat(d) };
}
/* 无止损基准 */
J.inf = (() => {
  const r = rows.map(z => z.res.inf.r), rs = r.slice().sort((a, b) => a - b);
  const cut = Math.max(1, Math.floor(r.length * 0.05));
  return { n: r.length, r: mean(r), cvar5: mean(rs.slice(0, cut)), l20: r.filter(x => x < -0.20).length / r.length };
})();
/* 分段（2020 前/后）—— 报告分类别结论要用 */
J.seg = {};
for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
  const sel = ty === 'ALL' ? rows : rows.filter(z => z.ty === ty);
  J.seg[ty] = {};
  for (const k of [0, 0.5, 1, 1.5, 2]) {
    const pre = sel.filter(z => z.date < '2020-01-01').map(z => z.res[k].r);
    const post = sel.filter(z => z.date >= '2020-01-01').map(z => z.res[k].r);
    J.seg[ty][k] = { pre: mean(pre), preN: pre.length, post: mean(post), postN: post.length };
  }
}
fs.writeFileSync(path.join(__dirname, 'out', 'bt_k' + tag + '.json'), JSON.stringify(J, null, 1));
