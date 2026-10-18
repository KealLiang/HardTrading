/* ==========================================================================
 * bt_sell.js —— 卖点回测（日线 / 30分钟 / 60分钟，TF 环境变量切换）
 *
 * 卖点评估口径（与买点镜像，但无空头交易）：
 *   卖点出现后，从 readyK+1 开盘起持有 N 日 —— 收益为负 = 卖点后确实走弱 = 该卖。
 *   三项指标：
 *     ① 超额 = 信号收益 − 随机基准收益（**负 = 有效**，卖点后跑输随机）
 *     ② 下跌成功率 = 信号后 N 日收盘 < 入场开盘 的占比，对比随机基准的下跌占比
 *     ③ 两比例差异 z 检验
 *
 * 纪律（继承 bt.js / bt_30m.js）：
 *   D1. 只读生产引擎 chan.js，跑前跑后 md5 双向核对
 *   D2. 观察起点 = readyK+1 开盘（引擎既定 readyK 语义）
 *   D3. 双随机基准（全区间 + 邻近窗口），窗口扫描做敏感性
 *   D4. 费率记 0：卖点评估的是价格行为，基准费率相同会在超额中抵消
 *
 * 环境变量：
 *   TF=daily|30|60   K线级别
 *   SMOKE=n          只取前 n 只（冒烟）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const L = require('./lib.js');

const ENGINE = 'D:/Trading/plugins/chanlens/core/chan.js';
const Chan = require(ENGINE);
const md5 = f => crypto.createHash('md5').update(fs.readFileSync(f)).digest('hex');
const MD5_BEFORE = md5(ENGINE);

const TF = process.env.TF || 'daily';
if (TF !== 'daily' && TF !== '30' && TF !== '60') { console.error('TF 只支持 daily|30|60'); process.exit(1); }

const DIR = TF === 'daily' ? 'D:/Trading/data/etfs' : 'D:/Trading/data/etfs_bt_30m';
const WARMUP = TF === 'daily' ? 500 : (TF === '30' ? 500 : 250);
const BPD = TF === 'daily' ? 1 : (TF === '30' ? 8 : 4);       // 每交易日 bar 数
const HOLDS = TF === 'daily' ? [5, 10, 20] : [1, 2, 5];       // 持有交易日数
const NB_WINDOWS = TF === 'daily' ? [5, 10, 20, 40] : [8, 16, 32, 64];
const NB_SAMPLES = 800, GLOB_SAMPLES = 800;

const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ------------------------------------------------------- 数据加载 */
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
    const bad = !(o > 0 && isFinite(o)) || !(cl > 0 && isFinite(cl)) ||
                !(h > 0 && isFinite(h)) || !(l > 0 && isFinite(l)) || h < l;
    rows.push({ t, date: t.slice(0, 10), o, c: cl, h, l, bad });
  }
  return rows;
}
function to60(ks30) {
  const out = [];
  for (let i = 0; i < ks30.length; i++) {
    const a = ks30[i], b = ks30[i + 1];
    if (b && b.date === a.date) {
      out.push({ t: b.t, date: b.date, o: a.o, c: b.c, h: Math.max(a.h, b.h), l: Math.min(a.l, b.l), bad: a.bad || b.bad });
      i++;
    } else out.push({ ...a });
  }
  return out;
}
function loadBook(code) {
  const f = path.join(DIR, code + '.csv');
  if (TF === 'daily') return L.loadETF(f).ks;
  const k30 = load30(f);
  return TF === '30' ? k30 : to60(k30);
}

/* ------------------------------------------------------- 选票 */
let all = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(c => c.replace('.csv', '')).sort();
const SMOKE = parseInt(process.env.SMOKE || '0', 10);
if (SMOKE > 0) {
  // 冒烟取历史最长的 n 只（短历史新票会被 need 门槛跳过，冒烟无意义）
  all = all.map(c => {
    try {
      const n = fs.readFileSync(path.join(DIR, c + '.csv'), 'utf8').split(/\r?\n/).filter(x => x.trim()).length;
      return { c, n };
    } catch (e) { return { c, n: 0 }; }
  }).sort((a, b) => b.n - a.n).slice(0, SMOKE).map(x => x.c);
}

const maxHoldBars = Math.max(...HOLDS) * BPD;
const need = WARMUP + maxHoldBars + 100;

/* ============================================================== 主流程 */
const out = {
  meta: { engine: ENGINE, md5Before: MD5_BEFORE, tf: TF, warmup: WARMUP, holdsDays: HOLDS, books: 0, skipped: [] },
  sig: {}, glob: {}, nb: {}
};
[1, 2, 3].forEach(Lv => { out.sig[Lv] = {}; HOLDS.forEach(h => out.sig[Lv][h] = []); });
HOLDS.forEach(h => out.glob[h] = []);
NB_WINDOWS.forEach(w => { out.nb[w] = {}; HOLDS.forEach(h => out.nb[w][h] = []); });

let nSig = 0, nBook = 0;
/* 基准下跌率必须用原始抽样（均值序列几乎恒为正，无法算下跌率） */
const globRaw = {}; HOLDS.forEach(h => globRaw[h] = []);
for (const code of all) {
  let ks;
  try {
    ks = loadBook(code);
    if (ks.length < need) { out.meta.skipped.push(code + '(' + ks.length + '根)'); continue; }
  } catch (e) { out.meta.skipped.push(code + '(' + e.message + ')'); continue; }
  out.meta.books++;
  const last = ks.length - 1;
  const rng = L.makeRng((hashSeed(code) + (TF === 'daily' ? 0 : TF === '30' ? 30 : 60)) >>> 0);

  /* 逐 bar 发现卖点信号（无未来视角：只看 slice(0,t+1)） */
  const seen = new Set();
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== -1 || p.level < 1 || p.level > 3) continue;   // 仅卖点
      if (p.readyK > t) continue;
      const key = p.level + ':' + p.readyK;
      if (seen.has(key)) continue;
      seen.add(key);

      const e = p.readyK + 1;
      if (e < WARMUP || e + maxHoldBars > last) continue;
      if (ks[e].bad) continue;

      let ok = false;
      for (const hd of HOLDS) {
        const hb = hd * BPD;
        const j = e + hb;
        if (j >= ks.length) continue;
        const r = ks[j].c / ks[e].o - 1;               // 费率 0（D4）
        if (!isFinite(r)) continue;
        ok = true;
        out.sig[p.level][hd].push(r);
      }
      if (!ok) continue;
      nSig++;

      /* 全区间随机基准 */
      for (const hd of HOLDS) {
        const hb = hd * BPD;
        let acc = 0, n = 0;
        for (let i = 0; i < GLOB_SAMPLES; i++) {
          const ei = WARMUP + Math.floor(rng() * (last - hb - WARMUP));
          const j = ei + hb;
          if (j >= ks.length || ks[ei].bad || ks[j].bad) continue;
          const r = ks[j].c / ks[ei].o - 1;
          if (!isFinite(r)) continue;
          acc += r; n++;
          globRaw[hd].push(r);
        }
        if (n) out.glob[hd].push(acc / n);
      }

      /* 邻近窗口随机基准 */
      for (const w of NB_WINDOWS) {
        for (const hd of HOLDS) {
          const hb = hd * BPD;
          let acc = 0, n = 0;
          const lo = Math.max(WARMUP, e - w), hi = Math.min(last - hb, e + w);
          if (hi <= lo) break;
          for (let i = 0; i < NB_SAMPLES; i++) {
            const ei = lo + Math.floor(rng() * (hi - lo));
            const j = ei + hb;
            if (j >= ks.length || ks[ei].bad || ks[j].bad) continue;
            acc += ks[j].c / ks[ei].o - 1; n++;
          }
          if (n) out.nb[w][hd].push(acc / n);
        }
      }
    }
  }
  log('  [' + (++nBook) + '/' + all.length + '] ' + code + '  ' + ks.length + '根  累计信号' + nSig + '  ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');
}

/* ---------------------------------------------------------------- 输出 */
const label = TF === 'daily' ? '日线' : TF + '分钟';
console.log('\n=========== ' + label + '缠论卖点回测 ===========');
console.log('引擎 md5(跑前) ' + MD5_BEFORE);
console.log('观察起点 = readyK+1 开盘  持有 ' + HOLDS.join('/') + ' 个交易日  费率 0（价格行为口径）');
console.log('ETF ' + out.meta.books + ' 只（跳过 ' + out.meta.skipped.length + '）  可观察信号 ' + nSig);
console.log('判读：超额为【负】且显著 = 卖点后确实跑输随机 = 卖点有效\n');

const NM = { 1: '一卖', 2: '二卖', 3: '三卖' };
const downRate = a => { let d = 0; for (const x of a) if (x < 0) d++; return a.length ? d / a.length : null; };
const propZ = (a, b) => {
  // 两比例差异 z 检验（信号下跌率 vs 基准下跌率）
  const pa = downRate(a), pb = downRate(b), na = a.length, nb = b.length;
  if (!na || !nb || pa == null || pb == null) return null;
  const p = (pa * na + pb * nb) / (na + nb);
  const se = Math.sqrt(p * (1 - p) * (1 / na + 1 / nb));
  return se > 0 ? (pa - pb) / se : null;
};

console.log('【1】信号 vs 全区间随机基准');
console.log('卖点 持有 | n  信号收益  基准收益   超额(负=有效)  Welch t | 下跌率  基准下跌率   z');
console.log('-'.repeat(92));
out.r1 = {};
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = out.sig[Lv][h], b = out.glob[h], rawB = globRaw[h];
  const ci = L.ci95(a, b), t = L.welchT(a, b), z = propZ(a, rawB);
  out.r1[Lv + '_' + h] = {
    n: a.length, exp: L.mean(a), base: L.mean(b), edge: ci && ci.d, t,
    down: downRate(a), baseDown: downRate(rawB), z
  };
  console.log(` ${NM[Lv]} ${String(h).padStart(2)}日 |${String(a.length).padStart(5)}  ${L.pc(L.mean(a)).padStart(8)}  ${L.pc(L.mean(b)).padStart(8)}  ${L.pp(ci && ci.d).padStart(10)}  ${L.f2(t).padStart(8)} |${(100 * downRate(a)).toFixed(1).padStart(6)}%  ${(100 * downRate(rawB)).toFixed(1).padStart(6)}%  ${L.f2(z).padStart(6)}`);
}

console.log('\n【2】邻近窗口随机基准（敏感性，合并三类）');
console.log('窗口(' + (TF === 'daily' ? '日' : 'bar') + ') | ' + HOLDS.map(h => h + '日超额(t)').join('  |  '));
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

console.log('\n【3】自检');
const anyNaN = HOLDS.some(h => out.glob[h].some(x => !isFinite(x)) || [1, 2, 3].some(Lv => out.sig[Lv][h].some(x => !isFinite(x))));
console.log('  收益序列含 NaN/Inf: ' + (anyNaN ? '有（异常！）' : '无'));
const MD5_AFTER = md5(ENGINE);
console.log('  引擎 md5(跑后) ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！结果不可信'));
out.meta.md5After = MD5_AFTER;
out.meta.nSig = nSig;
out.meta.elapsed = (Date.now() - T0) / 1000;

fs.mkdirSync(path.join(__dirname, 'tmp'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'tmp', 'bt_sell_' + TF + '.json'), JSON.stringify(out));
console.log('\n已写出 tmp/bt_sell_' + TF + '.json   耗时 ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');

function hashSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
