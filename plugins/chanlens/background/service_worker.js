/* ==========================================================================
 * service_worker.js —— 行情代理
 *
 * 为什么需要一个 background：content script 里的 fetch 依然受页面 CORS 限制，
 * 而声明过 host_permissions 的扩展出身 requests 不受 CORS 约束。
 * 所有行情都从这里发出（顺便做一层缓存与失败降级）。
 *
 * 注意：本扩展只做「读取公开行情」，不上传任何数据、不触碰账户信息。
 * ========================================================================== */
'use strict';

const CACHE_TTL = 60 * 1000;          // 一分钟内的重复请求直接复用
const cache = new Map();

const EM_HOST = 'https://push2his.eastmoney.com/api/qt/stock/kline/get';

const EM_PERIOD = {
  '1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
  'daily': '101', 'weekly': '102', 'monthly': '103'
};

function toSecid(code) {
  const c = String(code).trim();
  if (/^(sh|sz|bj)/i.test(c)) {
    return (/^sh/i.test(c) ? '1.' : '0.') + c.slice(2);
  }
  if (/^(6|9|5|11|68)/.test(c)) return '1.' + c;
  if (/^(0|1|3|2|8|4)/.test(c)) return '0.' + c;
  return '0.' + c;
}

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload), {
    headers: { 'Content-Type': 'application/json; charset=utf-8' }
  });
}

/* ------------------------------------------------------- 东方财富（主数据源） */
async function fetchEastmoney(code, period, limit, adjust) {
  const klt = EM_PERIOD[period] || '101';
  const params = new URLSearchParams({
    secid: toSecid(code),
    klt: klt,
    fqt: String(adjust == null ? 1 : adjust),
    lmt: String(limit || 800),
    end: '20500101',
    fields1: 'f1,f2,f3,f4,f5,f6',
    fields2: 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
    ut: 'fa5fd1943c7b386f172d6893dbfba10b'
  });
  const res = await fetch(EM_HOST + '?' + params.toString(), {
    headers: {
      'Referer': 'https://quote.eastmoney.com/',
      'User-Agent': 'Mozilla/5.0 ChanLens/1.0'
    }
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const json = await res.json();
  const data = json && json.data;
  if (!data || !data.klines) throw new Error('东财返回结构异常');

  const klines = data.klines.map(line => {
    const p = line.split(',');
    return {
      t: p[0],
      o: +p[1], c: +p[2], h: +p[3], l: +p[4],
      v: +p[5], a: +(p[6] || 0), pct: +(p[8] || 0), turn: +(p[10] || 0)
    };
  });
  return { source: 'eastmoney', name: data.name || '', code: code, period: period, adjust: adjust, klines: klines };
}

/* ------------------------------------------------------------ 新浪（备用源） */
const SINA_PERIOD = { '5m': 5, '15m': 15, '30m': 30, '60m': 60, 'daily': 240, 'weekly': 1200, 'monthly': 7200 };

async function fetchSina(code, period, limit) {
  const scale = SINA_PERIOD[period] || 240;
  let symbol = String(code).trim();
  if (!/^(sh|sz|bj)/i.test(symbol)) {
    symbol = (/^(6|9|5|11|68)/.test(symbol) ? 'sh' : 'sz') + symbol;
  }
  const url = 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=' +
              symbol + '&scale=' + scale + '&ma=no&datalen=' + (limit || 800);
  const res = await fetch(url, {
    headers: { 'Referer': 'https://finance.sina.com.cn/', 'User-Agent': 'Mozilla/5.0 ChanLens/1.0' }
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const text = await res.text();
  const json = JSON.parse(text.replace(/^.*?(\[.*\]).*$/s, '$1'));
  const klines = json.map(k => ({
    t: k.day, o: +k.open, c: +k.close, h: +k.high, l: +k.low, v: +k.volume, a: 0, pct: 0, turn: 0
  }));
  return { source: 'sina', name: '', code: code, period: period, adjust: 1, klines: klines };
}

/* ------------------------------------------------------------------ 入口 */
async function handleKline(msg) {
  const key = [msg.code, msg.period, msg.limit, msg.adjust].join('|');
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_TTL) return Object.assign({ cached: true }, hit.data);

  let data = null, errs = [];
  try { data = await fetchEastmoney(msg.code, msg.period, msg.limit, msg.adjust); }
  catch (e) { errs.push('eastmoney: ' + e.message); }
  if (!data || !data.klines.length) {
    try { data = await fetchSina(msg.code, msg.period, msg.limit); }
    catch (e) { errs.push('sina: ' + e.message); }
  }
  if (!data) throw new Error(errs.join(' / ') || '无可用数据源');

  data.fetchedAt = Date.now();
  cache.set(key, { at: Date.now(), data: data });
  if (cache.size > 40) cache.delete(cache.keys().next().value);
  return data;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return undefined;

  if (msg.type === 'CL_FETCH_KLINE') {
    handleKline(msg)
      .then(data => sendResponse({ ok: true, data: data }))
      .catch(e => sendResponse({ ok: false, error: String(e && e.message || e) }));
    return true;                       // 保持消息通道，异步响应
  }

  if (msg.type === 'CL_PING') {
    sendResponse({ ok: true, version: 1 });
    return undefined;
  }
  return undefined;
});
