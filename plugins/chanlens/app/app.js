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

  /* ------------------------------------------------------------------ 自选股 */
  function loadWatchlist(cb) {
    chrome.storage.local.get(WL_KEY, function (box) {
      var arr = box && box[WL_KEY];
      watchlist = Array.isArray(arr) ? arr.filter(function (x) { return x && x.code; }) : [];
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
    watchlist.forEach(function (item, idx) {
      var li = document.createElement('li');
      if (item.code === current.code) li.className = 'active';
      var nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = item.name || item.code;
      var cd = document.createElement('span');
      cd.className = 'cd';
      cd.textContent = item.code;
      li.appendChild(nm); li.appendChild(cd);
      li.addEventListener('click', function () { setCurrent(item.code, item.name); });
      li.addEventListener('contextmenu', function (e) {
        e.preventDefault();
        watchlist.splice(idx, 1);
        saveWatchlist();
        renderWatchlist();
      });
      listEl.appendChild(li);
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
    watchlist.forEach(function (w) {
      var lab = document.createElement('label');
      var ck = document.createElement('input');
      ck.type = 'checkbox'; ck.value = w.code; ck.checked = true;
      ck.addEventListener('change', syncDelStat);
      var nm = document.createElement('span'); nm.textContent = w.name || w.code;
      var cd = document.createElement('span'); cd.className = 'code'; cd.textContent = w.code;
      lab.appendChild(ck); lab.appendChild(nm); lab.appendChild(cd);
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

  function importBulk(items) {
    var added = 0, updated = 0;
    items.forEach(function (it) {
      var hit = null;
      for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === it.code) hit = watchlist[i];
      if (hit) {
        if (it.name && !hit.name) { hit.name = it.name; updated++; }
        return;
      }
      watchlist.push({ code: it.code, name: it.name || '' });
      added++;
    });
    saveWatchlist();
    renderWatchlist();
    resolveMissingNames(40);
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

  function openImport() {
    modal.classList.remove('hidden');
    importText.value = '';
    importPreview.innerHTML = '';
    importStat.textContent = '';
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
    var stat = importBulk(res.items);
    closeImport();
    panel.setStatus('批量导入完成：新增 ' + stat.added + ' 只，补全名称 ' + stat.updated +
                    ' 只（缺失名称正在后台自动补全）');
    if (stat.added && !current.code) {
      var first = watchlist[watchlist.length - 1];
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
    panel.setStatus('已加入自选：' + (current.name || current.code));
  });

  /* Alt + ↑/↓ 在自选股之间快速切换 */
  document.addEventListener('keydown', function (e) {
    if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || !watchlist.length) return;
    e.preventDefault();
    var idx = -1;
    for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === current.code) idx = i;
    idx = e.key === 'ArrowDown' ? (idx + 1) % watchlist.length
                                : (idx - 1 + watchlist.length) % watchlist.length;
    setCurrent(watchlist[idx].code, watchlist[idx].name);
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
      loadWatchlist(function () {
        renderWatchlist();
        resolveMissingNames(40);   // 兼容旧数据：启动时自动补全缺失/退化为代码的名称
        var fromUrl = new URLSearchParams(location.search).get('code');
        var initial = (fromUrl && /^\d{6}$/.test(fromUrl)) ? fromUrl : (watchlist[0] && watchlist[0].code);
        if (initial) {
          var known = null;
          for (var i = 0; i < watchlist.length; i++) if (watchlist[i].code === initial) known = watchlist[i].name;
          setCurrent(initial, known || '');
        } else {
          panel.setStatus('顶栏输入代码或从自选股里挑一只开始，例如 600519');
        }
      });
    },
    onPeriodChange: function () { datasets = {}; rebuild(); },
    onAdjustChange: function () { datasets = {}; rebuild(); },
    onParamChange: function () { rebuild(); },
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
    watchlist: function () { return watchlist.slice(); }
  };
})();
