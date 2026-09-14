/* ==========================================================================
 * tools/debug_dump.js —— 开发调试用：把引擎每一层的中间结果打印出来
 * 运行： node tools/debug_dump.js [数据源 ../testdata.json]
 *
 * 改参数后想知道"为什么最后一笔变了/为什么没线段"，跑这个最直观。
 * ========================================================================== */
'use strict';
const path = require('path');
const Chan = require(path.join(__dirname, '..', 'core', 'chan.js'));
const IND = require(path.join(__dirname, '..', 'core', 'indicators.js'));

function synth(plan) {
  const ks = []; let t = Date.UTC(2024, 0, 1); let idx = 0;
  for (const seg of plan.segs) {
    for (let i = 0; i < seg.n; i++) {
      const u = i / Math.max(1, seg.n - 1);
      const trend = seg.from + (seg.to - seg.from) * u;
      const osc = Math.sin(idx * seg.freq) * seg.amp;
      const o = trend + osc;
      const c = trend + osc * 0.6 + (seg.to - seg.from) / seg.n;
      const h = Math.max(o, c) + Math.abs(Math.cos(idx * 1.7)) * seg.amp * 0.5;
      const l = Math.min(o, c) - Math.abs(Math.sin(idx * 1.3)) * seg.amp * 0.5;
      ks.push({ t, o, h, l, c, v: 1000 + (idx % 7) * 100 });
      t += 86400000; idx++;
    }
  }
  return ks;
}

const DEFAULT_PLAN = {
  start: 100,
  segs: [
    { n: 40, from: 100, to: 78, amp: 0.8, freq: 0.55 },
    { n: 45, from: 78, to: 82, amp: 1.0, freq: 0.45 },
    { n: 50, from: 82, to: 108, amp: 0.9, freq: 0.5 },
    { n: 45, from: 108, to: 96, amp: 1.0, freq: 0.45 },
    { n: 40, from: 96, to: 116, amp: 0.9, freq: 0.55 }
  ]
};

const arg = process.argv[2];
let klines;
if (arg) {
  const mod = require(path.resolve(arg));
  klines = Array.isArray(mod) ? mod : mod.klines;
} else {
  klines = synth(DEFAULT_PLAN);
}
const userOpts = {};
process.argv.slice(3).forEach(kv => {
  const eq = kv.indexOf('=');
  if (eq < 0) return;
  const k = kv.slice(0, eq), raw = kv.slice(eq + 1);
  try { userOpts[k] = JSON.parse(raw); }
  catch (e) {
    const n = Number(raw);
    userOpts[k] = raw === 'true' ? true : raw === 'false' ? false : (isNaN(n) ? raw : n);
  }
});

const r = Chan.analyze(klines, userOpts);
const f2 = v => (v === undefined || v === null || !isFinite(v)) ? '-' : Number(v).toFixed(2);

console.log('=== 统计 ===');
console.log(JSON.stringify(r.stats, null, 2));

console.log('\n=== 分型 (%d 个) ===', r.fractals.length);
console.log(r.fractals.map(f => `${f.type > 0 ? '顶' : '底'}@k${f._k}(${f2(f.price)})`).join('  '));

console.log('\n=== 笔 (%d 笔) ===', r.bis.length);
r.bis.forEach((b, i) => {
  console.log(`  #${i} ${b.dir > 0 ? '↑' : '↓'} pen k${b.startK}→k${b.endK}  ` +
    `${f2(b.startPrice)} → ${f2(b.endPrice)}  ${b.confirmed ? '确认' : '待确认'}`);
});

console.log('\n=== 线段 (%d 段) ===', r.segs.length);
r.segs.forEach((s, i) => {
  console.log(`  #${i} ${s.dir > 0 ? '↑' : '↓'} pen${s.startBi}..${s.endBi}(${s.penCount}笔) ` +
    `k${s.startK}→k${s.endK}  ${f2(s.startPrice)} → ${f2(s.endPrice)}  ${s.confirmed ? '确认' : '待确认'}`);
});

console.log('\n=== 中枢 (%d 个) ===', r.zhongshus.length);
r.zhongshus.forEach((z, i) => {
  console.log(`  Z${i}: [${f2(z.ZD)}, ${f2(z.ZG)}]  part${z.startPart}..${z.endPart} ` +
    `(${z.partCount}段) k${z.startK}→k${z.endK}`);
});

console.log('\n=== 背驰 (%d 处) ===', r.divergences.length);
r.divergences.forEach(d => {
  console.log(`  ${d.type > 0 ? '底背驰' : '顶背驰'} @k${d.targetK} 前段力度 ${f2(d.fEnter)} ` +
    `后段 ${f2(d.fLeave)} 比值 ${f2(d.ratio)}`);
});

const counters = {};
r.points.forEach(p => { counters[p.note] = (counters[p.note] || 0) + 1; });
console.log('\n=== 买卖点 (%d 个) ===', r.points.length);
Object.keys(counters).sort().forEach(k => { console.log('    %s × %d', k, counters[k]); });
r.points.slice(0, 40).forEach(p => {
  console.log('  ' + p.note + ' @k' + p._k + ' price=' + f2(p.price));
});
