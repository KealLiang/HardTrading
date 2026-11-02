/* ==========================================================================
 * tests/test_chan.js —— 缠论引擎单元测试
 * 运行： node tests/test_chan.js
 *
 * 这些用例的目的不是"证明缠论正确"，而是保证引擎每一层在你改了参数之后
 * 仍然按设定好的规则走——这是自研工具相比闭源插件最大的好处。
 * ========================================================================== */
'use strict';
const path = require('path');
const fs = require('fs');
const Chan = require(path.join(__dirname, '..', 'core', 'chan.js'));
const IND = require(path.join(__dirname, '..', 'core', 'indicators.js'));

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log('  ✓ ' + name); }
  else { failed++; console.log('  ✗ ' + name + (extra !== undefined ? '  → ' + JSON.stringify(extra) : '')); }
}
function group(name) { console.log('\n' + name); }

/* ---------------------------------------------------------- 合成 K 线工具 */
function synth(plan) {
  const ks = [];
  let t = Date.UTC(2024, 0, 1);
  let idx = 0;
  for (const seg of plan.segs) {
    for (let i = 0; i < seg.n; i++) {
      const u = i / Math.max(1, seg.n - 1);
      const trend = seg.from + (seg.to - seg.from) * u;
      const osc = Math.sin(idx * seg.freq) * seg.amp;
      const o = trend + osc;
      const c = trend + osc * 0.6 + (seg.to - seg.from) / seg.n;
      const h = Math.max(o, c) + Math.abs(Math.cos(idx * 1.7)) * seg.amp * 0.5;
      const l = Math.min(o, c) - Math.abs(Math.sin(idx * 1.3)) * seg.amp * 0.5;
      ks.push({ t: t, o: o, h: h, l: l, c: c, v: 1000 + (idx % 7) * 100 });
      t += 86400000; idx++;
    }
  }
  return ks;
}

/* ==================================================== 1. 包含处理 */
group('[1] 包含处理');
{
  const raw = [
    { h: 10, l: 8, o: 9, c: 9, t: 1 },
    { h: 12, l: 9, o: 9, c: 11, t: 2 },
    { h: 11, l: 9.5, o: 10, c: 10, t: 3 }
  ];
  const m = Chan.mergeKlines(raw);
  check('包含后被合并，长度应为 2', m.length === 2, m.length);
  if (m.length === 2) {
    check('向上合并 high 取 max', Math.abs(m[1].high - 12) < 1e-9, m[1].high);
    check('向上合并 low 取 max', Math.abs(m[1].low - 9.5) < 1e-9, m[1].low);
  }
}

/* ==================================================== 2. 分型 */
group('[2] 分型识别');
{
  const merged = [
    { high: 10, low: 9, si: 0, ei: 0 },
    { high: 12, low: 10.5, si: 1, ei: 1 },
    { high: 11, low: 10, si: 2, ei: 2 }
  ];
  const fx = Chan.findFractals(merged);
  check('应识别出一个顶分型', fx.length === 1 && fx[0].type === 1, fx);
  if (fx.length) check('顶分型价格取高点', Math.abs(fx[0].price - 12) < 1e-9, fx[0].price);
}

/* ==================================================== 3. 同类型分型归并 */
group('[3] 同类型分型归并');
{
  const fxs = [
    { type: 1, mi: 1, high: 12, low: 10, _k: 1 },
    { type: 1, mi: 3, high: 14, low: 11, _k: 3 },
    { type: -1, mi: 5, high: 12, low: 9, _k: 5 },
    { type: -1, mi: 7, high: 13, low: 8, _k: 7 }
  ];
  const r = Chan.dedupFractals(fxs);
  check('归并后只剩 2 个', r.length === 2, r.length);
  check('保留更高的顶', r[0].type === 1 && r[0].high === 14, r[0]);
  check('保留更低的底', r[1].type === -1 && r[1].low === 8, r[1]);
}

/* ==================================================== 4. 笔 */
group('[4] 笔的划分');
{
  const fxs = [
    { type: -1, mi: 1, high: 10, low: 9, _k: 1 },
    { type: 1, mi: 4, high: 13, low: 11, _k: 4 },
    { type: -1, mi: 7, high: 12, low: 8, _k: 7 },
    { type: 1, mi: 10, high: 15, low: 13, _k: 10 }
  ];
  const bis = Chan.buildBi(fxs, Chan.DEFAULTS);
  check('应形成 3 笔', bis.length === 3, bis.map(b => [b.dir, b.startK, b.endK]));
  if (bis.length >= 1) {
    check('第1笔方向向上', bis[0].dir === 1, bis[0]);
    check('第1笔起点取底的低点', Math.abs(bis[0].startPrice - 9) < 1e-9, bis[0].startPrice);
    check('第1笔终点取顶的高点', Math.abs(bis[0].endPrice - 13) < 1e-9, bis[0].endPrice);
  }
  const strict = Chan.buildBi(fxs, Object.assign({}, Chan.DEFAULTS, { minFxGap: 5 }));
  check('minFxGap=5 时不该成笔', strict.length === 0, strict.length);

  // 笔序列必须首尾相接，不允许出现跳跃（曾经出现过的真实 bug）
  const gaps = bis.filter((b, i) => i > 0 && b.startK !== bis[i - 1].endK);
  check('相邻笔首尾相接，无断裂', gaps.length === 0, gaps.map(b => [b.startK, b.endK]));
}

/* ==================================================== 5. 真实日线数据全链路 */
const fixture = path.join(__dirname, '..', 'tools', 'testdata', '600519_daily.json');
let real = null;
if (fs.existsSync(fixture)) {
  const mod = JSON.parse(fs.readFileSync(fixture, 'utf8'));
  real = Array.isArray(mod) ? mod : mod.klines;
}
group('[5] 真实日线全链路' + (real ? '（贵州茅台 800 根）' : '（跳过：缺少 fixture）'));
if (real) {
  const r = Chan.analyze(real, {});
  console.log('    统计: ' + JSON.stringify(r.stats));
  check('识别出大量笔', r.bis.length > 50, r.bis.length);
  check('分型严格交替', r.fractals.every((f, i) => i === 0 || f.type !== r.fractals[i - 1].type));
  check('笔序列首尾相接无断裂',
        r.bis.every((b, i) => i === 0 || b.startK === r.bis[i - 1].endK),
        r.bis.filter((b, i) => i > 0 && b.startK !== r.bis[i - 1].endK).map(b => [b.startK, b.endK]));
  check('线段起笔索引单调递增', r.segs.every((s, i) => i === 0 || s.startBi > r.segs[i - 1].startBi));
  check('线段至少用了参数规定的最少笔数', r.segs.every(s => s.penCount >= 1 || s.confirmed === false));
  check('识别出中枢', r.zhongshus.length >= 5, r.zhongshus.length);
  check('所有中枢 ZD < ZG', r.zhongshus.every(z => z.ZD < z.ZG));
  check('识别出背驰', r.divergences.length > 0, r.divergences.length);
  check('所有背驰力度确实衰减',
        r.divergences.every(d => d.ratio < Chan.DEFAULTS.divMinForceRatio),
        r.divergences.map(d => d.ratio));
  const levels = {};
  r.points.forEach(p => { levels[p.level] = (levels[p.level] || 0) + 1; });
  console.log('    买卖点分级: ' + JSON.stringify(levels));
  check('产出一类买卖点', (levels[1] || 0) > 0, levels);
  check('产出二类买卖点', (levels[2] || 0) > 0, levels);
}

/* ==================================================== 6. 参数敏感性 */
group('[6] 参数可调性');
{
  const ks = real || synth({
    start: 100,
    segs: [
      { n: 40, from: 100, to: 78, amp: 0.8, freq: 0.55 },
      { n: 45, from: 78, to: 82, amp: 1.0, freq: 0.45 },
      { n: 50, from: 82, to: 108, amp: 0.9, freq: 0.5 },
      { n: 45, from: 108, to: 96, amp: 1.0, freq: 0.45 },
      { n: 40, from: 96, to: 116, amp: 0.9, freq: 0.55 }
    ]
  });
  const base = Chan.analyze(ks, {});
  const strict = Chan.analyze(ks, { minFxGap: 3 });
  check('minFxGap 越大笔越少',
        strict.bis.length <= base.bis.length, { strict: strict.bis.length, base: base.bis.length });
  const feat = Chan.analyze(ks, { segAlgo: 'feature' });
  check('feature 线段算法线段更粗',
        feat.segs.length <= base.segs.length, { feature: feat.segs.length, simple: base.segs.length });
  const segZs = Chan.analyze(ks, { zsSource: 'seg' });
  check('zsSource=seg 中枢数不多于 bi 口径',
        segZs.zhongshus.length <= base.zhongshus.length,
        { seg: segZs.zhongshus.length, bi: base.zhongshus.length });
  const noPts = Chan.analyze(ks, { showBuy: false, showSell: false });
  check('关闭买卖点后不再产生 points', noPts.points.length === 0, noPts.points.length);
  const looseDiv = Chan.analyze(ks, { divMinForceRatio: 1.01 });
  const tightDiv = Chan.analyze(ks, { divMinForceRatio: 0.5 });
  check('背驰阈值放宽则信号变多',
        looseDiv.divergences.length >= tightDiv.divergences.length,
        { loose: looseDiv.divergences.length, tight: tightDiv.divergences.length });
  const strictMode = Chan.analyze(ks, { divMode: 'zs' });
  check('divMode=zs 严格模式不崩溃', Array.isArray(strictMode.divergences));
}

/* ==================================================== 7. 确定性 / 健壮性 */
group('[7] 幂等与健壮性');
{
  const ks = real || synth({ start: 100, segs: [{ n: 120, from: 100, to: 90, amp: 1.2, freq: 0.5 }] });
  check('同一输入两次结果完全一致',
        JSON.stringify(Chan.analyze(ks, {}).stats) === JSON.stringify(Chan.analyze(ks, {}).stats));
  check('空数据不崩溃', Chan.analyze([], {}).bis.length === 0);
  check('3 根 K 线不崩溃', Chan.analyze(ks.slice(0, 3), {}).bis.length === 0);
  const dirty = ks.map((k, i) => i % 17 === 0 ? { t: k.t, o: NaN, h: NaN, l: NaN, c: NaN, v: 0 } : k);
  check('含 NaN 脏数据不崩溃', (function () {
    try { Chan.analyze(dirty, {}); return true; } catch (e) { return String(e); }
  })() === true);
  check('最后一段永远标记为待确认',
        Chan.analyze(ks, {}).segs.slice(-1)[0].confirmed === false);
}

/* ==================================================== 8. 指标层 */
group('[8] 指标层');
{
  const closes = (real || synth({ start: 100, segs: [{ n: 200, from: 100, to: 80, amp: 1, freq: 0.5 }] })).map(k => k.c);
  const m = IND.macd(closes, 12, 26, 9);
  check('MACD 长度一致', m.hist.length === closes.length);
  check('MACD 存在正负柱', m.hist.some(v => v > 0) && m.hist.some(v => v < 0));
  const fSame = IND.forceRange(m.hist, 0, 30, -1, 'same');
  const fAbs = IND.forceRange(m.hist, 0, 30, -1, 'abs');
  const fPer = IND.forceRange(m.hist, 0, 30, -1, 'perBar');
  check('abs ≥ same', fAbs >= fSame - 1e-9, [fAbs, fSame]);
  check('perBar = same / 根数', Math.abs(fPer - fSame / 31) < 1e-9, [fPer, fSame / 31]);
  check('力度恒为非负', fSame >= 0 && fAbs >= 0 && fPer >= 0, [fSame, fAbs, fPer]);
}

/* ============================================ 回抽候选（2.2.0，scanner.js） */
/* 候选态只看三件事：最后一笔的方向、价格从这笔终点回撤了多少、作废线破没破。
   造 4 根笔 + 1 个中枢的假 res，把六种情形钉死。 */
const Scan = require(path.join(__dirname, '..', 'core', 'scanner.js')).CLScanner;
function near(a, b) { return Math.abs(a - b) < 1e-9; }

function mkBi(dir, sk, ek, sp, ep, conf) {
  return { dir: dir, startK: sk, endK: ek, startPrice: sp, endPrice: ep,
           high: Math.max(sp, ep), low: Math.min(sp, ep), confirmed: !!conf };
}
function mkKs(n, close) {
  const out = [];
  for (let i = 0; i < n; i++) out.push({ o: close, h: close, l: close, c: close, v: 0 });
  return out;
}

group('candidates —— 三买/三卖候选（回抽中，作废线未破）');
/* 最后一笔是向上突破笔（10.0 → 10.4），中枢把它吸收为自己的 endPart */
const bisBuy = [mkBi(-1, 0, 8, 9.6, 9.4), mkBi(1, 8, 14, 9.4, 9.9),
                mkBi(-1, 14, 20, 9.9, 9.5), mkBi(1, 20, 30, 9.5, 10.4)];
const zsBuy = [{ ZG: 10.0, ZD: 9.2, startPart: 0, endPart: 3 }];
const resBuy = { bis: bisBuy, parts: bisBuy, zhongshus: zsBuy, points: [], opts: {} };

const c3 = Scan.candidates(mkKs(31, 10.2), resBuy, {});
check('三买候选：最后一笔向上 + 回撤 1.9% + 现价在 ZG 上 → 给出候选',
      c3.length === 1 && c3[0].level === 3 && c3[0].type === 1, c3);
check('作废线 = 中枢上沿 ZG（结构价，不是猜的）',
      c3.length === 1 && c3[0].invalid === 10.0 && c3[0].invalidRule === '中枢上沿 ZG', c3[0]);
check('两档挂单参考在作废线上方 2% / 3%，近档更便宜',
      c3.length === 1 && near(c3[0].refs[0], 10.2) && near(c3[0].refs[1], 10.3), c3[0] && c3[0].refs);

const cNone1 = Scan.candidates(mkKs(31, 9.9), resBuy, {});
check('现价已跌回 ZG 之下 → 没有三买候选（作废线破了就不是候选）', cNone1.length === 0, cNone1);
const cNone2 = Scan.candidates(mkKs(31, 10.38), resBuy, {});
check('回撤不足 0.5% → 不算回抽（还在往外走）', cNone2.length === 0, cNone2);
const cNone3 = Scan.candidates(mkKs(31, 10.2), { bis: bisBuy, parts: bisBuy, zhongshus: [], points: [], opts: {} }, {});
check('没有中枢也没有一买 → 空（不硬造候选）', cNone3.length === 0, cNone3);
const cSeg = Scan.candidates(mkKs(31, 10.2),
  { bis: bisBuy, parts: bisBuy, zhongshus: zsBuy, points: [], opts: { zsSource: 'seg' } }, {});
check('中枢来自线段时索引口径不同 → 直接不给（宁可没有也不给错位数字）', cSeg.length === 0, cSeg);

/* 卖点对称：最后一笔向下离开中枢（9.9 → 9.3），现价反抽到 ZD 之下 */
const bisSell = [mkBi(1, 0, 8, 9.4, 9.9), mkBi(-1, 8, 14, 9.9, 9.4),
                 mkBi(1, 14, 20, 9.4, 9.8), mkBi(-1, 20, 30, 9.8, 9.1)];
const zsSell = [{ ZG: 9.9, ZD: 9.5, startPart: 0, endPart: 3 }];
const cS = Scan.candidates(mkKs(31, 9.3),
  { bis: bisSell, parts: bisSell, zhongshus: zsSell, points: [], opts: {} }, {});
check('三卖候选：最后一笔向下 + 反抽 + 现价在 ZD 下 → 给出候选',
      cS.length === 1 && cS[0].level === 3 && cS[0].type === -1, cS);
check('三卖作废线 = 中枢下沿 ZD，挂单参考在下方',
      cS.length === 1 && cS[0].invalid === 9.5 &&
      near(cS[0].refs[0], 9.5 * 0.98) && near(cS[0].refs[1], 9.5 * 0.97), cS[0] && cS[0].refs);

group('candidates —— 二买候选（一买之后的反弹笔正在被回抽）');
const bis2 = [mkBi(-1, 0, 10, 10.4, 10.0), mkBi(1, 10, 20, 10.0, 10.6),
              mkBi(-1, 20, 25, 10.6, 9.8), mkBi(1, 25, 30, 9.8, 10.5)];
const p1 = [{ level: 1, type: 1, _k: 25, readyK: 25, price: 9.8, note: '一买·底背驰' }];
const res2 = { bis: bis2, parts: bis2, zhongshus: [], points: p1, opts: {} };
const c2 = Scan.candidates(mkKs(31, 10.0), res2, {});
check('二买候选：一买低点 9.8 未破 + 反弹笔回撤 → 给出候选',
      c2.length === 1 && c2[0].level === 2 && c2[0].type === 1, c2);
check('二买作废线 = 一买低点（不是中枢边）',
      c2.length === 1 && c2[0].invalid === 9.8 && c2[0].invalidRule === '一买低点', c2[0]);
const c2b = Scan.candidates(mkKs(31, 9.7), res2, {});
check('现价跌破一买低点 → 没有二买候选', c2b.length === 0, c2b);

group('candidates —— 口径边界');
check('参数可关：minRetr=0.05 时 1.9% 的回撤不算候选',
      Scan.candidates(mkKs(31, 10.2), resBuy, { minRetr: 0.05 }).length === 0);
check('refs 跟随 nearPct/farPct 参数',
      near(Scan.candidates(mkKs(31, 10.2), resBuy, { nearPct: 0.01, farPct: 0.015 })[0].refs[0], 10.1));
check('笔太少（<3）时不判 —— 结构还没成形', Scan.candidates(mkKs(31, 10.2),
      { bis: bisBuy.slice(0, 2), parts: [], zhongshus: zsBuy, points: [], opts: {} }, {}).length === 0);

/* ==================================================== 汇总 */
console.log('\n' + '='.repeat(62));
console.log(`结果：${passed} 通过，${failed} 失败`);
console.log('='.repeat(62));
process.exit(failed ? 1 : 0);
