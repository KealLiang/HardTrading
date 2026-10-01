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
   * 某类买卖点自己的失效基准（全部取自已定型结构）：
   *   一类 = 买卖点自身价（一买低点 / 一卖高点）
   *   二类 = 它引用的那个一类极值（二买 → 一买低点；二卖 → 一卖高点，都记在 extra.b1）
   *   三类 = 中枢边（买 → 跌回中枢 ZG；卖 → 升回中枢 ZD）
   * 买/卖各取各的结构：一买低点和一卖高点本来就是两个不同的价位。
   */
  function anchorOf(p) {
    var ex = p.extra || {};
    if (p.level === 1) return p.price;
    if (p.level === 2) return (ex.b1 != null ? ex.b1 : p.price);
    return p.type > 0 ? (ex.zsZG != null ? ex.zsZG : null)
                      : (ex.zsZD != null ? ex.zsZD : null);
  }

  /** 取指定方向上最近的一个点（_k 最大）；没有就是 null */
  function lastPointOf(pts, type) {
    var best = null;
    pts.forEach(function (p) {
      if (type > 0 ? !(p.type > 0) : !(p.type < 0)) return;
      if (!best || p._k > best._k) best = p;
    });
    return best;
  }

  /**
   * 按方向算「动盈 + 目标」的参照（1.8.0，从 pickSignal 里抽出来）。
   * 跟踪中的标的要**持续**推进这两条线，而 pickSignal 挑的是「当前最佳信号」——
   * 行情走好后日线会转出反向信号（多头持仓后出现顶背驰），pickSignal 一换靶子，
   * 跟踪线就冻结了。所以推进必须走本函数：只认方向，不认信号。
   *   多头 trailLow  = max{ 回调笔低点 | 低点 > 入场 }   —— 只上移（回撤时取 max 不动）
   *   多头 targetHigh = 最近一根已完成向下笔的高点（= 最近前高）；已收在其上 → null
   *                    （前高被突破，上方没有结构参照，目标就该消失而不是挂在远处）
   *   空头对称。entry 缺省取最新收盘；**entry 只过滤动盈**（建卡后传 rec.entry 固定值），
   *   目标的突破判定永远用最新收盘。全部来自已定型笔，无未来函数。
   */
  function refsFor(klines, res, dir, entry, markK) {
    var ks = klines || [];
    if (!ks.length) return { trailLow: null, trailHigh: null, targetHigh: null, targetLow: null };
    if (entry == null) entry = ks[ks.length - 1].c;
    var last = ks[ks.length - 1].c;                  // 目标是否被突破按**现价**判
    var long = dir > 0;
    var trailLow = null, trailHigh = null;
    var bis = (res && res.bis) || [];
    for (var i = 0; i < bis.length; i++) {
      var b = bis[i];
      /* markK（信号标记位）之后才形成的反向笔才作数 —— 买点前的高位回撤笔
         低点也可能高于入场价，但那是几个月前的结构，不是本单的跟踪位 */
      var after = (markK == null || (b.startK != null && b.startK >= markK));
      if (b.dir < 0 && after && b.low > entry) trailLow = (trailLow == null) ? b.low : Math.max(trailLow, b.low);
      if (b.dir > 0 && after && b.high < entry) trailHigh = (trailHigh == null) ? b.high : Math.min(trailHigh, b.high);
    }
    var targetHigh = null, targetLow = null;
    for (var j = bis.length - 1; j >= 0; j--) {              // 从最新往回找第一根反向已完成笔
      var bb = bis[j];
      if (long && bb.dir < 0) {
        if (last < bb.high) targetHigh = bb.high;            // 已收在其上 → 上方无参照
        break;
      }
      if (!long && bb.dir > 0) {
        if (last > bb.low) targetLow = bb.low;
        break;
      }
    }
    return { trailLow: trailLow, trailHigh: trailHigh, targetHigh: targetHigh, targetLow: targetLow };
  }

  /**
   * 从单只标的的分析结果里挑「正在形成」的那个信号。
   * 判据：信号成立位 readyK 距最后一根 K 的滞后 <= maxLag，取其中最新的一个。
   * readyK 是以前做可得性审计时引入的字段，用它判定可以避免“信号还没成立就画出来”。
   * 同时组装 refs（作战卡用）：两类失效位 + 目标位 + 动盈 + 最新收盘 —— 全部来自
   * 已定型结构，无未来函数。
   *   stopBuy  做多失效位：跌破即错 —— 最近一个「买点」的失效基准
   *   stopSell 做空失效位：升破即错 —— 最近一个「卖点」的失效基准
   *   trailLow/trailHigh 动盈（移动止盈）：信号**之后**才形成的反向笔里，
   *       优于入场价的那个极值 —— 多头取 max（只上移不下移）、空头取 min。
   *       信号刚出时通常还没有 → null（那时它贴着失效位甚至更低，画出来只会误导）
   *   targetHigh/targetLow 目标位：上方（下方）最近的已完成笔极值，须在有利方向
   *       上（多头在现价之上、空头在现价之下）；已创新高/新低时 null
   *
   * 1.7.0 修正：1.6.0 把一/二类的 stopBuy 与 stopSell 写成同一个数字（都取
   * 当前这一个信号的引用极值），于是「看多/看空」给出的是同一张图 —— 那既不符
   * 合缠论（买点锚一买低点、卖点锚一卖高点，本就是两个结构），也让两个方向按钮
   * 失去意义。现在多空各按自己的结构取，取不到就是 null（不编造数字）。
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

    /* —— 失效位：多空各按自己的结构求（1.7.0）—— */
    var pBuy = lastPointOf(pts, 1), pSell = lastPointOf(pts, -1);
    var stopBuy = pBuy ? anchorOf(pBuy) : null;
    var stopSell = pSell ? anchorOf(pSell) : null;

    /* —— 动盈 + 目标（1.8.0 起走 refsFor：与跟踪推进同一套算法，口径不漂移）—— */
    var entry = klines[lastK].c;
    var rr = refsFor(klines, res, best.type > 0 ? 1 : -1, entry, best._k);

    return {
      level: best.level, type: best.type, note: best.note,
      readyK: best.readyK, markK: best._k, price: best.price,
      confirmed: !!best.confirmed,
      lag: lastK - (best.readyK == null ? best._k : best.readyK),
      t: k ? (k.t || '') : '',
      ratio: (best.extra && best.extra.ratio != null) ? best.extra.ratio : null,
      refs: {
        stopBuy: stopBuy != null ? stopBuy : null,
        stopSell: stopSell != null ? stopSell : null,
        trailLow: rr.trailLow, trailHigh: rr.trailHigh,
        targetHigh: rr.targetHigh, targetLow: rr.targetLow,
        lastClose: entry,
        /* 方向来自信号本身（买点=多、卖点=空）。1.7.0 起不再让用户反着选，
           但把方向记下来，作战卡/徽标/盯梢都读它 */
        dir: best.type > 0 ? 1 : -1
      }
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
    scan: scan, pickSignal: pickSignal, refsFor: refsFor,
    anchorOf: anchorOf, lastPointOf: lastPointOf   // 供单测/调试直接验证失效位规则
  };
})(typeof self !== 'undefined' ? self : this);
