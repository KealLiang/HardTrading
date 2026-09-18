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
    return { min: min - pad, max: max + pad };
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
      ctx.fillStyle = k.c >= k.o ? this.theme.up : this.theme.down;
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

    // 浮动信息条
    var lines = [
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
    this.canvas.addEventListener('dblclick', function () {
      if (!self.klines) return;
      var n = Math.min(self.klines.length, self.options.defaultBars || 160);
      var s = self.klines.length - n;
      self.window = { t0: self.klines[s]._t, t1: self.maxT() };
      if (self.options.onZoom) self.options.onZoom({ reset: n });
      self.draw();
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
