/* ==========================================================================
 * market.js —— 共享数据层（无 chrome.* 依赖，service worker 与 App 页共用）
 *
 * 两个运行环境都具备跨源请求能力：
 *   - service worker：扩展出身 + host_permissions
 *   - App 页面：chrome-extension:// 页同样受 host_permissions 保护，免 CORS
 * 因此这一层只管「发请求、解析、降级」，消息转发由上层自行选择。
 * ========================================================================== */
'use strict';

(function (g) {
  'use strict';

  var EM_HOST = 'https://push2his.eastmoney.com/api/qt/stock/kline/get';
  var EM_PERIOD = {
    '1m': '1', '5m': '5', '15m': '15', '30m': '30', '60m': '60',
    'daily': '101', 'weekly': '102', 'monthly': '103'
  };
  var SINA_PERIOD = { '5m': 5, '15m': 15, '30m': 30, '60m': 60, 'daily': 240, 'weekly': 1200, 'monthly': 7200 };

  function toSecid(code) {
    const c = String(code).trim();
    if (/^(sh|sz|bj)/i.test(c)) {
      return (/^sh/i.test(c) ? '1.' : '0.') + c.slice(2);
    }
    if (/^(6|9|5|11|68)/.test(c)) return '1.' + c;
    if (/^(0|1|3|2|8|4)/.test(c)) return '0.' + c;
    return '0.' + c;
  }

  /* ------------------------------------------------------- 东方财富（主源） */
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
      headers: { 'Referer': 'https://quote.eastmoney.com/' }
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
    return { source: 'eastmoney', name: data.name || '', code: String(code), period: period, adjust: adjust, klines: klines };
  }

  /* ------------------------------------------------------- 新浪（备用源） */
  async function fetchSina(code, period, limit) {
    const scale = SINA_PERIOD[period] || 240;
    let symbol = String(code).trim();
    if (!/^(sh|sz|bj)/i.test(symbol)) {
      symbol = (/^(6|9|5|11|68)/.test(symbol) ? 'sh' : 'sz') + symbol;
    }
    const url = 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=' +
                symbol + '&scale=' + scale + '&ma=no&datalen=' + (limit || 800);
    const res = await fetch(url, {
      headers: { 'Referer': 'https://finance.sina.com.cn/' }
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const text = await res.text();
    const json = JSON.parse(text.replace(/^.*?(\[.*\]).*$/s, '$1'));
    const klines = json.map(k => ({
      t: k.day, o: +k.open, c: +k.close, h: +k.high, l: +k.low, v: +k.volume, a: 0, pct: 0, turn: 0
    }));
    if (!klines.length) throw new Error('新浪返回空数据');
    return { source: 'sina', name: '', code: String(code), period: period, adjust: 1, klines: klines };
  }

  /* 主源失败自动切备用源 */
  async function fetchKline(code, period, limit, adjust) {
    let errs = [];
    try { return await fetchEastmoney(code, period, limit, adjust); }
    catch (e) { errs.push('eastmoney: ' + e.message); }
    try { return await fetchSina(code, period, limit); }
    catch (e) { errs.push('sina: ' + e.message); }
    throw new Error(errs.join(' / '));
  }

  /* ----------------------------------------------------- 搜索与名称反查 */
  async function searchSuggest(text) {
    const url = 'https://searchapi.eastmoney.com/api/suggest/get?input=' +
                encodeURIComponent(text) +
                '&type=14&token=D43CF722A11C4C0EB9AFCAB1A9C0D9A6&count=10';
    const res = await fetch(url, { headers: { 'Referer': 'https://www.eastmoney.com/' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const json = await res.json();
    const groups = (json && json.QuotationCodeTable && json.QuotationCodeTable.Data) || [];
    return groups.map(d => ({
      code: String(d.Code || ''),
      name: d.Name || '',
      market: String(d.MktNum || ''),
      type: d.SecurityTypeName || ''
    })).filter(d => /^\d{6}$/.test(d.code));
  }

  async function fetchName(code) {
    const res = await fetch(
      'https://push2.eastmoney.com/api/qt/stock/get?secid=' + toSecid(code) +
      '&fields=f43,f57,f58,f170&fltt=2&invt=2',
      { headers: { 'Referer': 'https://quote.eastmoney.com/' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const j = await res.json();
    const d = j && j.data;
    if (!d || !d.f57) throw new Error('未找到该代码');
    return { code: d.f57, name: d.f58 || '', price: d.f43, pct: d.f170 };
  }

  g.CLMarket = {
    toSecid: toSecid,
    fetchKline: fetchKline,
    fetchEastmoney: fetchEastmoney,
    fetchSina: fetchSina,
    searchSuggest: searchSuggest,
    fetchName: fetchName
  };
})(typeof self !== 'undefined' ? self : this);
