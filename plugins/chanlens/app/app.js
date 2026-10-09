/* ==========================================================================
 * app.js —— ChanLens App 外壳
 *
 * 这是扩展自己的页面（chrome-extension://），不再依赖任何第三方站点：
 *   顶栏：代码/拼音搜索 + 自选股快速切换
 *   主体：复用 ui/panel.js（嵌入模式）+ chart/renderer.js 自绘
 * 数据仍然走 background service worker 代理，因此不受页面 CORS 限制。
 * ========================================================================== */
'use strict';

(function () {
  'use strict';

  var WL_KEY = 'chanlens.watchlist.v1';

  var stage = document.getElementById('stage');
  var searchInput = document.getElementById('search');
  var suggestBox = document.getElementById('suggest');
  var listEl = document.getElementById('watchlist');
  var curNameEl = document.getElementById('curName');
  var curCodeEl = document.getElementById('curCode');
  var addBtn = document.getElementById('addBtn');
  var importBtn = document.getElementById('importBtn');
  var delBtnEl = document.getElementById('delBtn');

  var watchlist = [];
  var current = { code: null, name: '' };
  var panel = null;
  var views = [];
  var datasets = {};
  var syncing = false;
  var suggestItems = [];
  var activeSuggest = -1;
  var quotes = {};            // code -> {price, pct}，自选列表右侧的涨跌幅
  var quoteTimer = null;
  var signals = {};           // code -> 扫描信号（来自 CLScanner 持久化缓存）
  var scanBusy = false;
  var trackMap = {};          // code -> 追踪记录（CLTrack 持久化，1.6.0 缠论追踪）
  var extraOn = true;         // 「额外」显隐：追踪价位线 + 图上短文案
  var EXTRA_KEY = 'chanlens.extra.v1';

  /** 状态栏输出：panel 在「同步回调」场景（如测试桩）下可能尚未赋值，统一在这里兜底 */
  function setStatus(msg, warn) { if (panel && panel.setStatus) panel.setStatus(msg, warn); }

  var PERIOD_LABEL = {};
  CLPanel.PERIODS.forEach(function (p) { PERIOD_LABEL[p.id] = p.label; });

  /* ------------------------------------------------ 与 background 通信（兜底用） */
  function send(msg) {
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (!settled) { settled = true; reject(new Error('background 响应超时')); }
      }, 8000);
      function done(reply) {
        if (settled) return;
        settled = true; clearTimeout(timer);
        var err = chrome.runtime.lastError && chrome.runtime.lastError.message;
        if (err) { reject(new Error(err)); return; }
        if (!reply) { reject(new Error('background 无响应')); return; }
        if (!reply.ok) { reject(new Error(reply.error || '未知错误')); return; }
        resolve(reply.data);
      }
      try {
        var pr = chrome.runtime.sendMessage(msg);
        if (pr && typeof pr.then === 'function') pr.then(done).catch(done);
        else chrome.runtime.sendMessage(msg, done);
      } catch (e) { clearTimeout(timer); settled = true; reject(e); }
    });
  }

  /** App 页面自身具备 host_permissions，直连优先，background 仅作兜底 */
  function searchSuggest(text) {
    return CLMarket.searchSuggest(text).catch(function () { return send({ type: 'CL_SEARCH', text: text }); });
  }
  function fetchName(code) {
    return CLMarket.fetchName(code).catch(function () { return send({ type: 'CL_QUOTE', code: code }); });
  }

  /* ------------------------------------------------------------------ 分类 */
  /**
   * 分类（文件夹）模型：
   *   cats[0] 固定是「未分类」(id='')，其余按新建顺序排列
   *   自选股只多了一个字段 cat = 分类 id，旧数据没有 cat 就落到「未分类」，向后兼容
   */
  var CAT_KEY = 'chanlens.watchcats.v1';
  var UNCAT = '';
  var cats = [];              // [{id, name, closed}]
  var activeCat = UNCAT;      // 「+自选」「批量导入」的默认落点
  var dragCode = null;
  var catSeq = 1;

  function ensureUncat() {
    if (!cats.length || cats[0].id !== UNCAT) cats.unshift({ id: UNCAT, name: '未分类', closed: false });
    cats[0].name = '未分类';
  }

  function loadCats(cb) {
    chrome.storage.local.get(CAT_KEY, function (box) {
      var arr = box && box[CAT_KEY];
      cats = Array.isArray(arr)
        ? arr.filter(function (c) { return c && typeof c === 'object' && c.id !== undefined; })
        : [];
      cats.forEach(function (c) {
        if (!c.name) c.name = '分类';
        var n = parseInt(String(c.id).replace(/^c/, ''), 10);
        if (n >= catSeq) catSeq = n + 1;
      });
      ensureUncat();
      cb && cb();
    });
  }

  function saveCats() {
    var box = {}; box[CAT_KEY] = cats;
    try { chrome.storage.local.set(box); } catch (e) { /* 忽略 */ }
  }

  function catName(id) {
    for (var i = 0; i < cats.length; i++) if (cats[i].id === (id || UNCAT)) return cats[i].name;
    return '未分类';
  }

  function itemsOf(id) {
    return watchlist.filter(function (w) { return (w.cat || UNCAT) === id; });
  }

  /** 分组顺序下的扁平列表：分组顺序 → 组内按加入顺序。Alt+↑/↓ 与批量删除都用它 */
  function orderedItems() {
    var out = [], seen = [];
    cats.forEach(function (c) {
      itemsOf(c.id).forEach(function (w) { out.push(w); seen.push(w); });
    });
    watchlist.forEach(function (w) { if (seen.indexOf(w) < 0) out.push(w); });  // cat 指向已删分类的兜底
    return out;
  }

  /* --------------------------------------------------------- 涨跌幅快照 */
  /** 批量拉自选最新涨跌幅；失败静默降级为逐只查询（复用名称反查接口） */
  function refreshQuotes() {
    var codes = watchlist.map(function (w) { return w.code; });
    if (!codes.length) { quotes = {}; renderWatchlist(); return Promise.resolve(); }
    return CLMarket.fetchQuotes(codes)
      .catch(function () {
        var out = {}, idx = 0, CONC = 4;
        function worker() {
          if (idx >= codes.length) return Promise.resolve();
          var c = codes[idx++];
          return fetchName(c)
            .then(function (q) { if (q) out[c] = { price: q.price, pct: q.pct }; })
            .catch(function () { /* 拿不到就不显示 */ })
            .then(worker);
        }
        var all = [];
        for (var k = 0; k < CONC; k++) all.push(worker());
        return Promise.all(all).then(function () { return out; });
      })
      .then(function (m) {
        if (m && Object.keys(m).length) { quotes = m; renderWatchlist(); checkTrackAlerts(); checkTimingAll(); }
      })
      .catch(function () { /* 静默：涨跌幅拿不到不影响主功能 */ });
  }

  function fmtPct(p) {
    if (p == null || !isFinite(p)) return '—';
    return (p > 0 ? '+' : '') + p.toFixed(2) + '%';
  }

  /* 价格格式化：≥100 两位小数（股票），<100 三位（ETF 常见毫级精度） */
  function fmtPrice(v) {
    if (v == null || !isFinite(v)) return '—';
    return v >= 100 ? v.toFixed(2) : v.toFixed(3);
  }

  /* 轻提示：安卓壳走原生 Toast，PC 落状态栏 */
  function toast(msg) {
    if (window.CLMobile && window.CLMobile.toast) window.CLMobile.toast(msg);
    else setStatus(msg);
  }

  /* ------------------------------------------------- 缠论信号扫描（周期可选） */
  var SCAN = { period: 'daily', limit: 200, maxLag: 10, freshMs: 30 * 60 * 1000 };
  var LEVEL_CN = { 1: '一', 2: '二', 3: '三' };
  var TRACK_LIMIT = 800;    // 追踪现算时的取数根数：与看图一致，笔/中枢才对得上
  /* 1.8.0 心法定盘：日线定方向、30 分定时机。追踪不再跟随主图级别 ——
     级别一跟人走，「换级别重追」「看不到原来的卡」这类问题全都是它派生的。 */
  var TRACK_PERIOD = 'daily';
  var TIMING_PERIOD = '30m';
  var TIMING_FRESH_MS = 2 * 60 * 1000;   // 30 分时机检查的间隔抑制（数据源另有 45s 缓存）
  var sigCache = {};        // '<period>|<code>' -> 追踪现算出来的信号（不污染扫描缓存）

  var scanBtnEl = document.getElementById('scanBtn');

  /** 扫描周期在设置面板「自选扫描」分组里改，这里是唯一同步点 */
  function syncScanPeriod(params) {
    var p = (params && params.scanPeriod) || null;
    if (!p || p === SCAN.period) return;
    SCAN.period = p;
    if (scanBtnEl) scanBtnEl.title = '扫描自选列表最新 ' + (PERIOD_LABEL[p] || p) +
                                    ' 缠论信号（Shift+点击强制重扫）';
    loadScanCache();   // 只读该周期缓存，零请求
  }

  /** 数据源在设置面板「数据」分组里改，这里是唯一同步点 */
  function syncDataSource(params) {
    if (!CLMarket.setSource) return false;
    var want = (params && params.dataSource) || 'auto';
    if (want === CLMarket.getSource()) return false;
    CLMarket.setSource(want);
    return true;                       // 变了 → 需要丢掉缓存重新取数
  }

  function loadScanCache() {
    return CLScanner.loadFor(SCAN.period).then(function (items) {
      signals = items || {};
      renderWatchlist();
      return signals;
    }).catch(function () { return {}; });
  }

  /** force=true 忽略「30 分钟内已扫过」的缓存，全部重扫 */
  function runScan(force) {
    if (scanBusy) { setStatus('正在扫描中，稍等…'); return; }
    var codes = watchlist.map(function (w) { return w.code; });
    if (!codes.length) { setStatus('自选列表是空的，先加几只'); return; }
    scanBusy = true;
    if (scanBtnEl) { scanBtnEl.textContent = '扫描中…'; scanBtnEl.style.opacity = '.6'; }
    var st = panel ? panel.getState() : {};
    var done = 0, found = 0, skipped = 0;
    CLScanner.scan(codes, {
      period: SCAN.period, limit: SCAN.limit, maxLag: SCAN.maxLag, freshMs: SCAN.freshMs,
      params: st.params || {}, adjust: st.adjust == null ? 1 : st.adjust,
      concurrency: 3, force: !!force,
      onResult: function (code, sig) {          // 出一个渲染一个，不等全部跑完
        signals[code] = sig;
        if (sig && !sig.none) found++;
        renderWatchlist();
      },
      onProgress: function (d, total, skip) {
        done = d; skipped = skip;
        setStatus('扫描 ' + SCAN.period + ' 缠论信号：' + d + '/' + total +
                  (skip ? '，缓存跳过 ' + skip + ' 只' : ''));
      }
    }).then(function (all) {
      signals = all;
      renderWatchlist();
      var n = Object.keys(all).filter(function (c) { return all[c] && !all[c].none; }).length;
      setStatus('扫描完成（' + SCAN.period + ' · 每只 ' + SCAN.limit + ' 根）：共 ' +
                Object.keys(all).length + ' 只，其中 ' + n + ' 只有信号。' +
                (skipped ? '（缓存跳过 ' + skipped + ' 只，Shift+点击可强制重扫）' : ''));
    }).catch(function (e) {
      setStatus('扫描失败：' + (e && e.message || e), true);
    }).then(function () {
      scanBusy = false;
      if (scanBtnEl) { scanBtnEl.textContent = '扫信号'; scanBtnEl.style.opacity = ''; }
    });
  }

  if (scanBtnEl) {
    scanBtnEl.addEventListener('click', function (e) {
      runScan(e && e.shiftKey);   // Shift+点击 = 忽略缓存强制重扫
    });
  }

  /* ------------------------------------------------- 分类名输入弹层（新建/重命名） */
  var catModalEl = document.getElementById('catModal');
  var catNameEl = document.getElementById('catName');
  var catHeadEl = document.getElementById('catModalHead');
  var catErrEl = document.getElementById('catErr');

  function askCatName(title, def, cb, excludeId) {
    catHeadEl.textContent = title;
    catNameEl.value = def || '';
    catErrEl.textContent = '';
    catModalEl.classList.remove('hidden');
    catNameEl.focus(); catNameEl.select();
    catNameEl.onkeydown = function (e) {
      if (e.key === 'Escape') { e.preventDefault(); finishCatName(null); }
      else if (e.key === 'Enter') { e.preventDefault(); confirmCatName(); }
    };
    function finish(v) {
      catModalEl.classList.add('hidden');
      catNameEl.onkeydown = null;
      cb && cb(v);
    }
    catNameEl._finish = finish;
    catNameEl._exclude = excludeId;
  }
  function finishCatName(v) { catNameEl._finish && catNameEl._finish(v); }
  function confirmCatName() {
    var v = (catNameEl.value || '').trim();
    if (!v) { catErrEl.textContent = '名字不能为空'; return; }
    var ex = catNameEl._exclude;
    var dup = cats.some(function (c) { return c.id !== ex && c.id !== UNCAT && c.name === v; });
    if (dup) { catErrEl.textContent = '已有同名分类'; return; }
    finishCatName(v);
  }
  if (catModalEl) {
    document.getElementById('catOk').addEventListener('click', confirmCatName);
    document.getElementById('catCancel').addEventListener('click', function () { finishCatName(null); });
    catModalEl.addEventListener('click', function (e) { if (e.target === catModalEl) finishCatName(null); });
  }

  function newCat(then) {
    askCatName('新建分类', '', function (name) {
      if (!name) return;
      var c = { id: 'c' + (catSeq++), name: name, closed: false };
      cats.push(c);
      saveCats(); renderWatchlist();
      then && then(c.id);
    });
  }

  function renameCat(id) {
    var c = null;
    for (var i = 0; i < cats.length; i++) if (cats[i].id === id) c = cats[i];
    if (!c || c.id === UNCAT) return;
    askCatName('重命名分类', c.name, function (name) {
      if (!name) return;
      c.name = name;
      saveCats(); renderWatchlist();
    }, c.id);
  }

  function dropCat(id) {
    var c = null, idx = -1;
    for (var i = 0; i < cats.length; i++) if (cats[i].id === id) { c = cats[i]; idx = i; }
    if (!c || c.id === UNCAT) return;
    var n = itemsOf(id).length;
    if (!window.confirm('删除分类「' + c.name + '」？' + (n ? '其中 ' + n + ' 只标的会移到「未分类」，' : '') + '标的本身不会删除。')) return;
    watchlist.forEach(function (w) { if ((w.cat || UNCAT) === id) w.cat = UNCAT; });
    cats.splice(idx, 1);
    if (activeCat === id) activeCat = UNCAT;
    saveCats(); saveWatchlist(); renderWatchlist();
    setStatus('已删除分类「' + c.name + '」');
  }

  function moveTo(code, id) {
    var w = null;
    for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === code) w = watchlist[i];
    if (!w) return;
    w.cat = id;
    saveWatchlist(); renderWatchlist();
    setStatus('已把 ' + (w.name || w.code) + ' 移到「' + catName(id) + '」');
  }

  function delOne(code) {
    var w = null, idx = -1;
    for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === code) { w = watchlist[i]; idx = i; }
    if (!w) return;
    watchlist.splice(idx, 1);
    saveWatchlist(); renderWatchlist();
    setStatus('已从自选删除 ' + (w.name || w.code));
  }

  /* ------------------------------------------------------------- 右键菜单 */
  var ctxEl = document.getElementById('ctxMenu');
  function showCtx(e, entries) {
    ctxEl.innerHTML = '';
    entries.forEach(function (en) {
      if (en.sep) { var s = document.createElement('div'); s.className = 'app-ctx-sep'; ctxEl.appendChild(s); return; }
      var d = document.createElement('div');
      d.className = 'app-ctx-item' + (en.danger ? ' danger' : '') + (en.disabled ? ' disabled' : '');
      d.textContent = en.label;
      if (!en.disabled) d.addEventListener('click', function () { hideCtx(); en.fn && en.fn(); });
      ctxEl.appendChild(d);
    });
    ctxEl.classList.remove('hidden');
    ctxEl.style.left = e.clientX + 'px';
    ctxEl.style.top = e.clientY + 'px';
    var r = ctxEl.getBoundingClientRect();
    if (r.right > window.innerWidth) ctxEl.style.left = Math.max(2, window.innerWidth - r.width - 4) + 'px';
    if (r.bottom > window.innerHeight) ctxEl.style.top = Math.max(2, window.innerHeight - r.height - 4) + 'px';
  }
  function hideCtx() { if (ctxEl) ctxEl.classList.add('hidden'); }
  document.addEventListener('mousedown', function (e) { if (ctxEl && !ctxEl.contains(e.target)) hideCtx(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideCtx(); });
  window.addEventListener('resize', hideCtx);

  /* ------------------------------------------------------------------ 自选股 */
  function loadAll(cb) { loadCats(function () { loadWatchlist(cb); }); }

  function loadWatchlist(cb) {
    chrome.storage.local.get(WL_KEY, function (box) {
      var arr = box && box[WL_KEY];
      watchlist = Array.isArray(arr) ? arr.filter(function (x) { return x && x.code; }) : [];
      watchlist.forEach(function (w) { if (w.cat === undefined) w.cat = UNCAT; });
      cb && cb();
    });
  }

  function saveWatchlist() {
    var box = {}; box[WL_KEY] = watchlist;
    try { chrome.storage.local.set(box); } catch (e) { /* 忽略 */ }
  }

  function renderWatchlist() {
    updateAddBtn();           // 按钮 +/− 状态跟列表与当前标的走，空列表早退前也要刷
    listEl.innerHTML = '';
    if (!watchlist.length) {
      var empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = '还没有自选股';
      listEl.appendChild(empty);
      return;
    }

    cats.forEach(function (c) {
      var items = itemsOf(c.id);

      /* ---- 分组头：点击折叠/展开并设为默认落点，右键重命名/删除，可接收拖拽 ---- */
      var gh = document.createElement('li');
      gh.className = 'grp' + (c.closed ? ' closed' : '') + (c.id === activeCat ? ' grp-active' : '');
      gh.title = '点击折叠/展开；高亮表示「+自选」「批量导入」默认加到这个分类';
      var caret = document.createElement('span');
      caret.className = 'grp-caret';
      caret.textContent = c.closed ? '▸' : '▾';
      var gnm = document.createElement('span');
      gnm.className = 'grp-name';
      gnm.textContent = c.name;
      var gct = document.createElement('span');
      gct.className = 'grp-count';
      gct.textContent = items.length;
      gh.appendChild(caret); gh.appendChild(gnm); gh.appendChild(gct);

      gh.addEventListener('click', function () {
        c.closed = !c.closed;
        activeCat = c.id;
        saveCats(); renderWatchlist();
      });
      gh.addEventListener('contextmenu', function (e) {
        e.preventDefault();
        var ents = [
          { label: '新建分类…', fn: function () { newCat(); } }
        ];
        if (c.id !== UNCAT) {
          ents.push({ label: '重命名…', fn: function () { renameCat(c.id); } });
          ents.push({ label: '删除分类', danger: true, fn: function () { dropCat(c.id); } });
        } else {
          ents.push({ label: '「未分类」不可改名/删除', disabled: true });
        }
        ents.push({ sep: true });
        ents.push({ label: c.closed ? '展开' : '折叠', fn: function () { c.closed = !c.closed; saveCats(); renderWatchlist(); } });
        ents.push({ label: '设为默认落点', disabled: c.id === activeCat, fn: function () { activeCat = c.id; renderWatchlist(); } });
        showCtx(e, ents);
      });
      gh.addEventListener('dragover', function (e) { e.preventDefault(); gh.classList.add('drop'); });
      gh.addEventListener('dragleave', function () { gh.classList.remove('drop'); });
      gh.addEventListener('drop', function (e) {
        e.preventDefault();
        gh.classList.remove('drop');
        var code = (e.dataTransfer && e.dataTransfer.getData('text/plain')) || dragCode;
        if (code) moveTo(code, c.id);
      });
      listEl.appendChild(gh);

      if (c.closed) return;

      /* ---- 组内标的 ---- */
      items.forEach(function (item) {
        var li = document.createElement('li');
        li.className = 'item' + (item.code === current.code ? ' active' : '');
        li.draggable = true;
        var top = document.createElement('span');
        top.className = 'top';
        var nm = document.createElement('span');
        nm.className = 'nm';
        nm.textContent = item.name || item.code;
        top.appendChild(nm);

        var sg = signals[item.code];
        if (sg && !sg.none) {
          var badge = document.createElement('span');
          /* 1.9.0：三买=回测唯一有统计优势的信号 → prime 高亮；一/二买 title 标注「参考」 */
          var prime = sg.level === 3 && sg.type > 0;
          badge.className = 'sig ' + (sg.type > 0 ? 'buy' : 'sell') +
            (sg.confirmed ? '' : ' fresh') + (prime ? ' prime' : '');
          badge.textContent = (LEVEL_CN[sg.level] || sg.level) + (sg.type > 0 ? '买' : '卖');
          badge.title = (PERIOD_LABEL[sg.period] || sg.period || '') + '：' + (sg.note || '') +
                        (prime ? '\n★ 回测验证：唯一有统计优势的信号（ETF 日线 10d +0.76%，t=2.54）'
                               : (sg.type > 0 ? '\n参考：回测无可测优势，作结构参照' : '')) +
                        '\n信号成立 K：' + (sg.t || sg.readyK) + '（滞后 ' + sg.lag + ' 根）' +
                        (sg.ratio != null ? '\n背驰力度比：' + sg.ratio.toFixed(2) : '') +
                        '\n标记价：' + sg.price + (sg.confirmed ? '' : '\n未确认：分型右侧可能修订');
          top.appendChild(badge);
        }

        // 追踪徽标（1.6.0）：长按列表项可查看计划/取消
        var tr = trackMap[item.code];
        if (tr) {
          var tb = document.createElement('span');
          tb.className = 'sig track';
          tb.textContent = tr.dir > 0 ? '追多' : '追空';
          tb.title = (tr.dir > 0 ? '做多 ▲' : '做空 ▼') + ' · ' +
                     (CLTrack.PERIOD_CN[tr.period] || tr.period) + '\n' +
                     (tr.lines || []).join('\n');
          top.appendChild(tb);
        }

        var cd = document.createElement('span');
        cd.className = 'cd';
        cd.textContent = item.code;
        var row = document.createElement('span');
        row.className = 'row';
        row.appendChild(cd);
        var pc = document.createElement('span');
        var pct = quotes[item.code] ? quotes[item.code].pct : null;
        pc.className = 'pc' + (pct == null || !isFinite(pct) ? ' flat'
                              : pct > 0 ? ' up' : pct < 0 ? ' down' : ' flat');
        pc.textContent = fmtPct(pct);
        pc.title = '最新日K涨跌幅（打开时拉取，10 分钟兜底刷新；看图直接刷新页面）';
        row.appendChild(pc);
        li.appendChild(top); li.appendChild(row);
        li.addEventListener('click', function () { setCurrent(item.code, item.name); });
        li.addEventListener('dragstart', function (e) {
          dragCode = item.code;
          li.classList.add('dragging');
          if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', item.code); }
        });
        li.addEventListener('dragend', function () { dragCode = null; li.classList.remove('dragging'); });

        // 手机长按 = 右键：mobile/cats.js 已把列表项长按合成为 contextmenu，
        // 这里只管菜单内容（追踪条目置顶，分类/删除沿用），两端一份逻辑。
        li.addEventListener('contextmenu', function (e) {
          e.preventDefault();
          openItemMenu(item, e.clientX, e.clientY);
        });
        listEl.appendChild(li);
      });
    });
  }

  /* ------------------------------------------------------------ 批量删除 */
  var delModalEl = document.getElementById('delModal');
  var delListEl = document.getElementById('delList');
  var delStatEl = document.getElementById('delStat');
  var delToggleEl = document.getElementById('delToggle');

  function pickedCodes() {
    var out = [];
    delListEl.querySelectorAll('input[type=checkbox]').forEach(function (ck) {
      if (ck.checked) out.push(ck.value);
    });
    return out;
  }

  function syncDelStat() {
    var n = pickedCodes().length, total = delListEl.querySelectorAll('input').length;
    delStatEl.textContent = '已选 ' + n + ' / 共 ' + total + ' 只';
    delToggleEl.textContent = (n === total && total > 0) ? '全不选' : '全选';
  }

  function openDel() {
    if (!watchlist.length) { panel.setStatus('自选股列表是空的'); return; }
    delListEl.innerHTML = '';
    orderedItems().forEach(function (w) {
      var lab = document.createElement('label');
      var ck = document.createElement('input');
      ck.type = 'checkbox'; ck.value = w.code; ck.checked = true;
      ck.addEventListener('change', syncDelStat);
      var nm = document.createElement('span'); nm.textContent = w.name || w.code;
      var ct = document.createElement('span'); ct.className = 'cat'; ct.textContent = catName(w.cat);
      var cd = document.createElement('span'); cd.className = 'code'; cd.textContent = w.code;
      lab.appendChild(ck); lab.appendChild(nm); lab.appendChild(ct); lab.appendChild(cd);
      delListEl.appendChild(lab);
    });
    buildDelCats();
    syncDelStat();
    delModalEl.classList.remove('hidden');
    var first = delListEl.querySelector('input');
    if (first) first.focus();
  }

  /** 「按分类快选」：点分类 chip = 只勾该类（再点同一个恢复全选）。
   *  只动勾选，确认删除仍走 doDelete —— 删的是自选，cats 本身一个不动，
   *  删空了的分类保留（删除分类是「分类管理」里的独立功能）。 */
  function buildDelCats() {
    var row = document.getElementById('delCatRow');
    if (!row) return;
    row.innerHTML = '';
    var setChecked = function (fn) {
      delListEl.querySelectorAll('input[type=checkbox]').forEach(function (ck) {
        ck.checked = !!fn(ck.value);
      });
      syncDelStat();
    };
    var add = function (label, pickFn, onFn) {
      var s = document.createElement('span');
      s.className = 'app-dcat';
      s.textContent = label;
      s.addEventListener('click', function () {
        var already = onFn && onFn();
        setChecked(already ? function () { return true; } : pickFn);
      });
      row.appendChild(s);
    };
    add('全部', function () { return true; });
    cats.forEach(function (c) {
      var items = itemsOf(c.id);
      if (!items.length) return;           // 空分类没有可删的，不显示
      var codes = {}; items.forEach(function (w) { codes[w.code] = 1; });
      add(c.name + ' ' + items.length,
          function (code) { return !!codes[code]; },
          function () {
            var picked = pickedCodes();
            return picked.length === items.length &&
                   picked.every(function (code) { return codes[code]; });
          });
    });
  }

  function closeDel() { delModalEl.classList.add('hidden'); }

  function doDelete() {
    var kill = pickedCodes();
    if (!kill.length) { delStatEl.textContent = '没有勾选任何标的'; return; }
    var map = {}; kill.forEach(function (c) { map[c] = 1; });
    var cnt = 0;
    watchlist = watchlist.filter(function (w) { if (map[w.code]) { cnt++; return false; } return true; });
    closeDel();
    saveWatchlist(); renderWatchlist();
    panel.setStatus('已删除 ' + cnt + ' 只自选股');
  }

  if (delBtnEl) {
    delBtnEl.addEventListener('click', openDel);
    document.getElementById('delCancel').addEventListener('click', closeDel);
    document.getElementById('delOk').addEventListener('click', doDelete);
    delToggleEl.addEventListener('click', function () {
      var all = delListEl.querySelectorAll('input');
      var n = pickedCodes().length;
      var on = n !== all.length;              // 全选 / 全不选 切换
      all.forEach(function (ck) { ck.checked = on; });
      syncDelStat();
    });
    delModalEl.addEventListener('click', function (e) { if (e.target === delModalEl) closeDel(); });
    document.addEventListener('keydown', function (e) {
      if (delModalEl.classList.contains('hidden')) return;
      if (e.key === 'Escape') closeDel();
      else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doDelete(); }
    });
  }

  function addToWatchlist(code, name) {
    if (!code) return;
    for (var i = 0; i < watchlist.length; i++) {
      if (watchlist[i].code === code) {
        if (name) watchlist[i].name = name;
        saveWatchlist(); renderWatchlist();
        return true;
      }
    }
    watchlist.push({ code: code, name: name || '' });
    saveWatchlist(); renderWatchlist();
    return true;
  }

  /* ------------------------------------------------------------ 批量导入 */
  /**
   * 解析粘贴文本：一行一个，或逗号/分号/空格分隔，支持前缀与混写名称
   *   600519 / SH600519 / sh.600519 / 600519 贵州茅台 / 000001,300750
   * @returns {{items:{code,name}[], bad:string[]}}
   */
  function parseCodes(text) {
    var items = [], bad = [], seen = {};
    String(text || '').split(/[\r\n,，;；、|]+/).forEach(function (seg) {
      var s = String(seg || '').trim();
      if (!s) return;
      // 一段里如果藏着多个代码（空格分隔），逐个取出
      var m = s.match(/\d{6}/g);
      if (!m) { bad.push(s); return; }
      m.forEach(function (code) {
        if (seen[code]) return;
        seen[code] = 1;
        items.push({ code: code, name: '' });
      });
      // 名称：最后一个代码之后的中文/字母部分
      if (m.length === 1) {
        var nm = s.replace(/\d{6}/, ' ')
                  .replace(/^(sh|sz|bj)[\.:\-]?/i, ' ')
                  .replace(/^[()\[\]（）"'·,:：\s]+|[()\[\]（）"'·,，:：\s]+$/g, '')
                  .trim();
        if (nm && nm.length <= 12) items[items.length - 1].name = nm;
      }
    });
    return { items: items, bad: bad };
  }

  /** 并发补全缺失名称，逐条刷新列表并写回 storage（否则重启后名称丢失） */
  function nameMissing(w) { return !w.name || w.name === w.code; }
  function resolveMissingNames(limit) {
    var queue = watchlist.filter(nameMissing).slice(0, limit || 40);
    if (!queue.length) return;
    var idx = 0, CONC = 4, dirty = false, done = 0;
    function flush() { if (dirty) { dirty = false; saveWatchlist(); } }
    function worker() {
      if (idx >= queue.length) { flush(); return Promise.resolve(); }
      var item = queue[idx++];
      return fetchName(item.code)
        .then(function (q) {
          if (q && q.name) { item.name = q.name; dirty = true; renderWatchlist(); }
        })
        .catch(function () { /* 拿不到名字不影响 */ })
        .then(function () { if (++done % 8 === 0) flush(); return worker(); });
    }
    for (var k = 0; k < CONC; k++) worker();
  }

  function importBulk(items, cat) {
    var added = 0, updated = 0;
    var to = (cat === undefined || cat === null) ? activeCat : cat;
    items.forEach(function (it) {
      var hit = null;
      for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === it.code) hit = watchlist[i];
      if (hit) {
        if (it.name && !hit.name) { hit.name = it.name; updated++; }
        if (to && !hit.cat) hit.cat = to;
        return;
      }
      watchlist.push({ code: it.code, name: it.name || '', cat: to });
      added++;
    });
    saveWatchlist();
    renderWatchlist();
    resolveMissingNames(40);
    refreshQuotes();
    return { added: added, updated: updated };
  }

  /* ---------------------------------------------------------------- 当前标的 */
  function setCurrent(code, name) {
    code = String(code || '').trim();
    if (!/^\d{6}$/.test(code)) return;
    current.code = code;
    current.name = name || '';
    datasets = {};
    renderWatchlist();
    updateHeader();
    if (!current.name) {
      fetchName(code)
        .then(function (q) { if (q && q.name) { current.name = q.name; updateHeader(); renderWatchlist(); } })
        .catch(function () { updateHeader(); /* 名字拿不到不影响看图 */ });
    }
    rebuild();
  }

  function updateHeader() {
    curNameEl.textContent = current.name || (current.code ? '（未取名）' : '未选择标的');
    curCodeEl.textContent = current.code || '';
  }

  /* ------------------------------------------------------------------ 图表区 */
  function chartHeights() {
    var vh = Math.max(520, window.innerHeight || 720);
    var avail = Math.max(320, vh - 190);
    return [Math.round(avail * 0.5), Math.round(avail * 0.25), Math.round(avail * 0.25)];
  }

  async function loadPeriod(period) {
    if (!period) return null;
    if (datasets[period] && datasets[period].code === current.code) return datasets[period];
    var st = panel.getState();
    var data = await CLDataSource.getKlines(current.code, period, 800, st.adjust);
    CLDataSource.withTimestamps(data);
    datasets[period] = data;
    return data;
  }

  async function rebuild() {
    var st = panel.getState();
    try {
      if (!current.code) { panel.setStatus('请在顶栏输入代码或从自选股里选一只', true); return; }
      panel.setStatus('正在获取行情…');
      var periods = st.levels.filter(Boolean);
      if (!periods.length) { panel.setStatus('请至少选择一个周期', true); return; }

      var loaded = [];
      for (var i = 0; i < periods.length; i++) {
        var d = await loadPeriod(periods[i]);
        if (d) loaded.push(d);
      }
      if (!loaded.length) throw new Error('没有拿到任何行情数据');

      panel.setSub((loaded[0].name || current.name || '') + ' ' + current.code);

      views = [];
      var canvases = panel.activeCanvases().map(function (h) { return h.canvas; });
      var stats = [];
      for (var j = 0; j < loaded.length && j < canvases.length; j++) {
        var data = loaded[j];
        var res = ChanEngine.analyze(data.klines, st.params);
        var shown = st.params.klineMode === 'merged'
          ? CLMergedView.build(data.klines, res)      // 缠论K线（含包处理后），判定不变
          : { klines: data.klines, result: res };
        var view = CLRenderer.create(canvases[j], {
          defaultBars: j === 0 ? 160 : 320,
          layers: st.layers,
          onZoom: onZoom,
          onPan: onPan,
          onNoteTap: onNoteTap
        });
        view.setData({ klines: shown.klines, period: data.period, code: data.code, name: data.name,
                       result: shown.result, mergedBars: st.params.klineMode === 'merged' });
        advanceTrackTrail(data, res);           // 动盈/目标随新数据推进（只朝有利方向）
        applyTrackToView(view);                 // 追踪价位线/短文案（额外）
        view.draw();
        views.push(view);
        stats.push(PERIOD_LABEL[data.period] + ' 笔' + res.bis.length +
                   ' / 段' + res.segs.length + ' / 中枢' + res.zhongshus.length +
                   ' / 背驰' + res.divergences.length + ' / 点' + res.points.length);
      }
      var srcName = CLMarket.sourceLabel ? CLMarket.sourceLabel(loaded[0].source)
                                         : (loaded[0].source === 'sina' ? '新浪财经' : '东方财富');
      // 末端从别的源补过时要说出来：否则用户看到「多出一根」会以为是乱跳
      var fix = loaded[0].tailFix;
      var fixNote = '';
      if (fix) {
        var nm = function (id) { return CLMarket.sourceLabel ? CLMarket.sourceLabel(id) : id; };
        fixNote = fix.rejected
          ? '（' + nm(fix.from) + ' 末尾落后，但 ' + nm(fix.to) + ' 数据基准对不上，未追加）'
          : fix.gap
          ? '（缺口超过 ' + (CLMarket.TAIL_PROBE_N || 30) + ' 根，未自动补；长按「重算」强刷）'
          : '（' + nm(fix.from) + ' 未更新，已从 ' + nm(fix.to) + ' 补 ' + fix.n + ' 根）';
      }
      /* 1.8.0 追踪恒按日线（心法：日线定方向、30 分定时机）。切到别的级别看盘时
         价位线不画，不明说会以为追踪丢了 —— 状态栏念一句它属于日线。 */
      var tp = trackMap[current.code];
      var trackNote = (tp && tp.period !== periods[0])
        ? '　|　追踪：日线级别（价位线在日线图）' : '';
      panel.setStatus(stats.join('　|　') + trackNote +
                      '\n滚轮缩放 · 拖拽平移 · 「全览」看全部 · 三图联动按同比缩放 · 数据来源 ' +
                      srcName + fixNote);
      // 追踪动态盯梢：图表重算后顺手核对一次（列表侧由行情刷新触发）
      var lastKs = loaded[0].klines;
      if (lastKs && lastKs.length) checkTrackAlerts(lastKs[lastKs.length - 1].c);
      checkTimingAll();   // 30 分时机顺带查一轮（内部有间隔抑制）
    } catch (e) {
      panel.setStatus('出错：' + (e && e.message || e), true);
    }
  }

  /* ------------------------------------------------------------ 缠论追踪（1.6.0 → 1.8.0）
   * 追踪记录 trackMap[code] → { dir, period, level/type/note, markK, entry, stop,
   * stopRule, target, trail, lines, timing, createdAt, alerted*, timingCheckedAt }。
   * 图上的价位线（目标/失效/动盈）+ 短文案都属「额外」，extraOn 控制。
   *
   * 1.7.1：把「止盈」拆成两件事 —— 目标（前高，到价减 1/3）与动盈（跟踪止损，
   *   在价格下方，只上移不下移）。动盈只在跑出浮盈后才存在，信号刚出时 rec.trail
   *   为 null，图上就不画这条线（那时它贴着失效位，画出来只会误导）。
   *
   * 1.8.0 两条硬性规则（取代 1.7.0 的「级别跟主图走」）：
   *   ① 级别恒为日线（心法：日线定方向、30 分定时机），30 分信号记入 rec.timing；
   *   ② 方向 = 信号自带（买点做多 / 卖点做空），不再让用户选看多还是看空。
   * 跟踪推进走 CLScanner.refsFor（只认方向），不再依赖 pickSignal —— 日线后来
   * 转出反向信号时（多头持仓后出顶背驰），跟踪线照常推进，不会冻结。 */

  /** 同步取该级别下的信号。优先级：
   *   ① 当前已加载的图数据（零请求，和画面上画的笔/中枢完全一套）
   *   ② 本次会话现算过的（ensureSignal 缓存）
   *   ③ 扫描缓存 —— 只在还新鲜（freshMs 内）时用，过期的不拿来凑数
   *   都没有 → null，交给 ensureSignal 现拉一次。 */
  function signalOf(code, period) {
    var d = datasets[period];
    if (d && d.code === code && d.klines && d.klines.length) {
      var st = panel.getState();
      var res = ChanEngine.analyze(d.klines, st.params);
      var fromChart = CLScanner.pickSignal(d.klines, res, { maxLag: SCAN.maxLag });
      if (fromChart) return fromChart;
    }
    var c = sigCache[period + '|' + code];
    if (c) return c.none ? null : c;
    var s = signals[code];
    if (s && !s.none && s.period === period && s.ts && (Date.now() - s.ts) < SCAN.freshMs) return s;
    return null;
  }

  /** 取不到就现拉一次（与看图同根数，保证笔/中枢和画面一致），并缓存住。
   *  取数失败返回 { failed: true } —— 必须跟「这个级别真没信号」区分开，
   *  否则用户点「追踪」只看到一句「暂无买卖点」，会当成功能坏了。 */
  function ensureSignal(code, period) {
    var s = signalOf(code, period);
    if (s) return Promise.resolve(s);
    var st = panel.getState();
    return CLDataSource.getKlines(code, period, TRACK_LIMIT, st.adjust)
      .then(function (d) {
        CLDataSource.withTimestamps(d);
        var ks = (d && d.klines) || [];
        if (!ks.length) return { failed: true, empty: true };
        var res = ChanEngine.analyze(ks, st.params);
        var sig = CLScanner.pickSignal(ks, res, { maxLag: SCAN.maxLag });
        if (sig) { sig.ts = Date.now(); sig.period = period; }
        sigCache[period + '|' + code] = sig || { none: true, period: period };
        return sig;
      })
      .catch(function (e) { return { failed: true, err: (e && e.message) || String(e) }; });
  }

  function applyTrackToView(view) {
    view.planLines = null;
    view.planNote = null;
    view.planNote2 = null;
    if (!extraOn) return;
    var rec = trackMap[current.code];
    if (!rec || !view.data || view.data.period !== rec.period) return;
    var lines = [];
    /* 目标在有利方向的上/下方，到价减 1/3 —— 这才是「止盈」 */
    if (rec.target != null)
      lines.push({ price: rec.target, color: '#a8631f', label: '目标' });
    /* 参考（入场价）只在作战卡里写，图上不画：它冻在建卡那一刻，画出来只是多一条线 */
    if (rec.stop != null)
      lines.push({ price: rec.stop, color: '#b02b2b', label: '失效' });
    /* 动盈 = 跟踪止损，在价格下方（空头在上方），只有跑出浮盈后才会出现 */
    if (rec.trail != null)
      lines.push({ price: rec.trail, color: '#1e6e3c', label: '动盈' });
    if (lines.length) view.planLines = lines;
    /* 短文案要一屏放得下：级别+信号类型缩写，不塞完整 note。
       1.8.1：第一行写「参考」价（失效价图上已有红线，写出来是重复），
       点这一行直接开作战卡（renderer/touch.js 里做命中）。 */
    view.planNote = (rec.dir > 0 ? '▲多 ' : '▼空 ') +
      (CLTrack.PERIOD_CN[rec.period] || rec.period) + ' ' +
      (LEVEL_CN[rec.level] || rec.level) + (rec.type > 0 ? '买' : '卖') +
      (rec.entry != null ? ' ｜ 参考 ' + fmtPrice(rec.entry) : '');
    /* 第二行 = 状态行，所见即所做：主状态（取第一个命中，动词导向）+ 修饰（背景全拼）。
       主状态优先级：破失效 > 破动盈 > 到目标 > 时机已到 > 等时机 —— 已破失效后
       不再出现「等买点」这类矛盾提示。信号名一律取实际 note，不硬编码类型；
       配色沿用现有样式，警示靠文案不靠颜色。 */
    var main;
    if (rec.alertedStop && rec.stop != null)
      main = '已破失效 ' + fmtPrice(rec.stop) + ' · 离场';
    else if (rec.alertedTrail && rec.trail != null)
      main = '动盈位已破 · 清剩余';
    else if (rec.alertedTarget && rec.target != null)
      main = '已到目标 ' + fmtPrice(rec.target) + ' · 减1/3';
    else if (rec.timing)
      main = '时机已到：' + rec.timing.note + ' · 可进场';
    else
      main = '等30分同向' + (rec.dir > 0 ? '买' : '卖') + '点 · 不动手';
    var sfx = [];
    if (rec.reverse)
      sfx.push((rec.dir > 0 ? '日线转空' : '日线转多') + '（' + rec.reverse.note + '）· 仅提示');
    if (rec.timingFail)
      sfx.push('30分' + (rec.dir > 0 ? '买' : '卖') + '点已失效 · 重新等');
    if (rec.trail != null) sfx.push('动盈 ' + fmtPrice(rec.trail));
    if (rec.target == null) sfx.push('目标：等新结构');
    if (rec.confirmed === false) sfx.push('未定型');
    view.planNote2 = main + (sfx.length ? ' ｜ ' + sfx.join(' ｜ ') : '');
  }

  function applyTrackToViews() {
    views.forEach(function (v) { applyTrackToView(v); v.draw(); });
  }

  /** 动盈推进：每次重算后，用刚画出来的这份数据重算动盈/目标并回写记录。
   *  纯结构计算，不发新请求。动盈只朝有利方向走（CLTrack.advanceTrail 内部保证），
   *  所以信号刚出、还没跑出浮盈时它一直是 null —— 图上就不画这条线。 */
  function advanceTrackTrail(data, res) {
    var rec = trackMap[data.code];
    if (!rec || rec.period !== data.period) return;
    /* 1.8.0：走 refsFor（只认方向、不认信号）。pickSignal 挑的是「当前最佳信号」，
       行情走好后日线会转出反向信号（多头持仓后出顶背驰），跟着它换靶子，
       跟踪线就冻结了。动盈的「优于入场」用建卡时的 rec.entry 判。 */
    var rr = CLScanner.refsFor(data.klines, res, rec.dir,
                               rec.entry != null ? rec.entry : null, rec.markK);
    var changed = CLTrack.advanceTrail(rec, rec.dir > 0 ? rr.trailLow : rr.trailHigh);
    if (CLTrack.refreshTarget(rec, rec.dir > 0 ? rr.targetHigh : rr.targetLow)) changed = true;
    if (changed) CLTrack.save(trackMap);
  }

  /* ------------------------------------------------- 30 分时机 + 日线反向（1.8.0→1.8.1）
   * 心法：日线定方向、30 分定时机。对每只追踪中的标的定时做两件事：
   *   ① 拉 30 分数据现算：同向信号 → 记 rec.timing 提醒「时机到」（key 去重，
   *      同一信号反复算出不重报）；时机已到后又出**反向**信号 → 时机失效
   *      （failTiming 清 timing 回「在等」，报一次，自动去重）。
   *   ② 日线反向信号：多头持仓后日线出一卖（空头出一买）→ 提醒（updateReverse，
   *      key 去重；rec.reverse 保留最近一次，不随信号消失/同向清除，防横跳）。
   * 拉数失败静默跳过（下一轮再试）。force=true 忽略间隔抑制（测试/手动刷新）。 */
  function checkTimingAll(force) {
    var st = panel.getState();
    Object.keys(trackMap).forEach(function (code) {
      var rec = trackMap[code];
      if (!force && rec.timingCheckedAt && Date.now() - rec.timingCheckedAt < TIMING_FRESH_MS) return;
      rec.timingCheckedAt = Date.now();
      var onHit = function (r) {
        if (!r || !r.hit) return;
        CLTrack.save(trackMap);
        applyTrackToViews();   // 图上左上角的「时机」状态随手刷新
        toast((rec.name || code) + '：' + r.text);
        renderWatchlist();
      };
      /* ① 30 分时机 / 时机失效 */
      CLDataSource.getKlines(code, TIMING_PERIOD, 200, st.adjust).then(function (d) {
        CLDataSource.withTimestamps(d);
        var ks = (d && d.klines) || [];
        if (!ks.length) return;
        var res = ChanEngine.analyze(ks, st.params);
        var sig = CLScanner.pickSignal(ks, res, { maxLag: SCAN.maxLag });
        var r = CLTrack.updateTiming(rec, sig);
        if (!r.hit) r = CLTrack.failTiming(rec, sig);
        onHit(r);
      }).catch(function () { /* 取数失败下一轮再试，时机检查不该打扰人 */ });
      /* ② 日线反向信号（走 ensureSignal：主图已加载零请求，否则现拉带缓存） */
      ensureSignal(code, TRACK_PERIOD).then(function (sig) {
        if (!sig || sig.failed || sig.none) return;
        onHit(CLTrack.updateReverse(rec, sig));
      }).catch(function () {});
    });
  }

  /** 动态盯梢：现价触碰失效位/止盈位时提醒。priceOfCurrent 优先（实时 K 线收盘），
   *  其余追踪标的用行情快照价。hit 只报一次，标记写回记录。 */
  function checkTrackAlerts(priceOfCurrent) {
    var changed = false;
    Object.keys(trackMap).forEach(function (code) {
      var rec = trackMap[code];
      var px = (code === current.code && priceOfCurrent != null) ? priceOfCurrent
             : (quotes[code] && quotes[code].price != null ? quotes[code].price : null);
      if (px == null) return;
      var r = CLTrack.check(rec, px);
      if (r.hit) {
        if (r.hit === 'stop') rec.alertedStop = true;
        else if (r.hit === 'target') rec.alertedTarget = true;
        else rec.alertedTrail = true;
        changed = true;
        toast((rec.name || code) + '：' + r.text);
      }
    });
    if (changed) { CLTrack.save(trackMap); applyTrackToViews(); }  // 盯梢命中随手刷 HUD
  }

  /** 取消追踪 */
  function cancelTrack(code) {
    var rec = trackMap[code];
    CLTrack.del(trackMap, code);
    applyTrackToViews();
    renderWatchlist();
    setStatus(rec ? '已取消' + (CLTrack.PERIOD_CN[rec.period] || rec.period) + '追踪' : '已取消追踪');
  }

  /** 点图上左上角的追踪摘要 = 直接打开作战卡（1.8.1）。
   *  摘要只画在追踪记录所属级别（恒为日线）的那张图上，能点到就说明有计划可看；
   *  viewMode 打开的是已存计划，动态状态（时机/动盈/目标）按当前记录实时渲染。 */
  function onNoteTap() {
    if (!current.code) return;
    openTrackCard({ code: current.code, name: current.name }, true);
  }

  /* ---- 菜单：长按/右键共用。追踪条目置顶，分类/删除沿用原有条目 ---- */
  function openItemMenu(item, x, y) {
    var ents = [];
    var rec = trackMap[item.code];
    if (rec) {
      ents.push({ label: '追踪中：' + (rec.dir > 0 ? '做多 ▲' : '做空 ▼') + ' ' +
        (CLTrack.PERIOD_CN[rec.period] || rec.period) + ' ' + rec.note, disabled: true });
      ents.push({ label: '取消追踪', danger: true, fn: function () { cancelTrack(item.code); } });
      ents.push({ sep: true });
      /* 已追踪：这个入口就是「查看/重算计划」 */
      ents.push({ label: '查看计划（日线）',
                  fn: function () { openTrackCard(item, false); } });
    } else {
      /* 未追踪：恒按日线判方向（心法：日线定方向、30 分定时机）。
         日线无信号直接在标签上写明，点进去也会明确提示。 */
      var sg = signalOf(item.code, TRACK_PERIOD);
      var cached = sigCache[TRACK_PERIOD + '|' + item.code];
      var tag = (sg && !sg.none) ? ' · ' + (LEVEL_CN[sg.level] || sg.level) + (sg.type > 0 ? '买' : '卖')
                                 : ((cached && cached.none) ? ' · 无信号' : '');
      ents.push({ label: '追踪（日线' + tag + '）',
                  fn: function () { openTrackCard(item, false); } });
    }
    ents.push({ sep: true });
    cats.forEach(function (t) {
      if (t.id === (item.cat || UNCAT)) return;
      ents.push({ label: '移动到「' + t.name + '」', fn: function () { moveTo(item.code, t.id); } });
    });
    ents.push({ label: '新建分类并移入…', fn: function () { newCat(function (id) { moveTo(item.code, id); }); } });
    ents.push({ sep: true });
    ents.push({ label: '从自选中删除', danger: true, fn: function () { delOne(item.code); } });
    showCtx({ clientX: x, clientY: y, preventDefault: function () {} }, ents);
  }

  /* ---- 作战卡弹层 ---- */
  var trackModalEl = document.getElementById('trackModal');
  var trackHeadEl = document.getElementById('trackHead');
  var trackBodyEl = document.getElementById('trackBody');
  var trackDirRow = document.getElementById('trackDirRow');
  var trackOkBtn = document.getElementById('trackOk');
  var trackCtx = null;   // { item, viewMode, sig, period, plan }

  /**
   * 打开作战卡。签名兼容旧调用 openTrackCard(item, dir, viewMode)：
   * 第二个参数是布尔就是新的（只带 viewMode），数字则是旧的（方向已废弃）。
   * 1.8.0：追踪恒按**日线**（心法：日线定方向、30 分定时机），不再跟随主图级别。
   * 日线算不出信号、但标的已在追踪中 → 回退展示已存计划（只读）。
   */
  function openTrackCard(item, a, b) {
    var viewMode = (typeof a === 'boolean') ? a : !!b;
    var rec = trackMap[item.code];
    if (viewMode && !rec) return Promise.resolve(null);
    if (viewMode) {
      trackCtx = { item: item, viewMode: true, sig: null, period: rec.period, plan: null };
      showTrackModal();
      return Promise.resolve(rec);
    }
    var per = TRACK_PERIOD;
    var nm = item.name || item.code;
    setStatus('正在按日线计算「' + nm + '」的追踪计划…');
    return ensureSignal(item.code, per).then(function (sig) {
      if (sig && sig.failed) {
        // 取数失败 ≠ 没信号，必须说清楚，否则用户只会觉得「点了没反应」
        var msg = sig.empty ? '没取到' + nm + '的' + (PERIOD_LABEL[per] || per) + '数据'
                            : '取数失败：' + (sig.err || '网络或数据源异常');
        setStatus(msg + '，稍后重试', true);
        toast('「' + nm + '」' + msg);
        return null;
      }
      if (!sig || sig.none) {
        var rec0 = trackMap[item.code];
        if (rec0) {
          // 已追踪但日线现算不出信号（信号走完离开 maxLag 等）→ 展示存下来的计划
          var msgR = '「' + nm + '」日线暂无买卖点，下面显示的是已存的追踪计划';
          setStatus(msgR);
          trackCtx = { item: item, viewMode: true, sig: null, period: rec0.period, plan: null };
          showTrackModal();
          return rec0;
        }
        var msg2 = '「' + nm + '」日线暂无买卖点，等信号出现再追';
        setStatus(msg2, true);
        toast(msg2);
        return null;
      }
      trackCtx = { item: item, viewMode: false, sig: sig, period: sig.period || per, plan: null };
      showTrackModal();
      return sig;
    });
  }

  function showTrackModal() {
    if (!trackCtx) return;
    var ctx = trackCtx;
    ctx.plan = null;
    if (trackDirRow) trackDirRow.style.display = 'none';   // 1.7.0：方向由信号决定，不再选
    trackOkBtn.style.display = ctx.viewMode ? 'none' : '';
    document.getElementById('trackCancel').textContent = ctx.viewMode ? '关闭' : '取 消';
    renderTrackCard();
    trackModalEl.classList.remove('hidden');
  }

  /** 时机时间戳的短格式：MM-DD HH:mm */
  function fmtTs(ts) {
    var d = new Date(ts), p = function (n) { return n < 10 ? '0' + n : '' + n; };
    return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  /**
   * 作战卡状态区（1.8.0）：把「建卡定死的 / 还在等的 / 跟踪中动态的」分三行写清。
   * d: { dir, period, note, entry, stop, target, trail, timing }
   * 目的：打开卡就知道现在跟踪到哪一步、还有什么没出现，不用去图上找线。
   */
  function trackStatusHtml(d) {
    if (!d) return '';
    var long = d.dir > 0;
    var fixed = [];
    if (d.entry != null) fixed.push('参考 ' + fmtPrice(d.entry));
    if (d.stop != null) fixed.push('失效 ' + fmtPrice(d.stop));
    var h = '<div><b>已定</b>：' + (long ? '做多 ▲' : '做空 ▼') + ' · ' +
      (CLTrack.PERIOD_CN[d.period] || d.period) + ' ' + (d.note || '') +
      (fixed.length ? ' ｜ ' + fixed.join(' ｜ ') : '') + '</div>';
    /* 反向：最近一次日线反向信号（不随消失/同向清除，是「最后一次走坏」的存档）。
       1.9.0 降级为纯提示：回测证明翻转清仓是价值毁灭者，离场只看失效位/动盈 */
    if (d.reverse)
      h += '<div><b>反向</b>：日线 ' + d.reverse.note + '（' + fmtTs(d.reverse.ts) +
           '）· 仅提示，离场看失效/动盈</div>';
    var waits = [];
    waits.push(d.timing
      ? '<b>30分时机已到</b>：' + d.timing.note + '（' + fmtTs(d.timing.ts) + '）'
      : '30分同向' + (long ? '买' : '卖') + '点（入场时机）');
    if (d.trail == null) waits.push('动盈启动（等首个优于入场的回调低点）');
    h += '<div><b>' + (d.timing ? '时机' : '在等') + '</b>：' + waits.join('；') + '</div>';
    var dyn = [];
    dyn.push(d.target != null ? '目标 ' + fmtPrice(d.target) : '目标：前高已过，等新结构');
    dyn.push(d.trail != null ? '动盈 ' + fmtPrice(d.trail) + '（只朝有利方向移）' : '动盈：未启动');
    h += '<div><b>动态</b>：' + dyn.join(' ｜ ') + '</div>';
    /* 已报：盯梢提醒是「只报一次」的，报过之后卡里得有处可查，不然用户不知道
       是没触发还是触发过没看见 */
    var hits = [];
    if (d.timingFail) hits.push('30分时机失效（' + d.timingFail.note + ' ' + fmtTs(d.timingFail.ts) + '）');
    if (d.alertedTarget) hits.push('已到目标');
    if (d.alertedStop) hits.push('已破失效位');
    if (d.alertedTrail) hits.push('已触发动盈');
    if (hits.length) h += '<div><b>已报</b>：' + hits.join('；') + '（提醒过）</div>';
    return h;
  }

  /* 1.9.0：信号价值标注（回测 26 只 ETF 日线全历史）——三买唯一有统计优势，
     一/二买无可测优势只作结构参照。只在 UI 层标注，不动引擎口径。 */
  function sigTag(level, type) {
    if (level === 3 && type > 0) return '（回测验证）';
    if (level < 3 && type > 0) return '（参考）';
    return '';
  }

  function renderTrackCard() {
    var ctx = trackCtx;
    if (!ctx) return;
    var meta, status = '', items, warn = '';
    if (ctx.viewMode) {
      var rec = trackMap[ctx.item.code];
      trackHeadEl.textContent = '缠论追踪 · 计划';
      meta = '<b class="' + (rec.dir > 0 ? 'up' : 'dn') + '">' + (rec.dir > 0 ? '做多 ▲' : '做空 ▼') + '</b> · ' +
        (CLTrack.PERIOD_CN[rec.period] || rec.period) + ' ' + rec.note +
        sigTag(rec.level, rec.type) +
        ' · ' + new Date(rec.createdAt).toLocaleDateString() +
        (rec.confirmed ? '' : ' · <b>未定型</b>');
      status = trackStatusHtml(rec);
      items = (rec.lines || []).map(function (s) { return '<li>' + s + '</li>'; }).join('');
    } else {
      var sig = ctx.sig;
      ctx.period = sig.period || ctx.period;
      ctx.plan = CLTrack.buildPlan(sig, null, ctx.period, { fmtPrice: fmtPrice });
      ctx.dir = ctx.plan.dir;
      trackHeadEl.textContent = '缠论追踪 · 作战卡';
      meta = '<b class="' + (ctx.plan.dir > 0 ? 'up' : 'dn') + '">' +
        (ctx.plan.dir > 0 ? '做多 ▲' : '做空 ▼') + '</b>（方向由' +
        (sig.type > 0 ? '买点' : '卖点') + '决定） · ' +
        (ctx.item.name || ctx.item.code) + ' ' + ctx.item.code + ' · ' +
        (PERIOD_LABEL[ctx.period] || ctx.period || '') + ' ' + sig.note +
        sigTag(sig.level, sig.type) +
        '<br>参考入场（现价口径）：<b>' + fmtPrice(ctx.plan.entry) + '</b>' +
        (sig.ratio != null ? ' · 背驰力度比 ' + sig.ratio.toFixed(2) : '');
      status = trackStatusHtml({ dir: ctx.plan.dir, period: ctx.period, note: sig.note,
        entry: ctx.plan.entry, stop: ctx.plan.stop,
        target: ctx.plan.target, trail: ctx.plan.trail, timing: null });
      items = ctx.plan.lines.map(function (s) { return '<li>' + s + '</li>'; }).join('');
      if (!sig.confirmed)
        warn = '<div class="tk-warn">⚠ 信号未定型：分型右侧可能修订，确认前等 readyK+1 根走完。</div>';
    }
    trackBodyEl.innerHTML = '<div class="tk-meta">' + meta + '</div>' +
      (status ? '<div class="tk-meta">' + status + '</div>' : '') +
      '<ol>' + items + '</ol>' + warn;
  }

  trackOkBtn.addEventListener('click', function () {
    var ctx = trackCtx;
    if (!ctx || ctx.viewMode || !ctx.plan) return;
    var sig = ctx.sig, plan = ctx.plan;
    var rec = {
      code: ctx.item.code, name: ctx.item.name || ctx.item.code,
      dir: plan.dir, period: ctx.period,
      level: sig.level, type: sig.type, note: sig.note, confirmed: !!sig.confirmed,
      markK: sig.markK,       // 信号标记位：动盈只认这之后的回调笔（推进时要用）
      entry: plan.entry, stop: plan.stop, stopRule: plan.stopRule,
      target: plan.target, trail: plan.trail,
      lines: plan.lines, createdAt: Date.now(),
      alertedStop: false,
      // 建卡时价格已在目标位/动盈位的另一侧 → 立刻提醒没有意义，直接标记已报
      alertedTarget: plan.target != null && plan.entry != null &&
        (plan.dir > 0 ? plan.entry >= plan.target : plan.entry <= plan.target),
      alertedTrail: plan.trail != null && plan.entry != null &&
        (plan.dir > 0 ? plan.entry <= plan.trail : plan.entry >= plan.trail)
    };
    CLTrack.set(trackMap, ctx.item.code, rec);
    applyTrackToViews();
    renderWatchlist();
    trackModalEl.classList.add('hidden');
    toast('已进入追踪：' + rec.name + ' ' + (rec.dir > 0 ? '做多 ▲（' : '做空 ▼（') +
          (CLTrack.PERIOD_CN[rec.period] || rec.period) + '）');
  });
  document.getElementById('trackCancel').addEventListener('click', function () {
    trackModalEl.classList.add('hidden');
  });
  /* 1.7.0：方向 pill 已移除（方向由信号类型决定），这行只保留一个显式说明：
     万一还有旧页面/旧测试点进来，不做事也不报错。 */
  if (trackDirRow) trackDirRow.style.display = 'none';

  /**
   * 多图联动：同步「缩放倍数」而不是绝对时间窗口。
   * 各周期数据跨度相差极大（日线数年 vs 5 分钟数天），广播绝对窗口会被
   * 各图 clamp 成完全不同的跨度，再缩放时就会出现跳变。改为各图按自身
   * 当前跨度同比缩放，锚点用相对位置，视觉上三图始终同步。
   */
  function eachView(fn) {
    if (syncing) return;
    syncing = true;
    views.forEach(function (v) { fn(v); v.draw(); });
    syncing = false;
  }

  function onZoom(g) {
    if (g && g.reset) { eachView(function (v) { v.zoomReset(g.reset); }); return; }
    eachView(function (v) { v.zoomBy(g.factor, g.pxRatio); });
  }

  function onPan(g) { eachView(function (v) { v.panBy(g.dFrac); }); }

  function zoomFull() {
    eachView(function (v) { v.zoomFull(); });
    panel.setStatus('已全览：三图均显示完整数据区间');
  }

  /* -------------------------------------------------------------------- 导出 */
  function exportJSON() {
    var st = panel.getState();
    var payload = { code: current.code, name: current.name, exportedAt: new Date().toISOString(),
                    params: st.params, levels: {} };
    Object.keys(datasets).forEach(function (p) {
      var d = datasets[p];
      if (!d || d.code !== current.code) return;
      var res = ChanEngine.analyze(d.klines, st.params);
      payload.levels[p] = {
        period: p,
        source: d.source,
        klines: d.klines,
        stats: res.stats,
        zhongshus: res.zhongshus,
        divergences: res.divergences,
        points: res.points,
        bis: res.bis.map(function (b) {
          return { dir: b.dir, startK: b.startK, endK: b.endK, startPrice: b.startPrice, endPrice: b.endPrice, confirmed: b.confirmed };
        }),
        segs: res.segs.map(function (s) {
          return { dir: s.dir, startK: s.startK, endK: s.endK, pens: s.penCount, confirmed: s.confirmed };
        })
      };
    });
    CLDataSource.downloadJSON('chanlens_' + current.code + '_' + Date.now() + '.json', payload);
    panel.setStatus('已导出 JSON，可直接喂给 D:\\Trading 里的 Python 做回测');
  }

  function saveShot() {
    if (!views.length) return;
    var a = document.createElement('a');
    a.href = views[0].canvas.toDataURL('image/png');
    a.download = 'chanlens_' + current.code + '_' + Date.now() + '.png';
    document.body.appendChild(a); a.click(); a.remove();
    panel.setStatus('已保存主图截图');
  }

  /* -------------------------------------------------------------------- 搜索 */
  var searchTimer = null;
  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimer);
    var text = searchInput.value.trim();
    if (!text) { hideSuggest(); return; }
    searchTimer = setTimeout(function () { runSearch(text); }, 220);
  });

  searchInput.addEventListener('keydown', function (e) {
    if (suggestBox.classList.contains('hidden')) {
      if (e.key === 'Enter') {
        var raw = searchInput.value.trim();
        var m = raw.match(/(\d{6})/);
        if (m) pick({ code: m[1], name: '' });
      }
      return;
    }
    if (e.key === 'ArrowDown') { activeSuggest = Math.min(activeSuggest + 1, suggestItems.length - 1); paintSuggest(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { activeSuggest = Math.max(activeSuggest - 1, 0); paintSuggest(); e.preventDefault(); }
    else if (e.key === 'Enter') {
      var item = suggestItems[activeSuggest >= 0 ? activeSuggest : 0];
      if (item) pick(item);
      e.preventDefault();
    } else if (e.key === 'Escape') { hideSuggest(); }
  });

  function runSearch(text) {
    searchSuggest(text)
      .then(function (list) { suggestItems = (list || []).slice(0, 10); activeSuggest = 0; paintSuggest(); })
      .catch(function () { suggestItems = []; paintSuggest(); });
  }

  function paintSuggest() {
    suggestBox.innerHTML = '';
    suggestBox.classList.remove('hidden');
    if (!suggestItems.length) {
      var empty = document.createElement('div');
      empty.className = 'app-suggest-empty';
      empty.textContent = '没有匹配结果';
      suggestBox.appendChild(empty);
      return;
    }
    suggestItems.forEach(function (item, idx) {
      if (!/^\d{6}$/.test(String(item.code))) return;
      var row = document.createElement('div');
      row.className = 'app-suggest-item' + (idx === activeSuggest ? ' active' : '');
      var nm = document.createElement('span');
      nm.textContent = item.name || item.code;
      var cd = document.createElement('span');
      cd.className = 'code';
      cd.textContent = item.code;
      row.appendChild(nm); row.appendChild(cd);
      row.addEventListener('mousedown', function (e) { e.preventDefault(); pick(item); });
      suggestBox.appendChild(row);
    });
  }

  function hideSuggest() { suggestBox.classList.add('hidden'); suggestItems = []; }

  function pick(item) {
    hideSuggest();
    searchInput.value = '';
    if (!item) return;
    addToWatchlist(String(item.code), item.name || '');
    setCurrent(item.code, item.name || '');
  }

  document.addEventListener('click', function (e) {
    if (!suggestBox.contains(e.target) && e.target !== searchInput) hideSuggest();
  });

  /* ------------------------------------------------------------------ 导入弹层 */
  var modal = document.getElementById('importModal');
  var importText = document.getElementById('importText');
  var importPreview = document.getElementById('importPreview');
  var importStat = document.getElementById('importStat');
  var importCatEl = document.getElementById('importCat');

  /** 把分类列表灌进 <select>，selId 为默认选中项 */
  function fillCatSelect(sel, selId) {
    if (!sel) return;
    sel.innerHTML = '';
    cats.forEach(function (c) {
      var op = document.createElement('option');
      op.value = c.id;
      op.textContent = c.name + '（' + itemsOf(c.id).length + '）';
      sel.appendChild(op);
    });
    sel.value = (selId === undefined || selId === null) ? UNCAT : selId;
    if (sel.value !== String((selId === undefined || selId === null) ? UNCAT : selId)) sel.value = UNCAT;
  }

  function openImport() {
    modal.classList.remove('hidden');
    importText.value = '';
    importPreview.innerHTML = '';
    importStat.textContent = '';
    fillCatSelect(importCatEl, activeCat);
    importText.focus();
  }
  function closeImport() { modal.classList.add('hidden'); }

  function paintImportPreview() {
    var res = parseCodes(importText.value);
    importPreview.innerHTML = '';
    res.items.forEach(function (it) {
      var tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = it.name ? it.code + ' ' + it.name : it.code;
      importPreview.appendChild(tag);
    });
    res.bad.forEach(function (b) {
      var tag = document.createElement('span');
      tag.className = 'tag bad';
      tag.textContent = '跳过：' + (b.length > 10 ? b.slice(0, 10) + '…' : b);
      importPreview.appendChild(tag);
    });
    importStat.textContent = res.items.length
      ? '识别到 ' + res.items.length + ' 只' + (res.bad.length ? '，' + res.bad.length + ' 段无代码' : '')
      : (res.bad.length ? '没找到任何 6 位代码' : '');
    return res;
  }

  function doImport() {
    var res = parseCodes(importText.value);
    if (!res.items.length) { importStat.textContent = '没有可导入的代码'; return; }
    var to = importCatEl ? importCatEl.value : activeCat;
    var stat = importBulk(res.items, to);
    closeImport();
    setStatus('批量导入完成：新增 ' + stat.added + ' 只，补全名称 ' + stat.updated +
                    ' 只，归入「' + catName(to) + '」（缺失名称正在后台自动补全）');
    if (stat.added && !current.code) {
      var first = orderedItems()[orderedItems().length - 1];
      if (first) setCurrent(first.code, first.name);
    }
  }

  importBtn.addEventListener('click', openImport);
  document.getElementById('importCancel').addEventListener('click', closeImport);
  document.getElementById('importOk').addEventListener('click', doImport);
  importText.addEventListener('input', paintImportPreview);
  importText.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeImport();
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doImport(); }
  });
  modal.addEventListener('click', function (e) { if (e.target === modal) closeImport(); });

  /* ------------------------------------------------------------------ 心法弹层（点左上角「缠」） */
  var mantraModal = document.getElementById('mantraModal');
  var logoBtn = document.getElementById('logoBtn');
  if (mantraModal && logoBtn) {
    var openMantra = function () { mantraModal.classList.remove('hidden'); };
    var closeMantra = function () { mantraModal.classList.add('hidden'); };
    logoBtn.addEventListener('click', openMantra);
    document.getElementById('mantraClose').addEventListener('click', closeMantra);
    mantraModal.addEventListener('click', function (e) { if (e.target === mantraModal) closeMantra(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !mantraModal.classList.contains('hidden')) closeMantra();
    });
  }

  /* 搜索框里粘贴一大段多写代码时，直接转成批量导入 */
  searchInput.addEventListener('paste', function (e) {
    var text = (e.clipboardData && e.clipboardData.getData('text')) || '';
    var found = text.match(/\d{6}/g) || [];
    if (found.length > 1) {
      e.preventDefault();
      openImport();
      importText.value = text;
      paintImportPreview();
    }
  });

  /* +自选 / −自选 切换：当前标的已在自选 → 点击移出；不在 → 加入当前高亮分类。
     按钮状态由 renderWatchlist 统一刷新（加入/删除/切换标的都会走它），
     放在函数声明区靠文件头 hoist，renderWatchlist 首行就能调用。 */
  function inWatchlist(code) {
    for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === code) return true;
    return false;
  }
  function updateAddBtn() {
    var on = !!current.code && inWatchlist(current.code);
    addBtn.textContent = on ? '− 自选' : '+ 自选';
    addBtn.classList.toggle('on', on);
  }
  addBtn.addEventListener('click', function () {
    if (!current.code) return;
    if (inWatchlist(current.code)) {
      delOne(current.code);
    } else {
      addToWatchlist(current.code, current.name);
      setStatus('已加入自选「' + catName(activeCat) + '」：' + (current.name || current.code));
    }
  });

  var catBtnEl = document.getElementById('catBtn');
  if (catBtnEl) catBtnEl.addEventListener('click', function () {
    newCat(function (id) {
      activeCat = id;
      renderWatchlist();
      setStatus('已新建分类「' + catName(id) + '」，新加入的自选会默认放这里');
    });
  });

  /* Alt + ↑/↓ 在自选股之间快速切换（按分组顺序） */
  document.addEventListener('keydown', function (e) {
    if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || !watchlist.length) return;
    e.preventDefault();
    var seq = orderedItems(), idx = -1;
    for (var i = 0; i < seq.length; i++) if (seq[i].code === current.code) idx = i;
    idx = e.key === 'ArrowDown' ? (idx + 1) % seq.length
                                : (idx - 1 + seq.length) % seq.length;
    setCurrent(seq[idx].code, seq[idx].name);
  });

  /* 窗口变化时重排图表高度 */
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var hs = chartHeights();
      views.forEach(function (v, i) {
        if (v && v.canvas && hs[i] != null) { v.canvas.style.height = hs[i] + 'px'; v.draw(); }
      });
    }, 160);
  });

  /* -------------------------------------------------------------------- 启动 */
  panel = CLPanel.create({
    container: stage,
    chartCount: 3,
    chartHeights: chartHeights(),
    onReady: function (state) {
      state.levels[0] = state.period;
      syncDataSource(state && state.params);   // 必须在首次取数之前生效
      loadAll(function () {
        syncScanPeriod(state && state.params);   // 恢复设置的扫描周期（纯读缓存）
        renderWatchlist();
        resolveMissingNames(40);   // 兼容旧数据：启动时自动补全缺失/退化为代码的名称
        refreshQuotes();           // 自选列表右侧涨跌幅
        loadScanCache();           // 上次扫描结果（纯本地，不联网）
        CLTrack.load().then(function (m) {   // 追踪记录（纯本地）
          trackMap = m || {};
          renderWatchlist();
          applyTrackToViews();
        });
        chrome.storage.local.get(EXTRA_KEY, function (o) {   // 额外显隐记忆
          if (o && o[EXTRA_KEY] === false) { extraOn = false; applyTrackToViews(); }
        });
        quoteTimer = setInterval(function () {
          if (document.visibilityState === 'visible') refreshQuotes();  // 后台页不刷，省流量
        }, 600000);   // 10 分钟兜底刷新，日常看图直接刷新页面即可
        var fromUrl = new URLSearchParams(location.search).get('code');
        var initial = (fromUrl && /^\d{6}$/.test(fromUrl)) ? fromUrl : (watchlist[0] && watchlist[0].code);
        if (initial) {
          var known = null;
          for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === initial) known = watchlist[i].name;
          setCurrent(initial, known || '');
        } else {
          setStatus('顶栏输入代码或从自选股里挑一只开始，例如 600519');
        }
      });
    },
    onPeriodChange: function () { datasets = {}; rebuild(); },
    onAdjustChange: function () { datasets = {}; rebuild(); },
    onParamChange: function (params) {
      syncScanPeriod(params);
      if (syncDataSource(params)) datasets = {};   // 换源 → 旧缓存作废，必须重取
      rebuild();
    },
    onLayerChange: function (layers) { views.forEach(function (v) { v.setLayers(layers); v.draw(); }); },
    onLevelsChange: function () { rebuild(); },
    onAction: function (act) {
      if (act === 'full') { zoomFull(); return; }
      if (act === 'recalc') { datasets = {}; rebuild(); }
      else if (act === 'export') exportJSON();
      else if (act === 'shot') saveShot();
      else if (act === 'extra') {
        extraOn = !extraOn;
        var o = {}; o[EXTRA_KEY] = extraOn;
        chrome.storage.local.set(o);
        applyTrackToViews();
        setStatus('额外（追踪价位线 / 图上短文案）已' + (extraOn ? '显示' : '隐藏'));
      }
      else if (act === 'reset') {
        panel.resetState();
        // 重置会把参数写回默认值，这里必须像 onParamChange 那样重新应用一遍：
        // 否则「数据源/扫描周期」这类不在引擎里的开关还停在被重置前的状态
        var rstParams = (panel.getState() || {}).params;
        syncScanPeriod(rstParams);
        syncDataSource(rstParams);
        datasets = {};
        rebuild();
      }
    }
  });

  window.ChanLensApp = {
    open: setCurrent,
    watchlist: function () { return watchlist.slice(); },
    ordered: function () { return orderedItems(); },
    categories: function () { return cats.map(function (c) { return { id: c.id, name: c.name, count: itemsOf(c.id).length }; }); },
    moveTo: moveTo,
    newCat: newCat,
    refreshQuotes: refreshQuotes,
    setScanPeriod: function (p) { syncScanPeriod({ scanPeriod: p }); },   // 与设置面板同步用
    reloadScanCache: loadScanCache,   // 测试/调试：注入扫描缓存后手动重载
    quotes: function () { return JSON.parse(JSON.stringify(quotes)); },
    runScan: runScan,
    signals: function () { return JSON.parse(JSON.stringify(signals)); },
    /* 追踪模式（1.6.0）：供测试与调试 */
    track: function () { return JSON.parse(JSON.stringify(trackMap)); },
    cancelTrack: cancelTrack,
    openTrackCard: openTrackCard,
    openItemMenu: openItemMenu,
    setExtra: function (on) { extraOn = !!on; applyTrackToViews(); },
    curPeriod: function () {                       // 兼容旧调用：追踪已固定日线
      var st = panel && panel.getState ? panel.getState() : null;
      var p = st && st.levels && st.levels[0];
      return p || (st && st.period) || TRACK_PERIOD;
    },
    signalOf: signalOf,
    clearSigCache: function () { sigCache = {}; },   // 测试/调试：追踪现算缓存
    reloadData: function () { datasets = {}; return rebuild(); },   // 测试/调试：强制重拉行情（动态模拟切换切片用）
    applyTrackToViews: applyTrackToViews,
    checkTrackAlerts: checkTrackAlerts,
    checkTiming: checkTimingAll   // 测试/调试：force=true 忽略间隔抑制
  };
})();
