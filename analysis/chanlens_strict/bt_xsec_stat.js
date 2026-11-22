#!/usr/bin/env node
/* ============================================================
 * bt_xsec_stat.js — 全市场横截面量价因子检验（论文口径）
 *
 * 输入：out/xsec_panel.jsonl（bt_xsec_build.js 产出）
 * 方法：
 *   每月末对全市场做横截面排序，按因子值分 5 组等权
 *   统计各组下 20 交易日收益（已扣 0.1% 双边费）
 *   多空 = Q5 − Q1（Q5 = 因子值最高组）
 *   报告：月均、年化、t、Sharpe、胜率、单调性
 *
 * 两套样本域：
 *   ALL  全部 A 股等权
 *   INV  可投资域：剔除 px<2、剔除 BSE/B、剔除当月成交额最小 30%（防微盘偏差）
 *
 * 用法：node bt_xsec_stat.js
 * ============================================================ */
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const OUTD = path.join(__dirname, 'out');
const PANEL = path.join(OUTD, 'xsec_panel.jsonl');

const FEE = 0.001;      // 双边 0.1%
const NG = 5;           // 分组数
const MIN_N = 150;      // 每月最少样本

/* 因子定义：名称、中文、预期方向（+1 表示值越高越好，-1 表示越低越好，0 待测） */
const FACTORS = [
  { i: 0, key: 'rev20', lab: '过去1月涨幅（反转）', dir: -1 },
  { i: 1, key: 'mom12_1', lab: '12-1月动量', dir: +1 },
  { i: 2, key: 'pvt_ma', lab: '价量趋势 A：均线偏离差', dir: +1 },
  { i: 3, key: 'pvt_vwap', lab: '价量趋势 B：VWAP 比（论文式）', dir: +1 },
  { i: 4, key: 'turn20', lab: '20日均换手率', dir: -1 },
  { i: 5, key: 'pmo', lab: '异常换手（20日/250日）', dir: -1 },
  { i: 6, key: 'vol20', lab: '20日波动率', dir: -1 },
  { i: 7, key: 'lnamt20', lab: '成交额（规模代理）', dir: -1 },
  { i: 8, key: 'vr20', lab: '当日量/20日均量（量比）', dir: 0 },
  { i: 9, key: 'illiq20', lab: 'Amihud非流动性', dir: +1 }
];

const boardName = ['MAIN', 'GEM', 'STAR', 'BSE', 'B'];
const mLabel = m => (2012 + Math.floor(m / 12)) + '-' + String(m % 12 + 1).padStart(2, '0');

const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const sd = a => {
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1));
};
const P = x => (x > 0 ? '+' : '\u2212') + (100 * Math.abs(x)).toFixed(2) + 'pp';
const F = (x, n = 2) => (x == null || !Number.isFinite(x)) ? '\u2014' : x.toFixed(n);

/* 分位数（线性插值） */
function quantile(sorted, q) {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

async function load() {
  const n = parseInt((await new Promise(res => {
    let c = 0;
    readline.createInterface({ input: fs.createReadStream(PANEL) })
      .on('line', () => c++).on('close', () => res(c));
  })), 10);
  console.log('面板 ' + n + ' 条，分配内存...');

  const mi = new Uint16Array(n);
  const bd = new Uint8Array(n);
  const px = new Float32Array(n);
  const r20 = new Float32Array(n);
  const Fs = FACTORS.map(() => new Float32Array(n));

  let k = 0;
  await new Promise(res => {
    readline.createInterface({ input: fs.createReadStream(PANEL) })
      .on('line', ln => {
        if (!ln) return;
        const o = JSON.parse(ln);
        const y = +o.m.slice(0, 4), mo = +o.m.slice(5, 7);
        mi[k] = (y - 2012) * 12 + (mo - 1);
        bd[k] = boardName.indexOf(o.bd);
        px[k] = o.px;
        r20[k] = o.r20 * 100;                 // 转成百分点数值，便于打印
        for (let j = 0; j < FACTORS.length; j++) Fs[j][k] = o.f[FACTORS[j].i];
        k++;
      })
      .on('close', res);
  });
  console.log('已加载 ' + k + ' 条');
  return { n: k, mi, bd, px, r20, Fs };
}

/* 按月份分组（计数排序，保持索引） */
function groupByMonth(mi, n) {
  let maxM = 0;
  for (let i = 0; i < n; i++) if (mi[i] > maxM) maxM = mi[i];
  const cnt = new Int32Array(maxM + 2);
  for (let i = 0; i < n; i++) cnt[mi[i] + 1]++;
  for (let m = 1; m <= maxM + 1; m++) cnt[m] += cnt[m - 1];
  const out = new Int32Array(n);
  const pos = cnt.slice();
  for (let i = 0; i < n; i++) out[pos[mi[i]]++] = i;
  const groups = [];
  for (let m = 0; m <= maxM; m++) {
    const s = cnt[m], e = cnt[m + 1];
    if (e > s) groups.push({ m, idx: out.subarray(s, e) });
  }
  return groups;
}

async function main() {
  if (!fs.existsSync(PANEL)) { console.error('缺少 ' + PANEL + '，先跑 bt_xsec_build.js'); process.exit(1); }
  const D = await load();
  const groups = groupByMonth(D.mi, D.n);
  console.log('月份 ' + groups.length + ' 个：' + groups[0].m + ' ~ ' + groups[groups.length - 1].m);
  console.log('');

  /* 每个因子每月每组的收益序列 */
  const res = {};
  for (const f of FACTORS) {
    res[f.key] = {
      Q: Array.from({ length: NG }, () => []),      // 等权（可投资域）
      QW: Array.from({ length: NG }, () => []),     // 成交额加权
      ls: [], lsW: [], lsL: [], mon: [],
      spreadHit: 0, nMon: 0, avgN: 0
    };
  }
  /* 全局复权收益缓存（供各域复用 winsorize 后的值） */
  const rwAll = new Float64Array(D.n);
  /* 全市场基准（两套域） */
  const base = { ALL: [], INV: [] };
  const contrib = {};

  for (const g of groups) {
    const idx = g.idx;
    if (idx.length < MIN_N) continue;

    /* --- 可投资域过滤 --- */
    const amtIdx = FACTORS.findIndex(f => f.key === 'lnamt20');
    const lens = [];
    for (let t = 0; t < idx.length; t++) lens.push(D.Fs[amtIdx][idx[t]]);
    lens.sort((a, b) => a - b);
    const amtCut = quantile(lens, 0.30);

    const inv = [], all = [];
    for (let t = 0; t < idx.length; t++) {
      const i = idx[t];
      if (D.r20[i] == null || !Number.isFinite(D.r20[i])) continue;
      all.push(i);
      const isBad = D.px[i] < 2 || D.bd[i] === 3 || D.bd[i] === 4 || D.Fs[amtIdx][i] < amtCut;
      if (!isBad) inv.push(i);
    }
    if (inv.length < MIN_N) continue;

    /* 基准：等权全市场（扣费） */
    base.ALL.push(mean(all.map(i => D.r20[i])) - FEE * 100);
    base.INV.push(mean(inv.map(i => D.r20[i])) - FEE * 100);

    /* --- 每个月内对 r20 做 0.5%/99.5% winsorize，避免极端值拉组均值 --- */
    const rs = inv.map(i => D.r20[i]).slice().sort((a, b) => a - b);
    const lo = quantile(rs, 0.005), hi = quantile(rs, 0.995);
    for (const i of inv) rwAll[i] = Math.min(hi, Math.max(lo, D.r20[i]));

    /* 大票域：可投资域中成交额最大的 30%（用户实盘场景） */
    const invByAmt = inv.slice().sort((a, b) => D.Fs[amtIdx][b] - D.Fs[amtIdx][a]);
    const lcap = invByAmt.slice(0, Math.floor(inv.length * 0.30));

    /* 单域内按因子五分组，返回各组收益 */
    const cross = (domain, f) => {
      const vals = domain.map(i => ({
        v: D.Fs[f.i][i], r: rwAll[i], w: Math.exp(D.Fs[amtIdx][i])
      }));
      const vs = vals.map(o => o.v).slice().sort((a, b) => a - b);
      const cuts = [];
      for (let q = 1; q < NG; q++) cuts.push(quantile(vs, q / NG));
      const buckets = Array.from({ length: NG }, () => []);
      for (const o of vals) {
        let b = 0;
        while (b < NG - 1 && o.v > cuts[b]) b++;
        buckets[b].push(o);
      }
      const g = buckets.map(b => (b.length ? mean(b.map(o => o.r)) - FEE * 100 : null));
      const gw = buckets.map(b => {
        if (!b.length) return null;
        let sw = 0, swr = 0;
        for (const o of b) { sw += o.w; swr += o.w * o.r; }
        return sw > 0 ? swr / sw - FEE * 100 : null;
      });
      if (g.some(x => x == null)) return null;
      return { g, gw };
    };

    for (const f of FACTORS) {
      const R = res[f.key];
      const a = cross(inv, f);
      if (!a) continue;
      for (let q = 0; q < NG; q++) { R.Q[q].push(a.g[q]); R.QW[q].push(a.gw[q]); }
      const ls = a.g[NG - 1] - a.g[0];
      R.ls.push(ls);
      R.lsW.push(a.gw[NG - 1] - a.gw[0]);
      R.mon.push(mLabel(g.m));
      if (ls > 0) R.spreadHit++;
      R.nMon++;
      R.avgN += inv.length;

      /* 大票域单独算（比等权域更接近个人实盘） */
      const L = cross(lcap, f);
      if (L) R.lsL.push(L.g[NG - 1] - L.g[0]);
    }
  }

  /* ---------------- 输出 ---------------- */
  const lines = [];
  const log = s => { console.log(s); lines.push(s); };

  const bALL = mean(base.ALL), bINV = mean(base.INV);
  const nMon = res[FACTORS[0].key].nMon;
  const mons = res[FACTORS[0].key].mon;
  log('样本：' + nMon + ' 个有效月（' + mons[0] + ' ~ ' + mons[mons.length - 1] + '），每月可投资域约 ' +
    Math.round(res[FACTORS[0].key].avgN / nMon) + ' 只');
  log('全市场等权月均（扣费）：ALL ' + P(bALL / 100) + '｜INV ' + P(bINV / 100));
  log('');
  log('=== 表 1：各因子五分组月均收益（可投资域，等权，扣 0.1% 双边）===');
  log('因子                              Q1        Q2        Q3        Q4        Q5      Q5−Q1   年化    t      Sharpe  胜率');

  const rows = [];
  for (const f of FACTORS) {
    const R = res[f.key];
    const gm = R.Q.map(a => mean(a));
    const ls = R.ls;
    const mls = mean(ls), sdl = sd(ls);
    const t = mls / (sdl / Math.sqrt(ls.length));
    const ann = mls * 12, sh = mls / sdl * Math.sqrt(12);
    const hit = R.spreadHit / ls.length;
    const mlsW = mean(R.lsW);
    const tW = mlsW / (sd(R.lsW) / Math.sqrt(R.lsW.length));
    const mL = mean(R.lsL);
    const tL = mL / (sd(R.lsL) / Math.sqrt(R.lsL.length));
    rows.push({ f, gm, mls, t, ann, sh, hit, n: ls.length, mlsW, tW, mL, tL, ls });
    log(f.lab.padEnd(32) +
      gm.map(x => P(x / 100).padStart(9)).join('') +
      P(mls / 100).padStart(9) +
      P(ann / 100).padStart(8) +
      F(t).padStart(7) +
      F(sh).padStart(8) +
      (100 * hit).toFixed(0).padStart(6) + '%');
  }
  log('（Q5−Q1 单位是「每月百分点」；年化 = 月均 × 12，未复利）');

  /* 等权 vs 加权 */
  log('');
  log('=== 表 1b：稳健性——等权 vs 成交额加权（检验是否由微盘股驱动）===');
  log('因子                              等权多空   t     加权多空   t      判断');
  for (const r of rows) {
    let v;
    if (Math.abs(r.t) < 2 && Math.abs(r.tW) < 2) v = '两口径都无效';
    else if (Math.abs(r.t) >= 2 && Math.abs(r.tW) < 2) v = '仅等权有效 → 微盘驱动';
    else if (Math.abs(r.t) < 2 && Math.abs(r.tW) >= 2) v = '仅加权有效';
    else v = Math.sign(r.mls) === Math.sign(r.mlsW) ? '两口径同向' : '方向相反';
    log('  ' + r.f.lab.padEnd(30) + P(r.mls / 100).padStart(9) + F(r.t).padStart(7) +
      P(r.mlsW / 100).padStart(10) + F(r.tW).padStart(7) + '  ' + v);
  }

  /* 大票子样本 */
  log('');
  log('=== 表 1c：大票子样本（可投资域中成交额前 30%，接近个人实盘）===');
  log('因子                              可投资域   t     大票域    t      判断');
  for (const r of rows) {
    let v;
    if (Math.abs(r.t) < 2 && Math.abs(r.tL) < 2) v = '两域都无效';
    else if (Math.abs(r.t) >= 2 && Math.abs(r.tL) < 2) v = '仅全池有效 → 小微盘驱动';
    else if (Math.abs(r.t) < 2 && Math.abs(r.tL) >= 2) v = '仅大票有效';
    else v = Math.sign(r.mls) === Math.sign(r.mL) ? '两域同向' : '方向相反';
    log('  ' + r.f.lab.padEnd(30) + P(r.mls / 100).padStart(9) + F(r.t).padStart(7) +
      P(r.mL / 100).padStart(9) + F(r.tL).padStart(7) + '  ' + v);
  }

  /* 单调性 */
  log('');
  log('=== 表 2：单调性与方向判定（等权口径）===');
  for (const r of rows) {
    const gm = r.gm;
    let up = 0, dn = 0;
    for (let q = 1; q < NG; q++) { if (gm[q] > gm[q - 1]) up++; else dn++; }
    const mono = up === NG - 1 ? '严格递增' : dn === NG - 1 ? '严格递减' : '不单调';
    const exp = r.f.dir;
    let verdict;
    if (Math.abs(r.t) < 2) verdict = '无效';
    else if (exp === 0) verdict = '有效（方向待定）';
    else if ((exp > 0 && r.mls > 0) || (exp < 0 && r.mls < 0)) verdict = '有效，符合预期';
    else verdict = '有效，但方向与预期相反';
    log('  ' + r.f.lab.padEnd(30) + mono.padEnd(10) + ' Q5−Q1=' + P(r.mls / 100).padStart(8) +
      '  t=' + F(r.t).padStart(6) + '  → ' + verdict);
  }

  /* 显著性排序 */
  log('');
  log('=== 表 3：按 |t| 排序（Harvey-Liu-Zhu 多重检验门槛 t>3）===');
  const sorted = rows.slice().sort((a, b) => Math.abs(b.t) - Math.abs(a.t));
  sorted.forEach((r, i) => {
    const mark = Math.abs(r.t) >= 3 ? '\u2605' : Math.abs(r.t) >= 2 ? '\u25cb' : '\u00d7';
    log('  ' + mark + ' ' + (i + 1) + '. ' + r.f.lab.padEnd(30) + 't=' + F(r.t).padStart(6) +
      '  月均多空 ' + P(r.mls / 100).padStart(9) + '  年化 ' + P(r.ann / 100).padStart(8));
  });
  log('  \u2605 |t|≥3  \u25cb 2≤|t|<3  \u00d7 |t|<2');

  /* 分年度：看因子是否随时间衰减 */
  log('');
  log('=== 表 4：分年度多空收益（百分点/年，检验是否被量化抹平）===');
  const years = [...new Set(mons.map(m => m.slice(0, 4)))].sort();
  log('因子                            ' + years.map(y => y.slice(2)).map(y => y.padStart(7)).join(''));
  for (const r of rows) {
    const cells = years.map(y => {
      const v = r.ls.filter((_, k) => mons[k].slice(0, 4) === y);
      return v.length ? P(mean(v) / 100).padStart(7) : '      —';
    });
    log('  ' + r.f.lab.padEnd(28) + cells.join(''));
  }
  log('（每个数字是该年各月多空收益的均值；空 = 该年无数据）');
  /* 因子相关性 */
  log('');
  log('=== 表 5：因子相关性（|r|>0.40 的配对，全样本抽样，Pearson，两端 1% 截尾）===');
  const samp = [];
  for (let i = 0; i < D.n; i += 7) samp.push(i);
  const cols = FACTORS.map(f => {
    const arr = samp.map(i => D.Fs[f.i][i]);
    const s = arr.slice().sort((a, b) => a - b);
    const lo = quantile(s, 0.01), hi = quantile(s, 0.99);
    return arr.map(x => Math.min(hi, Math.max(lo, x)));
  });
  const corrOf = (a, b) => {
    const ma = mean(a), mb = mean(b);
    let sa = 0, sb = 0, sab = 0;
    for (let k = 0; k < a.length; k++) {
      const x = a[k] - ma, y = b[k] - mb;
      sa += x * x; sb += y * y; sab += x * y;
    }
    return sab / Math.sqrt(sa * sb);
  };
  const pairs = [];
  for (let a = 0; a < FACTORS.length; a++) {
    for (let b = a + 1; b < FACTORS.length; b++) {
      const c = corrOf(cols[a], cols[b]);
      if (Math.abs(c) > 0.40) pairs.push({ a, b, c });
    }
  }
  pairs.sort((x, y) => Math.abs(y.c) - Math.abs(x.c));
  if (!pairs.length) log('  无（所有因子两两 |r| ≤ 0.40，相互独立）');
  for (const p of pairs) {
    const tag = Math.abs(p.c) > 0.8 ? '  ← 基本同一个因子' : Math.abs(p.c) > 0.6 ? '  ← 高度重复' : '';
    log('  ' + FACTORS[p.a].lab.padEnd(30) + FACTORS[p.b].lab.padEnd(30) + 'r=' + F(p.c) + tag);
  }

  log('');
  log('=== 读法 ===');
  log('\u00b7 Q1~Q5 是因子值从低到高的五组，每组月均绝对收益（含市场 beta）。');
  log('\u00b7 Q5−Q1 是多空组合，剥离市场，才是因子的净贡献。');
  log('\u00b7 t 用月序列算（n=' + res[FACTORS[0].key].ls.length + '），未做年化修正。');

  fs.writeFileSync(path.join(OUTD, 'bt_xsec.txt'), lines.join('\n') + '\n', 'utf8');

  /* 落盘明细，供复算 */
  const dump = {
    months: res[FACTORS[0].key].nMon,
    base: { ALL: bALL, INV: bINV },
    factors: rows.map(r => ({
      key: r.f.key, lab: r.f.lab, dir: r.f.dir,
      Q: r.gm, ls: r.mls, t: r.t, ann: r.ann, sharpe: r.sh, hit: r.hit,
      series: res[r.f.key].ls
    }))
  };
  fs.writeFileSync(path.join(OUTD, 'bt_xsec.json'), JSON.stringify(dump), 'utf8');
  console.log('\n输出：out/bt_xsec.txt、out/bt_xsec.json');
}

main();
