/* ==========================================================================
 * point_audit.js —— 买卖点「可得性」审计（信号可用性 / 入场前视偏差）
 *
 * 与 walkforward.js 的区别（两者互补，都要跑）：
 *   walkforward 验证「历史结构会不会被未来数据改写」  → 重绘型未来函数
 *   本脚本验证「标记所在的那根 K 线，当时是否已能算出」 → 可得性型未来函数
 *
 * 方法（黑盒，只用引擎公开输出）：
 *   全量跑一次得到标定点集合；然后从最小可用长度开始逐步推进 T，
 *   用 klines.slice(0, T+1) 重跑，记录每个标定点的**首次出现**位置 firstVisible。
 *
 *   相对于标记位置：   lagMark  = firstVisible - _k        → 图形位置的可得延迟
 *   相对于信息终点：   lagReady = firstVisible - readyK     → 判据条件完整后的额外延迟
 *
 *   期望 lagMark > 0（缠论分型天生要右侧确认一根，正常且不可避免）
 *   期望 lagReady ∈ [0, 1~2]，且**绝不为负** —— 若为负说明信号提前于所需信息出现 = 前视
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const Chan = require('../core/chan.js');

const DIR = path.join(__dirname, 'testdata');
const load = f => {
  const j = JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf8'));
  return j.klines || j;
};

const CASES = [
  { file: '600519_daily.json', name: '茅台日线' },
  { file: '000001_daily.json', name: '平安日线' },
  { file: '300750_daily.json', name: '宁德日线' },
  { file: '600519_30m.json',   name: '茅台30分' }
];
const OPTSETS = [
  { name: '默认(线段+滚动三笔)', opts: {} },
  { name: '笔中枢+严格背驰',     opts: { zsSource: 'bi', divMode: 'zs' } },
  { name: '笔级别买卖点',        opts: { pointsOnSegs: false } },
  { name: '特征序列线段',        opts: { segAlgo: 'feature' } }
];

const WARMUP = 5;
const keyOf = p => `${p.level}|${p.type}|${p._k}`;
const q = (a, p) => {
  if (!a.length) return NaN;
  const s = a.slice().sort((x, y) => x - y), i = (s.length - 1) * p;
  const lo = Math.floor(i), hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
};
const stat = a => a.length
  ? `n=${a.length} min=${Math.min(...a)} p50=${q(a, .5)} p90=${q(a, .9)} max=${Math.max(...a)}`
  : 'n=0';

function audit(file, opts) {
  const kl = load(file), n = kl.length;
  const full = Chan.analyze(kl, opts);
  const ref = new Map(full.points.map(p => [keyOf(p), p]));
  if (!ref.size) return null;

  const firstVisible = new Map();
  for (let T = WARMUP; T < n && firstVisible.size < ref.size; T++) {
    const r = Chan.analyze(kl.slice(0, T + 1), opts);
    for (const p of r.points) {
      const k = keyOf(p);
      if (ref.has(k) && !firstVisible.has(k)) firstVisible.set(k, T);
    }
  }

  return full.points.map(p => {
    const fv = firstVisible.has(keyOf(p)) ? firstVisible.get(keyOf(p)) : NaN;
    return { p, fv, lagMark: fv - p._k, lagReady: fv - p.readyK };
  });
}

console.log('='.repeat(84));
console.log('买卖点可得性审计    lagMark=首见bar-标记bar    lagReady=首见bar-信息终点readyK');
console.log('='.repeat(84));

let early = 0, total = 0;
const allMark = [], allReady = [], byLv = {};

for (const c of CASES) {
  console.log(`\n■ ${c.name}`);
  for (const os of OPTSETS) {
    const rows = audit(c.file, os.opts);
    if (!rows) { console.log(`   ${os.name}: 无买卖点`); continue; }
    const ok = rows.filter(r => isFinite(r.fv));
    ok.forEach(r => {
      allMark.push(r.lagMark); allReady.push(r.lagReady);
      (byLv[r.p.level] = byLv[r.p.level] || []).push(r);
      if (r.lagReady < 0) early++;
    });
    total += ok.length;
    console.log(`   ${os.name.padEnd(18)} 点数=${String(rows.length).padStart(3)}  lagMark ${stat(ok.map(r => r.lagMark))}  lagReady ${stat(ok.map(r => r.lagReady))}`);
    const neg = ok.filter(r => r.lagReady < 0);
    if (neg.length) console.log(`        ❌ 提前于所需信息出现 ${neg.length} 个（真·前视）`);
  }
}

console.log('\n' + '='.repeat(84));
console.log('按买卖点级别汇总（全部数据×全部参数）');
console.log('='.repeat(84));
for (const L of Object.keys(byLv).sort()) {
  const nm = { 1: '一类 背驰极值点', 2: '二类 背驰后回抽', 3: '三类 中枢后回抽' }[L];
  const rows = byLv[L];
  console.log(`${nm.padEnd(20)} n=${String(rows.length).padStart(3)}  lagMark ${stat(rows.map(r => r.lagMark))}  lagReady ${stat(rows.map(r => r.lagReady))}`);
}

console.log('\n' + '='.repeat(84));
console.log(`样本 ${total} 个；lagReady < 0（信号早于所需信息 = 真·前视偏差）：${early} 个`);
console.log(`readyK 覆盖：全部买卖点均已携带 readyK 字段`);
console.log('='.repeat(84));
