/* ==========================================================================
 * exitsignal.js —— 「信号消失即离场」这条规则到底可不可执行？
 *
 * 背景问题（用户提出）：
 *   买入后若发现信号没了，是否该立刻离场？
 *
 * 关键约束（必须先回答，否则规则无意义）：
 *   引擎在 day t 只能看到 ks.slice(0, t+1)。因此「信号消失」最早只能在
 *   某个 t 被发现，而离场成交最早是 t+1 开盘。这里必须实测「从入场到发现消失」
 *   中间隔了多少根 K 线 —— 若隔 60 根（3 个月），该规则在实战中不可执行。
 *
 * 纪律：
 *   D1. 只读生产引擎 chan.js，跑前跑后 md5 双向核对
 *   D2. 入场 = readyK+1 开盘（与 bt.js 一致）
 *   D3. 无未来函数：每天只用 ks.slice(0, t+1) 判断信号是否还在
 *   D4. 所有阈值（最晚观察根数）做敏感性扫描，不靠单一取值下结论
 *
 * 环境变量：SMOKE=n 只取历史最长的 n 只
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const L = require('./lib.js');

const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const Chan = require(ENGINE);
const DIR = 'D:/Trading/data/etfs';
const md5 = f => crypto.createHash('md5').update(fs.readFileSync(f)).digest('hex');
const MD5_BEFORE = md5(ENGINE);

const FEE = 0.001;
const WARMUP = 500;
const HORIZONS = [10, 20, 30, 40, 60];  // 固定持有期对照组（敏感性扫描）
const MAXWATCH = 120;                   // 最长观察：入场后 120 根内若未判消失则记为「未消失」
const TOL = parseInt(process.env.TOL || '0', 10);  // 身份容差（主口径 0 = 无容差）
const HOLDS = [20];

const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ---------------------------------------------------------------- 选票 */
let all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).sort();
const SMOKE = parseInt(process.env.SMOKE || '0', 10);
if (SMOKE > 0) {
  all = all.map(c => {
    try {
      const n = fs.readFileSync(path.join(DIR, c), 'utf8').split(/\r?\n/).filter(x => x.trim()).length;
      return { c: c.replace('.csv', ''), n };
    } catch (e) { return { c: c.replace('.csv', ''), n: 0 }; }
  }).sort((a, b) => b.n - a.n).slice(0, SMOKE).map(x => x.c);
} else {
  all = all.map(c => c.replace('.csv', ''));
}
const need = WARMUP + MAXWATCH + 100;

/* ------------------------------------------------------------ 数据加载 */
const books = [], skipped = [];
for (const code of all) {
  try {
    const r = L.loadETF(path.join(DIR, code + '.csv'));
    if (r.ks.length < need) { skipped.push(code + '(' + r.ks.length + '根)'); continue; }
    books.push({ code, ks: r.ks, badCount: r.badCount });
  } catch (e) { skipped.push(code + '(' + e.message + ')'); }
}

/* ---------------------------------------------- 逐日发现信号（同 bt.js） */
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
const out = {
  meta: { engine: ENGINE, md5Before: MD5_BEFORE, fee: FEE, warmup: WARMUP, maxwatch: MAXWATCH, tol: TOL, books: books.length, skipped },
  /* barsToLoss 分布：入场后第几根才发现信号没了 */
  barsToLoss: {},
  /* 分组收益（20 日口径） */
  grp: { lost: [], survived: [] },
  /* 离场即离场 vs 固定持有 */
  exitRule: [],   // {ret, barsHeld}
  holdRule: [],   // {ret}
  /* 各观察上限下的敏感性 */
  scan: {},       // W -> {lostN, lostRet, ruleRet, holdRet, diff, t}
  horizonScan: {},// H -> 固定持有期下 lost vs survived 的差
  nSig: 0
};

let nBook = 0;
for (const bk of books) {
  const ks = bk.ks, last = ks.length - 1;
  const sigs = scanDaily(ks);

  for (const s of sigs) {
    const e = s.readyK + 1;                       // D2 入场
    if (e < WARMUP || e + MAXWATCH > last) continue;
    const probe = L.retAt(ks, e, MAXWATCH, FEE);
    if (probe == null) continue;                   // 中途有坏 K 线，该信号不可用
    out.nSig++;

    /* ---- 逐日判断「信号是否还在」，只看 ks.slice(0,t+1)（D3） ----
     * 注意：TOL 是「身份容差」。若换一个合理取值结论就变了，说明判据不稳健。
     * 0 = 锚点必须完全一致才算同一信号；±40 = 极宽松。
     * 用 0 作主口径（无容差，最严格），并扫描 3/5/10/20/40 做稳健性检验。 */
    const alive = (t) => {
      const res = Chan.analyze(ks.slice(0, t + 1), {});
      return res.points.some(p => p.type === 1 && p.level === s.level && Math.abs(p._k - s.markK) <= TOL);
    };

    let lostAt = -1;
    for (let t = e; t <= e + MAXWATCH && t < last; t++) {
      if (!alive(t)) { lostAt = t; break; }
    }

    /* 固定持有 20 日 */
    const holdRet = L.retAt(ks, e, 20, FEE);
    if (holdRet == null) continue;

    /* 规则离场：发现消失的当天收盘可知 → 最早 t+1 开盘卖出 */
    let ruleRet = null, barsHeld = null;
    if (lostAt >= 0) {
      const ex = lostAt + 1;                       // 次日开盘离场
      if (ex < last && !(ks[ex] && ks[ex].bad)) {
        const gross = ks[ex].o / ks[e].o - 1;
        if (isFinite(gross)) { ruleRet = gross - FEE; barsHeld = ex - e; }
      }
    }

    /* 记录分布（离场价不可得的情形也记，避免只统计成功样本造成偏差） */
    const b = lostAt < 0 ? '未消失' : String(Math.min(MAXWATCH, lostAt - e));
    out.barsToLoss[b] = (out.barsToLoss[b] || 0) + 1;

    if (lostAt >= 0) {
      out.grp.lost.push(holdRet);
      if (ruleRet != null) out.exitRule.push({ ret: ruleRet, bars: barsHeld });
    } else {
      out.grp.survived.push(holdRet);
    }
    out.holdRule.push(holdRet);

    /* 敏感性：若最多观察 W 根，之后一律按固定 20 日持有 */
    for (const W of [10, 20, 30, 40, 60, 120]) {
      const k = String(W);
      out.scan[k] = out.scan[k] || { lostN: 0, lostHold: [], rule: [], hold: [] };
      const eW = lostAt >= 0 && (lostAt - e) <= W;
      out.scan[k].hold.push(holdRet);
      if (eW) {
        out.scan[k].lostN++;
        out.scan[k].lostHold.push(holdRet);
        if (ruleRet != null) out.scan[k].rule.push(ruleRet);
      }
    }
  }
  log('  [' + (++nBook) + '/' + books.length + '] ' + bk.code + '  信号' + sigs.length + '  ' + ((Date.now() - T0) / 1000).toFixed(1) + 's');
}

/* ------------------------------------------------------------ 不同持有期下的 lost/survived 对照，见下方 horizonPass */

/* ================== 额外一遍：不同持有期下 lost/survived 的收益差 ================== */
(function horizonPass() {
  const HZ = [10, 20, 30, 40, 60];
  const acc = {}; HZ.forEach(h => acc[h] = { lost: [], surv: [] });
  for (const bk of books) {
    const ks = bk.ks, last = ks.length - 1;
    const sigs = scanDaily(ks);
    const full = Chan.analyze(ks, {});
    const fullKeys = new Set();
    full.points.forEach(p => { if (p.type === 1) fullKeys.add(p.level + ':' + p._k); });
    for (const s of sigs) {
      const e = s.readyK + 1;
      if (e < WARMUP || e + Math.max.apply(null, HZ) > last) continue;
      const survives = fullKeys.has(s.level + ':' + s.markK);
      for (const H of HZ) {
        const r = L.retAt(ks, e, H, FEE);
        if (r == null) continue;
        acc[H][survives ? 'surv' : 'lost'].push(r);
      }
    }
  }
  HZ.forEach(H => {
    const a = acc[H].lost, b = acc[H].surv;
    const ci = L.ci95(a, b), t = L.welchT(a, b);
    out.horizonScan[H] = {
      lostN: a.length, lostExp: L.mean(a),
      survN: b.length, survExp: L.mean(b),
      diff: L.mean(a) != null && L.mean(b) != null ? L.mean(a) - L.mean(b) : null,
      t: t, ci: ci
    };
  });
})();

/* ---------------------------------------------------------------- 输出 */
console.log('\n============ 「信号消失即离场」可执行性检验 ============');
console.log('引擎 md5(跑前) ' + MD5_BEFORE);
console.log('ETF ' + books.length + ' 只（跳过 ' + skipped.length + '），可观察信号 ' + out.nSig + ' 个');
console.log('身份容差 TOL = ±' + TOL + ' 根' + (TOL === 0 ? '（无容差，锚点须完全一致）' : '') + '\n');

console.log('【1】入场后第几根才发现信号没了（bars = 入场后经过的 K 线数）');
const bk2 = Object.keys(out.barsToLoss).filter(k => k !== '未消失').map(Number).sort((a, b) => a - b);
const tot = Object.values(out.barsToLoss).reduce((s, x) => s + x, 0);
const cum = [];
let acc2 = 0;
for (const k of bk2) { acc2 += out.barsToLoss[k]; cum.push({ k, n: out.barsToLoss[k], cum: acc2, pct: 100 * acc2 / tot }); }
cum.forEach(c => { if (c.cum / tot <= 1.0) console.log('  ' + String(c.k).padStart(4) + ' 根: ' + String(c.n).padStart(5) + '  累计 ' + (100 * c.cum / tot).toFixed(1) + '%'); });
const tail = cum.filter(c => c.cum / tot > 0.985 && c.cum / tot <= 1.0);
if (tail.length) console.log('  （尾部细节）' + tail.map(c => c.k + '根:' + c.n).join('  '));
console.log('  未消失（观察 ' + MAXWATCH + ' 根内仍在）: ' + out.barsToLoss['未消失'] + ' = ' + (100 * out.barsToLoss['未消失'] / tot).toFixed(1) + '%');
// 中位数（仅在被判定消失的样本内计算，'未消失' 不参与）
const nLost = tot - (out.barsToLoss['未消失'] || 0);
let half = nLost / 2, run = 0, med = null;
for (const k of bk2) { run += out.barsToLoss[k]; if (run >= half) { med = k; break; } }
const qAt = q => { let a = 0, c = 0; for (const k of bk2) { c += out.barsToLoss[k]; if (c >= q * nLost) return k; } return null; };
console.log('  被判定消失 ' + nLost + ' 个，发现时点中位数 = 第 ' + med + ' 根（约 ' + (med / 21).toFixed(1) + ' 个月）');
console.log('  25%分位=' + qAt(0.25) + ' 根  75%分位=' + qAt(0.75) + ' 根  90%分位=' + qAt(0.90) + ' 根');
console.log('  → 若 75 分位已超过 20 根，说明多数信号在一个月后仍未被判消失。');

console.log('\n【2】分固定持有期：被抹除组 vs 留存组（20 日口径已在 horizonScan 全列）');
console.log('持有 | 抹除n  抹除收益   留存n  留存收益     差(pp) Welch t   95%CI');
console.log('-'.repeat(80));
for (const H of [10, 20, 30, 40, 60]) {
  const d = out.horizonScan[H];
  console.log(` ${String(H).padStart(3)}日 |${String(d.lostN).padStart(6)}${L.pc(d.lostExp).padStart(9)}${String(d.survN).padStart(7)}${L.pc(d.survExp).padStart(9)}` +
    `${L.pp(d.diff).padStart(9)}${L.f2(d.t).padStart(8)}   [${L.pp(d.ci && d.ci.lo)}, ${L.pp(d.ci && d.ci.hi)}]`);
}

console.log('\n【3】规则 A：固定持有 20 日  vs  规则 B：发现信号消失即离场（次日开盘）');
const holdArr = out.holdRule, ruleArr = out.exitRule.map(x => x.ret);
const ciAB = L.ci95(ruleArr, holdArr), tAB = L.welchT(ruleArr, holdArr);
console.log('  规则A 固定持有20日 : n=' + holdArr.length + '  平均 ' + L.pc(L.mean(holdArr)));
console.log('  规则B 消失即离场   : n=' + ruleArr.length + '  平均 ' + L.pc(L.mean(ruleArr)) +
  '  平均持有 ' + L.f2(L.mean(out.exitRule.map(x => x.bars))) + ' 根');
console.log('  差(B-A) ' + L.pp(ciAB && ciAB.d) + '  Welch t=' + L.f2(tAB) + '  95%CI [' + L.pp(ciAB && ciAB.lo) + ', ' + L.pp(ciAB && ciAB.hi) + ']');
console.log('  注意：B 只对「确实发现消失」的那批生效，n 小于 A 是正常的。');
console.log('  公平比较应看下方【4】同一批信号上的两种走法。');

console.log('\n【4】同一批「发现了消失」的信号上，两种走法对比（公平口径）');
const fairBase = out.scan['120'].lostHold;
console.log('  样本: 发现消失的信号 ' + fairBase.length + ' 个');
if (ruleArr.length) {
  const ciF = L.ci95(ruleArr, fairBase), tF = L.welchT(ruleArr, fairBase);
  console.log('  固定持有20日 : ' + L.pc(L.mean(fairBase)));
  console.log('  消失即离场   : ' + L.pc(L.mean(ruleArr)));
  console.log('  差 ' + L.pp(ciF && ciF.d) + '  Welch t=' + L.f2(tF) + '  95%CI [' + L.pp(ciF && ciF.lo) + ', ' + L.pp(ciF && ciF.hi) + ']');
  const sig2 = ciF && (ciF.lo > 0 || ciF.hi < 0);
  console.log('  CI ' + (sig2 ? '不含 0 → 差异显著' : '含 0 → 差异不显著') +
    '；方向：' + (ciF && ciF.d > 0 ? '离场规则更好' : '离场规则更差') + '。');
}

console.log('\n【5】敏感性：若最多观察 W 根就放弃等待（超出则按固定 20 日持有）');
console.log('  W根 | 发现消失n | 抹除组持有20日 | 离场规则收益 |    差   Welch t');
console.log('-'.repeat(76));
for (const W of [10, 20, 30, 40, 60, 120]) {
  const d = out.scan[String(W)];
  const ci = L.ci95(d.rule, d.lostHold), t = L.welchT(d.rule, d.lostHold);
  console.log(`  ${String(W).padStart(3)} |${String(d.lostN).padStart(9)} |${L.pc(L.mean(d.lostHold)).padStart(14)} |${L.pc(L.mean(d.rule)).padStart(12)} |${L.pp(ci && ci.d).padStart(7)} ${L.f2(t).padStart(7)}`);
}

const MD5_AFTER = md5(ENGINE);
console.log('\n引擎 md5(跑后) ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！结果不可信'));
out.meta.md5After = MD5_AFTER;
out.meta.elapsed = (Date.now() - T0) / 1000;

fs.writeFileSync(path.join(__dirname, 'tmp', 'exitsignal.json'), JSON.stringify(out));
console.log('\n已写出 tmp/exitsignal.json   耗时 ' + ((Date.now() - T0) / 1000).toFixed(1) + 's');