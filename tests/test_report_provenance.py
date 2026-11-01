from litresearch.workbench.engine import render_report
from litresearch.workbench.schemas import Request


def test_report_discloses_sources_and_excludes_unread_comparisons():
    papers = [dict(id="p", title="已筛除论文", year=2024, url="https://example.org/p", doi="")]
    state = dict(
        papers=papers,
        readings={"p": {"warnings": ["摘要筛选不相关"]}},
        sections=[],
        evidence=[],
        warnings=[],
        diagnostics=[dict(source="semantic_scholar", status="http_429", count=0, query="test")],
    )
    report = render_report(Request(topic="真实文献测试"), state)
    assert "http_429" in report
    assert "## 摘要" in report
    assert "关键词：" in report
    assert "## 结论与展望" in report
    assert "不代表本系统复现实验" in report
    assert "筛除文献（不参与方法比较）" in report
    comparison = report.split("### 研究方法与实验条件")[1].split("## 证据索引")[0]
    assert "已筛除论文" not in comparison
