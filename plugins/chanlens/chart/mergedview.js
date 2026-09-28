/* ==========================================================================
 * mergedview.js —— 「缠论 K 线」显示视图（纯显示层变换）
 *
 * 缠论要求先做「K 线包含处理」，得到的合并序列（merged）才是分型/笔/线段/
 * 中枢/背驰的真正输入。本模块只负责把这段已经算好的 merged 序列，变换成
 * 一份「可以直接交给 renderer 画」的 K 线 + 结果副本：
 *
 *   - 每根缠论 K 线 = 合并区间首根开盘 + 末根收盘，高低取合并后的 [low, high]
 *   - 成交量/成交额取区间之和；MACD 按区间末根采样（数值不变，只压缩横坐标）
 *   - 所有结构下标字段（_k / mi / startK / endK / targetK / readyK）重映射到新下标
 *
 * 判定结果一个字节都不改，纯显示切换，因此不会引入任何未来函数风险。
 * 无 DOM 依赖，Node 里可直接单测。
 * ========================================================================== */
'use strict';

(function (g) {
  'use strict';

  function build(klines, res) {
    var merged = (res && res.merged) || [];
    if (!merged.length || !klines || !klines.length) {
      return { klines: klines, result: res };
    }

    var map = new Array(klines.length);      // 原始下标 → 缠论 K 线下标
    var mk = [];
    for (var i = 0; i < merged.length; i++) {
      var m = merged[i];
      var a = klines[m.si], b = klines[m.ei];
      if (!a || !b) continue;
      var idx = mk.length, v = 0, amt = 0;
      for (var j = m.si; j <= m.ei; j++) {
        map[j] = idx;
        v += (klines[j].v || 0);
        amt += (klines[j].a || 0);
      }
      mk.push({
        t: b.t, _t: b._t, _n: (m.ei - m.si + 1),   // _n = 这根缠论K线吞掉了几根原始K
        o: a.o, c: b.c, h: m.high, l: m.low,
        v: v, a: amt, pct: b.pct, turn: b.turn
      });
    }
    if (!mk.length) return { klines: klines, result: res };

    function rm(v) { return (v == null || map[v] == null) ? v : map[v]; }
    function dup(arr, fields) {
      return (arr || []).map(function (o) {
        var n = {};
        for (var k in o) n[k] = o[k];
        fields.forEach(function (f) { if (n[f] != null) n[f] = rm(n[f]); });
        return n;
      });
    }
    function sample(src) {
      if (!src) return src;
      var out = new Array(mk.length);
      for (var i = 0; i < mk.length; i++) {
        var e = merged[i] ? merged[i].ei : i;
        out[i] = e < src.length ? src[e] : 0;
      }
      return out;
    }

    var view = {
      klines: mk,
      fractals: dup(res.fractals, ['_k', 'mi']),
      bis: dup(res.bis, ['startK', 'endK']),
      segs: dup(res.segs, ['startK', 'endK']),
      zhongshus: dup(res.zhongshus, ['startK', 'endK']),
      divergences: dup(res.divergences, ['targetK', 'startK', 'endK']),
      points: dup(res.points, ['_k', 'readyK']),
      macd: res.macd ? {
        hist: sample(res.macd.hist), dif: sample(res.macd.dif), dea: sample(res.macd.dea)
      } : null,
      opts: res.opts, stats: res.stats, merged: merged
    };
    return { klines: mk, result: view };
  }

  g.CLMergedView = { build: build };
})(typeof self !== 'undefined' ? self : this);
