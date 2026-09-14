/* ==========================================================================
 * adapters.js —— 站点适配
 *
 * 因为我们「自己画图」，站点适配的工作被压缩到只剩一件事：
 *   从当前页面里识别出「股票代码」，并找到一个适合挂载图表的容器。
 * 剩下的画法完全由我们控制，所以网站改版顶多导致识别不到代码，不会画歪。
 * ========================================================================== */
'use strict';

(function (global) {
  'use strict';

  /** 形如 600519 / SH600519 / sh.600519 的各种写法统一成 6 位数字 */
  function normalizeCode(raw) {
    if (!raw) return null;
    let s = String(raw).trim().toUpperCase();
    s = s.replace(/^(SH|SZ|BJ)[\.:\-]?/, '');
    const m = s.match(/(\d{6})/);
    return m ? m[1] : null;
  }

  /** 从 URL 里找代码 */
  function fromUrl(href) {
    const patterns = [
      /xueqiu\.com\/S\/[A-Z]{0,2}(\d{6})/i,
      /(?:stockpage\.|d\.)?10jqka\.com\.cn\/(?:new)?(?:code|stockpage)\/?[a-z]*?(\d{6})/i,
      /quote\.eastmoney\.com\/(?:sh|sz|bj)?(\d{6})\.html/i,
      /finance\.sina\.com\.cn\/realstock\/company\/(?:sh|sz|bj)(\d{6})/i,
      /finance\.sina\.com\.cn\/.*?[?&](?:symbol|code)=(?:sh|sz|bj)?(\d{6})/i,
      /tradingview\.com\/(?:chart\/)?.*?[?&]symbol=.*?(\d{6})/i,
      /\/(\d{6})(?:[/?#]|$)/                                  // 兜底：路径里裸的 6 位数字
    ];
    for (const re of patterns) {
      const m = href.match(re);
      if (m && m[1]) return normalizeCode(m[1]);
    }
    return null;
  }

  /** 从页面标题/DOM 文本里找代码（兜底） */
  function fromDom() {
    const title = document.title || '';
    let m = title.match(/(\d{6})/);
    if (m) return normalizeCode(m[1]);

    // 页面里常见 <span class="code">600519</span> 之类
    const sel = ['[class*=code]', '[id*=code]', '[data-code]', '.stock-code', '.quote-code'];
    for (const s of sel) {
      const el = document.querySelector(s);
      if (!el) continue;
      const txt = (el.getAttribute('data-code') || el.textContent || '').trim();
      m = txt.match(/(\d{6})/);
      if (m) return normalizeCode(m[1]);
    }
    const bodyMatch = (document.body && document.body.innerText || '').match(/\((\d{6})\)/);
    return bodyMatch ? normalizeCode(bodyMatch[1]) : null;
  }

  /** 找一个合适的挂载容器：优先主内容区，其次 body */
  function findMount() {
    const candidates = [
      '#app', '.main-content', '.content', '#content', 'main',
      '.quote-container', '.stock-detail', '.u-mainWrap'
    ];
    for (const s of candidates) {
      const el = document.querySelector(s);
      if (el && el.offsetHeight > 200) return el;
    }
    return document.body;
  }

  const SITES = [
    { id: 'xueqiu', name: '雪球', test: /xueqiu\.com/i },
    { id: 'sina', name: '新浪财经', test: /sina\.com\.cn/i },
    { id: 'eastmoney', name: '东方财富', test: /eastmoney\.com/i },
    { id: '10jqka', name: '同花顺', test: /10jqka\.com\.cn/i },
    { id: 'tradingview', name: 'TradingView', test: /tradingview\.com/i },
    { id: 'unknown', name: '未知站点', test: /.*/ }
  ];

  function detect() {
    const href = location.href;
    const site = SITES.find(s => s.test.test(href)) || SITES[SITES.length - 1];
    const code = fromUrl(href) || fromDom();
    return {
      site: site.id,
      siteName: site.name,
      code: code,
      mount: findMount(),
      supported: !!code
    };
  }

  global.CLAdapters = { detect: detect, normalizeCode: normalizeCode, SITES: SITES };
})(typeof window !== 'undefined' ? window : this);
