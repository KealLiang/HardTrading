"""日常复盘图片汇总页

把 images/ 下固定的几张复盘图汇总成**一个** HTML（固定路径，每日覆盖更新），
浏览器里收藏该页面，跑完 daily_routine 刷新即可。

用法：
    from analysis.html_gen.daily_review_html import generate_daily_review_html
    generate_daily_review_html()
"""

import os
from datetime import datetime
from typing import List, Optional, Sequence, Tuple
from urllib.parse import quote

# 需要展示的图（顺序即页面顺序）；不想看某张就注释/删除对应行
DAILY_REVIEW_IMAGES: List[Tuple[str, str]] = [
    ("hot_concept.png", "热门概念词云"),
    ("hot_concept_rotation.png", "热门概念轮动"),
    ("market_analysis_overview.png", "市场全景总览"),
    ("market_analysis_strength.png", "市场强度"),
    ("market_analysis_limit_up.png", "涨停梯队分析"),
    ("market_analysis_next_day_zt.png", "次日涨停预期"),
    ("market_analysis_open_break_returns.png", "开盘 / 炸板收益"),
]

DEFAULT_IMAGE_DIR = "./images"
DEFAULT_OUTPUT = "./images/daily_review.html"

# 顶部快捷按钮：点击用本机 Excel 打开文件（Office URI Scheme: ms-excel:）
# 加更多就往下加一行 (绝对路径, 按钮文字)；不想要就置空 []
DAILY_REVIEW_OPEN_FILES: List[Tuple[str, str]] = [
    (r"D:\Trading\excel\ladder_analysis.xlsx", "打开天梯 Excel"),
]


def _office_href(path: str) -> str:
    """本机文件 → ms-excel 打开链接；文件不存在返回空串"""
    if not os.path.isfile(path):
        return ""
    url = "file:///" + os.path.abspath(path).replace("\\", "/").lstrip("/")
    return "ms-excel:ofe|u|" + quote(url, safe="/:")


def _fmt_mtime(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M")
    except OSError:
        return "-"


def _file_version(path: str) -> str:
    """用 mtime 做缓存击穿，避免浏览器刷新后仍显示旧图"""
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


def generate_daily_review_html(
        images: Optional[Sequence[Tuple[str, str]]] = None,
        image_dir: str = DEFAULT_IMAGE_DIR,
        output_path: str = DEFAULT_OUTPUT,
        open_files: Optional[Sequence[Tuple[str, str]]] = None,
) -> str:
    """生成复盘图汇总 HTML，返回输出文件路径

    Args:
        images: [(文件名, 标题), ...]，默认用 DAILY_REVIEW_IMAGES
        image_dir: 图片目录（相对 HTML 所在目录或绝对路径）
        output_path: HTML 输出路径（固定覆盖）
        open_files: [(绝对路径, 按钮文字), ...]，默认用 DAILY_REVIEW_OPEN_FILES；
            用 ms-excel 协议调本机 Excel 打开，文件不存在则按钮置灰
    """
    images = images if images is not None else DAILY_REVIEW_IMAGES
    image_dir = image_dir or DEFAULT_IMAGE_DIR
    open_files = open_files if open_files is not None else DAILY_REVIEW_OPEN_FILES

    # HTML 与图片目录的相对关系（output 与 images 同级时为 "."）
    out_dir = os.path.dirname(os.path.abspath(output_path))
    rel_dir = os.path.relpath(os.path.abspath(image_dir), out_dir).replace("\\", "/")

    buttons = []
    for path, label in open_files:
        href = _office_href(path)
        if href:
            buttons.append(f'<a class="btn-open" href="{href}" title="{path}">📊 {label}</a>')
        else:
            buttons.append(
                f'<span class="btn-open disabled" title="文件不存在：{path}">📊 {label}</span>'
            )
    buttons_html = f'<div class="btn-group">{"".join(buttons)}</div>' if buttons else ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nav_items, sections, missing = [], [], []

    for idx, (filename, title) in enumerate(images, 1):
        abs_file = os.path.join(os.path.abspath(image_dir), filename)
        exists = os.path.isfile(abs_file)
        anchor = f"sec{idx}"

        nav_items.append(
            f'<a class="chip{" missing" if not exists else ""}" href="#{anchor}">{title}</a>'
        )

        if exists:
            src = f"{rel_dir}/{filename}?v={_file_version(abs_file)}"
            body = (f'<a class="shot" href="{src}" target="_blank" rel="noopener">'
                    f'<img src="{src}" alt="{title}" loading="lazy"></a>')
            meta = f"更新于 {_fmt_mtime(abs_file)}"
        else:
            missing.append(filename)
            body = f'<div class="warn">未找到 <code>{filename}</code>，请先跑 daily_routine 生成该图。</div>'
            meta = "缺失"

        sections.append(f"""  <section id="{anchor}" class="card">
    <div class="card-head"><h2>{idx}. {title}</h2><span class="meta">{meta}</span></div>
    {body}
  </section>""")

    missing_note = (f'<div class="banner">⚠️ 有 {len(missing)} 项缺失：{", ".join(missing)}</div>'
                    if missing else "")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股复盘 · 每日图表</title>
<style>
  :root {{
    --bg:#f6f7f9; --card:#fff; --line:#e5e7eb; --text:#1f2328; --sub:#6b7280; --accent:#c0392b;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
    font-size:14px; line-height:1.5;
  }}
  header {{
    position:sticky; top:0; z-index:10; background:rgba(255,255,255,.94);
    backdrop-filter:blur(8px); border-bottom:1px solid var(--line); padding:10px 16px 8px;
  }}
  .title-row {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  h1 {{ margin:0; font-size:17px; font-weight:600; }}
  .stamp {{ color:var(--sub); font-size:12px; }}
  .btn-group {{ margin-left:auto; display:flex; gap:8px; }}
  .btn-open {{
    display:inline-flex; align-items:center; gap:6px; padding:5px 12px; border-radius:8px;
    background:var(--accent); border:1px solid #a93226; color:#fff; text-decoration:none;
    font-size:12.5px; font-weight:500; white-space:nowrap;
  }}
  .btn-open:hover {{ background:#a93226; }}
  .btn-open.disabled {{ background:#eef0f3; border-color:#e2e5ea; color:#9aa1ab; cursor:not-allowed; }}
  nav {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:9px; }}
  .chip {{
    display:inline-block; padding:3px 10px; border:1px solid var(--line); border-radius:99px;
    background:#fff; color:#374151; text-decoration:none; font-size:12px;
  }}
  .chip:hover {{ border-color:var(--accent); color:var(--accent); }}
  .chip.missing {{ color:#9ca3af; border-style:dashed; }}
  main {{ max-width:1400px; margin:0 auto; padding:14px 16px 40px; display:flex; flex-direction:column; gap:14px; }}
  .banner {{
    background:#fff7ed; border:1px solid #fed7aa; color:#9a3412;
    border-radius:10px; padding:10px 12px; font-size:13px;
  }}
  .card {{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:12px 14px 14px; box-shadow:0 1px 2px rgba(16,24,40,.04);
  }}
  .card-head {{ display:flex; align-items:baseline; justify-content:space-between; gap:10px; margin-bottom:10px; }}
  h2 {{ margin:0; font-size:15px; font-weight:600; }}
  .meta {{ color:var(--sub); font-size:12px; white-space:nowrap; }}
  .shot {{ display:block; }}
  .shot img {{ display:block; width:100%; height:auto; border:1px solid #f0f1f3; border-radius:8px; background:#fff; }}
  .warn {{
    background:#fef2f2; border:1px dashed #fecaca; color:#b91c1c;
    border-radius:8px; padding:22px 14px; text-align:center; font-size:13px;
  }}
  .warn code {{ background:#fff; padding:1px 5px; border-radius:4px; }}
</style>
</head>
<body>
<header>
  <div class="title-row">
    <h1>A股复盘 · 每日图表</h1>
    <span class="stamp">生成于 {now}</span>
    {buttons_html}
  </div>
  <nav>{''.join(nav_items)}</nav>
</header>
<main>
  {missing_note}
{chr(10).join(sections)}
</main>
</body>
</html>
"""

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.abspath(output_path), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"📄 复盘汇总页已生成: {os.path.abspath(output_path)}"
          f"（{len(images) - len(missing)}/{len(images)} 张图）")
    return os.path.abspath(output_path)


if __name__ == "__main__":
    generate_daily_review_html()
