/* ==========================================================================
 * walkforward.js —— 未来函数（look-ahead / 重绘）检测
 *
 * 原理：如果引擎没有未来函数，那么「只用截止 T 的数据」算出的第 j 个结构，
 *      必须和「用全部数据」算出的第 j 个结构完全一致（j 指向已定型的结构）。
 *      换句话说：新数据只能**在末尾追加**，不能改写已经定型的历史。
 *
 * 判定口径：
 *   - 每一层（笔/线段/中枢/背驰/买卖点）的**最后一个**元素天然是「待确认」，
 *     允许被后续数据修改（缠论本身如此，图上画成虚线）。
 *   - 除此之外任何位置出现不一致，就是重绘 = 未来函数，必须修。
 *   - MACD 是另外查的：截断序列算出的 hist 必须与全序列同位完全相同。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const Chan = require('../core/chan.js');

const DIR = path.join(__dirname, 'testdata');

function load(file) {
  const j = JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));
  return j.klines || j;
}

/* ---------------- 结构指纹 ---------------- */
const key = {
  bi: b => [b.startK, b.endK, b.dir, r(b.startPrice), r(b.endPrice)].join('|'),
  seg: s => [s.startK, s.endK, s.dir, r(s.startPrice), r(s.endPrice), s.penCount].join('|'),
  zs: z => [z.startPart, z.endPart, z.startK, z.endK, r(z.ZD), r(z.ZG), z.partCount].join('|'),
  div: d => [d.type, d.kind, d.targetK, r(d.targetPrice), r(d.ratio), d.basis].join('|'),
  pt: p => [p.level, p.type, p._k, r(p.price), p.note].join('|')
};
function r(v) { return typeof v === 'number' ? v.toFixed(6) : String(v); }

/**
 * 单层比对：要求 cut[j] === full[j]，j < cut.length - keepTail
 * @returns {{fail:number, cases:Array, tailChurn:number}}
 */
function cmpLayer(name, cutArr, fullArr, kf, keepTail, ctx) {
  const limit = cutArr.length - keepTail;
  let fail = 0;
  const cases = [];
  for (let j = 0; j < limit; j++) {
    const a = kf(cutArr[j]);
    const b = fullArr[j] ? kf(fullArr[j]) : '<MISSING>';
    if (a !== b && fail < 3 && cases.length < 3) {
      cases.push(`${name}[${j}] cut=${a} full=${b}`);
    }
    if (a !== b) fail++;
  }
  return { fail, cases, ctx };
}

/**
 * 对一份数据跑滚动检测
 * @param keepTail 末尾保留几个元素作为「待确认区」（默认每层最后一个）
 */
/**
 * 分层比对的口径说明：
 *   笔/线段/中枢/背驰 这四层严格按时间顺序追加，可以直接按下标逐一比对。
 *   买卖点不行 —— 它按「一类→三类→二类」分组排列，一旦最后一个待确认背驰
 *   在后续数据里被撤销，分组内部的下标就会整体错位（表现为伪重绘）。
 *   所以买卖点要按 level 拆成三条子序列，各自沿用同样的「末尾待确认」口径。
 */
function cmpPoints(curPts, fullPts, cut) {
  const bad = [];
  [1, 2, 3].forEach(level => {
    const c = curPts.filter(p => p.level === level);
    const f = fullPts.filter(p => p.level === level);
    const res = cmpLayer(level + '类点', c, f, key.pt, 1, cut);
    if (res.fail) bad.push(`${level}类点:${res.fail}`, ...res.cases.map(s => `cut=${cut} ${s}`));
  });
  return bad;
}

function runSeries(file, klines, opts, cuts, keepTailMap) {
  const full = Chan.analyze(klines, opts);
  const report = { file, total: 0, bad: 0, detail: [], macdBad: 0, tailChurn: {} };

  for (const cut of cuts) {
    if (cut < 30 || cut > klines.length) continue;
    const slice = klines.slice(0, cut);
    const cur = Chan.analyze(slice, opts);
    report.total++;

    let dirty = false;

    // —— A. 指标因果性：MACD 每一位必须完全一致 ——
    const hc = cur.macd.hist, hf = full.macd.hist;
    let macdDiff = 0;
    for (let j = 0; j < hc.length; j++) {
      if (Math.abs(hc[j] - hf[j]) > 1e-9) macdDiff++;
    }
    if (macdDiff) { report.macdBad++; dirty = true; }

    // —— B~F. 各层历史结构一致性 ——
    const layers = [
      ['笔', cur.bis, full.bis, key.bi, keepTailMap.bi],
      ['线段', cur.segs, full.segs, key.seg, keepTailMap.seg],
      ['中枢', cur.zhongshus, full.zhongshus, key.zs, keepTailMap.zs],
      ['背驰', cur.divergences, full.divergences, key.div, keepTailMap.div]
    ];
    const badLayers = [];
    layers.forEach(([nm, c, f, kf, kt]) => {
      const res = cmpLayer(nm, c, f, kf, kt, cut);
      if (res.fail) { badLayers.push(`${nm}:${res.fail}`); report.detail.push(...res.cases.map(s => `cut=${cut} ${s}`)); dirty = true; }
    });
    const ptBad = cmpPoints(cur.points, full.points, cut);
    if (ptBad.length) {
      badLayers.push(ptBad[0]);
      report.detail.push(...ptBad.slice(1).map(s => `cut=${cut} ${s}`));
      dirty = true;
    }

    if (dirty) {
      report.bad++;
      if (report.detail.length < 12) {
        report.detail.push(`  └ cut=${cut} (${klines[cut - 1] && klines[cut - 1].t}) 违规层: ${badLayers.join(', ')}${macdDiff ? ' MACD差异点:' + macdDiff : ''}`);
      }
    }
  }
  return report;
}

/* ------------------------------------------------------------------ 主流程 */
console.log('==================================================================');
console.log(' ChanLens 未来函数 / 重绘检测（滚动推进比对）');
console.log(' 判定：j 号结构在「截止T」与「全量」两笔计算中必须完全一致');
console.log(' 每层末尾 N 个元素为待确认区，不计入违规');
console.log('==================================================================\n');
const DATASETS = ['600519_daily.json', '000001_daily.json', '300750_daily.json', '600519_30m.json'];
const VARIANTS = [
  { name: '默认 (笔中枢+简化线段+滚动三笔背驰)', opts: {} },
  { name: '线段中枢 zsSource=seg', opts: { zsSource: 'seg' } },
  { name: '特征序列线段 segAlgo=feature', opts: { segAlgo: 'feature' } },
  { name: '严格中枢背驰 divMode=zs', opts: { divMode: 'zs' } }
];

console.log('==================================================================');
console.log(' ChanLens 未来函数 / 重绘检测（滚动推进比对）');
console.log(' 判定：j 号结构在「截止T」与「全量」两笔计算中必须完全一致');
console.log(' 每层末尾 N 个元素为待确认区，不计入违规');
console.log('==================================================================\n');

let grandFail = 0;
for (const v of VARIANTS) {
  console.log('── 参数组合：' + v.name);
  for (const ds of DATASETS) {
    let klines;
    try { klines = load(ds); } catch (e) { console.log('  ' + ds + ' 读取失败'); continue; }
    const cuts = [];
    for (let c = 120; c <= klines.length; c += 5) cuts.push(c);
    cuts.push(klines.length - 1, klines.length - 2, klines.length - 3);

    const rep = runSeries(ds, klines, v.opts, cuts, { bi: 1, seg: 1, zs: 1, div: 1, pt: 1 });
    const tag = rep.bad === 0 ? '✅ 无重绘' : '❌ 发现 ' + rep.bad + ' 处';
    console.log(`  ${ds.padEnd(20)} n=${String(klines.length).padStart(4)} 切点${String(rep.total).padStart(4)}个  ${tag}` +
      (rep.macdBad ? `  ⚠ MACD不一致:${rep.macdBad}` : '  MACD因果 ✓'));
    if (rep.detail.length) console.log('     ' + rep.detail.slice(0, 6).join('\n     '));
    grandFail += rep.bad + rep.macdBad;
  }
  console.log('');
}

console.log('==================================================================');
console.log(grandFail === 0
  ? '结论：所有组合下，历史结构在新增数据后均未被改写 —— 无未来函数。'
  : '结论：存在 ' + grandFail + ' 处重绘，需要修复。');
console.log('==================================================================');

/* ==========================================================================
 * 补充压力测试
 * ======================================================================== */

/* ① 盘中未收盘 K 线：最后一根 bar 的收盘价/最高价还在变，
 *    必须证明这种扰动只影响「正在进行」的结构，不污染已定型的历史。 */
function testIntradayTick(klines, opts) {
  let bad = 0, cases = [];
  const make = (mut) => {
    const arr = klines.slice();
    const last = Object.assign({}, arr[arr.length - 1]);
    mut(last);
    arr[arr.length - 1] = last;
    return arr;
  };
  // 三种盘中快照：收在最高 / 收在最低 / 最高最低都不同
  const variants = {
    '收=高': make(k => { k.c = k.h; }),
    '收=低': make(k => { k.c = k.l; }),
    '高更高': make(k => { k.h = k.h * 1.05; k.c = k.h; })
  };
  const base = Chan.analyze(klines, opts);
  for (const name in variants) {
    const r = Chan.analyze(variants[name], opts);
    [['笔', base.bis, r.bis, key.bi],
     ['线段', base.segs, r.segs, key.seg],
     ['中枢', base.zhongshus, r.zhongshus, key.zs],
     ['背驰', base.divergences, r.divergences, key.div]].forEach(([nm, a, b, kf]) => {
      const res = cmpLayer(nm, a, b, kf, 1, 0);
      if (res.fail) { bad += res.fail; cases.push(`  ${name} → ${nm} 受影响 ${res.fail} 项: ${res.cases[0] || ''}`); }
    });
  }
  return { bad, cases };
}

/* ② 病态数据：不崩溃 + 不产生历史重绘 + 必须真的能算出结构（否则等于没测到） */
let _seed = 20240917;
function rnd() { _seed = (_seed * 1103515245 + 12345) & 0x7fffffff; return _seed / 0x7fffffff; }

function pathological() {
  const n = 300;
  const flat = [], limitUp = [], gapDown = [], wobble = [];
  let p = 10;
  for (let i = 0; i < n; i++) {
    flat.push({ t: '2024-01-01', o: 10, h: 10, l: 10, c: 10, v: 1 });      // 四价合一
    limitUp.push({ t: '2024-01-01', o: p, h: p, l: p, c: p, v: 1 });        // 一字板
    gapDown.push({ t: '2024-01-01', o: p, h: p, l: p * 0.5, c: p * 0.9, v: 1 });
    p = p * (1 + (rnd() - 0.45) * 0.08);                                   // 随机游走，保证分型有间隔
    // 带实体/影线的随机 K 线：更接近真实行情形态
    const base = 10 * (1 + Math.sin(i / 11) * 0.4) + (rnd() - 0.5) * 1.2;
    const body = Math.abs(rnd() - 0.5) * 0.9 + 0.05;
    wobble.push({
      t: '2024-01-01', o: base, c: base + (rnd() - 0.5) * body,
      h: base + body * 1.6, l: base - body * 1.6, v: 1
    });
  }
  return {
    '全平盘(四价合一)': flat,
    '一字板(随机阶梯)': limitUp,
    '长下影+跳空': gapDown,
    '随机锯齿(拟真)': wobble,
    'NaN污染': wobble.map((k, i) => i === 150 ? { t: 'x', o: NaN, h: NaN, l: NaN, c: NaN, v: NaN } : k),
    '缺失值undefined': wobble.map((k, i) => i === 151 ? { t: 'x' } : k),
    '极短序列': wobble.slice(0, 3),
    '空序列': []
  };
}

/** 哪些数据集「理应算出结构」——短序列/全平盘允许 0 结构，其余必须有输出才算真测到 */
const EXPECT_STRUCTURE = {
  '全平盘(四价合一)': false, '一字板(随机阶梯)': true, '长下影+跳空': true,
  '随机锯齿(拟真)': true, 'NaN污染': true, '缺失值undefined': true,
  '极短序列': false, '空序列': false
};

console.log('\n\n==================================================================');
console.log(' 补充压力测试');
console.log('==================================================================\n');

console.log('① 盘中未收盘 K 线扰动（同样的数据，最后一根 bar 取不同盘中快照）');
['600519_daily.json', '600519_30m.json'].forEach(ds => {
  const klines = load(ds);
  [120, 300, 500, 700, klines.length - 1].filter(c => c < klines.length).forEach(cut => {
    const sub = klines.slice(0, cut);
    const res = testIntradayTick(sub, {});
    console.log(`   ${ds} 截止第${String(cut).padStart(3)}根  ${sub[sub.length - 1].t}  ` +
      (res.bad === 0 ? '✅ 历史结构不受盘中波动影响' : '❌ ' + res.bad + ' 项历史被污染'));
    res.cases.forEach(c => console.log(c));
  });
});

console.log('\n② 病态数据：能否稳定产出（崩溃=不合格），且自身不含未来函数');
const pset = pathological();
for (const nm in pset) {
  let ok = true, note = '';
  try {
    const data = pset[nm];
    const r = Chan.analyze(data, {});
    if (EXPECT_STRUCTURE[nm] && r.bis.length === 0) { ok = false; note = '❗ 本应算出笔却为 0 —— 数据或引擎有异常'; }
    const n2 = (data.length >= 2) ? Chan.analyze(data.slice(0, data.length - 1), {}) : null;
    const chk = n2 ? [['笔', n2.bis, r.bis, key.bi], ['线段', n2.segs, r.segs, key.seg],
                      ['中枢', n2.zhongshus, r.zhongshus, key.zs]]
      .map(([a, x, y, kf]) => cmpLayer(a, x, y, kf, 1, 0).fail).reduce((s, v) => s + v, 0) : 0;
    if (chk) { ok = false; note = (note ? note + '；' : '') + '发现 ' + chk + ' 项历史重绘'; }
    if (!note) note = `笔${r.bis.length} 段${r.segs.length} 中枢${r.zhongshus.length} 背驰${r.divergences.length} 点${r.points.length}`;
  } catch (e) { ok = false; note = '抛出异常：' + e.message; }
  console.log(`   ${nm.padEnd(18)} ${ok ? '✅' : '❌'} ${note}`);
}

console.log('\n④ 复权（除权除息）对历史结构的影响 —— 这是算法之外的真实重绘源');
{
  const klines = load('600519_daily.json');
  const structural = (a, b) => {
    // 只看「形状」：分型所在 K 线序号序列是否一致（价格等比缩放不改变大小关系）
    const fxA = a.fractals.map(f => f._k + ':' + f.type);
    const fxB = b.fractals.map(f => f._k + ':' + f.type);
    return fxA.join(',') === fxB.join(',');
  };

  // (a) 整体等比缩放 —— 模拟「除权日之前的所有历史统一乘 k」，形态不应改变
  const scaled = klines.map(k => ({ t: k.t, o: k.o * 1.7, h: k.h * 1.7, l: k.l * 1.7, c: k.c * 1.7, v: k.v }));
  const base = Chan.analyze(klines, {}), scaledRes = Chan.analyze(scaled, {});
  console.log('   (a) 全序列等比缩放 ×1.7    ' +
    (structural(base, scaledRes) ? '✅ 结构完全一致（除同比例外不影响任何判定）' : '❌ 结构改变'));

  // (b) 分段缩放 —— 模拟「前复权」：除权日之前的历史被重新加权，
  //     此时跨越除权点的局部形态会发生变化（真实的前复权重绘风险就在这里）
  const split = 400;
  const qfqLike = klines.map((k, i) => i < split
    ? { t: k.t, o: k.o * 0.62, h: k.h * 0.62, l: k.l * 0.62, c: k.c * 0.62, v: k.v }
    : k);
  const qfqRes = Chan.analyze(qfqLike, {});
  const sameBars = structural(base, qfqRes);
  console.log('   (b) 前复权式分段缩放(前400根×0.62) ' +
    (sameBars ? '✅ 连分型位置都未变（该股期间形态对缩放不敏感）'
              : '⚠ 分型/笔位置发生变化 —— 前复权会改写跨越除权点的历史结构'));
  console.log('       基准: 笔' + base.bis.length + ' 中枢' + base.zhongshus.length +
              '   分段缩放后: 笔' + qfqRes.bis.length + ' 中枢' + qfqRes.zhongshus.length);
  console.log('       → 结论：回测请用「后复权 hfq」锁定历史价格；前复权只适合看盘。');
}

console.log('\n③ 结构单调性：随数据增长，已定型结构的数量不应减少');
['600519_daily.json', '000001_daily.json'].forEach(ds => {
  const klines = load(ds);
  let prev = 0, violated = 0;
  for (let c = 150; c <= klines.length; c += 1) {
    const r = Chan.analyze(klines.slice(0, c), {});
    const settled = Math.max(0, r.bis.length - 1);   // 去掉待确认的最后一项
    if (settled < prev) violated++;
    prev = Math.max(prev, settled);
  }
  console.log(`   ${ds.padEnd(20)} ${violated === 0 ? '✅ 已定型笔数量单调不减' : '❌ 出现 ' + violated + ' 次倒退'}`);
});
