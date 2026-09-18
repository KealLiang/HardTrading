/* ==========================================================================
 * content.js —— 注入页面的主入口
 *
 * 流程：识别股票代码 → 拉行情 → 跑缠论引擎 → 自绘渲染 → 面板控制
 * 多级别联动：三张图共享同一个时间窗口，任意一张缩放/平移，另外两张同步。
 * ========================================================================== */
/* ==========================================================================
 * content_legacy.js ——【已停用的旧模式】站点页面内直接画图的入口
 *
 * 现在主入口是 App 全屏页（app/app.html），本文件不再出现在 manifest 里。
 * 保留它的意义是：若你将来仍想在特定网站内直��出图，
 * 把 manifest 的 content_scripts 改回下面的组合即可复活：
 *   core/indicators.js, core/chan.js, chart/renderer.js, ui/panel.js,
 *   content/adapters.js, content/datasource.js, content/content_legacy.js
 * ========================================================================== */
'use strict';

(function () {
  'use strict';

  if (window.__chanlensLoaded) return;
  window.__chanlensLoaded = true;

  var info = window.CLAdapters.detect();
  if (!info.supported) {
    console.log('[ChanLens] 当前页面未识别到股票代码，未启动。支持的站点：雪球 / 新浪财经 / 东财 / 同花顺 / TradingView');
    return;
  }

  var views = [];               // 每个周期一张图
  var datasets = {};            // period -> data
  var syncing = false;
  var panel = null;
  var currentCode = info.code;

  var PERIOD_LABEL = {};
  window.CLPanel.PERIODS.forEach(function (p) { PERIOD_LABEL[p.id] = p.label; });

  /* ------------------------------------------------------------ 加载与计算 */
  async function loadPeriod(period) {
    if (!period) return null;
    if (datasets[period] && datasets[period].code === currentCode) return datasets[period];
    var st = panel.getState();
    var data = await window.CLDataSource.getKlines(currentCode, period, 800, st.adjust);
    window.CLDataSource.withTimestamps(data);
    datasets[period] = data;
    return data;
  }

  function analyze(data, params) {
    var result = window.ChanEngine.analyze(data.klines, params);
    return result;
  }

  /** 重建（或刷新）三张图 */
  async function rebuild(opts) {
    opts = opts || {};
    var st = panel.getState();
    try {
      panel.setStatus('正在获取行情…');
      var periods = st.levels.filter(Boolean);
      if (!periods.length) {
        panel.setStatus('请至少选择一个周期', true);
        return;
      }
      var loaded = [];
      for (var i = 0; i < periods.length; i++) {
        var d = await loadPeriod(periods[i]);
        if (d) loaded.push(d);
      }
      if (!loaded.length) throw new Error('没有拿到任何行情数据');

      panel.setSub(loaded[0].name ? loaded[0].name + ' ' + currentCode : currentCode);

      var canvases = panel.activeCanvases().map(function (h) { return h.canvas; });

      views = [];
      var stats = [];
      for (var j = 0; j < loaded.length && j < canvases.length; j++) {
        var data = loaded[j];
        var res = analyze(data, st.params);
        var view = window.CLRenderer.create(canvases[j], {
          defaultBars: j === 0 ? 160 : 320,
          layers: st.layers,
          onWindowChange: onWindowChange
        });
        view.setData({ klines: data.klines, period: data.period, code: data.code, name: data.name, result: res });
        if (sharedWindow) view.setWindow(sharedWindow);
        view.draw();
        views.push(view);
        stats.push(PERIOD_LABEL[data.period] + ' 笔' + res.bis.length +
                   ' / 段' + res.segs.length + ' / 中枢' + res.zhongshus.length +
                   ' / 背驰' + res.divergences.length + ' / 点' + res.points.length);
      }
      panel.setStatus(stats.join('　|　') + '\n滚轮缩放 · 拖拽平移 · 双击复位 · 数据来源 ' +
                      (loaded[0].source === 'sina' ? '新浪财经' : '东方财富'));
    } catch (e) {
      panel.setStatus('出错：' + (e && e.message || e), true);
    }
  }

  var sharedWindow = null;
  function onWindowChange(w) {
    if (syncing) return;
    syncing = true;
    sharedWindow = w;
    views.forEach(function (v) { v.setWindow(w); v.draw(); });
    syncing = false;
  }

  /* -------------------------------------------------------------- 导出动作 */
  function exportJSON() {
    var st = panel.getState();
    var payload = { code: currentCode, exportedAt: new Date().toISOString(), params: st.params, levels: {} };
    Object.keys(datasets).forEach(function (p) {
      var d = datasets[p];
      if (d.code !== currentCode) return;
      var res = analyze(d, st.params);
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
    window.CLDataSource.downloadJSON('chanlens_' + currentCode + '_' + Date.now() + '.json', payload);
    panel.setStatus('已导出 JSON，可直接喂给 D:\\Trading 里的 Python 做回测');
  }

  function saveShot() {
    if (!views.length) return;
    var canvas = views[0].canvas;
    var a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = 'chanlens_' + currentCode + '_' + Date.now() + '.png';
    document.body.appendChild(a); a.click(); a.remove();
    panel.setStatus('已保存主图截图');
  }

  /* ------------------------------------------------------------------ 启动 */
  panel = window.CLPanel.create({
    onReady: function (state) {
      state.levels[0] = state.period;
      rebuild();
    },
    onPeriodChange: function () { datasets = {}; rebuild(); },
    onAdjustChange: function () { datasets = {}; rebuild(); },
    onParamChange: function () { rebuild(); },
    onLayerChange: function (layers) {
      views.forEach(function (v) { v.setLayers(layers); v.draw(); });
    },
    onLevelsChange: function () { rebuild(); },
    onAction: function (act) {
      if (act === 'recalc') { datasets = {}; rebuild(); }
      else if (act === 'export') exportJSON();
      else if (act === 'shot') saveShot();
      else if (act === 'reset') {
        var s = panel.resetState();
        datasets = {};
        rebuild();
      }
    }
  });

  window.ChanLens = {
    code: currentCode,
    reload: function (code) {
      if (code) currentCode = code;
      datasets = {};
      rebuild();
    }
  };

  // 没有识别出代码时给一个手动入口
  if (!currentCode) {
    setTimeout(function () {
      var c = window.prompt('ChanLens：未能自动识别股票代码，请输入 6 位代码（留空取消）', '');
      if (c && /\d{6}/.test(c)) {
        currentCode = c.match(/\d{6}/)[0];
        rebuild();
      }
    }, 400);
  }
})();
