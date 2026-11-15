/* 主线（行业强度）过滤能不能增强信号
 *
 * 口径与 bt_hold.js 完全一致：lag==1、entry=discT+1 开盘、FEE=0.001、
 * 基线「同季度 + 同价位分位 ±0.15 + 至少 8 个对照日」。
 *
 * 主线定义（全部只用 discT 日收盘及以前的信息，无前视）：
 *   P20  行业指数过去 20 个交易日涨幅的截面分位（0~1，1 最强）
 *   P60  同上，60 日
 *   PA   行业成交额占全市场比重的截面分位
 *   PAc  该比重的 5 日 vs 60 日变化（资金流入）的截面分位
 *
 * 四个对照：
 *   A  绝对收益：主线内 vs 主线外
 *   B  vs 同股同季同价位（ex4，与正文主表同口径）
 *   C  vs 所属行业指数（行业 alpha）：去掉行业 beta 后还剩什么
 *   D  严格版：主线内信号 vs 主线内对照日（基线池也只取行业当时在主线里的日子）
 *
 * 用法：STOCKS=1 node theme.js
 */
const fs = require('fs');
const path = require('path');
const L = require('./lib');

const FEE = 0.001;
const PCT_WIN = 250;      // 价格分位窗口
const B4_BAND = 0.15;     // 同价位带宽
const MIN_POOL = 8;       // 同价位对照日下限
const XS = [3, 5, 10, 20, 60];
const TOP_Q = 0.75;       // 「主线」= 行业强度前 25%
const MIN_COVER = 0.5;    // 当日至少一半行业有数据才做排名

const SW_DIR = 'D:/Trading/data/sw_industry';
const PACK = path.join(__dirname, 'tmp', 'pack_daily_stock.json');
const OUT_TXT = path.join(__dirname, 'out', 'theme_stock.txt');

const mean = a => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
const sd = a => {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, v) => s + (v - m) * (v - m), 0) / (a.length - 1));
};
const tStat = a => {
  const s = sd(a);
  return s && s > 0 ? mean(a) / (s / Math.sqrt(a.length)) : null;
};
const med = a => {
  if (!a.length) return null;
  const s = a.slice().sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const pct = v => (v == null ? '—' : (100 * v).toFixed(2) + '%');
const pp = v => (v == null ? '—' : (v >= 0 ? '+' : '\u2212') + (100 * Math.abs(v)).toFixed(2) + 'pp');
const f2 = v => (v == null ? '—' : v.toFixed(2));

const LOG = [];
const log = s => { LOG.push(s); console.log(s); };

/* ---------- 行业指数 ---------- */
function loadSw() {
  const meta = JSON.parse(fs.readFileSync(path.join(SW_DIR, 'meta.json'), 'utf8'));
  const sws = [];
  for (const code of Object.keys(meta)) {
    const fp = path.join(SW_DIR, code + '.csv');
    if (!fs.existsSync(fp)) continue;
    const rows = fs.readFileSync(fp, 'utf8').trim().split(/\r?\n/).slice(1)
      .map(l => l.split(','));
    const dates = [], c = [], amt = [];
    // CSV 列序：代码,日期,收盘,开盘,最高,最低,成交量,成交额
    for (const r of rows) {
      if (!r[1]) continue;
      dates.push(r[1]);
      c.push(+r[2]);
      amt.push(+r[7]);
    }
    sws.push({ code, name: meta[code], dates, c, amt, idx: new Map(dates.map((d, i) => [d, i])) });
  }
  return sws;
}

/* 每个交易日的行业截面：涨幅分位、成交额占比分位 */
function buildRank(sws) {
  const allDates = new Set();
  for (const s of sws) for (const d of s.dates) allDates.add(d);
  const dates = Array.from(allDates).sort();
  const rank = new Map();   // date -> { swCode: {p20,p60,pa,pac} }
  const rdates = [];        // 只含「有完整截面」的日期
  const needed = sws.length * MIN_COVER;

  for (const d of dates) {
    const rows = [];
    let totalAmt = 0, nAmt = 0;
    for (const s of sws) {
      const i = s.idx.get(d);
      if (i == null || i < 121) continue;
      const r20 = s.c[i] / s.c[i - 20] - 1;
      const r60 = s.c[i] / s.c[i - 60] - 1;
      const r120 = i >= 120 ? s.c[i] / s.c[i - 120] - 1 : null;
      const r250 = i >= 250 ? s.c[i] / s.c[i - 250] - 1 : null;
      // 成交额占比：20 日均
      let a20 = 0, a60 = 0;
      for (let k = 0; k < 20; k++) a20 += s.amt[i - k];
      for (let k = 0; k < 60; k++) a60 += s.amt[i - k];
      a20 /= 20; a60 /= 60;
      rows.push({ code: s.code, r20, r60, r120, r250, a20, a60 });
      totalAmt += a20; nAmt++;
    }
    if (rows.length < needed) continue;
    // 成交额占比 + 短期抬升
    for (const r of rows) r.share = totalAmt > 0 ? r.a20 / totalAmt : 0;
    const pctRank = (arr, key) => {
      const s = arr.filter(v => v[key] != null).sort((a, b) => a[key] - b[key]);
      const m = new Map();
      s.forEach((v, i) => m.set(v.code, s.length > 1 ? i / (s.length - 1) : 0.5));
      return m;
    };
    for (const r of rows) r.chg = r.a60 > 0 ? r.a20 / r.a60 - 1 : 0;
    const m20 = pctRank(rows, 'r20'), m60 = pctRank(rows, 'r60');
    const m120 = pctRank(rows, 'r120'), m250 = pctRank(rows, 'r250');
    const mpa = pctRank(rows, 'share'), mpac = pctRank(rows, 'chg');
    const box = {};
    for (const r of rows) {
      box[r.code] = {
        p20: m20.get(r.code), p60: m60.get(r.code), p120: m120.get(r.code), p250: m250.get(r.code),
        pa: mpa.get(r.code), pac: mpac.get(r.code)
      };
    }
    rank.set(d, box);
    rdates.push(d);
  }
  return { dates: rdates, all: dates, rank };
}

/* 取 date 当日或之前最近的行业截面 */
function rankAt(R, date) {
  let lo = 0, hi = R.dates.length - 1, ans = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (R.dates[m] <= date) { ans = m; lo = m + 1; } else hi = m - 1;
  }
  return ans < 0 ? null : R.rank.get(R.dates[ans]) || null;
}

/* 行业指数在 date 的点位（取当日或之前最近） */
function swClose(sw, date) {
  let lo = 0, hi = sw.dates.length - 1, ans = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (sw.dates[m] <= date) { ans = m; lo = m + 1; } else hi = m - 1;
  }
  return ans < 0 ? null : sw.c[ans];
}

function tradableMask(p) {
  const n = p.c.length, ok = new Array(n).fill(true);
  for (let i = 1; i < n; i++) {
    if (p.h[i] === p.l[i] && p.o[i] > p.c[i - 1] * 1.045) { ok[i] = false; continue; }
    if ((Date.parse(p.dates[i]) - Date.parse(p.dates[i - 1])) / 86400000 > 15) ok[i] = false;
  }
  return ok;
}

function pricePct(p) {
  const n = p.c.length, out = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) {
      if (p.c[j] < lo) lo = p.c[j];
      if (p.c[j] > hi) hi = p.c[j];
    }
    out[i] = hi > lo ? (p.c[i] - lo) / (hi - lo) : null;
  }
  return out;
}

/* ---------- 主流程 ---------- */
function main() {
  fs.mkdirSync(path.join(__dirname, 'out'), { recursive: true });
  const sws = loadSw();
  const s2s = JSON.parse(fs.readFileSync(path.join(SW_DIR, 'stock2sw.json'), 'utf8'));
  const R = buildRank(sws);
  log('行业指数 ' + sws.length + ' 个，全部交易日 ' + R.all.length + ' 个，有完整截面 ' + R.rank.size +
    ' 个（' + R.all[0] + ' ~ ' + R.all[R.all.length - 1] + '）');

  const swByCode = new Map(sws.map(s => [s.code, s]));
  const pack = JSON.parse(fs.readFileSync(PACK, 'utf8'));

  const miss = pack.packs.filter(p => !s2s[p.code]).map(p => p.code);
  if (miss.length) log('⚠ 无行业归属：' + miss.join(','));

  const rows = [];   // 每个信号
  const base = [];   // 每个 (信号) 的基线池，用于严格对照
  let nCover = 0, nAll = 0;

  for (const p of pack.packs) {
    const swc = s2s[p.code];
    const sw = swc ? swByCode.get(swc) : null;
    const n = p.o.length;
    const trad = tradableMask(p);
    const pq = pricePct(p);
    const q = p.dates.map(d => d.slice(0, 4) + 'Q' + (Math.floor((+d.slice(5, 7) - 1) / 3) + 1));
    const sx = p.dates.map(d => (sw ? swClose(sw, d) : null));

    // 基线池（每 x 一份）
    const pools = {};
    for (const x of XS) {
      const g = {};
      for (let t = p.warmup; t + x <= n - 1; t++) {
        if (!trad[t] || pq[t] == null) continue;
        if (sx[t] == null || sx[t + x] == null) continue;
        const ir = sx[t + x] / sx[t] - 1;         // 行业指数同期收益
        (g[q[t]] = g[q[t]] || []).push({ t, r: p.o[t + x] / p.o[t] - 1 - FEE, ir, pc: pq[t] });
      }
      pools[x] = g;
    }

    for (const b of p.buy || []) {
      if (b.discT - b.readyK !== 1) continue;      // 只用当场可发现的
      if (!(b.level >= 1 && b.level <= 3)) continue;
      if (!sw) continue;
      const e = b.discT + 1;
      if (e + 60 > n - 1 || !trad[e] || pq[e] == null) continue;
      // 主线状态：discT 日收盘可知的行业截面
      const rk = rankAt(R, p.dates[b.discT]);
      if (!rk || !rk[swc]) continue;
      nAll++;
      const m = rk[swc];
      if (m.p20 == null) continue;
      nCover++;

      const rec = {
        code: p.code, sw: swc, swName: sw.name, date: p.dates[e], type: 'L' + b.level,
        p20: m.p20, p60: m.p60, p120: m.p120 == null ? null : m.p120,
        p250: m.p250 == null ? null : m.p250, pa: m.pa, pac: m.pac,
        r: {}, ex4: {}, exInd: {}, exIndB: {},
        stkMom: p.c[b.discT] / p.c[Math.max(0, b.discT - 20)] - 1
      };
      for (const x of XS) {
        const ei = e + x;
        if (ei > n - 1) { rec.r[x] = rec.ex4[x] = rec.exInd[x] = rec.exIndB[x] = null; continue; }
        const r = p.o[ei] / p.o[e] - 1 - FEE;
        const ir = sx[ei] / sx[e] - 1;
        rec.r[x] = r;
        rec.exInd[x] = r - ir;                       // 行业 alpha
        const pool = (pools[x][q[e]] || []).filter(z => z.t !== e && Math.abs(z.pc - pq[e]) <= B4_BAND);
        if (pool.length >= MIN_POOL) {
          const B = mean(pool.map(z => z.r));
          rec.ex4[x] = r - B;
          rec['B' + x] = B;
        } else { rec.ex4[x] = null; rec['B' + x] = null; }
        // 基线池里的行业 alpha（同样同价位）
        rec.exIndB[x] = pool.length >= MIN_POOL ? mean(pool.map(z => z.r - z.ir)) : null;
        // 严格版：只比「行业当时也在主线」的对照日
        const th = pool.filter(z => {
          const r2 = rankAt(R, p.dates[z.t]);
          return r2 && r2[swc] && r2[swc].p20 >= TOP_Q;
        });
        if (th.length >= MIN_POOL) {
          const Bt = mean(th.map(z => z.r));
          rec['ex4t' + x] = r - Bt;
          rec['Bt' + x] = Bt;
        } else { rec['ex4t' + x] = null; rec['Bt' + x] = null; }
      }
      rows.push(rec);
    }
  }

  log('信号 ' + nAll + ' 个，有行业排名 ' + nCover + ' 个\n');

  /* ---------- 表 1：按行业 20 日强度分桶 ---------- */
  const BUCKETS = [
    [0.90, 1.01, '前 10%（≈前3名）'],
    [0.75, 0.90, '前 10~25%'],
    [0.50, 0.75, '中上 25~50%'],
    [0.25, 0.50, '中下 50~75%'],
    [0.00, 0.25, '后 25%']
  ];
  const TAB = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty);
    TAB[ty] = BUCKETS.map(([lo, hi, lab]) => {
      const sub = s.filter(z => z.p20 >= lo && z.p20 < hi);
      const a = sub.length;
      const o = { lab, n: a, share: a / s.length };
      for (const x of XS) {
        const v = sub.map(z => z.r[x]).filter(v => v != null);
        const e4 = sub.map(z => z.ex4[x]).filter(v => v != null);
        const ei = sub.map(z => z.exInd[x]).filter(v => v != null);
        const e4t = sub.map(z => z['ex4t' + x]).filter(v => v != null);
        o['r' + x] = mean(v); o['ex4' + x] = mean(e4); o['t4_' + x] = tStat(e4);
        o['exInd' + x] = mean(ei); o['tI_' + x] = tStat(ei);
        o['ex4t' + x] = mean(e4t); o['tT_' + x] = tStat(e4t); o['nT_' + x] = e4t.length;
      }
      return o;
    });
  }

  log('=== 表 1 按行业 20 日强度分位（x=20）===');
  log('类型  分桶                  n    占比    单笔20    ex4(t)            vs行业alpha(t)     严格版(t)          n严格');
  for (const ty of ['L1', 'L2', 'L3']) {
    for (const o of TAB[ty]) {
      log(ty + '    ' + o.lab.padEnd(20) + String(o.n).padStart(5) + '  ' + pct(o.share).padStart(7) +
        '  ' + pp(o.r20).padStart(8) + '  ' + (pp(o.ex420) + '(' + f2(o.t4_20) + ')').padStart(17) +
        '  ' + (pp(o.exInd20) + '(' + f2(o.tI_20) + ')').padStart(18) +
        '  ' + (pp(o.ex4t20) + '(' + f2(o.tT_20) + ')').padStart(18) + '  ' + String(o.nT_20).padStart(5));
    }
    log('');
  }

  /* ---------- 表 2：主线 vs 非主线（直接用阈值切） ---------- */
  const CUT = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty);
    const inT = s.filter(z => z.p20 >= TOP_Q), outT = s.filter(z => z.p20 < TOP_Q);
    const o = { nIn: inT.length, nOut: outT.length, shareIn: inT.length / s.length };
    for (const x of XS) {
      o['rIn' + x] = mean(inT.map(z => z.r[x]).filter(v => v != null));
      o['rOut' + x] = mean(outT.map(z => z.r[x]).filter(v => v != null));
      const a = inT.map(z => z.ex4[x]).filter(v => v != null);
      const b2 = outT.map(z => z.ex4[x]).filter(v => v != null);
      o['ex4In' + x] = mean(a); o['t4In_' + x] = tStat(a);
      o['ex4Out' + x] = mean(b2); o['t4Out_' + x] = tStat(b2);
      o['dEx4_' + x] = mean(a) != null && mean(b2) != null ? mean(a) - mean(b2) : null;
      const ia = inT.map(z => z.exInd[x]).filter(v => v != null);
      const ib = outT.map(z => z.exInd[x]).filter(v => v != null);
      o['exIndIn' + x] = mean(ia); o['tIIn_' + x] = tStat(ia);
      o['exIndOut' + x] = mean(ib);
      const ta = inT.map(z => z['ex4t' + x]).filter(v => v != null);
      o['ex4tIn' + x] = mean(ta); o['tTIn_' + x] = tStat(ta); o['nTIn_' + x] = ta.length;
    }
    CUT[ty] = o;
  }

  log('=== 表 2 主线（行业 20 日强度前 25%）vs 其余 ===');
  log('类型   x   主线n  其余n  主线占比   主线单笔  其余单笔   主线ex4(t)         其余ex4(t)        差');
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = CUT[ty];
    for (const x of XS) {
      log(ty + '   ' + String(x).padStart(3) + String(o.nIn).padStart(7) + String(o.nOut).padStart(7) +
        '  ' + pct(o.shareIn).padStart(8) + '  ' + pp(o['rIn' + x]).padStart(9) + '  ' + pp(o['rOut' + x]).padStart(9) +
        '   ' + (pp(o['ex4In' + x]) + '(' + f2(o['t4In_' + x]) + ')').padStart(17) +
        '   ' + (pp(o['ex4Out' + x]) + '(' + f2(o['t4Out_' + x]) + ')').padStart(17) +
        '   ' + pp(o['dEx4_' + x]).padStart(8));
    }
    log('');
  }

  /* ---------- 表 3：四种主线定义 —— 必须按类型分开看 ---------- */
  // 合并三类会被样本结构带偏（三买有 45% 落在主线，一买只有 14%）
  const DEF = {};
  const DEFNAME = { p20: '行业 20 日涨幅', p60: '行业 60 日涨幅', p120: '行业 120 日涨幅',
    p250: '行业 250 日涨幅', pa: '行业成交额占比', pac: '成交额占比抬升' };
  const DKEYS = ['p20', 'p60', 'p120', 'p250', 'pa', 'pac'];
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty);
    DEF[ty] = {};
    for (const key of DKEYS) {
      const ss = s.filter(z => z[key] != null);
      const inT = ss.filter(z => z[key] >= TOP_Q), outT = ss.filter(z => z[key] < TOP_Q);
      const o = {
        nIn: inT.length, nOut: outT.length, shareIn: inT.length / ss.length,
        ex4In: mean(inT.map(z => z.ex4[20]).filter(v => v != null)),
        t4In: tStat(inT.map(z => z.ex4[20]).filter(v => v != null)),
        ex4Out: mean(outT.map(z => z.ex4[20]).filter(v => v != null)),
        t4Out: tStat(outT.map(z => z.ex4[20]).filter(v => v != null)),
        rIn: mean(inT.map(z => z.r[20]).filter(v => v != null)),
        rOut: mean(outT.map(z => z.r[20]).filter(v => v != null))
      };
      o.d = o.ex4In != null && o.ex4Out != null ? o.ex4In - o.ex4Out : null;
      DEF[ty][key] = o;
    }
  }
  log('=== 表 3 四种「主线」定义的一致性（x=20，按类型分开）===');
  for (const ty of ['L1', 'L2', 'L3']) {
    log('-- ' + ty + ' --');
    log('定义                主线n  占比     主线ex4(t)          非主线ex4(t)        差');
    for (const key of DKEYS) {
      const o = DEF[ty][key];
      log(DEFNAME[key].padEnd(18) + String(o.nIn).padStart(5) + '  ' + pct(o.shareIn).padStart(7) +
        '  ' + (pp(o.ex4In) + '(' + f2(o.t4In) + ')').padStart(17) +
        '  ' + (pp(o.ex4Out) + '(' + f2(o.t4Out) + ')').padStart(18) + '  ' + pp(o.d).padStart(8));
    }
    log('');
  }

  /* ---------- 表 4：基线效应 —— 主线里「随便买」本来就更赚吗 ---------- */
  // 如果 B_theme（同价位、且行业当时在主线）明显高于 B_all，
  // 那「主线内信号超额低」就不是信号变差，而是基线变高了。
  const BEF = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty && z.ex4[20] != null);
    const bAll = s.map(z => z.B20).filter(v => v != null);
    const bTh = s.map(z => z.Bt20).filter(v => v != null);
    const sr = s.map(z => z.ex4t20).filter(v => v != null);
    BEF[ty] = {
      n: s.length, nTh: bTh.length,
      bAll: mean(bAll), bTh: mean(bTh),
      r: mean(s.map(z => z.r[20]).filter(v => v != null)),
      ex4: mean(s.map(z => z.ex4[20]).filter(v => v != null)),
      exStrict: mean(sr), tStrict: tStat(sr)
    };
    BEF[ty].dB = BEF[ty].bAll != null && BEF[ty].bTh != null ? BEF[ty].bTh - BEF[ty].bAll : null;
  }
  log('=== 表 4 基线效应：主线内「随便买」的收益 vs 全体「随便买」（x=20）===');
  log('类型    n     信号      B_全体     B_主线内   基线上移    ex4(vs全体)  严格ex4(vs主线内)');
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = BEF[ty];
    log(ty + String(o.n).padStart(7) + '  ' + pp(o.r).padStart(8) + '  ' + pp(o.bAll).padStart(8) + '  ' +
      pp(o.bTh).padStart(8) + '  ' + pp(o.dB).padStart(8) + '  ' + pp(o.ex4).padStart(11) + '  ' +
      (pp(o.exStrict) + '(' + f2(o.tStrict) + ')').padStart(18));
  }
  log('');

  /* ---------- 表 5：主线 × 个股自身强度 ---------- */
  // 你的打法里有第二层条件：要做「已经启动」的票。两个条件叠起来是什么效果
  const CROSS = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty && z.stkMom != null && z.ex4[20] != null);
    for (const [inT, lab] of [[true, '主线'], [false, '非主线']]) {
      for (const [strong, lab2] of [[true, '个股强'], [false, '个股弱']]) {
        const sub = s.filter(z => (z.p20 >= TOP_Q) === inT && (z.stkMom > 0) === strong);
        const e = sub.map(z => z.ex4[20]).filter(v => v != null);
        CROSS[ty + lab + lab2] = {
          n: sub.length, share: sub.length / s.length,
          r: mean(sub.map(z => z.r[20]).filter(v => v != null)),
          ex4: mean(e), t: tStat(e)
        };
      }
    }
  }
  log('=== 表 5 主线 × 个股 20 日动量（x=20，超额 vs 同季同价位）===');
  log('类型  组合        n    占比    单笔      超额(t)');
  for (const ty of ['L1', 'L2', 'L3']) {
    for (const lab of ['主线', '非主线']) {
      for (const lab2 of ['个股强', '个股弱']) {
        const o = CROSS[ty + lab + lab2];
        log(ty + '   ' + (lab + lab2).padEnd(9) + String(o.n).padStart(5) + '  ' + pct(o.share).padStart(6) +
          '  ' + pp(o.r).padStart(8) + '  ' + (pp(o.ex4) + '(' + f2(o.t) + ')').padStart(14));
      }
    }
    log('');
  }

  /* ---------- 表 6：分段 ---------- */
  const SEG = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    for (const [t0, t1, nm] of [['0000', '2020', '20前'], ['2020', '9999', '20后']]) {
      const s = rows.filter(z => z.type === ty && z.date >= t0 && z.date < t1 && z.ex4[20] != null);
      const inT = s.filter(z => z.p20 >= TOP_Q), outT = s.filter(z => z.p20 < TOP_Q);
      const a = inT.map(z => z.ex4[20]), b2 = outT.map(z => z.ex4[20]);
      SEG[ty + nm] = {
        nIn: a.length, nOut: b2.length,
        exIn: mean(a), tIn: tStat(a), exOut: mean(b2), tOut: tStat(b2),
        d: mean(a) != null && mean(b2) != null ? mean(a) - mean(b2) : null
      };
    }
  }
  log('=== 表 6 分段（x=20）===');
  log('类型  段    主线n  非主线n  主线ex4(t)          非主线ex4(t)        差');
  for (const ty of ['L1', 'L2', 'L3']) {
    for (const nm of ['20前', '20后']) {
      const o = SEG[ty + nm];
      log(ty + '   ' + nm + String(o.nIn).padStart(7) + String(o.nOut).padStart(8) +
        '  ' + (pp(o.exIn) + '(' + f2(o.tIn) + ')').padStart(17) +
        '  ' + (pp(o.exOut) + '(' + f2(o.tOut) + ')').padStart(18) + '  ' + pp(o.d).padStart(8));
    }
  }
  log('');

  /* ---------- 表 4：行业本身是不是主线，决定了什么 ---------- */
  // 拆解：信号收益 = 行业 beta + 行业 alpha
  const DEC = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty);
    for (const x of [20]) {
      const inT = s.filter(z => z.p20 >= TOP_Q);
      const v = inT.map(z => z.r[x]).filter(v => v != null);
      const ia = inT.map(z => z.exInd[x]).filter(v => v != null);
      DEC[ty] = { n: v.length, tot: mean(v), ind: mean(v) - mean(ia), alpha: mean(ia) };
    }
  }

  /* ---------- 表 7：按标的聚合（防重叠信号把 t 撑大） ---------- */
  const PER = {};
  for (const ty of ['L1', 'L2', 'L3']) {
    const s = rows.filter(z => z.type === ty && z.ex4[20] != null);
    const byCode = {};
    for (const z of s) (byCode[z.code] = byCode[z.code] || []).push(z);
    const a = [], b2 = [], pair = [];
    for (const code of Object.keys(byCode)) {
      const inT = byCode[code].filter(z => z.p20 >= TOP_Q).map(z => z.ex4[20]);
      const outT = byCode[code].filter(z => z.p20 < TOP_Q).map(z => z.ex4[20]);
      if (inT.length < 3 || outT.length < 3) continue;      // 两边都要够才配对
      a.push(mean(inT)); b2.push(mean(outT)); pair.push(mean(inT) - mean(outT));
    }
    PER[ty] = { nPair: pair.length, mIn: mean(a), tIn: tStat(a), mOut: mean(b2), tOut: tStat(b2), d: mean(pair), t: tStat(pair) };
  }
  log('=== 表 7 按标的聚合（每只标的先算一个均值，两边都 ≥3 个信号才进，x=20）===');
  log('类型   配对数   主线均值   非主线均值   配对差    t');
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = PER[ty];
    log(ty + String(o.nPair).padStart(8) + '  ' + pp(o.mIn).padStart(10) + '  ' + pp(o.mOut).padStart(11) +
      '  ' + pp(o.d).padStart(8) + '  ' + f2(o.t).padStart(6));
  }
  log('');

  /* ---------- 表 8：行业动量本身有没有延续性 ---------- */
  // 不看个股，直接买「行业指数」：前 25% 的行业持有 20 天，比全行业平均多赚吗
  const MON = { all: [], n: 0 };
  const MKEY = [['p20', 20, '行业 20 日涨幅'], ['p60', 60, '行业 60 日涨幅'],
    ['p120', 120, '行业 120 日涨幅'], ['p250', 250, '行业 250 日涨幅']];
  for (const [key, len, lab] of MKEY) {
    const top = [], bot = [];
    for (let i = 250; i + 20 < R.all.length; i++) {
      const d = R.all[i], d2 = R.all[i + 20];
      const box = R.rank.get(d);
      if (!box) continue;
      const rs = [];
      for (const sw of sws) {
        const a = sw.idx.get(d), b2 = sw.idx.get(d2);
        if (a == null || b2 == null || a < 251) continue;
        const bx = box[sw.code];
        if (!bx || bx[key] == null) continue;
        rs.push({ q: bx[key], fwd: sw.c[b2] / sw.c[a] - 1 });
      }
      if (rs.length < 20) continue;
      const all = mean(rs.map(z => z.fwd));
      if (len === 20) MON.all.push(all);
      top.push(mean(rs.filter(z => z.q >= TOP_Q).map(z => z.fwd)) - all);
      bot.push(mean(rs.filter(z => z.q < 1 - TOP_Q).map(z => z.fwd)) - all);
      if (len === 20) MON.n++;
    }
    MON[key] = {
      n: top.length, lab,
      top: mean(top), tTop: tStat(top), winTop: top.filter(v => v > 0).length / top.length,
      bot: mean(bot), tBot: tStat(bot), winBot: bot.filter(v => v > 0).length / bot.length
    };
  }
  log('=== 表 8 行业动量延续性（买行业指数本身，持有 20 个交易日）===');
  log('样本 ' + MON.n + ' 个交易日；全行业平均 20 日收益 ' + pp(mean(MON.all)) + '（中位 ' + pp(med(MON.all)) + '）');
  log('定义              前25%相对全体(t)        胜率      后25%相对全体(t)        胜率');
  for (const [key] of MKEY) {
    const o = MON[key];
    log(o.lab.padEnd(16) + (pp(o.top) + '(' + f2(o.tTop) + ')').padStart(18) + '  ' + pct(o.winTop).padStart(7) +
      '  ' + (pp(o.bot) + '(' + f2(o.tBot) + ')').padStart(18) + '  ' + pct(o.winBot).padStart(7));
  }
  log('');

  /* ---------- 落盘 ---------- */
  fs.writeFileSync(OUT_TXT, LOG.join('\n') + '\n', 'utf8');
  const J = {
    nAll, nCover, nRows: rows.length,
    tab: TAB, cut: CUT, def: DEF, bef: BEF, cross: CROSS, seg: SEG, per: PER, mon: MON, dec: DEC,
    params: { TOP_Q, XS, B4_BAND, MIN_POOL, FEE }
  };
  fs.writeFileSync(path.join(__dirname, 'out', 'theme_stock.json'), JSON.stringify(J, null, 1));
  log('落盘 out/theme_stock.json、out/theme_stock.txt');
}

main();
