/* ==========================================================================
 * tests/test_track.js —— 缠论追踪（作战卡）单元测试
 * 运行： node tests/test_track.js
 *
 * 只测纯函数：buildPlan（三句话/失效位规则）、check（动态盯梢判据）、
 * pickSignal 的 refs 组装（失效位引用、移动止盈起点）。不发网络请求。
 * ========================================================================== */
'use strict';
const path = require('path');

global.self = global;
require(path.join(__dirname, '..', 'core', 'chan.js'));
require(path.join(__dirname, '..', 'core', 'scanner.js'));
require(path.join(__dirname, '..', 'core', 'track.js'));
const CLScanner = global.CLScanner;
const CLTrack = global.CLTrack;

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log('  ✓ ' + name); }
  else { failed++; console.log('  ✗ ' + name + (extra !== undefined ? '  → ' + JSON.stringify(extra) : '')); }
}
function group(name) { console.log('\n' + name); }
function near(a, b) { return Math.abs(a - b) < 1e-9; }

group('buildPlan —— 方向跟着信号走（1.7.0）');
/* 二买：refs 里多空各有各的失效位（一买低点 9.8 / 一卖高点 12.8） */
const sig2 = { level: 2, type: 1, note: '二买·回抽不破前低', confirmed: true, price: 10.12,
               refs: { stopBuy: 9.8, stopSell: 12.8, dir: 1, trailLow: 10.05, trailHigh: 11.0,
                       targetHigh: 11.5, targetLow: 9.4, lastClose: 10.5 } };
const p2 = CLTrack.buildPlan(sig2, null, 'daily', { fmtPrice: v => v.toFixed(3) });
check('买点信号 → 方向自动 = 做多', p2.dir === 1, p2.dir);
check('失效位取一买极值价（不是卖点那个）', near(p2.stop, 9.8), p2.stop);
check('第 2 句写明「跌破一买低点」+ 具体数字', /跌破一买低点 9\.800/.test(p2.lines[1]), p2.lines[1]);
check('第 1 句写明级别与信号', /日线级别.*二买·回抽不破前低/.test(p2.lines[0]), p2.lines[0]);
check('第 1 句写明做多', /做多/.test(p2.lines[0]), p2.lines[0]);
check('目标取上方参照（多头用 targetHigh）', near(p2.target, 11.5), p2.target);
check('第 3 句：目标到价减 1/3 + 动盈 + 一卖再减',
      /目标 11\.500 减 1\/3/.test(p2.lines[2]) && /动盈 10\.050/.test(p2.lines[2]) &&
      /一卖/.test(p2.lines[2]), p2.lines[2]);
check('参考入场 = 最新收盘', near(p2.entry, 10.5), p2.entry);

const p2m = CLTrack.buildPlan(sig2, -1, 'daily', { fmtPrice: v => v.toFixed(3) });
check('显式传方向仍然尊重（老记录/调试用）', p2m.dir === -1 && near(p2m.stop, 12.8), p2m);
check('做空文案用「升破一卖高点」', /升破一卖高点 12\.800/.test(p2m.lines[1]), p2m.lines[1]);

const sig3 = { level: 3, type: 1, note: '三买·回抽不入中枢', confirmed: true, price: 11.2,
               refs: { stopBuy: 10.6, stopSell: 10.2, dir: 1, trailLow: 10.9, trailHigh: null, lastClose: 11.2 } };
const p3 = CLTrack.buildPlan(sig3, null, '30m', { fmtPrice: v => v.toFixed(3) });
check('三买失效位 = 跌回中枢（ZG）', /跌回中枢.*10\.600/.test(p3.lines[1]), p3.lines[1]);
check('30 分钟级别写进第 1 句', /30 分钟级别/.test(p3.lines[0]), p3.lines[0]);

group('buildPlan —— 卖点信号 = 做空（对称）');
const sig1s = { level: 1, type: -1, note: '一卖·顶背驰', confirmed: true, price: 12.8,
                refs: { stopBuy: 9.8, stopSell: 12.8, dir: -1, trailLow: 11.0, trailHigh: 12.6,
                        targetHigh: 13.4, targetLow: 11.4, lastClose: 12.3 } };
const p1s = CLTrack.buildPlan(sig1s, null, 'daily', { fmtPrice: v => v.toFixed(3) });
check('卖点信号 → 方向自动 = 做空', p1s.dir === -1, p1s.dir);
check('做空失效位 = 升破一卖高点', /升破一卖高点 12\.800/.test(p1s.lines[1]), p1s.lines[1]);
check('做空动盈起点 = 最近反抽高点', /动盈 12\.600/.test(p1s.lines[2]), p1s.lines[2]);
check('做空目标取下方参照（targetLow）', near(p1s.target, 11.4), p1s.target);
check('做空第 3 句含回补语义', /一买|回补/.test(p1s.lines[2]), p1s.lines[2]);

const p3s = CLTrack.buildPlan({ level: 3, type: -1, note: '三卖·反抽不入中枢', confirmed: true, price: 9.0,
  refs: { stopBuy: 10.6, stopSell: 10.2, dir: -1, trailLow: null, trailHigh: 9.6, lastClose: 9.1 } },
  null, 'weekly', { fmtPrice: v => v.toFixed(3) });
check('三卖失效位 = 升回中枢（ZD）', /升回中枢.*10\.200/.test(p3s.lines[1]), p3s.lines[1]);

group('buildPlan —— 未定型提示与结构缺失兜底');
const pf = CLTrack.buildPlan({ level: 2, type: 1, note: '二买·回抽不破前低', confirmed: false, price: 10.1,
  refs: { stopBuy: 9.8, stopSell: null, dir: 1, trailLow: 10.0, trailHigh: null, lastClose: 10.4 } },
  null, 'daily', { fmtPrice: v => v.toFixed(3) });
check('未定型时第 2 句带警示', /未定型/.test(pf.lines[1]), pf.lines[1]);
const pno = CLTrack.buildPlan({ level: 3, type: 1, note: '三买·回抽不入中枢', confirmed: true, price: 11,
  refs: { stopBuy: null, stopSell: null, dir: 1, trailLow: null, trailHigh: null, lastClose: 11 } },
  null, 'daily', { fmtPrice: v => v.toFixed(3) });
check('没有结构就空着失效位，不编数字也不出 undefined',
  pno.stop === null && !/undefined/.test(pno.lines.join(' ')) && /失效位待定/.test(pno.lines[1]), pno);
check('没有目标位时明说「暂无参照」，不编数字',
  pno.target === null && /暂无参照/.test(pno.lines[2]), pno.lines[2]);
check('动盈还没启动（信号刚出）时明说条件，不编数字',
  /动盈 未启动/.test(pno.lines[2]) && /高于入场/.test(pno.lines[2]), pno.lines[2]);

group('advanceTrail —— 动盈只朝有利方向推进（无状态，纯靠结构重算）');
const at1 = { dir: 1, trail: null };
check('从无到有：第一次算出就写上', CLTrack.advanceTrail(at1, 10.9) === true && near(at1.trail, 10.9), at1);
check('多头：更低的回调低点不动它', CLTrack.advanceTrail(at1, 10.6) === false && near(at1.trail, 10.9), at1);
check('多头：更高的回调低点才上移', CLTrack.advanceTrail(at1, 11.5) === true && near(at1.trail, 11.5), at1);
const at2 = { dir: -1, trail: 11.6 };
check('空头：更高的反抽高点不动它', CLTrack.advanceTrail(at2, 11.9) === false && near(at2.trail, 11.6), at2);
check('空头：更低的反抽高点才下移', CLTrack.advanceTrail(at2, 11.2) === true && near(at2.trail, 11.2), at2);
const at3 = { dir: 1, trail: 10.9, alertedTrail: true };
CLTrack.advanceTrail(at3, 11.5);
check('线动了就重新允许提醒（alertedTrail 复位）', at3.alertedTrail === false, at3);
check('算不出（null）就不动记录', CLTrack.advanceTrail(at3, null) === false && near(at3.trail, 11.5), at3);

group('refreshTarget —— 目标没有单调性：突破后消失，回落再出现');
const rt1 = { dir: 1, target: 1535 };
check('同一目标不动它', CLTrack.refreshTarget(rt1, 1535) === false && rt1.target === 1535, rt1);
check('换了前高就更新，并重新允许提醒',
      CLTrack.refreshTarget(rt1, 1560) === true && rt1.target === 1560 && rt1.alertedTarget === false, rt1);
check('已创新高（上方无参照）→ 清空，线消失',
      CLTrack.refreshTarget(rt1, null) === true && rt1.target === null, rt1);
check('回落出现新前高 → 重新出现', CLTrack.refreshTarget(rt1, 1540) === true && rt1.target === 1540, rt1);
const rt2 = { dir: 1, target: null };
check('本来就没有目标时传 null 不算改动', CLTrack.refreshTarget(rt2, null) === false, rt2);

group('check —— 动态盯梢判据');
const rec = { dir: 1, stop: 9.8, stopRule: '跌破一买低点 9.800', target: 11.6, trail: 10.05,
              alertedStop: false, alertedTarget: false, alertedTrail: false };
check('跌破失效位 → stop', CLTrack.check(rec, 9.7).hit === 'stop');
check('已报过不再报', CLTrack.check({ ...rec, alertedStop: true }, 9.7).hit === null);
check('触及动盈位 → trail', CLTrack.check(rec, 10.05).hit === 'trail');
check('高于动盈位不报', CLTrack.check(rec, 10.4).hit === null);
check('动盈与失效之间也属触及动盈', CLTrack.check(rec, 9.9).hit === 'trail');
check('涨到目标位 → target（减 1/3，优先于动盈）', CLTrack.check(rec, 11.7).hit === 'target');
check('目标已报过就不再报，转而看动盈', CLTrack.check({ ...rec, alertedTarget: true, trail: 11.8 }, 11.7).hit === 'trail');
const recS = { dir: -1, stop: 12.8, stopRule: '升破一卖高点 12.800', target: 11.4, trail: 12.6,
               alertedStop: false, alertedTarget: false, alertedTrail: false };
check('看空：跌到目标位 → target', CLTrack.check(recS, 11.3).hit === 'target');
check('看空：升破失效位 → stop', CLTrack.check(recS, 12.9).hit === 'stop');
check('看空：升破止盈参考 → trail', CLTrack.check(recS, 12.6).hit === 'trail');
check('无效价格不报', CLTrack.check(rec, NaN).hit === null);

group('pickSignal.refs —— 失效位引用与移动止盈组装');
/* 构造 800 根假 K 线 + 一个二买点（extra.b1 = 一买极值价） */
const ks = [];
for (let i = 0; i < 800; i++) {
  ks.push({ t: 'd' + i, _t: i, o: 10, h: 10.5, l: 9.5, c: 10.2, v: 1 });
}
const fakeRes = {
  bis: [{ dir: 1, low: 9.0, high: 10.5 }, { dir: -1, low: 10.05, high: 11.0 }],
  points: [{ level: 2, type: 1, note: '二买·回抽不破前低', _k: 795, readyK: 797, price: 10.12,
             confirmed: true, extra: { fromDiv: 0, b1: 9.8 } }]
};
const sig = CLScanner.pickSignal(ks, fakeRes, { maxLag: 10 });
check('二买 refs.stopBuy = extra.b1', near(sig.refs.stopBuy, 9.8), sig.refs);
check('只有买点时 stopSell = null（不拿买点的数充数）', sig.refs.stopSell === null, sig.refs);
check('refs.dir 跟着信号走', sig.refs.dir === 1, sig.refs.dir);
check('lastClose = 末根收盘', near(sig.refs.lastClose, 10.2), sig.refs.lastClose);

group('pickSignal.refs —— 1.7.1：动盈只认「信号之后 + 优于入场」，目标取有利方向上的笔极值');
/* 信号在 _k=795；造出它的那根下跌笔 low=10.05 在信号之前，且低于入场 10.2
   → 1.7.0 会把它当成「移动止盈」，算出一个比失效位还低的止盈（用户报的怪现象） */
check('信号之后的回调低点才作数：此时没有 → trailLow = null',
      sig.refs.trailLow === null, sig.refs);
check('目标 = 最近前高（最近完成向下笔的高点，未突破）', near(sig.refs.targetHigh, 11), sig.refs);

/* 信号之后走出一段：先涨到 11.4（向上笔），回调到 10.9（向下笔，仍高于入场 10.2） */
const resAfter = {
  bis: [{ dir: -1, low: 10.05, high: 11.0, startK: 700, endK: 780 },
        { dir: 1,  low: 10.1,  high: 11.4, startK: 780, endK: 790 },
        { dir: -1, low: 10.05, high: 11.0, startK: 790, endK: 795 },   // 造出买点的那根
        { dir: 1,  low: 10.1,  high: 11.4, startK: 795, endK: 810 },   // 信号后：涨
        { dir: -1, low: 10.9,  high: 11.4, startK: 810, endK: 820 }],  // 信号后：回调
  points: [{ level: 2, type: 1, note: '二买·回抽不破前低', _k: 795, readyK: 797, price: 10.12,
             confirmed: true, extra: { fromDiv: 0, b1: 9.8 } }]
};
const sigT1 = CLScanner.pickSignal(ks, resAfter, { maxLag: 10 });
check('动盈 = 信号之后、高于入场的回调低点', near(sigT1.refs.trailLow, 10.9), sigT1.refs);
check('信号之前那根下跌笔（10.05）不再被当成动盈',
      sigT1.refs.trailLow !== 10.05, sigT1.refs.trailLow);

/* 再走一段：回调到 10.6（比 10.9 低，但仍高于入场）→ 动盈只上移不回头，停在 10.9 */
resAfter.bis.push({ dir: 1, low: 10.6, high: 11.8, startK: 820, endK: 840 });
resAfter.bis.push({ dir: -1, low: 10.6, high: 11.8, startK: 840, endK: 850 });
const sigTrl2 = CLScanner.pickSignal(ks, resAfter, { maxLag: 10 });
check('回撤到更低的低点：动盈停在原处（只上移不下移）', near(sigTrl2.refs.trailLow, 10.9), sigTrl2.refs);
/* 继续涨、回调到 11.5 → 动盈上移 */
resAfter.bis.push({ dir: 1, low: 10.7, high: 12.4, startK: 850, endK: 870 });
resAfter.bis.push({ dir: -1, low: 11.5, high: 12.4, startK: 870, endK: 880 });
const sigT3 = CLScanner.pickSignal(ks, resAfter, { maxLag: 10 });
check('新高后的回调低点抬高 → 动盈上移', near(sigT3.refs.trailLow, 11.5), sigT3.refs);

group('pickSignal.refs —— 空头对称（动补只下移不回头）');
/* 假 K 线收盘恒为 10.2 → 入场口径就是 10.2：空头的「优于入场」= 反抽高点 < 10.2 */
const resSell = {
  bis: [{ dir: -1, low: 9.0, high: 12.0, startK: 780, endK: 795 },
        { dir: -1, low: 9.0, high: 10.0, startK: 795, endK: 810 },   // 信号后：继续跌
        { dir: 1,  low: 9.2, high: 9.6, startK: 810, endK: 830 }],   // 信号后：反抽（仍低于入场）
  points: [{ level: 2, type: -1, note: '二卖·反抽不过前高', _k: 795, readyK: 797, price: 10.2,
             confirmed: true, extra: { fromDiv: 0, s1: 12.6 } }]
};
const sigS = CLScanner.pickSignal(ks, resSell, { maxLag: 10 });
check('空头动补 = 信号之后、低于入场的反抽高点', near(sigS.refs.trailHigh, 9.6), sigS.refs);
check('空头目标 = 最近反抽笔的起点低点（未升破）', near(sigS.refs.targetLow, 9.2), sigS.refs);
check('空头目标必须在现价下方（≥ 入场就不算目标）',
      sigS.refs.targetLow < sigS.refs.lastClose, sigS.refs);
fakeRes.points[0] = { level: 3, type: 1, note: '三买·回抽不入中枢', _k: 795, readyK: 797,
                      price: 10.9, confirmed: true, extra: { zs: 0, zsZG: 10.6, zsZD: 10.2 } };
const sigZ = CLScanner.pickSignal(ks, fakeRes, { maxLag: 10 });
check('三买 refs.stopBuy = zsZG', near(sigZ.refs.stopBuy, 10.6), sigZ.refs);

group('pickSignal.refs —— 1.7.0：多空各按自己的结构取，不再是同一个数');
/* 同一个分析结果里既有二买（锚一买低点 9.8）又有一卖（锚一卖高点 12.8） */
const res2 = {
  bis: [{ dir: 1, low: 9.0, high: 12.8 }, { dir: -1, low: 10.05, high: 11.0 }],
  points: [
    { level: 1, type: -1, note: '一卖·顶背驰', _k: 780, readyK: 782, price: 12.8,
      confirmed: true, extra: {} },
    { level: 2, type: 1, note: '二买·回抽不破前低', _k: 795, readyK: 797, price: 10.12,
      confirmed: true, extra: { fromDiv: 0, b1: 9.8 } }
  ]
};
const sigB = CLScanner.pickSignal(ks, res2, { maxLag: 10 });
check('挑中的是最新那个信号（二买）', sigB.level === 2 && sigB.type === 1, sigB);
check('多头失效位 = 一买低点 9.8', near(sigB.refs.stopBuy, 9.8), sigB.refs);
check('空头失效位 = 一卖高点 12.8', near(sigB.refs.stopSell, 12.8), sigB.refs);
check('多空失效位不再相等（1.6.0 的老 bug）', sigB.refs.stopBuy !== sigB.refs.stopSell, sigB.refs);
const planB = CLTrack.buildPlan(sigB, null, 'daily', { fmtPrice: v => v.toFixed(2) });
check('同一张作战卡：买点 → 做多、跌破 9.80',
  planB.dir === 1 && /跌破一买低点 9\.80/.test(planB.lines[1]), planB.lines);
const planBs = CLTrack.buildPlan(sigB, -1, 'daily', { fmtPrice: v => v.toFixed(2) });
check('同一张作战卡：反手做空 → 升破 12.80',
  planBs.dir === -1 && /升破一卖高点 12\.80/.test(planBs.lines[1]), planBs.lines);

group('updateTiming —— 30 分时机状态机（1.8.0：日线定方向、30 分定时机）');
const tRec = { dir: 1 };
let rt = CLTrack.updateTiming(tRec, null);
check('30 分无信号 → 不动', rt.hit === false && tRec.timing === undefined, tRec);
rt = CLTrack.updateTiming(tRec, { type: -1, level: 1, note: '一卖·顶背驰' });
check('反向信号（30 分卖点对多头）不算时机', rt.hit === false, rt);
rt = CLTrack.updateTiming(tRec, { type: 1, level: 2, note: '二买·回抽不破前低' });
check('同向信号 → 时机到，提醒一次', rt.hit === true && /二买/.test(rt.text), rt);
check('timing 落进记录（key/note/ts）',
      tRec.timing && tRec.timing.key === '2|二买·回抽不破前低' && tRec.timing.ts > 0, tRec.timing);
rt = CLTrack.updateTiming(tRec, { type: 1, level: 2, note: '二买·回抽不破前低' });
check('同一个 30 分信号反复算出来 → 不重复提醒', rt.hit === false, rt);
rt = CLTrack.updateTiming(tRec, { type: 1, level: 1, note: '一买·底背驰' });
check('换成新信号 → 再提醒一次', rt.hit === true, rt);
check('key 换成新信号的', tRec.timing.key === '1|一买·底背驰', tRec.timing);
const sRec = { dir: -1 };
check('空头对称：30 分卖点才是时机',
      CLTrack.updateTiming(sRec, { type: -1, note: '一卖·顶背驰' }).hit === true &&
      CLTrack.updateTiming(sRec, { type: 1, note: '二买·回抽不破前低' }).hit === false, sRec);

group('failTiming —— 30 分时机失效（1.8.1：时机已到后 30 分走坏）');
const fRec = { dir: 1, timing: { key: '2|二买·回抽不破前低', level: 2, note: '二买·回抽不破前低', ts: 1 } };
let rf = CLTrack.failTiming(fRec, null);
check('30 分无信号 → 不动（时机保留）', rf.hit === false && !!fRec.timing, rf);
rf = CLTrack.failTiming(fRec, { type: 1, note: '一买·底背驰' });
check('同向信号 → 不算失效', rf.hit === false && !!fRec.timing, rf);
rf = CLTrack.failTiming(fRec, { type: -1, note: '一卖·顶背驰' });
check('反向信号 → 时机失效，报一次', rf.hit === true && /时机失效/.test(rf.text), rf);
check('timing 清空回「在等」，timingFail 记录失效详情',
      fRec.timing === null && fRec.timingFail && /一卖/.test(fRec.timingFail.note) &&
      fRec.timingFail.from === '二买·回抽不破前低', fRec);
rf = CLTrack.failTiming(fRec, { type: -1, note: '一卖·顶背驰' });
check('同一个反向信号反复算出 → 不重报（timing 已清，天然去重）', rf.hit === false, rf);
rf = CLTrack.failTiming(fRec, { type: -1, note: '二卖·反抽不破前高' });
check('时机已撤（timing 空）→ 后续反向一律不报', rf.hit === false, rf);
const fRec2 = { dir: 1, timing: { key: '1|一买·底背驰', level: 1, note: '一买·底背驰', ts: 2 } };
CLTrack.failTiming(fRec2, { type: -1, note: '一卖·顶背驰' });
const fRec3 = { dir: 1, timing: { key: '2|二买·回抽不破前低', level: 2, note: '二买·回抽不破前低', ts: 3 } };
const rf3 = CLTrack.failTiming(fRec3, { type: -1, note: '一卖·顶背驰' });
check('新时机成立后再遇同一反向信号 → 允许再报（对新的时机窗口语义正确）',
      rf3.hit === true, rf3);
const sfRec = { dir: -1, timing: { key: '1|一卖·顶背驰', level: 1, note: '一卖·顶背驰', ts: 4 } };
check('空头对称：30 分出买点 → 时机失效',
      CLTrack.failTiming(sfRec, { type: 1, note: '二买·回抽不破前低' }).hit === true &&
      sfRec.timing === null, sfRec);

group('updateReverse —— 日线反向信号（1.8.1：多头怕卖点、空头怕买点）');
const vRec = { dir: 1 };
let rv = CLTrack.updateReverse(vRec, null);
check('日线无信号 → 不动', rv.hit === false && vRec.reverse === undefined, rv);
rv = CLTrack.updateReverse(vRec, { type: 1, level: 1, note: '一买·底背驰' });
check('同向信号（买点对多头）→ 不算反向', rv.hit === false, rv);
rv = CLTrack.updateReverse(vRec, { type: -1, level: 1, note: '一卖·顶背驰' });
check('反向信号 → 提醒一次', rv.hit === true && /一卖·顶背驰/.test(rv.text), rv);
check('reverse 落进记录（key/note/ts）',
      vRec.reverse && vRec.reverse.key === '1|一卖·顶背驰' && vRec.reverse.ts > 0, vRec.reverse);
rv = CLTrack.updateReverse(vRec, { type: -1, level: 1, note: '一卖·顶背驰' });
check('同一个反向信号反复算出 → 不重复提醒', rv.hit === false, rv);
rv = CLTrack.updateReverse(vRec, { type: 1, level: 2, note: '二买·回抽不破前低' });
check('同向新信号出现 → 不清除反向存档、不提醒', rv.hit === false &&
      vRec.reverse.key === '1|一卖·顶背驰', vRec.reverse);
rv = CLTrack.updateReverse(vRec, { type: -1, level: 2, note: '二卖·反抽不破前高' });
check('换成新的反向信号 → 再提醒一次', rv.hit === true && /二卖/.test(rv.text), rv);
check('key 换成新反向信号的', vRec.reverse.key === '2|二卖·反抽不破前高', vRec.reverse);
const svRec = { dir: -1 };
check('空头对称：日线出买点才是反向',
      CLTrack.updateReverse(svRec, { type: 1, note: '一买·底背驰' }).hit === true &&
      CLTrack.updateReverse(svRec, { type: -1, note: '一卖·顶背驰' }).hit === false, svRec);
const rvTxt = CLTrack.updateReverse({ dir: 1 }, { type: -1, level: 1, note: '一卖·顶背驰' });
check('1.9.0 文案降级：多头方向词「转空」+ 仅提示 + 离场仍看结构线',
      /转空/.test(rvTxt.text) && /仅提示/.test(rvTxt.text) && /失效位\/动盈/.test(rvTxt.text), rvTxt.text);
const rvTxt2 = CLTrack.updateReverse({ dir: -1 }, { type: 1, level: 1, note: '一买·底背驰' });
check('1.9.0 文案对称：空头方向词「转多」', /转多/.test(rvTxt2.text), rvTxt2.text);

group('pickSignal —— 1.9.0：同 K 并列信号三类优先（三买排最前）');
/* 一买与三买同一根 K 成立：回测三买唯一有优势 → 选三买 */
const resTie = {
  bis: [{ dir: 1, low: 9.0, high: 12.8 }, { dir: -1, low: 10.05, high: 11.0 }],
  points: [
    { level: 1, type: 1, note: '一买·底背驰', _k: 795, readyK: 797, price: 9.8,
      confirmed: true, extra: {} },
    { level: 3, type: 1, note: '三买·回抽不入中枢', _k: 795, readyK: 797, price: 10.9,
      confirmed: true, extra: { zs: 0, zsZG: 10.6, zsZD: 10.2 } }
  ]
};
const sigTie = CLScanner.pickSignal(ks, resTie, { maxLag: 10 });
check('同 K 一买+三买并列 → 挑三买', sigTie.level === 3 && sigTie.type === 1, sigTie);
const resTieSell = {
  bis: resTie.bis,
  points: [
    { level: 3, type: 1, note: '三买·回抽不入中枢', _k: 795, readyK: 797, price: 10.9,
      confirmed: true, extra: { zs: 0, zsZG: 10.6, zsZD: 10.2 } },
    { level: 1, type: 1, note: '一买·底背驰', _k: 795, readyK: 797, price: 9.8,
      confirmed: true, extra: {} }
  ]
};
check('并列与顺序无关（数组顺序不影响）',
      CLScanner.pickSignal(ks, resTieSell, { maxLag: 10 }).level === 3);
/* 不同 K 仍按最新优先，三类优先只在同 K 并列时生效 */
const resNewer = {
  bis: resTie.bis,
  points: [
    { level: 3, type: 1, note: '三买·回抽不入中枢', _k: 794, readyK: 796, price: 10.9,
      confirmed: true, extra: { zs: 0, zsZG: 10.6, zsZD: 10.2 } },
    { level: 2, type: 1, note: '二买·回抽不破前低', _k: 796, readyK: 798, price: 10.12,
      confirmed: true, extra: { fromDiv: 0, b1: 9.8 } }
  ]
};
check('不同 K：更新的二买仍优先于更旧的三买',
      CLScanner.pickSignal(ks, resNewer, { maxLag: 10 }).level === 2);

console.log('\n==============================================================');
console.log('结果：' + passed + ' 通过，' + failed + ' 失败');
console.log('==============================================================');
process.exit(failed ? 1 : 0);
