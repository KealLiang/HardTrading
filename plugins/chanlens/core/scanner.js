/* ==========================================================================
 * scanner.js —— 自选股批量缠论信号扫描
 *
 * 设计目标只有一个字：**省**。三层减负——
 *   1) 少取：每只只拉 limit 根（默认 200 根日线），远少于看图用的 800 根
 *   2) 增量：单个标的 freshMs（默认 30 分钟）内跳过，除非 force
 *   3) 持久化：结果写 storage，重开页面零请求直接显示上次结果
 * 另加并发控制 + 逐个回调，出结果就渲染，不等全部跑完。
 *
 * 依赖注入（fetcher / analyze），不碰 chrome.* 之外的任何东西，Node 里也能单测。
 * ========================================================================== */
'use strict';

(function (g) {
  'use strict';

  var KEY = 'chanlens.scan.v1';

  /** 缓存键：按周期分桶（'daily|600519'），切周期互不覆盖 */
  function keyOf(period, code) { return period + '|' + code; }

  function store() {
    try {
      return (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local)
        ? chrome.storage.local : null;
    } catch (e) { return null; }
  }

  /** @returns {Promise<{meta:{}, items:{}}>} */
  function load() {
    var s = store();
    if (!s) return Promise.resolve({ meta: {}, items: {} });
    return new Promise(function (resolve) {
      s.get(KEY, function (box) {
        var v = box && box[KEY];
        var data = (v && typeof v === 'object')
          ? { meta: v.meta || {}, items: v.items || {} }
          : { meta: {}, items: {} };
        migrate(data);
        resolve(data);
      });
    });
  }

  /** 旧版单层 code 键 → 按 item.period 迁入分桶键（只跑一次） */
  function migrate(data) {
    var moved = false;
    Object.keys(data.items).forEach(function (k) {
      if (k.indexOf('|') >= 0) return;
      var it = data.items[k];
      var p = it && it.period;
      if (p) { data.items[keyOf(p, k)] = it; delete data.items[k]; moved = true; }
      else { delete data.items[k]; moved = true; }   // 无法归属的旧数据直接丢
    });
    if (moved) save(data);
  }

  function save(data) {
    var s = store();
    if (!s) return;
    var box = {}; box[KEY] = data;
    try { s.set(box); } catch (e) { /* 忽略 */ }
  }

  function clear() { save({ meta: {}, items: {} }); }

  /** 只取某个周期的缓存：{[code]: sig}，供启动时零请求回显 */
  function loadFor(period) {
    return load().then(function (c) {
      var out = {}, items = c.items || {}, pre = period + '|';
      Object.keys(items).forEach(function (k) {
        if (k.indexOf(pre) === 0) out[k.slice(pre.length)] = items[k];
      });
      return out;
    });
  }

  /**
   * 从单只标的的分析结果里挑「正在形成」的那个信号。
   * 判据：信号成立位 readyK 距最后一根 K 的滞后 <= maxLag，取其中最新的一个。
   * readyK 是以前做可得性审计时引入的字段，用它判定可以避免“信号还没成立就画出来”。
   */
  function pickSignal(klines, res, opts) {
    opts = opts || {};
    var pts = (res && res.points) || [];
    if (!pts.length || !klines || !klines.length) return null;
    var maxLag = opts.maxLag == null ? 10 : opts.maxLag;
    var lastK = klines.length - 1, best = null, bestKey = -1;
    pts.forEach(function (p) {
      var rk = (p.readyK == null ? p._k : p.readyK);
      if (rk > lastK || lastK - rk > maxLag) return;   // 太旧 or 数据还没走到
      if (rk > bestKey) { bestKey = rk; best = p; }
    });
    if (!best) return null;
    var k = klines[best._k] || null;
    return {
      level: best.level, type: best.type, note: best.note,
      readyK: best.readyK, markK: best._k, price: best.price,
      confirmed: !!best.confirmed,
      lag: lastK - (best.readyK == null ? best._k : best.readyK),
      t: k ? (k.t || '') : '',
      ratio: (best.extra && best.extra.ratio != null) ? best.extra.ratio : null
    };
  }

  function defaultFetcher() {
    if (g.CLDataSource && g.CLDataSource.getKlines) return g.CLDataSource.getKlines;
    if (g.CLMarket && g.CLMarket.fetchKline) return g.CLMarket.fetchKline;
    return null;
  }

  /**
   * 批量扫描
   * @param codes 6 位代码数组
   * @param opts  {period, limit, adjust, params, concurrency, maxLag, freshMs, force,
   *               fetcher, analyze, onResult(code, sig), onProgress(done, total, skipped)}
   * @returns {Promise<{[code]: object|null}>} 无信号为 null
   */
  function scan(codes, opts) {
    opts = opts || {};
    var period = opts.period || 'daily';
    var limit = opts.limit || 200;
    var adjust = opts.adjust == null ? 1 : opts.adjust;
    var params = opts.params || {};
    var maxLag = opts.maxLag == null ? 10 : opts.maxLag;
    var freshMs = opts.freshMs == null ? 30 * 60 * 1000 : opts.freshMs;
    var conc = Math.max(1, opts.concurrency || 3);
    var fetcher = opts.fetcher || defaultFetcher();
    var analyze = opts.analyze || (g.ChanEngine && g.ChanEngine.analyze);
    if (!fetcher) return Promise.reject(new Error('没有可用的取数器'));
    if (!analyze) return Promise.reject(new Error('没有可用的缠论引擎'));

    return load().then(function (cached) {
      var items = cached.items || {};
      var now = Date.now();
      var list = (codes || []).map(String).filter(function (c) { return /^\d{6}$/.test(c); });
      var todo = opts.force ? list.slice() : list.filter(function (c) {
        var it = items[keyOf(period, c)];
        return !it || !it.ts || (now - it.ts) > freshMs;
      });
      var skipped = list.length - todo.length;
      opts.onProgress && opts.onProgress(0, todo.length, skipped);

      var idx = 0, done = 0;
      function worker() {
        if (idx >= todo.length) return Promise.resolve();
        var code = todo[idx++];
        return Promise.resolve()
          .then(function () { return fetcher(code, period, limit, adjust); })
          .then(function (data) {
            var klines = (data && data.klines) || [];
            var res = analyze(klines, params);
            var sig = pickSignal(klines, res, { maxLag: maxLag });
            if (sig) { sig.ts = Date.now(); sig.period = period; sig.limit = limit; }
            items[keyOf(period, code)] = sig || { none: true, ts: Date.now(), period: period };   // none=扫过且无信号，占位让 freshMs 生效
            opts.onResult && opts.onResult(code, items[keyOf(period, code)]);
          })
          .catch(function () {
            items[keyOf(period, code)] = items[keyOf(period, code)] || null;   // 失败保留旧值，下次还能扫
            opts.onResult && opts.onResult(code, items[keyOf(period, code)]);
          })
          .then(function () {
            done++;
            opts.onProgress && opts.onProgress(done, todo.length, skipped);
            return worker();
          });
      }

      var pool = [];
      for (var i = 0; i < conc; i++) pool.push(worker());
      return Promise.all(pool).then(function () {
        var out = {};
        list.forEach(function (c) { out[c] = items[keyOf(period, c)] || null; });
        save({ meta: { at: now, period: period, limit: limit, adjust: adjust, maxLag: maxLag }, items: items });
        return out;
      });
    });
  }

  g.CLScanner = {
    KEY: KEY, load: load, loadFor: loadFor, save: save, clear: clear,
    scan: scan, pickSignal: pickSignal
  };
})(typeof self !== 'undefined' ? self : this);
