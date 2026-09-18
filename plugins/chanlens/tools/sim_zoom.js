/* 复现三图联动缩放：主图缩到最小后，任意图上滚一格滚轮会跳到最大放大 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

/* ---- 极简 DOM 桩 ---- */
const noop = () => {};
function fakeCtx() {
  return new Proxy({}, {
    get(t, k) {
      if (k === 'measureText') return () => ({ width: 20 });
      if (k === 'createLinearGradient') return () => ({ addColorStop: noop });
      if (k === 'canvas') return { width: 900, height: 400 };
      if (k in t) return t[k];
      return noop;
    },
    set(t, k, v) { t[k] = v; return true; }
  });
}
function fakeCanvas(w, h) {
  const hs = {};
  return {
    width: w, height: h, clientWidth: w, clientHeight: h,
    style: {}, getContext: () => fakeCtx(),
    addEventListener: (t, fn) => { (hs[t] = hs[t] || []).push(fn); },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: w, height: h }),
    _hs: hs
  };
}

const sandbox = { console, devicePixelRatio: 1, requestAnimationFrame: noop, document: { addEventListener: noop } };
sandbox.window = sandbox;
sandbox.global = sandbox;
sandbox.addEventListener = noop;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../chart/renderer.js'), 'utf8'), sandbox);
const R = sandbox.CLRenderer;

/* ---- 造数据：30m / 5m / 日线，各 800 根，时间跨度差异巨大 ---- */
const SEC = { '30m': 1800, '5m': 300, 'daily': 86400 };
function kl(period, n) {
  const step = SEC[period];
  const end = Date.parse('2026-09-17T15:00:00+08:00') / 1000;
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const t = end - i * step;
    out.push({ _t: t, open: 10, high: 11, low: 9, close: 10, volume: 100 });
  }
  return out;
}

const specs = [['30m', 430], ['5m', 210], ['daily', 210]];
const views = [], canvases = [];
/* 模拟 app.js 的联动：同步缩放倍数 / 相对平移 */
let syncing = false;
function eachView(fn) {
  if (syncing) return;
  syncing = true;
  views.forEach(v => { fn(v); });
  syncing = false;
}
specs.forEach(([p, h]) => {
  const c = fakeCanvas(900, h);
  canvases.push(c);
  const v = R.create(c, {
    defaultBars: 160,
    onZoom: (g) => eachView(x => g.reset ? x.zoomReset(g.reset) : x.zoomBy(g.factor, g.pxRatio)),
    onPan: (g) => eachView(x => x.panBy(g.dFrac))
  });
  v.setData({ klines: kl(p, 800), period: p, code: '600519', name: '测试', result: null });
  views.push(v);
});

function bars(v) {
  const r = v.indexRange();
  return r.i1 - r.i0 + 1;
}
function report(tag) {
  console.log(tag.padEnd(26) + views.map((v, i) =>
    specs[i][0].padStart(5) + ':' + String(bars(v)).padStart(4) + '根').join('  '));
}

function wheel(v, dir, px) {   // dir: 1 缩小, -1 放大
  const hs = v.canvas._hs.wheel;
  hs.forEach(fn => fn({ deltaY: dir, offsetX: px, offsetY: 100, preventDefault: noop }));
}

console.log('=== 初始 ==='); report('初始');

/* 1) 把主图缩到最小（滚到全貌） */
for (let i = 0; i < 60; i++) wheel(views[0], 1, 450);
report('主图缩到最小后');

/* 2) 在二图上滚一格滚轮（放大） */
wheel(views[1], -1, 450);
report('二图滚1格放大后');

/* 3) 再在主图上滚一格 */
wheel(views[0], -1, 450);
report('主图再滚1格');

/* 4) 再滚两格看看是否稳定 */
wheel(views[0], -1, 450);
report('主图第3次滚');
wheel(views[0], -1, 450);
report('主图第4次滚');

/* 5) 全览按钮：一键全览后再滚一格 */
eachView(v => v.zoomFull());
report('点全览后');
wheel(views[2], -1, 450);
report('日线滚1格');

console.log('\n各图自身限制：');
views.forEach((v, i) => console.log('  ' + specs[i][0].padStart(5) +
  ' minSpan=' + (v.minSpan() / 86400).toFixed(3) + '天' +
  ' maxSpan=' + (v.maxSpan() / 86400).toFixed(1) + '天' +
  ' 数据跨域=' + ((v.maxT() - v.minT()) / 86400).toFixed(1) + '天'));
