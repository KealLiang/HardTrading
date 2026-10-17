/* ==========================================================================
 * bt_30m.js —— 30/60 分钟级别缠论买点回测（T+1 合规）
 *
 * 背景痛点（用户）：日线等不到信号时，低级别等到了——此时是主观还是模式？
 * 本脚本回答：低级别买点相对随机买入是否有正超额；以及按「同期日线有无信号」
 * 分组后的条件超额。
 *
 * 纪律（继承 bt.js）：
 *   D1. 只读生产引擎 chan.js，跑前跑后 md5 双向核对
 *   D2. 入场 = readyK+1 根开盘（引擎既定 readyK 语义）
 *   D3. 基准：全区间随机 + 邻近窗口随机（控制局部行情），扫描窗口做敏感性
 *   D4. T+1 显式断言：卖出 bar 的日期必须严格晚于买入 bar 的日期
 *   D5. 所有结论带敏感性；60 分钟样本不足时明说，不硬分类型
 *
 * 环境变量：
 *   TF=30|60     K线级别（30=原始30分钟；60=两根合成）
 *   SMOKE=n      只取前 n 只（冒烟）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const L = require('./lib.js');

const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const Chan = require(ENGINE);
const DIR = 'D:/Trading/data/etfs_bt_30m';
const DIR_DAILY = 'D:/Trading/data/etfs';
const md5 = f => crypto.createHash('md5').update(fs.readFileSync(f)).digest('hex');
const MD5_BEFORE = md5(ENGINE);

const TF = parseInt(process.env.TF || '30', 10);
if (TF !== 30 && TF !== 60) { console.error('TF 只支持 30|60'); process.exit(1); }

const FEE = 0.001;
const WARMUP = TF === 30 ? 500 : 250;      // 结构预热（≈3 个月）
const BARS_PER_DAY = TF === 30 ? 8 : 4;    // A股每日 bar 数
const HOLDS = [1, 2, 5];                   // 持有交易日数 → bar 数 = 天数×BARS_PER_DAY
const NB_WINDOWS = [8, 16, 32, 64];        // 邻近基准窗口（bar 数；30分钟下=1/2/4/8 天）
const NB_SAMPLES = 800;
const GLOB_SAMPLES = 800;
const DAILY_LOOKBACK = 10;                 // 条件分组：入场前 N 个交易日日线有无信号

const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ------------------------------------------------------- 数据加载（30分钟格式） */
function load30(file) {
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  for (const col of ['时间', '开盘', '收盘', '最高', '最低']) {
    if (ix(col) < 0) throw new Error('表头缺列 ' + col);
  }
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const t = String(c[ix('时间')] || '').trim();
    if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(t)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')];
    const h = +c[ix('最高')], l = +c[ix('最低')];
    const v = +c[ix('成交量')] || 0;
    const bad = !(o > 0 && isFinite(o)) || !(cl > 0 && isFinite(cl)) ||
                !(h > 0 && isFinite(h)) || !(l > 0 && isFinite(l)) || h < l;
    rows.push({ t: t, date: t.slice(0, 10), o, c: cl, h, l, v, bad });
  }
  return rows;  // 已按时间升序（数据源保证），不再排序去重（分钟序列同刻度唯一）
}

/* 60 分钟合成：日内相邻两根合并，跨日不合并（保留边界 bar 原样） */
function to60(ks30) {
  const out = [];
  for (let i = 0; i < ks30.length; i++) {
    const a = ks30[i], b = ks30[i + 1];
    if (b && b.date === a.date) {
      out.push({ t: b.t, date: b.date, o: a.o, c: b.c, h: Math.max(a.h, b.h), l: Math.min(a.l, b.l), v: a.v + b.v, bad: a.bad || b.bad });
      i++;
    } else {
      out.push({ ...a });   // 日内落单（开盘/收盘边界），原样保留
    }
  }
  return out;
}

/* ------------------------------------------------------- T+1 合规的收益函数 */
/* 卖出 bar 日期必须严格晚于买入 bar 日期（D4），违规返回 null 并计数 */
let t1Violations = 0;
function retAtT1(ks, e, holdBars, fee) {
  const j = e + holdBars;
  if (j >= ks.length) return null;
  if (!(ks[j].date > ks[e].date)) { t1Violations++; return null; }   // T+1 断言
  return L.retAt(ks, e, holdBars, fee);
}

/* ------------------------------------------------------- 日线信号日集合（条件分组用） */
function dailySignalDates(code) {
  const f = path.join(DIR_DAILY, code + '.csv');
  if (!fs.existsSync(f)) return new Set();
  const { ks } = L.loadETF(f);
  const dates = new Set();
  for (let t = 500; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type === 1 && p.level >= 1 && p.level <= 3 && p.readyK + 1 <= t) {
        dates.add(ks[p.readyK + 1].t);   // 日线信号的入场日
      }
    }
  }
  return dates;
}

/* ------------------------------------------------------- 选票 */
let all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(c => c.replace('.csv', '')).sort();
const SMOKE = parseInt(process.env.SMOKE || '0', 10);
if (SMOKE > 0) all = all.slice(0, SMOKE);

const maxHoldBars = Math.max(...HOLDS) * BARS_PER_DAY;
const need = WARMUP + maxHoldBars + 50;

/* ============================================================== 主流程 */
const out = {
  meta: { engine: ENGINE, md5Before: MD5_BEFORE, tf: TF, fee: FEE, warmup: WARMUP, holdsDays: HOLDS, books: 0, skipped: [] },
  sig: {}, glob: {}, nb: {},
  cond: {}          // cond[level][grp] = [收益]  grp: nearDaily=日线有信号 / alone=日线无信号
};
[1, 2, 3].forEach(Lv => { out.sig[Lv] = {}; out.cond[Lv] = { nearDaily: [], alone: [] }; HOLDS.forEach(h => out.sig[Lv][h] = []); });
HOLDS.forEach(h => out.glob[h] = []);
NB_WINDOWS.forEach(w => { out.nb[w] = {}; HOLDS.forEach(h => out.nb[w][h] = []); });

let nSig = 0;
let nBook = 0;
for (const code of all) {
  let ks;
  try {
    const k30 = load30(path.join(DIR, code + '.csv'));
    if (k30.length < need) { out.meta.skipped.push(code + '(' + k30.length + '根)'); continue; }
    ks = TF === 30 ? k30 : to60(k30);
    if (ks.length < need) { out.meta.skipped.push(code + '(60m合成后' + ks.length + '根)'); continue; }
  } catch (e) { out.meta.skipped.push(code + '(' + e.message + ')'); continue; }
  out.meta.books++;
  const last = ks.length - 1;
  const rng = L.makeRng((hashSeed(code) + TF) >>> 0);
  const dailyDates = dailySignalDates(code);   // 条件分组：该票日线信号入场日集合
  // 日线日期 → 30m 序列中的日期索引（用于判断「入场前 N 个交易日」）
  const dateList = [];
  for (const k of ks) { if (!dateList.length || dateList[dateList.length - 1] !== k.date) dateList.push(k.date); }
  const dateIdx = new Map(dateList.map((d, i) => [d, i]));

  /* 逐日发现信号 */
  const seen = new Set();
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== 1 || p.level < 1 || p.level > 3) continue;
      if (p.readyK > t) continue;
      const key = p.level + ':' + p.readyK;
      if (seen.has(key)) continue;
      seen.add(key);

      const e = p.readyK + 1;
      if (e < WARMUP || e + maxHoldBars > last) continue;
      if (ks[e].bad) continue;

      /* 信号收益（T+1 合规） */
      let ok = false, firstRet = null;
      for (const hd of HOLDS) {
        const hb = hd * BARS_PER_DAY;
        const r = retAtT1(ks, e, hb, FEE);
        if (r == null) continue;
        ok = true;
        out.sig[p.level][hd].push(r);
        if (hd === HOLDS[Math.floor(HOLDS.length / 2)]) firstRet = r;  // 中位持有期做条件分组
      }
      if (!ok) continue;
      nSig++;

      /* 条件分组：入场前 DAILY_LOOKBACK 个交易日内，日线是否出现过信号入场日 */
      const di = dateIdx.has(ks[e].date) ? dateIdx.get(ks[e].date) : -1;
      let near = false;
      if (di >= 0) {
        for (let d = Math.max(0, di - DAILY_LOOKBACK); d <= di; d++) {
          if (dailyDates.has(dateList[d])) { near = true; break; }
        }
      }
      if (firstRet != null) out.cond[p.level][near ? 'nearDaily' : 'alone'].push(firstRet);

      /* 全区间随机基准（同持有期，同 T+1 断言） */
      for (const hd of HOLDS) {
        const hb = hd * BARS_PER_DAY;
        let acc = 0, n = 0;
        for (let i = 0; i < GLOB_SAMPLES; i++) {
          const ei = WARMUP + Math.floor(rng() * (last - hb - WARMUP));
          const r = retAtT1(ks, ei, hb, FEE);
          if (r != null) { acc += r; n++; }
        }
        if (n) out.glob[hd].push(acc / n);
      }

      /* 邻近窗口随机基准 */
      for (const w of NB_WINDOWS) {
        for (const hd of HOLDS) {
          const hb = hd * BARS_PER_DAY;
          let acc = 0, n = 0;
          const lo = Math.max(WARMUP, e - w), hi = Math.min(last - hb, e + w);
          if (hi <= lo) break;
          for (let i = 0; i < NB_SAMPLES; i++) {
            const ei = lo + Math.floor(rng() * (hi - lo));
            const r = retAtT1(ks, ei, hb, FEE);
            if (r != null) { acc += r; n++; }
          }
          if (n) out.nb[w][hd].push(acc / n);
        }
      }
    }
  }
  log('  [' + (++nBook) + '/' + all.length + '] ' + code + '  ' + ks.length + '根  累计信号' + nSig + '  ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');
}

/* ---------------------------------------------------------------- 输出 */
console.log('\n=========== ' + TF + ' 分钟级别缠论买点回测（T+1 合规） ===========');
console.log('引擎 md5(跑前) ' + MD5_BEFORE);
console.log('TF=' + TF + '分钟  WARMUP=' + WARMUP + '根  持有 ' + HOLDS.join('/') + ' 个交易日  双边费 ' + (FEE * 100) + '%');
console.log('ETF ' + out.meta.books + ' 只（跳过 ' + out.meta.skipped.length + '）  可交易信号 ' + nSig);
console.log('T+1 违规拦截: ' + t1Violations + ' 次（应为 0，持有≥1日设计下不可能触发）\n');

const NM = { 1: '一买', 2: '二买', 3: '三买' };
const HD = TF === 30 ? 8 : 4;   // 每日bar数（用于邻近窗口换算说明）

console.log('【1】信号 vs 全区间随机基准（Welch 两组均值差）');
console.log('买点 持有 | n   信号收益  基准收益     超额   Welch t  95%CI');
console.log('-'.repeat(80));
out.r1 = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = out.sig[Lv][h], b = out.glob[h];
  const ci = L.ci95(a, b), t = L.welchT(a, b);
  out.r1[Lv + '_' + h] = { n: a.length, exp: L.mean(a), base: L.mean(b), edge: ci && ci.d, t, ci };
  console.log(` ${NM[Lv]} ${h}日 |${String(a.length).padStart(5)}  ${L.pc(L.mean(a)).padStart(8)}  ${L.pc(L.mean(b)).padStart(8)}  ${L.pp(ci && ci.d).padStart(8)}  ${L.f2(t).padStart(7)}  [${L.pp(ci && ci.lo)}, ${L.pp(ci && ci.hi)}]`);
}

console.log('\n【2】邻近窗口随机基准（敏感性，窗口=bar数）');
console.log('窗口(' + TF + 'm) | ' + HOLDS.map(h => h + '日超额(t)').join('  |  '));
console.log('-'.repeat(64));
out.r2 = {};
for (const w of NB_WINDOWS) {
  const cells = HOLDS.map(h => {
    const a = [].concat(out.sig[1][h], out.sig[2][h], out.sig[3][h]);
    const b = out.nb[w][h];
    const ci = L.ci95(a, b), t = L.welchT(a, b);
    out.r2[w + '_' + h] = { edge: ci && ci.d, t };
    return (L.pp(ci && ci.d) + '(' + L.f2(t) + ')').padStart(15);
  }).join('  |  ');
  console.log(' ±' + String(w).padStart(2) + ' | ' + cells);
}
console.log('\n（邻近窗口换算：±' + NB_WINDOWS.join('/') + ' bar ≈ ±' + NB_WINDOWS.map(w => (w / HD).toFixed(1)).join('/') + ' 个交易日）');

console.log('\n【3】条件分组（你的痛点）：入场前 ' + DAILY_LOOKBACK + ' 个交易日内日线有无信号');
console.log('持有' + HOLDS[Math.floor(HOLDS.length / 2)] + '日口径 | 日线有信号(nearDaily)      日线无信号(alone)         差');
console.log('-'.repeat(84));
out.r3 = {};
for (const Lv of [1, 2, 3]) {
  const a = out.cond[Lv].nearDaily, b = out.cond[Lv].alone;
  const ci = L.ci95(a, b), t = L.welchT(a, b);
  out.r3[Lv] = { nearN: a.length, nearExp: L.mean(a), aloneN: b.length, aloneExp: L.mean(b), diff: ci && ci.d, t };
  console.log(` ${NM[Lv]} |${String(a.length).padStart(6)}${L.pc(L.mean(a)).padStart(10)} |${String(b.length).padStart(8)}${L.pc(L.mean(b)).padStart(10)} |${L.pp(ci && ci.d).padStart(9)} t=${L.f2(t)}`);
}
const allNear = [].concat(...[1, 2, 3].map(Lv => out.cond[Lv].nearDaily));
const allAlone = [].concat(...[1, 2, 3].map(Lv => out.cond[Lv].alone));
{
  const ci = L.ci95(allNear, allAlone), t = L.welchT(allNear, allAlone);
  out.r3.all = { nearN: allNear.length, nearExp: L.mean(allNear), aloneN: allAlone.length, aloneExp: L.mean(allAlone), diff: ci && ci.d, t };
  console.log(` 合计 |${String(allNear.length).padStart(6)}${L.pc(L.mean(allNear)).padStart(10)} |${String(allAlone.length).padStart(8)}${L.pc(L.mean(allAlone)).padStart(10)} |${L.pp(ci && ci.d).padStart(9)} t=${L.f2(t)}`);
}
console.log('\n判读：alone 组若仍有正超额 → 日线无信号时低级别信号仍有统计支撑（非纯主观）；');
console.log('      alone 组若 ≈0 或为负 → 低级别优势主要依附于日线背景，单独使用证据不足。');

const MD5_AFTER = md5(ENGINE);
console.log('\n引擎 md5(跑后) ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！结果不可信'));
out.meta.md5After = MD5_AFTER;
out.meta.nSig = nSig;
out.meta.t1Violations = t1Violations;
out.meta.elapsed = (Date.now() - T0) / 1000;

fs.mkdirSync(path.join(__dirname, 'tmp'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'tmp', 'bt_30m.json'), JSON.stringify(out));
console.log('\n已写出 tmp/bt_30m.json   耗时 ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');

function hashSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }