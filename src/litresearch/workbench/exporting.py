"""可离线阅读和打印的成品报告，不加载外部脚本或样式。"""

import html

from markdown_it import MarkdownIt


def report_html(title, markdown):
    parser = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")
    tokens = parser.parse(markdown)
    toc = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            anchor = f"section-{len(toc) + 1}"
            token.attrSet("id", anchor)
            toc.append((anchor, tokens[index + 1].content, token.tag))
    body = parser.renderer.render(tokens, parser.options, {})
    links = "".join(
        f'<li><a href="#{anchor}">{html.escape(text)}</a></li>'
        for anchor, text, tag in toc
        if tag == "h2"
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;background:#f2f5fa;color:#24334b;font:16px/1.9 "Microsoft YaHei",sans-serif}}
main{{max-width:1000px;margin:32px auto;background:white;padding:48px;box-sizing:border-box}}
h1{{font-size:28px}}h2{{font-size:22px;border-bottom:1px solid #dce3ee;padding-bottom:8px;margin-top:36px}}h3{{font-size:18px}}
nav{{background:#f5f8fd;padding:18px 24px}}a{{color:#3658b5;overflow-wrap:anywhere}}p,li{{overflow-wrap:anywhere}}
table{{border-collapse:collapse;width:100%;font-size:12px;table-layout:fixed}}th,td{{border:1px solid #ccd6e4;padding:9px;vertical-align:top;overflow-wrap:anywhere}}th{{background:#edf2fa}}
blockquote{{border-left:3px solid #9aafd4;margin:16px 0;padding-left:16px}}pre{{white-space:pre-wrap}}.hint{{font-size:13px;color:#61718a}}
@media(max-width:700px){{main{{margin:0;padding:20px}}table{{font-size:10px}}}}
@media print{{@page{{size:A4;margin:18mm}}body{{background:white;font-size:11pt}}main{{margin:0;padding:0;max-width:none}}h1,h2,h3{{break-after:avoid}}tr{{break-inside:avoid}}thead{{display:table-header-group}}.hint{{display:none}}nav{{break-after:page}}}}
</style></head><body><main><p class="hint">离线文档 · 浏览器打印可另存为 PDF · 引用与局限保留在正文中</p><nav aria-label="目录"><b>目录</b><ol>{links}</ol></nav>{body}</main></body></html>"""
