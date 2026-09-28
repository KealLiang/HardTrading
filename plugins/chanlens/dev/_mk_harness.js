const fs = require('fs');
const kl = JSON.parse(fs.readFileSync('tools/testdata/600519_daily.json', 'utf8'));
const klines = kl.klines || kl;
const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{margin:0}canvas{width:1200px;height:640px}</style></head><body>'
  + '<canvas id="c" width="1200" height="640"></canvas>'
  + '<script src="../core/indicators.js"></' + 'script>'
  + '<script src="../core/chan.js"></' + 'script>'
  + '<script src="../chart/renderer.js"></' + 'script>'
  + '<script>const KL=' + JSON.stringify(klines) + ';'
  + 'const r=ChanEngine.analyze(KL,{});'
  + 'const v=CLRenderer.create(document.getElementById("c"),{});'
  + 'v.setData({klines:KL,name:"600519",code:"600519",period:"daily",result:r});v.render();'
  + 'document.title="PTS="+r.points.length;'
  + '</' + 'script></body></html>';
fs.writeFileSync('dev/_render_harness.html', html);
const Chan = require('../core/chan.js');
console.log('points:', Chan.analyze(klines, {}).points.length, 'klines:', klines.length);
