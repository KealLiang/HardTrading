#!/usr/bin/env node
/* ============================================================
 * bt_xsec_build.js — 构建全市场横截面量价因子面板
 *
 * 数据：data/astocks/*.csv（6166 只，2012-01 ~ 2026-11）
 *   列：0 日期 1 代码 2 开 3 收 4 高 5 低 6 量(手) 7 额(元)
 *       8 振幅% 9 涨跌幅% 10 ? 11 换手率%
 *   注：价格不复权，因此收益一律用第 9 列涨跌幅累乘（等价前复权）
 *
 * 时点：每只票每月最后一个交易日（该股自己最后一个有交易的日子）
 * 因子：全部用 t 日及之前数据，无未来函数
 * 标签：ret20 = 之后 20 个交易日复权收益（用于横截面排序检验）
 *
 * 输出：out/xsec_panel.jsonl
 *   每行 {m, code, bd, px, n, f:[rev,mom,pvt,turn,vol,amt,vr,illiq], r20}
 *   m  信号月 'YYYY-MM'
 *   bd 板块 MAIN/GEM/STAR/BSE/B
 *   px 信号日收盘价
 *   n  上市以来交易日数（用于剔新股）
 *   f  因子数组，顺序见 FACTOR_NAMES
 *   r20 未来 20 交易日收益
 *
 * 用法：node bt_xsec_build.js [--limit N]
 * ============================================================ */
'use strict';

const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '../../data/astocks');
const OUTD = path.join(__dirname, 'out');
const OUT = path.join(OUTD, 'xsec_panel.jsonl');

const FACTOR_NAMES = ['rev20', 'mom12_1', 'pvt_ma', 'pvt_vwap', 'turn20', 'pmo', 'vol20', 'lnamt20', 'vr20', 'illiq20'];

const argv = process.argv.slice(2);
const li = argv.indexOf('--limit');
const LIMIT = li >= 0 ? parseInt(argv[li + 1], 10) : Infinity;

const MIN_HIST = 250;     // 上市交易日数门槛
const HOLD = 20;          // 持有交易日

/* ---------- 工具 ---------- */
function boardOf(code) {
  if (/^(900|200)/.test(code)) return 'B';
  if (/^(688|689)/.test(code)) return 'STAR';
  if (/^(300|301)/.test(code)) return 'GEM';
  if (/^(4|8|920)/.test(code)) return 'BSE';
  return 'MAIN';
}

/* 解析一个 CSV → { code, d[], c[], v[], a[], t[], r[] } */
function parseCsv(fp) {
  const txt = fs.readFileSync(fp, 'utf8');
  const lines = txt.split('\n');
  const d = [], c = [], v = [], a = [], t = [], rr = [];
  for (let k = 0; k < lines.length; k++) {
    const ln = lines[k];
    if (!ln || ln.length < 20) continue;
    const p = ln.split(',');
    if (p.length < 12) continue;
    const dt = p[0];
    if (dt.length !== 10 || dt[4] !== '-') continue;
    const close = +p[3];
    if (!(close > 0)) continue;
    d.push(dt);
    c.push(close);
    v.push(+p[6] || 0);
    a.push(+p[7] || 0);
    t.push(+p[11] || 0);
    rr.push((+p[9] || 0) / 100);      // 涨跌幅
  }
  return { d, c, v, a, t, r: rr };
}

/* 均值的倒数优化：预计算前缀和 */
function prefixSum(arr) {
  const s = new Float64Array(arr.length + 1);
  for (let i = 0; i < arr.length; i++) s[i + 1] = s[i] + arr[i];
  return s;
}

function main() {
  if (!fs.existsSync(OUTD)) fs.mkdirSync(OUTD, { recursive: true });
  const files = fs.readdirSync(DIR).filter(f => f.endsWith('.csv'));
  console.log('股票文件 ' + files.length + ' 只，输出 ' + OUT);

  const fd = fs.openSync(OUT, 'w');
  let buf = [];
  let nRec = 0, nStock = 0, nSkipShort = 0;
  const t0 = Date.now();

  for (let fi = 0; fi < Math.min(files.length, LIMIT); fi++) {
    const f = files[fi];
    const code = (f.match(/^(\d{6})/) || [])[1];
    if (!code) continue;
    const p = parseCsv(path.join(DIR, f));
    const N = p.c.length;
    if (N < MIN_HIST + HOLD + 5) { nSkipShort++; continue; }

    /* 复权价格序列：P[0]=1，累乘涨跌幅 */
    const P = new Float64Array(N);
    P[0] = 1;
    for (let i = 1; i < N; i++) P[i] = P[i - 1] * (1 + p.r[i]);
    /* 日收益（用于波动率/非流动性） */
    const R = p.r;

    const sumV = prefixSum(p.v);
    const sumA = prefixSum(p.a);
    const sumT = prefixSum(p.t);
    const sumAbsR = prefixSum(R.map(x => Math.abs(x)));
    const sumP = prefixSum(Array.from(P));
    /* 成交量加权用的股数前缀和（量是手，×100 转股） */
    const sumVV = prefixSum(p.v.map(x => x * 100));

    const bd = boardOf(code);

    for (let i = MIN_HIST; i + HOLD < N; i++) {
      /* 月末判断：下一条记录月份不同（或已到末尾） */
      const nx = i + 1 < N ? p.d[i + 1] : '';
      if (nx && nx.slice(0, 7) === p.d[i].slice(0, 7)) continue;
      /* 当日必须成交 */
      if (!(p.v[i] > 0) || !(p.a[i] > 0)) continue;

      const m = p.d[i].slice(0, 7);
      const px = p.c[i];

      /* --- 因子 --- */
      const rev20 = P[i] / P[i - 20] - 1;                       // 过去 20 日涨幅
      const mom = P[i - 20] / P[i - 240] - 1;                   // 12-1 动量
      /* 价量趋势：短期(3,5)均线偏离 − 长期(60,200)均线偏离 */
      const ma = k => (sumP[i + 1] - sumP[i + 1 - k]) / k;
      const d3 = P[i] / ma(3) - 1;
      const d5 = P[i] / ma(5) - 1;
      const d20 = P[i] / ma(20) - 1;
      const d60 = P[i] / ma(60) - 1;
      const d200 = P[i] / ma(200) - 1;
      const pvt = (d3 + d5 + d20) / 3 - (d60 + d200) / 2;
      /* 价量趋势（VWAP 口径，更贴近 Liu-Zhou-Zhu 2024）：
         短期成交量加权均价 / 长期成交量加权均价 − 1 */
      const vwap = k => {
        const av = sumA[i + 1] - sumA[i + 1 - k];
        const vv = sumVV[i + 1] - sumVV[i + 1 - k];
        return vv > 0 ? av / vv : NaN;
      };
      const vw3 = vwap(3), vw5 = vwap(5), vw20 = vwap(20), vw60 = vwap(60), vw200 = vwap(200);
      const pvtV = ((vw3 + vw5 + vw20) / 3) / ((vw60 + vw200) / 2) - 1;
      const turn20 = (sumT[i + 1] - sumT[i + 1 - 20]) / 20;     // 20 日均换手
      const turn250 = (sumT[i + 1] - sumT[i + 1 - 250]) / 250;  // 250 日均换手
      const pmo = turn250 > 0 ? turn20 / turn250 - 1 : NaN;     // 异常换手（LSY 2019 PMO）
      /* 20 日收益波动率 */
      let ss = 0, mu = 0;
      for (let k = i - 19; k <= i; k++) mu += R[k];
      mu /= 20;
      for (let k = i - 19; k <= i; k++) ss += (R[k] - mu) ** 2;
      const vol20 = Math.sqrt(ss / 19);
      const amt20 = (sumA[i + 1] - sumA[i + 1 - 20]) / 20;
      const vr20 = p.v[i] / (((sumV[i + 1] - sumV[i + 1 - 20]) / 20) || 1);
      /* Amihud 非流动性：|R| / 成交额，×1e10 放大 */
      const illiq20 = ((sumAbsR[i + 1] - sumAbsR[i + 1 - 20]) / 20) / (amt20 || 1) * 1e10;

      const r20 = P[i + HOLD] / P[i] - 1;

      const rec = {
        m, code, bd, px, n: i + 1,
        f: [
          +rev20.toFixed(6), +mom.toFixed(6), +pvt.toFixed(6), +pvtV.toFixed(6),
          +turn20.toFixed(4), +pmo.toFixed(6), +vol20.toFixed(6),
          +Math.log(amt20 || 1).toFixed(4),
          +vr20.toFixed(4), +illiq20.toFixed(6)
        ],
        r20: +r20.toFixed(6)
      };
      /* 过滤明显异常值，避免污染分组 */
      if (!Number.isFinite(r20) || Math.abs(r20) > 3) continue;
      if (!rec.f.every(Number.isFinite)) continue;

      buf.push(JSON.stringify(rec));
      nRec++;
      if (buf.length >= 20000) { fs.writeSync(fd, buf.join('\n') + '\n'); buf = []; }
    }
    nStock++;
    if (nStock % 1000 === 0) {
      console.log('  已处理 ' + nStock + ' 只，记录 ' + nRec + '，用时 ' + ((Date.now() - t0) / 1000).toFixed(0) + 's');
    }
  }
  if (buf.length) fs.writeSync(fd, buf.join('\n') + '\n');
  fs.closeSync(fd);

  const mb = (fs.statSync(OUT).size / 1048576).toFixed(1);
  console.log('');
  console.log('完成：' + nStock + ' 只有效，' + nSkipShort + ' 只历史不足剔除');
  console.log('记录 ' + nRec + ' 条，文件 ' + mb + ' MB，用时 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's');
}

main();
