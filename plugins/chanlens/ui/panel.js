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

  /* ------------------------------------------------------------------ 动作表
   * 两个快捷区各自一张表，互不掺：
   *   WATCH_ACTIONS —— 「自选」区（针对股票：加减自选/导入/扫信号/分类/删除）
   *   CHART_ACTIONS —— 「右上角」区（针对图表：全览/重算/导出/截图/额外/重置/切换）
   * 参数面板的「操作」区把两块并列展示（同一入口、但分组独立）；手机上「自选」
   * 那块搬进左抽屉，「右上角」那块是图表右上角的悬浮按钮（quickbar 配置）。
   *
   * 以前是 HTML 里写死一串 span + 手机端 ui.js 里另有一份 id 清单，漏一处就静默
   * 失效（v1.9.3 的「切换」按钮就是这么丢的）。现在这两份都不存在了。
   *   key    : 动作标识，交给 onAction(key, ev)
   *   id     : DOM id（沿用历史 id 的保留原名，其余 act_<key>；面板里另加 pact_ 前缀）
   *   label  : 按钮文案      title : 悬浮说明
   *   pin    : true = 快捷区里常驻平铺（其余收进「更多」浮层）
   *   danger : true = 危险操作（红色）
   */
  var WATCH_ACTIONS = [
    { key: 'add',    id: 'addBtn',    label: '+ 自选', pin: true,
      title: '加入/移出自选（点按切换，默认加到高亮分类）' },
    { key: 'import', id: 'importBtn', label: '批量导入', pin: true,
      title: '批量导入自选股（粘贴代码列表）' },
    { key: 'scan',   id: 'scanBtn',   label: '扫信号', pin: true,
      title: '扫描自选列表最新缠论信号（Shift+点击强制重扫）' },
    { key: 'cat',    id: 'catBtn',    label: '+ 分类',
      title: '新建分类（文件夹）' },
    { key: 'del',    id: 'delBtn',    label: '批量删除', danger: true,
      title: '批量删除自选股' }
  ];

  var CHART_ACTIONS = [
    { key: 'full',   label: '全览', pin: true, title: '缩放到全部 K 线' },
    { key: 'recalc', label: '重算', pin: true, title: '清缓存重算（长按/Shift 强制重取行情）' },
    { key: 'export', label: '导出JSON', title: '导出当前标的缠论结构到系统「下载」目录' },
    { key: 'shot',   label: '保存截图', title: '保存主图截图到系统「下载」目录' },
    { key: 'extra',  label: '额外',     title: '显示/隐藏追踪价位线与图上短文案' },
    { key: 'reset',  label: '重置参数', title: '恢复引擎默认参数' },
    { key: 'kline',  id: 'klineBtn', label: '切换', pin: true,
      title: '切换 缠论K/普通K（纯本地重算，不重新拉数据）' }
  ];

  var ACTIONS = WATCH_ACTIONS.concat(CHART_ACTIONS);

  function actionId(a) { return a.id || ('act_' + a.key); }

  function actionList(group) {
    if (group === 'watch') return WATCH_ACTIONS;
    if (group === 'chart') return CHART_ACTIONS;
    return ACTIONS;
  }

  function mkActionEl(a, onAct, idPrefix) {
    var e = document.createElement('span');
    e.className = 'app-side-add' + (a.danger ? ' danger' : '');
    e.id = (idPrefix || '') + actionId(a);
    e.textContent = a.label;
    e.title = a.title;
    e.setAttribute('data-key', a.key);   // 测试/外部脚本按 key 定位，不依赖 id
    if (a.pin) e.setAttribute('data-pin', '1');
    e.addEventListener('click', function (ev) { onAct && onAct(a.key, ev); });
    return e;
  }

  /** 往快捷区渲染一组动作：清空 host 后重建，返回 key -> 元素。
   *  opts.fold = true 时只把 pin 项平铺，其余收进「更多」浮层（顶栏空间有限）。 */
  function renderActions(host, onAct, group, opts) {
    if (!host) return {};
    opts = opts || {};
    host.innerHTML = '';
    var list = actionList(group);
    var main = [], rest = [];
    if (opts.fold) list.forEach(function (a) { (a.pin ? main : rest).push(a); });
    else main = list;

    var map = {};
    main.forEach(function (a) {
      map[a.key] = mkActionEl(a, onAct);
      host.appendChild(map[a.key]);
    });
    if (!rest.length) return map;

    var wrap = document.createElement('span');
    wrap.className = 'app-more-wrap';
    var more = document.createElement('span');
    more.className = 'app-more';   // 它不是动作，别带 app-side-add（否则会被当成动作统计进去）
    more.textContent = '更多';
    more.title = '展开其余操作';
    var drop = document.createElement('div');
    drop.className = 'app-more-panel hidden';
    rest.forEach(function (a) {
      map[a.key] = mkActionEl(a, onAct);
      drop.appendChild(map[a.key]);
    });
    var shut = function () { drop.classList.add('hidden'); };
    more.addEventListener('click', function (e) {
      e.stopPropagation();
      drop.classList.toggle('hidden');
    });
    drop.addEventListener('click', shut);
    document.addEventListener('click', function (e) {
      if (!drop.classList.contains('hidden') && !wrap.contains(e.target)) shut();
    });
    wrap.appendChild(more);
    wrap.appendChild(drop);
    host.appendChild(wrap);
    return map;
  }

  /* ------------------------------------------------------------ 参数表 */
  var PARAM_SCHEMA = [
    {
      group: '显示', items: [
        { key: 'klineMode', label: 'K 线形态', type: 'select', options: [
            { id: 'raw', label: '普通 K 线（原始）' },
            { id: 'merged', label: '缠论 K 线（含包处理后）' }],
          help: '只影响画图：缠论 K 线把有包含关系的相邻 K 合并成一根（首根开盘+末根收盘，高低取合并后的区间）；分型/笔/线段/中枢/背驰的判定结果完全不变' }
      ]
    },
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
          help: '默认关＝背驰/买卖点基于笔（灵敏也更杂）；打开＝基于线段（少而严谨）' }
      ]
    },
    {
      group: '自选扫描', items: [
        { key: 'scanPeriod', label: '扫描周期', type: 'select', options: [
            { id: '15m', label: '15 分钟' },
            { id: '30m', label: '30 分钟' },
            { id: '60m', label: '60 分钟' },
            { id: 'daily', label: '日线（默认）' },
            { id: 'weekly', label: '周线' }],
          help: '自选列表右侧信号徽标用的周期；切换后自动显示该周期上次缓存，点「扫信号」才联网' }
      ]
    },
    {
      // 放在最后：改它要重取全部数据，不是调参那种随手切的开关
      group: '数据', items: [
        { key: 'dataSource', label: '数据源', type: 'select', options: sourceOptions(),
          help: '自动＝东财优先、失败切新浪（原行为）。手动选中某源时它以优先，仍失败会自动降级，' +
                '状态栏「来源」显示的是实际拿到数据的源' }
      ]
    }
  ];

  /** 选项列表由行情层提供，避免两端各写一份；拿不到时退回硬编码 */
  function sourceOptions() {
    if (global.CLMarket && typeof global.CLMarket.sourceOptions === 'function') {
      return global.CLMarket.sourceOptions();
    }
    return [
      { id: 'auto', label: '自动（东财优先，失败切新浪）' },
      { id: 'eastmoney', label: '东方财富' },
      { id: 'sina', label: '新浪财经' },
      { id: 'tencent', label: '腾讯财经' }
    ];
  }

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
    params.scanPeriod = params.scanPeriod || 'daily';   // 自选扫描专用（非引擎参数）
    params.klineMode = params.klineMode || 'raw';     // 画图用哪种 K 线（非引擎参数）
    params.dataSource = params.dataSource || 'auto';  // 行情源（非引擎参数）
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
        // 一次性迁移：扫描周期默认值由 30m 改为日线（只对未手动调整过的旧配置生效一次）
        if (saved.params && saved.params.scanPeriod === '30m' && !saved._scanDailyDefault) {
          base.params.scanPeriod = 'daily';
          saved._scanDailyDefault = true;
          try { var b = {}; b[STORE_KEY] = saved; chrome.storage.sync.set(b); } catch (e) { /* 忽略 */ }
        }
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

    var fullBtn = el('button', 'cl-btn', '全览');
    fullBtn.title = '三图一键显示完整数据区间（免滚轮）';
    fullBtn.style.marginLeft = '6px';
    fullBtn.addEventListener('click', function () {
      options.onAction && options.onAction('full');
    });
    head.appendChild(fullBtn);

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

    /** 「操作」区里的一个分组块：小标题 + 一行按钮（cls 供 quickbar 按组显隐） */
    function actionBlock(title, list, cls, help) {
      var box = el('div', 'cl-act-block');
      box.appendChild(el('div', 'cl-act-title', title));
      var row = el('div', 'cl-row cl-act-row ' + cls);
      list.forEach(function (a) {
        var b = el('button', 'cl-btn', a.label);
        b.id = 'pact_' + a.key;          // 快捷区用 act_/历史 id，这里加前缀避免重复
        b.title = a.title;
        // 外部（quickbar 的显隐维护、测试）按 key 定位，别按文案匹配文案会变
        b.setAttribute('data-key', a.key);
        b.addEventListener('click', function () {
          options.onAction && options.onAction(a.key);
        });
        row.appendChild(b);
      });
      box.appendChild(row);
      box.appendChild(el('div', 'cl-help', help));
      return box;
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

      /* 两个快捷区在这里并列，但仍是两块：上面是「自选」（针对股票），
         下面是「右上角 / 图表」（针对图，手机上就是图表右上角那几个悬浮按钮）。
         数据来源还是那两张表 —— 加动作只改表，三个地方一起出现。 */
      sideCol.appendChild(el('h4', null, '操作'));
      sideCol.appendChild(actionBlock('自选 · 针对股票', WATCH_ACTIONS, 'cl-act-watch',
        '手机端在左抽屉顶部'));
      sideCol.appendChild(actionBlock('右上角 · 针对图表', CHART_ACTIONS, 'cl-act-chart',
        '手机端是图表右上角的悬浮按钮（上方「右上角」里勾选后，从这里移走）'));
      sideCol.appendChild(el('div', 'cl-help',
        '参数自动保存到浏览器同步存储，下次打开保持。改动引擎请直接编辑 core/chan.js。'));
      /* 版本脚注：每次发版改这里（versionName 对齐 build.gradle.kts），
         一句话说清这版动了什么——手机上没有别的地方能看版本 */
      sideCol.appendChild(el('div', 'cl-help',
        'v1.9.6 · 修右上角「切换」点了没反应（手机端动作改直连执行入口，不再按按钮文案找按钮）；自选/右上角两块快捷区各管各的'));
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
        buildTabs(); buildSide();
        // 这里必须跟着 chartCount 走：宿主（如安卓壳）可以把图数配成 1，
        // 写死 3 会让「重置参数」把多出来的空图一起建出来（画面上突然多两张图）。
        rebuildCharts(options.chartCount || 3);
        return state;
      },
      activeCanvases: function () {
        return chartHosts.filter(function (h) { return !!h.sel.value; });
      },
      /* 供宿主以动作方式改参数（如 K 线形态切换按钮）：落盘 + 重建参数 UI，
         让下拉框显示与实际值一致。 */
      setParam: function (key, value) {
        state.params[key] = value;
        saveState(state);
        buildSide();
      }
    };
  }

  global.CLPanel = {
    create: create, PERIODS: PERIODS, PARAM_SCHEMA: PARAM_SCHEMA, LAYERS: LAYERS,
    ACTIONS: ACTIONS, WATCH_ACTIONS: WATCH_ACTIONS, CHART_ACTIONS: CHART_ACTIONS,
    actionList: actionList, renderActions: renderActions
  };
})(typeof window !== 'undefined' ? window : this);
