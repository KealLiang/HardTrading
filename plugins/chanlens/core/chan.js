/* ==========================================================================
 * chan.js —— 缠论结构识别引擎
 *
 * 设计原则：
 *   1. 纯函数、零 DOM 依赖 → 浏览器 content script 与 Node 单测共用同一份代码
 *   2. 所有判定阈值都是可选参数 → 面板可视化调节、持久化
 *   3. 每一步的输出都保留原始 K 线索引(_k)与价格，渲染层不需要二次反推
 *
 * 分层：原始K线 → 包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点
 *
 * 输入格式：[{ t, o, h, l, c, v }]  字段含义 time/open/high/low/close/volume
 *          （同时兼容驼峰写法 open/high/low/close）
 * ========================================================================== */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./indicators.js'));
  } else {
    root.ChanEngine = factory(root.CLIndicators);
  }
})(typeof self !== 'undefined' ? self : this, function (IND) {
  'use strict';

  /* ---------------------------------------------------------------- 参数 */

  var DEFAULTS = {
    // —— 包含处理 ——
    merge: true,                 // 是否进行包含处理（关掉则用原始 K 线找分型）

    // —— 笔 ——
    minFxGap: 1,                 // 顶底分型之间至少间隔多少根「处理后」K 线（旧笔要求更高，可改 3）
    biRequireBreak: true,        // 是否要求「顶必须高于前一个被否定的低分型高点」式严格成笔
    fxConfirmBars: 1,            // 分型右侧需要几根 K 线才算确认

    // —— 线段 ——
    segAlgo: 'simple',           // 'simple' 回调破坏最近低点即终结（默认，切分更均衡）
                                 // 'feature' 特征序列法（教科书标准，但线段会长很多）
    featureMerge: true,          // 特征序列是否做包含处理后再找分型
    segMinPens: 3,               // 线段最少由几笔构成

    // —— 中枢 ——
    zsSource: 'bi',              // 'bi' 用笔算中枢（颗粒度接近主流工具） | 'seg' 用线段算（教科书口径）
    zsMinParts: 3,               // 构成中枢的最少次级别走势数
    zsExtendUpdate: false,       // 中枢延伸时是否更新 ZG/ZD

    // —— 背驰 ——
    divMode: 'pen',              // 'pen' 滚动三笔比较（默认，稳定可用）
                                 // 'zs'  只比较被同一个中枢隔开的两个连接波（严格趋势背驰）
    divMinForceRatio: 0.85,      // 后段力度 / 前段力度 小于该比例才判背驰（0.85 = 衰减15%）
    divFallbackAmplitude: true,  // MACD 力度取不到时，退化为用价格幅度比较
    wavePatience: 1,             // 连续几次「同方向未能创新极值」才认定这个走势波结束
    forceMode: 'same',           // 'same' 同方向MACD柱面积 | 'abs' 绝对值之和 | 'perBar' 面积/根数
    macdFast: 12,
    macdSlow: 26,
    macdSignal: 9,

    // —— 买卖点 ——
    showBuy: true,
    showSell: true,
    pointsOnSegs: false,         // true 买卖点基于线段（少而严）；false 基于笔（默认，灵敏也更杂）
  };

  function optsOf(user) {
    var o = {};
    for (var k in DEFAULTS) o[k] = DEFAULTS[k];
    if (user) for (var k2 in user) if (o.hasOwnProperty(k2)) o[k2] = user[k2];
    return o;
  }

  /* ------------------------------------------------------- 通用取值工具 */

  function hi(k) { return k.h != null ? k.h : k.high; }
  function lo(k) { return k.l != null ? k.l : k.low; }
  function op(k) { return k.o != null ? k.o : k.open; }
  function cl(k) { return k.c != null ? k.c : k.close; }
  function tm(k) { return k.t != null ? k.t : k.time; }

  /* ======================================================================
   * 1. 包含处理
   *    相邻两 K 线存在包含关系（一根的高低点区间完全被另一根包住）时合并，
   *    合并方向由「已处理序列的最后两根」决定：
   *      向上：high = max(h1,h2), low = max(l1,l2)
   *      向下：high = min(h1,h2), low = min(l1,l2)
   * ==================================================================== */
  function mergeKlines(klines) {
    var out = [];
    for (var i = 0; i < klines.length; i++) {
      var k = klines[i];
      if (!isFinite(hi(k)) || !isFinite(lo(k))) continue;
      var cur = { high: hi(k), low: lo(k), si: i, ei: i };
      if (out.length === 0) { out.push(cur); continue; }

      var prev = out[out.length - 1];
      var contained = (cur.high <= prev.high && cur.low >= prev.low) ||
                      (cur.high >= prev.high && cur.low <= prev.low);
      if (!contained) { out.push(cur); continue; }

      var dir;
      if (out.length >= 2) {
        if (out[out.length - 1].high > out[out.length - 2].high) dir = 1;
        else if (out[out.length - 1].high < out[out.length - 2].high) dir = -1;
        else dir = out[out.length - 1].low > out[out.length - 2].low ? 1 : -1;
      } else {
        dir = prev.high >= cur.high ? -1 : 1;
      }
      if (dir > 0) {
        prev.high = Math.max(prev.high, cur.high);
        prev.low = Math.max(prev.low, cur.low);
      } else {
        prev.high = Math.min(prev.high, cur.high);
        prev.low = Math.min(prev.low, cur.low);
      }
      prev.ei = i;
    }
    return out;
  }

  /* ======================================================================
   * 2. 分型
   *    顶分型：中间 K 线的高低点均高于左右
   *    底分型：中间 K 线的高低点均低于左右
   *    注意：包含处理已保证相邻不含包，因此这里的判断不会出现模棱两可
   * ==================================================================== */
  function findFractals(merged) {
    var fxs = [];
    for (var i = 1; i < merged.length - 1; i++) {
      var p = merged[i - 1], c = merged[i], n = merged[i + 1];
      if (c.high > p.high && c.high > n.high && c.low > p.low && c.low > n.low) {
        fxs.push({ type: 1, mi: i, _k: merged[i].ei, high: c.high, low: c.low, price: c.high });
      } else if (c.low < p.low && c.low < n.low && c.high < p.high && c.high < n.high) {
        fxs.push({ type: -1, mi: i, _k: merged[i].ei, high: c.high, low: c.low, price: c.low });
      }
    }
    return fxs;
  }

  /** 连续同类型的分型只保留最极端的一个（后面的更极端则替换前面的） */
  function dedupFractals(fxs) {
    var res = [];
    for (var i = 0; i < fxs.length; i++) {
      var fx = fxs[i];
      var last = res[res.length - 1];
      if (!last || last.type !== fx.type) { res.push(copyObj(fx)); continue; }
      if (fx.type === 1) { if (fx.high >= last.high) res[res.length - 1] = copyObj(fx); }
      else { if (fx.low <= last.low) res[res.length - 1] = copyObj(fx); }
    }
    return res;
  }

  function copyObj(o) {
    var r = {};
    for (var k in o) r[k] = o[k];
    return r;
  }

  /* ======================================================================
   * 3. 笔
   *    在「严格交替的顶底序列」上成笔，两条硬条件：
   *      a) 间隔：两分型之间至少间隔 minFxGap 根处理后 K 线
   *      b) 方向：顶必须真正高于底jiantou（否则视为同一方向的震荡，不成笔）
   *    最后一段永远是「待确认」状态：因为后面的同类型分型随时可能把它替换掉
   * ==================================================================== */
  function buildBi(fxs, opts) {
    var bis = [];
    var i = 0;
    var guard = 0;

    while (i < fxs.length - 1 && guard++ < 100000) {
      var anchor = fxs[i];
      var next = i + 1;
      var target = -1;

      while (next < fxs.length) {
        var fx = fxs[next];

        // ① 同类型分型：更极端者取代当前锚点（并且要把已发出的那一笔同步延伸）
        if (fx.type === anchor.type) {
          if ((fx.type === 1 && fx.high > anchor.high) ||
              (fx.type === -1 && fx.low < anchor.low)) {
            extendLastPen(bis, anchor, fx);
            i = next;
            target = -2;                 // 标记：锚点已转移，回到外层重新搜索
            break;
          }
          next++;
          continue;
        }

        // ② 反向分型：是否满足成笔条件
        var gap = fx.mi - anchor.mi - 1;
        var up = (anchor.type === -1 && fx.type === 1);
        var ok = gap >= opts.minFxGap;
        if (ok && opts.biRequireBreak) {
          ok = up ? (fx.high > anchor.high) : (fx.low < anchor.low);
        }
        if (ok) { target = next; break; }
        next++;                          // 不够格，跳过继续找
      }

      if (target === -2) continue;       // 锚点转移，外层重新来
      if (target < 0) break;             // 后面再也配不出笔了
      bis.push(makePen(fxs[i], fxs[target]));
      i = target;
    }

    if (bis.length) bis[bis.length - 1].confirmed = false;  // 最后一笔待确认
    return bis;
  }

  function makePen(a, b) {
    var up = (a.type === -1 && b.type === 1);
    return {
      dir: up ? 1 : -1,
      startFx: a, endFx: b,
      startK: a._k, endK: b._k,
      startPrice: up ? a.low : a.high,
      endPrice: up ? b.high : b.low,
      high: Math.max(a.high, b.high),
      low: Math.min(a.low, b.low),
      confirmed: true
    };
  }

  /** 锚点被更极端的同类型分型取代时，同步延伸最后一笔的终点 */
  function extendLastPen(bis, oldAnchor, newAnchor) {
    if (!bis.length) return;
    var last = bis[bis.length - 1];
    if (last.endFx !== oldAnchor) return;
    last.endFx = newAnchor;
    last.endK = newAnchor._k;
    last.endPrice = last.dir > 0 ? newAnchor.high : newAnchor.low;
    last.high = Math.max(last.startFx.high, newAnchor.high);
    last.low = Math.min(last.startFx.low, newAnchor.low);
  }

  /* ======================================================================
   * 4. 线段
   *
   * 【feature】标准特征序列法
   *   以上升线段为例：线段内所有的「向下笔」构成特征序列。
   *   对特征序列做包含处理后，一旦出现顶分型，该上升线段即告终结。
   *   等价展开（上升线段在第 k 个顶 T_m 结束）需要同时满足：
   *      T_m > T_(m-1)   且   T_m > T_(m+1)     高点不再抬高
   *      B_m > B_(m-1)   且   B_m > B_(m+1)     低点被击破
   *   这解释了为什么「最后的线段总在变」——后面两笔没出来前，它在数学上就是未定的。
   *
   * 【simple】三笔简化法（更灵敏，适合短线）：
   *   向上线段：任意一次回调跌破上一次回调的低点 → 线段在前一个高点结束。
   * ==================================================================== */
  function buildSegments(bis, opts) {
    var segs = [];
    var n = bis.length;
    var s = 0;
    var guard = 0;
    while (s < n && guard++ < 20000) {
      if (n - s < opts.segMinPens) { segs.push(makeSeg(bis, s, n - 1, false)); break; }
      var end = opts.segAlgo === 'simple'
        ? findSegEndSimple(bis, s, opts)
        : findSegEndFeature(bis, s, opts);
      if (end < 0) { segs.push(makeSeg(bis, s, n - 1, false)); break; }
      segs.push(makeSeg(bis, s, end, true));
      s = end + 1;
    }
    return segs;
  }

  function makeSeg(bis, s, e, confirmed) {
    var high = -Infinity, low = Infinity;
    for (var i = s; i <= e; i++) {
      if (bis[i].high > high) high = bis[i].high;
      if (bis[i].low < low) low = bis[i].low;
    }
    return {
      dir: bis[s].dir,
      startBi: s, endBi: e,
      penCount: e - s + 1,
      startK: bis[s].startK, endK: bis[e].endK,
      startPrice: bis[s].startPrice, endPrice: bis[e].endPrice,
      high: high, low: low,
      confirmed: !!confirmed
    };
  }

  function findSegEndFeature(bis, s, opts) {
    var n = bis.length;
    var dir = bis[s].dir;
    for (var k = s + 2; k < n; k += 2) {
      if (k + 3 >= n) break;
      if (dir > 0) {
        var Tprev = bis[k - 2].endPrice, Tcur = bis[k].endPrice, Tnext = bis[k + 2].endPrice;
        var Bprev = bis[k - 1].endPrice, Bcur = bis[k + 1].endPrice, Bnext = bis[k + 3].endPrice;
        if (opts.featureMerge) {
          var m = mergeTriple(Tprev, Bprev, Tcur, Bcur, Tnext, Bnext, -1);
          Tprev = m[0]; Bprev = m[1]; Tcur = m[2]; Bcur = m[3]; Tnext = m[4]; Bnext = m[5];
        }
        if (Tcur > Tprev && Tcur > Tnext && Bcur > Bprev && Bcur > Bnext) return k;
      } else {
        var Dprev = bis[k - 2].endPrice, Dcur = bis[k].endPrice, Dnext = bis[k + 2].endPrice;
        var Uprev = bis[k - 1].endPrice, Ucur = bis[k + 1].endPrice, Unext = bis[k + 3].endPrice;
        if (opts.featureMerge) {
          var m2 = mergeTriple(Dprev, Uprev, Dcur, Ucur, Dnext, Unext, 1);
          Dprev = m2[0]; Uprev = m2[1]; Dcur = m2[2]; Ucur = m2[3]; Dnext = m2[4]; Unext = m2[5];
        }
        if (Dcur < Dprev && Dcur < Dnext && Ucur < Uprev && Ucur < Unext) return k;
      }
    }
    return -1;
  }

  /**
   * 对连续三个特征元素做包含合并（与 K 线的包含处理规则一致）
   * @param dir -1: 期望这组元素整体向下(用于上升线段的回调杆)；1: 向上
   */
  function mergeTriple(h1, l1, h2, l2, h3, l3, dir) {
    function contains(aH, aL, bH, bL) {
      return (bH <= aH && bL >= aL) || (bH >= aH && bL <= aL);
    }
    if (contains(h1, l1, h2, l2)) {
      if (dir < 0) { h2 = Math.min(h1, h2); l2 = Math.min(l1, l2); }
      else { h2 = Math.max(h1, h2); l2 = Math.max(l1, l2); }
    }
    if (contains(h2, l2, h3, l3)) {
      if (dir < 0) { h3 = Math.min(h2, h3); l3 = Math.min(l2, l3); }
      else { h3 = Math.max(h2, h3); l3 = Math.max(l2, l3); }
    }
    return [h1, l1, h2, l2, h3, l3];
  }

  function findSegEndSimple(bis, s, opts) {
    var n = bis.length;
    var dir = bis[s].dir;
    for (var k = s + 2; k < n; k += 2) {
      if (k + 1 >= n) break;
      if (dir > 0) {
        var prevLow = (k - 2 >= s) ? bis[k - 1].endPrice : -Infinity;
        if (bis[k + 1].endPrice < prevLow) return k;
      } else {
        var prevHigh = (k - 2 >= s) ? bis[k - 1].endPrice : Infinity;
        if (bis[k + 1].endPrice > prevHigh) return k;
      }
    }
    return -1;
  }

  /* ======================================================================
   * 5. 中枢
   *    连续 zsMinParts 个次级别走势的重叠区间：
   *      ZD = max(各段最低点)   ZG = min(各段最高点)
   *    若 ZD >= ZG 说明没有重叠（那是快速 trending，不是中枢）
   *    之后只要后续走势仍与 [ZD, ZG] 相交，中枢就继续延伸
   * ==================================================================== */
  function buildZhongshu(parts, opts) {
    var zss = [];
    var need = Math.max(2, opts.zsMinParts);
    var i = 0;
    while (i + need - 1 < parts.length) {
      var ZD = -Infinity, ZG = Infinity;
      for (var j = 0; j < need; j++) {
        ZD = Math.max(ZD, parts[i + j].low);
        ZG = Math.min(ZG, parts[i + j].high);
      }
      if (ZD >= ZG) { i++; continue; }

      var right = i + need - 1;
      for (var k = right + 1; k < parts.length; k++) {
        var p = parts[k];
        if (p.low < ZG && p.high > ZD) {
          if (opts.zsExtendUpdate) {
            ZG = Math.min(ZG, p.high);
            ZD = Math.max(ZD, p.low);
          }
          right = k;
        } else break;
      }
      zss.push({
        ZD: ZD, ZG: ZG,
        startPart: i, endPart: right,
        partCount: right - i + 1,
        startK: parts[i].startK, endK: parts[right].endK,
        level: 1
      });
      // 重要：产生“离开中枢”动作的那一个 part 不能算进下一个中枢，
      // 否则相邻中枢会首尾相接，中间没有过渡走势，背驰就永远无从比较。
      // 这里强制跳过它，让它成为两个中枢之间的连接波（= 前一个中枢的离开段）。
      i = right + 2;
    }
    return zss;
  }

  /* ======================================================================
   * 6. 背驰
   *    比较「进入中枢前那段」与「离开中枢那段」的力度（MACD 柱面积）。
   *    价格创新高（新低）而力度反而衰减 → 背驰。
   * ==================================================================== */
  /**
   * 从一个已知的次级别走势出发，按「是否还在创新极值」收集属于同一个走势波的 parts。
   *
   * 为什么不能直接用「两个中枢之间」来切波：中枢常常紧挨着出现（下一个中枢的第一个
   * part 紧接着上一个中枢的最后一个 part），那样"离开段"永远是空的，背驰永远检测不出来。
   * 所以这里改为纯价格行为驱动：一路往 同/反 交替的方向走，只要同方向的段还在创新极值
   * 就属于同一个波，连续 wavePatience 次创新失败才认为波已经结束。
   *
   * @param startIdx 波在该方向上的第一个次级别走势索引
   * @param forward  true=向后（离开中枢） false=向前回溯（进入中枢）
   * @param patience 连续几次失败算结束
   * @param lo,hi    parts 下标边界，防止跑到相邻中枢里面去
   * @returns {{from:number, to:number}} parts 下标闭区间，或 null
   */
  function extractWave(parts, startIdx, forward, patience, lo, hi) {
    patience = patience || 1;
    lo = lo === undefined ? 0 : Math.max(0, lo);
    hi = hi === undefined ? parts.length - 1 : Math.min(parts.length - 1, hi);
    if (startIdx < lo || startIdx > hi) return null;
    var dir = parts[startIdx].dir;
    var best = dir > 0 ? parts[startIdx].high : parts[startIdx].low;
    var step = forward ? 1 : -1;
    var last = startIdx;
    var fail = 0;
    for (var i = startIdx + step; i >= lo && i <= hi; i += step) {
      if (parts[i].dir === dir) {
        var ext = dir > 0 ? parts[i].high : parts[i].low;
        var improves = dir > 0 ? ext > best : ext < best;
        if (improves) { best = ext; fail = 0; }
        else { fail++; if (fail >= patience) break; }
      }
      last = i;
    }
    return forward ? { from: startIdx, to: last } : { from: last, to: startIdx };
  }

  function waveOf(parts, a, b) {
    if (a < 0) a = 0;
    if (b >= parts.length) b = parts.length - 1;
    if (b < a) return null;
    var high = -Infinity, low = Infinity;
    for (var i = a; i <= b; i++) {
      if (parts[i].high > high) high = parts[i].high;
      if (parts[i].low < low) low = parts[i].low;
    }
    return {
      dir: parts[a].dir, fromPart: a, toPart: b,
      partCount: b - a + 1,
      startK: parts[a].startK, endK: parts[b].endK,
      startPrice: parts[a].startPrice, endPrice: parts[b].endPrice,
      high: high, low: low
    };
  }

  /**
   * 把 parts 序列重排成「连接波 - 中枢 - 连接波 - 中枢 ……」的交替序列。
   *
   * 连接波 = 两个相邻中枢之间的整段走势（以及首中枢之前、末中枢之后的部分）。
   * 趋势背驰比的就是：被同一个中枢隔开的前后两个连接波。
   * 这样做不再依赖「第几个 part」，中枢数量变了、奇偶变了都不会失效。
   */
  function buildSequence(parts, zss) {
    var seq = [];
    var from = 0;
    for (var i = 0; i < zss.length; i++) {
      var zs = zss[i];
      if (zs.startPart > from) seq.push({ type: 'conn', from: from, to: zs.startPart - 1 });
      seq.push({ type: 'zs', zs: zs, zsIndex: i });
      from = zs.endPart + 1;
    }
    if (from <= parts.length - 1) seq.push({ type: 'conn', from: from, to: parts.length - 1 });
    return seq;
  }

  /** 走势波的净方向：终点价格高于起点即向上（比取第一个 part 的方向稳健） */
  function netDir(w) {
    if (w.endPrice > w.startPrice) return 1;
    if (w.endPrice < w.startPrice) return -1;
    return w.dir;
  }

  function detectDivergence(parts, zss, hist, klines, opts) {
    return opts.divMode === 'zs'
      ? detectDivergenceByZS(parts, zss, hist, klines, opts)
      : detectDivergenceBySequence(parts, zss, hist, klines, opts);
  }

  /**
   * 【默认模式】滚动三笔比较 —— 最贴近实际看图习惯，也最稳定。
   * 相邻三笔里第 1 笔与第 3 笔必然同向，中间那笔（连同三笔的重叠区）就是笔级别中枢。
   * 判定：第 3 笔创出超过第 1 笔的新极值，但力度反而更小 → 背驰。
   */
  function detectDivergenceBySequence(parts, zss, hist, klines, opts) {
    var divs = [];
    for (var i = 0; i + 2 < parts.length; i++) {
      var a = parts[i], mid = parts[i + 1], c = parts[i + 2];
      if (a.dir !== c.dir) continue;

      // 三笔必须有公共重叠区才算「中间存在一个中枢」
      var ZD = Math.max(a.low, mid.low, c.low);
      var ZG = Math.min(a.high, mid.high, c.high);
      if (ZD >= ZG) continue;

      var dir = a.dir;
      var madeNewExtreme = dir > 0 ? (c.high > a.high) : (c.low < a.low);
      if (!madeNewExtreme) continue;

      var fA = IND.forceRange(hist, a.startK, a.endK, dir, opts.forceMode);
      var fC = IND.forceRange(hist, c.startK, c.endK, dir, opts.forceMode);
      var rA = Math.abs(a.endPrice - a.startPrice);
      var rC = Math.abs(c.endPrice - c.startPrice);

      var ratio, basis;
      if (fA > 0 && fC > 0) { ratio = fC / fA; basis = 'macd'; }
      else if (opts.divFallbackAmplitude && rA > 0) { ratio = rC / rA; basis = 'amplitude'; }
      else continue;

      if (ratio < opts.divMinForceRatio) {
        divs.push({
          type: dir > 0 ? -1 : 1,
          kind: dir > 0 ? 'top' : 'bottom',
          targetK: extremeKIndex(klines, c.startK, c.endK, dir > 0 ? 'high' : 'low'),
          // 信号确立所需的信息终点：第 3 笔走完的那一根（targetK 可能早于它）
          readyK: c.endK,
          targetPrice: dir > 0 ? c.high : c.low,
          zsIndex: zsIndexCovering(zss, i, i + 2),
          fEnter: basis === 'macd' ? fA : rA,
          fLeave: basis === 'macd' ? fC : rC,
          ratio: ratio, basis: basis,
          enterParts: 1, leaveParts: 1
        });
      }
    }
    return divs;
  }

  function zsIndexCovering(zss, fromPart, toPart) {
    for (var i = 0; i < zss.length; i++) {
      if (zss[i].startPart <= fromPart && zss[i].endPart >= toPart) return i;
    }
    return -1;
  }

  /**
   * 【严格模式】比较被同一个中枢隔开的前后两个连接波（教科书意义上的趋势背驰）。
   * 注意：中枢常常首尾相接，中间没有过渡走势，此时本模式会一个信号都给不出，
   * 所以默认不启用，只提供给想做严格复盘的场景。
   */
  function detectDivergenceByZS(parts, zss, hist, klines, opts) {
    var divs = [];
    var seq = buildSequence(parts, zss);

    for (var i = 1; i < seq.length - 1; i++) {
      if (seq[i].type !== 'zs') continue;
      var before = seq[i - 1], after = seq[i + 1];
      if (!before || !after || before.type !== 'conn' || after.type !== 'conn') continue;

      var enter = waveOf(parts, before.from, before.to);
      var leave = waveOf(parts, after.from, after.to);
      if (!enter || !leave) continue;
      enter.dir = netDir(enter);
      leave.dir = netDir(leave);
      if (enter.dir !== leave.dir) continue;        // 只有趋势中的同向后段才谈背驰

      // 必须创出新的极值，才算「趋势延续但力竭」
      var madeNewExtreme = enter.dir > 0
        ? (leave.high > enter.high)
        : (leave.low < enter.low);
      if (!madeNewExtreme) continue;

      var fEnter = IND.forceRange(hist, enter.startK, enter.endK, enter.dir, opts.forceMode);
      var fLeave = IND.forceRange(hist, leave.startK, leave.endK, leave.dir, opts.forceMode);
      var rEnter = Math.abs(enter.endPrice - enter.startPrice);
      var rLeave = Math.abs(leave.endPrice - leave.startPrice);

      var ratio, basis;
      if (fEnter > 0 && fLeave > 0) {
        ratio = fLeave / fEnter;
        basis = 'macd';
      } else if (opts.divFallbackAmplitude && rEnter > 0) {
        // MACD 力度取到 0 说明该段 MACD 柱全程反向，退化用价格幅度比较
        ratio = rLeave / rEnter;
        basis = 'amplitude';
      } else {
        continue;
      }

      if (ratio < opts.divMinForceRatio) {
        var isTop = enter.dir > 0;
        divs.push({
          type: isTop ? -1 : 1,
          kind: isTop ? 'top' : 'bottom',
          targetK: extremeKIndex(klines, leave.startK, leave.endK, isTop ? 'high' : 'low'),
          readyK: leave.endK,
          targetPrice: isTop ? leave.high : leave.low,
          zsIndex: seq[i].zsIndex,
          enterParts: enter.partCount, leaveParts: leave.partCount,
          fEnter: basis === 'macd' ? fEnter : rEnter,
          fLeave: basis === 'macd' ? fLeave : rLeave,
          ratio: ratio, basis: basis
        });
      }
    }
    return divs;
  }

  /** 在 [a, b] 区间内找到走出最高/最低价的那根 K 线索引（用于精确定位背驰点） */
  function extremeKIndex(klines, a, b, field) {
    if (!klines || !klines.length) return b;
    a = Math.max(0, a); b = Math.min(klines.length - 1, b);
    var bestIdx = b, best = -Infinity;
    for (var i = a; i <= b; i++) {
      var v = field === 'high' ? hi(klines[i]) : lo(klines[i]);
      var key = field === 'high' ? v : -v;
      if (isFinite(key) && key > best) { best = key; bestIdx = i; }
    }
    return bestIdx;
  }

  /* ======================================================================
   * 7. 三类买卖点
   *    一类：本级别某方向走势背驰的极值点
   *    二类：一类之后第一次回抽（反向次级回调）未破一类极值
   *    三类：离开中枢后回抽，未重新落回中枢区间
   * ==================================================================== */
  function detectPoints(parts, zss, divs, opts) {
    var pts = [];
    if (!opts.showBuy && !opts.showSell) return pts;

    /**
     * @param k        标记的图形位置（K 线索引）
     * @param readyK   该信号**确立**所需信息的最后一根 K 线索引（>= k）
     *                 判定它依赖的结构在 readyK 走到才完整；此前它尚未"存在"。
     *                 回测成交价应取 readyK + 1 根的开盘（或之后），不可用第 k 根收盘价。
     */
    function add(level, type, k, price, note, extra, readyK) {
      pts.push({ level: level, type: type, _k: k,
                 readyK: readyK == null ? k : Math.max(k, readyK),
                 price: price, note: note,
                 confirmed: false, extra: extra || null });
    }

    // —— 一类：本级别背驰的极值点 ——
    for (var i = 0; i < divs.length; i++) {
      var d = divs[i];
      var isBuy = d.type > 0;
      if (isBuy && !opts.showBuy) continue;
      if (!isBuy && !opts.showSell) continue;
      add(1, d.type, d.targetK, d.targetPrice,
          isBuy ? '一买·底背驰' : '一卖·顶背驰',
          { ratio: d.ratio, basis: d.basis }, d.readyK);
    }

    // —— 三类：离开中枢后的第一次回抽，未重新落回中枢区间 ——
    for (var z = 0; z < zss.length; z++) {
      var zs = zss[z];
      var leaveIdx = zs.endPart + 1;
      if (leaveIdx >= parts.length) continue;
      var dir = parts[leaveIdx].dir;

      // 只看离开之后出现的第一次反向回抽
      for (var j = leaveIdx + 1; j < parts.length; j++) {
        if (parts[j].dir === dir) continue;
        var pp = parts[j];
        if (dir > 0 && opts.showBuy && pp.low > zs.ZG) {
          add(3, 1, pp.endK, pp.low, '三买·回抽不入中枢', { zs: z });
        } else if (dir < 0 && opts.showSell && pp.high < zs.ZD) {
          add(3, -1, pp.endK, pp.high, '三卖·反抽不入中枢', { zs: z });
        }
        break;
      }
    }

    // —— 二类：一类之后的第一次回抽未创新低/新高 ——
    //    注意要跳过「一类之后的第一笔反弹」，真正要看的是再下一笔、与原先同向的回抽。
    for (var q = 0; q < divs.length; q++) {
      var d = divs[q];
      var isBuy = d.type > 0;
      if ((isBuy && !opts.showBuy) || (!isBuy && !opts.showSell)) continue;
      var refIdx = firstPartIndexAfter(parts, d.targetK);
      if (refIdx < 0) continue;
      var refDir = parts[refIdx].dir;
      for (var t = refIdx + 1; t < parts.length; t++) {
        if (parts[t].dir !== refDir) continue;       // 跳过反向的第一笔（那是反弹本身）
        var cand = parts[t];
        if (isBuy && cand.low > d.targetPrice) {
          add(2, 1, cand.endK, cand.low, '二买·回抽不破前低', { fromDiv: q });
        } else if (!isBuy && cand.high < d.targetPrice) {
          add(2, -1, cand.endK, cand.high, '二卖·反抽不破前高', { fromDiv: q });
        }
        break;                                        // 只看紧邻的第一次回抽
      }
    }
    return pts;
  }

  /** 找出第一根「终点不早于 k」的次级别走势索引 */
  function firstPartIndexAfter(parts, k) {
    for (var i = 0; i < parts.length; i++) if (parts[i].endK >= k) return i;
    return -1;
  }

  /* ======================================================================
   * 顶层入口
   * @param klines 原始K线数组
   * @param userOpts 覆盖默认参数
   * ==================================================================== */
  function analyze(klines, userOpts) {
    var opts = optsOf(userOpts);
    if (!klines || klines.length < 5) {
      return { klines: klines || [], merged: [], fractals: [], bis: [], segs: [],
               zhongshus: [], divergences: [], points: [], macd: null, opts: opts, stats: {} };
    }

    var merged = opts.merge ? mergeKlines(klines) : klines.map(function (k, i) {
      return { high: hi(k), low: lo(k), si: i, ei: i };
    });

    var fractalsRaw = findFractals(merged);
    var fractals = dedupFractals(fractalsRaw);
    var bis = buildBi(fractals, opts);
    var segs = buildSegments(bis, opts);

    /* 统一提取成「走势段」视图；中枢与背驰/买卖点各取各的源，互不耦合 */
    function toParts(arr) {
      return arr.map(function (p) {
        return { dir: p.dir, startK: p.startK, endK: p.endK, high: p.high, low: p.low,
                 startPrice: p.startPrice, endPrice: p.endPrice };
      });
    }
    var parts = opts.zsSource === 'seg' ? toParts(segs) : toParts(bis);   // 中枢的来源

    var zhongshus = buildZhongshu(parts, opts);

    var closes = klines.map(cl);
    var macd = IND.macd(closes, opts.macdFast, opts.macdSlow, opts.macdSignal);

    /* 背驰/买卖点的来源只看 pointsOnSegs，不再被 zsSource 牵着走
       （旧实现写成 `pointsOnSegs ? parts : bis`，zsSource='bi' 时两个分支都落到笔上，开关形同虚设）*/
    var pointParts = opts.pointsOnSegs ? toParts(segs) : toParts(bis);
    var divergences = detectDivergence(pointParts, zhongshus, macd.hist, klines, opts);
    var points = detectPoints(pointParts, zhongshus, divergences, opts);

    // 已确认 = 后面还有新的走势延伸出来
    var lastK = klines.length - 1;
    for (var i = 0; i < points.length; i++) {
      // 判据：确立信号的那一根之后还要再走出 1 根（分型右侧确认），才算彻底定型
      points[i].confirmed = (lastK - points[i].readyK) >= 3;
    }

    return {
      klines: klines,
      merged: merged,
      fractals: fractals,
      fractalsRaw: fractalsRaw,
      bis: bis,
      segs: segs,
      parts: parts,
      zhongshus: zhongshus,
      divergences: divergences,
      points: points,
      macd: macd,
      opts: opts,
      stats: {
        n: klines.length,
        mergedCount: merged.length,
        fxCount: fractals.length,
        biCount: bis.length,
        segCount: segs.length,
        zsCount: zhongshus.length,
        divCount: divergences.length,
        pointCount: points.length,
        lastClose: closes[closes.length - 1],
        trend: trendOf(segs, zhongshus)
      }
    };
  }

  function trendOf(segs, zss) {
    if (!zss.length) return segs.length ? (segs[segs.length - 1].dir > 0 ? 'up' : 'down') : 'unknown';
    var last = zss[zss.length - 1];
    return last.ZG <= (zss.length > 1 ? zss[zss.length - 2].ZD : -Infinity) ? 'down'
         : last.ZD >= (zss.length > 1 ? zss[zss.length - 2].ZG : Infinity) ? 'up'
         : 'consolidation';
  }

  return {
    DEFAULTS: DEFAULTS,
    analyze: analyze,
    mergeKlines: mergeKlines,
    findFractals: findFractals,
    dedupFractals: dedupFractals,
    buildBi: buildBi,
    buildSegments: buildSegments,
    buildZhongshu: buildZhongshu,
    detectDivergence: detectDivergence,
    detectPoints: detectPoints,
    buildSequence: buildSequence,
    extractWave: extractWave,
    waveOf: waveOf
  };
});
