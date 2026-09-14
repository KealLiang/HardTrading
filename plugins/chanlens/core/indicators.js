/* ==========================================================================
 * indicators.js —— 技术指标（纯函数，无 DOM 依赖，Node / 浏览器通用）
 *
 * 只实现缠论背驰判定真正需要的部分：EMA 与 MACD。
 * 背驰的标准度量是「同向两段走势所对应的 MACD 柱面积」
 * （严格说是先把相邻同号的柱状体合并后再算面积，这里提供两种算法）。
 * ========================================================================== */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CLIndicators = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** 指数移动平均 */
  function ema(values, n) {
    if (!Array.isArray(values) || values.length === 0) return [];
    const alpha = 2 / (n + 1);
    const out = new Array(values.length);
    out[0] = values[0];
    for (let i = 1; i < values.length; i++) {
      out[i] = alpha * values[i] + (1 - alpha) * out[i - 1];
    }
    return out;
  }

  /**
   * MACD
   * @returns {{dif:number[], dea:number[], hist:number[], histRaw:number[]}}
   *          hist 单位为原始价格差（dif-dea），histRaw 为 hist*2 的常见口径
   */
  function macd(closes, fast, slow, signal) {
    fast = fast || 12;
    slow = slow || 26;
    signal = signal || 9;
    const n = closes.length;
    if (n === 0) return { dif: [], dea: [], hist: [], histRaw: [] };

    const ef = ema(closes, fast);
    const es = ema(closes, slow);
    const dif = new Array(n);
    for (let i = 0; i < n; i++) dif[i] = ef[i] - es[i];
    const dea = ema(dif, signal);
    const hist = new Array(n);
    const histRaw = new Array(n);
    for (let i = 0; i < n; i++) {
      hist[i] = dif[i] - dea[i];
      histRaw[i] = hist[i] * 2;
    }
    return { dif: dif, dea: dea, hist: hist, histRaw: histRaw };
  }

  /**
   * 区间力度：给定 [startIdx, endIdx]（含端点）之间的 K 线，度量这一段趋势的力度。
   *
   * @param hist       MACD 柱状体数组（hist[i]，有正负号）
   * @param startIdx   起始 K 线索引（原始未处理 K 线索引）
   * @param endIdx     结束 K 线索引
   * @param dir        1=向上段，-1=向下段
   * @param mode       'same'   只累加与 dir 同号的柱（教科书口径，= 合并同号柱后的面积）
   *                   'abs'    累加区间内所有柱的绝对值之和
   *                   'perBar' 'same' 的面积再除以 K 线根数，消除「段越长面积自然越大」的偏差
   */
  function forceRange(hist, startIdx, endIdx, dir, mode) {
    mode = mode || 'same';
    const a = Math.max(0, Math.min(startIdx, endIdx));
    const b = Math.min(hist.length - 1, Math.max(startIdx, endIdx));
    if (b <= a) return 0;
    const bars = b - a + 1;

    // 'same' 与 'area' 在数学上等价：同号连续柱合并求和 = 逐根同号柱求和
    if (mode === 'abs') {
      let s = 0;
      for (let i = a; i <= b; i++) s += Math.abs(hist[i]);
      return s;
    }
    let sum = 0;
    for (let i = a; i <= b; i++) {
      if (dir > 0 && hist[i] > 0) sum += hist[i];
      else if (dir < 0 && hist[i] < 0) sum += Math.abs(hist[i]);
    }
    return mode === 'perBar' ? sum / bars : sum;
  }

  return { ema: ema, macd: macd, forceRange: forceRange };
});
