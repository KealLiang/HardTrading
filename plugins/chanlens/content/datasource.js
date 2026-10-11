/* ==========================================================================
 * datasource.js —— content script 侧的行情获取
 * 实际的网络请求都在 background service worker 里完成（绕开 CORS），
 * 这里只负责发消息、做本地兜底、以及把数据整理成引擎要的格式。
 * ========================================================================== */
'use strict';

(function (global) {
  'use strict';

  var localCache = new Map();
  var LOCAL_TTL = 45 * 1000;
  /* 1.9.9：TTL 按交易时段取（CLMarket.cacheTTLFor）——盘中 45s 防抖；
     非交易时段数据不会变，缓存一直活到下次开盘，来回切股/切周期零请求。
     「重算」会显式清掉整层缓存，不受长 TTL 影响。
     TTL 在**写入时**定死存在条目上（周五 15:10 写的活到下周一 9:15），
     不能在读取时按当下时段算——那样周一开盘后旧数据会被新 TTL 掩护。 */
  function ttlForNow() {
    return (global.CLMarket && global.CLMarket.cacheTTLFor)
      ? global.CLMarket.cacheTTLFor(Date.now(), LOCAL_TTL) : LOCAL_TTL;
  }

  /* 末端兜底的抑制表：code|period -> 上次「别的源也没有」的时间戳。
     节假日/停牌时每次取数都会判定落后，靠它避免反复白发请求。
     追加成功不记（那种情况主源一直落后，每次都得补）；
     clearCache()（长按强制重算）会连它一起清。 */
  var fixGuard = {};
  var FIX_GUARD_MS = 10 * 60 * 1000;
  /* 追加的那根相对当前末根的最大允许跳变：超过就怀疑复权基准/精度对不上，
     宁可不补。25% 放得下 20cm 涨停，但拦得住除权级别的断层。 */
  var FIX_JUMP_MAX = 0.25;

  /**
   * MV3 中 background 的 sendResponse 回包通过 sendMessage 的 Promise 返回，
   * 不是一条新的广播消息。这里同时兼容 Promise 与 callback 两种 API 形态。
   */
  function ask(msg) {
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (!settled) { settled = true; reject(new Error('background 响应超时')); }
      }, 8000);
      function done(reply) {
        if (settled) return;
        settled = true; clearTimeout(timer);
        var err = (typeof chrome !== 'undefined' && chrome.runtime.lastError) ? chrome.runtime.lastError.message : null;
        if (err) reject(new Error(err)); else resolve(reply);
      }
      try {
        var pr = chrome.runtime.sendMessage(msg);
        if (pr && typeof pr.then === 'function') {
          pr.then(done).catch(function (e) {
            if (!settled) { settled = true; clearTimeout(timer); reject(e); }
          });
        } else {
          chrome.runtime.sendMessage(msg, done);
        }
      } catch (e) { clearTimeout(timer); settled = true; reject(e); }
    });
  }

  /**
   * 取 K 线
   * @param code   6位代码
   * @param period daily/weekly/monthly/60m/30m/15m/5m/1m
   * @param limit  根数
   * @param adjust 复权 0=不复权 1=前复权 2=后复权
   */
  async function getKlines(code, period, limit, adjust) {
    // 缓存键里带上当前数据源：手动换源后必须立刻重取，
    // 否则 45 秒内还会拿到上一个源的数据（图上「来源」与实际内容不符）
    const src = (global.CLMarket && global.CLMarket.getSource) ? global.CLMarket.getSource() : 'auto';
    const key = [code, period, limit, adjust, src].join('|');
    const hit = localCache.get(key);
    if (hit && Date.now() - hit.at < hit.ttl) return hit.data;

    const req = {
      type: 'CL_FETCH_KLINE', code: code, period: period,
      limit: limit || 800, adjust: adjust == null ? 1 : adjust,
      source: src                    // 后台模块是另一个实例，选源要显式带过去
    };

    let data = null, lastErr = null;
    try {
      const reply = await ask(req);
      if (!reply || !reply.ok) throw new Error((reply && reply.error) || '未知错误');
      data = reply.data;
    } catch (e) { lastErr = e; }

    /* 兜底：App 页面本身有 host_permissions，可以直接跨源请求，
       background 服务睡着/重启的窗口期不至于卡死界面 */
    if ((!data || !data.klines || !data.klines.length) && global.CLMarket) {
      try {
        data = await global.CLMarket.fetchKline(code, period, limit || 800, adjust == null ? 1 : adjust);
      } catch (e2) {
        throw new Error((lastErr && lastErr.message ? lastErr.message + ' / ' : '') + e2.message);
      }
    }
    if (!data) throw new Error((lastErr && lastErr.message) || '未知错误');

    /* 末端兜底：日/周/月各源落地时间不一致，主源可能还没出当前这根
       （用户看到的「30 分钟图正常、日线图还是昨天的形态」）。末端落后时
       去别的源找更晚的，**只把那几根追加到尾部**，历史不动。
       只有别的源确实更晚才追加，所以周末/节假日/停牌不会误改数据。 */
    var MK = global.CLMarket;
    if (MK && MK.isStale && MK.isStale(data.klines, period)) {
      var gk = code + '|' + period;
      // 上次试过但别的源也没有（节假日/停牌就是这样），10 分钟内不再空跑；
      // 追加成功则不抑制 —— 那种情况主源一直落后，每次都得补。
      // clearCache()（长按强制重算）会连这张表一起清，保证「强制」即时生效。
      if (Date.now() - (fixGuard[gk] || 0) > FIX_GUARD_MS) {
        try {
          const fix = await MK.fetchFresherTail(
            code, period, limit || 800, adjust == null ? 1 : adjust,
            data.source || src, data.klines);
          if (fix && fix.tail && fix.tail.length) {
            // 连续性校验：追加的第一根相对当前末根跳变过大，多半是复权基准
            // 或报价精度对不上（新浪不复权 vs 腾讯 qfq），宁可不补也别造假跳空
            var prev = data.klines[data.klines.length - 1];
            var prevC = Number(prev.c), nextC = Number(fix.tail[0].c);
            var jump = prevC > 0 ? Math.abs(nextC - prevC) / prevC : 0;
            var note = { from: data.source || src, to: fix.from, n: fix.tail.length };
            if (jump > FIX_JUMP_MAX) {
              note.rejected = true;
            } else {
              data.klines = data.klines.concat(fix.tail);
            }
            data.tailFix = note;
          } else if (fix && fix.gap) {
            // 缺口 ≥ 探测窗口：多半是长期停牌/很久没打开。不再为它拉第二次
            // 全量，交给用户长按「重算」（会清掉这张抑制表，立刻生效）
            data.tailFix = { from: data.source || src, to: fix.from, gap: true };
            fixGuard[gk] = Date.now();
          } else {
            fixGuard[gk] = Date.now();      // 别的源也没有 → 抑制一会儿
          }
        } catch (e) { /* 兜底失败不影响主流程，图上顶多还是旧的那根 */ }
      }
    }

    localCache.set(key, { at: Date.now(), ttl: ttlForNow(), data: data });
    if (localCache.size > 30) localCache.delete(localCache.keys().next().value);
    return data;
  }

  /** 把 ISO/各种时间字符串解析成毫秒（用于多级别时间轴对齐） */
  function parseTime(t) {
    if (t == null) return NaN;
    if (typeof t === 'number') return t < 1e12 ? t * 1000 : t;
    if (typeof t === 'string' && /^\d+$/.test(t)) {
      const n = parseInt(t, 10);
      return t.length === 10 ? n * 1000 : n;
    }
    const ms = Date.parse(String(t).replace(/-/g, '/').replace('T', ' '));
    return isNaN(ms) ? NaN : ms;
  }

  /** 给每根 K 线补上 _t（毫秒时间戳），引擎的多级别联动依赖它 */
  function withTimestamps(data) {
    if (!data || !data.klines) return data;
    data.klines.forEach(function (k) { if (k._t == null) k._t = parseTime(k.t); });
    data.klines = data.klines.filter(function (k) { return isFinite(k._t); });
    return data;
  }

  /** 导出结构为 JSON 文件，供本地 Python 回测使用 */
  function downloadJSON(filename, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  /** 清掉本层缓存（强制刷新用）。1.9.9 起「重算」无论哪个入口都走它，所以：
   *  ① 非交易时段的长 TTL 缓存也要能被它作废（这正是强制语义）；
   *  ② background 还有一层请求缓存（另一个 JS 实例，60s/非交易时段同样拉长），
   *     必须发消息一起清 —— v1.9.9 之前它从没被清过，重算后 1 分钟内重取
   *     仍会命中，这就是当初「45 秒内连点重算不联网」的另一半原因。 */
  function clearCache() {
    localCache.clear(); fixGuard = {};
    try {
      chrome.runtime.sendMessage({ type: 'CL_CLEAR_CACHE' }, function () {
        void chrome.runtime.lastError;   // SW 睡着/预览环境没有 background：无所谓
      });
    } catch (e) { /* 同上，fire-and-forget */ }
  }

  global.CLDataSource = {
    getKlines: getKlines,
    withTimestamps: withTimestamps,
    parseTime: parseTime,
    downloadJSON: downloadJSON,
    clearCache: clearCache
  };
})(typeof window !== 'undefined' ? window : this);
