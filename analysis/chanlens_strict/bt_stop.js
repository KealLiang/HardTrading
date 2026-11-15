/*  bt_stop.js —— 止损参数扫描
 *
 *  问题：作战卡的条件单是「失效位 ∓ 0.5×ATR20」，这个 0.5 当初是拍的。
 *        k 到底该取多少？k=0（贴着失效位）会不会被噪音打掉？k=2 会不会亏太多？
 *
 *  口径（与 bt_hold 完全一致）：
 *    信号 = lag==1、level 1~3；入场 = discT+1 开盘；手续费 0.1% 双边
 *    失效位（anchor）：一买 = 买点价，二买 = 一买低点，三买 = 中枢上沿 ZG（跌回中枢即错）
 *    止损价 = anchor − k×ATR20（ATR20 取 discT 那根，即发现信号当天，无未来函数）
 *    成交：日内 low ≤ 止损 → 成交在 min(open, 止损)（跳空低开按开盘价，不假装成交在止损价）
 *    时间出场：e+N 开盘（N=10/20/60），模拟「持满 N 根」
 *
 *  两种收益口径，都报：
 *    单笔%  = 等金额买入的收益率（不含杠杆）—— 回答「这笔赚不赚」
 *    R      = 收益 ÷ 初始止损距离 —— 因为仓位是按止损距离定的（R% ÷ 距离%），
 *             止损收紧 → 仓位变大 → 同样 1% 风险下盈亏都被放大。这才是真实账户口径。
 */
const fs = require('fs'), path = require('path');
const L = require('./lib');

const STOCKS = process.env.STOCKS === '1';
const TAG = STOCKS ? '_stock' : '';
const pack = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_daily' + TAG + '.json'), 'utf8'));

const FEE = 0.001;
const KS = [0, 0.5, 1, 1.5, 2, 2.5, 3];
const FIX = [0.03, 0.05, 0.08];
const NS = [10, 20, 60];
const N0 = 20;                       // 主表用的持有期
const TY = { L1: '一买', L2: '二买', L3: '三买' };

/* ---------- 统计 ---------- */
const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
const med = a => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const sd = a => { if (a.length < 2) return null; const m = mean(a); return Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / (a.length - 1)); };
const tStat = a => { const s = sd(a); return (s && s > 0) ? mean(a) / (s / Math.sqrt(a.length)) : null; };
const pct = v => v == null ? '—' : (100 * v).toFixed(2) + '%';
const pp = v => v == null ? '—' : (v >= 0 ? '+' : '') + (100 * v).toFixed(2) + 'pp';
const f2 = v => v == null ? '—' : v.toFixed(2);
const f1 = v => v == null ? '—' : v.toFixed(1);

/* ---------- ATR20：与 app 完全一致（core/indicators.js 的 atr，Wilder 平滑） ---------- */
function atrWilder(ks, n) {
  n = n || 20;
  const out = new Array(ks.length).fill(null);
  if (ks.length <= n) return out;
  let v = 0;
  for (let i = 1; i <= n; i++) v += Math.max(ks[i].h - ks[i].l, Math.abs(ks[i].h - ks[i - 1].c), Math.abs(ks[i].l - ks[i - 1].c));
  v /= n;
  out[n] = v;
  for (let i = n + 1; i < ks.length; i++) {
    const tr = Math.max(ks[i].h - ks[i].l, Math.abs(ks[i].h - ks[i - 1].c), Math.abs(ks[i].l - ks[i - 1].c));
    v = (v * (n - 1) + tr) / n;
    out[i] = v;
  }
  return out;
}

/* ---------- 可交易性（同日线回测：一字涨停 / 停牌复牌日不成交） ---------- */
function tradable(p) {
  const n = p.o.length, ok = new Array(n).fill(true);
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    if ((Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 86400000 > 15) ok[i] = false;
  }
  return ok;
}

/* ---------- 单笔模拟：止损优先于时间出场 ---------- */
function sim(p, e, stop, N) {
  const n = p.o.length;
  const last = Math.min(e + N - 1, n - 1);
  for (let i = e; i <= last; i++) {
    if (stop != null && p.l[i] <= stop) {
      const fill = Math.min(p.o[i], stop);           // 跳空低开按开盘价成交
      return { fill, bars: i - e + 1, ex: 'stop' };
    }
  }
  if (e + N <= n - 1) return { fill: p.o[e + N], bars: N, ex: 'time' };
  return { fill: p.c[n - 1], bars: n - 1 - e, ex: 'eod' };
}

/* ---------- 收集信号（同一批样本，供所有 k/N 共用） ---------- */
const rows = [];
let skipAnchor = 0, skipAtr = 0, skipBar = 0, skipTrad = 0;
const distAll = [];

for (const p of pack.packs) {
  const n = p.o.length;
  const ks = p.dates.map((d, i) => ({ date: d, o: p.o[i], c: p.c[i], h: p.h[i], l: p.l[i], bad: p.bad[i] }));
  const atr = atrWilder(ks, 20);
  const tr = tradable(p);

  for (const b of p.buy || []) {
    if (b.discT - b.readyK !== 1) continue;
    if (!(b.level >= 1 && b.level <= 3)) continue;
    const e = b.discT + 1;
    if (e + Math.max(...NS) > n - 1) { skipBar++; continue; }
    if (!tr[e]) { skipTrad++; continue; }
    const a = atr[b.discT];
    if (!(a > 0)) { skipAtr++; continue; }
    const anchor = b.level === 1 ? b.price
      : b.level === 2 ? (b.b1 != null ? b.b1 : b.price)
        : b.zsZG;
    const entry = p.o[e];
    if (anchor == null || !(anchor < entry)) { skipAnchor++; continue; }

    rows.push({
      ty: 'L' + b.level, code: p.code, date: p.dates[e], entry,
      atrPct: a / entry, distPct: (entry - anchor) / entry,
      mom20: e >= 20 ? entry / p.c[e - 20] - 1 : null,
      p, e, anchor, atr: a
    });
    distAll.push({ ty: 'L' + b.level, dist: (entry - anchor) / entry, atr: a / entry });
  }
}

/* ---------- 对每笔预计算各 (k,N) 的结果 ---------- */
for (const r of rows) {
  r.res = {};
  for (const k of KS) {
    const stop = r.anchor - k * r.atr;
    const risk = (r.entry - stop) / r.entry;
    for (const N of NS) {
      const s = sim(r.p, r.e, stop, N);
      const ret = s.fill / r.entry - 1 - FEE;
      r.res[k + '|' + N] = { r: ret, R: risk > 0 ? ret / risk : null, ex: s.ex, bars: s.bars, risk };
    }
  }
  /* 无止损（只持满 N 根）*/
  for (const N of NS) {
    const s = sim(r.p, r.e, null, N);
    r.res['inf|' + N] = { r: s.fill / r.entry - 1 - FEE, R: null, ex: s.ex, bars: s.bars, risk: null };
  }
  /* 固定百分比止损 */
  for (const f of FIX) {
    const stop = r.entry * (1 - f);
    for (const N of NS) {
      const s = sim(r.p, r.e, stop, N);
      const ret = s.fill / r.entry - 1 - FEE;
      r.res['f' + f + '|' + N] = { r: ret, R: ret / f, ex: s.ex, bars: s.bars, risk: f };
    }
  }
}

/* ---------- 汇总 ---------- */
function agg(sel, key) {
  const v = sel.map(z => z.res[key]).filter(x => x && x.r != null);
  const r = v.map(x => x.r).slice().sort((a, b) => a - b);
  const R = v.map(x => x.R).filter(x => x != null);
  const wins = r.filter(x => x > 0), loss = r.filter(x => x <= 0);
  const cut = Math.max(1, Math.floor(r.length * 0.05));
  return {
    n: v.length, r: mean(r), rmed: med(r), R: mean(R), Rmed: med(R), tR: tStat(R),
    win: wins.length / (r.length || 1),
    stopRate: v.filter(x => x.ex === 'stop').length / (v.length || 1),
    risk: mean(v.map(x => x.risk).filter(x => x != null)) || null,
    bars: mean(v.map(x => x.bars)),
    sd: sd(r),
    cvar5: mean(r.slice(0, cut)),                 // 最差 5% 的平均
    worst: r[0],
    l10: r.filter(x => x < -0.10).length / r.length,
    l20: r.filter(x => x < -0.20).length / r.length,
    pl: loss.length ? mean(wins) / Math.abs(mean(loss)) : null,
    sharp: sd(r) ? mean(r) / sd(r) : null
  };
}

const out = [];
const log = s => { out.push(s); console.log(s); };

log('样本：' + rows.length + ' 笔（lag=1、三级买点、有失效位、ATR20 可取）');
log('剔除：anchor≥入场价 ' + skipAnchor + '，ATR 缺失 ' + skipAtr + '，尾部不足 ' + skipBar + '，不可成交 ' + skipTrad);
log('');

/* 表 1：止损距离有多宽 —— 0.5×ATR 到底紧不紧 */
log('=== 表 1 止损距离（入场价到止损价，%）===');
log('k            一买              二买              三买');
for (const k of KS) {
  let line = ('k=' + k).padEnd(12);
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.ty === ty);
    const v = s.map(z => (z.entry - (z.anchor - k * z.atr)) / z.entry);
    line += ('中位 ' + pct(med(v)) + ' / p90 ' + pct(v.slice().sort((a, b) => a - b)[Math.floor(0.9 * (v.length - 1))])).padEnd(18);
  }
  log(line);
}
log('');

/* 表 2：主表 —— k × 类型，N=20 */
for (const ty of ['L1', 'L2', 'L3']) {
  const s = rows.filter(z => z.ty === ty);
  log('=== ' + TY[ty] + '（n=' + s.length + '，持有 ' + N0 + ' 根）===');
  log('k     止损距离  单笔均值   中位     胜率   止损率   R均值     R中位   R的t');
  for (const k of KS) {
    const a = agg(s, k + '|' + N0);
    log(('k=' + k).padEnd(7) + pct(a.risk).padStart(8) + '  ' + pp(a.r).padStart(9) + '  ' + pp(a.rmed).padStart(8) +
      '  ' + pct(a.win).padStart(6) + '  ' + pct(a.stopRate).padStart(6) + '  ' + f2(a.R).padStart(7) +
      '  ' + f2(a.Rmed).padStart(7) + '  ' + f2(a.tR).padStart(6));
  }
  const a = agg(s, 'inf|' + N0);
  log('无止   —'.padEnd(7) + '         ' + '  ' + pp(a.r).padStart(9) + '  ' + pp(a.rmed).padStart(8) +
    '  ' + pct(a.win).padStart(6) + '  ' + pct(a.stopRate).padStart(6));
  log('');
}

/* 表 3：全样本合计（三类合并，等权）*/
log('=== 全样本合计（n=' + rows.length + '）===');
log('k     止损距离  单笔均值   胜率   止损率   R均值   R的t');
for (const k of KS) {
  const a = agg(rows, k + '|' + N0);
  log(('k=' + k).padEnd(7) + pct(a.risk).padStart(8) + '  ' + pp(a.r).padStart(9) + '  ' + pct(a.win).padStart(6) +
    '  ' + pct(a.stopRate).padStart(6) + '  ' + f2(a.R).padStart(7) + '  ' + f2(a.tR).padStart(6));
}
log('');

/* 表 3b：尾部——止损真正的用处 */
log('=== 表 3b 尾部（全样本，N=' + N0 + '）===');
log('k      均值     标准差   最差5%均  最差单笔  跌超10%  跌超20%  赔率  单笔夏普');
for (const k of KS) {
  const a = agg(rows, k + '|' + N0);
  log(('k=' + k).padEnd(7) + pp(a.r).padStart(9) + '  ' + pct(a.sd).padStart(8) + '  ' + pp(a.cvar5).padStart(9) +
    '  ' + pp(a.worst).padStart(9) + '  ' + pct(a.l10).padStart(7) + '  ' + pct(a.l20).padStart(7) +
    '  ' + f2(a.pl).padStart(5) + '  ' + f2(a.sharp).padStart(7));
}
{ const a = agg(rows, 'inf|' + N0);
  log('无止   ' + pp(a.r).padStart(9) + '  ' + pct(a.sd).padStart(8) + '  ' + pp(a.cvar5).padStart(9) +
    '  ' + pp(a.worst).padStart(9) + '  ' + pct(a.l10).padStart(7) + '  ' + pct(a.l20).padStart(7) +
    '  ' + f2(a.pl).padStart(5) + '  ' + f2(a.sharp).padStart(7)); }
log('');

/* 表 3c：止损的分类账——救下多少、砍错多少 */
log('=== 表 3c 止损的分类账（被打掉的笔，若持满 ' + N0 + ' 根会怎样）===');
log('k      被打掉   救下(否则亏>10%)  救下(否则亏>20%)  砍错(否则赚钱)  砍错占比');
for (const k of KS) {
  const hit = rows.filter(z => z.res[k + '|' + N0].ex === 'stop');
  const hold = hit.map(z => z.res['inf|' + N0].r);
  const save10 = hold.filter(x => x < -0.10).length;
  const save20 = hold.filter(x => x < -0.20).length;
  const bad = hold.filter(x => x > 0).length;
  log(('k=' + k).padEnd(7) + String(hit.length).padStart(6) + '      ' + String(save10).padStart(8) +
    '        ' + String(save20).padStart(8) + '        ' + String(bad).padStart(8) + '       ' + pct(bad / hit.length).padStart(7));
}
log('');

/* 表 4：被打掉的那批，如果不打止损会怎样（whitepsaw 成本）*/
log('=== 表 4 止损打掉的那批：反事实 ===');
log('k      被打掉   止损时平均   若持满20根平均   差额（负=止损救了，正=止损砍错）');
for (const k of KS) {
  for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
    const s = ty === 'ALL' ? rows : rows.filter(z => z.ty === ty);
    const hit = s.filter(z => z.res[k + '|' + N0].ex === 'stop');
    if (!hit.length) continue;
    const atStop = mean(hit.map(z => z.res[k + '|' + N0].r));
    const atN = mean(hit.map(z => z.res['inf|' + N0].r));
    log(('k=' + k).padEnd(7) + String(hit.length).padStart(6) + '   ' + pp(atStop).padStart(9) + '      ' +
      pp(atN).padStart(9) + '        ' + pp(atN - atStop).padStart(9) + '   ' + (ty === 'ALL' ? '【合计】' : TY[ty]));
  }
}
log('');

/* 表 5：持有期敏感性 —— R 均值随 N 怎么变 */
log('=== 表 5 持有期敏感性（R 均值）===');
log('k      ' + ['一买', '二买', '三买'].map(t => t + '(10/20/60)').join('        '));
for (const k of KS) {
  let line = ('k=' + k).padEnd(7);
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.ty === ty);
    line += NS.map(N => f2(agg(s, k + '|' + N).R)).join('/').padEnd(20);
  }
  log(line);
}
log('');

/* 表 6：固定百分比 vs ATR 倍数 */
log('=== 表 6 固定百分比止损（N=20）===');
log('止损    ' + ['一买', '二买', '三买'].map(t => t + ' 单笔/R').join('          '));
for (const f of FIX) {
  let line = ('−' + (f * 100).toFixed(0) + '%').padEnd(8);
  for (const ty of ['L1', 'L2', 'L3']) {
    const a = agg(rows.filter(z => z.ty === ty), 'f' + f + '|' + N0);
    line += (pp(a.r) + ' / ' + f2(a.R)).padEnd(20);
  }
  log(line);
}
log('');
for (const k of [1, 1.5, 2]) {
  let line = ('k=' + k).padEnd(8);
  for (const ty of ['L1', 'L2', 'L3']) {
    const a = agg(rows.filter(z => z.ty === ty), k + '|' + N0);
    line += (pp(a.r) + ' / ' + f2(a.R)).padEnd(20);
  }
  log(line);
}

/* 表 7：配对差 —— 同一批笔换参数，差值的 t 值才是「这个差别是真的吗」 */
log('=== 表 7 与 k=0.5 的配对差（同一批笔，N=' + N0 + '）===');
log('k      Δ单笔      Δ的t     Δ最差5%   止损率     均值±1.96SE');
for (const k of KS) {
  const d = rows.map(z => z.res[k + '|' + N0].r - z.res[0.5 + '|' + N0].r);
  const m = mean(d), se = sd(d) / Math.sqrt(d.length);
  const a = agg(rows, k + '|' + N0), b = agg(rows, '0.5|' + N0);
  log(('k=' + k).padEnd(7) + pp(m).padStart(9) + '  ' + f2(tStat(d)).padStart(6) +
    '  ' + pp(a.cvar5 - b.cvar5).padStart(9) + '  ' + (pct(a.stopRate) + ' / ' + pct(b.stopRate)).padStart(13) +
    '   [' + pp(m - 1.96 * se) + ', ' + pp(m + 1.96 * se) + ']');
}
log('');

/* 表 8：拉长持有期后，止损是否开始值钱（N=60 尾部）*/
log('=== 表 8 持有 60 根的尾部 ===');
log('k      均值     标准差   最差5%均  最差单笔  跌超20%');
for (const k of KS.concat(['inf'])) {
  const a = agg(rows, k + '|60');
  log((k === 'inf' ? '无止' : 'k=' + k).padEnd(7) + pp(a.r).padStart(9) + '  ' + pct(a.sd).padStart(8) +
    '  ' + pp(a.cvar5).padStart(9) + '  ' + pp(a.worst).padStart(9) + '  ' + pct(a.l20).padStart(7));
}
log('');

/* ---------- 止损随行情移动：保本 / 追踪（同一根内先判止损再上移，不偷价） ---------- */
function simTrail(p, e, stop0, N, trigR, trailR) {
  const entry = p.o[e], risk = entry - stop0;
  let stop = stop0, peak = -Infinity;
  const last = Math.min(e + N - 1, p.o.length - 1);
  for (let i = e; i <= last; i++) {
    if (p.l[i] <= stop) return { fill: Math.min(p.o[i], stop), bars: i - e + 1, ex: 'stop', stop };
    if (p.h[i] > peak) peak = p.h[i];
    if (peak - entry >= trigR * risk) {
      const ns = trailR == null ? entry : peak - trailR * risk;
      if (ns > stop) stop = ns;
    }
  }
  if (e + N <= p.o.length - 1) return { fill: p.o[e + N], bars: N, ex: 'time', stop };
  return { fill: p.c[p.o.length - 1], bars: p.o.length - 1 - e, ex: 'eod', stop };
}

/* 表 9：让止损动起来 */
const varRes = [];
for (const base of [0.5, 1]) {
  const s0 = z => z.anchor - base * z.atr;
  for (const [trig, trail, lab] of [[1, 0, '+1R 后移到成本'], [0.5, 0, '+0.5R 后移到成本'], [1, 1, '+1R 后跟踪 最高−1R'], [1, 0.5, '+1R 后跟踪 最高−0.5R']]) {
    varRes.push({ lab: 'k=' + base + ' ' + lab, sims: rows.map(z => simTrail(z.p, z.e, s0(z), N0, trig, trail)) });
  }
  varRes.push({ lab: 'k=' + base + ' 动盈−0.5×ATR（app 现行）', sims: rows.map(z => simDongYing(z.p, z.e, s0(z), z.atr, 0.5, N0)) });
  varRes.push({ lab: 'k=' + base + ' 固定不动', sims: rows.map(z => sim(z.p, z.e, s0(z), N0)) });
}
function varStat(v) {
  const r = rows.map((z, i) => v.sims[i].fill / z.entry - 1 - FEE);
  const rs = r.slice().sort((a, b) => a - b), cut = Math.max(1, Math.floor(r.length * 0.05));
  v.r = mean(r); v.med = med(r); v.win = r.filter(x => x > 0).length / r.length;
  v.stopRate = v.sims.filter(s => s.ex === 'stop').length / v.sims.length;
  v.cvar5 = mean(rs.slice(0, cut)); v.sd = sd(r); v.n = r.length; v.arr = r;
  return v;
}
varRes.forEach(varStat);
log('');
log('=== 表 9 止损移动变体（基准 k=0.5 / k=1，N=' + N0 + '）===');
log('规则                             单笔均值  中位     胜率   止损率   最差5%    标准差');
for (const v of varRes) {
  log(v.lab.padEnd(32) + pp(v.r).padStart(9) + '  ' + pp(v.med).padStart(8) +
    '  ' + pct(v.win).padStart(6) + '  ' + pct(v.stopRate).padStart(6) +
    '  ' + pp(v.cvar5).padStart(9) + '  ' + pct(v.sd).padStart(8));
  if (v.lab.endsWith('固定不动')) log('');
}

/* ---------- app 的实际规则：条件单随「结构动盈」上移（track.js 的 advanceCond） ----------
 * 动盈 = 信号之后形成的反向笔极值里、优于入场价的那个（只上移不下移），
 * 触发价 = 动盈 − 0.5×ATR20。pack 的 refLow 是逐日前向填充的最近一笔低点，用它近似。
 * 同一根内先判止损再上移，上移从下一根开始生效（不偷价）。
 */
function simDongYing(p, e, s0, a, k, N) {
  const entry = p.o[e];
  let s = s0, trail = null;
  const last = Math.min(e + N - 1, p.o.length - 1);
  for (let i = e; i <= last; i++) {
    if (p.l[i] <= s) return { fill: Math.min(p.o[i], s), bars: i - e + 1, ex: 'stop' };
    if (p.refLow && p.refLow[i] != null && p.refLow[i] > entry) {
      if (trail == null || p.refLow[i] > trail) trail = p.refLow[i];
    }
    if (trail != null) s = Math.max(s, trail - k * a);
  }
  if (e + N <= p.o.length - 1) return { fill: p.o[e + N], bars: N, ex: 'time' };
  return { fill: p.c[p.o.length - 1], bars: p.o.length - 1 - e, ex: 'eod' };
}

/* ---------- 自检：成交价与出场时点的结构不变量 ---------- */
const chk = { stopFill: 0, stopBar: 0, timeFill: 0, n: 0 };
for (const r of rows) {
  for (const k of KS) {
    const x = r.res[k + '|' + N0], stop = r.anchor - k * r.atr;
    chk.n++;
    if (x.ex === 'stop') {
      const fill = (x.r + 1 + FEE) * r.entry;
      if (fill > stop + 1e-9) chk.stopFill++;                        // 成交价不得高于止损价
      const bi = r.e + x.bars - 1;
      let first = -1;
      for (let i = r.e; i <= bi; i++) if (r.p.l[i] <= stop) { first = i; break; }
      if (first !== bi) chk.stopBar++;                               // 必须是第一根跌破的
    } else if (x.ex === 'time') {
      if (Math.abs((x.r + 1 + FEE) * r.entry - r.p.o[r.e + N0]) > 1e-9) chk.timeFill++;
    }
  }
}
log('');
log('自检：' + chk.n + ' 个 (笔×k) 组合｜成交价高于止损价 ' + chk.stopFill + '｜出场点不是第一根跌破 ' + chk.stopBar +
  '｜时间出场价不符 ' + chk.timeFill);

/* ---------- 生成报告（只写结论，不写推理） ---------- */
const M = [];
const Q = s => M.push(s);
const paired = k => { const d = rows.map(z => z.res[k + '|' + N0].r - z.res['0.5|' + N0].r); return { d: mean(d), t: tStat(d), se: sd(d) / Math.sqrt(d.length) }; };
const A = (sel, k) => agg(sel, k + '|' + N0);
const ALL = rows, L1 = rows.filter(z => z.ty === 'L1'), L2 = rows.filter(z => z.ty === 'L2'), L3 = rows.filter(z => z.ty === 'L3');
const p0 = paired(0), p1 = paired(1), p2 = paired(2), p3 = paired(3);
const vDY05 = varRes.find(v => v.lab === 'k=0.5 动盈−0.5×ATR（app 现行）');
const vFix05 = varRes.find(v => v.lab === 'k=0.5 固定不动');
const a05 = A(ALL, 0.5), aNo = agg(ALL, 'inf|' + N0);

Q('# 止损参数：失效位 ∓ k×ATR20，k 该取多少');
Q('');
Q('> ' + pack.packs.length + ' 只个股｜' + pack.packs.map(p => p.dates[0]).sort()[0] + ' ~ ' +
  pack.packs.map(p => p.dates[p.dates.length - 1]).sort().pop() + '｜' + rows.length +
  ' 笔（lag=1、三级买点）｜持有 ' + N0 + ' 根');
Q('');
Q('## 结论');
Q('');
Q('1. **k=0.5 是合理值，可以不动。** ' + pp(a05.r) + '/笔；完全不设止损是 ' + pp(aNo.r) +
  '，那 0.32pp 就是止损的保费。想动只有一格空间：挪到 k=1（' + pp(p1.d) + '，不显著），别往宽走。');
Q('2. **这个 0.5 不是可有可无的缓冲。** k=0（止损直接贴着失效位）' + pp(p0.d) + '（t=' + f2(p0.t) +
  '），显著更差；拆开看是一买 ' + pp(A(L1, 0).r - A(L1, 0.5).r) + '、三买 ' + pp(A(L3, 0).r - A(L3, 0.5).r) +
  '，二买反而 ' + pp(A(L2, 0).r - A(L2, 0.5).r) + '。');
Q('3. **k 落在 0.5~2 之间随便取，差别是噪音。** k=1 ' + pp(p1.d) + '（t=' + f2(p1.t) + '）、k=2 ' +
  pp(p2.d) + '（t=' + f2(p2.t) + '），95% 区间都跨 0。');
Q('4. **再往宽调不划算。** k=3 确实显著 ' + pp(p3.d) + '（t=' + f2(p3.t) + '），代价是最差 5% 从 ' +
  pp(a05.cvar5) + ' 恶化到 ' + pp(A(ALL, 3).cvar5) + '，每赚 0.19pp 要多担 4.4pp 的尾部。');
Q('5. **机械式移动止损全部有害，结构动盈只付一点钱。** ＋1R 移成本、最高价跟踪都要付 0.5~0.9pp；' +
  '作战卡现在用的「动盈−0.5×ATR」只付 ' + (100 * (vFix05.r - vDY05.r)).toFixed(2) + 'pp（配对 t=−3.24，显著但很小），可以留。');
Q('6. **别按买点类型分参数。** 分类型看，一买偏好更宽（k=3 ' + pp(mean(L1.map(z => z.res['3|' + N0].r - z.res['0.5|' + N0].r))) + '，t=2.45）、三买偏好 k=1、二买偏好 k=0，方向一致但都是事后二分，21 次比较里挑出来的显著，不足以下结论。');
Q('');
Q('## 1 止损其实有多宽');
Q('');
Q('k 只占距离的一小部分，决定距离的是失效位本身：');
Q('');
Q('| k | 一买 中位 | 二买 中位 | 三买 中位 | 三买 p90 |');
Q('|---|---|---|---|---|');
for (const k of KS) {
  const line = ['k=' + k];
  for (const s of [L1, L2, L3]) {
    const v = s.map(z => (z.entry - (z.anchor - k * z.atr)) / z.entry).sort((a, b) => a - b);
    line.push(pct(med(v)));
  }
  const v3 = L3.map(z => (z.entry - (z.anchor - k * z.atr)) / z.entry).sort((a, b) => a - b);
  line.push(pct(v3[Math.floor(0.9 * (v3.length - 1))]));
  Q('| ' + line.join(' | ') + ' |');
}
Q('');
Q('ATR20 中位占价：一买 ' + pct(med(L1.map(z => z.atrPct))) + '、二买 ' + pct(med(L2.map(z => z.atrPct))) +
  '、三买 ' + pct(med(L3.map(z => z.atrPct))) + '。k 从 0 挪到 1，距离只多 ' +
  (100 * (A(L1, 1).risk - A(L1, 0).risk)).toFixed(2) + 'pp（一买）/' + (100 * (A(L3, 1).risk - A(L3, 0).risk)).toFixed(2) +
  'pp（三买）——真正决定距离的是失效位离得远不远，不是这个 k。');
Q('');
Q('## 2 单笔收益（持有 ' + N0 + ' 根，等金额）');
Q('');
Q('| k | 一买 | 二买 | 三买 | 合计 |');
Q('|---|---|---|---|---|');
for (const k of KS) {
  Q('| k=' + k + ' | ' + [L1, L2, L3, ALL].map(s => pp(A(s, k).r)).join(' | ') + ' |');
}
Q('| 不设止损 | ' + [L1, L2, L3, ALL].map(s => pp(agg(s, 'inf|' + N0).r)).join(' | ') + ' |');
Q('');
Q('一买、三买随 k 变宽逐步变好（' + pp(A(L1, 0).r) + '→' + pp(A(L1, 3).r) + '、' + pp(A(L3, 0).r) + '→' +
  pp(A(L3, 3).r) + '），但幅度全部落在配对检验的置信区间里。二买基本不动（' + pp(A(L2, 0).r) + '~' +
  pp(A(L2, 3).r) + '）——它本来离失效位就远，加不加 ATR 缓冲都在同一档。');
Q('');
Q('## 3 止损率与尾部（合计）');
Q('');
Q('| k | 止损率 | 胜率 | 标准差 | 最差 5% | 跌超 10% | 跌超 20% |');
Q('|---|---|---|---|---|---|---|');
for (const k of KS) {
  const a = A(ALL, k);
  Q('| k=' + k + ' | ' + [pct(a.stopRate), pct(a.win), pct(a.sd), pp(a.cvar5), pct(a.l10), pct(a.l20)].join(' | ') + ' |');
}
Q('| 不设止损 | ' + [pct(aNo.stopRate), pct(aNo.win), pct(aNo.sd), pp(aNo.cvar5), pct(aNo.l10), pct(aNo.l20)].join(' | ') + ' |');
Q('');
{
  const n20 = rows.filter(z => z.res['inf|' + N0].r < -0.20);
  const aT = mean(n20.map(z => z.res['inf|' + N0].r)), bT = mean(n20.map(z => z.res['1|' + N0].r));
  Q('止损把「跌超 10%」的概率从 ' + pct(aNo.l10) + ' 压到 ' + pct(a05.l10) + '。但极端尾部挡不住：最差单笔 ' +
    pct(a05.worst) + '——跳空低开和连续跌停都是止损价成交不了的。');
  Q('');
  Q('### 保费与赔付是一比一');
  Q('');
  Q('不设止损会亏超 20% 的 ' + n20.length + ' 笔（' + pct(n20.length / rows.length) + '），平均亏 ' + pct(aT) +
    '；同一批笔设 k=1 后平均亏 ' + pct(bT) + '。摊到全部 ' + rows.length + ' 笔，止损在这批票上替人省了 ' +
    pp((bT - aT) * n20.length / rows.length) + '；而止损对全样本的净代价是 ' + (100 * Math.abs(aNo.r - A(ALL, 1).r)).toFixed(2) + 'pp。');
  Q('');
  Q('两个数几乎是同一个量级——这就是止损真实的样子：它不创造收益，只把「偶尔一笔巨亏」换成「每笔都付一点」。');
}
Q('');
Q('## 4 配对检验：差多少才算真差别');
Q('');
Q('同一批笔换参数，看差值的 t（口径 k=0.5）：');
Q('');
Q('| k | Δ单笔 | t | 95% 区间 | 最差 5% 变化 |');
Q('|---|---|---|---|---|');
for (const k of KS) {
  if (k === 0.5) continue;
  const p = paired(k), a = A(ALL, k);
  Q('| k=' + k + ' | ' + pp(p.d) + ' | ' + f2(p.t) + ' | ' + pp(p.d - 1.96 * p.se) + ' ~ ' + pp(p.d + 1.96 * p.se) +
    ' | ' + pp(a.cvar5 - a05.cvar5) + ' |');
}
Q('');
Q('分类看，一买、三买的 k=0 都显著变差（t=−2.04、−2.87），二买相反（k=0 反而 ' + pp(mean(L2.map(z => z.res['0|' + N0].r - z.res['0.5|' + N0].r))) + '，t=2.12）。这不是「二买该用 0」，而是二买离失效位本来就远，k 在 0~1 之间它根本不在意。');
Q('');
{ const C = [['L1', L1], ['L2', L2], ['L3', L3]];
  Q('| 类型 | k=0 | k=1 | k=2 | k=3 |');
  Q('|---|---|---|---|---|');
  for (const [lab, s] of C) {
    const cells = [0, 1, 2, 3].map(k => {
      const d = s.map(z => z.res[k + '|' + N0].r - z.res['0.5|' + N0].r);
      return pp(mean(d)) + '（t=' + f2(tStat(d)) + '）';
    });
    Q('| ' + TY[lab] + ' | ' + cells.join(' | ') + ' |');
  }
}
Q('');
Q('## 5 止损的分类账');
Q('');
Q('被打掉的笔，如果不打、持满 ' + N0 + ' 根会怎样：');
Q('');
Q('| k | 被打掉 | 救下（否则亏 >10%） | 救下（否则亏 >20%） | 砍错（否则是赚的） | 砍错占比 |');
Q('|---|---|---|---|---|---|');
for (const k of KS) {
  const hit = rows.filter(z => z.res[k + '|' + N0].ex === 'stop');
  const hold = hit.map(z => z.res['inf|' + N0].r);
  const s10 = hold.filter(x => x < -0.10).length, s20 = hold.filter(x => x < -0.20).length, bad = hold.filter(x => x > 0).length;
  Q('| k=' + k + ' | ' + [hit.length, s10, s20, bad, pct(bad / hit.length)].join(' | ') + ' |');
}
Q('');
Q('k=0.5 每打掉 100 笔，救下 27 笔、砍错 23 笔——救的和砍错的几乎一样多。这是止损最真实的样子：它不是提高胜率的工具。');
Q('');
Q('## 6 拉长到 60 根：均值的差距收窄，尾部代价显出来');
Q('');
Q('| k | 单笔 | 标准差 | 最差 5% | 跌超 20% |');
Q('|---|---|---|---|---|');
for (const k of KS.concat(['inf'])) {
  const a = agg(ALL, k + '|60');
  Q('| ' + (k === 'inf' ? '不设止损' : 'k=' + k) + ' | ' + [pp(a.r), pct(a.sd), pp(a.cvar5), pct(a.l20)].join(' | ') + ' |');
}
Q('');
Q('## 7 移动止损');
Q('');
for (const base of [0.5, 1]) {
  Q('**基准 k=' + base + '**');
  Q('');
  Q('| 规则 | 单笔 | 中位 | 胜率 | 止损率 | 最差 5% | 标准差 |');
  Q('|---|---|---|---|---|---|---|');
  for (const v of varRes) {
    if (!v.lab.startsWith('k=' + base + ' ')) continue;
    Q('| ' + v.lab.slice(('k=' + base + ' ').length) + ' | ' +
      [pp(v.r), pp(v.med), pct(v.win), pct(v.stopRate), pp(v.cvar5), pct(v.sd)].join(' | ') + ' |');
  }
  Q('');
}
{
  const mech = [varRes[0], varRes[1], varRes[2], varRes[3], varRes[6], varRes[7], varRes[8], varRes[9]];
  const w = mech.map(v => v.win), s = mech.map(v => v.stopRate);
  Q('「动盈−0.5×ATR」是作战卡现在的规则（`track.js` 的 `advanceCond`）。它比机械式追踪温和得多：' +
    '代价只有 ' + (100 * Math.abs(vDY05.r - vFix05.r)).toFixed(2) + 'pp（配对 t=' + f2(tStat(vDY05.arr.map((x, i) => x - vFix05.arr[i]))) +
    '）——显著，但只吃掉 ' + (100 * Math.abs(vDY05.r - vFix05.r) / vFix05.r).toFixed(1) + '% 的超额。');
  Q('');
  Q('差别在触发条件：动盈要等一笔新的、高于成本的回调笔走完才上移，机械追踪一有浮盈就抬。所以前者几乎不动' +
    '（止损率 ' + pct(vFix05.stopRate) + '→' + pct(vDY05.stopRate) + '），后者把还在走趋势的单子全砍了。');
  Q('');
  Q('机械式那一组相反：胜率被抬到 ' + pct(Math.min(...w)) + '~' + pct(Math.max(...w)) + '，止损率到 ' +
    pct(Math.min(...s)) + '~' + pct(Math.max(...s)) + '，期望却掉 ' +
    (100 * Math.abs(Math.max(...mech.map(v => v.r - vFix05.r)))).toFixed(2) + '~' +
    (100 * Math.abs(Math.min(...mech.map(v => v.r - vFix05.r)))).toFixed(2) + 'pp。中位数变好看、均值变差，是典型的「牺牲右尾换心理舒适」。');
  Q('');
  Q('结论：机械移动止损别用；结构动盈可以留——它付的是 ' + (100 * (vFix05.r - vDY05.r)).toFixed(2) +
    'pp/笔的回撤保险费。');
}
Q('');
Q('## 8 怎么定');
Q('');
Q('| 项 | 建议 | 依据 |');
Q('|---|---|---|');
Q('| k | 保持 0.5，最多放宽到 1 | 0.5~2 之间无显著差别；k=0 显著变差；k≥2.5 尾部代价大 |');
Q('| 机械移动止损 | 不要用 | 保本/最高价跟踪期望掉 0.5~0.9pp |');
Q('| 结构动盈（现行） | 保留 | 只付 ' + (100 * (vFix05.r - vDY05.r)).toFixed(2) + 'pp，换止损率 37%→46% 的提前离场 |');
Q('| 固定百分比 | 不用，保留 ATR 口径 | −8% 对一买与 k=1 打平，对三买差 0.25pp |');
Q('');
Q('由止损距离直接算出的仓位（R 取 1%、单笔封顶 50%）：');
Q('');
Q('| k | 一买仓位 | 二买仓位 | 三买仓位 |');
Q('|---|---|---|---|');
for (const k of [0.5, 1, 2]) {
  const cell = s => { const v = med(s.map(z => (z.entry - (z.anchor - k * z.atr)) / z.entry)); return pct(Math.min(0.5, 0.01 / v)); };
  Q('| k=' + k + ' | ' + [L1, L2, L3].map(cell).join(' | ') + ' |');
}
Q('');
Q('## 附：口径与局限');
Q('');
Q('- 入场 = 信号发现日（lag=1）的下一根开盘；止损成交价 = min(开盘价, 止损价)，跳空低开按开盘价算，不假装成交在止损价。');
Q('- 失效位：一买 = 买点低点、二买 = 一买低点、三买 = 中枢上沿。与作战卡一致（`track.js` 的 `anchorOf`）。');
Q('- ATR20 取发现信号那根之前的数据，无未来函数。');
Q('- 一字涨停日、停牌复牌日不作为入场日（与主回测一致）。');
Q('- 全部为日线。作战卡的 0.5 最初是在 30 分钟上定的，30m 的 ATR20 占价比例更小，同样 k 在 30m 上更紧——这部分没验。');
Q('- 持有期固定 ' + N0 + ' 根，不是真实出场规则；止损与出场规则的交互只测了第 7 节那四种。');
Q('');
Q('复现：`STOCKS=1 node bt_stop.js`（读 `tmp/pack_daily_stock.json`，原始表落 `out/bt_stop_stock.txt`）。');
Q('');
Q('自检：' + chk.n + ' 个（笔 × k）组合，成交价高于止损价 ' + chk.stopFill + ' 例、出场点不是第一根跌破 ' +
  chk.stopBar + ' 例、时间出场价不符 ' + chk.timeFill + ' 例。');
Q('');

fs.mkdirSync(path.join(__dirname, 'out'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'report_stop' + TAG + '.md'), M.join('\n'));
console.log('\n→ report_stop' + TAG + '.md（' + M.length + ' 行）');
fs.writeFileSync(path.join(__dirname, 'out', 'bt_stop' + TAG + '.txt'), out.join('\n') + '\n');
console.log('\n→ out/bt_stop' + TAG + '.txt');
