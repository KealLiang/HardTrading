/* ==========================================================================
 * strict.js —— 严格回测：A/B/C/D 四组合
 *
 *   A 缠论入场 + 缠论出场（R1 买点失效 / R2 中枢破位 / R3 同级别卖点 / R4 超时120日）
 *   B 缠论入场 + 固定 N 日出场（N = 5/10/20）
 *   C 随机入场 + 缠论出场（全部规则，人工造参照：最近中枢ZD + 最近一笔低点）
 *   D 随机入场 + 固定 N 日出场
 *
 * 成交纪律：
 *   - 成交价一律用「触发 bar 的下一根开盘」；触发 bar = 信号首次被发现的 bar（discT）。
 *   - 入场只接受 lag = discT - readyK = 1 的买点（lag>1 是事后回填，不可交易）。
 *   - 破位用收盘确认，次日开盘卖出；卖点用 discT+1 开盘卖出。
 *   - T+1：出场日期必须晚于入场日期，否则顺延；跌停/停牌卖不出则顺延。
 *   - 涨停（开盘涨幅≥9.5%）买不进 → 跳过并计数。
 *
 * 用法：TF=daily|30|60 node strict.js [FEE=0.001]
 * 产物：out/trades_<tf>.csv（A/B 明细）, out/summary_<tf>.json, config.json
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');

const TF = process.env.TF || 'daily';
const FEE = parseFloat(process.env.FEE || '0.001');
const SUF = process.env.SUF || '';                       // 输出后缀，成本敏感性用
/* 单仓口径（主口径 = 分账）
 *   SPLIT（默认）：每类买点各占一套单仓 = 三个独立子账户。分层表每格都是该类信号的
 *                  真实表现，不会被其他类型吃掉样本。报告的分层结论一律按此读。
 *   SHARED=1     ：全类型共享一仓（单账户口径）。此时二买信号会被一买持仓大量吃掉
 *                  （日线 250 个信号只成交 27 个），且剩下的是反向选择的差样本，
 *                  分层 n 严重失真——只作「单账户实际能吃到多少」的附表，不作结论。 */
const SPLIT = process.env.SHARED !== '1';
/* 三买 R2 破位参照位（ZSREF）
 *   zg （默认）：中枢上沿 ZG。三买成交价在中枢上方，跌破 ZG 才是「突破失败回到中枢内」；
 *   mid        ：中枢中位；
 *   zd         ：中枢下沿 ZD。**这是原方案写错的值**——从买入价到 ZD 要跨过整个中枢高度
 *                再加突破溢价，等于让三买没有止损，实测 R2 破位 72 笔均值 -9.91%，
 *                且三周期出现「输家持仓 > 赢家持仓」的倒挂。保留该值仅为复现旧结果。 */
const ZSREF = (process.env.ZSREF || 'zg').toLowerCase();
const BPB = TF === 'daily' ? 1 : (TF === '30' ? 8 : 4);
const TIMEOUT_DAYS = 120, TIMEOUT_BARS = TIMEOUT_DAYS * BPB;
const NSEED = 1000, PICKS = 50;
const FIXED_N = [5, 10, 20];
const LIMIT = 0.095;
const outDir = path.join(__dirname, 'out');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

const packFile = path.join(__dirname, 'tmp', 'pack_' + TF + '.json');
if (!fs.existsSync(packFile)) { console.error('缺 ' + packFile + '，先跑 TF=' + TF + ' node scan.js'); process.exit(1); }
const packAll = JSON.parse(fs.readFileSync(packFile, 'utf8'));

/* ------------------------------------------------------------------ 成交约束 */
const prevC = (p, i) => (i > 0 ? p.c[i - 1] : null);
const limitUpBlocked = (p, i) => { const pc = prevC(p, i); return pc > 0 && p.o[i] / pc - 1 >= LIMIT; };
const limitDownBlocked = (p, i) => { const pc = prevC(p, i); return pc > 0 && p.o[i] / pc - 1 <= -LIMIT; };

function shiftExec(p, idx, entryIdx) {
  let i = Math.max(idx, entryIdx + 1);
  while (i < p.n) {
    if (p.dates[i] === p.dates[entryIdx]) { i++; continue; }
    if (p.bad[i] || limitDownBlocked(p, i)) { i++; continue; }
    return i;
  }
  return -1;
}

/* ------------------------------------------------------------------ 缠论出场 */
function chanExit(p, E, b1, zsRef, sells) {
  const cands = [];
  const hardEnd = Math.min(p.n - 2, E + TIMEOUT_BARS);

  if (b1 > 0) {
    for (let i = E + 1; i <= hardEnd; i++) {
      if (p.bad[i]) continue;
      if (p.c[i] < b1) { cands.push({ idx: i + 1, pri: 1, reason: 'R1失效位' }); break; }
    }
  }
  if (zsRef > 0) {
    for (let i = E + 1; i <= hardEnd; i++) {
      if (p.bad[i]) continue;
      if (p.c[i] < zsRef) { cands.push({ idx: i + 1, pri: 2, reason: 'R2中枢破位' }); break; }
    }
  }
  for (const s of sells) {
    if (s.execIdx > E) {
      if (s.execIdx <= hardEnd + 2) cands.push({ idx: s.execIdx, pri: 3, reason: 'R3卖' + s.level });
      break;
    }
  }
  if (E + TIMEOUT_BARS <= p.n - 1) cands.push({ idx: E + TIMEOUT_BARS, pri: 4, reason: 'R4超时' });

  let best = null;
  for (const c of cands) {
    const ex = shiftExec(p, c.idx, E);
    if (ex < 0) continue;
    if (!best || ex < best.idx || (ex === best.idx && c.pri < best.pri)) best = { idx: ex, reason: c.reason, pri: c.pri };
  }
  // 无合规出场（数据末端、持有期未满）→ 作废，不硬凑一个假出场
  return best || { idx: -1, reason: '数据不足' };
}

function fixedExit(p, E, nd) {
  const want = E + nd * BPB;
  if (want > p.n - 1) return -1;             // 持有期未满 → 作废
  return shiftExec(p, want, E);
}

/** 结构三态：先判下移，再判上移 */
function structureState(p, E, exitIdx, zsZD, biHigh) {
  if (!(zsZD > 0) && !(biHigh > 0)) return '未知';
  if (zsZD > 0) for (let i = E; i <= exitIdx; i++) if (!p.bad[i] && p.c[i] < zsZD) return '下移';
  if (biHigh > 0) for (let i = E; i <= exitIdx; i++) if (p.h[i] > biHigh) return '上移';
  return '震荡';
}

/* ------------------------------------------------------------------ 累加器 */
function newAcc() { return { ret: [], hold: [], reasons: {}, state: {}, trades: [], curves: [], seedMeans: [] }; }
const ACC = {};                                   // 'A|L1' / 'B10|ALL' / 'C|RND' / 'D5|RND'
const accOf = k => ACC[k] || (ACC[k] = newAcc());

function record(k, ret, holdDays, reason, st, trade) {
  const a = accOf(k);
  a.ret.push(ret); a.hold.push(holdDays);
  a.reasons[reason] = a.reasons[reason] || []; a.reasons[reason].push(ret);
  a.state[st] = (a.state[st] || 0) + 1;
  if (trade) a.trades.push(trade);
}

function makeTrade(p, E, X, reason, combo, type, st) {
  if (!(X > E)) return null;                                  // 出场必须在入场之后
  if (p.dates[X] <= p.dates[E]) return null;                  // T+1 硬约束：不得同日出场
  const ep = p.o[E], xp = p.o[X];
  if (!(ep > 0) || !(xp > 0)) return null;
  const ret = xp / ep - 1 - FEE;
  if (!isFinite(ret) || ret <= -1) return null;
  let hi = -Infinity, lo = Infinity;
  for (let i = E; i <= X; i++) { if (p.h[i] > hi) hi = p.h[i]; if (p.l[i] < lo) lo = p.l[i]; }
  const atr = p.atr[E];
  return {
    code: p.code, tf: TF, type, combo,
    entry_time: p.dates[E], entry_price: +ep.toFixed(4),
    exit_time: p.dates[X], exit_price: +xp.toFixed(4),
    exit_reason: reason, hold_bars: X - E,
    hold_days: +((X - E) / BPB).toFixed(2),
    ret_net: ret,
    mfe_atr: atr > 0 ? +((hi - ep) / atr).toFixed(2) : null,
    mae_atr: atr > 0 ? +((ep - lo) / atr).toFixed(2) : null,
    structure_state: st,
    entryIdx: E, exitIdx: X
  };
}

function curveOf(trades) {
  const ts = trades.slice().sort((a, b) => a.entryIdx - b.entryIdx);
  if (ts.length < 3) return null;
  let eq = 1, peak = 1, mdd = 0, hold = 0, span = 0;
  for (const t of ts) { eq *= 1 + t.ret_net; peak = Math.max(peak, eq); mdd = Math.max(mdd, 1 - eq / peak); hold += t.hold_bars; }
  span = ts[ts.length - 1].exitIdx - ts[0].entryIdx;
  const years = (new Date(ts[ts.length - 1].exit_time) - new Date(ts[0].entry_time)) / 86400000 / 365.25;
  if (!(years > 0.5)) return null;
  return { cagr: Math.pow(eq, 1 / years) - 1, mdd, exposure: span > 0 ? hold / span : null };
}

/* ------------------------------------------------------------------ 主循环 */
const stats = { signals: 0, skippedLimitUp: 0, busyA: 0, busyB: {}, skippedEnd: 0, lagDropped: 0, noExit: 0,
  busyAByType: { L1: 0, L2: 0, L3: 0 }, split: SPLIT, zsref: ZSREF, zsRefMissing: 0 };
for (const nd of FIXED_N) stats.busyB[nd] = 0;
const abTrades = [];
const busyGet = (o, k) => (o[k] === undefined ? -1 : o[k]);

for (const p of packAll.packs) {
  const buys = p.buy.filter(b => b.discT - b.readyK === 1);
  stats.lagDropped += p.buy.length - buys.length;
  const sells = p.sell.map(s => ({ execIdx: s.discT + 1, level: s.level }))
    .filter(s => s.execIdx < p.n).sort((a, b) => a.execIdx - b.execIdx);

  /* --- A / B --- */
  let busyA = {}; const busyB = { 5: {}, 10: {}, 20: {} };
  const perKey = {};                       // 'A|L1' / 'B10|ALL' … → 该标的的成交序列
  const kk = (cb, ty) => cb + '|' + ty;
  for (const b of buys) {
    const E = b.discT + 1;
    if (E >= p.n - 2) { stats.skippedEnd++; continue; }
    if (p.bad[E]) continue;
    if (limitUpBlocked(p, E)) { stats.skippedLimitUp++; continue; }
    stats.signals++;
    const zsZD = b.zsZD, biHigh = b.refBiHigh;
    /* 三买 R2 参照位：默认 ZG（中枢上沿）；mid/zd 仅作敏感性对照 */
    let zsRefL3 = null;
    if (b.level === 3) {
      if (ZSREF === 'zd') zsRefL3 = b.zsZD;
      else if (ZSREF === 'mid') zsRefL3 = (b.zsZG > 0 && b.zsZD > 0) ? (b.zsZG + b.zsZD) / 2 : null;
      else zsRefL3 = b.zsZG;
    }
    if (b.level === 3 && !(zsRefL3 > 0)) stats.zsRefMissing++;
    const b1 = b.level === 1 ? b.price : (b.level === 2 ? b.b1 : null);
    const tk = 'L' + b.level;
    const bk = SPLIT ? tk : 'ALL';            // 单仓归属键：独占模式按类型分开

    if (E > busyGet(busyA, bk)) {
      const ex = chanExit(p, E, b1, zsRefL3, sells);
      if (ex.idx < 0) { stats.noExit++; }
      else {
        const st = structureState(p, E, ex.idx, zsZD, biHigh);
        const t = makeTrade(p, E, ex.idx, ex.reason, 'A', tk, st);
        if (t) {
          const rsn = ex.reason.replace(/\/.*/, '');
          record(kk('A', tk), t.ret_net, t.hold_days, rsn, st, t);
          record(kk('A', 'ALL'), t.ret_net, t.hold_days, rsn, st, null);
          (perKey[kk('A', tk)] = perKey[kk('A', tk)] || []).push(t);
          /* 分账模式下同一标的可同时持有三类仓位，'ALL' 序列内部重叠，
           * 连乘求复利不成立（会得到与单笔均值矛盾的曲线）→ 不生成 ALL 曲线 */
          if (!SPLIT) (perKey[kk('A', 'ALL')] = perKey[kk('A', 'ALL')] || []).push(t);
          abTrades.push(t); busyA[bk] = ex.idx;
        } else stats.noExit++;
      }
    } else { stats.busyA++; stats.busyAByType[tk]++; }

    for (const nd of FIXED_N) {
      const key = 'B' + nd;
      if (E <= busyGet(busyB[nd], bk)) { stats.busyB[nd]++; continue; }
      const X = fixedExit(p, E, nd);
      const st = structureState(p, E, X, zsZD, biHigh);
      const t = makeTrade(p, E, X, 'FIX' + nd, key, tk, st);
      if (t) {
        record(kk(key, tk), t.ret_net, t.hold_days, 'FIX' + nd, st, t);
        record(kk(key, 'ALL'), t.ret_net, t.hold_days, 'FIX' + nd, st, null);
        (perKey[kk(key, tk)] = perKey[kk(key, tk)] || []).push(t);
        if (!SPLIT) (perKey[kk(key, 'ALL')] = perKey[kk(key, 'ALL')] || []).push(t);
        abTrades.push(t); busyB[nd][bk] = X;
      }
    }
  }
  for (const key of Object.keys(perKey)) {
    const c = curveOf(perKey[key]);
    if (c) accOf(key).curves.push(c);
  }

  /* --- C / D（流式聚合，不落明细） --- */
  const pool = [];
  for (let i = packAll.warmup + 1; i < p.n - 2; i++) if (!p.bad[i] && p.o[i] > 0) pool.push(i);
  if (!pool.length) continue;

  for (let seed = 0; seed < NSEED; seed++) {
    const rng = L.makeRng(L.hashSeed(p.code) + seed * 7919 + (TF === 'daily' ? 1 : parseInt(TF, 10)));
    const picks = [];
    for (let k = 0; k < PICKS; k++) picks.push(pool[Math.floor(rng() * pool.length)]);
    picks.sort((a, b) => a - b);
    operations: {
      let busyC = -1; const busyD = { 5: -1, 10: -1, 20: -1 };
      const chainC = [], chainD = { 5: [], 10: [], 20: [] };
      for (const R of picks) {
        const E = R + 1;
        if (E >= p.n - 2 || limitUpBlocked(p, E)) continue;
        const zsZD = p.refZD[R], b1 = p.refLow[R], biHigh = p.refHigh[R];
        if (E > busyC) {
          const ex = chanExit(p, E, b1, zsZD, sells);
          const st = structureState(p, E, ex.idx, zsZD, biHigh);
          const t = makeTrade(p, E, ex.idx, ex.reason, 'C', 'RND', st);
          if (t) { record('C|RND', t.ret_net, t.hold_days, ex.reason.replace(/\/.*/, ''), st, null); chainC.push(t); busyC = ex.idx; }
        }
        for (const nd of FIXED_N) {
          if (E <= busyD[nd]) continue;
          const X = fixedExit(p, E, nd);
          const st = structureState(p, E, X, zsZD, biHigh);
          const t = makeTrade(p, E, X, 'FIX' + nd, 'D' + nd, 'RND', st);
          if (t) { record('D' + nd + '|RND', t.ret_net, t.hold_days, 'FIX' + nd, st, null); chainD[nd].push(t); busyD[nd] = X; }
        }
      }
      const cc = curveOf(chainC);
      if (cc) accOf('C|RND').curves.push(cc);
      if (chainC.length) accOf('C|RND').seedMeans.push(L.mean(chainC.map(t => t.ret_net)));
      for (const nd of FIXED_N) {
        const cd = curveOf(chainD[nd]); if (cd) accOf('D' + nd + '|RND').curves.push(cd);
        if (chainD[nd].length) accOf('D' + nd + '|RND').seedMeans.push(L.mean(chainD[nd].map(t => t.ret_net)));
      }
    }
  }
}

/* ------------------------------------------------------------------ BM / BMED：持有期匹配基准
 * 审计指出的方法学问题：A 与 B20 的持仓长度根本不同（30m A 中位 1.5 日 vs B20 的 20 日），
 * 单笔均值差里混着「持有期长度」带来的 beta——窗口期内等权买入持有为负，拿得久自然输。
 * 所以 A 优于 B20 不能归因于「出场规则更聪明」。公平比法两种：
 *   BM  ：同一入场点，持有期从 A 自身该类型的持仓 bar 分布中随机抽，出场取该 bar 开盘；
 *         每笔抽 BM_DRAWS 次取平均（消除单次抽样噪声），再与 A 逐笔配对求差。
 *   BMED：同一入场点，持有期固定为 A 该类的中位持仓（"同长度固定持有"）。
 * 若 A − BM ≈ 0，说明 A 的贡献只是"选了一个合适的持有期长度"，出场时点本身没有信息。
 */
const packByCode = new Map(packAll.packs.map(p => [p.code, p]));
const holdPool = { L1: [], L2: [], L3: [] };
for (const t of abTrades) if (t.combo === 'A' && holdPool[t.type]) holdPool[t.type].push(t.hold_bars);
const BM_DRAWS = 100;
const bmAcc = {};
for (const ty of ['L1', 'L2', 'L3']) bmAcc[ty] = { a: [], bm: [], bmed: [], hmed: 0 };
for (const t of abTrades) {
  if (t.combo !== 'A') continue;
  const pool = holdPool[t.type];
  if (!pool || !pool.length) continue;
  const p = packByCode.get(t.code); if (!p) continue;
  const hmed = Math.max(1, Math.round(L.median(pool)));
  const rng = L.makeRng(L.hashSeed(t.code) * 31 + t.entryIdx * 17 + 7);
  let sum = 0, cnt = 0;
  for (let k = 0; k < BM_DRAWS; k++) {
    const h = pool[Math.floor(rng() * pool.length)];
    const x = shiftExec(p, t.entryIdx + h, t.entryIdx);
    if (x < 0) continue;
    const r = p.o[x] / p.o[t.entryIdx] - 1 - FEE;
    if (!isFinite(r) || r <= -1) continue;
    sum += r; cnt++;
  }
  const xm = shiftExec(p, t.entryIdx + hmed, t.entryIdx);
  if (cnt < BM_DRAWS * 0.5 || xm < 0) continue;
  const rmed = p.o[xm] / p.o[t.entryIdx] - 1 - FEE;
  if (!isFinite(rmed) || rmed <= -1) continue;
  const o = bmAcc[t.type];
  o.a.push(t.ret_net); o.bm.push(sum / cnt); o.bmed.push(rmed); o.hmed = hmed;
}
function pairedStat(a, b) {
  const n = a.length;
  if (n < 20) return { n };
  const d = a.map((x, i) => x - b[i]);
  const m = L.mean(d), s = L.sd(d);
  return {
    n, meanA: L.mean(a), meanBM: L.mean(b), meanBMED: null,
    d: m, t: s > 0 ? m / (s / Math.sqrt(n)) : null,
    posShare: d.filter(x => x > 0).length / n, sd: s
  };
}
const bmOut = { byType: {}, hmedByType: {} };
{
  const allA = [], allBM = [], allMED = [];
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = bmAcc[ty];
    if (o.a.length >= 20) {
      const dd = o.a.map((x, i) => x - o.bmed[i]);
      const mm = L.mean(dd), ss = L.sd(dd);
      bmOut.byType[ty] = pairedStat(o.a, o.bm);
      bmOut.byType[ty].meanBMED = L.mean(o.bmed);
      bmOut.byType[ty].dMED = mm;
      bmOut.byType[ty].tMED = ss > 0 ? mm / (ss / Math.sqrt(dd.length)) : null;
      bmOut.hmedByType[ty] = o.hmed;
    }
    allA.push(...o.a); allBM.push(...o.bm); allMED.push(...o.bmed);
  }
  const all = pairedStat(allA, allBM);
  const dd = allA.map((x, i) => x - allMED[i]);
  const mm = L.mean(dd), ss = L.sd(dd);
  all.meanBMED = L.mean(allMED);
  all.dMED = mm; all.tMED = ss > 0 ? mm / (ss / Math.sqrt(dd.length)) : null;
  bmOut.ALL = all;
}
const bmSummary = bmOut;

/* ------------------------------------------------------------------ 统计 */
const maxOf = a => { let m = -Infinity; for (const x of a) if (x > m) m = x; return m; };
const minOf = a => { let m = Infinity; for (const x of a) if (x < m) m = x; return m; };
function agg(a) {
  const rs = a.ret;
  if (!rs.length) return { n: 0 };
  const wins = rs.filter(r => r > 0), losses = rs.filter(r => r <= 0);
  const wH = [], lH = [];
  for (let i = 0; i < rs.length; i++) (rs[i] > 0 ? wH : lH).push(a.hold[i]);
  const reasons = {};
  for (const [k, v] of Object.entries(a.reasons)) reasons[k] = { n: v.length, mean: L.mean(v), share: v.length / rs.length };
  /* 收益集中度：前 5 笔贡献占总（净）收益的比例。>50% 说明结论由极少数交易决定。 */
  const sorted = rs.slice().sort((x, y) => y - x);
  const totalSum = rs.reduce((s, x) => s + x, 0);
  const top5 = sorted.slice(0, 5).reduce((s, x) => s + x, 0);
  return {
    n: rs.length, mean: L.mean(rs), median: L.median(rs),
    win: wins.length / rs.length,
    pl: (wins.length && losses.length) ? L.mean(wins) / Math.abs(L.mean(losses)) : null,
    holdMed: L.median(a.hold), holdMax: maxOf(a.hold),
    wHoldMed: L.median(wH), lHoldMed: L.median(lH),
    q05: L.quantile(rs, 0.05), maxLoss: minOf(rs),
    top5Sum: top5, totalSum, top5Share: totalSum !== 0 ? top5 / totalSum : null,
    reasons, state: a.state,
    seedN: a.seedMeans.length,
    seedMean: a.seedMeans.length ? L.mean(a.seedMeans) : null,
    seedSd: a.seedMeans.length > 1 ? L.sd(a.seedMeans) : null,
    cagr: L.mean(a.curves.map(c => c.cagr)),
    mdd: L.mean(a.curves.map(c => c.mdd)),
    exposure: L.mean(a.curves.map(c => c.exposure)),
    curveN: a.curves.length
  };
}

const summary = { tf: TF, fee: FEE, generatedAt: new Date().toISOString(), stats, cells: [], tests: [], bm: bmSummary };
const TYPES = ['L1', 'L2', 'L3', 'ALL'];
for (const ty of TYPES) for (const cb of ['A', 'B5', 'B10', 'B20']) {
  const a = ACC[cb + '|' + ty];
  if (a) { const s = agg(a); summary.cells.push({ tf: TF, type: ty, combo: cb, ...s }); }
}
for (const cb of ['C', 'D5', 'D10', 'D20']) {
  const a = ACC[cb + '|RND'];
  if (a) { const s = agg(a); summary.cells.push({ tf: TF, type: 'RND', combo: cb, ...s }); }
}

const retOf = k => (ACC[k] ? ACC[k].ret : []);
for (const ty of TYPES) {
  const A = retOf('A|' + ty), B10 = retOf('B10|' + ty);
  if (!A.length || !B10.length) continue;
  const row = { type: ty, A_vs_B10: { d: L.mean(A) - L.mean(B10), t: L.welchT(A, B10) } };
  for (const nd of FIXED_N) {
    const B = retOf('B' + nd + '|' + ty);
    if (B.length) row['A_vs_B' + nd] = { d: L.mean(A) - L.mean(B), t: L.welchT(A, B) };
  }
  summary.tests.push(row);
}
const Aall = retOf('A|ALL'), Call = retOf('C|RND'), B10all = retOf('B10|ALL'), D10all = retOf('D10|RND');
summary.decomp = {
  A: L.mean(Aall), B10: L.mean(B10all), C: L.mean(Call), D10: L.mean(D10all),
  exitContribution: L.mean(Aall) - L.mean(B10all),
  entryContribution: L.mean(Aall) - L.mean(Call),
  interaction: (L.mean(Aall) - L.mean(B10all)) - (L.mean(Call) - L.mean(D10all)),
  t_A_vs_C: L.welchT(Aall, Call),
  t_A_vs_B10: L.welchT(Aall, B10all),
  t_A_vs_D10: L.welchT(Aall, D10all)
};

/* ------------------------------------------------------------------ 落盘 */
function csv(rows, cols) {
  const esc = v => v == null ? '' : (typeof v === 'string' && /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : String(v));
  return [cols.join(',')].concat(rows.map(r => cols.map(c => esc(r[c])).join(','))).join('\n');
}
const tradeCols = ['code', 'tf', 'type', 'combo', 'entry_time', 'entry_price', 'exit_time', 'exit_price',
  'exit_reason', 'hold_bars', 'hold_days', 'ret_net', 'mfe_atr', 'mae_atr', 'structure_state',
  'entryIdx', 'exitIdx'];
fs.writeFileSync(path.join(outDir, 'trades_' + TF + SUF + '.csv'), csv(abTrades, tradeCols));
fs.writeFileSync(path.join(outDir, 'summary_' + TF + SUF + '.json'), JSON.stringify(summary, null, 1));

const cfg = {
  engine: 'D:/Trading/plugins/chanlens/core/chan.js',
  chanDefaults: Chan.DEFAULTS,
  tf: TF, fee: FEE, fixedN: FIXED_N, timeoutDays: TIMEOUT_DAYS,
  singlePosition: SPLIT ? '按买点类型分账（L1/L2/L3 各一套单仓）' : '全类型共享一仓（单账户口径）',
  barsPerDay: BPB, warmup: packAll.warmup, nseed: NSEED, picksPerSeed: PICKS,
  limitThreshold: LIMIT,
  entryRule: '买点首次发现bar(discT)下一根开盘；只接受 lag=discT-readyK=1',
  exitRule: 'R1 收盘跌破买点失效位→次日开盘 / R2 收盘跌破入场时中枢' + ZSREF.toUpperCase() + '(仅三买)→次日开盘 / R3 同级别卖点确认(discT)次日开盘 / R4 120交易日超时',
  zsRefL3: ZSREF,
  randomEntry: '随机bar R 当确认bar，R+1开盘入场；参照位取 R bar 快照',
  note: '参照位均为发现时刻快照，不含事后极值；C/D 1000次重抽仅聚合不落明细'
};
fs.writeFileSync(path.join(__dirname, 'config.json'), JSON.stringify(cfg, null, 2));

/* ------------------------------------------------------------------ 控制台 */
console.log('=== ' + TF + ' 严格回测（双边费 ' + (FEE * 100).toFixed(1) + '%）' + (SPLIT ? ' [分账单仓]' : ' [共享单仓]') + ' ===');
console.log('可交易信号 ' + stats.signals + ' | 涨停跳过 ' + stats.skippedLimitUp + ' | A持仓占用跳过 ' + stats.busyA +
  '（一买 ' + stats.busyAByType.L1 + ' / 二买 ' + stats.busyAByType.L2 + ' / 三买 ' + stats.busyAByType.L3 + '）' +
  ' | 越界 ' + stats.skippedEnd + ' | lag>1 剔除 ' + stats.lagDropped + ' | 无合规出场作废 ' + stats.noExit);
console.log('\n类型|组合|   n | 单笔均值|  中位 | 胜率  |盈亏比|持中位|赢/输持中位| 年化  | 回撤 | 占用');
console.log('-'.repeat(98));
for (const c of summary.cells) {
  console.log(c.type.padEnd(4) + '|' + c.combo.padEnd(4) + '|' + String(c.n).padStart(5) + '|' +
    L.pc(c.mean).padStart(8) + '|' + L.pc(c.median).padStart(7) + '|' + L.pc(c.win).padStart(6) + '|' +
    L.f2(c.pl).padStart(5) + '|' + L.f1(c.holdMed).padStart(5) + '|' +
    (L.f1(c.wHoldMed) + '/' + L.f1(c.lHoldMed)).padStart(9) + '|' + L.pc(c.cagr).padStart(7) + '|' +
    L.pc(c.mdd).padStart(6) + '|' + L.pc(c.exposure).padStart(6));
}
console.log('\n=== 分类型 A vs B（单笔均值差）===');
for (const t of summary.tests) {
  const cells = FIXED_N.map(nd => (t['A_vs_B' + nd] ? 'B' + nd + ' ' + L.pp(t['A_vs_B' + nd].d) + '(t=' + L.f2(t['A_vs_B' + nd].t) + ')' : '')).filter(Boolean);
  console.log(t.type.padEnd(4) + ' ' + cells.join('  '));
}
console.log('\n=== 持有期匹配基准（配对：同一入场点）===');
for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
  const b = ty === 'ALL' ? summary.bm.ALL : summary.bm.byType[ty];
  if (!b || !b.n) continue;
  console.log(ty.padEnd(4) + ' n=' + String(b.n).padStart(4) +
    '  A ' + L.pc(b.meanA) + ' | BM随机时点 ' + L.pc(b.meanBM) + '（差 ' + L.pp(b.d) + ' t=' + L.f2(b.t) + '）' +
    ' | BMED同长度 ' + L.pc(b.meanBMED) + '（差 ' + L.pp(b.dMED) + ' t=' + L.f2(b.tMED) + '）');
}
console.log('\n=== 2×2 分解（单笔均值）===');const d = summary.decomp;
console.log('A 完整循环 ' + L.pc(d.A) + ' | B10 只入场 ' + L.pc(d.B10) + ' | C 只出场 ' + L.pc(d.C) + ' | D10 纯基准 ' + L.pc(d.D10));
console.log('出场贡献 A−B10 = ' + L.pp(d.exitContribution) + ' (t=' + L.f2(d.t_A_vs_B10) + ')');
console.log('入场贡献 A−C   = ' + L.pp(d.entryContribution) + ' (t=' + L.f2(d.t_A_vs_C) + ')');
console.log('交互项         = ' + L.pp(d.interaction) + '   (A−D10 t=' + L.f2(d.t_A_vs_D10) + ')');
