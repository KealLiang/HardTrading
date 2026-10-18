/* ==========================================================================
 * rate_buy.js —— 买点上涨成功率补测（对应卖点回测的下跌成功率）
 *
 * 信号上涨率：直接读既有回测 JSON 里存的逐信号收益（net of fee 0.1%）
 *   daily → tmp/bt_v2.json；30/60 → tmp/bt_30m.json（须与 TF 一致）
 * 基准上涨率：同框架随机入场原始抽样（同样扣 0.1% 费，口径对齐）
 * 显著性：两比例差异 z 检验
 *
 * 用法：TF=daily|30|60 node rate_buy.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');

const TF = process.env.TF || 'daily';
if (TF !== 'daily' && TF !== '30' && TF !== '60') { console.error('TF 只支持 daily|30|60'); process.exit(1); }

const DIR = TF === 'daily' ? 'D:/Trading/data/etfs' : 'D:/Trading/data/etfs_bt_30m';
const WARMUP = TF === 'daily' ? 500 : (TF === '30' ? 500 : 250);
const BPD = TF === 'daily' ? 1 : (TF === '30' ? 8 : 4);
const HOLDS = TF === 'daily' ? [10, 20] : [1, 2, 5];
const FEE = 0.001;
const SAMPLES = 3000;                       // 基准原始抽样/票/持有期

function load30(file) {
  const txt = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const lines = txt.split(/\r?\n/).filter(x => x.trim());
  const head = lines[0].split(',').map(s => s.trim());
  const ix = n => head.indexOf(n);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].split(',');
    const t = String(c[ix('时间')] || '').trim();
    if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(t)) continue;
    const o = +c[ix('开盘')], cl = +c[ix('收盘')], h = +c[ix('最高')], l = +c[ix('最低')];
    const bad = !(o > 0 && isFinite(o)) || !(cl > 0 && isFinite(cl)) || !(h > 0 && isFinite(h)) || !(l > 0 && isFinite(l)) || h < l;
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

/* 信号上涨率（来自既有 JSON，与主回测完全同一批信号） */
const jPath = TF === 'daily' ? 'tmp/bt_v2.json' : 'tmp/bt_30m.json';
const j = JSON.parse(fs.readFileSync(path.join(__dirname, jPath), 'utf8'));
if (TF !== 'daily' && j.meta.tf !== parseInt(TF, 10)) { console.error('JSON 与 TF 不一致，先重跑 bt_30m.js'); process.exit(1); }

const upRate = a => { let u = 0; for (const x of a) if (x > 0) u++; return a.length ? u / a.length : null; };
const propZ = (a, b) => {
  const pa = upRate(a), pb = upRate(b), na = a.length, nb = b.length;
  if (!na || !nb) return null;
  const p = (pa * na + pb * nb) / (na + nb);
  const se = Math.sqrt(p * (1 - p) * (1 / na + 1 / nb));
  return se > 0 ? (pa - pb) / se : null;
};

/* 基准原始抽样池（随机入场，扣费口径与信号一致） */
const rawBase = {}; HOLDS.forEach(h => rawBase[h] = []);
const codes = fs.readdirSync(DIR).filter(f => f.endsWith('.csv')).map(c => c.replace('.csv', '')).sort();
let nBook = 0;
for (const code of codes) {
  let ks;
  try { ks = loadBook(code); } catch (e) { continue; }
  const last = ks.length - 1;
  if (last < WARMUP + Math.max(...HOLDS) * BPD + 50) continue;
  nBook++;
  for (const h of HOLDS) {
    const hb = h * BPD;
    for (let i = 0; i < SAMPLES; i++) {
      const ei = WARMUP + Math.floor(Math.random() * (last - hb - WARMUP));
      const jj = ei + hb;
      if (jj >= ks.length || ks[ei].bad || ks[jj].bad) continue;
      const r = ks[jj].c / ks[ei].o - 1 - FEE;
      if (isFinite(r)) rawBase[h].push(r);
    }
  }
}

/* 输出 */
const label = TF === 'daily' ? '日线' : TF + '分钟';
const NM = { 1: '一买', 2: '二买', 3: '三买' };
console.log('\n===== ' + label + '买点上涨成功率（净费口径，基准 ' + nBook + ' 票 × ' + SAMPLES + ' 次）=====');
console.log('买点 持有 | 信号n  上涨率   基准上涨率    z');
console.log('-'.repeat(56));
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const a = (j.sig[Lv] && j.sig[Lv][h]) || [];
  const z = propZ(a, rawBase[h]);
  console.log(` ${NM[Lv]} ${String(h).padStart(2)}日 |${String(a.length).padStart(6)}  ${(100 * upRate(a)).toFixed(1).padStart(6)}%  ${(100 * upRate(rawBase[h])).toFixed(1).padStart(8)}%  ${z == null ? 'n/a' : z.toFixed(2).padStart(6)}`);
}
console.log('\n基准合并上涨率（参考）:');
for (const h of HOLDS) console.log('  ' + h + '日: ' + (100 * upRate(rawBase[h])).toFixed(1) + '%  (n=' + rawBase[h].length + ')');
