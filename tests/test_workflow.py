import pytest
from pydantic import ValidationError

from litresearch.demo import DemoLiterature, DemoModel
from litresearch.models import Document, ResearchRequest
from litresearch.reporting import render_markdown
from litresearch.workflow import run_research


def run(tools=None, model=None, **kwargs):
    return run_research(
        ResearchRequest(topic="测试", **kwargs),
        model or DemoModel(),
        tools or DemoLiterature(),
        mode="demo",
    )


def test_offline_pipeline_keeps_source_and_demo_boundary():
    report = run()
    assert len(report.papers) == 3
    assert len(report.findings) == 6
    assert report.search_rounds == 1
    assert report.events[-1] == "verify:completed"
    assert report.semantic_verification == "not_performed"
    assert "合成示例" in render_markdown(report)


def test_empty_search_stops_at_budget():
    class Empty(DemoLiterature):
        def search(self, query, limit):
            return []

    report = run(Empty(), max_search_rounds=2)
    assert report.search_rounds == 2
    assert report.papers == []
    assert any("结果不足" in warning for warning in report.warnings)


def test_timeout_uses_next_query_without_infinite_retry():
    class Flaky(DemoLiterature):
        calls = 0

        def search(self, query, limit):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return super().search(query, limit)

    report = run(Flaky())
    assert report.search_rounds == 2
    assert len(report.papers) == 3
    assert any("TimeoutError" in warning for warning in report.warnings)


def test_doi_variants_do_not_fill_multiple_slots():
    class Duplicated(DemoLiterature):
        def search(self, query, limit):
            original = self.papers[0].model_copy(update={"doi": "10.1234/demo"})
            duplicate = original.model_copy(
                update={"paper_id": "copy", "doi": "https://doi.org/10.1234/DEMO"}
            )
            return [original, duplicate]

    report = run(Duplicated(), max_papers=2)
    assert len(report.papers) == 1
    assert report.search_rounds == 3


def test_fabricated_quotes_are_excluded():
    class Fabricating(DemoModel):
        def extract(self, paper, document):
            findings = super().extract(paper, document)
            return [finding.model_copy(update={"quote": "原文没有这句话"}) for finding in findings]

    report = run(model=Fabricating())
    assert report.findings == []
    assert len(report.warnings) == 6


def test_wrong_paper_attribution_is_excluded_even_when_document_exists():
    class WrongPaper(DemoModel):
        def extract(self, paper, document):
            findings = super().extract(paper, document)
            return [finding.model_copy(update={"paper_id": "demo-2"}) for finding in findings]

    report = run(model=WrongPaper())
    assert len(report.findings) == 2
    assert all(finding.paper_id == "demo-2" for finding in report.findings)


def test_read_failure_is_reported_and_other_papers_continue():
    class Broken(DemoLiterature):
        def read(self, paper):
            if paper.paper_id == "demo-1":
                raise OSError()
            return super().read(paper)

    report = run(Broken())
    assert len(report.findings) == 4
    assert any("阅读失败" in warning for warning in report.warnings)


def test_wrong_document_identity_does_not_enter_extraction():
    class WrongDocument(DemoLiterature):
        def read(self, paper):
            return Document(paper_id="other", blocks=[])

    assert run(WrongDocument()).findings == []


@pytest.mark.parametrize("topic", ["", "   "])
def test_blank_topic_rejected(topic):
    with pytest.raises(ValidationError):
        ResearchRequest(topic=topic)


def test_paper_budget_and_markdown_escaping():
    report = run(max_papers=1)
    assert len(report.papers) == 1
    report.topic = "<script>|危险\n标题"
    text = render_markdown(report)
    assert "<script>" not in text
    assert "&#124;" in text
