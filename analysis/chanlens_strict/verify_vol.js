#!/usr/bin/env node
/* ============================================================
 * verify_vol.js — 复算 report_vol.md 的显著性检验与分档表
 *   输入：out/bt_vol_stock.json、out/bt_vol.json（bt_vol.js 产出）
 *   输出：stdout（不写文件，避免与 bt_vol 输出冲突）
 *
 * 用法：node verify_vol.js
 *
 * 检验设计说明：
 *   置换检验的 null = 「随机抽取同样笔数的信号」，B=3000。
 *   统计量 = 保留组均值 − 其余组均值；p = (随机差值 ≥ 观测差值) 的比例。
 *   这个 null 能检出「从 N 笔里挑出 k 笔，本身就能抬高均值」这个问题。
 *
 *   反向规则的 p 值接近 1 不代表无效：反向假设是「该组显著低于其余」，
 *   此时 p 越接近 1 越支持该假设（随机置换几乎从不产生这么大的负差）。
 * ============================================================ */
'use strict';

const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'out');
const B = 3000;

const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const sd = a => {
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1));
};
const tstat = a => (a.length > 2 ? mean(a) / (sd(a) / Math.sqrt(a.length)) : null);
const fmtP = x => (x > 0 ? '+' : '\u2212') + (100 * Math.abs(x)).toFixed(2) + 'pp';
const fmt2 = x => (x == null ? '\u2014' : x.toFixed(2));

/* Fisher-Yates 部分洗牌后取前 k 个作为「保留组」。
   用固定种子的 LCG 而非 Math.random，保证多次运行结果完全一致。 */
let seed = 20261122;
const rnd = () => {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x80000000;
};

function permTest(vals, mask, obs) {
  const n = vals.length;
  const k = mask.filter(Boolean).length;
  if (k < 30 || n - k < 30) return null;
  const idx = [...Array(n).keys()];
  let hit = 0;
  for (let b = 0; b < B; b++) {
    for (let i = 0; i < k; i++) {
      const j = i + Math.floor(rnd() * (n - i));
      const tmp = idx[i]; idx[i] = idx[j]; idx[j] = tmp;
    }
    let s = 0, sr = 0;
    for (let i = 0; i < k; i++) s += vals[idx[i]];
    for (let i = k; i < n; i++) sr += vals[idx[i]];
    if (s / k - sr / (n - k) >= obs) hit++;
  }
  return hit / B;
}

const RULES = [
  ['规则A 非缩量≥0.8 且 量能<1.0', z => z.vr20 >= 0.8 && z.vlevel < 1.0],
  ['规则B 仅 非缩量≥0.8', z => z.vr20 >= 0.8],
  ['规则C 当日放量≥1.5', z => z.vr20 >= 1.5],
  ['规则D 极端缩量<0.65 (反向)', z => z.vr20 < 0.65]
];

let fail = 0;

for (const file of ['bt_vol_stock.json', 'bt_vol.json']) {
  const fp = path.join(OUT, file);
  if (!fs.existsSync(fp)) {
    console.error('缺少 ' + fp + '，请先运行 bt_vol.js');
    process.exitCode = 1;
    continue;
  }
  const d = JSON.parse(fs.readFileSync(fp, 'utf8'));
  const L1 = d.rows.filter(z => z.ty === 'L1' && z.ex4 != null && z.vr20 != null);
  seed = 20261122;   // 每个池子重置，保证结果与遍历顺序无关

  console.log('=== ' + d.pool + ' 一买 n=' + L1.length + '（B=' + B + '）===');
  console.log('规则                            保留n 留存  保留超额(t)        砍掉超额        差值      p');

  for (const [lab, fn] of RULES) {
    const keep = L1.filter(z => fn(z));
    const drop = L1.filter(z => !fn(z));
    if (keep.length < 30 || drop.length < 30) {
      console.log(lab.padEnd(30) + ' 样本不足');
      continue;
    }
    const kv = keep.map(z => z.ex4), dv = drop.map(z => z.ex4);
    const obs = mean(kv) - mean(dv);
    const p = permTest(L1.map(z => z.ex4), L1.map(z => fn(z)), obs);
    console.log(
      lab.padEnd(30) +
      String(keep.length).padStart(5) + ' ' +
      (100 * keep.length / L1.length).toFixed(0).padStart(4) + '% ' +
      (fmtP(mean(kv)) + '(' + fmt2(tstat(kv)) + ')').padStart(18) + ' ' +
      fmtP(mean(dv)).padStart(15) + ' ' +
      fmtP(obs).padStart(9) + ' ' +
      (p == null ? '\u2014' : p.toFixed(3))
    );
  }

  /* 量比五分位（检查是否单调） */
  console.log('');
  console.log('vr20 五分位（看梯度是否单调）：');
  const vs = L1.map(z => z.vr20).slice().sort((a, b) => a - b);
  const cuts = [0, 0.2, 0.4, 0.6, 0.8].map(x => vs[Math.floor((vs.length - 1) * x)]);
  const qs = cuts.concat([vs[vs.length - 1] + 1e-9]);
  let prev = null, monoUp = 0, monoDn = 0;
  for (let i = 0; i < 5; i++) {
    const s = L1.filter(z => z.vr20 >= qs[i] && z.vr20 < qs[i + 1]);
    if (s.length < 30) { console.log('  Q' + (i + 1) + ' 样本不足'); continue; }
    const m = mean(s.map(z => z.ex4));
    if (prev != null) { if (m > prev) monoUp++; else monoDn++; }
    prev = m;
    console.log(
      '  Q' + (i + 1) + ' 量比 [' + (i === 0 ? '0' : qs[i].toFixed(2)) + ',' +
      (i === 4 ? '∞' : qs[i + 1].toFixed(2)) + ')  n=' + String(s.length).padStart(4) +
      '  ' + fmtP(m) + '  t=' + fmt2(tstat(s.map(z => z.ex4)))
    );
  }
  const mono = monoUp === 4 ? '严格单调递增' : monoDn === 4 ? '严格单调递减' : '不单调（有转折 ' + monoDn + ' 次）';
  console.log('  形态：' + mono + ' → ' + (monoUp === 4 ? '可做梯度加权' : '只能排极值，不能做梯度'));
  console.log('');
}

/* 自检：确认 ETF 的规则D 反向 p 值确实高（不是代码把方向搞反了） */
const etf = JSON.parse(fs.readFileSync(path.join(OUT, 'bt_vol.json'), 'utf8'));
const e1 = etf.rows.filter(z => z.ty === 'L1' && z.ex4 != null && z.vr20 != null);
const sq = e1.filter(z => z.vr20 < 0.65);
if (sq.length >= 30) {
  const obs = mean(sq.map(z => z.ex4)) - mean(e1.filter(z => z.vr20 >= 0.65).map(z => z.ex4));
  if (obs > 0) {
    console.error('自检失败：极端缩量组超额应低于其余组，实际差值为正 ' + fmtP(obs));
    fail++;
  }
}
if (fail) process.exitCode = 1;
