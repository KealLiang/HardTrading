/* ==========================================================================
 * datasource.js —— content script 侧的行情获取
 * 实际的网络请求都在 background service worker 里完成（绕开 CORS），
 * 这里只负责发消息、做本地兜底、以及把数据整理成引擎要的格式。
 * ========================================================================== */
'use strict';

(function (global) {
  'use strict';

  var reqId = 0;
  var pending = new Map();
  var localCache = new Map();
  var LOCAL_TTL = 45 * 1000;

  chrome.runtime.onMessage.addListener(function (msg) {
    if (!msg || msg.__chanlensReply) return;
    var p = pending.get(msg.__id);
    if (p) { pending.delete(msg.__id); p(msg); }
  });

  function ask(msg) {
    return new Promise(function (resolve, reject) {
      var id = ++reqId;
      msg.__id = id;
      pending.set(id, resolve);
      setTimeout(function () {
        if (pending.has(id)) { pending.delete(id); reject(new Error('background 响应超时')); }
      }, 20000);
      try { chrome.runtime.sendMessage(msg); }
      catch (e) { pending.delete(id); reject(e); }
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
    const key = [code, period, limit, adjust].join('|');
    const hit = localCache.get(key);
    if (hit && Date.now() - hit.at < LOCAL_TTL) return hit.data;

    const reply = await ask({
      type: 'CL_FETCH_KLINE', code: code, period: period,
      limit: limit || 800, adjust: adjust == null ? 1 : adjust
    });
    if (!reply || !reply.ok) throw new Error((reply && reply.error) || '未知错误');
    localCache.set(key, { at: Date.now(), data: reply.data });
    if (localCache.size > 30) localCache.delete(localCache.keys().next().value);
    return reply.data;
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

  global.CLDataSource = {
    getKlines: getKlines,
    withTimestamps: withTimestamps,
    parseTime: parseTime,
    downloadJSON: downloadJSON
  };
})(typeof window !== 'undefined' ? window : this);
