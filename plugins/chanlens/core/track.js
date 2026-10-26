/* ==========================================================================
 * track.js —— 缠论追踪模式（作战卡）
 *
 * 用户在自选列表长按某只带信号的标的，选「追踪」后进入追踪：
 *   - 图上画虚线（失效 / 动盈 / 条件单），属于「额外」可显隐
 *   - 四句话（挂在哪一级 / 错了的价 / 买多少 / 怎么挂）生成文案，作为跟踪计划
 *   - 动态盯梢：条件单触发、时间单到期时提醒
 *   - 覆盖式：同一标的再选一次以新的为准；手动取消才退出追踪
 *
 * 方向（1.7.0）：缠论的买点/卖点自带方向 —— 买点就做多、卖点就做空，
 *   不再给用户「看多 / 看空」两个按钮。
 *
 * 失效位规则（与速查手册「开仓前写三句话」一致，全部取自已定型结构，无未来函数）：
 *   做多：一/二买 → 跌破一买低点（一买取信号价、二买取其引用的一买极值）
 *         三买   → 跌回中枢（跌破 ZG）
 *   做空：一/二卖 → 升破一卖高点；三卖 → 升回中枢（升破 ZD）
 *   本级别没有对应方向的结构时 stop = null —— 宁可空着，也不编一个数字。
 *
 * 出场三层（2026-10-24 手册重写后对齐，取代旧的「失效/目标/动盈」多线口径）：
 *   ① 条件单（唯一必做）：触发价 = 失效位（或已上移的动盈位）∓ 0.5×ATR20
 *   ② 时间单（盘后看）  ：N 根不启动 → 减半；N = 最近 3 个中枢持续根数均值 ×1.5
 *   ③ 卖点信号（可选）  ：同级别一卖 → 减 1/3 或不动；无统计优势，只兑现情绪
 *   「目标 = 前高、到价减 1/3」已整体移除：手册只保留「创新高 → 上移触发价」。
 *
 * 动盈（移动止盈）= 条件单的上移基准：只朝有利方向走，不回退。
 * 信号没有预测力，所以文案只写「挂在哪、错了在哪、拿多久」，不写「会涨到哪」。
 *
 * 本文件是纯存储 + 纯文案：不碰 K 线、不碰 DOM，Node 里也能单测。
 * ========================================================================== */
'use strict';

(function (g) {
  'use strict';

  var KEY = 'chanlens.track.v1';

  var LEVEL_CN = { 1: '一', 2: '二', 3: '三' };
  var PERIOD_CN = { '5m': '5 分钟', '15m': '15 分钟', '30m': '30 分钟', '60m': '60 分钟',
                    'daily': '日线', 'weekly': '周线', 'monthly': '月线' };

  /* 条件单价格只要 2 位小数（2.0.0）：ATR 缓冲算出来的第 3、4 位没有交易意义，
     挂单也挂不进去 —— 存储与显示统一按 2 位，避免「显示 9.60 实际 9.6043 才触发」。 */
  function round2(v) { return Math.round(v * 100) / 100; }
  function fmt2(v) { return v == null || !isFinite(v) ? '—' : v.toFixed(2); }

  /* ------------------------------------------------------------ 存储 */
  function load() {
    return new Promise(function (res) {
      if (g.chrome && g.chrome.storage && g.chrome.storage.local) {
        g.chrome.storage.local.get(KEY, function (o) { res((o && o[KEY]) || {}); });
      } else { res({}); }
    });
  }
  function save(map) {
    var o = {}; o[KEY] = map;
    if (g.chrome && g.chrome.storage && g.chrome.storage.local) {
      g.chrome.storage.local.set(o);
    }
  }

  /* ------------------------------------------------------------ 四句话文案
   * sig: pickSignal 的返回（level/type/note/confirmed/refs）
   * dir: +1 做多 / -1 做空；**可省略** —— 省略时按信号自带的 type 推导
   *      （买点 = 多、卖点 = 空）。period: 当前级别
   * opts: { fmtPrice, atr20 } —— atr20 用来算条件单触发价，缺省则显示口径不显示数字
   * 返回 { dir, stop, stopRule, condStop, trail, entry, lines: [s1,s2,s3,s4] }
   */
  function buildPlan(sig, dir, period, opts) {
    opts = opts || {};
    var fp = opts.fmtPrice || function (v) { return String(v); };
    // 条件单价格固定 2 位（不受标的价位影响），与 advanceCond / check 的判定口径一致
    var fc = opts.fmtCond || fmt2;
    var lv = LEVEL_CN[sig.level] || sig.level;
    var per = PERIOD_CN[period] || period;
    var refs = sig.refs || {};
    // 方向跟着信号走：买点做多、卖点做空。显式传入的方向仍然尊重（老记录/单测）
    if (dir !== 1 && dir !== -1) dir = (sig.type < 0 || (refs.dir === -1)) ? -1 : 1;
    var long = dir > 0;

    var stop = long ? refs.stopBuy : refs.stopSell;
    var stopRule;
    if (stop == null) {
      // 本级别没有这个方向的结构（比如只有买点却要做空）→ 空着，不编数字
      stopRule = '本级别暂无' + (long ? '买点' : '卖点') + '结构，失效位待定（换个级别再看）';
    } else if (sig.level === 3) {
      stopRule = long ? '跌回中枢（跌破 ' + fp(stop) + '）' : '升回中枢（升破 ' + fp(stop) + '）';
    } else {
      /* 一/二类的失效基准跟方向走：买点锚一买低点、卖点锚一卖高点 */
      var refLabel = long ? '一买低点' : '一卖高点';
      stopRule = (long ? '跌破' : '升破') + refLabel + ' ' + fp(stop);
    }

    var entry = refs.lastClose != null ? refs.lastClose : null;
    var trail = long ? refs.trailLow : refs.trailHigh;
    var atr20 = (opts.atr20 != null && isFinite(opts.atr20) && opts.atr20 > 0) ? opts.atr20 : null;

    /* 条件单（出场第 1 层，唯一必做）：失效位 ∓ 0.5×ATR20。
       动盈已上移时按动盈算 —— 与手册「失效位（或上移后的移动止盈位）」一致。 */
    var condBase = stop;
    var condStop = (condBase != null && atr20 != null)
      ? round2(condBase + (long ? -0.5 : 0.5) * atr20) : null;

    var confirmTxt = sig.confirmed ? '' : '⚠ 未定型（分型右侧可能修订），readyK+1 根才确立';

    /* 第 3 句：买多少 —— 仓位是主观信心唯一该待的地方（手册一·3） */
    var sizeLine;
    if (entry != null && stop != null) {
      var dist = Math.abs(entry - stop);
      var pct = entry ? (dist / entry * 100) : null;
      sizeLine = '买多少：R ÷（' + fp(entry) + ' − ' + fp(stop) + '）= R ÷ ' + fp(dist) +
        (pct != null ? '（止损距离 ' + pct.toFixed(1) + '%）' : '') +
        '；R = 总资金 0.5~1%，结果封顶 10%';
    } else {
      sizeLine = '买多少：失效位写成具体数字才能算 —— R ÷（买入价 − 失效价）';
    }

    /* 第 4 句：怎么挂 —— 入场 2 档限价、出场全部条件单（手册一·4 / 三·1） */
    var hangLine = '怎么挂：入场在回抽区挂 2 档限价（不追突破，不回抽就不做）；' +
      '出场全挂条件单' +
      (condStop != null
        ? '，触发价 ' + fc(condStop) + '（' + (long ? '失效位' : '失效位') +
          (long ? ' − 0.5×ATR20' : ' + 0.5×ATR20') + '）'
        : '（失效位 ∓ 0.5×ATR20，ATR 算不出时按失效位）') +
      '；创新高就把触发价往上挪';

    /* note 本身已带「二买·」前缀（detectPoints 的文案），别再拼一遍级别 */
    var sigTxt = sig.note || (lv + (long ? '买' : '卖'));

    return {
      dir: dir,
      stop: stop, stopRule: stopRule,
      condStop: condStop,
      trail: trail,
      entry: entry,
      atr20: atr20,
      confirmed: !!sig.confirmed,
      lines: [
        '我' + (long ? '做多' : '做空') + '的是' + per + '级别（' + sigTxt + '）',
        '我错了的标记：' + stopRule + (confirmTxt ? ' —— ' + confirmTxt : ''),
        sizeLine,
        hangLine
      ]
    };
  }

  /* ------------------------------------------------------------ 记录增删 */
  /** rec: { code, name, dir, period, level, type, note, confirmed, markK, startK,
   *         entry, stop, stopRule, condStop, atr20, trail, timerN, bars, started,
   *         lines, createdAt, alertedStop, alertedTimer } */
  function set(map, code, rec) {
    map[code] = rec; save(map); return map;
  }
  function del(map, code) {
    delete map[code]; save(map); return map;
  }

  /* ------------------------------------------------------------ 动态盯梢
   * 返回 { hit: 'cond'|'timer'|null, text } —— hit 只在新触发时非空，
   * 由调用方负责把 alerted 写回记录去重（同一状态只报一次）。
   * 优先级：条件单（触发即离场） > 时间单（减半）。
   * 老记录没有 condStop → 退回按失效位原价判，行为与此前一致。
   */
  function check(rec, lastPrice) {
    if (!rec || lastPrice == null || !isFinite(lastPrice)) return { hit: null, text: '' };
    var long = rec.dir > 0;
    var trig = rec.condStop != null ? rec.condStop : rec.stop;
    if (trig != null && !rec.alertedStop &&
        ((long && lastPrice < trig) || (!long && lastPrice > trig))) {
      return { hit: 'cond',
               text: '条件单触发（' + fmt2(trig) + '），按纪律离场，不重新分析' };
    }
    if (rec.timerN > 0 && rec.bars >= rec.timerN && !rec.started && !rec.alertedTimer) {
      return { hit: 'timer',
               text: '时间单：' + rec.bars + ' 根未启动（N=' + rec.timerN + '）→ 减半；浮亏就清' };
    }
    return { hit: null, text: '' };
  }

  /* ------------------------------------------------- 动盈推进（1.7.1）
   * 每次重算时把新算出的动盈并回记录：只朝有利方向走（多头只上移、空头只下移）。
   * 动盈是条件单的上移基准，所以它动了之后条件单要重算（见 advanceCond）。
   * 返回 true 表示记录被改动，调用方负责存盘。
   */
  function advanceTrail(rec, next) {
    if (!rec || next == null || !isFinite(next)) return false;
    if (rec.trail == null) { rec.trail = next; return true; }
    var better = rec.dir > 0 ? next > rec.trail : next < rec.trail;
    if (!better) return false;
    rec.trail = next;
    return true;
  }

  /* ------------------------------------------------- 条件单触发价（手册三·1）
   * 触发价 = (动盈已上移 ? 动盈 : 失效位) ∓ 0.5×ATR20。
   * 触发价变了（创新高上移）→ 复位 alertedStop，新价位重新允许提醒。
   * 返回 true 表示记录被改动。
   */
  function advanceCond(rec, atr20) {
    if (!rec || !(atr20 > 0)) return false;
    var base = rec.trail != null ? rec.trail : rec.stop;
    if (base == null) return false;
    var next = round2(base + (rec.dir > 0 ? -0.5 : 0.5) * atr20);
    if (rec.condStop === next) return false;
    rec.condStop = next;
    rec.alertedStop = false;
    return true;
  }

  /* ------------------------------------------------- 时间单（手册三·2）
   * N = 最近 3 个中枢持续根数均值 ×1.5（最少 3 根）。
   * 「启动」= 建卡后朝有利方向走出 0.5×ATR20（不是浮盈多少，而是有没有动）。
   * rec.bars 由调用方按 K 线数算好传入。
   */
  function timerN(zss) {
    if (!zss || !zss.length) return null;
    var last = zss.slice(-3), sum = 0, n = 0;
    last.forEach(function (z) {
      var d = (z.endK != null && z.startK != null) ? (z.endK - z.startK + 1) : 0;
      if (d > 0) { sum += d; n++; }
    });
    return n ? Math.max(3, Math.round(sum / n * 1.5)) : null;
  }

  function advanceTimer(rec, t) {
    if (!rec || !t) return false;
    var changed = false;
    if (t.n != null && t.n > 0 && rec.timerN !== t.n) { rec.timerN = t.n; changed = true; }
    if (t.bars != null && t.bars >= 0 && rec.bars !== t.bars) { rec.bars = t.bars; changed = true; }
    if (t.started != null && rec.started !== !!t.started) { rec.started = !!t.started; changed = true; }
    return changed;
  }

  /* ------------------------------------------------- 30 分同向信号（1.8.0）
   * 方向级别高于 30 分时，30 分出现同向买/卖点只是**时机参考** ——
   * 手册明确「信号无预测力」，所以文案不写「可进场」。
   * rec.timing 记录最近一次同向信号；从无到有、或换成新信号（key 不同）才提醒一次。
   */
  function updateTiming(rec, sig) {
    if (!rec) return { hit: false, text: '' };
    var want = rec.dir > 0 ? 1 : -1;
    var ok = sig && !sig.none && sig.type === want;
    if (!ok) return { hit: false, text: '' };
    var key = (sig.level == null ? '?' : sig.level) + '|' + (sig.note || '');
    if (rec.timing && rec.timing.key === key) return { hit: false, text: '' };
    rec.timing = { key: key, level: sig.level, note: sig.note || '', ts: Date.now() };
    return { hit: true, text: '30分同向信号：' + rec.timing.note + '（参考，不构成进场依据）' };
  }

  /* ------------------------------------------------- 30 分反向信号（1.8.1）
   * 时机窗口走坏：清空 timing 记 timingFail，报一次。清空即天然去重。
   * 手册：笔级别卖点只提示，不清仓 —— 文案只说「出现」，不说「失效/回在等」。
   */
  function failTiming(rec, sig) {
    if (!rec || !rec.timing) return { hit: false, text: '' };
    var want = rec.dir > 0 ? 1 : -1;
    if (!sig || sig.none || sig.type === want) return { hit: false, text: '' };
    rec.timingFail = { note: sig.note || '', ts: Date.now(), from: rec.timing.note };
    rec.timing = null;
    return { hit: true, text: '30分反向信号：' + rec.timingFail.note + '（仅提示，不清仓）' };
  }

  /* ------------------------------------------------- 本级别反向信号（1.8.1，1.9.0 降级，1.9.12 随级别）
   * 多头持仓后本级别出一卖 / 空头持仓后本级别出一买 —— 纯**信息提示**，不是离场建议。
   * 回测结论（26 只 ETF 日线全历史）：「翻转清仓」占 85% 换手、82% 离场后创新高，
   * 是价值毁灭者——离场只认条件单（结构线 ± ATR 缓冲）。
   * rec.reverse 保留最近一次反向信号：同向/消失都不清除（防横跳），
   * key=level|note 去重，换新的反向信号才再报。纯函数，同上。
   */
  function updateReverse(rec, sig) {
    if (!rec) return { hit: false, text: '' };
    var want = rec.dir > 0 ? -1 : 1;     // 反向：多头怕卖点、空头怕买点
    var ok = sig && !sig.none && sig.type === want;
    if (!ok) return { hit: false, text: '' };
    var key = (sig.level == null ? '?' : sig.level) + '|' + (sig.note || '');
    if (rec.reverse && rec.reverse.key === key) return { hit: false, text: '' };
    rec.reverse = { key: key, level: sig.level, note: sig.note || '', ts: Date.now() };
    var perCN = PERIOD_CN[rec.period] || rec.period || '本级别';
    return { hit: true,
      text: perCN + '出现' + rec.reverse.note + '（仅提示，不清仓，离场看条件单）' };
  }

  g.CLTrack = {
    KEY: KEY, load: load, save: save,
    buildPlan: buildPlan, set: set, del: del, check: check,
    advanceTrail: advanceTrail, advanceCond: advanceCond,
    timerN: timerN, advanceTimer: advanceTimer,
    updateTiming: updateTiming, failTiming: failTiming, updateReverse: updateReverse,
    round2: round2, fmt2: fmt2,
    LEVEL_CN: LEVEL_CN, PERIOD_CN: PERIOD_CN
  };
})(typeof self !== 'undefined' ? self : this);
