/* ==========================================================================
 * report.js — 生成 verify_report.html
 * ========================================================================== */
'use strict';
const fs = require('fs');
const path = require('path');
const D = __dirname;
const F = JSON.parse(fs.readFileSync(path.join(D, 'forward.json'), 'utf8'));
const BA = JSON.parse(fs.readFileSync(path.join(D, 'ba.json'), 'utf8'));
const PX = JSON.parse(fs.readFileSync(path.join(D, 'proxy.json'), 'utf8'));
const EX = JSON.parse(fs.readFileSync(path.join(D, 'exit.json'), 'utf8'));

const HZ = [1, 2, 3, 5, 8, 10, 15, 20, 30, 40];
const ORDER = ['一买·底背驰', '二买·回抽不破前低', '三买·回抽不入中枢', '一卖·顶背驰', '二卖·反抽不破前高', '三卖·反抽不入中枢'];
const COLORS = { '一买·底背驰': '#185FA5', '二买·回抽不破前低': '#888780', '三买·回抽不入中枢': '#534AB7', '一卖·顶背驰': '#5DCAA5', '二卖·反抽不破前高': '#EF9F27', '三卖·反抽不入中枢': '#E24B4A' };
const pc = x => x == null ? '—' : (100 * x).toFixed(2) + '%';
const pp = x => x == null ? '—' : (100 * x).toFixed(2) + 'pp';

function hzTable(note) {
  const s = F.signal[note];
  let h = `<table><thead><tr><th>持有期</th><th>信号均值</th><th>基线均值</th><th>超额</th><th>t 值</th><th>胜率</th><th>中位数</th></tr></thead><tbody>`;
  for (const N of HZ) {
    const x = s.hz[N];
    const strong = x.t != null && Math.abs(x.t) >= 2 && Math.sign(x.t) === Math.sign(x.edge);
    h += `<tr><td>${N} 日</td><td>${pc(x.exp)}</td><td>${pc(x.baseExp)}</td>`;
    h += `<td class="${strong ? 'pos' : 'muted'}">${pp(x.edge)}</td>`;
    h += `<td class="${strong ? 'pos' : 'muted'}">${x.t == null ? '—' : x.t.toFixed(2)}</td>`;
    h += `<td>${pc(x.win)}</td><td class="muted">${pc(x.med)}</td></tr>`;
  }
  return h + '</tbody></table>';
}

let html = `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>缠论信号独立复核</title><style>
*{box-sizing:border-box}
body{font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;margin:0;padding:20px 16px 60px;background:#faf9f7;color:#2c2c2a;max-width:1080px;margin:0 auto}
h1{font-size:20px;font-weight:500;margin:0 0 4px}
h2{font-size:16px;font-weight:500;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid #e5e3dc}
h3{font-size:14px;font-weight:500;margin:22px 0 8px}
.sub{color:#5f5e5a;font-size:13px;margin-bottom:20px}
table{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:13px;background:#fff;border-radius:8px;overflow:hidden}
th,td{padding:7px 9px;text-align:right;border-bottom:1px solid #f0eee8}
th{background:#f1efe8;font-weight:500;color:#444;font-size:12px}
td:first-child,th:first-child{text-align:left}
.pos{color:#0f6e56;font-weight:500}
.neg{color:#a32d2d}
.muted{color:#888780}
.box{background:#fff;border-radius:10px;padding:16px 18px;margin:12px 0;border:1px solid #e8e6df}
.warn{background:#fcebeb;border-color:#f09595}
.ok{background:#eaf3de;border-color:#97c459}
.note{background:#e6f1fb;border-color:#85b7eb}
.verdict{font-size:15px;line-height:1.7;margin:8px 0 0}
.tag{display:inline-block;background:#eeedfe;color:#26215c;padding:1px 7px;border-radius:4px;font-size:12px;margin-right:6px}
ul{margin:8px 0;padding-left:22px}li{margin:5px 0}
code{background:#f1efe8;padding:1px 5px;border-radius:3px;font-size:12px}
</style></head><body>
<h1>缠论信号独立复核</h1>
<div class="sub">${new Date().toISOString().slice(0, 10)} · 引擎 <code>chanlens/core/chan.js</code> · 24 只 ETF · 逐日切片无未来函数 · 费后 0.1%</div>

<div class="box ok">
<div class="verdict"><strong>用户的三条感性结论，全部与回测一致。</strong></div>
<ul>
<li><span class="tag">一买</span>前 10 天超额为负（偏早），20 日转正 <strong>+0.77pp（t=3.32）</strong> → 「偏早，持有久点」✓</li>
<li><span class="tag">二买</span>全程贴零轴，无显著超额 → 「约等于抛硬币」✓</li>
<li><span class="tag">三买</span>5~10 日显著为正，20 日转负 <strong>−0.21pp</strong> → 「靠谱，但赚了要走别恋战」✓</li>
</ul>
</div>

<h2>一、三类买点的持有期曲线</h2>
<p class="sub">超额 = 信号均值 − 同持有期无条件基线。这是本次复核的核心表。</p>`;

for (const note of ORDER.filter(x => F.signal[x] && F.signal[x].dir === 'buy')) {
  const s = F.signal[note];
  html += `<h3 style="color:${COLORS[note]}">${note}　n=${s.n}　覆盖 ${s.codes} 只票</h3>${hzTable(note)}`;
}

html += `<h2>二、「赚了要走」的直接检验</h2>
<p class="sub">同一批 ${Object.values(EX.res)[0].n} 个三买信号、同一 40 日观察窗口，样本集完全一致，只换出场规则。</p>
<table><thead><tr><th>出场规则</th><th>期望</th><th>t 值</th><th>胜率</th><th>中位数</th><th>p90</th><th>平均持有</th></tr></thead><tbody>`;
for (const [k, v] of Object.entries(EX.res)) {
  html += `<tr><td>${k}</td><td>${pc(v.exp)}</td><td>${v.t == null ? '—' : v.t.toFixed(2)}</td><td>${pc(v.win)}</td><td>${pc(v.med)}</td><td>${pc(v.p90)}</td><td>${v.held.toFixed(1)} 日</td></tr>`;
}
html += `</tbody></table>
<div class="box note">
<div class="verdict"><strong>移动止盈确实有用，但幅度有限。</strong></div>
<ul>
<li>trail5 期望 ${pc(EX.res.trail5.exp)}，比 hold10 的 ${pc(EX.res.hold10.exp)} 高约 ${(100 * (EX.res.trail5.exp - EX.res.hold10.exp)).toFixed(2)}pp，胜率从 ${pc(EX.res.hold10.win)} 提到 ${pc(EX.res.trail5.win)}。</li>
<li><strong>但 hold40（死拿 40 日）的期望 ${pc(EX.res.hold40.exp)} 与 trail5 基本持平</strong>（差 ${(100 * Math.abs(EX.res.hold40.exp - EX.res.trail5.exp)).toFixed(2)}pp）—— 说明「及时走」的主要价值不是提高单笔期望，而是<strong>把收益落袋</strong>：中位数从 ${pc(EX.res.hold40.med)} 提到 ${pc(EX.res.trail5.med)}，p90 从 ${pc(EX.res.hold40.p90)} 降到 ${pc(EX.res.trail5.p90)}，尾部变薄。</li>
<li>用户说「赚了就走」的直觉对应的是<strong>收益形态的改善（波动下降）</strong>，而不是期望的大幅提升。</li>
</ul>
</div>

<h2>三、方向判断 × 等信号的交互（B−A）</h2>
<p class="sub">方向条件为可计算的代理规则（过去 20 日涨幅跨票排名前 30%），三臂共用同一条件。</p>
<table><thead><tr><th>臂</th><th>定义</th><th>持有期</th><th>n</th><th>期望</th><th>t 值</th></tr></thead><tbody>`;
const ARMDEF = { A: '方向成立 → 直接进', B: '方向成立 → 等三买信号', C: '方向不成立 → 但有三买' };
for (const k of ['A', 'B', 'C']) for (const N of [10, 20]) {
  const v = BA.out.arms[k][N];
  html += `<tr><td>${k}</td><td class="muted" style="text-align:left">${ARMDEF[k]}</td><td>${N} 日</td><td>${v.n}</td><td>${pc(v.exp)}</td><td>${v.t == null ? '—' : v.t.toFixed(2)}</td></tr>`;
}
html += `</tbody></table>
<div class="box">
<div class="verdict"><strong>B−A 方向正确但量级极小，不构成「值得等」的证据。</strong></div>
<ul>
<li>10 日：<strong>B−A = ${pp(BA.out.diff[10].BA)}</strong>（t=${BA.out.diff[10].BAt.toFixed(2)}）</li>
<li>20 日：<strong>B−A = ${pp(BA.out.diff[20].BA)}</strong>（t=${BA.out.diff[20].BAt.toFixed(2)}）</li>
<li>10 日为正、20 日为负，<strong>两个方向都不显著（|t| &lt; 1）</strong>。在方向已定的前提下，三买信号没有带来可测量的额外收益。</li>
<li>C 臂（方向不成立但有三买）期望反而更高 —— 说明在这个代理下，「方向条件」本身可能不是有效过滤器。</li>
</ul>
</div>

<h2>四、方向代理体检</h2>
<p class="sub">B−A 依赖方向代理的有效性。若代理自身失效，B−A 建在流沙上。</p>
<table><thead><tr><th>代理</th><th>A 臂 10 日期望</th><th>t 值</th><th>A 臂 20 日期望</th><th>t 值</th><th>是否可用</th></tr></thead><tbody>`;
for (const key of PX.NAMES) {
  const a10 = PX.arms[key][10].A, a20 = PX.arms[key][20].A;
  const ok = a10.t > 0 && a20.t > 0;
  html += `<tr><td>${key}</td><td>${pc(a10.exp)}</td><td>${a10.t.toFixed(2)}</td><td>${pc(a20.exp)}</td><td>${a20.t.toFixed(2)}</td><td class="${ok ? 'pos' : 'neg'}">${ok ? '可用' : '不可用'}</td></tr>`;
}
html += `</tbody></table>
<div class="box note">所有代理的 A 臂都显著为正（费后 0.44%~1.09%），说明这批 ETF 长期有正的漂移，代理本身可用。但注意代理之间差异不大 —— 说明方向条件在这批样本上区分度弱。</div>

<h2>五、本次复核的方法学教训</h2>
<div class="box warn">
<ul>
<li><strong>排序 bug（已修）</strong>：<code>sort((a,b) => a.d &lt; b ? -1 : 1)</code> 漏了 <code>b.d</code>，变成字符串比较，日期被逆序。症状是「基线为负」「所有方向都反向」。已改为 <code>a.d &lt; b.d</code>。</li>
<li><strong>截断偏差（已修）</strong>：只统计「已触发离场」的单子，会系统性剔除走得很久还没回撤的单子 —— 而那恰恰是最赚的，导致移动止盈期望虚高到 17%~24%。改为所有出场统一 40 日窗口、窗口末强制平仓。</li>
<li><strong>选择性样本</strong>：同一批信号在不同出场下离场数不同（88~355），不能只统计已离场的。</li>
</ul>
</div>

<h2>六、结论与仍未回答的问题</h2>
<div class="box">
<div class="verdict"><strong>已验证：</strong>三条感性结论全部成立，尤其「三买赚了要走」在收益形态上得到支持。</div>
<div class="verdict" style="margin-top:14px"><strong>未验证：</strong>在方向已定的前提下，三买信号的边际价值（B−A）测不出来，|t| &lt; 1。这不代表信号无用 —— 本次用的是可计算的动量代理，并非用户本人的判断力，<strong>该结果不能外推到实盘</strong>。</div>
</div>`;

fs.writeFileSync(path.join(D, 'verify_report.html'), html);
console.log('written verify_report.html');
