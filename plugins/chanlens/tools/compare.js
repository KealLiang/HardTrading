/* ==========================================================================
 * tools/compare.js —— 对比不同参数组合下的结构产出，用来挑默认参数
 *                     并诊断背驰为什么没有触发
 * 运行： node tools/compare.js <testdata.json>
 * ========================================================================== */
'use strict';
const path = require('path');
const Chan = require(path.join(__dirname, '..', 'core', 'chan.js'));
const IND = require(path.join(__dirname, '..', 'core', 'indicators.js'));

const file = process.argv[2];
if (!file) { console.error('用法: node tools/compare.js <testdata.json>'); process.exit(1); }
const mod = require(path.resolve(file));
const klines = Array.isArray(mod) ? mod : mod.klines;

function pad(s, w) {
  s = String(s);
  let n = 0;
  for (const ch of s) n += /[\u4e00-\u9fa5（）·／+（）]/.test(ch) ? 2 : 1;
  return s + ' '.repeat(Math.max(0, w - n));
}
function padL(s, w) {
  s = String(s);
  let n = 0;
  for (const ch of s) n += /[\u4e00-\u9fa5（）·／+（）]/.test(ch) ? 2 : 1;
  return ' '.repeat(Math.max(0, w - n)) + s;
}

const variants = [
  ['默认(线段中枢/feature)', {}],
  ['笔中枢 + feature线段', { zsSource: 'bi' }],
  ['笔中枢 + simple线段', { zsSource: 'bi', segAlgo: 'simple' }],
  ['笔中枢 + simple + 更新ZG/ZD', { zsSource: 'bi', segAlgo: 'simple', zsExtendUpdate: true }],
  ['笔中枢 + minFxGap=2', { zsSource: 'bi', minFxGap: 2 }],
  ['笔中枢 + minFxGap=3', { zsSource: 'bi', minFxGap: 3 }],
  ['线段中枢 + simple线段', { segAlgo: 'simple' }],
  ['线段中枢 + simple + 更新ZG/ZD', { segAlgo: 'simple', zsExtendUpdate: true }]
];

console.log('文件: %s   共 %d 根 K 线', path.basename(file), klines.length);
console.log('');
console.log('  ' + pad('参数组合', 28) + padL('笔', 5) + padL('线段', 5) + padL('中枢', 5) +
            padL('背驰', 5) + padL('买卖点', 6) + padL('中枢覆盖', 9));
console.log('  ' + '-'.repeat(64));

const rows = [];
for (const [name, opts] of variants) {
  const r = Chan.analyze(klines, opts);
  rows.push([name, r, opts]);
  const cover = r.zhongshus.length
    ? (r.zhongshus.reduce((s, z) => s + (z.endK - z.startK + 1), 0) / klines.length * 100).toFixed(1) + '%'
    : '0%';
  console.log('  ' + pad(name, 28) + padL(r.stats.biCount, 5) + padL(r.stats.segCount, 5) +
              padL(r.stats.zsCount, 5) + padL(r.stats.divCount, 5) +
              padL(r.stats.pointCount, 6) + padL(cover, 9));
}

console.log('\n线段长度分布（单位：笔）');
rows.forEach(([name, r]) => {
  if (!r.segs.length) return;
  const lens = r.segs.map(s => s.penCount);
  console.log('  ' + pad(name, 28) + '均值 ' + padL((lens.reduce((a, b) => a + b, 0) / lens.length).toFixed(1), 5) +
              '  最长 ' + padL(Math.max.apply(null, lens), 4) + '  [' + lens.join(',') + ']');
});

/* ---------------------------------------------------- 背驰诊断 */
console.log('\n背驰诊断（为什么很多中枢没触发背驰）');
const diagOpts = { zsSource: 'bi', segAlgo: 'simple' };
const rd = Chan.analyze(klines, diagOpts);
const parts = rd.parts;
const hist = rd.macd.hist;
console.log('  共 %d 个中枢，逐个检查「进入段 vs 离开段」：', rd.zhongshus.length);
console.log('  ' + pad('中枢', 20) + padL('段数', 5) + padL('同向', 5) +
            padL('创新极', 7) + padL('前力度', 9) + padL('后力度', 9) + padL('比值', 7) + '  结论');
rd.zhongshus.forEach((z, i) => {
  const seq = Chan.buildSequence ? Chan.buildSequence(parts, rd.zhongshus) : null;
  // 定位该中枢前后的连接波
  let en = null, lv = null;
  if (seq) {
    const pos = seq.findIndex((s, k) => s.type === 'zs' && s.zsIndex === i);
    en = pos > 0 && seq[pos - 1].type === 'conn'
      ? Chan.waveOf(parts, seq[pos - 1].from, seq[pos - 1].to) : null;
    lv = pos >= 0 && seq[pos + 1] && seq[pos + 1].type === 'conn'
      ? Chan.waveOf(parts, seq[pos + 1].from, seq[pos + 1].to) : null;
  }
  const tag = 'Z' + i + ' [' + z.ZD.toFixed(1) + ',' + z.ZG.toFixed(1) + ']';
  let enter = en, leave = lv;
  if (enter) enter.dir = enter.endPrice > enter.startPrice ? 1 : -1;
  if (leave) leave.dir = leave.endPrice > leave.startPrice ? 1 : -1;
  if (!enter || !leave) {
    console.log('  ' + pad(tag, 20) + padL(z.partCount, 5) + '  —— 前后没有连接波可比较');
    return;
  }
  const sameDir = enter.dir === leave.dir;
  let newExt = false;
  if (sameDir && leave.dir > 0) newExt = leave.high > enter.high;
  else if (sameDir) newExt = leave.low < enter.low;
  const fEnter = IND.forceRange(hist, enter.startK, enter.endK, enter.dir, diagOpts.forceMode || 'same');
  const fLeave = IND.forceRange(hist, leave.startK, leave.endK, leave.dir, diagOpts.forceMode || 'same');
  const ratio = fEnter > 0 ? fLeave / fEnter : NaN;
  let verdict = '未触发';
  if (!sameDir) verdict = '方向不同';
  else if (!newExt) verdict = '未创新极值';
  else if (!(ratio < 0.85)) verdict = '力度未衰减(比值≥0.85)';
  else verdict = '★触发背驰';
  console.log('  ' + pad(tag, 20) + padL(z.partCount, 5) + padL(sameDir ? '是' : '否', 5) +
              padL(newExt ? '是' : '否', 7) + padL(fEnter.toFixed(2), 9) + padL(fLeave.toFixed(2), 9) +
              padL(isNaN(ratio) ? '-' : ratio.toFixed(2), 7) + '  ' + verdict);
});
