/* 探针：200 根 30m 能不能扫出「正在形成」的信号？不同长度对比。
 * 用法：node tools/scan_probe.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const Chan = require('../core/chan.js');
const S = require('../core/scanner.js').CLScanner;   // Node 下挂在 module.exports 上

const DIR = path.join(__dirname, 'testdata');
const files = fs.readdirSync(DIR).filter(f => f.endsWith('.json'));

function loadKl(f) {
  const j = JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf8'));
  const kl = j.klines || j;
  return Array.isArray(kl) ? kl : null;
}

console.log('文件'.padEnd(22), '长度'.padEnd(6), '信号', '  备注');
files.forEach(f => {
  const kl = loadKl(f);
  if (!kl || kl.length < 60) return;
  [100, 150, 200, 300, 400, kl.length].forEach(n => {
    if (n > kl.length) return;
    const sub = kl.slice(kl.length - n);
    const res = Chan.analyze(sub, {});
    const sig = S.pickSignal(sub, res, { maxLag: 10 });
    const label = sig ? `${sig.level}${sig.type > 0 ? '买' : '卖'}` : '—';
    console.log(f.padEnd(24), String(n).padEnd(6), label.padEnd(6),
      sig ? `readyK=${sig.readyK}/${n - 1} lag=${sig.lag} ${sig.note} 确认=${sig.confirmed}` : '');
  });
  console.log('-'.repeat(70));
});
