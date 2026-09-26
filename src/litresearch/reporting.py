"""用已通过片段校验的记录生成Markdown，不自动推断跨论文优劣。"""

from html import escape

from .models import ResearchReport


def cell(value: str) -> str:
    return escape(value).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def render_markdown(report: ResearchReport) -> str:
    lines = ["# 文献调研流程报告", "", f"主题：{cell(report.topic)}", ""]
    if report.mode == "demo":
        lines += ["> 离线演示：全部材料均为项目自建合成示例，未进行在线检索或真实模型分析。", ""]
    lines += [
        "验证范围：仅检查证据片段存在于对应段落，未进行语义支持性核验。",
        "",
        "## 文献记录",
        "",
        "| ID | 标题 | 来源 | 阅读层级 |",
        "|---|---|---|---|",
    ]
    for paper in report.papers:
        lines.append(
            f"| {cell(paper.paper_id)} | {cell(paper.title)} | "
            f"{cell(paper.source)} | {paper.content_level} |"
        )
    lines += [
        "",
        "## 按维度列示的提取结果",
        "",
        "此表尚不代表跨论文综合分析。",
        "",
        "| 文献 | 维度 | 提取内容 | 段落 | 原文片段 |",
        "|---|---|---|---|---|",
    ]
    for item in report.findings:
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in [
                    item.paper_id,
                    item.dimension,
                    item.claim,
                    item.block_id,
                    item.quote,
                ]
            )
            + " |"
        )
    lines += ["", "## 局限与异常", ""]
    lines += [f"- {cell(warning)}" for warning in report.warnings] or ["- 本次未记录工具异常。"]
    lines += ["", "## 运行记录", "", f"检索轮次：{report.search_rounds}", ""]
    lines += [f"- {event}" for event in report.events]
    return "\n".join(lines) + "\n"
