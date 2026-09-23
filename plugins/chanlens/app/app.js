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
        if (m && Object.keys(m).length) { quotes = m; renderWatchlist(); }
      })
      .catch(function () { /* 静默：涨跌幅拿不到不影响主功能 */ });
  }

  function fmtPct(p) {
    if (p == null || !isFinite(p)) return '—';
    return (p > 0 ? '+' : '') + p.toFixed(2) + '%';
  }

  /* ------------------------------------------------- 缠论信号扫描（周期可选） */
  var SCAN = { period: '30m', limit: 200, maxLag: 10, freshMs: 30 * 60 * 1000 };
  var LEVEL_CN = { 1: '一', 2: '二', 3: '三' };

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
          badge.className = 'sig ' + (sg.type > 0 ? 'buy' : 'sell') + (sg.confirmed ? '' : ' fresh');
          badge.textContent = (LEVEL_CN[sg.level] || sg.level) + (sg.type > 0 ? '买' : '卖');
          badge.title = (PERIOD_LABEL[sg.period] || sg.period || '') + '：' + (sg.note || '') +
                        '\n信号成立 K：' + (sg.t || sg.readyK) + '（滞后 ' + sg.lag + ' 根）' +
                        (sg.ratio != null ? '\n背驰力度比：' + sg.ratio.toFixed(2) : '') +
                        '\n标记价：' + sg.price + (sg.confirmed ? '' : '\n未确认：分型右侧可能修订');
          top.appendChild(badge);
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
        li.addEventListener('contextmenu', function (e) {
          e.preventDefault();
          var ents = [];
          cats.forEach(function (t) {
            if (t.id === (item.cat || UNCAT)) return;
            ents.push({ label: '移动到「' + t.name + '」', fn: function () { moveTo(item.code, t.id); } });
          });
          ents.push({ label: '新建分类并移入…', fn: function () { newCat(function (id) { moveTo(item.code, id); }); } });
          ents.push({ sep: true });
          ents.push({ label: '从自选中删除', danger: true, fn: function () { delOne(item.code); } });
          showCtx(e, ents);
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
    syncDelStat();
    delModalEl.classList.remove('hidden');
    var first = delListEl.querySelector('input');
    if (first) first.focus();
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
        var view = CLRenderer.create(canvases[j], {
          defaultBars: j === 0 ? 160 : 320,
          layers: st.layers,
          onZoom: onZoom,
          onPan: onPan
        });
        view.setData({ klines: data.klines, period: data.period, code: data.code, name: data.name, result: res });
        view.draw();
        views.push(view);
        stats.push(PERIOD_LABEL[data.period] + ' 笔' + res.bis.length +
                   ' / 段' + res.segs.length + ' / 中枢' + res.zhongshus.length +
                   ' / 背驰' + res.divergences.length + ' / 点' + res.points.length);
      }
      panel.setStatus(stats.join('　|　') + '\n滚轮缩放 · 拖拽平移 · 双击复位 · 「全览」看全部 · 三图联动按同比缩放 · 数据来源 ' +
                      (loaded[0].source === 'sina' ? '新浪财经' : '东方财富'));
    } catch (e) {
      panel.setStatus('出错：' + (e && e.message || e), true);
    }
  }

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

  addBtn.addEventListener('click', function () {
    if (!current.code) return;
    addToWatchlist(current.code, current.name);
    setStatus('已加入自选「' + catName(activeCat) + '」：' + (current.name || current.code));
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
      loadAll(function () {
        syncScanPeriod(state && state.params);   // 恢复设置的扫描周期（纯读缓存）
        renderWatchlist();
        resolveMissingNames(40);   // 兼容旧数据：启动时自动补全缺失/退化为代码的名称
        refreshQuotes();           // 自选列表右侧涨跌幅
        loadScanCache();           // 上次扫描结果（纯本地，不联网）
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
    onParamChange: function (params) { syncScanPeriod(params); rebuild(); },
    onLayerChange: function (layers) { views.forEach(function (v) { v.setLayers(layers); v.draw(); }); },
    onLevelsChange: function () { rebuild(); },
    onAction: function (act) {
      if (act === 'full') { zoomFull(); return; }
      if (act === 'recalc') { datasets = {}; rebuild(); }
      else if (act === 'export') exportJSON();
      else if (act === 'shot') saveShot();
      else if (act === 'reset') { panel.resetState(); datasets = {}; rebuild(); }
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
    quotes: function () { return JSON.parse(JSON.stringify(quotes)); },
    runScan: runScan,
    signals: function () { return JSON.parse(JSON.stringify(signals)); }
  };
})();
