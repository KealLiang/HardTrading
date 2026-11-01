/* ==========================================================================
 * stability.js —— 信号稳定性检查：买点被"发现"之后会不会消失
 *
 * 背景：scan.js 是逐 bar 切片重算（ks.slice(0,t+1)），所以 discT 那一刻信号真实存在。
 * 但新 K 线进来后，笔/中枢可能重划，导致这个买点在后来的视图中"不见了"。
 * 实盘含义：你在 discT+1 开盘买入时信号是真的；但如果它隔天就消失，说明这类信号不稳。
 *
 * 检查：对每个 lag=1 的买点，看 discT+k（k=1..6）时同 key(type:level:readyK) 是否还在。
 * 用法：node stability.js
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');
const Chan = require('D:/Trading/plugins/chanlens/core/chan.js');

const packFile = path.join(__dirname, 'tmp', 'pack_daily.json');
if (!fs.existsSync(packFile)) { console.error('缺 ' + packFile + '，先跑 TF=daily node scan.js'); process.exit(1); }
const pack = JSON.parse(fs.readFileSync(packFile, 'utf8'));
const KS = 6;                       // 往后看几根
const cache = {};
const getKs = code => cache[code] || (cache[code] = L.loadDaily(code));

const stat = {};                    // stat[k] = { tot, alive }
for (let k = 1; k <= KS; k++) stat[k] = { tot: 0, alive: 0 };
const byType = {};                  // byType[ty][k]
let nSig = 0, nChecked = 0;

for (const p of pack.packs) {
  let ks;
  try { ks = getKs(p.code); } catch (e) { continue; }
  for (const b of p.buy) {
    if (b.discT - b.readyK !== 1) continue;         // 与回测同一口径
    nSig++;
    const ty = 'L' + b.level;
    byType[ty] = byType[ty] || {};
    for (let k = 1; k <= KS; k++) byType[ty][k] = byType[ty][k] || { tot: 0, alive: 0 };
    for (let k = 1; k <= KS; k++) {
      const t = b.discT + k;
      if (t > ks.length - 1) continue;
      const r = Chan.analyze(ks.slice(0, t + 1), {});
      const has = r.points.some(x => x.type === b.type && x.level === b.level && x.readyK === b.readyK);
      stat[k].tot++; if (has) stat[k].alive++;
      byType[ty][k].tot++; if (has) byType[ty][k].alive++;
    }
    nChecked++;
  }
}

const pc = (a, b) => b ? (100 * a / b).toFixed(1) + '%' : 'n/a';
console.log('检查信号 ' + nSig + ' 个（lag=1），每个往后看 ' + KS + ' 根\n');
console.log('k（发现后再过几根）  同 key 仍在  占比');
for (let k = 1; k <= KS; k++) {
  console.log(String(k).padStart(12) + String(stat[k].alive).padStart(14) + '  ' + pc(stat[k].alive, stat[k].tot));
}
console.log('\n按类型：');
for (const ty of ['L1', 'L2', 'L3']) {
  if (!byType[ty]) continue;
  const row = [];
  for (let k = 1; k <= KS; k++) row.push('k=' + k + ' ' + pc(byType[ty][k].alive, byType[ty][k].tot));
  console.log(ty + '  ' + row.join('  '));
}

fs.writeFileSync(path.join(__dirname, 'out', 'stability.json'), JSON.stringify({
  generatedAt: new Date().toISOString(), ks: KS, nSig, stat, byType
}, null, 1));
console.log('\n产物：out/stability.json');
