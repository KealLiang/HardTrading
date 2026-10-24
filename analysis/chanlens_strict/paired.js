/* ==========================================================================
 * paired.js —— A vs B 配对检验（同一入场点，只换出场规则）
 *
 * 动机：A 与 B_N 各自单仓、各自跳过不同信号，交易集合不同（A 643 vs B10 680）。
 *      原来的 A−B 均值差混入了"样本不同"的效应。这里只保留 A 与 B_N
 *      都实际成交的入场点（同 code + 同 entryIdx），做配对差检验：
 *         d_i = retA_i − retB_i   （同一次入场，仅出场规则不同）
 *      d 的均值即纯出场规则贡献，t = mean(d)/(sd(d)/√n)（配对 t）。
 *
 * 用法：node paired.js [daily|30|60]
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const TF = process.argv[2] || 'daily';
const file = path.join(__dirname, 'out', 'trades_' + TF + '.csv');
if (!fs.existsSync(file)) { console.error('缺 ' + file); process.exit(1); }

const lines = fs.readFileSync(file, 'utf8').split('\n').filter(x => x.trim());
const head = lines[0].split(',');
const rows = lines.slice(1).map(l => {
  const c = l.split(',');
  const o = {}; head.forEach((k, i) => o[k] = c[i]); return o;
});

function key(r) { return r.code + '@' + r.entryIdx; }
function bucket(combo, type) {
  const m = new Map();
  for (const r of rows) {
    if (r.combo !== combo) continue;
    if (type && type !== 'ALL' && r.type !== type) continue;   // ALL = 不按买点类型过滤
    m.set(key(r), r);
  }
  return m;
}

function pairedT(d) {
  const n = d.length;
  if (n < 3) return { n, mean: null, t: null, posShare: null };
  const m = L.mean(d);
  const s = L.sd(d);
  return { n, mean: m, t: s ? m / (s / Math.sqrt(n)) : null, posShare: d.filter(x => x > 0).length / n };
}

const combos = ['B5', 'B10', 'B20'];
const types = ['ALL', 'L1', 'L2', 'L3'];
const out = [];
for (const ty of types) {
  const A = bucket('A', ty);
  for (const cb of combos) {
    const B = bucket(cb, ty);
    const d = [], holdA = [], holdB = [];
    for (const [k, ra] of A) {
      const rb = B.get(k);
      if (!rb) continue;
      d.push(+ra.ret_net - +rb.ret_net);
      holdA.push(+ra.hold_bars); holdB.push(+rb.hold_bars);
    }
    const s = pairedT(d);
    out.push({
      type: ty, combo: cb, nA: A.size, nB: B.size, nPair: s.n,
      meanA: s.n ? L.mean([...A.values()].filter(r => B.has(key(r))).map(r => +r.ret_net)) : null,
      meanB: s.n ? L.mean([...B.values()].filter(r => A.has(key(r))).map(r => +r.ret_net)) : null,
      d: s.mean, t: s.t, posShare: s.posShare,
      holdA: s.n ? L.median(holdA) : null, holdB: s.n ? L.median(holdB) : null
    });
  }
}

console.log('=== A vs B 配对检验（' + TF + '，同一入场点只换出场规则）===');
console.log('类型| 对比 | A笔数| B笔数| 配对数|A均值  |B均值  | 配对差 | 配对t | 差>0占比 |A持中|B持中');
console.log('-'.repeat(96));
for (const o of out) {
  if (!o.nPair) continue;
  console.log(o.type.padEnd(4) + '|A vs ' + o.combo.padEnd(4) + '|' +
    String(o.nA).padStart(5) + '|' + String(o.nB).padStart(5) + '|' + String(o.nPair).padStart(6) + '|' +
    L.pc(o.meanA).padStart(7) + '|' + L.pc(o.meanB).padStart(7) + '|' +
    L.pp(o.d).padStart(7) + '|' + L.f2(o.t).padStart(6) + '|' +
    L.pc(o.posShare).padStart(8) + '|' + L.f1(o.holdA).padStart(5) + '|' + L.f1(o.holdB).padStart(5));
}
console.log('\n读法：配对差 = 同一入场点上「缠论出场 − 固定出场」的单笔收益差；');
console.log('      配对t 衡量这个差是否稳定（|t|<2 视为测不出差异）；差>0占比为逐笔胜出比例。');
fs.writeFileSync(path.join(__dirname, 'out', 'paired_' + TF + '.json'), JSON.stringify(out, null, 1));
