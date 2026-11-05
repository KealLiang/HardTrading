"""把多份同模板的个股走势 HTML 合并成一份带 tab 切换的单文件页面。

思路：
- 每个子页面本身就是完整自包含的文档（图表 JSON 全在里面），直接读原文、
  转义后塞进 <iframe srcdoc>，浏览器当独立文档渲染，plotly / 收藏 / 复制按钮 /
  竖线游标全部原样可用，不需要改任何子页面逻辑；
- 子页面里追加一小段脚本上报自身内容高度，父页面收到后把 iframe 撑到对应高度，
  因此外层滚动条只有一条，不出现嵌套滚动；
- tab 状态记在 location.hash，刷新或收藏 #momo 这类链接能直达对应页。

新增页面：往 CHART_PAGES 里加一条即可，其它不用动。
"""

import html
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence

# 合并哪些页面（顺序即 tab 顺序）——以后新增的图页往这里加就行
CHART_PAGES: List[Dict[str, str]] = [
    {"key": "leader", "label": "龙头入选", "path": "./excel/html_charts/leader_sheet_all_2cols.html"},
    {"key": "momo", "label": "默默上涨", "path": "./excel/html_charts/momo_concept_group_all_2cols.html"},
]

DEFAULT_OUTPUT = "./excel/html_charts/all_charts.html"
DEFAULT_TITLE = "个股走势图"

# 子页面里注入的高度上报脚本（保留标记便于幂等）
_HEIGHT_SCRIPT_START = "<!--CHART_PAGE_HEIGHT_START-->"
_HEIGHT_SCRIPT_END = "<!--CHART_PAGE_HEIGHT_END-->"
_HEIGHT_SCRIPT = _HEIGHT_SCRIPT_START + """
<script>
(function () {
    var PAGE_KEY = '__PAGE_KEY__';
    // 只取 body 自身的内容高度（不能用 documentElement.scrollHeight，
    // 那是 max(视口, 内容)，父页面改 iframe 高度会反过来把它顶大 → 无限长高）
    function docHeight() {
        var b = document.body;
        if (!b) return 0;
        return Math.max(b.scrollHeight, b.offsetHeight);
    }
    function send() {
        try {
            parent.postMessage({ __chartPageHeight: docHeight(), __chartPageKey: PAGE_KEY }, '*');
        } catch (e) {}
    }
    window.addEventListener('load', send);
    window.addEventListener('resize', send);
    window.addEventListener('message', function (e) {
        if (e.data === '__chartPageMeasure') send();
    });
    // plotly 首屏渲染比 load 晚，多打几次
    [200, 600, 1500, 3000, 6000].forEach(function (t) { setTimeout(send, t); });
})();
</script>
""" + _HEIGHT_SCRIPT_END


def _read_page_html(path: str, page_key: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # 去掉上一次注入的高度脚本，避免重复叠加
    content = re.sub(
        re.escape(_HEIGHT_SCRIPT_START) + r".*?" + re.escape(_HEIGHT_SCRIPT_END),
        "",
        content,
        flags=re.S,
    )
    script = _HEIGHT_SCRIPT.replace("__PAGE_KEY__", page_key)
    if "</body>" in content:
        content = content.replace("</body>", script + "\n</body>", 1)
    else:
        content += script
    return content


def _extract_stock_count(page_html: str) -> str:
    """从子页面抓「共 N 只股票」，用作 tab 上的数量角标（抓不到就留空）。"""
    m = re.search(r"共\s*(\d+)\s*只股票", page_html)
    return m.group(1) if m else ""


def build_multi_page_html(
        pages: Optional[Sequence[Dict[str, str]]] = None,
        output_path: str = DEFAULT_OUTPUT,
        page_title: str = DEFAULT_TITLE,
) -> str:
    """生成合并页并返回输出路径。

    Args:
        pages: [{key, label, path}, ...]，默认 CHART_PAGES
        output_path: 输出 html 路径（每日覆盖同一份）
        page_title: 页面标题
    """
    pages = list(pages if pages is not None else CHART_PAGES)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    tabs_html: List[str] = []
    panes_html: List[str] = []
    missing: List[str] = []

    for idx, page in enumerate(pages):
        key = str(page.get("key") or f"page{idx}")
        label = str(page.get("label") or key)
        path = str(page.get("path") or "")
        content = _read_page_html(path, key)

        active = " active" if idx == 0 else ""
        count = _extract_stock_count(content) if content else ""
        count_html = f'<span class="count">{count}只</span>' if count else ""
        tabs_html.append(
            f'<button type="button" class="tab{active}" data-tab="{html.escape(key)}" '
            f'data-label="{html.escape(label)}">{html.escape(label)}{count_html}</button>'
        )

        if content:
            body = (
                '<iframe class="page-frame" data-page="{}" title="{}" '
                'srcdoc="{}"></iframe>'.format(
                    html.escape(key), html.escape(label), html.escape(content, quote=True)
                )
            )
        else:
            missing.append(os.path.basename(path) or label)
            body = (
                '<div class="missing">未找到图表文件：<code>{}</code><br>'
                '先跑一次对应的生成步骤，再重新生成本页。</div>'.format(html.escape(path))
            )
        panes_html.append(
            f'<section class="pane{active}" data-tab="{html.escape(key)}">{body}</section>'
        )

    missing_html = ""
    if missing:
        missing_html = (
            '<div class="warn">以下页面缺失，已生成的页面可正常查看：{}</div>'.format(
                html.escape("、".join(missing))
            )
        )

    doc = _TEMPLATE.format(
        page_title=html.escape(page_title),
        now=now,
        tabs="\n        ".join(tabs_html),
        panes="\n".join(panes_html),
        missing=missing_html,
    )

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return output_path


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
  :root {{
    --bg:#f5f5f5; --card:#fff; --line:#ddd;
    --text:#333; --sub:#666; --accent:#1a73e8; --warn:#e8a33d;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    font-family: Arial, "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--text);
  }}
  .topbar {{
    position: sticky; top:0; z-index:50;
    background: var(--card); border-bottom:1px solid var(--line);
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }}
  .bar-row {{
    display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:7px 14px;
  }}
  h1 {{ margin:0; font-size:15px; font-weight:600; }}
  .stamp {{ font-size:12px; color:var(--sub); }}
  .warn {{
    margin:0 14px 8px; padding:6px 10px; font-size:12px;
    color:#8a5b00; background:#fff6e0; border-left:3px solid var(--warn);
    border-radius:4px;
  }}
  /* tab 贴右边，与标题同一行，省一行高度 */
  .tabs {{ display:flex; gap:6px; flex-wrap:wrap; margin-left:auto; }}
  .tab {{
    border:1px solid var(--line); background:#fff; color:#444;
    border-radius:13px; padding:4px 12px; font-size:12.5px;
    cursor:pointer; line-height:1.4; transition: all .12s;
  }}
  .tab:hover {{ border-color:#bbb; }}
  .tab.active {{
    background: var(--accent); border-color: var(--accent); color:#fff;
  }}
  .tab .count {{ margin-left:5px; font-size:11px; opacity:.7; }}
  .pane {{ display:none; }}
  .pane.active {{ display:block; }}
  .page-frame {{ width:100%; border:0; display:block; background:transparent; min-height:420px; }}
  .missing {{
    margin:16px; padding:14px 16px; font-size:13px; color:#8a5b00;
    background:#fff6e0; border-left:3px solid var(--warn); border-radius:4px;
  }}
  .missing code {{ background:rgba(0,0,0,.05); padding:1px 4px; border-radius:3px; }}
</style>
</head>
<body>
<div class="topbar">
  <div class="bar-row">
    <h1>{page_title}</h1>
    <span class="stamp">生成于 {now}</span>
    <div class="tabs">
        {tabs}
    </div>
  </div>
  {missing}
</div>
{panes}
<script>
(function () {{
  var STORAGE_KEY = 'trading.charts.activeTab.v1';
  var panes = Array.prototype.slice.call(document.querySelectorAll('.pane'));
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));

  function measure(target) {{
    panes.forEach(function (pane) {{
      if (target && pane.dataset.tab !== target) return;
      var frame = pane.querySelector('iframe');
      if (frame && frame.contentWindow) {{
        try {{ frame.contentWindow.postMessage('__chartPageMeasure', '*'); }} catch (e) {{}}
      }}
    }});
  }}

  function activate(name, remember) {{
    var hit = false;
    panes.forEach(function (pane) {{
      var on = pane.dataset.tab === name;
      pane.classList.toggle('active', on);
      if (on) hit = true;
    }});
    if (!hit) return false;
    tabs.forEach(function (tab) {{
      tab.classList.toggle('active', tab.dataset.tab === name);
    }});
    if (remember) {{
      try {{ history.replaceState(null, '', '#' + name); }} catch (e) {{ location.hash = name; }}
      try {{ localStorage.setItem(STORAGE_KEY, name); }} catch (e) {{}}
    }}
    measure(name);
    // 隐藏时测量不准，显示后再补一次
    setTimeout(function () {{ measure(name); }}, 400);
    return true;
  }}

  tabs.forEach(function (tab) {{
    tab.addEventListener('click', function () {{ activate(tab.dataset.tab, true); }});
  }});

  window.addEventListener('message', function (e) {{
    var data = e.data || {{}};
    if (!data.__chartPageHeight) return;
    var raw = parseInt(data.__chartPageHeight, 10);
    if (!raw || raw < 200) return;  // 隐藏标签页测不出高度，忽略
    var key = data.__chartPageKey;
    var h = raw + 44;               // 子页面 body 的上下 margin
    panes.forEach(function (pane) {{
      if (key && pane.dataset.tab !== key) return;
      var frame = pane.querySelector('iframe');
      if (!frame) return;
      var cur = parseInt(frame.style.height, 10) || 0;
      if (Math.abs(cur - h) <= 2) return;   // 抖动保护，避免互相顶高
      frame.style.height = h + 'px';
    }});
  }});

  window.addEventListener('resize', function () {{ measure(); }});

  var initial = (location.hash || '').replace('#', '');
  if (!initial) {{
    try {{ initial = localStorage.getItem(STORAGE_KEY) || ''; }} catch (e) {{ initial = ''; }}
  }}
  var first = panes.length ? panes[0].dataset.tab : '';
  if (!initial || !activate(initial, false)) {{
    activate(first, false);
  }}
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print(build_multi_page_html())
