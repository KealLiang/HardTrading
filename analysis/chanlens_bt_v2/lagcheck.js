/* ==========================================================================
 * lagcheck.js —— 检验「发现滞后」是否构成未来函数
 *
 * 问题：lag = 发现日 − readyK。lag>1 表示信号在 readyK 之后才被识别，
 *      但回测仍用 readyK+1 的开盘价入场 —— 那笔成交在过去，无法执行。
 *      v2 结果里lag>=20 占 20.6%，必须查它是否虚高。
 *
 * 检验：按 lag 分组，比较各组超额。若 lag 大的组超额显著更高 → 存在前视偏差。
 * 同时给出「只保留 lag<=1（次日即可交易）」的干净子集结论。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const Chan = require(ENGINE);
const DIR = 'D:/Trading/data/etfs';
const FEE = 0.001, WARMUP = 500;
const HOLDS = [10, 20];

function scanDaily(ks) {
  const seen = new Set(), sigs = [];
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== 1 || p.level < 1 || p.level > 3 || p.readyK > t) continue;
      const key = p.level + ':' + p.readyK;
      if (seen.has(key)) continue;
      seen.add(key);
      sigs.push({ level: p.level, readyK: p.readyK, markK: p._k, lag: t - p.readyK });
    }
  }
  return sigs;
}

const all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(f => f.replace('.csv', '')).sort();
const need = WARMUP + Math.max.apply(null, HOLDS) + 100;

/* 分组：lag=1（次日可交易）vs lag>1（回溯成交，不可执行） */
const G = {
  clean: { 1: { 10: [], 20: [] }, 2: { 10: [], 20: [] }, 3: { 10: [], 20: [] } },
  dirty: { 1: { 10: [], 20: [] }, 2: { 10: [], 20: [] }, 3: { 10: [], 20: [] } }
};
const glob = { 10: [], 20: [] };
/* lag 分桶（不截断） */
const BUCKET = [[1, 1], [2, 3], [4, 7], [8, 15], [16, 40], [41, 99999]];
const byLag = BUCKET.map(() => ({ 10: [], 20: [] }));
let nBooks = 0;

for (const code of all) {
  let ks;
  try { ks = L.loadETF(path.join(DIR, code + '.csv')).ks; } catch (e) { continue; }
  if (ks.length < need) continue;
  nBooks++;
  const last = ks.length - 1;
  const rng = L.makeRng(hashSeed(code));
  const sigs = scanDaily(ks);

  for (const s of sigs) {
    const e = s.readyK + 1;
    if (e < WARMUP || e + Math.max.apply(null, HOLDS) > last) continue;
    if (!(ks[e] && !ks[e].bad && ks[e].o > 0)) continue;
    const tgt = s.lag <= 1 ? G.clean : G.dirty;
    for (const h of HOLDS) {
      const r = L.retAt(ks, e, h, FEE);
      if (r == null) continue;
      tgt[s.level][h].push(r);
      for (let i = 0; i < BUCKET.length; i++) {
        if (s.lag >= BUCKET[i][0] && s.lag <= BUCKET[i][1]) { byLag[i][h].push(r); break; }
      }
    }
  }
  for (const h of HOLDS) {
    let acc = 0, n = 0;
    for (let i = 0; i < 800; i++) {
      const ei = WARMUP + Math.floor(rng() * (last - h - WARMUP));
      const r = L.retAt(ks, ei, h, FEE);
      if (r != null) { acc += r; n++; }
    }
    if (n) glob[h].push(acc / n);
  }
  process.stderr.write('  ' + nBooks + ' ' + code + '\n');
}

const NM = { 1: '一买', 2: '二买', 3: '三买' };
const pc = x => x == null ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => x == null ? '  n/a' : ((x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp').padStart(8);

console.log('\n========== 1. 按 lag 分桶：超额是否随lag 变大而升高 ==========');
console.log('lag = 首次发现日− readyK。lag>1 意味着回测用了「发现之前」的入场价。\n');
console.log('lag 区间| 10日 n超额      t | 20日 n   超额      t');
console.log('-'.repeat(66));
for (let i = 0; i < BUCKET.length; i++) {
  const [lo, hi] = BUCKET[i];
  const cells = HOLDS.map(h => {
    const a = byLag[i][h], b = glob[h];
    const ci = L.ci95(a, b), t = L.welchT(a, b);
    return (String(a.length).padStart(5) + L.pp(ci && ci.d) + '(' + L.f2(t).padStart(6) + ')').padEnd(20);
  }).join('|');
  console.log(' ' + (lo === hi ? String(lo) : lo + '~' + (hi > 1000 ? '+' : hi)).padEnd(5) + '|' + cells);
}

console.log('\n========== 2. 干净子集（lag=1，次日可交易）vs 污染子集（lag>1）==========');
console.log('买点 持有 | 干净 n  收益   超额    t | 污染 n  收益超额    t');
console.log('-'.repeat(80));
const res = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const C = G.clean[Lv][h], D = G.dirty[Lv][h];
  const cci = L.ci95(C, glob[h]);
  const tC = L.welchT(C, glob[h]), tD = L.welchT(D, glob[h]);
  res[Lv + '_' + h] = {
    cleanN: C.length, cleanExp: L.mean(C), cleanEdge: cci && cci.d, cleanT: tC,
    dirtyN: D.length, dirtyExp: L.mean(D), dirtyEdge: L.mean(D) != null ? L.mean(D) - L.mean(glob[h]) : null, dirtyT: tD
  };
  console.log(` ${NM[Lv]} ${String(h).padStart(3)}日 |${String(C.length).padStart(5)}${pc(L.mean(C)).padStart(7)}${pp(cci && cci.d).padStart(8)}${L.f2(tC).padStart(6)} |` +
    `${String(D.length).padStart(5)}${pc(L.mean(D)).padStart(7)}${pp(res[Lv + '_' + h].dirtyEdge).padStart(7)}${L.f2(tD).padStart(6)}`);
}

console.log('\n========== 3. 干净子集汇总（这是可交易的真实口径）==========');
console.log('买点 | 持有 | n超额Welch t  95%CI');
console.log('-'.repeat(58));
const cleanAll = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = [].concat.apply([], [1, 2, 3].map(x => G.clean[x][h]));
  const b = glob[h];
  const ci = L.ci95(a, b), t = L.welchT(a, b);
  cleanAll[Lv + '_' + h] = { n: a.length, exp: L.mean(a), edge: ci && ci.d, t: t, ci: ci };
  console.log(` ${NM[Lv]} | ${String(h).padStart(3)}日 |${String(a.length).padStart(5)} ${pp(ci && ci.d).padStart(8)} ${L.f2(t).padStart(7)}  [${pp(ci && ci.lo)}, ${pp(ci && ci.hi)}]`);
}

console.log('\n判读：');
console.log('  · 若「污染子集」超额明显高于「干净子集」→ v2 的结论被前视偏差抬高');
console.log('  · 干净子集（lag=1）才是可真实执行的口径');

fs.writeFileSync(path.join(__dirname, 'tmp', 'lagcheck.json'), JSON.stringify({ res, cleanAll }, null, 1));
console.log('\n已写出 tmp/lagcheck.json');

function hashSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }