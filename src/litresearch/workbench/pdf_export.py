"""A4 文献综述 PDF：嵌入中文字体、目录、页码和实际覆盖图。"""

import html
import io
import os
from pathlib import Path

from markdown_it import MarkdownIt
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer
from reportlab.platypus.tableofcontents import TableOfContents


def font_name():
    name = "ResearchSong"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    path = Path(os.environ.get("LITRESEARCH_PDF_FONT", "C:/Windows/Fonts/simsun.ttc"))
    if path.is_file():
        pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
        return name
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


class ResearchDocument(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "Section":
            key = getattr(flowable, "anchor", "")
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=0)
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page, key))


def report_pdf(task):
    font = font_name()
    body = ParagraphStyle(
        "Body", fontName=font, fontSize=10.5, leading=17, spaceAfter=8, wordWrap="CJK"
    )
    small = ParagraphStyle(
        "Small", parent=body, fontSize=9, leading=14, textColor=colors.HexColor("#526078")
    )
    heading = ParagraphStyle(
        "Section",
        parent=body,
        fontSize=15,
        leading=23,
        spaceBefore=18,
        spaceAfter=12,
        keepWithNext=True,
    )
    subheading = ParagraphStyle("Subsection", parent=heading, fontSize=12, leading=19)
    title = ParagraphStyle("Title", parent=body, fontSize=23, leading=34, spaceAfter=24)
    buffer = io.BytesIO()
    document = ResearchDocument(
        buffer,
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=48,
        title=task["topic"],
        author="文献调研工作台",
    )

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(54, A4[1] - 30, "文献调研报告 / 可追溯研究初稿")
        canvas.drawRightString(A4[0] - 54, 28, str(doc.page))
        canvas.setStrokeColor(colors.HexColor("#dce2ea"))
        canvas.line(54, A4[1] - 36, A4[0] - 54, A4[1] - 36)
        canvas.restoreState()

    document.addPageTemplates(
        PageTemplate(
            id="paper",
            frames=[
                Frame(
                    54,
                    48,
                    A4[0] - 108,
                    A4[1] - 102,
                    leftPadding=0,
                    rightPadding=0,
                    topPadding=0,
                    bottomPadding=0,
                )
            ],
            onPage=furniture,
        )
    )

    def p(text, style=body):
        return Paragraph(html.escape(html.unescape(text)), style)

    state = task["state"]
    story = [
        Spacer(1, 65),
        p("文献调研报告", subheading),
        p(task["topic"], title),
        p(task["request"].get("focus", "")),
        Spacer(1, 20),
        p("基于已获取文献自动生成；事实、统计口径与语义支持仍需人工核验。", small),
        p("任务编号：" + task["id"], small),
        p("生成记录：" + task.get("created", "")[:10], small),
        PageBreak(),
    ]
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOC", parent=body, leftIndent=0, firstLineIndent=0, spaceBefore=6)
    ]
    story += [p("目录", title), toc, PageBreak()]
    papers = state.get("papers", [])
    if papers:
        story.append(p("文献与证据覆盖", heading))
        story[-1].anchor = "coverage"
        chart = Drawing(470, 38 + len(papers) * 25)
        counts = [
            sum(e["paper_id"] == paper["id"] for e in state.get("evidence", [])) for paper in papers
        ]
        maximum = max(counts + [1])
        for index, count in enumerate(counts):
            y = chart.height - 30 - index * 25
            chart.add(String(0, y, f"P{index + 1}", fontName=font, fontSize=10))
            chart.add(
                Rect(
                    36,
                    y - 2,
                    350 * count / maximum,
                    13,
                    fillColor=colors.HexColor("#49647f"),
                    strokeColor=None,
                )
            )
            chart.add(String(395, y, str(count), fontName=font, fontSize=10))
        story += [chart, p("图 1  各候选文献保留的证据条数（不是质量评分或实验性能）。", small)]
        for i, paper in enumerate(papers):
            level = state.get("readings", {}).get(paper["id"], {}).get("level", "unavailable")
            label = {
                "fulltext": "取得全文",
                "abstract": "仅摘要",
                "unavailable": "未纳入或不可读",
            }.get(level, level)
            story.append(p(f"P{i + 1} · {paper['title']} · {label}", small))
        story.append(PageBreak())
    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(state["report"])
    index, section = 0, 0
    in_table, cells, headers, in_head = False, [], [], False
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            in_table, headers = True, []
        elif token.type == "table_close":
            in_table = False
        elif token.type == "thead_open":
            in_head = True
        elif token.type == "thead_close":
            in_head = False
        elif token.type == "tr_open":
            cells = []
        elif token.type == "inline" and in_table:
            cells.append(token.content)
        elif token.type == "tr_close":
            if in_head:
                headers = cells
            else:
                # 长比较表转为按文献分组的字段列表，完整保留文字，避免宽表裁切。
                for n, cell in enumerate(cells):
                    story.append(
                        p(
                            (headers[n] + "：" if n < len(headers) else "") + cell,
                            subheading if n == 0 else body,
                        )
                    )
                story.append(Spacer(1, 8))
        elif token.type == "heading_open":
            text = tokens[index + 1].content
            if token.tag != "h1":
                style = heading if token.tag == "h2" else subheading
                item = p(text, style)
                if token.tag == "h2":
                    section += 1
                    item.anchor = f"section-{section}"
                story.append(item)
            index += 2
        elif token.type == "inline" and not in_table:
            text = "".join(
                child.content if child.type not in {"softbreak", "hardbreak"} else " "
                for child in (token.children or [])
                if child.type
                not in {
                    "strong_open",
                    "strong_close",
                    "em_open",
                    "em_close",
                    "link_open",
                    "link_close",
                    "image",
                }
            )
            if text.strip():
                story.append(p(text))
        index += 1
    document.multiBuild(story)
    return buffer.getvalue()
