/* ==========================================================================
 * verify.js —— A 组独立复核：不复用 strict.js / scan.js 的任何算价逻辑
 *   1) 每笔 entry_price / exit_price 是否等于原始 CSV 对应日开盘价
 *   2) ret_net 是否等于 exit/entry - 1 - FEE
 *   3) T+1：exit 日期必须晚于 entry 日期
 *   4) 持仓不重叠（同一标的、按入场索引）
 *   5) 入场日是否 = 买点 discT + 1，且 lag=1（回 pack_daily.json 核）
 *   6) 复利合法性：不重叠 → curveOf 的连乘成立
 *   7) 结构态"下移"是否入场即成立（描述字段失真检查）
 * 用法：node verify.js [daily|30|60]
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const TF = process.argv[2] || 'daily';
const FEE = 0.001;
const BPB = TF === 'daily' ? 1 : (TF === '30' ? 8 : 4);

const csvFile = path.join(__dirname, 'out', 'trades_' + TF + '.csv');
const packFile = path.join(__dirname, 'tmp', 'pack_' + TF + '.json');
if (!fs.existsSync(csvFile)) { console.error('缺 ' + csvFile); process.exit(1); }

/* 原始 K 线：直接按 TF 选目录，不经过 lib 的默认分支 */
function rawKs(code) {
  if (TF === 'daily') return L.loadDaily(code);
  if (TF === '30') return L.load30(code);
  return L.load60(code) || L.to60(L.load30(code));
}

const lines = fs.readFileSync(csvFile, 'utf8').split('\n').filter(x => x.trim());
const head = lines[0].split(',');
const rows = lines.slice(1).map(l => {
  const c = l.split(',');
  const o = {}; head.forEach((k, i) => o[k] = c[i]); return o;
}).filter(r => r.combo === 'A');

const pack = JSON.parse(fs.readFileSync(packFile, 'utf8'));
const packByCode = new Map(pack.packs.map(p => [p.code, p]));

let nCheck = 0;
const err = {
  priceMismatch: [], retMismatch: [], t1Violation: [], overlap: [],
  entryNotNext: [], lagNot1: [], badBar: [], noPack: []
};
const perCode = new Map();

for (const r of rows) {
  const code = r.code;
  const ks = rawKs(code);
  // 低级别同日多根 bar：用 CSV 落盘的 bar 索引定位（strict.js 已导出 entryIdx/exitIdx）
  const eIdx = +r.entryIdx, xIdx = +r.exitIdx;
  nCheck++;
  if (!(eIdx >= 0 && xIdx > eIdx && xIdx < ks.length)) { err.badBar.push(code + ' e=' + eIdx + ' x=' + xIdx); continue; }
  if (ks[eIdx].date !== r.entry_time) { err.badBar.push(code + ' 索引与日期不符 e=' + eIdx + ' ' + ks[eIdx].t + ' vs ' + r.entry_time); continue; }
  if (ks[xIdx].date !== r.exit_time) { err.badBar.push(code + ' 索引与日期不符 x=' + xIdx + ' ' + ks[xIdx].t + ' vs ' + r.exit_time); continue; }

  const ep = ks[eIdx].o, xp = ks[xIdx].o;
  // 1) 价格
  if (Math.abs(ep - +r.entry_price) > 1e-6) err.priceMismatch.push(code + ' 入 ' + r.entry_time + ' csv=' + r.entry_price + ' raw=' + ep);
  if (Math.abs(xp - +r.exit_price) > 1e-6) err.priceMismatch.push(code + ' 出 ' + r.exit_time + ' csv=' + r.exit_price + ' raw=' + xp);
  // 2) 收益
  const ret = xp / ep - 1 - FEE;
  if (Math.abs(ret - +r.ret_net) > 1e-9) err.retMismatch.push(code + ' csv=' + r.ret_net + ' calc=' + ret);
  // 3) T+1
  if (ks[xIdx].date <= ks[eIdx].date) err.t1Violation.push(code + ' ' + r.entry_time + '→' + r.exit_time);
  // 4) 持仓不重叠（主口径为分账单仓：每类买点一套资金，故按 code + 类型 分组检查）
  const gkey = code + '|' + r.type;
  if (!perCode.has(gkey)) perCode.set(gkey, []);
  perCode.get(gkey).push({ e: eIdx, x: xIdx, t: r.entry_time });
  // 5) 入场 = 买点 discT+1 且 lag=1
  /* 分账后同一 bar 可能同时有一买与二买两个买点（各自独立成交），
   * 故必须按 type 一起匹配，否则会把第二笔归到第一个买点的类型上 */
  const p = packByCode.get(code);
  if (!p) { err.noPack.push(code); continue; }
  const b = p.buy.find(q => q.discT + 1 === eIdx && q.discT - q.readyK === 1 && ('L' + q.level) === r.type);
  if (!b) {
    const any = p.buy.find(q => q.discT + 1 === eIdx && ('L' + q.level) === r.type);
    if (any) err.lagNot1.push(code + ' ' + r.entry_time + ' ' + r.type + ' 该日买点 lag>1');
    else err.entryNotNext.push(code + ' ' + r.entry_time + ' ' + r.type);
  }
}

// 4) 重叠检查（每标的按入场排序，前一笔出场必须 <= 下一笔入场）
for (const [code, ts] of perCode) {
  ts.sort((a, b) => a.e - b.e);
  for (let i = 1; i < ts.length; i++) {
    if (ts[i].e <= ts[i - 1].x) err.overlap.push(code + ' ' + ts[i - 1].t + '(' + ts[i - 1].x + ') → ' + ts[i].t + '(' + ts[i].e + ')');
  }
}

/* 7) 结构态失真检查：入场时价格是否已在中枢 ZD 下方（按买点类别拆） */
let stCheck = { total: 0, alreadyBelow: 0, byLevel: {} };
for (const r of rows) {
  const p = packByCode.get(r.code); if (!p) continue;
  const ks = rawKs(r.code);
  const ix = +r.entryIdx;
  const b = p.buy.find(q => q.discT + 1 === ix && q.discT - q.readyK === 1 && ('L' + q.level) === r.type);
  if (!b) continue;
  stCheck.total++;
  const below = b.zsZD > 0 && ks[ix].o < b.zsZD;
  if (below) stCheck.alreadyBelow++;
  const L4 = 'L' + b.level;
  stCheck.byLevel[L4] = stCheck.byLevel[L4] || [0, 0];
  stCheck.byLevel[L4][0] += below ? 1 : 0;
  stCheck.byLevel[L4][1] += 1;
}

const fmt = a => a.length ? a.slice(0, 5).join('\n    ') + (a.length > 5 ? '\n    ...共 ' + a.length + ' 条' : '') : '无';
console.log('=== A 组独立复核（' + TF + '）===');
console.log('核对笔数 ' + nCheck + '（分账口径下三类买点的成交合计）');
console.log('1) 入场/出场价与原始CSV开盘价不符: ' + err.priceMismatch.length + '\n    ' + fmt(err.priceMismatch));
console.log('2) ret_net 与 exit/entry-1-fee 不符: ' + err.retMismatch.length + '\n    ' + fmt(err.retMismatch));
console.log('3) T+1 违规（出场日 <= 入场日）: ' + err.t1Violation.length + '\n    ' + fmt(err.t1Violation));
console.log('4) 同标的持仓重叠: ' + err.overlap.length + '\n    ' + fmt(err.overlap));
console.log('5) 入场日 ≠ 买点discT+1: ' + err.entryNotNext.length + '\n    ' + fmt(err.entryNotNext));
console.log('6) 存在 lag≠1 的买点被交易: ' + err.lagNot1.length + '\n    ' + fmt(err.lagNot1));
console.log('7) 入场时价格已低于中枢ZD（结构态"下移"入场即成立）: ' + stCheck.alreadyBelow + '/' + stCheck.total +
  ' = ' + (100 * stCheck.alreadyBelow / stCheck.total).toFixed(1) + '%   ' +
  Object.entries(stCheck.byLevel).map(([k, v]) => k + ' ' + v[0] + '/' + v[1]).join('  '));

fs.writeFileSync(path.join(__dirname, 'out', 'verify_' + TF + '.json'), JSON.stringify({
  tf: TF, nCheck,
  priceMismatch: err.priceMismatch.length,
  retMismatch: err.retMismatch.length,
  t1Violation: err.t1Violation.length,
  overlap: err.overlap.length,
  entryNotNext: err.entryNotNext.length,
  lagNot1: err.lagNot1.length,
  badBar: err.badBar.length,
  belowZD: stCheck.alreadyBelow, zdTotal: stCheck.total, byLevel: stCheck.byLevel
}, null, 1));
