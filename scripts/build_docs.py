"""把 docs/src 下的 PRD、Spec 转成 docs/ 下的单文件 HTML（左侧目录、浅色 / 深色自适应）。
改文档：改 docs/src/*.md，再运行 python scripts/build_docs.py；不要直接改 HTML。
需要：pip install markdown-it-py
"""
import html, re, sys, pathlib
from markdown_it import MarkdownIt

CSS = r"""
:root{--bg:#ffffff;--fg:#1f2328;--muted:#656d76;--line:#d8dee4;--soft:#f6f8fa;--accent:#0b5cad;--code:#eff1f3;--mark:#fff8c5}
@media (prefers-color-scheme: dark){:root{--bg:#0f1419;--fg:#e6e8eb;--muted:#9aa4af;--line:#2d333b;--soft:#161b22;--accent:#6cb6ff;--code:#1c2128;--mark:#3b3a1f}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.75 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif}
.layout{display:flex;max-width:1400px;margin:0 auto}
nav{position:sticky;top:0;align-self:flex-start;width:270px;flex:none;height:100vh;overflow:auto;padding:24px 12px 40px 20px;border-right:1px solid var(--line);font-size:13px}
nav .t{font-weight:600;margin-bottom:10px;color:var(--muted)}
nav a{display:block;color:var(--fg);text-decoration:none;padding:3px 6px;border-radius:4px;line-height:1.45}
nav a:hover{background:var(--soft)}
nav a.l3{padding-left:20px;color:var(--muted);font-size:12.5px}
main{flex:1;min-width:0;padding:28px 48px 80px}
h1{font-size:26px;margin:0 0 18px;padding-bottom:12px;border-bottom:2px solid var(--fg)}
h2{font-size:20px;margin:40px 0 14px;padding:6px 0 6px 12px;border-left:4px solid var(--accent);scroll-margin-top:12px}
h3{font-size:16.5px;margin:28px 0 10px;scroll-margin-top:12px}
h4{font-size:15px;margin:20px 0 8px}
p{margin:10px 0}
a{color:var(--accent)}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13.5px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--soft);white-space:nowrap}
tr:nth-child(even) td{background:color-mix(in srgb,var(--soft) 55%,transparent)}
code{background:var(--code);padding:1px 5px;border-radius:4px;font:12.5px/1.5 ui-monospace,Consolas,"Cascadia Mono",monospace}
pre{background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:12px 14px;overflow-x:auto;line-height:1.5}
pre code{background:none;padding:0;font-size:12.5px}
blockquote{margin:12px 0;padding:6px 14px;border-left:3px solid var(--line);color:var(--muted);background:var(--soft)}
hr{border:none;border-top:1px solid var(--line);margin:32px 0}
ul,ol{padding-left:24px}
li{margin:3px 0}
.meta{color:var(--muted);font-size:13px;margin:-8px 0 20px}
.wait{background:var(--mark);padding:0 3px;border-radius:3px}
@media (max-width:900px){nav{display:none}main{padding:20px 16px 60px}}
@media print{nav{display:none}main{padding:0}h2{break-after:avoid}pre,table{break-inside:avoid}}
"""


def slug(text, used):
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[\s`*·，、：:（）()（）/\\\"'“”《》【】〔〕.,!?？！]+", "-", s).strip("-") or "sec"
    base, n = s, 2
    while s in used:
        s = f"{base}-{n}"; n += 1
    used.add(s)
    return s


def convert(md_path, out_path, meta, link_prefix=""):
    src = pathlib.Path(md_path).read_text(encoding="utf-8")
    md = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
    body = md.render(src)
    used, toc = set(), []
    title = re.search(r"<h1>(.*?)</h1>", body).group(1)

    def add_id(m):
        lvl, inner = m.group(1), m.group(2)
        i = slug(inner, used)
        if lvl in ("2", "3"):
            toc.append((lvl, i, re.sub(r"<[^>]+>", "", inner)))
        return f'<h{lvl} id="{i}">{inner}</h{lvl}>'
    body = re.sub(r"<h([1-4])>(.*?)</h\1>", add_id, body)
    # 〔待验证〕等标记高亮
    body = re.sub(r"〔(待[^〕]{1,40})〕", r'<span class="wait">〔\1〕</span>', body)
    # contracts/ 路径变成可点的相对链接
    body = re.sub(r"<code>(contracts/[^<\s#]+?)(#[^<]*)?</code>",
                  lambda m: f'<a href="{link_prefix}{m.group(1)}"><code>{m.group(1)}{m.group(2) or ""}</code></a>', body)
    body = body.replace(f"<h1 id=", '<h1 data-x id=', 1)
    body = re.sub(r"(<h1[^>]*>.*?</h1>)", r'\1\n<p class="meta">' + html.escape(meta) + "</p>", body, count=1)
    nav = "".join(f'<a class="l{l}" href="#{i}">{html.escape(t)}</a>' for l, i, t in toc)
    plain_title = re.sub(r"<[^>]+>", "", title)
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(plain_title)}</title><style>{CSS}</style></head>
<body><div class="layout"><nav><div class="t">目录</div>{nav}</nav><main>
{body}
</main></div></body></html>
"""
    pathlib.Path(out_path).write_text(page, encoding="utf-8")
    print(out_path, len(page), "bytes,", len(toc), "toc entries")


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[1]
    docs = root / "docs"
    convert(docs / "src" / "PRD.md", docs / "PRD.html", "技术实现和接口契约见 Spec.html", "../")
    convert(docs / "src" / "Spec.md", docs / "Spec.html", "需求见 PRD.html；字段级契约见仓库根目录 contracts/", "../")
