/* ==========================================================================
 * track.js —— 缠论追踪模式（作战卡）
 *
 * 用户在自选列表长按某只带信号的标的，选「追踪」后进入追踪：
 *   - 图上画虚线（目标 / 参考 / 失效 / 动盈），属于「额外」可显隐
 *   - 三句话（哪个级别 / 错了的标记 / 打算怎么走）生成文案，作为该标的的跟踪计划
 *   - 动态盯梢：现价触碰失效位 / 目标位 / 动盈位时提醒
 *   - 覆盖式：同一标的再选一次以新的为准；手动取消才退出追踪
 *
 * 方向（1.7.0）：缠论的买点/卖点自带方向 —— 买点就做多、卖点就做空，
 *   不再给用户「看多 / 看空」两个按钮。1.6.0 那两个按钮在一/二类上是同一
 *   个失效位（代码把多空引用写成了同一个数），等于同一张图，留着只会误导。
 *   方向仍记在记录里（徽标「追多/追空」、盯梢判据都读它），只是不再由人选。
 *
 * 失效位规则（与心法「出场四层」一致，全部取自已定型结构，无未来函数）：
 *   做多：一/二买 → 跌破一买低点（一买取信号价、二买取其引用的一买极值）
 *         三买   → 跌回中枢（跌破 ZG）
 *   做空：一/二卖 → 升破一卖高点；三卖 → 升回中枢（升破 ZD）
 *   本级别没有对应方向的结构时 stop = null —— 宁可空着，也不编一个数字。
 *
 * 目标 / 动盈（1.7.1，用户反馈「止盈怎么在价格下面」后重做）：
 *   目标 = 有利方向上最近的已完成笔极值（多头是上方前高、空头是下方前低），
 *          到价减 1/3 —— 这才是「止盈」，动作是涨到/跌到某个位置主动卖。
 *   动盈 = 移动止盈，本质是**跟踪止损**：它在价格下方，随回调低点抬高而只上移
 *          不下移，用来兑现已有浮盈。它的起点必须优于入场价，否则信号刚出就画
 *          出来只会贴着失效位（甚至更低），既触发不到也看不懂 —— 那时不画。
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

  /* ------------------------------------------------------------ 三句话文案
   * sig: pickSignal 的返回（level/type/note/confirmed/refs）
   * dir: +1 做多 / -1 做空；**可省略** —— 省略时按信号自带的 type 推导
   *      （买点 = 多、卖点 = 空）。period: 当前级别；opts: {fmtPrice}
   * 返回 { dir, stop, stopRule, target, trail, entry, lines: [s1, s2, s3] }
   */
  function buildPlan(sig, dir, period, opts) {
    opts = opts || {};
    var fp = opts.fmtPrice || function (v) { return String(v); };
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

    /* 目标：有利方向上最近的笔极值；已创新高/新低时没有参照 → 不编数字 */
    var target = long ? refs.targetHigh : refs.targetLow;
    var trail = long ? refs.trailLow : refs.trailHigh;
    var trailTxt = trail != null ? fp(trail)
      : '未启动（等首个' + (long ? '高于入场的回调低点' : '低于入场的反抽高点') + '）';

    var confirmTxt = sig.confirmed ? '' : '⚠ 未定型（分型右侧可能修订），readyK+1 根才确立';

    var s3 = (target != null
        ? (long ? '涨到目标 ' : '跌到目标 ') + fp(target) + ' 减 1/3；'
        : (long ? '上方暂无参照（已创新高）；' : '下方暂无参照（已创新低）；')) +
      '动盈 ' + trailTxt + '，' + (long ? '只上移不回头' : '只下移不回头') +
      '；本级别出现' + (long ? '一卖（顶背驰）再减' : '一买（底背驰）再回补') +
      '，破失效位认错';

    /* note 本身已带「二买·」前缀（detectPoints 的文案），别再拼一遍级别 */
    var sigTxt = sig.note || (lv + (long ? '买' : '卖'));

    return {
      dir: dir,
      stop: stop, stopRule: stopRule,
      target: target != null ? target : null,
      trail: trail,
      entry: refs.lastClose != null ? refs.lastClose : null,
      confirmed: !!sig.confirmed,
      lines: [
        '我' + (long ? '做多' : '做空') + '的是' + per + '级别（' + sigTxt + '）',
        '我错了的标记：' + stopRule + (confirmTxt ? ' —— ' + confirmTxt : ''),
        '我打算怎么走：' + s3
      ]
    };
  }

  /* ------------------------------------------------------------ 记录增删 */
  /** rec: { code, name, dir, period, level, type, note, confirmed,
   *         entry, stop, stopRule, target, trail, lines, createdAt } */
  function set(map, code, rec) {
    map[code] = rec; save(map); return map;
  }
  function del(map, code) {
    delete map[code]; save(map); return map;
  }

  /* ------------------------------------------------------------ 动态盯梢
   * 返回 { hit: 'stop'|'target'|'trail'|null, text } —— hit 只在新触发时非空，
   * 由调用方负责把 alerted 写回记录去重（同一状态只报一次）。
   * 优先级：失效（认错离场） > 目标（减 1/3） > 动盈（落袋）。
   */
  function check(rec, lastPrice) {
    if (!rec || lastPrice == null || !isFinite(lastPrice)) return { hit: null, text: '' };
    var long = rec.dir > 0;
    // 失效位：多头跌破 stop / 空头升破 stop —— 无条件离场，优先级最高
    if (rec.stop != null &&
        ((long && lastPrice < rec.stop) || (!long && lastPrice > rec.stop))) {
      if (!rec.alertedStop) return { hit: 'stop', text: '失效位触发（' + rec.stopRule + '），按纪律离场' };
      return { hit: null, text: '' };
    }
    // 目标：到价减 1/3（这才是「止盈」：涨到/跌到位主动卖）
    if (rec.target != null && !rec.alertedTarget) {
      var atTarget = long ? lastPrice >= rec.target : lastPrice <= rec.target;
      if (atTarget) return { hit: 'target', text: '触及目标位 ' + rec.target + '（按计划减 1/3）' };
    }
    // 动盈：跟踪位，跌破/升破即落袋，仅提醒一次
    if (rec.trail != null && !rec.alertedTrail) {
      var touched = long ? lastPrice <= rec.trail : lastPrice >= rec.trail;
      if (touched) return { hit: 'trail', text: '触及动盈位 ' + rec.trail + '（跟踪位，落袋）' };
    }
    return { hit: null, text: '' };
  }

  /* ------------------------------------------------- 目标刷新（1.7.1）
   * 目标没有单调性：前高被突破后上方就没参照了 → 置 null（线消失）；
   * 回落到某个前高之下时它又会重新出现，此时重新允许提醒。
   * 返回 true 表示记录被改动，调用方负责存盘。
   */
  function refreshTarget(rec, next) {
    if (!rec) return false;
    if (next == null) {
      if (rec.target == null) return false;
      rec.target = null; return true;
    }
    if (next === rec.target) return false;
    rec.target = next;
    rec.alertedTarget = false;
    return true;
  }

  /* ------------------------------------------------- 动盈推进（1.7.1）
   * 每次重算时把新算出的动盈并回记录：只朝有利方向走（多头只上移、空头只下移）。
   * 返回 true 表示记录被改动，调用方负责存盘。
   */
  function advanceTrail(rec, next) {
    if (!rec || next == null || !isFinite(next)) return false;
    if (rec.trail == null) { rec.trail = next; rec.alertedTrail = false; return true; }
    var better = rec.dir > 0 ? next > rec.trail : next < rec.trail;
    if (!better) return false;
    rec.trail = next;
    rec.alertedTrail = false;      // 线动了，重新允许提醒
    return true;
  }

  /* ------------------------------------------------- 30 分时机（1.8.0）
   * 心法：日线定方向、30 分钟定时机。rec.timing 记录最近一次「与方向一致的
   * 30 分信号」；从无到有、或换成了新信号（key 不同）才提醒一次——同一个
   * 30 分买点在多根 K 线里反复被算出来，不能每次都报。
   * 纯函数：只动 rec.timing，返回 { hit, text }，调用方负责存盘与 toast。
   */
  function updateTiming(rec, sig) {
    if (!rec) return { hit: false, text: '' };
    var want = rec.dir > 0 ? 1 : -1;
    var ok = sig && !sig.none && sig.type === want;
    if (!ok) return { hit: false, text: '' };
    var key = (sig.level == null ? '?' : sig.level) + '|' + (sig.note || '');
    if (rec.timing && rec.timing.key === key) return { hit: false, text: '' };
    rec.timing = { key: key, level: sig.level, note: sig.note || '', ts: Date.now() };
    return { hit: true, text: '30 分时机：' + rec.timing.note };
  }

  /* ------------------------------------------------- 30 分时机失效（1.8.1）
   * 时机已到（rec.timing 非空）之后 30 分出了**反向**信号 → 这个时机窗口
   * 走坏了：清空 timing 回到「在等」，记 rec.timingFail 供卡里回看，报一次。
   * 报完即清 timing —— 同一个反向信号反复算出时 timing 已是空，天然去重；
   * 下一个新时机成立后再遇反向，允许再次报（对新的时机窗口语义正确）。
   * 纯函数：返回 { hit, text }，调用方负责存盘与 toast。
   */
  function failTiming(rec, sig) {
    if (!rec || !rec.timing) return { hit: false, text: '' };
    var want = rec.dir > 0 ? 1 : -1;
    if (!sig || sig.none || sig.type === want) return { hit: false, text: '' };
    rec.timingFail = { note: sig.note || '', ts: Date.now(), from: rec.timing.note };
    rec.timing = null;
    return { hit: true, text: '30 分时机失效（' + rec.timingFail.note + '），回「在等」' };
  }

  /* ------------------------------------------------- 日线反向信号（1.8.1，1.9.0 降级）
   * 多头持仓后日线出一卖 / 空头持仓后日线出一买 —— 纯**信息提示**，不是离场建议。
   * 回测结论（26 只 ETF 日线全历史）：「日线翻转清仓」占 85% 换手、82% 离场后创新高，
   * 是价值毁灭者——离场只认两条结构线：失效位、动盈/移动止盈。
   * 跟踪推进（refsFor）只认方向、不认信号，是为了跟踪线不冻结；反向信号对持仓者
   * 仍是重要信息，但只提示不催动作。
   * rec.reverse 保留最近一次反向信号：同向信号/信号消失都不清除（防横跳），
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
    return { hit: true,
      text: '日线方向转' + (rec.dir > 0 ? '空' : '多') + '（' + rec.reverse.note +
            '）· 仅提示，离场仍看失效位/动盈' };
  }

  g.CLTrack = {
    KEY: KEY, load: load, save: save,
    buildPlan: buildPlan, set: set, del: del, check: check,
    advanceTrail: advanceTrail, refreshTarget: refreshTarget,
    updateTiming: updateTiming, failTiming: failTiming, updateReverse: updateReverse,
    LEVEL_CN: LEVEL_CN, PERIOD_CN: PERIOD_CN
  };
})(typeof self !== 'undefined' ? self : this);
