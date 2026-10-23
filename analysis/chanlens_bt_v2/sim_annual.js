/* ==========================================================================
 * sim_annual.js —— 组合级年化模拟：信号策略 vs 随机入场 vs 买入持有
 *
 * 回答：策略整体表现如何（盈亏比 / 年化 / 最大回撤 / 资金占用）。
 *
 * 方法（防自欺的三条铁律）：
 *   M1. 必须模拟真实资金曲线：每 ETF 单仓位、信号重叠跳过、空仓期计入年化。
 *       严禁「单笔超额 × 交易频率」外推年化——那是错的。
 *   M2. 随机基准走完全相同的仓位机制（单仓位、跳过重叠），
 *       候选入场数与信号数相同，20 个种子取均值±sd。
 *   M3. 摩擦：双边费 0.1%/笔（与前序回测口径一致）；入场=readyK+1开盘，
 *       持有 N 日收盘卖出；T+1 天然满足（持有≥1日）。
 *
 * 环境变量：TF=daily|30|60   SMOKE=n
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
const SMOKE = parseInt(process.env.SMOKE || '0', 10);
const FEE = 0.001;
const SEEDS = 20;

let DIR, WARMUP, HOLDS, BARS_PER_DAY;
if (TF === 'daily') {
  DIR = 'D:/Trading/data/etfs'; WARMUP = 500; HOLDS = [10, 20]; BARS_PER_DAY = 1;
} else if (TF === '30' || TF === '60') {
  DIR = 'D:/Trading/data/etfs_bt_30m'; WARMUP = TF === '30' ? 500 : 250;
  HOLDS = [1, 2]; BARS_PER_DAY = TF === '30' ? 8 : 4;
} else { console.error('TF 只支持 daily|30|60'); process.exit(1); }
/* HOLDS 环境变量覆盖（单位=交易日，支持小数，如 "2.5,5" = 60m 的 10/20 根 bar） */
const HOLDS_ENV = process.env.HOLDS;
if (HOLDS_ENV) HOLDS = HOLDS_ENV.split(',').map(Number).filter(x => x > 0);
/* LEVEL 环境变量：只交易指定级别买卖点（如 LEVEL=3 纯三买）；不设 = 1~3 级混合 */
const LEVEL = parseInt(process.env.LEVEL || '0', 10);
if (LEVEL && !(LEVEL >= 1 && LEVEL <= 3)) { console.error('LEVEL 只支持 1|2|3'); process.exit(1); }
/* SHIFT 环境变量：入场额外推迟的 bar 数（默认 0 = readyK+1 开盘；SHIFT=1 = readyK+2，即确认收盘后的下一根开盘，严格无可执行性争议口径） */
const SHIFT = parseInt(process.env.SHIFT || '0', 10);
const OUT_TAG = (HOLDS_ENV ? '_' + HOLDS_ENV.replace(/[.,]/g, '-') : '') + (LEVEL ? '_L' + LEVEL : '') + (SHIFT ? '_s' + SHIFT : '');
const T0 = Date.now();
const log = m => process.stderr.write(m + '\n');

/* ---- 数据加载（30m 格式 + 60m 合成，复用 bt_30m.js 逻辑） ---- */
function load30(file) {
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  for (const col of ['时间', '开盘', '收盘', '最高', '最低']) if (ix(col) < 0) throw new Error('表头缺列 ' + col);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const t = String(c[ix('时间')] || '').trim();
    if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(t)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')], h = +c[ix('最高')], lo = +c[ix('最低')];
    const bad = !(o > 0 && isFinite(o)) || !(cl > 0 && isFinite(cl)) ||
                !(h > 0 && isFinite(h)) || !(lo > 0 && isFinite(lo)) || h < lo;
    rows.push({ t, date: t.slice(0, 10), o, c: cl, h, l: lo, v: +c[ix('成交量')] || 0, bad });
  }
  return rows;
}
function to60(k30) {
  const out = [];
  for (let i = 0; i < k30.length; i++) {
    const a = k30[i], b = k30[i + 1];
    if (b && b.date === a.date) { out.push({ t: b.t, date: b.date, o: a.o, c: b.c, h: Math.max(a.h, b.h), l: Math.min(a.l, b.l), v: a.v + b.v, bad: a.bad || b.bad }); i++; }
    else out.push({ ...a });
  }
  return out;
}
function loadData(code) {
  if (TF === 'daily') {
    const ks = L.loadETF(path.join(DIR, code + '.csv')).ks;
    for (const k of ks) k.date = k.t;          // 统一字段：日线 t 即日期
    return ks;
  }
  const k30 = load30(path.join(DIR, code + '.csv'));
  return TF === '30' ? k30 : to60(k30);
}
function hashSeed(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

/* ---- 信号扫描（与 bt.js / bt_30m.js 同口径：逐日切片、首次发现、entry=readyK+1） ---- */
function scanSignals(ks) {
  const seen = new Set(), sigs = [];
  const last = ks.length - 1;
  for (let t = WARMUP; t < ks.length; t++) {
    const res = Chan.analyze(ks.slice(0, t + 1), {});
    for (const p of res.points) {
      if (p.type !== 1 || p.level < 1 || p.level > 3) continue;
      if (LEVEL && p.level !== LEVEL) continue;
      if (p.readyK > t) continue;
      const key = p.level + ':' + p.readyK;
      if (seen.has(key)) continue;
      seen.add(key);
      const e = p.readyK + 1 + SHIFT;
      if (e < WARMUP || e >= ks.length || ks[e].bad) continue;
      sigs.push(e);                       // 已按 e 升序（t 递增，readyK 单调性由 key 去重保证）
    }
  }
  sigs.sort((a, b) => a - b);
  return sigs;
}

/* ---- 单仓位轮动模拟（信号与随机共用） ----
 * eq: 每根 bar 的净值（标记到市）；返回 { eq, trades, exposureBars }
 * 候选入场按序消费：持仓中遇新候选 → 直接放弃（不排队，如实模拟） */
function simulate(ks, candidates, holdBars) {
  const n = ks.length;
  const eq = new Float64Array(n).fill(1);
  let eqv = 1, inPos = false, exitAt = -1, entryAt = -1, entryO = 0;
  let ci = 0, exposureBars = 0;
  const trades = [];
  for (let t = WARMUP; t < n; t++) {
    if (inPos) {
      exposureBars++;
      eqv *= ks[t].c / ks[t - 1].c;            // 持仓中：close-to-close
      if (t === exitAt) {
        eqv *= (1 - FEE);
        const r = ks[t].c / entryO - 1 - FEE;
        if (isFinite(r) && r > -1) trades.push(r); else eqv = NaN;
        inPos = false;
      }
      eq[t] = eqv;
    } else {
      while (ci < candidates.length && candidates[ci] < t) ci++;   // 跳过错过的候选
      if (ci < candidates.length && candidates[ci] === t && t + holdBars < n &&
          !ks[t].bad && !ks[t + holdBars].bad) {
        entryAt = t; exitAt = t + holdBars; entryO = ks[t].o; inPos = true;
        exposureBars++;
        eqv *= ks[t].c / entryO;               // 入场当天 open→close 必须进净值链
        if (t === exitAt) { eqv *= (1 - FEE); trades.push(ks[t].c / entryO - 1 - FEE); inPos = false; }  // holdBars=0 防御
        ci++;                                   // 该候选已消费
      }
      eq[t] = eqv;
    }
  }
  return { eq, trades, exposureBars };
}

/* ---- 组合聚合：按日期对齐各槽位净值求和 → 组合曲线 → CAGR / MaxDD ---- */
/* ---- 组合聚合：每槽位独立复利 → 等权平均 ----
 * 注意：不能用「各槽净值按日期求和」当组合曲线——后上市 ETF 加入时净值+1
 * 会被当成组合增值（假性增长，先期几只 vs 后期 24 只时灌水严重）。
 * 正确口径：每槽位在自己的时间跨度上独立复利，CAGR / MaxDD 取槽位均值。 */
function portfolio(books, holdBars) {
  let expN = 0, totN = 0;
  const allTrades = [], slotCagr = [], slotDD = [], slotYears = [];
  for (const bk of books) {
    const { eq, trades, exposureBars } = simulate(bk.ks, bk.candidates, holdBars);
    expN += exposureBars; totN += bk.ks.length - WARMUP;
    allTrades.push(...trades);
    const n = bk.ks.length;
    const years = (new Date(bk.ks[n - 1].date) - new Date(bk.ks[WARMUP].date)) / (365.25 * 864e5);
    if (years > 0.1 && isFinite(eq[n - 1]) && eq[n - 1] > 0) {
      slotCagr.push(Math.pow(eq[n - 1], 1 / years) - 1);   // eq 起点 = 1
      slotYears.push(years);
      let peak = -Infinity, maxDD = 0;
      for (let t = WARMUP; t < n; t++) { if (eq[t] > peak) peak = eq[t]; const dd = 1 - eq[t] / peak; if (dd > maxDD) maxDD = dd; }
      slotDD.push(maxDD);
    }
  }
  const last = books[books.length - 1].ks;
  return {
    cagr: L.mean(slotCagr), cagrSd: L.sd(slotCagr), maxDD: L.mean(slotDD),
    exposure: expN / totN, trades: allTrades, years: L.mean(slotYears),
    span: [books[0].ks[WARMUP].date, last[last.length - 1].date]
  };
}

/* ---- 交易统计：胜率 / 盈亏比 / 单笔期望 ---- */
function tradeStats(trades) {
  if (!trades.length) return null;
  const wins = trades.filter(r => r > 0), losses = trades.filter(r => r <= 0);
  const aw = wins.length ? L.mean(wins) : 0, al = losses.length ? L.mean(losses) : 0;
  return {
    n: trades.length,
    winRate: wins.length / trades.length,
    avgWin: aw, avgLoss: al,
    plr: al < 0 ? aw / -al : null,           // 盈亏比 = 平均盈利 / |平均亏损|
    exp: L.mean(trades)
  };
}

/* ============================================================== 主流程 */
let codes = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(c => c.replace('.csv', '')).sort();
if (SMOKE > 0) codes = codes.slice(0, SMOKE);

const maxHoldBars = Math.max(...HOLDS) * BARS_PER_DAY;
const books = [];
let skipped = [];
for (const code of codes) {
  try {
    const ks = loadData(code);
    if (ks.length < WARMUP + maxHoldBars + 50) { skipped.push(code + '(' + ks.length + '根)'); continue; }
    const candidates = scanSignals(ks);
    books.push({ code, ks, candidates });
  } catch (e) { skipped.push(code + '(' + e.message + ')'); }
}
log('载入 ' + books.length + ' 只（跳过 ' + skipped.length + '）信号扫描完成 ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');

const out = { meta: { tf: TF, md5Before: MD5_BEFORE, fee: FEE, seeds: SEEDS, warmup: WARMUP, books: books.length, skipped }, res: {} };
const totalSigCand = books.reduce((s, b) => s + b.candidates.length, 0);
console.log('\n========= ' + TF + ' 组合级年化模拟（每ETF单仓位 / 重叠跳过 / 双边费0.1%） =========');
console.log('ETF ' + books.length + ' 只  信号候选 ' + totalSigCand + ' 个  随机基准 ' + SEEDS + ' 种子');

/* 买入持有参考（每槽位全期持有，CAGR 取槽位均值——与信号策略同口径） */
{
  const cs = [];
  for (const bk of books) {
    const s = WARMUP, e = bk.ks.length - 1;
    if (!(bk.ks[s].o > 0) || !isFinite(bk.ks[e].c)) continue;
    const years = (new Date(bk.ks[e].date) - new Date(bk.ks[s].date)) / (365.25 * 864e5);
    if (years < 0.1) continue;
    const g = bk.ks[e].c / bk.ks[s].o * (1 - FEE);
    cs.push(Math.pow(g, 1 / years) - 1);
  }
  out.bh = { cagr: L.mean(cs), cagrSd: L.sd(cs), n: cs.length };
}

for (const hd of HOLDS) {
  const hb = hd * BARS_PER_DAY;
  const sig = portfolio(books, hb);

  /* 随机基准：同候选数、同机制，20 种子 */
  const rCagr = [], rMaxDD = [], rTrades = [], rStats = [];
  for (let s = 1; s <= SEEDS; s++) {
    const rnd = books.map(bk => {
      const rng = L.makeRng(hashSeed(bk.code) + s * 7919 + hb);
      const n = bk.ks.length;
      const arr = [];
      for (let i = 0; i < bk.candidates.length; i++) {
        arr.push(WARMUP + Math.floor(rng() * (n - hb - WARMUP - 1)));
      }
      arr.sort((a, b) => a - b);
      return { code: bk.code, ks: bk.ks, candidates: arr };
    });
    const rp = portfolio(rnd, hb);
    rCagr.push(rp.cagr); rMaxDD.push(rp.maxDD);
    const st = tradeStats(rp.trades); if (st) { rTrades.push(st.n); rStats.push(st); }
  }
  const sSt = tradeStats(sig.trades);
  const rStAvg = {
    cagr: L.mean(rCagr),
    winRate: L.mean(rStats.map(x => x.winRate)),
    plr: L.mean(rStats.map(x => x.plr)),
    exp: L.mean(rStats.map(x => x.exp)),
    n: L.mean(rTrades)
  };
  const rCagrSd = L.sd(rCagr);
  out.res[hd] = {
    sig: { cagr: sig.cagr, maxDD: sig.maxDD, exposure: sig.exposure, years: sig.years, span: sig.dates, stats: sSt },
    rnd: { cagr: L.mean(rCagr), cagrSd: rCagrSd, maxDD: L.mean(rMaxDD), stats: rStAvg }
  };
  console.log('\n【持有 ' + hd + ' 个交易日】  区间 ' + sig.span[0] + ' ~ ' + sig.span[1] + '（槽位均值 ' + (sig.years || 0).toFixed(1) + ' 年）');
  console.log('            交易数   胜率    盈亏比   单笔期望   年化      最大回撤   资金占用');
  console.log('  信号策略  ' + String(sSt.n).padStart(5) + '  ' + (100 * sSt.winRate).toFixed(1).padStart(5) + '%  ' +
    L.f2(sSt.plr).padStart(6) + '  ' + L.pc(sSt.exp).padStart(8) + '  ' + L.pc(sig.cagr).padStart(8) + '  ' +
    (100 * sig.maxDD).toFixed(1).padStart(6) + '%  ' + (100 * sig.exposure).toFixed(0).padStart(5) + '%');
  console.log('  随机基准  ' + String(rStAvg.n.toFixed(0)).padStart(5) + '  ' + (100 * rStAvg.winRate).toFixed(1).padStart(5) + '%  ' +
    L.f2(rStAvg.plr).padStart(6) + '  ' + L.pc(rStAvg.exp).padStart(8) + '  ' + L.pc(rStAvg.cagr).padStart(8) + '±' +
    (100 * rCagrSd).toFixed(1) + '% ' + (100 * L.mean(rMaxDD)).toFixed(1).padStart(6) + '%');
  console.log('  买入持有（参考，每槽位均值）: 年化 ' + L.pc(out.bh.cagr) + ' ± ' + (100 * (out.bh.cagrSd || 0)).toFixed(1) + '%');
}

const MD5_AFTER = md5(ENGINE);
out.meta.md5After = MD5_AFTER;
out.meta.elapsed = (Date.now() - T0) / 1000;
console.log('\n引擎 md5 ' + MD5_AFTER + (MD5_AFTER === MD5_BEFORE ? '  ✓ 未被修改' : '  ✗ 被修改！'));
fs.mkdirSync(path.join(__dirname, 'tmp'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'tmp', 'sim_' + TF + OUT_TAG + '.json'), JSON.stringify(out));
console.log('已写出 tmp/sim_' + TF + '.json  耗时 ' + ((Date.now() - T0) / 1000).toFixed(0) + 's');
