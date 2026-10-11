/* ==========================================================================
 * service_worker.js —— 消息路由 + 行情缓存
 *
 * 实际的数据抓取逻辑在 core/market.js（与 App 页共享同一份代码）。
 * background 存在的意义：
 *   1. content script（launcher）没有跨源权限，需要它代发请求；
 *   2. 打开 App 标签页（CL_OPEN_APP）；
 *   3. 一层请求缓存。
 * App 页面本身优先直连 market.js，这里只是兜底与缓存。
 *
 * 注意：本扩展只做「读取公开行情」，不上传任何数据、不触碰账户信息。
 * ========================================================================== */
'use strict';

importScripts('../core/market.js');

const CACHE_TTL = 60 * 1000;          // 盘中的重复请求防抖窗口
const cache = new Map();

/* TTL 按交易时段取（CLMarket.cacheTTLFor，与 content 层同一套规则）：
   盘中 60s；非交易时段缓存活到下次开盘 —— 数据不会变，来回切股零请求。
   TTL 写入时定死在条目上，读的时候不能按当下时段重算（那样开盘后
   旧数据会被「盘中 60s」以外的新长 TTL 掩护着过不了期）。 */
function ttlForNow() {
  return (CLMarket && CLMarket.cacheTTLFor) ? CLMarket.cacheTTLFor(Date.now(), CACHE_TTL) : CACHE_TTL;
}

/* ------------------------------------------------------------------ 入口 */
async function handleKline(msg) {
  const adjust = msg.adjust == null ? 1 : msg.adjust;
  // service worker 里的 CLMarket 是独立实例，页面上改的「数据源」不会自动同步过来
  if (msg.source && CLMarket.setSource) CLMarket.setSource(msg.source);
  const key = [msg.code, msg.period, msg.limit, adjust, msg.source || 'auto'].join('|');
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < hit.ttl) return Object.assign({ cached: true }, hit.data);

  const data = await CLMarket.fetchKline(msg.code, msg.period, msg.limit, adjust);
  data.fetchedAt = Date.now();
  cache.set(key, { at: Date.now(), ttl: ttlForNow(), data: data });
  if (cache.size > 40) cache.delete(cache.keys().next().value);
  return data;
}

/* 统一的异步回包包装：任何异常都变成 {ok:false,error}，前端不会卡在超时上 */
function reply(promise, sendResponse) {
  Promise.resolve()
    .then(promise)
    .then(data => sendResponse({ ok: true, data: data }))
    .catch(e => sendResponse({ ok: false, error: String(e && e.message || e) }));
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return undefined;

  if (msg.type === 'CL_FETCH_KLINE') { reply(handleKline(msg), sendResponse); return true; }

  /* 「重算」/强制重扫 由 content 层发来：这层请求缓存（60s/非交易时段到开盘）
     必须一起作废，否则强制重取 1 分钟内还是命中旧数据。 */
  if (msg.type === 'CL_CLEAR_CACHE') { cache.clear(); sendResponse({ ok: true }); return undefined; }

  if (msg.type === 'CL_SEARCH') { reply(CLMarket.searchSuggest(msg.text || ''), sendResponse); return true; }

  if (msg.type === 'CL_QUOTE') { reply(CLMarket.fetchName(msg.code), sendResponse); return true; }

  if (msg.type === 'CL_OPEN_APP') {
    const url = chrome.runtime.getURL('app/app.html') +
                (msg.code ? '?code=' + encodeURIComponent(msg.code) : '');
    chrome.tabs.create({ url: url });
    sendResponse({ ok: true });
    return undefined;
  }

  if (msg.type === 'CL_PING') {
    sendResponse({ ok: true, version: 1 });
    return undefined;
  }
  return undefined;
});

/* 点击工具栏图标 → 打开 App（任何页面都能用，能顺手认出代码就带上） */
const URL_CODE = [
  /xueqiu\.com\/S\/[A-Z]{0,2}(\d{6})/i,
  /quote\.eastmoney\.com\/(?:sh|sz|bj)?(\d{6})\.html/i,
  /finance\.sina\.com\.cn\/realstock\/company\/(?:sh|sz|bj)(\d{6})/i,
  /10jqka\.com\.cn\/(?:new)?(?:code|stockpage)\/?[a-z]*?(\d{6})/i,
  /finance\.sina\.com\.cn\/.*?[?&](?:symbol|code)=(?:sh|sz|bj)?(\d{6})/i
];
function codeFromUrl(url) {
  if (!url) return null;
  for (const re of URL_CODE) { const m = url.match(re); if (m && m[1]) return m[1]; }
  return null;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.action.setTitle({ title: 'ChanLens 缠论透镜' });
});

chrome.action.onClicked.addListener((tab) => {
  const code = codeFromUrl(tab && tab.url);
  chrome.tabs.create({
    url: chrome.runtime.getURL('app/app.html') + (code ? '?code=' + code : '')
  });
});
