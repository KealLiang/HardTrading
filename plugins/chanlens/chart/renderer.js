/* ==========================================================================
 * renderer.js —— K 线 + 缠论结构叠层渲染器
 *
 * 坐标完全由我们自己算：
 *   x ← 由「可见时间窗口」换算出的 K 线索引
 *   y ← 由「可见价格极值」线性映射到画布高度
 * 所以不存在「和原图对不上」这个问题——这正是自绘相比覆盖层方案的核心价值。
 *
 * 多级别联动靠共享同一个时间窗口 t0..t1 实现：不同周期的图表按时间对齐，
 * 各自落互不干扰的索引区间，视觉上自动对齐。
 * ========================================================================== */
'use strict';

(function (global) {
  'use strict';

  var THEME = {
    bg: '#ffffff',
    grid: '#eeeeee',
    axis: '#cccccc',
    text: '#555555',
    textStrong: '#222222',
    up: '#d94a4a',          // 中国习惯：涨红
    down: '#2f9e57',        // 跌绿
    upFill: 'rgba(217,74,74,0.16)',
    downFill: 'rgba(47,158,87,0.16)',
    fx: '#8a6d3b',
    bi: '#2b6cb0',
    seg: '#7d4bbd',
    zsFill: 'rgba(214,158,46,0.14)',
    zsLine: '#c8901a',
    div: '#e8590c',
    buy: '#d6336c',
    sell: '#087f5b',
    pending: 'rgba(0,0,0,0.45)'
  };

  function ChartView(canvas, options) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.options = options || {};
    this.theme = Object.assign({}, THEME, this.options.theme || {});
    this.layers = Object.assign({
      fractal: true, bi: true, seg: true, zhongshu: true,
      divergence: true, points: true, macd: true, volume: true
    }, this.options.layers || {});
    this.data = null;
    this.result = null;
    this.window = null;          // {t0, t1}
    this.padding = { left: 8, right: 66, top: 10, bottom: 22 };
    this.cross = null;
    this._barW = 6;
    this.bindEvents();
  }

  /* ------------------------------------------------------------ 数据装载 */
  ChartView.prototype.setData = function (payload) {
    this.data = payload;                     // {klines, name, code, period}
    this.result = payload.result;            // ChanEngine.analyze 的结果
    this.klines = payload.klines;
    this._mergedBars = !!payload.mergedBars; // 缠论K线：简洁区间柱画法
    if (!this.window && this.klines.length) {
      var defaultBars = Math.min(this.klines.length, this.options.defaultBars || 160);
      var s = this.klines.length - defaultBars;
      this.window = { t0: this.klines[s]._t, t1: this.klines[this.klines.length - 1]._t + 1 };
    }
    return this;
  };

  ChartView.prototype.setLayers = function (layers) {
    Object.assign(this.layers, layers);
    return this;
  };

  ChartView.prototype.setWindow = function (w) {
    if (!w) return this;
    var t0 = Math.max(this.minT(), w.t0);
    var t1 = Math.min(this.maxT(), w.t1);
    this.window = { t0: t0, t1: t1 };
    this.clampWindow();
    return this;
  };

  ChartView.prototype.minT = function () { return this.klines && this.klines.length ? this.klines[0]._t : 0; };
  ChartView.prototype.maxT = function () {
    return this.klines && this.klines.length ? this.klines[this.klines.length - 1]._t + 1 : 1;
  };

  /* ------------------------------------------------------- 索引 / 坐标换算 */
  ChartView.prototype.indexRange = function () {
    var ks = this.klines;
    var lo = lowerBound(ks, this.window.t0, function (k) { return k._t; });
    var hi = lowerBound(ks, this.window.t1, function (k) { return k._t; });
    var i0 = Math.max(0, lo - 1);
    var i1 = Math.max(i0, Math.min(ks.length - 1, hi));
    if (i1 - i0 < 2) { i1 = Math.min(ks.length - 1, i0 + 2); i0 = Math.max(0, i1 - 2); }
    return { i0: i0, i1: i1 };
  };

  function lowerBound(arr, target, key) {
    var lo = 0, hi = arr.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (key(arr[mid]) < target) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  ChartView.prototype.layout = function () {
    var w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    var pad = this.padding;
    var innerH = h - pad.top - pad.bottom;
    var volH = this.layers.volume ? Math.round(innerH * 0.16) : 0;
    var macdH = this.layers.macd ? Math.round(innerH * 0.18) : 0;
    var priceH = innerH - volH - macdH;
    return {
      w: w, h: h, pad: pad,
      left: pad.left, right: w - pad.right,
      priceTop: pad.top, priceBottom: pad.top + priceH,
      volTop: pad.top + priceH + 6, volBottom: pad.top + priceH + 6 + volH,
      macdTop: pad.top + priceH + 6 + volH + 4, macdBottom: pad.top + priceH + 6 + volH + 4 + macdH
    };
  };

  /** K 线索引 → x 像素中心 */
  ChartView.prototype.x = function (idx) {
    var r = this._range;
    if (!r) return 0;
    var L = this.layout();
    var span = Math.max(1, r.i1 - r.i0 + 1);
    var step = (L.right - L.left) / span;
    return L.left + (idx - r.i0 + 0.5) * step;
  };

  ChartView.prototype.priceY = function (p) {
    var L = this.layout();
    var pr = this._price;
    if (!pr) return 0;
    return L.priceBottom - (p - pr.min) / (pr.max - pr.min || 1) * (L.priceBottom - L.priceTop);
  };

  ChartView.prototype.yPrice = function (y) {
    var L = this.layout(), pr = this._price;
    return pr.min + (L.priceBottom - y) / (L.priceBottom - L.priceTop) * (pr.max - pr.min);
  };

  ChartView.prototype.indexAt = function (px) {
    var r = this._range, L = this.layout();
    if (!r) return 0;
    var span = Math.max(1, r.i1 - r.i0 + 1);
    var step = (L.right - L.left) / span;
    var idx = Math.round(r.i0 + (px - L.left) / step - 0.5);
    return Math.max(0, Math.min(this.klines.length - 1, idx));
  };

  /* ---------------------------------------------------------------- 绘制 */
  ChartView.prototype.draw = function () {
    if (!this.klines || !this.klines.length) return this;
    var dpr = global.devicePixelRatio || 1;
    var w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    var ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    this._range = this.indexRange();
    this._price = this.priceRange();
    this._barW = Math.max(1, Math.min(14, (this.layout().right - this.layout().left) /
                                          Math.max(1, this._range.i1 - this._range.i0 + 1) * 0.7));

    this.drawBackground();
    this.drawGrid();
    if (this.layers.zhongshu) this.drawZhongshu();
    this.drawKlines();
    if (this.layers.macd) this.drawMacd();
    if (this.layers.volume) this.drawVolume();
    if (this.layers.seg) this.drawSegments();
    if (this.layers.bi) this.drawBis();
    if (this.layers.fractal) this.drawFractals();
    if (this.layers.divergence) this.drawDivergences();
    if (this.layers.points) this.drawPoints();
    if (this.planLines && this.planLines.length) this.drawPlanLines();
    this.drawPriceAxis();
    this.drawTimeAxis();
    this.drawCrosshair();
    return this;
  };

  ChartView.prototype.priceRange = function () {
    var r = this._range, ks = this.klines;
    var min = Infinity, max = -Infinity;
    for (var i = r.i0; i <= r.i1; i++) {
      if (ks[i].l < min) min = ks[i].l;
      if (ks[i].h > max) max = ks[i].h;
    }
    if (!isFinite(min)) { min = 0; max = 1; }
    var pad = (max - min) * 0.08 || 1;
    min -= pad; max += pad;
    /* 追踪模式的价位线（失效/止盈）通常就在价格附近，纳入量程才能看见；
       但只最多把量程向外扩 25%，防止远端历史价位把图压扁 */
    var lines = this.planLines || [];
    for (var j = 0; j < lines.length; j++) {
      var p = lines[j] && lines[j].price;
      if (p == null || !isFinite(p)) continue;
      var span = max - min;
      if (p < min && p > min - span * 0.25) min = p;
      if (p > max && p < max + span * 0.25) max = p;
    }
    return { min: min, max: max };
  };

  ChartView.prototype.drawBackground = function () {
    var ctx = this.ctx, L = this.layout();
    ctx.fillStyle = this.theme.bg;
    ctx.fillRect(0, 0, L.w, L.h);
  };

  ChartView.prototype.drawGrid = function () {
    var ctx = this.ctx, L = this.layout(), pr = this._price;
    ctx.strokeStyle = this.theme.grid;
    ctx.lineWidth = 1;
    ctx.font = '11px system-ui, "Microsoft YaHei", sans-serif';
    ctx.fillStyle = this.theme.text;
    for (var i = 0; i <= 4; i++) {
      var y = L.priceTop + (L.priceBottom - L.priceTop) * i / 4;
      ctx.beginPath();
      ctx.moveTo(L.left, y); ctx.lineTo(L.right, y);
      ctx.stroke();
      var val = pr.max - (pr.max - pr.min) * i / 4;
      ctx.textAlign = 'left';
      ctx.fillText(fmtPrice(val), L.right + 6, y + 4);
    }
    ctx.strokeStyle = this.theme.axis;
    ctx.beginPath();
    ctx.moveTo(L.right, L.priceTop); ctx.lineTo(L.right, L.priceBottom);
    ctx.stroke();
  };

  ChartView.prototype.drawKlines = function () {
    var ctx = this.ctx, L = this.layout(), r = this._range, ks = this.klines;
    var bw = this._barW;
    /* 缠论 K 线（mergedBars）：只画高低点区间的简洁柱——无开收盘、无影线、无红绿，
       因为合并后的开收盘是拼凑的，唯一有意义的信息就是 [low, high] 区间 */
    if (this._mergedBars) {
      for (var m = r.i0; m <= r.i1; m++) {
        var km = ks[m];
        var ytm = this.priceY(km.h), ybm = this.priceY(km.l);
        ctx.fillStyle = 'rgba(100,130,170,0.28)';
        ctx.strokeStyle = '#7a93b5';
        var w = Math.max(1, bw);
        ctx.fillRect(this.x(m) - w / 2, ytm, w, Math.max(1, ybm - ytm));
        ctx.lineWidth = 1;
        ctx.strokeRect(this.x(m) - w / 2, ytm, w, Math.max(1, ybm - ytm));
      }
      return;
    }
    for (var i = r.i0; i <= r.i1; i++) {
      var k = ks[i];
      var up = k.c >= k.o;
      var x = this.x(i);
      var color = up ? this.theme.up : this.theme.down;
      var fill = up ? this.theme.upFill : this.theme.downFill;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      var yh = this.priceY(k.h), yl = this.priceY(k.l);
      ctx.beginPath();
      ctx.moveTo(x, yh); ctx.lineTo(x, yl);
      ctx.lineWidth = 1;
      ctx.stroke();
      var yo = this.priceY(k.o), yc = this.priceY(k.c);
      var top = Math.min(yo, yc), bodyH = Math.max(1, Math.abs(yc - yo));
      if (bw <= 2) {
        ctx.beginPath(); ctx.moveTo(x, Math.min(yo, yc)); ctx.lineTo(x, Math.max(yo, yc)); ctx.stroke();
      } else {
        ctx.fillStyle = fill;
        ctx.fillRect(x - bw / 2, top, bw, bodyH);
        ctx.strokeStyle = color;
        ctx.strokeRect(x - bw / 2, top, bw, bodyH);
      }
    }
  };

  ChartView.prototype.drawVolume = function () {
    var ctx = this.ctx, L = this.layout(), r = this._range, ks = this.klines;
    var maxV = 0;
    for (var i = r.i0; i <= r.i1; i++) if (ks[i].v > maxV) maxV = ks[i].v;
    if (!maxV) return;
    var bw = this._barW;
    for (var j = r.i0; j <= r.i1; j++) {
      var k = ks[j];
      var hh = (L.volBottom - L.volTop) * (k.v / maxV);
      /* 缠论 K 线下开收盘无意义，量柱统一中性色 */
      ctx.fillStyle = this._mergedBars ? 'rgba(100,130,170,0.45)'
                                       : (k.c >= k.o ? this.theme.up : this.theme.down);
      ctx.fillRect(this.x(j) - bw / 2, L.volBottom - hh, Math.max(1, bw), hh);
    }
    ctx.strokeStyle = this.theme.grid;
    ctx.beginPath(); ctx.moveTo(L.left, L.volTop); ctx.lineTo(L.right, L.volTop); ctx.stroke();
  };

  ChartView.prototype.drawMacd = function () {
    var res = this.result, ctx = this.ctx, L = this.layout(), r = this._range;
    if (!res || !res.macd) return;
    var hist = res.macd.hist, dif = res.macd.dif, dea = res.macd.dea;
    var max = 0;
    for (var i = r.i0; i <= r.i1; i++) {
      max = Math.max(max, Math.abs(hist[i] || 0), Math.abs(dif[i] || 0), Math.abs(dea[i] || 0));
    }
    if (!max) return;
    var mid = (L.macdTop + L.macdBottom) / 2;
    var half = (L.macdBottom - L.macdTop) / 2 - 1;
    var bw = Math.max(1, this._barW * 0.7);
    for (var j = r.i0; j <= r.i1; j++) {
      var v = hist[j] || 0;
      var hh = Math.abs(v) / max * half;
      ctx.fillStyle = v >= 0 ? this.theme.up : this.theme.down;
      ctx.fillRect(this.x(j) - bw / 2, v >= 0 ? mid - hh : mid, bw, hh);
    }
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#f08c00';
    drawLine(ctx, dif, r, this, mid, half, max);
    ctx.strokeStyle = '#1971c2';
    drawLine(ctx, dea, r, this, mid, half, max);
    ctx.strokeStyle = this.theme.grid;
    ctx.beginPath(); ctx.moveTo(L.left, mid); ctx.lineTo(L.right, mid); ctx.stroke();
  };

  function drawLine(ctx, arr, r, view, mid, half, max) {
    ctx.beginPath();
    var first = true;
    for (var i = r.i0; i <= r.i1; i++) {
      var y = mid - (arr[i] || 0) / max * half;
      if (first) { ctx.moveTo(view.x(i), y); first = false; } else ctx.lineTo(view.x(i), y);
    }
    ctx.stroke();
  }

  /* ------------------------------------------------------------ 缠论图层 */
  ChartView.prototype.drawFractals = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    ctx.fillStyle = this.theme.fx;
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    res.fractals.forEach(function (f) {
      if (f._k < this._range.i0 - 1 || f._k > this._range.i1 + 1) return;
      var x = this.x(f._k);
      var y = this.priceY(f.type > 0 ? f.high : f.low);
      ctx.beginPath();
      if (f.type > 0) { ctx.moveTo(x, y + 4); ctx.lineTo(x - 4, y + 11); ctx.lineTo(x + 4, y + 11); }
      else { ctx.moveTo(x, y - 4); ctx.lineTo(x - 4, y - 11); ctx.lineTo(x + 4, y - 11); }
      ctx.closePath();
      ctx.fill();
    }, this);
  };

  ChartView.prototype.drawBis = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    res.bis.forEach(function (b) {
      var x1 = this.x(b.startK), x2 = this.x(b.endK);
      var y1 = this.priceY(b.startPrice), y2 = this.priceY(b.endPrice);
      ctx.save();
      ctx.strokeStyle = this.theme.bi;
      ctx.lineWidth = 1.4;
      if (!b.confirmed) { ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.75; }
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.restore();
    }, this);
  };

  ChartView.prototype.drawSegments = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    res.segs.forEach(function (s) {
      var x1 = this.x(s.startK), x2 = this.x(s.endK);
      var y1 = this.priceY(s.startPrice), y2 = this.priceY(s.endPrice);
      ctx.save();
      ctx.strokeStyle = this.theme.seg;
      ctx.lineWidth = 3.2;
      ctx.globalAlpha = 0.55;
      if (!s.confirmed) ctx.setLineDash([7, 4]);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      ctx.restore();
    }, this);
  };

  ChartView.prototype.drawZhongshu = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    res.zhongshus.forEach(function (z, idx) {
      if (z.endK < this._range.i0 || z.startK > this._range.i1) return;
      var x1 = this.x(Math.max(z.startK, this._range.i0));
      var x2 = this.x(Math.min(z.endK, this._range.i1));
      var yTop = this.priceY(z.ZG), yBot = this.priceY(z.ZD);
      ctx.fillStyle = this.theme.zsFill;
      ctx.fillRect(x1, yTop, Math.max(2, x2 - x1), Math.max(1, yBot - yTop));
      ctx.save();
      ctx.strokeStyle = this.theme.zsLine;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(x1, yTop, Math.max(2, x2 - x1), Math.max(1, yBot - yTop));
      ctx.restore();
      if (x2 - x1 > 46) {
        ctx.fillStyle = '#a16207';
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Z' + idx + ' ' + fmtPrice(z.ZD) + '~' + fmtPrice(z.ZG), x1 + 3, yTop + 11);
      }
    }, this);
  };

  ChartView.prototype.drawDivergences = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    res.divergences.forEach(function (d) {
      if (d.targetK < this._range.i0 - 1 || d.targetK > this._range.i1 + 1) return;
      var x = this.x(d.targetK);
      var y = this.priceY(d.targetPrice);
      ctx.save();
      ctx.strokeStyle = this.theme.div;
      ctx.setLineDash([2, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x, this.layout().macdBottom);
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = this.theme.div;
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText((d.kind === 'top' ? '顶背驰' : '底背驰') + ' ' + d.ratio.toFixed(2),
                   x, d.kind === 'top' ? y - 8 : y + 14);
    }, this);
  };

  ChartView.prototype.drawPoints = function () {
    var res = this.result, ctx = this.ctx;
    if (!res) return;
    var labels = { 1: '一', 2: '二', 3: '三' };
    res.points.forEach(function (p) {
      if (p._k < this._range.i0 - 1 || p._k > this._range.i1 + 1) return;
      var x = this.x(p._k);
      var y = this.priceY(p.price);
      var isBuy = p.type > 0;
      var r = 9;
      var cy = isBuy ? y + r + 12 : y - r - 12;
      // 右侧确认数据还不够的信号画半透明+虚线圈（与笔/线段的虚线同一套语言）
      var pending = !p.confirmed;
      if (pending) ctx.globalAlpha = 0.45;
      ctx.beginPath();
      ctx.arc(x, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = isBuy ? this.theme.buy : this.theme.sell;
      ctx.fill();
      if (pending) {
        ctx.setLineDash([3, 2]);
        ctx.strokeStyle = isBuy ? this.theme.buy : this.theme.sell;
        ctx.beginPath(); ctx.arc(x, cy, r + 2.5, 0, Math.PI * 2); ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText((labels[p.level] || p.level) + (isBuy ? '买' : '卖'), x, cy);
      ctx.textBaseline = 'alphabetic';
      ctx.globalAlpha = 1;
    }, this);
  };

  /* --------------------------------------------------------------- 坐标轴 */
  ChartView.prototype.drawPriceAxis = function () { /* 已在 drawGrid 中绘制 */ };

  /* ------------------------------------------------ 1.6.0 追踪价位线（额外）
   * this.planLines: [{price, color, label}]，由 app.js 按追踪记录注入；
   * this.planNote: 图上短文案（追踪摘要）。跟随「额外」开关显隐。
   *
   * 1.7.0：目标/参考/失效/动盈四条线经常挤在 1% 以内（一买低点和动盈起步常是
   * 同一笔的两端），缩到全览时它们压在同一个像素上、后画的标签把前面的盖掉，
   * 看上去就只剩一条线。这里做两件事：① 像素级同价的合并成一个标签
   * （「失效/止盈 1450.00」）；② 标签纵向强制错开 15px，各条都读得到。 */
  ChartView.prototype.drawPlanLines = function () {
    var ctx = this.ctx, L = this.layout(), P = this._price;
    var lines = this.planLines || [];
    var vis = [];
    var i, ln;

    /* ① 画虚线本身（各用自己的颜色） */
    for (i = 0; i < lines.length; i++) {
      ln = lines[i];
      if (!ln || ln.price == null || !isFinite(ln.price)) continue;
      if (ln.price < P.min || ln.price > P.max) continue;
      var y = this.priceY(ln.price);
      ctx.save();
      ctx.strokeStyle = ln.color || '#2b6cb0';
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(L.left, y);
      ctx.lineTo(L.right, y);
      ctx.stroke();
      ctx.restore();
      vis.push({ y: y, label: ln.label || '', price: ln.price, color: ln.color || '#2b6cb0' });
    }

    /* ② 标签：按 y 排序，几乎同价的合并，剩下的纵向错开 */
    vis.sort(function (a, b) { return a.y - b.y; });
    var groups = [];
    for (i = 0; i < vis.length; i++) {
      var last = groups[groups.length - 1];
      if (last && Math.abs(vis[i].y - last.y) < 3) {
        if (vis[i].label && last.labels.indexOf(vis[i].label) < 0) last.labels.push(vis[i].label);
        continue;
      }
      groups.push({ y: vis[i].y, price: vis[i].price, color: vis[i].color,
                    labels: vis[i].label ? [vis[i].label] : [] });
    }

    var lastBottom = -1e9;
    for (i = 0; i < groups.length; i++) {
      var gp = groups[i];
      var text = (gp.labels.length ? gp.labels.join('/') + ' ' : '') + gp.price;
      var by = gp.y - 16;
      if (by < L.priceTop + 2) by = gp.y + 4;
      if (by < lastBottom) by = lastBottom;        // 与上一个标签不重叠
      lastBottom = by + 15;
      ctx.save();
      // 右端标签：底色块 + 白字。textAlign 必须显式设置 —— 前面的时间轴把
      // 'center' 留在上下文里，长文本会以中点定位、头部画出画布外
      ctx.setLineDash([]);
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      var tw = ctx.measureText(text).width;
      // 标签放左端：右端是最新的那几根 K 线，标签压上去会挡住最该看的地方
      var bx = L.left + 6;
      ctx.globalAlpha = 0.92;
      ctx.fillStyle = gp.color;
      ctx.fillRect(bx - 4, by, tw + 8, 15);
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#fff';
      ctx.fillText(text, bx, by + 11);
      ctx.restore();
    }
    /* 追踪摘要（1.8.1 起两行）：planNote = 方向·级别·信号·参考价；
       planNote2 = 动态状态行（30 分时机 / 动盈启动与否），由 app.js 注入。
       整块区域记进 _noteRect，点击（鼠标 click / 触摸 tap）直接开作战卡 ——
       免去长按列表项找菜单。跟随「额外」开关显隐。 */
    this._noteRect = null;
    var notes = [];
    if (this.planNote) notes.push(this.planNote);
    if (this.planNote2) notes.push(this.planNote2);
    if (notes.length) {
      ctx.save();
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      var nx = L.left + 6, ny = L.priceTop + 6, maxW = 0;
      for (var ni = 0; ni < notes.length; ni++) {
        ctx.font = ni === 0 ? '11px sans-serif' : '10px sans-serif';
        var tw2 = ctx.measureText(notes[ni]).width;
        if (tw2 > maxW) maxW = tw2;
        var bh = ni === 0 ? 18 : 16;
        ctx.globalAlpha = ni === 0 ? 0.82 : 0.68;
        ctx.fillStyle = '#2b3a4a';
        ctx.fillRect(nx, ny, tw2 + 12, bh);
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#fff';
        ctx.fillText(notes[ni], nx + 6, ny + (ni === 0 ? 13 : 12));
        ny += bh + 2;
      }
      this._noteRect = { x: L.left + 6, y: L.priceTop + 6,
                         w: maxW + 12, h: ny - (L.priceTop + 6) - 2 };
      ctx.restore();
    }
  };


  ChartView.prototype.drawTimeAxis = function () {
    var ctx = this.ctx, L = this.layout(), r = this._range, ks = this.klines;
    ctx.fillStyle = this.theme.text;
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    var count = Math.max(2, Math.floor((L.right - L.left) / 90));
    for (var i = 0; i <= count; i++) {
      var idx = Math.round(r.i0 + (r.i1 - r.i0) * i / count);
      if (idx < 0 || idx >= ks.length) continue;
      ctx.fillText(fmtTime(ks[idx].t, this.data.period), this.x(idx), L.h - 6);
    }
  };

  ChartView.prototype.drawCrosshair = function () {
    if (!this.cross) return;
    var ctx = this.ctx, L = this.layout();
    var idx = this.indexAt(this.cross.x);
    var k = this.klines[idx];
    ctx.save();
    ctx.strokeStyle = 'rgba(60,60,60,0.45)';
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    var x = this.x(idx);
    ctx.beginPath(); ctx.moveTo(x, L.priceTop); ctx.lineTo(x, L.priceBottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(L.left, this.cross.y); ctx.lineTo(L.right, this.cross.y); ctx.stroke();
    ctx.restore();

    // 横线的纵坐标读数：直接贴在右侧价格轴上（盖住被指到的那格刻度）。
    // 信息条给的是「那根 K 线」的开高低收，而手指的 y 未必落在 K 线实体上，
    // 所以要单独把这个价位标出来 —— 用户看的就是「我指的这个高度值多少钱」。
    ctx.font = '11px system-ui, "Microsoft YaHei", sans-serif';
    var pTag = fmtPrice(this.yPrice(this.cross.y));
    var pTagW = Math.min(this.padding.right - 4, ctx.measureText(pTag).width + 8);
    var pTagY = Math.min(L.priceBottom - 15, Math.max(L.priceTop, this.cross.y - 7.5));
    ctx.fillStyle = '#2b6cb0';
    ctx.fillRect(L.right + 2, pTagY, pTagW, 15);
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'left';
    ctx.fillText(pTag, L.right + 6, pTagY + 11.5);

    // 浮动信息条
    var lines = this._mergedBars ? [
      fmtTime(k.t, this.data.period),
      '缠论K线  区间 ' + fmtPrice(k.l) + ' ~ ' + fmtPrice(k.h),
      '量 ' + fmtVol(k.v) + (k._n > 1 ? '  （合并 ' + k._n + ' 根原始K）' : '')
    ] : [
      fmtTime(k.t, this.data.period),
      '开 ' + fmtPrice(k.o) + '  高 ' + fmtPrice(k.h),
      '低 ' + fmtPrice(k.l) + '  收 ' + fmtPrice(k.c),
      '量 ' + fmtVol(k.v) + '  幅 ' + (k.pct != null ? k.pct.toFixed(2) : '-') + '%'
    ];
    ctx.font = '11px system-ui, "Microsoft YaHei", sans-serif';
    var wBox = 0;
    lines.forEach(function (s) { wBox = Math.max(wBox, ctx.measureText(s).width); });
    wBox += 14;
    var hBox = lines.length * 15 + 8;
    var bx = Math.min(L.right - wBox, Math.max(L.left, x + 12));
    var by = Math.min(L.priceBottom - hBox, Math.max(L.priceTop, this.cross.y - hBox / 2));
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    ctx.strokeStyle = 'rgba(0,0,0,0.15)';
    ctx.fillRect(bx, by, wBox, hBox);
    ctx.strokeRect(bx, by, wBox, hBox);
    ctx.fillStyle = this.theme.textStrong;
    ctx.textAlign = 'left';
    lines.forEach(function (s, i) { ctx.fillText(s, bx + 7, by + 18 + i * 15); });
  };

  /* ------------------------------------------------------------- 交互事件 */
  ChartView.prototype.bindEvents = function () {
    var self = this;
    var dragging = false, lastX = 0;
    var downX = 0, downY = 0;      // mousedown 落点：区分「点击」和「拖拽松手」

    this.canvas.addEventListener('wheel', function (e) {
      if (!self.klines) return;
      e.preventDefault();
      var L = self.layout();
      var factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      var pxRatio = Math.max(0, Math.min(1, (e.offsetX - L.left) / (L.right - L.left)));
      if (self.options.onZoom) {
        // 由外层统一驱动所有图，按各自当前跨度同比缩放（避免绝对窗口广播造成跳变）
        self.options.onZoom({ factor: factor, pxRatio: pxRatio });
      } else {
        self.zoomBy(factor, pxRatio);
        self.draw();
      }
    }, { passive: false });

    this.canvas.addEventListener('mousedown', function (e) {
      dragging = true; lastX = e.offsetX;
      downX = e.offsetX; downY = e.offsetY;
      self.canvas.style.cursor = 'grabbing';
    });
    this.canvas.addEventListener('mousemove', function (e) {
      self.cross = { x: e.offsetX, y: e.offsetY };
      if (dragging) {
        var L2 = self.layout();
        var dFrac = (e.offsetX - lastX) / Math.max(1, L2.right - L2.left);
        lastX = e.offsetX;
        if (self.options.onPan) {
          self.options.onPan({ dFrac: dFrac });       // 相对位移，各图按自身跨度平移
        } else {
          self.panBy(dFrac);
        }
      }
      // 悬停在左上角摘要上给个「可点」的暗示
      var nr = self._noteRect;
      var overNote = nr && e.offsetX >= nr.x && e.offsetX <= nr.x + nr.w &&
                     e.offsetY >= nr.y && e.offsetY <= nr.y + nr.h;
      self.canvas.style.cursor = dragging ? 'grabbing' : (overNote ? 'pointer' : 'crosshair');
      self.draw();
    });
    this.canvas.addEventListener('mouseleave', function () {
      self.cross = null; dragging = false;
      self.canvas.style.cursor = 'crosshair';
      self.draw();
    });
    global.addEventListener('mouseup', function () {
      dragging = false;
      self.canvas.style.cursor = 'crosshair';
    });
    /* 点左上角追踪摘要 → 开作战卡（桌面鼠标路径；触摸路径在 mobile/touch.js）。
       click 在拖拽松手时也会触发，用位移阈值排除掉。 */
    this.canvas.addEventListener('click', function (e) {
      var nr = self._noteRect;
      if (!nr || !self.options.onNoteTap) return;
      if (Math.abs(e.offsetX - downX) > 6 || Math.abs(e.offsetY - downY) > 6) return;
      if (e.offsetX >= nr.x && e.offsetX <= nr.x + nr.w &&
          e.offsetY >= nr.y && e.offsetY <= nr.y + nr.h) {
        self.options.onNoteTap();
      }
    });
    this.canvas.style.cursor = 'crosshair';
  };

  /**
   * 按倍数缩放。锚点用「相对位置」表示，因此不同周期/不同数据长度的图
   * 可以同步缩放而不会互相干扰（各图只动自己的跨度，比例一致）。
   * @param factor  >1 缩小（显示更多），<1 放大
   * @param pxRatio 锚点在可视区内的横向比例 0..1
   */
  ChartView.prototype.zoomBy = function (factor, pxRatio) {
    if (!this.klines) return this;
    pxRatio = Math.max(0, Math.min(1, pxRatio == null ? 0.5 : pxRatio));
    var spanBefore = this.window.t1 - this.window.t0;
    var anchorT = this.window.t0 + spanBefore * pxRatio;
    var newSpan = Math.max(this.minSpan(), Math.min(this.maxSpan(), spanBefore * factor));
    this.window.t0 = anchorT - newSpan * pxRatio;
    this.window.t1 = this.window.t0 + newSpan;
    this.clampWindow();
    return this;
  };

  /** 按可视区宽度比例平移；dFrac>0 表示内容右移（窗口左移） */
  ChartView.prototype.panBy = function (dFrac) {
    if (!this.klines) return this;
    var span = this.window.t1 - this.window.t0;
    var dt = dFrac * span;
    this.window.t0 -= dt; this.window.t1 -= dt;
    this.clampWindow();
    return this;
  };

  /** 全览：把整段数据全部显示出来 */
  ChartView.prototype.zoomFull = function () {
    if (!this.klines || !this.klines.length) return this;
    this.window = { t0: this.minT(), t1: this.maxT() };
    this.clampWindow();
    return this;
  };

  /** 复位到默认根数（双击） */
  ChartView.prototype.zoomReset = function (n) {
    if (!this.klines || !this.klines.length) return this;
    n = Math.min(this.klines.length, n || this.options.defaultBars || 160);
    this.window = { t0: this.klines[this.klines.length - n]._t, t1: this.maxT() };
    this.clampWindow();
    return this;
  };

  ChartView.prototype.minSpan = function () {
    if (!this.klines || this.klines.length < 3) return 1;
    return (this.klines[1]._t - this.klines[0]._t) * 12;
  };
  ChartView.prototype.maxSpan = function () { return Math.max(1, this.maxT() - this.minT()); };

  ChartView.prototype.clampWindow = function () {
    var minT = this.minT(), maxT = this.maxT();
    var span = Math.min(this.maxSpan(), Math.max(this.minSpan(), this.window.t1 - this.window.t0));
    if (span > this.maxSpan()) span = this.maxSpan();
    if (this.window.t0 < minT) { this.window.t0 = minT; }
    if (this.window.t1 > maxT) { this.window.t1 = maxT; }
    if (this.window.t1 - this.window.t0 < span) {
      this.window.t1 = Math.min(maxT, this.window.t0 + span);
      this.window.t0 = Math.max(minT, this.window.t1 - span);
    }
  };

  /* --------------------------------------------------------------- 工具函数 */
  function fmtPrice(v) {
    if (v == null || !isFinite(v)) return '-';
    if (Math.abs(v) >= 1000) return v.toFixed(1);
    if (Math.abs(v) >= 100) return v.toFixed(2);
    return v.toFixed(3);
  }
  function fmtVol(v) {
    if (v == null) return '-';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿手';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万手';
    return String(v);
  }
  function fmtTime(t, period) {
    var s = String(t || '');
    var date = s.slice(0, 10);
    if (s.length > 10 && (period === 'daily' || period === 'weekly' || period === 'monthly')) return date;
    return s.length > 10 ? s.slice(5, 16) : s;
  }

  global.CLRenderer = {
    THEME: THEME,
    create: function (canvas, options) { return new ChartView(canvas, options); }
  };
})(typeof window !== 'undefined' ? window : this);
