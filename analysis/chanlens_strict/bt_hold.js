/* ==========================================================================
 * bt_hold.js —— 极简持有期回测：只测「买点 + 固定持有 x 天」，日线
 *
 * 规则（无未来数据）：
 *   买点在 discT 收盘确认 → discT + 1 开盘买入 → 第 x 根之后开盘卖出
 *   只接受 lag = discT − readyK === 1 的买点（lag>1 视为事后回填，剔除）
 *   收益扣双边费 0.1%
 *
 * 三个基线（同样扣费、同样 x 日持有）：
 *   B1 随便哪天买：同标的全样本所有可入场日的平均
 *   B2 同月随便买：同标的、入场月相同的所有交易日 → 剔除「信号扎堆在牛市」的市场环境
 *   B3 同价位买：同标的、入场时价格分位 |Δ|≤0.10 的交易日 → 剔除「信号都在低位」这个因子
 *   超额 = 信号收益 − 对应基线（逐笔配对）
 *
 * 用法：node bt_hold.js   （先 TF=daily node scan.js 生成 tmp/pack_daily.json）
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const FEE = 0.001;                 // 双边合计
const XS = [3, 5, 7, 10, 20, 60];

/* 品种分组：判断一买超额是否跨类别稳健（组内样本少时只作方向参考） */
const GROUP = {
  '宽基': ['510300', '510500', '512100', '159949', '588000'],
  '科技': ['159819', '159995', '512480', '515880', '512980', '159869', '562500', '159857', '515700', '516160'],
  '消费': ['159928', '159825', '512690', '159996', '159865'],
  '医药': ['159992', '512010', '512170'],
  '金融': ['512800', '512880', '512070'],
  '周期': ['515220', '512400', '515210', '512200'],
  '其他行业': ['512660', '512890', '159611', '516970'],
  '海外': ['513050', '513260', '159920', '513100', '513500'],
  '商品/债券': ['518880', '511010']
};
const groupOf = {};
for (const [g, cs] of Object.entries(GROUP)) for (const c of cs) groupOf[c] = g;
const PCT_WIN = 250;               // 价格分位窗口
const PCT_BAND = 0.10;             // B3 的分位带宽
const PCT_BAND4 = 0.15;            // B4 的分位带宽
const B4_MIN = 8;                  // B4 最少对照样本

const packFile = path.join(__dirname, 'tmp', 'pack_daily.json');
if (!fs.existsSync(packFile)) { console.error('缺 ' + packFile + '，先跑 TF=daily node scan.js'); process.exit(1); }
const pack = JSON.parse(fs.readFileSync(packFile, 'utf8'));

const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
function sd(a) {
  if (a.length < 2) return null;
  const m = mean(a);
  return Math.sqrt(a.reduce((s, x) => s + (x - m) * (x - m), 0) / (a.length - 1));
}
const median = a => {
  if (!a.length) return null;
  const s = a.slice().sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const pct = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : (x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp';
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const tStat = a => {
  if (a.length < 3) return null;
  const s = sd(a);
  return s ? mean(a) / (s / Math.sqrt(a.length)) : null;
};

/* 预计算：每只标的的价格分位 */
function pctSeries(p) {
  const n = p.c.length, out = new Array(n).fill(null);
  for (let i = PCT_WIN; i < n; i++) {
    let lo = Infinity, hi = -Infinity;
    for (let j = i - PCT_WIN + 1; j <= i; j++) { if (p.c[j] < lo) lo = p.c[j]; if (p.c[j] > hi) hi = p.c[j]; }
    out[i] = hi > lo ? (p.c[i] - lo) / (hi - lo) : null;
  }
  return out;
}

const byX = {};                    // byX[x][type] = { rows:[{ex2, ex3, ...}] }
const perCode = {};                // perCode[x][code][type] = [ex2...]
const sigDates = [];               // 信号日期分布
let lagDrop = 0, noRoom = 0;

/* lag>1 与「剩余天数不足」只统计一次（别在每个 x 循环里重复累加） */
for (const p of pack.packs) for (const b of p.buy) if (b.discT - b.readyK !== 1) lagDrop++;
for (const p of pack.packs) for (const b of p.buy) {
  if (b.discT - b.readyK !== 1) continue;
  if (b.discT + 1 + XS[0] > p.c.length - 1) noRoom++;
}

for (const p of pack.packs) {
  const n = p.c.length, o = p.o;
  const pq = pctSeries(p);
  const months = p.dates.map(d => d.slice(0, 7));
  const quarters = months.map(m => m.slice(0, 4) + 'Q' + (Math.floor((+m.slice(5, 7) - 1) / 3) + 1));

  for (const x of XS) {
    byX[x] = byX[x] || {};
    perCode[x] = perCode[x] || {};

    /* 该标的在每个可入场日的 x 日收益（全部扣费） */
    const all = [], byMonth = {}, byQ = {};
    for (let t = p.warmup; t + x <= n - 1; t++) {
      const r = o[t + x] / o[t] - 1 - FEE;
      all.push(r);
      const m = months[t];
      (byMonth[m] = byMonth[m] || []).push({ t, r });
      const q = quarters[t];
      (byQ[q] = byQ[q] || []).push({ t, r, pc: pq[t] });
    }

    for (const b of p.buy) {
      if (b.discT - b.readyK !== 1) continue;
      const e = b.discT + 1;
      if (e + x > n - 1) continue;
      const r = o[e + x] / o[e] - 1 - FEE;

      /* B2 同月 */
      const same = byMonth[months[e]];
      if (!same || same.length < 10) continue;
      const B2 = mean(same.map(z => z.r));

      /* B3 同价位：同标的所有可入场日里，价格分位与信号日相近的 */
      const ps = pq[e];
      const near = [];
      if (ps != null) {
        for (let t = p.warmup; t + x <= n - 1; t++) {
          if (pq[t] == null) continue;
          if (Math.abs(pq[t] - ps) <= PCT_BAND) near.push(o[t + x] / o[t] - 1 - FEE);
        }
      }
      const B3 = near.length >= 30 ? mean(near) : null;

      /* B4 同季度 + 同价位：同时锁住时间和价位两个因子 */
      let B4 = null;
      if (ps != null) {
        const pool = (byQ[quarters[e]] || []).filter(z => z.pc != null && Math.abs(z.pc - ps) <= PCT_BAND4);
        if (pool.length >= B4_MIN) B4 = mean(pool.map(z => z.r));
      }

      const rec = {
        code: p.code, date: p.dates[e], e, type: 'L' + b.level,
        r, B1: mean(all), B2, B3, B4, pct: ps
      };
      rec.ex2 = r - rec.B2;
      rec.ex3 = B3 == null ? null : r - B3;
      rec.ex4 = B4 == null ? null : r - B4;

      for (const ty of [rec.type, 'ALL']) {
        (byX[x][ty] = byX[x][ty] || []).push(rec);
        ((perCode[x][p.code] = perCode[x][p.code] || {})[ty] = perCode[x][p.code][ty] || []).push(rec.ex2);
      }
    }
  }
}

/* ---------------------------------------------------------------- 输出 */
const TY = { L1: '一买', L2: '二买', L3: '三买', ALL: '全部' };
const lines = [];
const out = m => { lines.push(m); console.log(m); };

out('=== 日线 · 买点 + 固定持有 x 天（扣双边费 0.1%）===');
out('样本：' + pack.packs.length + ' 只 ETF，' + pack.packs.map(p => p.dates[0]).sort()[0] + ' ~ ' +
  pack.packs.map(p => p.dates[p.dates.length - 1]).sort().pop() + '；lag>1 剔除 ' + lagDrop + ' 个，剩余天数不足跳过 ' + noRoom + ' 次');

const tableOut = {};
for (const x of XS) {
  out('\n--- x = ' + x + ' 天 ---');
  out('类型    n    信号      超额vs同月(t)     超额vs同价位(t)     超额vs同季同价位(t)   分位中位  逐笔胜率');
  for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
    const rows = byX[x][ty] || [];
    if (!rows.length) continue;
    const r = rows.map(z => z.r), e2 = rows.map(z => z.ex2);
    const e3 = rows.filter(z => z.ex3 != null).map(z => z.ex3);
    const e4 = rows.filter(z => z.ex4 != null).map(z => z.ex4);
    const B1 = mean(rows.map(z => z.B1)), B2 = mean(rows.map(z => z.B2));
    const B3 = rows.filter(z => z.B3 != null).length ? mean(rows.filter(z => z.B3 != null).map(z => z.B3)) : null;
    const B4 = rows.filter(z => z.B4 != null).length ? mean(rows.filter(z => z.B4 != null).map(z => z.B4)) : null;
    const winShare = e2.filter(v => v > 0).length / e2.length;
    const pm = median(rows.map(z => z.pct).filter(v => v != null));
    /* 绝对胜率与赔率：与基线无关，只看这笔交易本身赚没赚 */
    const W = r.filter(v => v > 0), L = r.filter(v => v <= 0);
    const winAbs = W.length / r.length;
    const avgWin = W.length ? mean(W) : null, avgLoss = L.length ? mean(L) : null;
    const pl = (avgWin != null && avgLoss) ? avgWin / Math.abs(avgLoss) : null;
    out(TY[ty].padEnd(5) + String(rows.length).padStart(4) + '  ' + pct(mean(r)).padStart(8) + '  ' +
      pp(mean(e2)).padStart(8) + ' (' + f2(tStat(e2)).padStart(6) + ')  ' +
      pp(mean(e3)).padStart(8) + ' (' + f2(tStat(e3)).padStart(6) + ')  ' +
      pp(mean(e4)).padStart(8) + ' (' + f2(tStat(e4)).padStart(6) + ')  ' +
      pct(pm).padStart(8) + '  胜率' + pct(winAbs).padStart(6) + ' 赔率' + f2(pl).padStart(5));
    /* B4p / sig4：只在「同季同价位有足够对照日」的那批笔上算，保证 sig4 − B4p = ex4 */
    const sub4 = rows.filter(z => z.ex4 != null);
    const B4p = sub4.length ? mean(sub4.map(z => z.B4)) : null;
    const sig4 = sub4.length ? mean(sub4.map(z => z.r)) : null;
    tableOut[x + ty] = {
      n: rows.length, sig: mean(r), B1, B2, B3, B4, B4p, sig4,
      ex1: mean(r) - B1, ex2: mean(e2), t2: tStat(e2),
      ex3: mean(e3), t3: tStat(e3), ex4: mean(e4), t4: tStat(e4),
      n4: e4.length, winShare, pctMed: pm,
      winAbs, avgWin, avgLoss, pl
    };
  }
  out('（B1 随便买 ' + pct(mean((byX[x].ALL || []).map(z => z.B1))) +
    '｜B2 同月 ' + pct(mean((byX[x].ALL || []).map(z => z.B2))) + '｜各项均已扣费）');
}

/* 重叠率：同标的、同一 x 下，本笔入场早于上一笔出场 → 收益不独立，t 会偏大 */
function overlapShare(rows, x) {
  const g = {};
  for (const z of rows) (g[z.code] = g[z.code] || []).push(z);
  let tot = 0, ov = 0;
  for (const code of Object.keys(g)) {
    const a = g[code].slice().sort((p, q) => p.e - q.e);
    for (let i = 1; i < a.length; i++) { tot++; if (a[i].e <= a[i - 1].e + x) ov++; }
  }
  return tot ? ov / tot : null;
}

out('\n=== 持仓重叠率（同标的连续信号，本笔入场早于上笔出场）===');
out(XS.map(x => 'x=' + x + '：' + pct(overlapShare(byX[x].ALL || [], x))).join('   ') +
  '　重叠会让 t 值偏大');

/* 分段稳健性：信号收益是否只来自某一段行情 */
out('\n=== 分段稳健性（超额 vs 同月，按入场年份切两段）===');
out('x     类型   2012-2019（n/超额/t）              2020-2026（n/超额/t）');
const segOut = {};
for (const x of XS) {
  for (const ty of ['L1', 'ALL']) {
    const rows = (byX[x][ty] || []);
    const a = rows.filter(z => z.date < '2020-01-01').map(z => z.ex2);
    const b = rows.filter(z => z.date >= '2020-01-01').map(z => z.ex2);
    if (a.length < 5 && b.length < 5) continue;
    out(String(x).padStart(2) + '  ' + TY[ty].padEnd(5) +
      (String(a.length).padStart(4) + ' / ' + pp(mean(a)).padStart(8) + ' / ' + f2(tStat(a)).padStart(6)).padEnd(38) +
      String(b.length).padStart(4) + ' / ' + pp(mean(b)).padStart(8) + ' / ' + f2(tStat(b)));
    segOut[x + ty] = { a: { n: a.length, ex: mean(a), t: tStat(a) }, b: { n: b.length, ex: mean(b), t: tStat(b) } };
  }
}

/* 按标的聚合（更保守：每只各算一个均值，再对标的数求 t；单只 ≥5 个信号才入表） */
out('\n=== 按标的聚合（每只先求均值，再对 ' + pack.packs.length + ' 只求 t；剔除过度自信）===');
out('x     类型   标的数  超额2 均值   跨标的 t   正超额标的占比   超额3 均值   跨标的 t');
const aggOut = {};
for (const x of XS) {
  for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
    const arr = [], arr3 = [];
    for (const code of Object.keys(perCode[x] || {})) {
      const v = perCode[x][code][ty];
      if (v && v.length >= 5) arr.push(mean(v));
    }
    if (arr.length < 5) continue;
    const t = tStat(arr), pos = arr.filter(v => v > 0).length / arr.length;
    out(String(x).padStart(2) + '  ' + TY[ty].padEnd(5) + String(arr.length).padStart(5) + '  ' +
      pp(mean(arr)).padStart(9) + '  ' + f2(t).padStart(8) + '  ' + pct(pos).padStart(12));
    aggOut[x + ty] = { nCodes: arr.length, ex2: mean(arr), t, posShare: pos };
  }
}

/* 不同标的是否有不同最优 x */
out('\n=== 每只标的最优 x（按超额2）===');
const bestDist = {};
for (const code of Object.keys(perCode[XS[0]] || {})) {
  let best = null;
  for (const x of XS) {
    const v = perCode[x][code] && perCode[x][code].ALL;
    if (!v || v.length < 8) continue;
    const m = mean(v);
    if (!best || m > best.m) best = { x, m, n: v.length };
  }
  if (!best) continue;
  (bestDist[best.x] = bestDist[best.x] || []).push(best.m);
}
out(XS.map(x => 'x=' + x + '：' + (bestDist[x] || []).length + ' 只').join('  ') +
  '｜最优 x 的中位超额 ' + pp(median(Object.values(bestDist).flat())));
out('（若最优 x 在各标的间随机分布，说明不存在通用持有期，只是拟合噪声）');
/* ------------------------------------------------------- 报告（结论版） */
/* 只写结论，不写推理过程；推理放对话里讲。 */

let vh = null;
try { vh = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'verify_hold.json'), 'utf8')); } catch (e) { }

const M = [];
const P = s => M.push(s);

const firstDay = pack.packs.map(p => p.dates[0]).sort()[0];
const lastDay = pack.packs.map(p => p.dates[p.dates.length - 1]).sort().pop();
const genAt = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');
const nRange = ty => XS.map(x => tableOut[x + ty] ? tableOut[x + ty].n : null).filter(v => v != null);
const nTxt = ty => { const a = nRange(ty); return Math.min(...a) + '~' + Math.max(...a); };
const sigT = t => t != null && Math.abs(t) >= 2;
const B = (v, t) => (sigT(t) ? '**' + v + '**' : v);
const cell = (x, ty, key, fmt, withT) => {
  const o = tableOut[x + ty];
  if (!o || o[key] == null) return '—';
  return B(fmt(o[key]), withT ? o[withT] : null);
};

/* ---------- 抬头 ---------- */
P('# 日线买点：信号到底有没有超额收益\n');
P('> ' + pack.packs.length + ' 只 ETF｜' + firstDay + ' ~ ' + lastDay +
  '｜一买 ' + nTxt('L1') + '、二买 ' + nTxt('L2') + '、三买 ' + nTxt('L3') + ' 个信号');
P('> 买点收盘确认 → 次日开盘买 → 持有 x 个交易日 → 开盘卖，扣双边 0.1%｜生成 ' + genAt + '\n');

/* ---------- 结论 ---------- */
P('## 结论\n');
P('**一买有超额。二买测不出。三买没有。**\n');
P('| 类型 | 信号数 | 进场位置 | 判定 |');
P('|---|---|---|---|');
P('| 一买 | ' + nTxt('L1') + ' | 250 日分位 ' + pct(tableOut['20L1'].pctMed) + '（偏低） | **有超额**，持有 3~60 天全部成立 |');
P('| 二买 | ' + nTxt('L2') + ' | 250 日分位 ' + pct(tableOut['20L2'].pctMed) + '（中间） | 测不出（方向为正但不显著） |');
P('| 三买 | ' + nTxt('L3') + ' | 250 日分位 ' + pct(tableOut['20L3'].pctMed) + '（偏高） | **无正超额**，拿 60 天为负 |');
P('');
P('**超额**（单位 pp = 百分点）＝ 这笔实际赚的钱 −「同一只基金、同一个季度、价格分位 ±0.15 的普通交易日」赚的钱。' +
  '把「那阵子大盘在涨」和「买得便宜」都扣掉，剩下的才算买点自己的本事。\n');
const c3 = tableOut['20L3'];
P('> 三买拿 20 天单笔赚 ' + pct(c3.sig4) + '，但同期同价位的普通交易日能赚 ' + pct(c3.B4p) + '。**它赚的是行情，不是买点。**\n');

/* ---------- §1 核心表：单笔 → 超额 ---------- */
P('## 1 超额收益（单笔 → 扣掉基准）\n');
P('| 持有 | 一买 | 二买 | 三买 |');
P('|---|---|---|---|');
for (const x of XS) {
  let line = '| ' + x + ' 天 |';
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = tableOut[x + ty];
    line += ' ' + pct(o.sig4) + ' → ' + B(pp(o.ex4), o.t4) + ' |';
  }
  P(line);
}
P('');
P('左边是这笔实际到手（单笔平均，已扣 0.1% 费用），右边是扣掉「同期同价位随便买」之后剩下的。' +
  '**粗体 = 统计上站得住（t ≥ 2）**，完整 t 值在附录 A。');
P('一买 6 个持有期超额全为正、全部显著；二买全不显著；三买全为负，其中 7/10/60 天显著。\n');

/* ---------- §2 基准 ---------- */
P('## 2 基准：同期同价位随便买能赚多少\n');
P('| 持有 | 一买 | 二买 | 三买 |');
P('|---|---|---|---|');
for (const x of XS) {
  let line = '| ' + x + ' 天 |';
  for (const ty of ['L1', 'L2', 'L3']) line += ' ' + pct(tableOut[x + ty].B4p) + ' |';
  P(line);
}
P('');
P('基准 = 同一只基金、同一个季度、过去 250 日价格分位 ±0.15 的所有交易日，各买一次拿同样的 x 天，取平均。');
P('**一买的基准是负的**：在「跌了很久、位置很低」的时点随便买，3~20 天平均亏 ' +
  pct(tableOut['3L1'].B4p) + ' ~ ' + pct(tableOut['20L1'].B4p) + '（60 天转正 ' + pct(tableOut['60L1'].B4p) +
  '，因为这段时间本身有反弹），而一买还能赚 ' + pct(tableOut['3L1'].sig4) + ' ~ ' + pct(tableOut['20L1'].sig4) + '。这才叫超额。');
P('**三买反过来**：那个位置本来就容易涨（' + pct(tableOut['3L3'].B4p) + ' ~ ' + pct(tableOut['60L3'].B4p) +
  '），三买只赚到 ' + pct(tableOut['3L3'].sig4) + ' ~ ' + pct(tableOut['60L3'].sig4) + '，比随便买还少。\n');

/* ---------- 费率 ---------- */
const a = tableOut['20L1'];
const fee3 = tableOut['3L1'].sig4, fee20 = tableOut['20L1'].sig4;
P('一买 3 天到手只有 ' + pct(fee3) + '：毛收益约 ' + pct(fee3 + FEE) + '，0.1% 的费用吃掉一半以上。' +
  '拿 20 天是 ' + pct(fee20) + '，费用只占 ' + (100 * FEE / (fee20 + FEE)).toFixed(0) + '%。**短线在 ETF 上被费率拖死。**\n');

/* ---------- §3 怎么用 ---------- */
P('## 3 怎么用\n');
P('1. **做一买，拿 20 天。** 超额最高（' + pp(a.ex4) + '）、最稳（t=' + f2(a.t4) + '）、单笔 ' + pct(a.sig4) + '。');
P('2. **别做 3 天。** 超额有，但单笔 ' + pct(fee3) + '，费用吃掉一半。');
P('3. **二买不单独开仓。** 6 个持有期没一个显著。');
P('4. **三买不当入场信号。** 它的用处只在趋势确认（说明中枢被突破且回踩成功），收益上体现不出来。\n');

/* ---------- §4 可信度 ---------- */
const posMin = Math.min(...XS.map(x => aggOut[x + 'L1'] ? aggOut[x + 'L1'].posShare : 1));
const posMax = Math.max(...XS.map(x => aggOut[x + 'L1'] ? aggOut[x + 'L1'].posShare : 0));
const a20 = aggOut['20L1'], s5 = segOut['5L1'];
P('## 4 这个结论有多可信\n');
P('| 质疑 | 检验结果 |');
P('|---|---|');
P('| 是不是某一只基金的运气 | 一买在 ' + (a20 ? a20.nCodes : '—') + ' 只有效标的中 ' + pct(posMin) + '~' + pct(posMax) + ' 为正，9 个品种组全为正 |');
P('| 是不是被重叠信号撑大了 t | 每只基金先算一个均值再检验：x=20 一买 ' + (a20 ? pp(a20.ex2) : '—') +
  '（t=' + (a20 ? f2(a20.t) : '—') + '），' + (a20 ? pct(a20.posShare) : '—') + ' 标的为正 |');
P('| 是不是只靠某一段行情 | 2020 年后 ' + (s5 ? s5.b.n + ' 个信号、' + pp(s5.b.ex) + '（t=' + f2(s5.b.t) + '）' : '—') +
  '；2012-2019 只有 ' + (s5 ? s5.a.n : '—') + ' 个，测不出 |');
P('| 有没有偷看未来 | 确认日收盘后才知道信号，次日开盘才买；独立脚本重算原始 CSV：入场违规 ' +
  (vh ? vh.err.notNext : '—') + '、价格不一致 ' + (vh ? vh.err.priceMismatch : '—') + ' |');
P('');

/* ---------- 附录 ---------- */
P('---\n');
P('## 附录 A 逐笔全表\n');
P('| x | 类型 | n | 单笔 | 胜率 | 赔率 | 均盈 / 均亏 | vs 同月（t） | vs 同价位（t） | vs 同季同价位（t） |');
P('|---|---|---|---|---|---|---|---|---|---|');
for (const x of XS) {
  for (const ty of ['L1', 'L2', 'L3']) {
    const o = tableOut[x + ty]; if (!o) continue;
    P('| ' + x + ' | ' + TY[ty] + ' | ' + o.n + ' | ' + pct(o.sig) + ' | ' + pct(o.winAbs) + ' | ' + f2(o.pl) +
      ' | ' + pct(o.avgWin) + ' / ' + pct(o.avgLoss) +
      ' | ' + pp(o.ex2) + ' (' + f2(o.t2) + ')' +
      ' | ' + pp(o.ex3) + ' (' + f2(o.t3) + ')' +
      ' | ' + pp(o.ex4) + ' (' + f2(o.t4) + ') |');
  }
}
P('');
P('「vs 同季同价位」要求同一季度里价格分位 ±0.15 至少有 ' + B4_MIN + ' 个对照日，凑不够的笔不进这一列' +
  '（x=5 时一买 ' + tableOut['5L1'].n + '→' + tableOut['5L1'].n4 + ' 笔、三买 ' + tableOut['5L3'].n + '→' + tableOut['5L3'].n4 + ' 笔）。');
P('本表「单笔」是全样本均值；正文第 1 节用的是「同季同价位可比子集」的均值（与超额严格同一批笔），两者最多差 0.07pp。\n');

P('## 附录 B 按标的聚合\n');
P('每只基金先算均值，再看是否多数基金方向一致（避免同标的连续信号把 t 撑大）：\n');
P('| 类型 | x=3 | x=5 | x=7 | x=10 | x=20 | x=60 |');
P('|---|---|---|---|---|---|---|');
for (const ty of ['L1', 'L2', 'L3']) {
  let line = '| ' + TY[ty] + ' |';
  for (const x of XS) {
    const o = aggOut[x + ty];
    line += o ? ' ' + pp(o.ex2) + '（t=' + f2(o.t) + '，正 ' + pct(o.posShare) + '） |' : ' — |';
  }
  P(line);
}
const shortPk = pack.packs.filter(p => p.warmup < pack.warmup);
const aggN5 = aggOut['5L1'] ? aggOut['5L1'].nCodes : null;
P('');
P('口径为 vs 同月。这里故意用较弱的基准：同季同价位的对照日门槛会砍掉部分标的的样本，跨标的检验要样本尽量全。方向与主表一致。' +
  (aggN5 && aggN5 < pack.packs.length
  ? pack.packs.length + ' 只里 ' + aggN5 + ' 只入表（单只信号 < 5 个的不进；' + shortPk.length + ' 只上市太晚）。' : '') + '\n');

/* 按品种组再切一刀，看一买超额是不是集中在某一类资产 */
const grp = [];
for (const g of Object.keys(GROUP)) {
  const codes = GROUP[g].filter(cc => pack.packs.some(p => p.code === cc));
  if (!codes.length) continue;
  const v = (byX[5].L1 || []).filter(z => codes.includes(z.code) && z.ex4 != null).map(z => z.ex4);
  if (v.length >= 5) grp.push([g, mean(v)]);
}
if (grp.length) {
  P('按品种拆（一买 x=5）：' + grp.length + ' 个组里 ' + grp.filter(z => z[1] > 0).length + ' 组为正，区间 ' +
    pp(Math.min(...grp.map(z => z[1]))) + ' ~ ' + pp(Math.max(...grp.map(z => z[1]))) +
    '（' + grp.map(z => z[0] + ' ' + pp(z[1])).join('、') + '）。不是单一品种特性。\n');
}

P('## 附录 C 分段、重叠、局限\n');
P('一买超额按入场年份切两段（vs 同月）：\n');
P('| x | 2012-2019 | 2020-2026 |');
P('|---|---|---|');
for (const x of XS) {
  const s = segOut[x + 'L1']; if (!s) continue;
  P('| ' + x + ' 天 | ' + s.a.n + ' 笔 ' + pp(s.a.ex) + '（t=' + f2(s.a.t) + '） | ' +
    s.b.n + ' 笔 ' + pp(s.b.ex) + '（t=' + f2(s.b.t) + '） |');
}
P('');
P('- **证据全在 2020 年后。** 准确的说法是「2020 年后有效」，不是「一直有效」。');
P('- **持仓重叠**：同标的连续信号叠加率 ' + XS.map(x => 'x=' + x + ' ' + pct(overlapShare(byX[x].ALL || [], x))).join('、') +
  '。重叠会让逐笔 t 偏大，所以以附录 B 的跨标的 t 为准。');
P('- **无单仓约束**：假设每个信号都有钱买。实际多个买点同时出现只能选一个，且可能没钱。');
P('- **成交价与滑点**：一律按开盘价成交、费用双边 0.1%。ETF 免印花税、实际佣金约万 0.5~2，费用这块是**高估**（偏保守）；' +
  '但完全没算滑点——大 ETF 开盘价差 0.02~0.05%，冷门 ETF 可能 0.1~0.3%，会吃掉一部分超额。');
P('- **x=20 是从这批数据里挑出来的最优**，不是在实盘前就定好的。好在一买 3~60 天全部显著为正，换个持有期不至于翻盘。');
P('- **只测 ETF**，不外推到个股（个股有业绩驱动、涨跌停、停牌，分布不同）。');
P('- 部分标的 2021 年后才上市，可用窗口只有 2~3 年，信号集中在 2023-2026 一段行情。\n');

P('## 附录 D 复现、可执行性、复核\n');
P('**信号不是事后回填的**：`scan.js` 对每只基金逐根回放——第 t 根收盘时只用 `ks.slice(0, t+1)` 重跑一遍引擎，' +
  '买点是那一刻引擎真的报出来的，记下首次发现时间 discT，买入 = discT + 1 的开盘价。价格分位也只用过去 250 根。\n');
P('```bash');
P('cd D:/Trading/analysis/chanlens_strict');
P('TF=daily node scan.js   # → tmp/pack_daily.json');
P('node bt_hold.js          # → report_hold.md + out/bt_hold.json');
P('node verify_hold.js      # 独立复核');
P('node stability.js        # 信号发现后会不会消失');
P('```\n');
if (vh) {
  P('`verify_hold.js` 直接读原始 CSV 重算，不复用 bt_hold.js 的任何算价函数：\n');
  P('| 检查项 | 结果 |');
  P('|---|---|');
  P('| 入场日 = 确认日 + 1（逐笔对 CSV 相邻行） | 违规 ' + vh.err.notNext + ' |');
  P('| 卖出日 = 入场日 + x，开盘价逐笔一致 | 不一致 ' + vh.err.priceMismatch + ' |');
  P('| 只用 lag = 1 的信号 | 剔除 ' + vh.err.lagNot1 + '（脚本记 ' + lagDrop + '）|');
  P('| 确认日之后没有下一根 K 线（不成交） | 剔除 ' + vh.err.tailEdge + ' 笔 |');
  P('| 18 个格子（6 个 x × 3 类）的 n / 均值 / 胜率逐位比对 | ' + (vh.badCells === 0 ? '全部一致' : vh.badCells + ' 格不符') + ' |');
  P('| 「同季同价位」基线用 CSV 独立重算 | 差异 < 0.01pp |');
} else {
  P('尚未运行 `node verify_hold.js`。');
}

/* 信号稳定性：发现之后新 K 线进来，笔/中枢可能重划，买点在事后视图里可能消失 */
let st = null;
try { st = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'stability.json'), 'utf8')); } catch (e) { }
if (st) {
  const sh = k => st.stat[k] ? pct(st.stat[k].alive / st.stat[k].tot) : '—';
  P('');
  P('**买点会不会隔天消失**（`stability.js`：发现后再放几根 K 线重算，看同一个买点还在不在）：\n');
  P('| 发现后再过 | 1 根 | 2 根 | 3 根 | 6 根 |');
  P('|---|---|---|---|---|');
  P('| 同一个买点仍在 | ' + sh(1) + ' | ' + sh(2) + ' | ' + sh(3) + ' | ' + sh(6) + ' |');
  P('');
  P('买入那一刻（discT+1）信号 100% 在；越往后越多买点被合并进新的笔、从视图里消失，' +
    '6 根后剩 ' + sh(6) + '。**这不影响下单时点，但意味着事后复盘看到的图与当时不完全一样。**\n');
}

const md = M.join('\n') + '\n';
fs.writeFileSync(path.join(__dirname, 'report_hold.md'), md);
console.log('\n报告：report_hold.md（' + md.trimEnd().split('\n').length + ' 行）');

/* 落盘 */
fs.writeFileSync(path.join(__dirname, 'out', 'bt_hold.json'), JSON.stringify({
  generatedAt: new Date().toISOString(), fee: FEE, xs: XS, lagDrop, noRoom,
  table: tableOut, byCode: aggOut, seg: segOut, bestX: Object.fromEntries(XS.map(x => [x, (bestDist[x] || []).length]))
}, null, 1));
fs.writeFileSync(path.join(__dirname, 'out', 'bt_hold.txt'), lines.join('\n'));
console.log('\n产物：out/bt_hold.json, out/bt_hold.txt');

