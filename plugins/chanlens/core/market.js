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

  /* ------------------------------------------------------- 腾讯（备用源） */
  const TX_KLINE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get';   // 日/周/月，支持前复权
  const TX_MKLINE = 'https://ifzq.gtimg.cn/appstock/app/kline/mkline';     // 分钟线（不带 web. 前缀才通）
  const TX_PERIOD = {
    '1m': 'm1', '5m': 'm5', '15m': 'm15', '30m': 'm30', '60m': 'm60',
    'daily': 'day', 'weekly': 'week', 'monthly': 'month'
  };
  const TX_BIG = { daily: 1, weekly: 1, monthly: 1 };   // 走 fqkline（带复权）的那几档

  function txSymbol(code) {
    const c = String(code).trim();
    if (/^(sh|sz|bj)/i.test(c)) return c.toLowerCase();
    const parts = toSecid(c).split('.');
    return (parts[0] === '1' ? 'sh' : 'sz') + parts[1];
  }

  /** 腾讯时间戳 -> 与其它源一致的字符串。
   *  注意两个接口格式不同：fqkline（日/周/月）给的是 'YYYY-MM-DD'，
   *  mkline（分钟）给的是紧凑的 'YYYYMMDDhhmm'。别一律按紧凑切。 */
  function txTime(raw, isBig) {
    const s = String(raw);
    if (isBig || s.indexOf('-') >= 0) return s.slice(0, 10);
    return s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) +
           ' ' + s.slice(8, 10) + ':' + s.slice(10, 12) + ':00';
  }

  async function fetchTencent(code, period, limit) {
    const sym = txSymbol(code);
    const key = TX_PERIOD[period] || 'day';
    const big = !!TX_BIG[period];
    const n = limit || 800;
    const url = big
      ? TX_KLINE + '?param=' + sym + ',' + key + ',,,' + n + ',qfq'
      : TX_MKLINE + '?param=' + sym + ',' + key + ',,' + n;
    const res = await fetch(url, { headers: { 'Referer': 'https://gu.qq.com/' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const json = await res.json();
    const d = json && json.data && json.data[sym];
    if (!d) throw new Error('腾讯返回结构异常');
    const rows = d[(big ? 'qfq' : '') + key] || d[key];
    if (!rows || !rows.length) throw new Error('腾讯返回空数据');

    const klines = rows.map(r => ({
      t: txTime(r[0], big),
      o: +r[1], c: +r[2], h: +r[3], l: +r[4], v: +r[5],
      a: 0, pct: 0, turn: 0
    }));
    return {
      source: 'tencent', name: '', code: String(code),
      period: period, adjust: big ? 1 : 0, klines: klines
    };
  }

  /* ------------------------------------------------------- 数据源注册表
   * auto = 原来的行为：东财优先，挂了切新浪（顺序不变，备用源不参与自动选）。
   * 手动指定某个源时，它是首选，失败仍会自动往 auto 链里降级 —— 宁可给出
   * 数据并把真实来源显示在状态栏，也不要因为一个源抖动就整个打不开图。
   */
  const SOURCES = [
    { id: 'eastmoney', label: '东方财富', fetch: fetchEastmoney },
    { id: 'sina', label: '新浪财经', fetch: fetchSina },
    { id: 'tencent', label: '腾讯财经', fetch: fetchTencent }
  ];
  const AUTO_CHAIN = ['eastmoney', 'sina'];
  let prefSource = 'auto';

  function setSource(id) {
    prefSource = SOURCES.some(s => s.id === id) ? id : 'auto';
    return prefSource;
  }
  function getSource() { return prefSource; }
  function sourceLabel(id) {
    const s = SOURCES.find(x => x.id === id);
    return s ? s.label : '未知来源';
  }
  /** 供设置面板生成选项，避免两端各写一份列表 */
  function sourceOptions() {
    return [{ id: 'auto', label: '自动（东财优先，失败切新浪）' }]
      .concat(SOURCES.map(s => ({ id: s.id, label: s.label })));
  }

  /* 按选中源取数；未指定时保持历史行为（东财 -> 新浪） */
  async function fetchKline(code, period, limit, adjust) {
    const order = prefSource === 'auto'
      ? AUTO_CHAIN.slice()
      : [prefSource].concat(AUTO_CHAIN.filter(id => id !== prefSource));
    const errs = [];
    for (const id of order) {
      const s = SOURCES.find(x => x.id === id);
      if (!s) continue;
      try { return await s.fetch(code, period, limit, adjust); }
      catch (e) { errs.push(s.id + ': ' + e.message); }
    }
    throw new Error(errs.join(' / '));
  }

  /* -------------------------------------------- 日/周/月「末端缺失」兜底
   * 各源日线当日数据的落地时间不一致：东财 push2his 盘中就给实时当日，
   * 腾讯 fqkline 也较早；而新浪 getKLineData(scale=240) 收盘后有一段合成
   * 空窗 —— 同一时刻它的分钟线（scale=30）已经是当日，日线却还停在昨天。
   * 表现就是用户看到的「30 分钟图正常、日线图还是昨天的形态」，
   * 而且这时候不管怎么重算都刷不出来，因为源那边确实没有这根。
   *
   * 这里只做一件事：末端明显落后时，去别的源看看谁更新，**把更晚的那几根
   * 追加到尾部**，历史一个字不动。不整份替换 —— 各源的复权基准（新浪压根
   * 不支持复权，腾讯日/周/月是 qfq）和报价精度（腾讯 ETF 只到分）都不一样，
   * 整份换会把历史的笔/段/中枢一起改掉。
   *
   * 判据是「别的源有没有更晚的」而不是「等于今天」—— 周末、节假日、停牌
   * 这些情况所有源都停在同一天，追加 0 根，保持原样，不会误判成数据缺失。
   */
  var nowFn = function () { return Date.now(); };   // 单测/冒烟可注入时间基准
  function setNowFn(fn) {
    nowFn = typeof fn === 'function' ? fn : function () { return Date.now(); };
  }

  function fmtDate(d) {
    var m = d.getMonth() + 1, dd = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' +
           (dd < 10 ? '0' : '') + dd;
  }

  /** 当前周期「应有的最新一根」的日期下限：末端日期 >= 它，就算已更新。
   *  不查节假日日历 —— 反正真正决定是否追加的是「别的源有没有更晚的」，
   *  多试一次无害（外层还有 10 分钟抑制，不会反复浪费请求）。
   *
   *  周/月线不猜「这根该标周几」（各源标周首/周末不一致），只要求它落在
   *  当前周期内：周线扯到本周一、月线扯到 1 号，末端在里面就算新。 */
  function expectLastDate(period, nowMs) {
    var d = new Date(nowMs == null ? nowFn() : nowMs);
    if (period === 'weekly') {
      var wd = d.getDay();                       // 0=周日 .. 6=周六
      d.setDate(d.getDate() - ((wd + 6) % 7));   // 周一退 0 天，周日退 6 天
    } else if (period === 'monthly') {
      d.setDate(1);
    } else {
      // 日线：09:30 前算上一交易日，周末回退周五
      if (d.getHours() * 60 + d.getMinutes() < 9 * 60 + 30) d.setDate(d.getDate() - 1);
      while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
    }
    return fmtDate(d);
  }

  /** 日线专用入口（老调用兼容） */
  function expectTradingDate(nowMs) { return expectLastDate('daily', nowMs); }

  function lastDateOf(klines) {
    if (!klines || !klines.length) return '';
    var t = String(klines[klines.length - 1].t || '').slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(t) ? t : '';
  }
  function dateOf(k) { return String((k && k.t) || '').slice(0, 10); }

  /** 末端是否落后（只给日/周/月用；分钟线各源都是实时聚合，不参与） */
  var FIX_PERIODS = { daily: 1, weekly: 1, monthly: 1 };
  function isStale(klines, period, nowMs) {
    if (!FIX_PERIODS[period]) return false;
    var last = lastDateOf(klines);
    return !!last && last < expectLastDate(period, nowMs);
  }
  function isStaleDaily(klines, nowMs) { return isStale(klines, 'daily', nowMs); }

  /** 末端落后时依次试其它源：腾讯（当日落地最早）-> 东财 -> 新浪。
   *  只把「晚于当前末端的那几根」交回来，历史一个字不动 —— 各源根数、
   *  复权基准、报价精度都不一样，整份替换会把笔/段/中枢一起改掉。
   *
   *  探测只用小窗口：要补的通常就 1~2 根，不值得为它拉满 800 根。源只能按
   *  「最近 N 根」取，所以 30 根的末根和 800 根的末根是同一根 —— 不存在
   *  「窗口小就没拉到当日」这回事，探测没更新就是源真的没更新。
   *
   *  整个窗口都比当前末端新 = 缺口 ≥ 窗口：这是长期停牌/很久没打开的信号，
   *  **不再为它拉第二次全量**，交回 gap 标记让用户长按强制重算。 */
  const DAILY_FIX_ORDER = ['tencent', 'eastmoney', 'sina'];
  const TAIL_PROBE_N = 30;
  async function fetchFresherTail(code, period, limit, adjust, curSrc, curKlines) {
    const cur = lastDateOf(curKlines);
    if (!cur) return null;
    for (const id of DAILY_FIX_ORDER) {
      if (id === curSrc) continue;
      const s = SOURCES.find(x => x.id === id);
      if (!s) continue;
      try {
        const d = await s.fetch(code, period, Math.min(TAIL_PROBE_N, limit || TAIL_PROBE_N), adjust);
        const ks = (d && d.klines) || [];
        if (!ks.length) continue;
        const tail = ks.filter(k => dateOf(k) > cur);
        if (tail.length === ks.length && dateOf(ks[0]) > cur) {
          return { tail: [], from: id, gap: true };
        }
        if (tail.length) return { tail: tail, from: id };
      } catch (e) { /* 这个源不通/没数据，换下一个 */ }
    }
    return null;
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

  /* ----------------------------------------------------- 批量实时快照 */
  var EM_QUOTE = 'https://push2.eastmoney.com/api/qt/ulist.np/get';
  var TX_QUOTE = 'https://qt.gtimg.cn/q=';

  function _num(v) {
    if (typeof v === 'number' && isFinite(v)) return v;
    if (typeof v === 'string' && v !== '-' && v !== '' && isFinite(+v)) return +v;
    return null;
  }

  /** 东财批量：一次几十只；部分网络对 push2 不可达，失败自动走腾讯 */
  async function fetchQuotesEM(list) {
    const out = {};
    const CHUNK = 60;   // 控制 URL 长度
    for (let i = 0; i < list.length; i += CHUNK) {
      const url = EM_QUOTE +
        '?secids=' + encodeURIComponent(list.slice(i, i + CHUNK).map(toSecid).join(',')) +
        '&fields=f2,f3,f12&fltt=2&invt=2&ut=fa5fd1943c7b386f172d6893dbfba10b';
      const res = await fetch(url, { headers: { 'Referer': 'https://quote.eastmoney.com/' } });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const j = await res.json();
      const diff = (j && j.data && j.data.diff) || [];
      diff.forEach(d => {
        const code = String(d.f12 || '');
        if (code) out[code] = { price: _num(d.f2), pct: _num(d.f3) };
      });
    }
    if (!Object.keys(out).length) throw new Error('东财快照返回为空');
    return out;
  }

  /** 腾讯批量兜底：GBK 编码但只取数字字段（f3=现价 f32=涨跌幅）；ACAO:* 任何页面可直连 */
  async function fetchQuotesTX(list) {
    const qs = list.map(c => (toSecid(c)[0] === '1' ? 'sh' : 'sz') + c).join(',');
    const res = await fetch(TX_QUOTE + qs, { headers: { 'Referer': 'https://gu.qq.com/' } });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const text = await res.text();
    const out = {};
    text.split(';').forEach(part => {
      const m = part.match(/v_\w+="([^"]*)"/);
      if (!m) return;
      const f = m[1].split('~');
      const code = String(f[2] || '');
      if (/^\d{6}$/.test(code)) out[code] = { price: _num(f[3]), pct: _num(f[32]) };
    });
    if (!Object.keys(out).length) throw new Error('腾讯快照返回为空');
    return out;
  }

  /**
   * 批量取最新价/涨跌幅（一次请求拿全部自选）
   * @returns {{[code]: {price:number|null, pct:number|null}}} pct 单位 %，停牌/异常为 null
   */
  async function fetchQuotes(codes) {
    const list = (Array.isArray(codes) ? codes : [])
      .map(c => String(c).trim()).filter(c => /^\d{6}$/.test(c));
    if (!list.length) return {};
    try { return await fetchQuotesEM(list); }
    catch (e) { /* 东财不可达/限频 → 腾讯 */ }
    return await fetchQuotesTX(list);
  }

  g.CLMarket = {
    toSecid: toSecid,
    fetchKline: fetchKline,
    fetchEastmoney: fetchEastmoney,
    fetchSina: fetchSina,
    fetchTencent: fetchTencent,
    setSource: setSource,
    getSource: getSource,
    sourceLabel: sourceLabel,
    sourceOptions: sourceOptions,
    searchSuggest: searchSuggest,
    fetchName: fetchName,
    fetchQuotes: fetchQuotes,
    /* 日/周/月末端缺失兜底（供 content/datasource.js 调用；单测直接测纯函数） */
    isStale: isStale,
    isStaleDaily: isStaleDaily,
    expectLastDate: expectLastDate,
    expectTradingDate: expectTradingDate,
    fetchFresherTail: fetchFresherTail,
    TAIL_PROBE_N: TAIL_PROBE_N,
    setNowFn: setNowFn
  };
})(typeof self !== 'undefined' ? self : this);
