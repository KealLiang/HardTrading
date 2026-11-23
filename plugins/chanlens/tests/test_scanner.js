/* ==========================================================================
 * tests/test_scanner.js —— CLScanner.refsFor 单元测试（2.5.1 新增）
 * 运行： node tests/test_scanner.js
 *
 * 只测纯函数，不发网络请求。核心是钉住 2.5.1 修的动盈污染 bug：
 *   markK（信号标记位）缺失时，旧实现 `markK == null || ...` 恒真 →
 *   把信号之前几个月的历史反向笔全吸进来当动盈（002491 实测 12.13 的现价
 *   动盈算成 23.31，条件单 23.17，建卡即「已触发」→ 此后永久静默）。
 * ========================================================================== */
'use strict';
const path = require('path');

global.self = global;
require(path.join(__dirname, '..', 'core', 'chan.js'));
require(path.join(__dirname, '..', 'core', 'scanner.js'));
const S = global.CLScanner;

let passed = 0, failed = 0;
function check(name, cond, extra) {
  if (cond) { passed++; console.log('  ✓ ' + name); }
  else { failed++; console.log('  ✗ ' + name + (extra !== undefined ? '  → ' + JSON.stringify(extra) : '')); }
}
function group(name) { console.log('\n' + name); }

const ks = Array.from({ length: 40 }, (_, i) => ({ t: 'd' + i, o: 10, h: 11, l: 9, c: 10 }));

/* 两份反向笔：5~8 是「信号之前」的高位笔（低点 23.31），30~33 是建卡之后的新低 */
const res = { bis: [
  { dir: -1, startK: 5,  endK: 8,  low: 23.31, high: 25 },
  { dir: -1, startK: 30, endK: 33, low: 12.5,  high: 13 }
]};

group('refsFor —— 只看 markK 之后的反向笔（2.5.1 动盈污染修复）');
check('markK=30：只取 30 那笔的低点 12.5（信号前 23.31 不算）',
      S.refsFor(ks, res, 1, 11.83, 30).trailLow === 12.5,
      S.refsFor(ks, res, 1, 11.83, 30).trailLow);
check('markK=null：返回 null —— 宁可不给动盈，也不给信号前几个月的历史结构',
      S.refsFor(ks, res, 1, 11.83, null).trailLow === null,
      S.refsFor(ks, res, 1, 11.83, null).trailLow);
check('旧 bug 值 23.31 在任何路径下都不再出现（002491 实测值）',
      S.refsFor(ks, res, 1, 11.83, null).trailLow !== 23.31 &&
      S.refsFor(ks, res, 1, 11.83, 30).trailLow !== 23.31);
check('markK 之后的低点若仍低于入场价，同样不算（12.5 → 11.5 时为空）',
      S.refsFor(ks, { bis: [{ dir: -1, startK: 30, endK: 33, low: 11.5, high: 12 }] },
                1, 11.83, 30).trailLow === null);
check('startK < markK 的笔一律跳过（20 那笔 23.31 不算）',
      S.refsFor(ks, { bis: [
        { dir: -1, startK: 20, endK: 25, low: 23.31, high: 25 },
        { dir: -1, startK: 30, endK: 33, low: 12.5,  high: 13 }
      ] }, 1, 11.83, 30).trailLow === 12.5);
check('markK 落在最后一根之后（还没有新笔）→ null，不是「全部历史」',
      S.refsFor(ks, res, 1, 11.83, 38).trailLow === null);

group('refsFor —— 空头对称');
const resS = { bis: [
  { dir: 1, startK: 5,  endK: 8,  low: 8,  high: 9.2 },     // 信号之前的高位笔？
  { dir: 1, startK: 30, endK: 33, low: 9.5, high: 9.9 }     // 建卡之后的反弹高点
]};
/* 空头：动盈取「高点 < 入场价」的最近正向笔，只下移 */
check('空头 markK=30：取 9.9（< 入场 10.5）',
      S.refsFor(ks, resS, -1, 10.5, 30).trailHigh === 9.9,
      S.refsFor(ks, resS, -1, 10.5, 30).trailHigh);
check('空头 markK=null：返回 null（对称，不吸历史）',
      S.refsFor(ks, resS, -1, 10.5, null).trailHigh === null,
      S.refsFor(ks, resS, -1, 10.5, null).trailHigh);

group('refsFor —— 防御：空输入');
check('无 K 线 → 全 null', JSON.stringify(S.refsFor([], res, 1, 11.83, 30)) ===
      JSON.stringify({ trailLow: null, trailHigh: null, targetHigh: null, targetLow: null }));
check('无 res → 不抛错', S.refsFor(ks, null, 1, 11.83, 30).trailLow === null);

console.log('\n==============================================================');
console.log('结果：' + passed + ' 通过，' + failed + ' 失败');
console.log('==============================================================');
process.exit(failed ? 1 : 0);
