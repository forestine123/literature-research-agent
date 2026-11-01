import asyncio

import httpx

from litresearch.workbench.schemas import Paper, Request, Settings
from litresearch.workbench.sources import ScholarSearch, select


def test_title_priority_and_no_substring_match():
    request = Request(topic="RAG factuality", max_papers=3)
    papers = [
        Paper(id="a", title="Graph fragments", abstract="fragmentation", source="arxiv"),
        Paper(id="b", title="RAG factuality", source="arxiv"),
        Paper(id="c", title="General survey", abstract="RAG factuality", source="arxiv"),
    ]
    result = select(papers, request, ["RAG factuality", "faithfulness evaluation"])
    assert [p.id for p in result] == ["b", "c", "a"]
    assert result[-1].score == 0


def test_rate_limit_stops_remaining_queries(monkeypatch):
    search = ScholarSearch(Settings())
    calls = []

    async def one(source, query, limit, request):
        calls.append(query)
        response = httpx.Response(429, request=httpx.Request("GET", "https://example.org"))
        response.raise_for_status()

    monkeypatch.setattr(search, "one", one)
    papers, notes = asyncio.run(
        search.search(["first", "second"], Request(topic="RAG", sources=["semantic_scholar"]))
    )
    assert not papers and calls == ["first"]
    assert [n["status"] for n in notes] == ["http_429", "remaining_queries_skipped"]


def test_small_arxiv_result_broadens_once(monkeypatch):
    search = ScholarSearch(Settings())
    calls = []

    async def one(source, query, limit, request):
        calls.append(query)
        return [Paper(id="a", title="RAG factuality", source="arxiv")]

    async def no_wait(_):
        pass

    monkeypatch.setattr(search, "one", one)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    _, notes = asyncio.run(
        search.search(
            ["retrieval augmented generation factuality evaluation"],
            Request(topic="RAG", sources=["arxiv"], max_papers=3),
        )
    )
    assert len(calls) == 2
    assert calls[1] == "retrieval augmented generation"
    assert notes[-1]["status"] == "broadened"
