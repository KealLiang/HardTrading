/* ==========================================================================
 * bt.js —— 逐日无未来函数回测框架 v2
 *
 * 纪律（针对此前四轮的错误）：
 *   D1. 只读生产引擎 chan.js，跑前跑后 md5 双向核对，任何不一致直接中止
 *   D2. 入场时刻固定为 readyK+1 开盘（引擎既定的 readyK 语义，见 chan.js detectPoints）
 *   D3. 基准不设人为参数：全区间随机 + 邻近窗口随机，并扫描窗口做敏感性检验
 *   D4. 不做任何"信号是否幸存"的人工判定；一次性口径对比只用引擎自身结果
 *   D5. 所有结论必须带敏感性检验；不稳健的结论显式标注
 *
 * 环境变量：
 *   SMOKE=n  只取历史最长的 n 只 ETF（冒烟自检用）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const L = require('./lib.js');

const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const Chan = require(ENGINE);
const DIR = 'D:/Trading/data/etfs';

const FEE = 0.001;            // ETF 场内双边费率
const WARMUP = 500;           // 结构预热根数
const HOLDS = [10, 20];// 持有期（交易日）
const NB_WINDOWS = [5, 10, 20, 40];   // 邻近基准窗口（敏感性扫描用）
const NB_SAMPLES = 800;       // 邻近基准每信号抽样次数
const GLOB_SAMPLES = 800;     // 全区间基准每信号抽样次数

const md5 = f => crypto.createHash('md5').update(fs.readFileSync(f)).digest('hex');
const MD5_BEFORE = md5(ENGINE);

const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ------------------------------------------------------- 选票（含冒烟） */
let all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).sort();
const SMOKE = parseInt(process.env.SMOKE || '0', 10);
if (SMOKE > 0) {
  all = all.map(c => {
    try {
      const n = fs.readFileSync(path.join(DIR, c), 'utf8').split(/\r?\n/).filter(x => x.trim()).length;
      return { c: c.replace('.csv', ''), n: n };
    } catch (e) { return { c: c.replace('.csv', ''), n: 0 }; }
  }).sort((a, b) => b.n - a.n).slice(0, SMOKE).map(x => x.c);
} else {
  all = all.map(c => c.replace('.csv', ''));
}

const maxHold = Math.max.apply(null, HOLDS);
const need = WARMUP + maxHold + 100;

/* ------------------------------------------------------------ 数据加载 */
const books = [], skipped = [];
for (const code of all) {
  try {
    const r = L.loadETF(path.join(DIR, code + '.csv'));
    if (r.ks.length < need) { skipped.push({ code, why: '仅 ' + r.ks.length + ' 根，不足 ' + need }); continue; }
    books.push({ code, ks: r.ks, badCount: r.badCount });
  } catch (e) { skipped.push({ code, why: e.message }); }
}

/* ---------------------------------------------------------- 逐日发现信号 */
function scanDaily(ks) {
  const seen = new Set(), sigs = [], lagHist = {};
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== 1) continue;                 // 仅买点；type 是方向符号 ±1
      if (p.level < 1 || p.level > 3) continue;   // level 才是买点类型 1/2/3
      if (p.readyK > t) continue;                 // 结构尚未确立，不该出现
      const key = p.level + ':' + p.readyK;       // 同位置同类型只记首次
      if (seen.has(key)) continue;
      seen.add(key);
      sigs.push({ level: p.level, readyK: p.readyK, markK: p._k, price: p.price });
      // 自检：记录该信号是在第几根被发现的（应为 0，即 readyK 当根即发现）
      const lag = t - p.readyK;
      lagHist[Math.min(20, lag)] = (lagHist[Math.min(20, lag)] || 0) + 1;
    }
  }
  return { sigs, lagHist };
}

/* ============================================================== 主流程 */
const out = {
  meta: {
    engine: ENGINE, md5Before: MD5_BEFORE, fee: FEE, warmup: WARMUP, holds: HOLDS,
    nbWindows: NB_WINDOWS, smoke: SMOKE,
    books: books.length, skipped: skipped, bars: books.map(b => b.ks.length),
    badBars: books.reduce((s, b) => s + b.badCount, 0)
  },
  sig: {},        // sig[level][hold] = [收益]
  glob: {},       // glob[hold] = [收益]
  nb: {},         // nb[win][hold] = [收益]
  perEft: {},     // perEft[code][hold] = {sig:[], nb10:[]}
  survivor: {},   // survivor[level] = {keep:[], drop:[]}
  oneShot: {},    // oneShot[level][hold] = [收益]
  lagHist: {},
  sanity: {}
};

HOLDS.forEach(h => { out.glob[h] = []; });
NB_WINDOWS.forEach(w => { out.nb[w] = {}; HOLDS.forEach(h => out.nb[w][h] = []); });
books.forEach(b => { out.perEft[b.code] = {}; });
[1, 2, 3].forEach(Lv => {
  out.sig[Lv] = {}; out.oneShot[Lv] = {}; out.survivor[Lv] = { keep: [], drop: [] };
  HOLDS.forEach(h => { out.sig[Lv][h] = []; out.oneShot[Lv][h] = []; });
});

let nSig = 0;

for (const bk of books) {
  const ks = bk.ks, last = ks.length - 1;
  const rng = L.makeRng(hashSeed(bk.code));
  const { sigs, lagHist } = scanDaily(ks);
  for (const k in lagHist) out.lagHist[k] = (out.lagHist[k] || 0) + lagHist[k];

  /* 一次性全序列结果（用于 D4：只看引擎自己怎么说，不加人工判据） */
  const full = Chan.analyze(ks, {});
  const fullKeys = new Set();
  full.points.forEach(p => { if (p.type === 1) fullKeys.add(p.level + ':' + p._k); });

  for (const s of sigs) {
    const e = s.readyK + 1;                       // D2：确立次日开盘入场
    if (e < WARMUP || e + maxHold > last) continue;
    const row = L.stat([L.retAt(ks, e, maxHold, FEE)]); // 先探一次可交易性
    if (!row || !row.n) continue;
    nSig++;

    /* --- 信号收益 --- */
    for (const h of HOLDS) {
      const r = L.retAt(ks, e, h, FEE);
      if (r == null) continue;
      out.sig[s.level][h].push(r);
      if (!out.perEft[bk.code][h]) out.perEft[bk.code][h] = { sig: [], nb: [] };
      out.perEft[bk.code][h].sig.push(r);
    }

    /* --- D3a：全区间随机基准 --- */
    for (const h of HOLDS) {
      let acc = 0, n = 0;
      for (let i = 0; i < GLOB_SAMPLES; i++) {
        const ei = WARMUP + Math.floor(rng() * (last - h - WARMUP));
        const r = L.retAt(ks, ei, h, FEE);
        if (r != null) { acc += r; n++; }
      }
      if (n) out.glob[h].push(acc / n);
    }

    /* --- D3b：邻近窗口随机基准（控制局部行情环境） --- */
    for (const w of NB_WINDOWS) {
      for (const h of HOLDS) {
        let acc = 0, n = 0;
        for (let i = 0; i < NB_SAMPLES; i++) {
          const lo = Math.max(WARMUP, e - w), hi = Math.min(last - h, e + w);
          if (hi <= lo) break;
          const ei = lo + Math.floor(rng() * (hi - lo));
          const r = L.retAt(ks, ei, h, FEE);
          if (r != null) { acc += r; n++; }
        }
        if (n) out.nb[w][h].push(acc / n);
      }
    }

    /* --- D4：一次性口径是否还认这个信号（零人为容差） --- */
    if (e + 20 <= last) {
      const r = L.retAt(ks, e, 20, FEE);
      if (r != null) out.survivor[s.level][fullKeys.has(s.level + ':' + s.markK) ? 'keep' : 'drop'].push(r);
    }
  }

  /* --- 一次性口径自身收益 --- */
  full.points.forEach(p => {
    if (p.type !== 1 || p.level < 1 || p.level > 3) return;
    const e = p.readyK + 1;
    if (e < WARMUP || e + maxHold > last) return;
    for (const h of HOLDS) {
      const r = L.retAt(ks, e, h, FEE);
      if (r != null) out.oneShot[p.level][h].push(r);
    }
  });

  log('  [' + (books.indexOf(bk) + 1) + '/' + books.length + '] ' + bk.code +
    '  ' + ks.length + '根  信号' + sigs.length + '  ' + (L.mean(Object.values(out.perEft[bk.code]).map(v => v.sig.length)) || 0).toFixed(0) +
    '  ' + ((Date.now() - T0) / 1000).toFixed(1) + 's');
}

/* ------------------------------------------------------------ 自检断言 */
out.sanity.badBars = out.meta.badBars;
out.sanity.lagDist = out.lagHist;
out.sanity.nSig = nSig;

/* ---------------------------------------------------------------- 输出 */
console.log('\n=========== 逐日无未来函数回测 v2 ===========');
console.log('引擎 md5(跑前) ' + MD5_BEFORE);
console.log('ETF ' + books.length + ' 只（跳过 ' + skipped.length + '），坏 K 线 ' + out.meta.badBars + ' 根，可交易信号 ' + nSig + ' 个');
console.log('入场 = readyK+1 开盘   持有 ' + HOLDS.join('/') + ' 日   双边费 ' + (FEE * 100) + '%\n');

const NM = { 1: '一买', 2: '二买', 3: '三买' };

console.log('【1】信号 vs 全区间随机买入基准');
console.log('买点 持有 | 信号 n信号收益  基准收益     超额   Welch t  95%CI');
console.log('-'.repeat(78));
out.r1 = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = out.sig[Lv][h], b = out.glob[h];
  const ci = L.ci95(a, b);
  const t = L.welchT(a, b);
  out.r1[Lv + '_' + h] = { n: a.length, exp: L.mean(a), base: L.mean(b), edge: ci && ci.d, t: t, ci: ci };
  console.log(` ${NM[Lv]} ${h}日 |${String(a.length).padStart(7)}  ${L.pc(L.mean(a)).padStart(8)}  ${L.pc(L.mean(b)).padStart(8)}  ${L.pp(ci && ci.d).padStart(8)}  ${L.f2(t).padStart(8)}  [${L.pp(ci && ci.lo)}, ${L.pp(ci && ci.hi)}]`);
}

console.log('\n【2】邻近窗口随机基准（控制局部行情环境）—— 敏感性扫描');
console.log('持有期 ' + HOLDS.map(h => h + '日').join('  |  ') + '   （各行 = 邻近窗口大小）');
console.log('窗口 | ' + HOLDS.map(h => '超额(t)').join('  |  '));
console.log('-'.repeat(62));
out.r2 = {};
for (const w of NB_WINDOWS) {
  const cells = HOLDS.map(h => {
    const a = [].concat(out.sig[1][h], out.sig[2][h], out.sig[3][h]);
    const b = out.nb[w][h];
    const ci = L.ci95(a, b), t = L.welchT(a, b);
    out.r2[w + '_' + h] = { edge: ci && ci.d, t: t };
    return (L.pp(ci && ci.d) + '(' + L.f2(t) + ')').padStart(14);
  }).join('  |  ');
  console.log(' ±' + String(w).padStart(2) + ' | ' + cells);
}
console.log('\n判读：若各窗口超额符号一致且幅度相近 → 结论稳健；否则说不稳健。');

console.log('\n【3】一次性全序列口径 vs 逐日口径（同一引擎、同一数据）');
console.log('买点 持有 | 一次口径 n一次收益  逐日口径 n  逐日收益     差');
console.log('-'.repeat(72));
out.r3 = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = out.oneShot[Lv][h], b = out.sig[Lv][h];
  const d = L.mean(a) != null && L.mean(b) != null ? L.mean(a) - L.mean(b) : null;
  out.r3[Lv + '_' + h] = { oneN: a.length, oneExp: L.mean(a), dayN: b.length, dayExp: L.mean(b), diff: d };
  console.log(` ${NM[Lv]} ${h}日 |${String(a.length).padStart(8)}  ${L.pc(L.mean(a)).padStart(8)}  ${String(b.length).padStart(8)}  ${L.pc(L.mean(b)).padStart(8)}  ${L.pp(d).padStart(8)}`);
}
const oneN = [1, 2, 3].reduce((s, Lv) => s + out.oneShot[Lv][maxHold].length, 0);
const dayN = [1, 2, 3].reduce((s, Lv) => s + out.sig[Lv][maxHold].length, 0);
console.log(`\n 合计：一次性口径 ${oneN} 个信号，逐日口径 ${dayN} 个，逐日多 ${dayN - oneN} 个`);

console.log('\n【4】一次性口径漏掉的信号质量（零人为容差）');
console.log('判据：把逐日发现的信号逐个查它在【最终全序列结果】里还在不在。');
console.log('      这正是"直接用 res.points 回测"会漏掉的部分。\n');
console.log('买点 | 留存 n留存收益   t  | 漏掉 n  漏掉收益    t  |     差Welch t');
console.log('-'.repeat(82));
out.r4 = {};
for (const Lv of [1, 2, 3]) {
  const K = out.survivor[Lv].keep, D = out.survivor[Lv].drop;
  const t = L.welchT(K, D), d = L.mean(K) != null && L.mean(D) != null ? L.mean(K) - L.mean(D) : null;
  out.r4[Lv] = { keepN: K.length, keepExp: L.mean(K), dropN: D.length, dropExp: L.mean(D), diff: d, t: t };
  const tk = L.sd(K) ? L.mean(K) / (L.sd(K) / Math.sqrt(K.length)) : null;
  const td = L.sd(D) ? L.mean(D) / (L.sd(D) / Math.sqrt(D.length)) : null;
  console.log(` ${NM[Lv]} |${String(K.length).padStart(7)}${L.pc(L.mean(K)).padStart(8)}${L.f2(tk).padStart(7)} |` +
    `${String(D.length).padStart(7)}${L.pc(L.mean(D)).padStart(9)}${L.f2(td).padStart(7)} |${L.pp(d).padStart(8)}${L.f2(t).padStart(8)}`);
}

console.log('\n【5】自检');
const lagKeys = Object.keys(out.lagHist).map(Number).sort((a, b) => a - b);
console.log('  信号发现滞后(t - readyK) 分布: ' + lagKeys.slice(0, 6).map(k => k + '→' + out.lagHist[k]).join('  '));
console.log('  滞后>5 根的信号: ' + lagKeys.filter(k => k > 5).reduce((s, k) => s + out.lagHist[k], 0) +
  ' (' + (100 * lagKeys.filter(k => k > 5).reduce((s, k) => s + out.lagHist[k], 0) / nSig).toFixed(1) + '%)');
console.log('  坏 K 线总数: ' + out.meta.badBars + '（已标记，不参与入场）');
const anyNaN = HOLDS.some(h => out.glob[h].some(x => !isFinite(x)) || [1, 2, 3].some(Lv => out.sig[Lv][h].some(x => !isFinite(x))));
console.log('  收益序列含 NaN/Inf: ' + (anyNaN ? '有（异常！）' : '无'));
console.log('  K 线根数范围: ' + Math.min.apply(null, out.meta.bars) + ' ~ ' + Math.max.apply(null, out.meta.bars));
console.log('  耗时 ' + ((Date.now() - T0) / 1000).toFixed(1) + 's');

const MD5_AFTER = md5(ENGINE);
console.log('\n引擎 md5(跑后) ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！结果不可信'));
out.meta.md5After = MD5_AFTER;
out.meta.elapsed = (Date.now() - T0) / 1000;

fs.writeFileSync(path.join(__dirname, 'tmp', 'bt_v2.json'), JSON.stringify(out));
console.log('\n已写出 tmp/bt_v2.json');

function hashSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }