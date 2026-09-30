/* ==========================================================================
 * tests/test_market.js —— 行情层的「日线当日缺失兜底」单元测试
 * 运行： node tests/test_market.js
 *
 * 只测纯函数（时间判定），不发网络请求：fetchFresherDaily 的源顺序在
 * 安卓壳的冒烟测试（§19d）里用 mock 报文验证。
 * ========================================================================== */
'use strict';
const path = require('path');

global.self = global;
// market.js 是挂全局的 UMD（没有 module.exports 分支），require 只能触发加载
require(path.join(__dirname, '..', 'core', 'market.js'));
const CLMarket = global.CLMarket;

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log('  ✓ ' + name); }
  else { failed++; console.log('  ✗ ' + name + (extra !== undefined ? '  → ' + JSON.stringify(extra) : '')); }
}
function group(name) { console.log('\n' + name); }

/* 测试用的时间点一律显式给，避免跟着系统时间飘 */
function at(s) { return Date.parse(s); }
function bars(...dates) { return dates.map(t => ({ t, o: 1, h: 1, l: 1, c: 1, v: 0 })); }

/* 2026-09-14 是周一，09-18 是周五，09-19/20 是周末 */
group('expectTradingDate —— 应有最新交易日');
check('交易日盘中(周一 10:00) → 当天', CLMarket.expectTradingDate(at('2026-09-14T10:00:00')) === '2026-09-14');
check('交易日收盘后(周一 20:00) → 当天', CLMarket.expectTradingDate(at('2026-09-14T20:00:00')) === '2026-09-14');
check('开盘前(周一 08:00) → 上一交易日（周五）', CLMarket.expectTradingDate(at('2026-09-14T08:00:00')) === '2026-09-11');
check('周六 → 周五', CLMarket.expectTradingDate(at('2026-09-19T10:00:00')) === '2026-09-18');
check('周日 → 周五', CLMarket.expectTradingDate(at('2026-09-20T10:00:00')) === '2026-09-18');
check('周一 09:29 → 仍算上一交易日', CLMarket.expectTradingDate(at('2026-09-14T09:29:00')) === '2026-09-11');
check('周一 09:30 → 当天', CLMarket.expectTradingDate(at('2026-09-14T09:30:00')) === '2026-09-14');

group('isStaleDaily —— 日线末端是否落后');
check('末端=应有交易日 → 不落后',
  CLMarket.isStaleDaily(bars('2026-09-11', '2026-09-14'), at('2026-09-14T15:00:00')) === false);
check('末端=昨天 → 落后（源没落地当日）',
  CLMarket.isStaleDaily(bars('2026-09-11'), at('2026-09-14T15:00:00')) === true);
check('末端=上周五，今天周六 → 不落后（周末不该报缺失）',
  CLMarket.isStaleDaily(bars('2026-09-18'), at('2026-09-19T11:00:00')) === false);
check('周一开盘前，末端=上周五 → 不落后',
  CLMarket.isStaleDaily(bars('2026-09-11'), at('2026-09-14T08:00:00')) === false);
check('带时分秒的时间戳也能解析',
  CLMarket.isStaleDaily([{ t: '2026-09-11 15:00:00' }], at('2026-09-14T15:00:00')) === true);
check('时间格式不认识 → 不动作（宁可不兜底，也别乱换源）',
  CLMarket.isStaleDaily([{ t: '20260911' }], at('2026-09-14T15:00:00')) === false);
check('空数组 → false', CLMarket.isStaleDaily([], at('2026-09-14T15:00:00')) === false);

group('expectLastDate —— 周/月线的「应有的最新一根」下限');
/* 2026-09-14 周一，09-16 周三，09-19 周六，09-20 周日；本周一 = 09-14 */
check('周线 周一 → 本周一', CLMarket.expectLastDate('weekly', at('2026-09-14T15:00:00')) === '2026-09-14');
check('周线 周三 → 本周一', CLMarket.expectLastDate('weekly', at('2026-09-16T15:00:00')) === '2026-09-14');
check('周线 周六 → 本周一', CLMarket.expectLastDate('weekly', at('2026-09-19T11:00:00')) === '2026-09-14');
check('周线 周日 → 本周一', CLMarket.expectLastDate('weekly', at('2026-09-20T11:00:00')) === '2026-09-14');
check('月线 月中 → 本月 1 号', CLMarket.expectLastDate('monthly', at('2026-09-16T15:00:00')) === '2026-09-01');
check('月线 月初 → 本月 1 号', CLMarket.expectLastDate('monthly', at('2026-09-01T15:00:00')) === '2026-09-01');
check('日线 入口不变（等同 expectTradingDate）',
  CLMarket.expectLastDate('daily', at('2026-09-19T11:00:00')) ===
  CLMarket.expectTradingDate(at('2026-09-19T11:00:00')));

group('isStale —— 周/月线末端是否落后，分钟线不参与');
check('周线 末端=上周五(09-11)，今天周三(09-16) → 落后',
  CLMarket.isStale(bars('2026-09-04', '2026-09-11'), 'weekly', at('2026-09-16T15:00:00')) === true);
check('周线 末端=本周一(09-14) → 不落后（不管源标周首还是周末）',
  CLMarket.isStale(bars('2026-09-14'), 'weekly', at('2026-09-16T15:00:00')) === false);
check('周线 末端=本周四(09-17) → 不落后',
  CLMarket.isStale(bars('2026-09-17'), 'weekly', at('2026-09-17T15:00:00')) === false);
check('月线 末端=8月，今天9月 → 落后',
  CLMarket.isStale(bars('2026-08-31'), 'monthly', at('2026-09-16T15:00:00')) === true);
check('月线 末端=9月1号 → 不落后',
  CLMarket.isStale(bars('2026-09-01'), 'monthly', at('2026-09-16T15:00:00')) === false);
check('30m 不参与兜底（各源分钟线都是实时聚合）',
  CLMarket.isStale(bars('2026-09-11 10:30:00'), '30m', at('2026-09-16T15:00:00')) === false);
check('5m 不参与兜底',
  CLMarket.isStale(bars('2026-09-11 10:30:00'), '5m', at('2026-09-16T15:00:00')) === false);
check('isStaleDaily 仍是日线入口',
  CLMarket.isStaleDaily(bars('2026-09-11'), at('2026-09-14T15:00:00')) === true &&
  CLMarket.isStale(bars('2026-09-11'), 'daily', at('2026-09-14T15:00:00')) === true);

group('setNowFn —— 时间基准可注入（冒烟用）');
CLMarket.setNowFn(() => at('2026-09-21T15:00:00'));
check('注入后 expectTradingDate 跟着变', CLMarket.expectTradingDate() === '2026-09-21');
check('注入后 isStaleDaily 判断跟着变',
  CLMarket.isStaleDaily(bars('2026-09-14'), null) === true);
CLMarket.setNowFn(null);
check('传 null 复位成真实时间（返回今天或上一交易日）',
  /^\d{4}-\d{2}-\d{2}$/.test(CLMarket.expectTradingDate()));

console.log('\n' + '='.repeat(62));
console.log(`结果：${passed} 通过，${failed} 失败`);
console.log('='.repeat(62));
process.exit(failed ? 1 : 0);
