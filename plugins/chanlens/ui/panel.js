/* ==========================================================================
 * panel.js —— 控制面板
 *
 * 设计原则：所有东西都是用一个「参数表」生成的。
 * 想加一个新参数？往 PARAM_SCHEMA 里加一行就行，UI 和引擎自动同步。
 * 源码在你自己电脑上，改完刷新页面（重载扩展）即生效。
 * ========================================================================== */
'use strict';

(function (global) {
  'use strict';

  var STORE_KEY = 'chanlens.settings.v1';

  var PERIODS = [
    { id: 'monthly', label: '月线' },
    { id: 'weekly', label: '周线' },
    { id: 'daily', label: '日线' },
    { id: '60m', label: '60分' },
    { id: '30m', label: '30分' },
    { id: '15m', label: '15分' },
    { id: '5m', label: '5分' },
    { id: '1m', label: '1分' }
  ];

  var ADJUSTS = [
    { id: 0, label: '不复权' },
    { id: 1, label: '前复权' },
    { id: 2, label: '后复权' }
  ];

  /* ------------------------------------------------------------ 参数表 */
  var PARAM_SCHEMA = [
    {
      group: '笔', items: [
        { key: 'minFxGap', label: '顶底最小间隔K线', type: 'range', min: 0, max: 6, step: 1,
          help: '0=最灵敏；旧笔规则建议 3' },
        { key: 'biRequireBreak', label: '严格成笔', type: 'bool',
          help: '要求顶必须真正高于底的高点' },
        { key: 'merge', label: '含包处理', type: 'bool' }
      ]
    },
    {
      group: '线段', items: [
        { key: 'segAlgo', label: '线段算法', type: 'select', options: [
            { id: 'simple', label: '回调破坏即终结（默认，切分均衡）' },
            { id: 'feature', label: '特征序列法（教科书标准，线段更长）' }],
          help: 'feature 更严谨但需要更多后续笔才能确认' },
        { key: 'featureMerge', label: '特征序列含包处理', type: 'bool' },
        { key: 'segMinPens', label: '线段最少笔数', type: 'range', min: 3, max: 9, step: 2 }
      ]
    },
    {
      group: '中枢', items: [
        { key: 'zsSource', label: '中枢来源', type: 'select', options: [
            { id: 'bi', label: '笔算中枢（颗粒度细，接近主流工具）' },
            { id: 'seg', label: '线段算中枢（教科书口径）' }] },
        { key: 'zsMinParts', label: '最少次级别走势数', type: 'range', min: 3, max: 7, step: 2 },
        { key: 'zsExtendUpdate', label: '延伸时更新ZG/ZD', type: 'bool' }
      ]
    },
    {
      group: '背驰', items: [
        { key: 'divMode', label: '背驰模式', type: 'select', options: [
            { id: 'pen', label: '滚动三笔比较（默认，稳定可用）' },
            { id: 'zs', label: '同中枢隔开的连接波（严格）' }],
          help: '严格模式常因中枢首尾相接而一个信号都没有' },
        { key: 'forceMode', label: '力度度量', type: 'select', options: [
            { id: 'same', label: '同方向MACD柱面积' },
            { id: 'abs', label: '区间绝对值之和' },
            { id: 'perBar', label: '面积/K线根数' }] },
        { key: 'divMinForceRatio', label: '背驰阈值', type: 'range', min: 0.3, max: 1.2, step: 0.05,
          help: '后段力度/前段力度 小于该值才判背驰' },
        { key: 'divFallbackAmplitude', label: '力度为0时用幅度', type: 'bool' },
        { key: 'macdFast', label: 'MACD 快线', type: 'range', min: 5, max: 30, step: 1 },
        { key: 'macdSlow', label: 'MACD 慢线', type: 'range', min: 20, max: 60, step: 1 },
        { key: 'macdSignal', label: 'MACD 信号线', type: 'range', min: 5, max: 20, step: 1 }
      ]
    },
    {
      group: '买卖点', items: [
        { key: 'showBuy', label: '显示买点', type: 'bool' },
        { key: 'showSell', label: '显示卖点', type: 'bool' },
        { key: 'pointsOnSegs', label: '买卖点基于线段', type: 'bool',
          help: '关掉则基于笔，更灵敏也更杂乱' }
      ]
    }
  ];

  var LAYERS = [
    { id: 'zhongshu', label: '中枢' },
    { id: 'bi', label: '笔' },
    { id: 'seg', label: '线段' },
    { id: 'fractal', label: '分型' },
    { id: 'divergence', label: '背驰' },
    { id: 'points', label: '买卖点' },
    { id: 'volume', label: '成交量' },
    { id: 'macd', label: 'MACD' }
  ];

  /* ------------------------------------------------------------ 状态持久化 */
  function defaultState() {
    var params = {};
    var D = global.ChanEngine.DEFAULTS;
    Object.keys(D).forEach(function (k) { params[k] = D[k]; });
    return {
      params: params,
      layers: {
        fractal: true, bi: true, seg: true, zhongshu: true,
        divergence: true, points: true, volume: true, macd: true
      },
      period: 'daily',
      adjust: 1,
      levels: ['daily', '30m', '']       // 三级：主图 + 次图 + 低级图
    };
  }

  function loadState(cb) {
    chrome.storage.sync.get(STORE_KEY, function (box) {
      var base = defaultState();
      var saved = box && box[STORE_KEY];
      if (saved) {
        if (saved.params) Object.assign(base.params, saved.params);
        if (saved.layers) Object.assign(base.layers, saved.layers);
        if (saved.period) base.period = saved.period;
        if (saved.adjust != null) base.adjust = saved.adjust;
        if (saved.levels) base.levels = saved.levels;
      }
      cb(base);
    });
  }

  function saveState(state) {
    var box = {}; box[STORE_KEY] = state;
    try { chrome.storage.sync.set(box); } catch (e) { /* 忽略配额/权限异常 */ }
  }

  /* ---------------------------------------------------------------- 构建 */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function create(options) {
    options = options || {};
    var host = options.container || document.body;
    var embedded = !!options.container;
    var chartHeights = options.chartHeights || [430, 210, 210];
    var extraRight = options.extraHead || null;   // 宿主页面可往标题栏塞自己的控件

    var state = null;
    var root = el('div', 'cl-root');
    var launcher = embedded ? null : el('button', 'cl-launcher', '缠');
    if (launcher) launcher.title = 'ChanLens 缠论透镜（点击展开/收起）';
    var panel = el('div', 'cl-panel');
    var head = el('div', 'cl-head');
    var body = el('div', 'cl-body');
    var mainCol = el('div', 'cl-main');
    var sideCol = el('div', 'cl-side');
    var status = el('div', 'cl-status', '初始化…');

    var titleEl = el('span', 'cl-title', 'ChanLens 缠论透镜');
    var subEl = el('span', 'cl-sub', '');
    var tabsEl = el('div', 'cl-tabs');
    head.appendChild(titleEl);
    head.appendChild(subEl);
    head.appendChild(el('div', 'cl-spacer'));
    head.appendChild(tabsEl);

    var adjSel = el('select');
    ADJUSTS.forEach(function (a) {
      var o = el('option', null, a.label); o.value = a.id; adjSel.appendChild(o);
    });
    head.appendChild(adjSel);

    var hideBtn = el('button', 'cl-btn', '收起');
    if (!embedded) head.appendChild(hideBtn);
    if (extraRight) head.appendChild(extraRight);

    body.appendChild(mainCol);
    body.appendChild(sideCol);
    panel.appendChild(head);
    panel.appendChild(body);
    panel.appendChild(status);
    root.appendChild(panel);
    if (launcher) root.appendChild(launcher);
    if (embedded) root.className += ' cl-embedded';

    var chartHosts = [];

    function setStatus(msg, isError) {
      status.textContent = msg;
      status.className = 'cl-status' + (isError ? ' cl-error' : '');
    }

    function rebuildCharts(count) {
      mainCol.innerHTML = '';
      chartHosts = [];
      for (var i = 0; i < count; i++) {
        var wrap = el('div', 'cl-row');
        var lab = el('span', 'cl-label', i === 0 ? '主图' : (i === 1 ? '次级' : '次次级'));
        var sel = el('select');
        sel.innerHTML = '<option value="">（关闭）</option>' + PERIODS.map(function (p) {
          return '<option value="' + p.id + '">' + p.label + '</option>';
        }).join('');
        sel.value = state.levels[i] || '';
        sel.addEventListener('change', function () {
          var idx = chartHosts.findIndex(function (h) { return h.sel === this; }, this);
          if (idx < 0) return;
          state.levels[idx] = this.value;
          saveState(state);
          options.onLevelsChange && options.onLevelsChange();
        });
        wrap.appendChild(lab); wrap.appendChild(sel);
        mainCol.appendChild(wrap);

        var canvas = el('canvas', 'cl-chart');
        canvas.style.height = (chartHeights[i] != null ? chartHeights[i] : 210) + 'px';
        mainCol.appendChild(canvas);
        chartHosts.push({ canvas: canvas, sel: sel });
      }
    }

    function buildSide() {
      sideCol.innerHTML = '';

      sideCol.appendChild(el('h4', null, '显示图层'));
      var layerRow = el('div', 'cl-row');
      LAYERS.forEach(function (L) {
        var pill = el('span', 'cl-pill' + (state.layers[L.id] ? ' cl-on' : ''), L.label);
        pill.addEventListener('click', function () {
          state.layers[L.id] = !state.layers[L.id];
          pill.className = 'cl-pill' + (state.layers[L.id] ? ' cl-on' : '');
          saveState(state);
          options.onLayerChange && options.onLayerChange(state.layers);
        });
        layerRow.appendChild(pill);
      });
      sideCol.appendChild(layerRow);

      PARAM_SCHEMA.forEach(function (grp) {
        sideCol.appendChild(el('h4', null, grp.group));
        grp.items.forEach(function (it) {
          var p = el('div', 'cl-param');
          var headRow = el('div', 'cl-param-head');
          headRow.appendChild(el('span', null, it.label));
          var valEl = el('span', 'cl-param-val', '');
          headRow.appendChild(valEl);
          p.appendChild(headRow);

          if (it.type === 'range') {
            var inp = el('input');
            inp.type = 'range';
            inp.min = it.min; inp.max = it.max; inp.step = it.step;
            inp.value = state.params[it.key];
            valEl.textContent = state.params[it.key];
            inp.addEventListener('input', function () {
              var v = parseFloat(inp.value);
              if (it.step >= 1) v = Math.round(v);
              state.params[it.key] = v;
              valEl.textContent = v;
              saveState(state);
              options.onParamChange && options.onParamChange(state.params);
            });
            p.appendChild(inp);
          } else if (it.type === 'select') {
            var sel = el('select');
            it.options.forEach(function (o) {
              var op = el('option', null, o.label); op.value = o.id; sel.appendChild(op);
            });
            sel.value = state.params[it.key];
            sel.addEventListener('change', function () {
              state.params[it.key] = sel.value;
              saveState(state);
              options.onParamChange && options.onParamChange(state.params);
            });
            p.appendChild(sel);
          } else if (it.type === 'bool') {
            var pill = el('span', 'cl-pill' + (state.params[it.key] ? ' cl-on' : ''),
                          state.params[it.key] ? '开' : '关');
            pill.style.float = 'right';
            pill.addEventListener('click', function () {
              state.params[it.key] = !state.params[it.key];
              pill.textContent = state.params[it.key] ? '开' : '关';
              pill.className = 'cl-pill' + (state.params[it.key] ? ' cl-on' : '');
              saveState(state);
              options.onParamChange && options.onParamChange(state.params);
            });
            p.appendChild(pill);
          }
          if (it.help) p.appendChild(el('div', 'cl-help', it.help));
          sideCol.appendChild(p);
        });
      });

      sideCol.appendChild(el('h4', null, '操作'));
      var actRow = el('div', 'cl-row');
      [
        ['重算', function () { options.onAction && options.onAction('recalc'); }],
        ['导出JSON', function () { options.onAction && options.onAction('export'); }],
        ['保存截图', function () { options.onAction && options.onAction('shot'); }],
        ['重置参数', function () { options.onAction && options.onAction('reset'); }]
      ].forEach(function (pair) {
        var b = el('button', 'cl-btn', pair[0]);
        b.addEventListener('click', pair[1]);
        actRow.appendChild(b);
      });
      sideCol.appendChild(actRow);
      sideCol.appendChild(el('div', 'cl-help',
        '参数自动保存到浏览器同步存储，下次打开保持。改动引擎请直接编辑 core/chan.js。'));
    }

    function buildTabs() {
      tabsEl.innerHTML = '';
      PERIODS.forEach(function (p) {
        var t = el('span', 'cl-tab' + (state.period === p.id ? ' cl-active' : ''), p.label);
        t.addEventListener('click', function () {
          state.period = p.id;
          state.levels[0] = p.id;
          saveState(state);
          buildTabs();
          options.onPeriodChange && options.onPeriodChange(p.id);
        });
        tabsEl.appendChild(t);
      });
    }

    loadState(function (s) {
      state = s;
      adjSel.value = state.adjust;
      buildTabs();
      buildSide();
      rebuildCharts(options.chartCount || 3);
      if (launcher) launcher.classList.add('cl-hidden');
      host.appendChild(root);
      options.onReady && options.onReady(state, chartHosts);
    });

    if (!embedded) {
      hideBtn.addEventListener('click', function () {
        panel.style.display = 'none';
        launcher.classList.remove('cl-hidden');
      });
      launcher.addEventListener('click', function () {
        panel.style.display = 'flex';
        launcher.classList.add('cl-hidden');
      });
    }
    adjSel.addEventListener('change', function () {
      state.adjust = +adjSel.value;
      saveState(state);
      options.onAdjustChange && options.onAdjustChange(state.adjust);
    });

    return {
      root: root,
      canvases: function () { return chartHosts.map(function (h) { return h.canvas; }); },
      getState: function () { return state; },
      setStatus: setStatus,
      setSub: function (txt) { subEl.textContent = txt; },
      resetState: function () {
        state = defaultState();
        saveState(state);
        buildTabs(); buildSide(); rebuildCharts(3);
        return state;
      },
      activeCanvases: function () {
        return chartHosts.filter(function (h) { return !!h.sel.value; });
      }
    };
  }

  global.CLPanel = { create: create, PERIODS: PERIODS, PARAM_SCHEMA: PARAM_SCHEMA, LAYERS: LAYERS };
})(typeof window !== 'undefined' ? window : this);
