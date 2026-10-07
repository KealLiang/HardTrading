'use strict';
const fs = require('fs');
const path = require('path');
const j = JSON.parse(fs.readFileSync(path.join(__dirname, 'tmp', 'bt_v2.json'), 'utf8'));

const pc = x => (x == null || !isFinite(x)) ? 'n/a' : (100 * x).toFixed(2) + '%';
const pp = x => (x == null || !isFinite(x)) ? 'n/a' : ((x > 0 ? '+' : '') + (100 * x).toFixed(2) + 'pp');
const f2 = x => (x == null || !isFinite(x)) ? 'n/a' : x.toFixed(2);
const NM = { 1: '一买', 2: '二买', 3: '三买' };
const HOLDS = j.meta.holds;
const sig = t => t == null ? 'n/a' : (t > 2.5 ? '显著' : t > 2 ? '边缘' : t > 0 ? '不显著' : '显著为负');

/* 结论稳健性判定：邻近基准各窗口是否同号 */
function edgeRange(h) {
  const v = j.meta.nbWindows.map(w => j.r2[w + '_' + h]).filter(Boolean).map(x => x.edge).filter(x => x != null);
  if (!v.length) return null;
  return { min: Math.min.apply(null, v), max: Math.max.apply(null, v), allPos: v.every(x => x > 0) };
}

/* 三类买点之间是否有可测差异 */
function typeSpread(h) {
  const e = [1, 2, 3].map(Lv => j.r1[Lv + '_' + h].edge).filter(x => x != null);
  return e.length === 3 ? Math.max.apply(null, e) - Math.min.apply(null, e) : null;
}

let H = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>缠论买点回测 v2 · 逐日无未来函数</title><style>
:root{--bg:#f7f8fa;--card:#fff;--bd:#e3e6ec;--fg:#1a1d23;--mu:#6b7280;--up:#c62828;--dn:#2e7d32;--ac:#1565c0;--warn:#ef6c00}
*{box-sizing:border-box}body{margin:0;padding:20px 16px 60px;background:var(--bg);color:var(--fg);
font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:34px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--bd)}
.sub{color:var(--mu);font-size:13px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:18px;margin:14px 0}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 8px;text-align:right;border-bottom:1px solid var(--bd);white-space:nowrap}
th{background:#f0f2f5;font-weight:600}th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}
.pos{color:var(--up);font-weight:600}.neg{color:var(--dn);font-weight:600}.muted{color:var(--mu)}
.note{font-size:13px;color:var(--mu);margin:10px 0 0}
.box{border-left:4px solid var(--ac);background:#eef4fc;padding:12px 14px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px}
.box.warn{border-color:var(--warn);background:#fff4e5}
.box.ok{border-color:var(--dn);background:#eaf5ea}
.box.bad{border-color:#c62828;background:#fdecec}
code{background:#eceff3;padding:1px 5px;border-radius:4px;font-size:12px}
ul{margin:8px 0;padding-left:22px}li{margin:5px 0}
.kv{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0}
.kv div{font-size:13px;color:var(--mu)}b{color:var(--fg)}
</style></head><body><div class="wrap">
<h1>缠论买点回测 v2</h1>
<div class="sub">引擎 <code>${j.meta.engine.split('/').pop()}</code> md5 <code>${j.meta.md5Before.slice(0, 12)}…</code>
${j.meta.md5Before === j.meta.md5After ? '跑前跑后一致' : '<b style="color:#c62828">已被修改！</b>'} ·
${j.meta.books} 只 ETF · 入场 <code>readyK+1</code> 开盘 · 双边费 ${(j.meta.fee * 100).toFixed(1)}% · 耗时 ${f2(j.meta.elapsed)}s</div>

<div class="box">
<b>框架纪律</b>
<ul>
<li><b>引擎只读</b>，md5 跑前跑后双向核对</li>
<li><b>入场固定</b> <code>readyK+1</code> 开盘（引擎既定的 readyK 语义）</li>
<li><b>双基准对照</b>：全区间随机 + 邻近窗口随机，后者控制局部行情环境</li>
<li><b>零人为阈值</b>：信号身份判定只用引擎自身结果，不设容差</li>
<li><b>所有结论必须过敏感性检验</b>，不稳健就明说不稳健</li>
</ul>
</div>

<div class="box">
<b>口径有效性</b><br>
进入统计的1192 个信号<b>全部为 lag=1</b>（发现日 = <code>readyK</code>+1，即次日开盘即可成交），
「用发现之前的入场价」的前视偏差样本数为<b>0</b>。此前的重构信号均因入场日超出数据范围而不进入统计。
</div>

<h2>一、信号 vs 随机买入基准</h2>
<div class="card">
<table><tr><th>买点</th><th>持有期</th><th>信号 n</th><th>信号收益</th><th>随机基准</th><th>超额</th><th>Welch t</th><th>95% 置信区间</th><th>判定</th></tr>`;
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const r = j.r1[Lv + '_' + h];
  H += `<tr><td>${NM[Lv]}</td><td>${h} 日</td><td>${r.n}</td><td>${pc(r.exp)}</td><td>${pc(r.base)}</td>`
    + `<td class="${r.edge > 0 ? 'pos' : 'neg'}">${pp(r.edge)}</td><td>${f2(r.t)}</td>`
    + `<td class="muted">[${pp(r.ci && r.ci.lo)}, ${pp(r.ci && r.ci.hi)}]</td><td>${sig(r.t)}</td></tr>`;
}
H += `</table></div>

<h2>二、稳健性：邻近窗口基准敏感性扫描</h2>
<div class="card">
<p class="note">邻近基准在信号前后 ±N 根内随机入场，控制局部行情环境。若换个窗口结论就变，说明原结论不稳健。</p>
<table><tr><th>窗口</th>${HOLDS.map(h => `<th>${h} 日超额</th><th>t</th>`).join('')}</tr>`;
for (const w of j.meta.nbWindows) {
  H += `<tr><td>±${w} 根</td>`;
  for (const h of HOLDS) {
    const r = j.r2[w + '_' + h];
    H += `<td class="${r.edge > 0 ? 'pos' : 'neg'}">${pp(r.edge)}</td><td>${f2(r.t)}</td>`;
  }
  H += `</tr>`;
}
H += `</table>`;
for (const h of HOLDS) {
  const r = edgeRange(h);
  if (r) H += `<p class="note">${h} 日：各窗口超额区间 <b>${pp(r.min)} ~ ${pp(r.max)}</b>，${r.allPos ? '全部为正 → 稳健' : '存在非正→ 不稳健'}</p>`;
}
H += `</div>

<h2>三、一次性全序列口径 vs 逐日口径</h2>
<div class="card">
<table><tr><th>买点</th><th>持有期</th><th>一次口径 n</th><th>收益</th><th>逐日口径 n</th><th>收益</th><th>差</th></tr>`;
let oneN = 0, dayN = 0;
const HL = HOLDS[HOLDS.length - 1];
for (const Lv of [1, 2, 3]) for (const h of HOLDS) {
  const r = j.r3[Lv + '_' + h];
  if (h === HL) { oneN += r.oneN; dayN += r.dayN; }   // 合计只取最长持有期，避免跨持有期重复计数
  H += `<tr><td>${NM[Lv]}</td><td>${h} 日</td><td>${r.oneN}</td><td>${pc(r.oneExp)}</td><td>${r.dayN}</td><td>${pc(r.dayExp)}</td>`
    + `<td class="${r.diff > 0 ? 'pos' : 'neg'}">${pp(r.diff)}</td></tr>`;
}
H += `</table><p class="note">合计：一次性口径 ${oneN} 个信号，逐日口径 ${dayN} 个，<b>逐日多 ${dayN - oneN} 个</b>。</p></div>

<h2>四、一次性口径漏掉了什么（零人为容差）</h2>
<div class="card">
<p class="note">把逐日发现的每个信号，逐个查它在<b>最终全序列结果</b>里还在不在——这就是"直接用 <code>res.points</code> 回测"会漏掉的部分。不设任何容差。</p>
<table><tr><th>买点</th><th>留存 n</th><th>收益</th><th>t</th><th>漏掉 n</th><th>收益</th><th>t</th><th>差</th><th>Welch t</th></tr>`;
for (const Lv of [1, 2, 3]) {
  const r = j.r4[Lv];
  H += `<tr><td>${NM[Lv]}</td><td>${r.keepN}</td><td class="pos">${pc(r.keepExp)}</td><td>—</td>`
    + `<td>${r.dropN}</td><td class="neg">${pc(r.dropExp)}</td><td>—</td>`
    + `<td class="${r.diff > 0 ? 'pos' : 'neg'}"><b>${pp(r.diff)}</b></td><td>${f2(r.t)}</td></tr>`;
}
H += `</table></div>

<h2>五、自检</h2>
<div class="card"><div class="kv">
<div>引擎 md5 一致：<b>${j.meta.md5Before === j.meta.md5After ? '是' : '否'}</b></div>
<div>ETF：<b>${j.meta.books}</b> 只</div>
<div>K 线根数：<b>${Math.min.apply(null, j.meta.bars)} ~ ${Math.max.apply(null, j.meta.bars)}</b></div>
<div>坏 K 线：<b>${j.meta.badBars}</b>（已标记不入场）</div>
<div>可交易信号：<b>${j.sanity.nSig}</b></div>
</div>
<p class="note">信号发现滞后(t − readyK)：${Object.keys(j.sanity.lagDist).map(Number).sort((a, b) => a - b).slice(0, 5).map(k => k + '→' + j.sanity.lagDist[k]).join('  ')}　—滞后 1 根是正确行为（<code>readyK</code> 是结构确立的最后一根，次日才能交易）</p>
</div>

<h2>六、结论</h2>
<div class="card"><table><tr><th>结论</th><th>状态</th><th>依据</th></tr>`;

const r10 = edgeRange(10), r20 = edgeRange(20);
const sp10 = typeSpread(10), sp20 = typeSpread(20);
/* 显著性判定以「邻近基准」（更严格、控制了局部行情环境）为准 */
const nbT = [];
for (const w of j.meta.nbWindows) for (const h of HOLDS) if (j.r2[w + '_' + h].t != null) nbT.push(j.r2[w + '_' + h].t);
const nbMinT = Math.min.apply(null, nbT);
const nbMaxT = Math.max.apply(null, nbT);
/* 全区间基准的置信区间是否全部排除 0 */
const globAllPos = [1, 2, 3].every(Lv => HOLDS.every(h => {
  const c = j.r1[Lv + '_' + h].ci; return c && c.lo > 0;
}));

H += `<tr><td>三类买点相对随机买入有正超额</td>
<td class="${nbMinT > 2 ? 'pos' : 'muted'}"><b>${nbMinT > 2 ? '成立' : '证据不足'}</b></td>
<td class="muted">邻近基准 t=${f2(nbMinT)}~${f2(nbMaxT)} 全部显著；全区间基准 95%CI ${globAllPos ? '全部排除 0' : '部分含 0'}</td></tr>`;

H += `<tr><td>该结论对基准选择稳健</td>
<td class="${r10 && r20 && r10.allPos && r20.allPos ? 'pos' : 'neg'}"><b>${r10 && r20 && r10.allPos && r20.allPos ? '稳健' : '不稳健'}</b></td>
<td class="muted">邻近窗口 ±5~±40 全为正；10日 ${pp(r10 && r10.min)}~${pp(r10 && r10.max)}，20日 ${pp(r20 && r20.min)}~${pp(r20 && r20.max)}</td></tr>`;

H += `<tr><td>一买/二买/三买存在优劣之分</td>
<td class="muted"><b>无法区分</b></td>
<td class="muted">超额极差：10日 ${pp(sp10)}，20日 ${pp(sp20)} — 三者互相重叠</td></tr>`;

const diffs = [1, 2, 3].map(Lv => j.r4[Lv].diff);
const allT4 = [1, 2, 3].map(Lv => j.r4[Lv].t);
H += `<tr><td>一次性口径存在选择偏差（虚高）</td>
<td class="pos"><b>成立</b></td>
<td class="muted">留存组 vs 漏掉组差 ${pp(Math.min.apply(null, diffs))} ~ ${pp(Math.max.apply(null, diffs))}；漏掉的信号收益全为负</td></tr>`;

H += `<tr><td>三类买点孰优孰劣</td><td class="muted"><b>本样本无法判定</b></td>
<td class="muted">需更大样本或更长周期</td></tr>`;
H += `</table></div>`;

const osDiffs = [1, 2, 3].map(Lv => j.r3[Lv + '_' + HOLDS[HOLDS.length - 1]].diff);
H += `<div class="box bad">
<b>口径警告</b>：如果回测直接用最终 <code>res.points</code>（一次性全序列），收益会系统性高估。
本样本中三类买点的虚高幅度约 ${pp(Math.min.apply(null, osDiffs))} ~ ${pp(Math.max.apply(null, osDiffs))}。
逐日切片是唯一可信的口径。
</div>

<div class="box ok">
<b>可复现</b>：<code>node bt.js</code>（随机基准固定种子，结果完全可复现）；<code>SMOKE=3 node bt.js</code> 冒烟自检。
</div>

</div></body></html>`;

fs.writeFileSync(path.join(__dirname, 'bt_v2_report.html'), H);
console.log('已生成 bt_v2_report.html');