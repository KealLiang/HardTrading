/* ==========================================================================
 * diag.js —— 单仓口径诊断：共享一仓 vs 分账，各类买点被吃掉了多少
 *
 * 背景：主口径原为「同一标的全类型共享一仓」。二买在结构上紧跟一买，
 *       一买持仓期间二买信号全部作废 → 日线 250 个二买信号只成交 27 个，
 *       而且剩下的是「一买持仓已结束」之后才来的差位置（反向选择）。
 *       本脚本把每一类买点信号的去向与「若独占单仓能拿到什么」逐条算清楚。
 *
 * 产物：out/diag_<tf>.json
 * 用法：TF=daily|30|60 node diag.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const TF = process.env.TF || 'daily';
const FEE = parseFloat(process.env.FEE || '0.001');
/* 与 strict.js 保持一致：三买 R2 参照位默认 ZG（中枢上沿），ZD 仅作旧口径复现 */
const ZSREF = (process.env.ZSREF || 'zg').toLowerCase();
const TIMEOUT_DAYS = 120, LIMIT = 0.095;
const BPB = TF === 'daily' ? 1 : (TF === '30' ? 8 : 4);
const TIMEOUT_BARS = TIMEOUT_DAYS * BPB;

const packAll = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'pack_' + TF + '.json'), 'utf8'));
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
function chanExit(p, E, b1, zsZD, sells) {
  const cands = [];
  const hardEnd = Math.min(p.n - 2, E + TIMEOUT_BARS);
  if (b1 > 0) for (let i = E + 1; i <= hardEnd; i++) {
    if (p.bad[i]) continue;
    if (p.c[i] < b1) { cands.push({ idx: i + 1, pri: 1, reason: 'R1失效位' }); break; }
  }
  if (zsZD > 0) for (let i = E + 1; i <= hardEnd; i++) {
    if (p.bad[i]) continue;
    if (p.c[i] < zsZD) { cands.push({ idx: i + 1, pri: 2, reason: 'R2中枢破位' }); break; }
  }
  for (const s of sells) {
    if (s.execIdx > E) { if (s.execIdx <= hardEnd + 2) cands.push({ idx: s.execIdx, pri: 3, reason: 'R3卖' + s.level }); break; }
  }
  if (E + TIMEOUT_BARS <= p.n - 1) cands.push({ idx: E + TIMEOUT_BARS, pri: 4, reason: 'R4超时' });
  let best = null;
  for (const c of cands) {
    const ex = shiftExec(p, c.idx, E);
    if (ex < 0) continue;
    if (!best || ex < best.idx || (ex === best.idx && c.pri < best.pri)) best = { idx: ex, reason: c.reason, pri: c.pri };
  }
  return best || { idx: -1, reason: '数据不足' };
}

/* 逐类型累加器 */
const LV = {};
const acc = k => LV[k] || (LV[k] = {
  sig: 0, busyBy: {}, sharedRet: [], soloRet: [], eatenRet: [], soloReason: {}, soloHold: [], sharedHold: [],
  noexit: 0, oob: 0, limit: 0, codes: {}
});

for (const p of packAll.packs) {
  const buys = p.buy.filter(b => b.discT - b.readyK === 1);
  const sells = p.sell.map(s => ({ execIdx: s.discT + 1, level: s.level }))
    .filter(s => s.execIdx < p.n).sort((a, b) => a.execIdx - b.execIdx);

  let busyShared = -1, holder = null;
  const soloBusy = { 1: -1, 2: -1, 3: -1 };

  for (const b of buys) {
    const E = b.discT + 1, lv = b.level, tk = 'L' + lv, a = acc(tk);

    if (E >= p.n - 2) { a.oob++; a.sig++; continue; }
    if (p.bad[E]) { a.oob++; a.sig++; continue; }
    if (limitUpBlocked(p, E)) { a.limit++; a.sig++; continue; }
    a.sig++;
    a.codes[p.code] = (a.codes[p.code] || 0) + 1;

    const zsZD = b.zsZD, biHigh = b.refBiHigh;
    const b1 = lv === 1 ? b.price : (lv === 2 ? b.b1 : null);
    let zForExit = null;
    if (lv === 3) {
      if (ZSREF === 'zd') zForExit = b.zsZD;
      else if (ZSREF === 'mid') zForExit = (b.zsZG > 0 && b.zsZD > 0) ? (b.zsZG + b.zsZD) / 2 : null;
      else zForExit = b.zsZG;
    }

    /* 这笔信号在「独占单仓」下能拿到什么（与共享是否成交无关，纯参照） */
    let solo = null;
    if (E > soloBusy[lv]) {
      const ex = chanExit(p, E, b1, zForExit, sells);
      if (ex.idx > E && p.dates[ex.idx] > p.dates[E] && p.o[E] > 0 && p.o[ex.idx] > 0) {
        const ret = p.o[ex.idx] / p.o[E] - 1 - FEE;
        solo = { ret, hold: ex.idx - E, reason: ex.reason.replace(/\/.*/, '') };
        soloBusy[lv] = ex.idx;
        a.soloRet.push(ret); a.soloHold.push((ex.idx - E) / BPB);
        a.soloReason[solo.reason] = a.soloReason[solo.reason] || [];
        a.soloReason[solo.reason].push(ret);
      }
    }

    /* 共享单仓下的实际命运 */
    if (E > busyShared) {
      const ex = chanExit(p, E, b1, zForExit, sells);
      if (ex.idx < 0) { a.noexit++; }
      else if (p.dates[ex.idx] > p.dates[E] && p.o[E] > 0 && p.o[ex.idx] > 0) {
        a.sharedRet.push(p.o[ex.idx] / p.o[E] - 1 - FEE);
        a.sharedHold.push((ex.idx - E) / BPB);
        busyShared = ex.idx; holder = { tk, X: ex.idx };
      } else a.noexit++;
    } else {
      /* 被占用 → 记下「本该拿到的收益」，这就是被吃掉的样本 */
      a.busyBy[holder ? holder.tk : '?'] = (a.busyBy[holder ? holder.tk : '?'] || 0) + 1;
      if (solo) a.eatenRet.push(solo.ret);
    }
  }
}

/* ---------------------------------------------------------------- 汇总 */
const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
const med = a => { if (!a.length) return null; const b = a.slice().sort((x, y) => x - y); const m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; };
const frac = a => a.length ? a.filter(x => x > 0).length / a.length : null;

const out = { tf: TF, generatedAt: new Date().toISOString(), levels: {} };
for (const tk of ['L1', 'L2', 'L3']) {
  const a = LV[tk]; if (!a) continue;
  const reasons = {};
  for (const [k, v] of Object.entries(a.soloReason)) reasons[k] = { n: v.length, mean: mean(v) };
  out.levels[tk] = {
    signals: a.sig,
    sharedN: a.sharedRet.length, sharedMean: mean(a.sharedRet), sharedWin: frac(a.sharedRet), sharedHoldMed: med(a.sharedHold),
    busyN: a.sig - a.sharedRet.length - a.noexit - a.oob - a.limit,
    busyBy: a.busyBy,
    soloN: a.soloRet.length, soloMean: mean(a.soloRet), soloMedian: med(a.soloRet), soloWin: frac(a.soloRet), soloHoldMed: med(a.soloHold),
    soloReasons: reasons,
    eatenN: a.eatenRet.length, eatenMean: mean(a.eatenRet),
    noexit: a.noexit, oob: a.oob, limit: a.limit,
    codes: Object.keys(a.codes).length
  };
}
fs.writeFileSync(path.join(__dirname, 'out', 'diag_' + TF + '.json'), JSON.stringify(out, null, 1));

console.log('=== ' + TF + ' 单仓口径诊断 ===');
console.log('类型|信号|共享成交|共享均值|被占用|占用者(L1/L3)|独占笔数|独占均值|被吃掉样本均值');
for (const tk of ['L1', 'L2', 'L3']) {
  const d = out.levels[tk]; if (!d) continue;
  console.log(tk + '  |' + String(d.signals).padStart(4) + '|' + String(d.sharedN).padStart(6) + '|' +
    (d.sharedMean == null ? '   n/a' : (100 * d.sharedMean).toFixed(2) + '%').padStart(7) + '|' +
    String(d.busyN).padStart(5) + '|' + (d.busyBy.L1 || 0) + '/' + (d.busyBy.L3 || 0) + '        |' +
    String(d.soloN).padStart(6) + '|' + (d.soloMean == null ? '   n/a' : (100 * d.soloMean).toFixed(2) + '%').padStart(7) + '|' +
    (d.eatenMean == null ? '     n/a' : (100 * d.eatenMean).toFixed(2) + '%').padStart(8));
}
