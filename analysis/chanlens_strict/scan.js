/* ==========================================================================
 * scan.js —— 逐 bar 切片扫描，导出结构包
 *
 * 用法：TF=daily|30|60 node scan.js        （SMOKE=1 只跑前 2 只，用于冒烟）
 * 产物：tmp/pack_<tf>.json
 *
 * 纪律：
 *   1. 只取「首次发现」的买卖点（key = type:level:readyK），发现时刻 discT 一并记录；
 *   2. 每个 bar 快照当时的参照位（最近中枢 ZD / 最近一笔的低点、高点），
 *      供入场时使用——不取事后才确认的极值；
 *   3. 记录 lag = discT - readyK 分布，断言 lag >= 1（分型需右侧一根）。
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');

const TF = process.env.TF || 'daily';
if (!['daily', '30', '60'].includes(TF)) { console.error('TF 只支持 daily|30|60'); process.exit(1); }
const SMOKE = process.env.SMOKE === '1';
const WARMUP = TF === 'daily' ? 500 : (TF === '30' ? 500 : 250);

const tmpDir = path.join(__dirname, 'tmp');
if (!fs.existsSync(tmpDir)) fs.mkdirSync(tmpDir, { recursive: true });
const log = m => process.stderr.write(m + '\n');

/* 数据源：TF=60 优先用真实 60m（新浪源已前复权）；缺文件或 SYNTH60=1 时退回 30m 合成 */
const SYNTH60 = process.env.SYNTH60 === '1';
function loadKs(code) {
  if (TF === 'daily') return L.loadDaily(code);
  if (TF === '30') return L.load30(code);
  if (!SYNTH60) {
    const k60 = L.load60(code);
    if (k60 && k60.length > 100) return k60;
    log('60m 无真实文件，退回 30m 合成: ' + code);
  }
  return L.to60(L.load30(code));
}

/** 刻度门禁：日线(前复权) 与 30m(原始价) 若存在份额折算/拆分错配，整只剔除 */
function scaleConsistent(code, ks) {
  let daily;
  try { daily = L.loadDaily(code); } catch (e) { return { ok: false, why: '无日线' }; }
  const dmap = new Map(daily.map(k => [k.date, k.c]));
  const byDate = new Map();
  for (const k of ks) if (dmap.has(k.date)) byDate.set(k.date, k.c);
  if (byDate.size < 50) return { ok: false, why: '重叠日不足 ' + byDate.size };
  let mism = 0;
  for (const [d, c30] of byDate) {
    const r = c30 / dmap.get(d);
    if (r < 0.9 || r > 1.1) mism++;
  }
  return mism === 0 ? { ok: true } : { ok: false, why: '刻度错配 ' + mism + '/' + byDate.size };
}

/* 取当前切片的结构参照：最近中枢 ZD/ZG、最近一笔低点/高点 */
function snapshot(res) {
  const zss = res.zhongshus || [];
  const zs = zss.length ? zss[zss.length - 1] : null;
  const bis = res.bis || [];
  let low = null, high = null;
  for (let i = bis.length - 1; i >= 0; i--) {
    if (isFinite(bis[i].low) && isFinite(bis[i].high)) { low = bis[i].low; high = bis[i].high; break; }
  }
  return {
    zsZD: zs ? zs.ZD : null,
    zsZG: zs ? zs.ZG : null,
    biLow: low,
    biHigh: high
  };
}

function collect(res, typeWanted, seen, out, t) {
  for (const p of res.points) {
    if (p.type !== typeWanted) continue;
    if (p.level < 1 || p.level > 3) continue;
    const key = p.type + ':' + p.level + ':' + p.readyK;
    if (seen.has(key)) continue;
    seen.add(key);
    const s = snapshot(res);
    out.push({
      level: p.level, type: p.type, readyK: p.readyK, k: p._k,
      price: p.price, discT: t, note: p.note,
      zsZD: p.extra && p.extra.zsZD != null ? p.extra.zsZD : s.zsZD,
      zsZG: p.extra && p.extra.zsZG != null ? p.extra.zsZG : s.zsZG,
      b1: p.extra && p.extra.b1 != null ? p.extra.b1 : null,
      refZD: s.zsZD, refBiLow: s.biLow, refBiHigh: s.biHigh
    });
  }
}

const codesAll = L.listCodes();
const codes = SMOKE ? ['510300', '159915'] : codesAll;   // 冒烟取历史最长的两只
const packs = [];
const lagHist = { buyBi: {}, sellBi: {}, buySeg: {}, sellSeg: {} };

for (const code of codes) {
  let ks;
  try { ks = loadKs(code); } catch (e) { log('skip ' + code + ' ' + e.message); continue; }
  if (ks.length < WARMUP + 200) { log('skip ' + code + ' 太短 ' + ks.length); continue; }
  if (TF !== 'daily') {
    const chk = scaleConsistent(code, ks);
    if (!chk.ok) { log('skip ' + code + ' ' + chk.why); continue; }
  }

  const n = ks.length;
  const refZD = new Array(n).fill(null), refLow = new Array(n).fill(null), refHigh = new Array(n).fill(null);
  const buy = [], sell = [], sellSeg = [], buySeg = [];
  const seenB = new Set(), seenS = new Set(), seenBS = new Set(), seenSS = new Set();

  for (let t = WARMUP; t < n; t++) {
    const slice = ks.slice(0, t + 1);
    const res = Chan.analyze(slice, {});                      // 笔派生（主口径）
    const s = snapshot(res);
    refZD[t] = s.zsZD; refLow[t] = s.biLow; refHigh[t] = s.biHigh;
    collect(res, 1, seenB, buy, t);
    collect(res, -1, seenS, sell, t);

    if (TF === 'daily') {                                      // 线段派生只记录（日线才跑，低级别样本少但一致）
      const resSeg = Chan.analyze(slice, { pointsOnSegs: true });
      collect(resSeg, 1, seenBS, buySeg, t);
      collect(resSeg, -1, seenSS, sellSeg, t);
    }
  }

  // 填充参照位空档（前向填充），供随机入场按日取用
  for (let i = 1; i < n; i++) {
    if (refZD[i] == null) refZD[i] = refZD[i - 1];
    if (refLow[i] == null) refLow[i] = refLow[i - 1];
    if (refHigh[i] == null) refHigh[i] = refHigh[i - 1];
  }

  // 滞后分布（断言检查用）
  const bump = (h, p) => { const lag = p.discT - p.readyK; h[lag] = (h[lag] || 0) + 1; };
  for (const p of buy) bump(lagHist.buyBi, p);
  for (const p of sell) bump(lagHist.sellBi, p);
  for (const p of buySeg) bump(lagHist.buySeg, p);
  for (const p of sellSeg) bump(lagHist.sellSeg, p);

  packs.push({
    code, tf: TF, n,
    dates: ks.map(k => k.date), o: ks.map(k => k.o), c: ks.map(k => k.c),
    h: ks.map(k => k.h), l: ks.map(k => k.l), bad: ks.map(k => !!k.bad),
    atr: L.atrSeries(ks, 14),
    refZD, refLow, refHigh,
    buy, sell, buySeg, sellSeg
  });
  log(code + ' n=' + n + ' 买点' + buy.length + ' 卖点' + sell.length +
      ' | 线段派生 买' + buySeg.length + ' 卖' + sellSeg.length);
}

const outFile = path.join(tmpDir, 'pack_' + TF + '.json');
fs.writeFileSync(outFile, JSON.stringify({
  tf: TF, warmup: WARMUP, generatedAt: new Date().toISOString(),
  lagHist, packs
}));

/* ---------------- 滞后断言 ---------------- */
function lagSummary(h) {
  const ks = Object.keys(h).map(Number).sort((a, b) => a - b);
  const tot = ks.reduce((s, k) => s + h[k], 0);
  const one = h[1] || 0;
  return { total: tot, lag1: one, lag1Share: tot ? one / tot : null, lags: ks.filter(k => k !== 1).slice(0, 6) };
}
console.log('=== 滞后分布 lag = 首次发现bar − readyK（' + TF + '）===');
for (const [nm, h] of Object.entries(lagHist)) {
  const s = lagSummary(h);
  console.log(nm.padEnd(8) + ' 共 ' + String(s.total).padStart(5) + '  lag=1 ' + String(s.lag1).padStart(5) +
    ' (' + (s.lag1Share == null ? 'n/a' : (100 * s.lag1Share).toFixed(1) + '%') + ')  lag>1 示例 ' + JSON.stringify(s.lags));
}
const allLags = Object.keys(Object.assign({}, lagHist.buyBi, lagHist.sellBi)).map(Number);
const bad = allLags.filter(k => k < 1);
console.log('断言 lag>=1（readyK 不晚于发现bar）: ' + (bad.length === 0 ? '通过' : '失败 lag=' + bad.join(',')));
console.log('产物：' + outFile + '  标的 ' + packs.length + ' 只');
