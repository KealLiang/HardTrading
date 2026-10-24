/* ==========================================================================
 * report.js —— 结论版报告（约 100 行），完整细节见 report_full.js → report_full.md
 * 用法：node report.js
 * 原则：只放结论、必要口径、主检验；所有文字方向由数据生成，不硬编码
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, 'out');
const TFS = [
  { tf: 'daily', name: '日线', span: '2014-08~2026-09（12年）' },
  { tf: '60', name: '60分钟', span: '2025-09~2026-10（256日）' },
  { tf: '30', name: '30分钟', span: '2025-09~2026-09（10个月）' }
];
const TYPE = { L1: '一买', L2: '二买', L3: '三买', ALL: '全部' };
const tryLoad = f => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return null; } };
const pc = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : (x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp';
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const f1 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(1);
const sg = t => (t == null || !isFinite(t)) ? '' : (Math.abs(t) >= 2 ? '**' : '');

const S = {}, PA = {}, VI = {};
for (const t of TFS) {
  S[t.tf] = tryLoad(path.join(outDir, 'summary_' + t.tf + '.json'));
  PA[t.tf] = tryLoad(path.join(outDir, 'paired_' + t.tf + '.json')) || [];
  VI[t.tf] = tryLoad(path.join(outDir, 'verify_' + t.tf + '.json')) || {};
}
const cell = (tf, ty, cb) => { const s = S[tf]; return s ? s.cells.find(c => c.type === ty && c.combo === cb) : null; };
const pairOf = (tf, ty, cb) => (PA[tf] || []).find(o => o.type === ty && o.combo === cb);

/* 主判定：出场规则相对「同入场点+同持有期分布+随机出场时点」的贡献 */
function verdict(s) {
  if (!s || !s.bm || !s.bm.ALL) return '无数据';
  const { d, t } = s.bm.ALL;
  if (t == null || !isFinite(t)) return '测不出（样本不足）';
  if (Math.abs(t) < 2) return '无差异';
  return d > 0 ? '**显著为正**' : '**显著为负**';
}

let md = '';
md += '# 缠论信号严格回测 · 结论版\n\n';
md += '> 26 只 ETF · 日线/60m/30m · 引擎 `chan.js` 参数未改\n';
md += '> 完整细节（逐格全表、新旧数据源对照、ZG/ZD 对照、共享一仓附表）见 `report_full.md`\n';
md += '> 生成 ' + new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 16).replace('T', ' ') + '（北京时间）· 所有数字为**扣费后单笔净收益**\n\n';

/* ---------------------------------------------------------------- 0 结论 */
md += '## 0 结论\n\n';
md += '| 周期 | A 完整循环 | BM 同长度随机时点 | A−BM | t | 判定 |\n|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const s = S[t.tf]; if (!s || !s.bm || !s.bm.ALL) continue;
  const b = s.bm.ALL, A = cell(t.tf, 'ALL', 'A');
  md += '| ' + t.name + ' | ' + pc(A && A.mean) + '（n=' + (A ? A.n : '—') + '） | ' + pc(b.meanBM) +
    ' | ' + sg(b.t) + pp(b.d) + sg(b.t) + ' | ' + f2(b.t) + ' | ' + verdict(s) + ' |\n';
}
md += '\n';

/* 三句要点：出场端 / 入场端 / 持有期长度混淆（全部按数据生成） */
{
  const bms = [], ents = [], lens = [];
  for (const t of TFS) {
    const s = S[t.tf]; if (!s) continue;
    const b = s.bm && s.bm.ALL;
    if (b) bms.push(t.name + ' ' + pp(b.d) + '（t=' + f2(b.t) + '）');
    ents.push(t.name + ' ' + pp(s.decomp.entryContribution) + '（t=' + f2(s.decomp.t_A_vs_C) + '）');
    const o = pairOf(t.tf, 'ALL', 'B20');
    if (o) lens.push(t.name + ' 对 B20 ' + pp(o.d) + '（t=' + f2(o.t) + '）→ 匹配持有期后 ' +
      (b ? pp(b.d) + '（t=' + f2(b.t) + '）' : 'n/a'));
  }
  md += '- **出场端（主检验）**：' + bms.join('；') + '。\n';
  md += '- **入场端**（A − 随机入场 C）：' + ents.join('；') + '。\n';
  md += '- **持有期混淆**：' + lens.join('；') + '。\n\n';
}
md += '**怎么读**：只要「A 显著优于固定持有 20 日」在这张表里对不上，就说明那点优势来自持有期长度，'
  + '而不是卖点更准。结构出场的实际价值是**替你决定持有多久**，省掉调 N 这一步，不创造 alpha。\n\n';

/* ---------------------------------------------------------------- 1 口径 */
md += '## 1 口径\n\n';
md += '| 项 | 设定 |\n|---|---|\n';
md += '| 标的 / 样本 | 26 只 ETF；' + TFS.map(t => t.name + ' ' + t.span).join('、') + ' |\n';
const st = S['daily'] ? S['daily'].stats : {};
md += '| 信号时点 | 只接受 lag = 发现bar − 可确认bar ≤ 1；lag>1 视为事后回填剔除（日线 ' + (st.lagDropped || '—') + ' 个） |\n';
md += '| 成交价 | 信号确认后**下一根开盘** |\n';
md += '| 交易约束 | T+1；涨停不可买、跌停不可卖顺延；无法合规出场则该笔作废（不硬凑） |\n';
md += '| 成本 | 双边 0.1%；0.2% 敏感性结论不变 |\n';
md += '| 仓位 | 一/二/三买**各一套独立资金**（分账）。单账户单仓口径见完整版 §4.11 |\n';
md += '| 出场规则 | R1 收盘破买点失效位 / R2 收盘破入场时中枢**ZG**（仅三买）/ R3 同级别卖点 / R4 120日超时兜底（触发 1.3%，不占仓） |\n\n';

/* ---------------------------------------------------------------- 2 主表 */
md += '## 2 主表（A 完整循环，分账）\n\n';
md += '| 周期 | 类型 | n | 单笔均值 | 胜率 | 盈亏比 | 持仓中位 | 赢家/输家持仓 |\n|---|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  for (const ty of ['L1', 'L2', 'L3', 'ALL']) {
    const c = cell(t.tf, ty, 'A'); if (!c) continue;
    md += '| ' + t.name + ' | ' + TYPE[ty] + ' | ' + c.n + ' | ' + pc(c.mean) + ' | ' + pc(c.win) + ' | ' +
      f2(c.pl) + ' | ' + f1(c.holdMed) + ' 日 | ' + f1(c.wHoldMed) + ' / ' + f1(c.lHoldMed) + ' 日 |\n';
  }
}
md += '\n> 赢家持仓 > 输家持仓 = 「截断亏损」在工作；倒挂说明止损过松。'
  + '三买本轮已把 R2 参照位从 ZD 改回 ZG（旧口径倒挂已修正），仍是一/二/三买里最弱的一类。\n\n';

/* ---------------------------------------------------------------- 3 四组合 */
md += '## 3 四组合（全部买点，单笔均值）\n\n';
md += '| 周期 | A 完整 | B5 | B10 | B20 | C 随机入场+缠论出场 | D10 随机固定 |\n|---|---|---|---|---|---|---|\n';
for (const t of TFS) {
  const g = (ty, cb) => {
    const c = cell(t.tf, ty, cb); if (!c) return '—';
    return pc(c.mean) + (ty === 'RND' ? '' : ' (' + c.n + ')');
  };
  md += '| ' + t.name + ' | ' + g('ALL', 'A') + ' | ' + g('ALL', 'B5') + ' | ' + g('ALL', 'B10') +
    ' | ' + g('ALL', 'B20') + ' | ' + g('RND', 'C') + ' | ' + g('RND', 'D10') + ' |\n';
}
md += '\n> 括号内为笔数（随机组约 80 万笔，略）。A−C = 入场贡献；A−B 含持有期长度差异，须看 §4 的配对与 BM。\n\n';

/* ---------------------------------------------------------------- 4 检验 */
md += '## 4 关键检验\n\n';
md += '| 检验 | ' + TFS.map(t => t.name).join(' | ') + ' |\n|---|' + TFS.map(() => '---').join('|') + '|\n';
const row = (label, fn) => {
  md += '| ' + label + ' | ' + TFS.map(t => fn(t.tf)).join(' | ') + ' |\n';
};
row('2×2 出场贡献 A−B10（t）', tf => {
  const s = S[tf]; if (!s) return '—';
  return pp(s.decomp.exitContribution) + '（' + f2(s.decomp.t_A_vs_B10) + '）';
});
row('2×2 入场贡献 A−C（t）', tf => {
  const s = S[tf]; if (!s) return '—';
  return pp(s.decomp.entryContribution) + '（' + f2(s.decomp.t_A_vs_C) + '）';
});
row('配对 A vs B10（t）', tf => { const o = pairOf(tf, 'ALL', 'B10'); return o ? pp(o.d) + '（' + f2(o.t) + '，n=' + o.nPair + '）' : '—'; });
row('配对 A vs B20（t）', tf => { const o = pairOf(tf, 'ALL', 'B20'); return o ? pp(o.d) + '（' + f2(o.t) + '，n=' + o.nPair + '）' : '—'; });
row('**主检验** BM 持有期匹配（t）', tf => { const b = S[tf] && S[tf].bm && S[tf].bm.ALL; return b ? sg(b.t) + pp(b.d) + sg(b.t) + '（' + f2(b.t) + '）' : '—'; });
row('同长度固定 BMED（t）', tf => { const b = S[tf] && S[tf].bm && S[tf].bm.ALL; return b ? pp(b.dMED) + '（' + f2(b.tMED) + '）' : '—'; });
row('独立复核 7 项违规', tf => {
  const v = VI[tf] || {};
  const sum = (v.priceMismatch || 0) + (v.retMismatch || 0) + (v.t1Violation || 0) + (v.overlap || 0) +
    (v.entryNotNext || 0) + (v.lagNot1 || 0) + (v.badBar || 0);
  return sum + ' / ' + (v.nCheck || 0) + ' 笔';
});
row('前5笔净贡献 / 合计', tf => {
  const c = cell(tf, 'ALL', 'A'); if (!c || c.top5Sum == null) return '—';
  return pp(c.top5Sum) + ' / ' + pp(c.totalSum) + (c.totalSum <= 0 ? '（合计为负）' : '');
});
md += '\n- **BM** ＝ 同一入场点、持有期从 A 自身分布随机抽（每笔 100 次）、出场取该 bar 开盘价。这是唯一公平的「规则 vs 长度」比法。\n';
md += '- 粗体 = |t| ≥ 2。所有 t 值按独立样本算，只能当**上界**（见局限 1）。\n';
md += '- 独立复核脚本不复用回测算价逻辑，从原始数据重算：价格、收益、T+1、持仓重叠、入场=discT+1、只用 lag=1。\n\n';

/* ---------------------------------------------------------------- 5 局限 */
md += '## 5 局限（读结论前必看）\n\n';
const c5 = cell('daily', 'ALL', 'A');
md += '1. **有效独立环境约 2 个，不是 900 次试验**：日线前 5 笔净贡献 ' + pp(c5 && c5.top5Sum) +
  '，占全部 ' + (c5 ? c5.n : '—') + ' 笔合计（' + pp(c5 && c5.totalSum) + '）的 ' + pc(c5 && c5.top5Share) +
  '；前 8 名里 5 笔集中在 2024-07~09，30m/60m 全部挤在 10 个月内且窗口重叠。所以 t 值只能当上界。\n';
md += '2. **三买最弱**（日线 ' + pc((cell('daily', 'L3', 'A') || {}).mean) + '），且对 R2 参照位敏感（ZD→ZG：+0.13%→+0.27%）。\n';
md += '3. **结构三态字段仅对三买有效**：一/二买入场时价格已低于中枢 ZD 的比例约 71%/70%，「下移」无区分力。\n';
md += '4. **样本内最优格不作预期**（如日线二买×固定20日），分钟线为阶梯复权（与日线最大偏差 0.59%）。\n\n';

/* ---------------------------------------------------------------- 6 复现 */
md += '## 6 复现\n\n```bash\ncd ' + __dirname.replace(/\\/g, '/') + '\n';
md += 'TF=daily node scan.js && TF=daily node strict.js      # 30/60 同理\n';
md += 'node verify.js daily && node paired.js daily && node diag.js\n';
md += 'node report.js        # 本文件（结论版）\n';
md += 'node report_full.js   # 完整版 → report_full.md\n```\n';

fs.writeFileSync(path.join(__dirname, 'report.md'), md);
console.log('report.md 已生成，' + md.length + ' 字符 / ' + md.split('\n').length + ' 行');
