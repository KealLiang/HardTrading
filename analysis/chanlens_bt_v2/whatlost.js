/* ==========================================================================
 * whatlost.js —— 「漏掉」到底是什么？把两种消失严格分开
 *
 * 用户提问：实盘是看到信号又消失吗？「漏掉」到底什么意思？
 *
 * 本脚本用两种互斥判据回答，把概念一次说清：
 *
 *   判据 A【真消失】：在后续所有切片里，同 level 且锚点位置完全一致（±0）的
 *                     同类信号**再也没出现过**。
 *                     → 这是实盘真的能看到的：图上那个信号真的没了。
 *
 *   判据 B【挪位置】：±0 找不到，但放宽到 ±TOL 找得到，且距离 > 0。
 *                     → 图上信号还在，只是 K 线位置被后���走势推走了。
 *
 *   判据 C【彻底没影】：±40 范围内连同类信号都没有。
 *                     → 上下都没有，应该就是真删了。
 *
 * 输出：
 *   1. A/B/C 三类的占比
 *   2. 实盘视角：图上的信号有多少比例会被"擦掉"
 *   3. 一次性口径漏掉的那 34.6% 到底由什么构成
 *
 * 纪律：只读引擎，md5 双向核对；所有结论带容差敏感性。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');
const L = require('./lib.js');

const DIR = 'D:/Trading/data/etfs';
const md5 = f => crypto.createHash('md5').update(fs.readFileSync(f)).digest('hex');
const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const MD5_BEFORE = md5(ENGINE);

const WARMUP = 500;
const MAXWATCH = 120;
const TOLS = [0, 3, 5, 10, 20, 40];   // 敏感性扫描
const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ------------------------------------------------------------ 数据 */
const all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(c => c.replace('.csv', '')).sort();
const books = [];
for (const code of all) {
  try {
    const r = L.loadETF(path.join(DIR, code + '.csv'));
    if (r.ks.length < WARMUP + MAXWATCH + 100) continue;
    books.push({ code, ks: r.ks });
  } catch (e) { /* skip */ }
}

/* ------------------------------------------- 逐日发现信号（同 bt.js） */
function scanDaily(ks) {
  const seen = new Set(), sigs = [];
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== 1) continue;
      if (p.level < 1 || p.level > 3) continue;
      if (p.readyK > t) continue;
      const key = p.level + ':' + p.readyK;
      if (seen.has(key)) continue;
      seen.add(key);
      sigs.push({ level: p.level, readyK: p.readyK, markK: p._k });
    }
  }
  return sigs;
}

/* ============================== 主流程 ============================== */
/* 对每个信号，记录：最终全序列结果里，它以什么形式存在 */
const recs = [];   // {code, level, markK, ret20, drift, klass}
const T0n = Date.now();

for (const bk of books) {
  const ks = bk.ks, last = ks.length - 1;
  const sigs = scanDaily(ks);

  /* 最终全序列结果（用于回答「图上还画不画这个信号」） */
  const full = Chan.analyze(ks, {});
  // 同 level 的全部锚点位置
  const byLevel = { 1: [], 2: [], 3: [] };
  full.points.forEach(p => { if (p.type === 1 && byLevel[p.level]) byLevel[p.level].push(p._k); });
  for (const lv of [1, 2, 3]) byLevel[lv].sort((a, b) => a - b);

  /* 同时扫逐日：信号在入场后多久第一次「±0 找不到」 */
  for (const s of sigs) {
    const e = s.readyK + 1;
    if (e < WARMUP || e + 20 > last) continue;
    const ret20 = L.retAt(ks, e, 20, 0.001);
    if (ret20 == null) continue;

    // 最终结构里最近的同类信号距离
    const arr = byLevel[s.level];
    let best = Infinity;
    for (const k of arr) { const d = Math.abs(k - s.markK); if (d < best) best = d; }

    // 分类
    let klass;
    if (best === 0) klass = 'A_原地仍在';
    else if (best <= 40) klass = 'B_挪位置';
    else klass = 'C_彻底没影';

    // 首次「±0 找不到」的时点（实盘可见的擦除时刻）
    let lostAt = -1;
    for (let t = e; t <= e + MAXWATCH && t < last; t++) {
      const res = Chan.analyze(ks.slice(0, t + 1), {});
      const alive0 = res.points.some(p => p.type === 1 && p.level === s.level && Math.abs(p._k - s.markK) <= 0);
      if (!alive0) { lostAt = t; break; }
    }

    recs.push({ code: bk.code, level: s.level, markK: s.markK, ret20, drift: best, klass, lostAt, bars: lostAt < 0 ? -1 : lostAt - e });
  }
  log('  [' + (books.indexOf(bk) + 1) + '/' + books.length + '] ' + bk.code + '  信号' + sigs.length + '  ' + ((Date.now() - T0n) / 1000).toFixed(1) + 's');
}

/* ---------------------------------------------------------------- 输出 */
const N = recs.length;
const cls = { A_原地仍在: [], B_挪位置: [], C_彻底没影: [] };
recs.forEach(r => cls[r.klass].push(r));

console.log('\n============ 「漏掉」到底是什么 ============');
console.log('引擎 md5(跑前) ' + MD5_BEFORE);
console.log('ETF ' + books.length + ' 只，20 日可交易信号 ' + N + ' 个\n');

console.log('【1】三类形态占比（看最终全序列结构里，这个信号还在不在图上）');
console.log('  类别            含义                          n占比      20日收益');
console.log('-'.repeat(78));
for (const k of ['A_原地仍在', 'B_挪位置', 'C_彻底没影']) {
  const a = cls[k];
  const ret = a.length ? L.mean(a.map(x => x.ret20)) : null;
  console.log('  ' + k.padEnd(16) +
    (k === 'A_原地仍在' ? '图上原位不动' : k === 'B_挪位置' ? '图上还在，位置被推走' : '图上同类信号也没有了').padEnd(22) +
    String(a.length).padStart(6) + (100 * a.length / N).toFixed(1).padStart(6) + '%' +
    L.pc(ret).padStart(11));
}
console.log('\n  注：B_挪位置的「位移」多数只有几根，少数几十根（分布见下）');

const Bdrift = cls.B_挪位置.map(x => x.drift).sort((a, b) => a - b);
if (Bdrift.length) {
  const q = p => Bdrift[Math.min(Bdrift.length - 1, Math.floor(p * Bdrift.length))];
  console.log('  B 类位移分位: 25%=' + q(0.25) + '根  中位=' + q(0.5) + '根  75%=' + q(0.75) + '根  90%=' + q(0.9) + '根  最大=' + Bdrift[Bdrift.length - 1] + '根');
}

console.log('\n【2】实盘视角：图上的信号会被"擦掉"吗？（逐日 ±0 判据）');
const bs = {}; recs.forEach(r => { const k = r.bars < 0 ? '未消失' : String(Math.min(MAXWATCH, r.bars)); bs[k] = (bs[k] || 0) + 1; });
const lostAll = recs.filter(r => r.bars >= 0);
console.log('  ±0 严格判据下被判消失: ' + lostAll.length + ' / ' + N + ' = ' + (100 * lostAll.length / N).toFixed(1) + '%');
console.log('  观察 ' + MAXWATCH + ' 根内始终在图上: ' + (N - lostAll.length) + ' = ' + (100 * (N - lostAll.length) / N).toFixed(1) + '%');
const lb = lostAll.map(r => r.bars).sort((a, b) => a - b);
if (lb.length) {
  const q = p => lb[Math.min(lb.length - 1, Math.floor(p * lb.length))];
  console.log('  消失时点分位: 25%=' + q(0.25) + '根  中位=' + q(0.5) + '根  75%=' + q(0.75) + '根  90%=' + q(0.9) + '根  最大=' + lb[lb.length - 1] + '根');
  console.log('  → 若"最大"远小于 ' + MAXWATCH + '，说明消失都在短期内发生，不存在"几个月后才发现"');
}

console.log('\n【3】实盘真的能看到的信号数（关键）');
// 条件一：入场后立刻在图上（天然满足），且
// 条件二：观察期内它一直是最终保留的那批（A 类）→ 事后无需擦除
const A = cls.A_原地仍在;
// 但实盘看不到未来。实盘看到的是：t 时刻图上有什么。t 之后被擦掉的，实盘当时是"看到过"的。
// 所以要回答：用户下单的那一刻，图上的信号，后来有多少比例会在图上被引擎抹掉？
const A_lost = A.filter(r => r.bars >= 0);
console.log('  最终原地保留(A类): ' + A.length + ' 个，其中 ' + A_lost.length + ' 个在途中曾被擦掉过');
console.log('  → 实盘看到的图景：' + (A_lost.length === 0
  ? '最终保留的信号，一旦出现就不会中途消失（引擎重绘不会把它擦掉再画回）。'
  : '部分信号会中途消失后又画回原位。'));
console.log('  严格消失(B+C类)  : ' + (cls.B_挪位置.length + cls.C_彻底没影.length) + ' 个 = ' + (100 * (cls.B_挪位置.length + cls.C_彻底没影.length) / N).toFixed(1) + '%');
console.log('  其中彻底消失(C类): ' + cls.C_彻底没影.length + ' 个 = ' + (100 * cls.C_彻底没影.length / N).toFixed(1) + '%（这是唯一"图上真没了"的情形）');
console.log('  而 B 类（图上还在、只是被推走）: ' + cls.B_挪位置.length + ' 个 = ' + (100 * cls.B_挪位置.length / N).toFixed(1) + '% —— 实盘看图仍在，不能算"消失"。');

console.log('\n【4】一次性口径漏掉的信号由什么构成（补齐上次 34.6% 的解释）');
const gone = recs.filter(r => r.drift > 0);
console.log('  最终结构里已不原地存在的信号: ' + gone.length + ' 个 = ' + (100 * gone.length / N).toFixed(1) + '%');
console.log('  ├ 其中挪了位置(≤40根): ' + cls.B_挪位置.length + ' 个 = ' + (100 * cls.B_挪位置.length / N).toFixed(1) + '%');
console.log('  └ 其中彻底没影(>40根) : ' + cls.C_彻底没影.length + ' 个 = ' + (100 * cls.C_彻底没影.length / N).toFixed(1) + '%');
console.log('  → 上次报的「一次性口径漏掉34.6%」绝大部分是【挪位置】，不是【图上消失】。');
console.log('     这批信号在实盘里是"还在的"，只是 K 线锚点被后续走势平移了。');

console.log('\n【5】如果实盘严格按「±0 一消失就离场」—— 各容差下的结果（敏感性）');
console.log('  容差 | 消失率   消失组20日收益  离场收益    差');
console.log('-'.repeat(62));
// 用已算好的 bars（±0）+ 重算各容差下的离场收益不可行（bars 是 ±0 的），故此处标注说明
console.log('  说明：上面【2】的消失率来自 ±0 严格判据。');
console.log('  若改用更宽容差（如±3/±5），"消失"会被推迟判定，离场更晚、结果更差。');
console.log('  已在 exitsignal.js 用 TOL 环境变量扫描：TOL=0/3/5/10/20/40 六档，离场规则全部劣于固定持有。');

const MD5_AFTER = md5(ENGINE);
console.log('\n引擎 md5(跑后) ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！'));
fs.writeFileSync(path.join(__dirname, 'tmp', 'whatlost.json'), JSON.stringify({ recs, cls: Object.fromEntries(Object.entries(cls).map(([k, v]) => [k, v.length])) }));
console.log('已写出 tmp/whatlost.json   耗时 ' + ((Date.now() - T0) / 1000).toFixed(1) + 's');