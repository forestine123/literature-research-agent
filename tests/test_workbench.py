import asyncio
import json

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from litresearch.workbench.api import create_app
from litresearch.workbench.engine import Engine, original_quote, validate_claims, verified_findings
from litresearch.workbench.model import BudgetError, ModelClient, ModelError
from litresearch.workbench.reading import parse_pdf
from litresearch.workbench.schemas import (
    STAGES,
    Block,
    Claim,
    Finding,
    Paper,
    Probe,
    Provider,
    Request,
    Settings,
)
from litresearch.workbench.sources import ScholarSearch, select
from litresearch.workbench.store import Store
from litresearch.workbench.vectors import VectorIndex


def run(awaitable):
    return asyncio.run(awaitable)


def test_settings_do_not_echo_secrets_or_send_saved_key_to_new_host(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        settings = Settings(providers={"default": Provider(api_key="private-key", model="test")})
        response = client.put("/api/settings", json=settings.model_dump())
        assert response.status_code == 200
        assert "private-key" not in response.text
        public = response.json()
        public["providers"]["default"]["base_url"] = "https://new.example/v1"
        assert client.put("/api/settings", json=public).status_code == 400
        assert (
            client.get("/api/settings", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 400


def test_claim_and_restart_reconcile(tmp_path):
    store = Store(tmp_path)
    tid = store.create(Request(topic="恢复测试"))
    assert store.claim(tid)
    assert not store.claim(tid)
    store.checkpoint(tid, {"done": ["search"], "papers": ["kept"]}, "read")
    assert store.reconcile() == 1
    task = store.get(tid)
    assert task["status"] == "interrupted"
    assert task["state"]["papers"] == ["kept"]
    assert store.events(tid)[-1]["kind"] == "interrupted"
    assert store.claim(tid)


def test_dedup_merges_sources_and_filters():
    req = Request(topic="retrieval", year_from=2020, exclude=["exclude"])
    items = [
        Paper(
            id="a",
            title="Retrieval Study",
            doi="https://doi.org/10.1/ABC",
            source="arxiv",
            year=2024,
        ),
        Paper(
            id="b",
            title="Retrieval study!",
            doi="10.1/abc",
            source="openalex",
            year=2024,
            pdf_url="https://example.org/p.pdf",
        ),
        Paper(id="c", title="Old retrieval", source="arxiv", year=2010),
        Paper(id="d", title="Retrieval exclude", source="arxiv", year=2024),
    ]
    result = select(items, req, ["retrieval"])
    assert len(result) == 1
    assert result[0].sources == ["arxiv", "openalex"]
    assert result[0].pdf_url.endswith("p.pdf")


def test_rejects_invented_quotes_and_unknown_citations():
    block = Block(id="b1", text="This is exact evidence from a document.", page=2)
    good = Finding(dimension="方法", claim="方法描述", block_id="b1", quote="exact evidence")
    wrong = good.model_copy(update={"quote": "fabricated quote"})
    evidence, rejected = verified_findings("paper", [block], [good, wrong])
    assert len(evidence) == 1 and evidence[0].page == 2 and len(rejected) == 1
    with pytest.raises(ValueError):
        validate_claims([Claim(text="unsupported", evidence_ids=["invented"])], {"E-1"})


def test_layout_normalization_maps_back_to_original_without_fuzzy_matching():
    text = "This retrieval aug-\nmented method is\n supported by evidence."
    quote = original_quote(text, "retrieval augmented method is supported by evidence.")
    assert quote in text
    assert "aug-\nmented" in quote
    assert original_quote(text, "retrieval augmented method is NOT supported by evidence.") is None


@pytest.mark.parametrize("backend", ["openai", "openai_compat", "anthropic", "anthropic_compat"])
def test_protocols_and_usage(backend):
    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == "model-test"
        if backend.startswith("anthropic"):
            assert req.headers["x-api-key"] == "secret"
            assert body["system"] and req.url.path == "/v1/messages"
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": '{"ok":true}'}],
                    "usage": {"input_tokens": 20, "output_tokens": 5},
                },
            )
        assert req.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    settings = Settings(
        providers={"default": Provider(backend=backend, api_key="secret", model="model-test")}
    )
    model = ModelClient(
        settings, Request(topic="测试主题"), lambda *a: None, transport=httpx.MockTransport(handler)
    )
    assert run(model.json("search", "probe", {}, Probe)).ok
    assert model.usage["search"]["budget_tokens"] == 25


def test_model_format_retry_and_budget():
    count = 0

    def handler(req):
        nonlocal count
        count += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "bad" if count == 1 else '{"ok":true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    settings = Settings(providers={"default": Provider(model="m")})
    model = ModelClient(
        settings, Request(topic="格式重试"), lambda *a: None, transport=httpx.MockTransport(handler)
    )
    assert run(model.json("search", "probe", {}, Probe)).ok
    assert count == 2 and model.usage["search"]["calls"] == 2
    low = ModelClient(
        settings,
        Request(topic="预算不足", token_budget=1000),
        lambda *a: None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(BudgetError):
        run(low.json("search", "probe", {}, Probe))
    assert count == 2


def test_auth_error_not_retried_and_redacted():
    def handler(req):
        return httpx.Response(401, text="secret in upstream body")

    settings = Settings(providers={"default": Provider(model="m", api_key="secret")})
    model = ModelClient(
        settings, Request(topic="错误处理"), lambda *a: None, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ModelError, match="HTTP 401") as caught:
        run(model.json("search", "probe", {}, Probe))
    assert "secret" not in str(caught.value)
    assert model.usage["search"]["calls"] == 1


def test_pdf_pages_and_vector_persistence(tmp_path):
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Evidence tracing preserves source locations.")
    doc.new_page().insert_text((72, 72), "Graph retrieval uses connected entities.")
    doc.save(path)
    doc.close()
    reading, md = parse_pdf(path, "paper")
    assert reading.pages == 2 and {b.page for b in reading.blocks} == {1, 2}
    assert "第 2 页" in md

    async def exercise():
        index = VectorIndex(tmp_path, "test", Settings())
        await index.add("paper", reading.blocks)
        again = VectorIndex(tmp_path, "test", Settings())
        hits = await again.query("Graph retrieval connected entities", 1)
        assert hits[0]["page"] == 2

    run(exercise())


def test_demo_engine_and_resume_does_not_duplicate_evidence(tmp_path):
    store = Store(tmp_path)
    tid = store.create(Request(topic="文献调研测试", mode="demo", max_papers=3))
    store.claim(tid)
    run(Engine(store, tid).run())
    task = store.get(tid)
    assert task["status"] == "completed", task["error"]
    assert task["state"]["done"] == list(STAGES)
    assert len(task["state"]["evidence"]) == 3
    assert "合成演示" in task["state"]["report"]
    state = task["state"]
    state["done"] = ["search", "read"]
    state["sections"] = []
    store.checkpoint(tid, state, "analyse")
    store.status(tid, "interrupted")
    store.claim(tid)
    run(Engine(store, tid).run())
    assert store.get(tid)["status"] == "completed"
    assert len(store.get(tid)["state"]["evidence"]) == 3


def test_sse_replays_saved_events_and_upload_validation(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        store = app.state.store
        tid = store.create(Request(topic="历史事件"))
        store.status(tid, "failed", "test failure")
        response = client.get(f"/api/tasks/{tid}/events")
        assert "event: progress" in response.text and "event: done" in response.text
        assert client.get(f"/api/tasks/{tid}/export/md").status_code == 409
        assert (
            client.post("/api/uploads", files={"file": ("bad.pdf", b"not a pdf")}).status_code
            == 400
        )
        assert (
            client.post("/api/tasks", json={"topic": "实测缺少模型", "mode": "live"}).status_code
            == 400
        )


def test_three_connector_field_mappings():
    def handler(req):
        if "arxiv" in req.url.host:
            assert "AND" in req.url.params["search_query"]
            return httpx.Response(
                200,
                text="""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.01234</id><title>Graph retrieval</title><published>2024-01-01</published><summary>Abstract text</summary><author><name>A Author</name></author></entry></feed>""",
            )
        if "openalex" in req.url.host:
            assert req.headers["Authorization"] == "Bearer openalex-secret"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "title": "Graph retrieval",
                            "publication_year": 2024,
                            "abstract_inverted_index": {"Graph": [0], "retrieval": [1]},
                            "best_oa_location": {"pdf_url": "https://example.org/p.pdf"},
                        }
                    ]
                },
            )
        assert req.headers["x-api-key"] == "scholar-secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "s1",
                        "title": "Graph retrieval",
                        "year": 2024,
                        "abstract": "Abstract text",
                        "externalIds": {"DOI": "10.1/test"},
                        "openAccessPdf": {"url": "https://example.org/p.pdf"},
                    }
                ]
            },
        )

    search = ScholarSearch(
        Settings(openalex_key="openalex-secret", semantic_scholar_key="scholar-secret"),
        transport=httpx.MockTransport(handler),
    )
    papers, notes = run(search.search(["graph retrieval"], Request(topic="graph retrieval")))
    assert len(papers) == 3 and all(n["status"] == "ok" for n in notes)
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2401.01234"
    assert papers[1].abstract == "Graph retrieval"
    assert papers[2].doi == "10.1/test"


def test_download_rejects_private_network_and_accepts_only_official_proxy_mapping(monkeypatch):
    from litresearch.workbench.reading import public_url

    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a: [(None, None, None, None, ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError):
        run(public_url("https://example.org/file.pdf"))
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *a: [(None, None, None, None, ("198.18.0.1", 443))]
    )
    with pytest.raises(ValueError):
        run(public_url("https://other.example/file.pdf"))
    run(public_url("https://arxiv.org/pdf/1706.03762"))


def test_cancel_keeps_checkpoint_and_resume_completes(tmp_path):
    async def exercise():
        store = Store(tmp_path)
        tid = store.create(Request(topic="取消与恢复", mode="demo"))
        store.claim(tid)
        signal = asyncio.Event()
        signal.set()
        await Engine(store, tid, signal).run()
        assert store.get(tid)["status"] == "cancelled"
        assert store.claim(tid)
        await Engine(store, tid).run()
        assert store.get(tid)["status"] == "completed"

    run(exercise())


@pytest.mark.parametrize("supplement_from", ["analyse", "write"])
def test_live_contract_pipeline_with_bounded_supplement_and_audit(tmp_path, supplement_from):
    """仅模拟模型/来源；验证真实模式控制分支，不作真实 API 质量证据。"""
    from litresearch.workbench.schemas import (
        Analysis,
        EvidenceAudit,
        EvidenceCorrection,
        Extraction,
        Outline,
        Plan,
        Relevance,
        Review,
        Section,
        SectionPlan,
    )

    class Model:
        async def json(self, stage, instruction, data, schema, validator=None):
            if schema is Plan:
                return Plan(queries=["evidence tracing"], subtopics=["证据方法"])
            if schema is Relevance:
                return Relevance(relevant=True, reason="相关")
            if schema is Extraction:
                block = data["blocks"][0]
                return Extraction(
                    findings=[
                        Finding(
                            dimension="方法",
                            claim="保留原文证据",
                            block_id=block["id"],
                            quote=block["text"],
                        )
                    ]
                )
            if schema is EvidenceAudit:
                return EvidenceAudit(
                    corrections=[
                        EvidenceCorrection(id=e["id"], claim=e["claim"], quote=e["quote"])
                        for e in data["evidence"]
                    ]
                )
            if schema is Analysis:
                return Analysis(
                    claims=[Claim(text="证据支持定位", evidence_ids=[data["evidence"][0]["id"]])],
                    gaps=["缺少比较"],
                    followup_queries=["more evidence"] if supplement_from == "analyse" else [],
                )
            if schema is Outline:
                return Outline(
                    sections=[
                        SectionPlan(
                            title="方法比较", evidence_ids=[e["id"] for e in data["evidence"]]
                        )
                    ]
                )
            if schema is Section:
                return Section(
                    paragraphs=[
                        Claim(text="保留原文用于核验", evidence_ids=[data["evidence"][0]["id"]])
                    ]
                )
            if schema is Review:
                if supplement_from == "write" and len(data["evidence"]) < 2:
                    return Review(approved=False, issues=["缺少比较证据"], rejected_paragraphs=[0])
                return Review(approved=True)
            raise AssertionError(schema)

    class Search:
        calls = 0

        async def search(self, queries, request):
            self.calls += 1
            return [
                Paper(
                    id=f"paper-{self.calls}",
                    title=f"Evidence {self.calls}",
                    source="mock",
                    year=2024,
                    abstract="This method preserves source evidence for verification.",
                )
            ], []

    store = Store(tmp_path)
    task_id = store.create(Request(topic="证据方法比较", mode="live", max_papers=2, max_rounds=2))
    store.claim(task_id)
    search = Search()
    run(Engine(store, task_id, model=Model(), search=search).run())
    task = store.get(task_id)
    assert task["status"] == "completed", task["error"]
    assert search.calls == 2
    assert len(task["state"]["evidence"]) == 2
    assert len(task["state"]["audited_papers"]) == 2
    assert "研究方法与实验条件" in task["state"]["report"]


def test_audit_material_deduplicates_blocks_without_losing_context():
    from litresearch.workbench.engine import audit_material

    evidence = [
        {"id": "E-1", "block_id": "b1", "quote": "first"},
        {"id": "E-2", "block_id": "b1", "quote": "second"},
        {"id": "E-3", "block_id": "b2", "quote": "third"},
    ]
    blocks = {"b1": "first and second with all conditions", "b2": "third", "b3": "unused"}
    result = audit_material("论文", evidence, blocks)
    assert result["evidence"] == evidence
    assert result["source_blocks"] == {"b1": blocks["b1"], "b2": blocks["b2"]}
    assert all(result["source_blocks"][e["block_id"]] == blocks[e["block_id"]] for e in evidence)


def test_claims_allow_algorithm_delimiters_but_not_inline_evidence():
    validate_claims(
        [Claim(text="以“[”进入抽取模式，以“]”返回生成；概率位于[0, 1]。", evidence_ids=["E-1"])],
        {"E-1"},
    )
    with pytest.raises(ValueError, match="正文不得"):
        validate_claims([Claim(text="结论 [E-1]", evidence_ids=["E-1"])], {"E-1"})


def test_pdf_chunks_keep_metric_sentence_and_preserve_all_text():
    from litresearch.workbench.reading import split_passage

    text = (
        "Earlier finding. " * 105
        + "The VS Context Recall gain was 0.63 and Context Precision gain was 0.56. "
    )
    chunks = list(split_passage(text))
    assert "".join(chunks) == text
    assert all(len(chunk) <= 1800 for chunk in chunks)
    assert any(
        "VS Context Recall gain was 0.63 and Context Precision gain was 0.56" in c for c in chunks
    )
    assert "".join(split_passage("x" * 4000)) == "x" * 4000


def test_review_rejects_inconsistent_verdict_and_out_of_range_indices():
    from litresearch.workbench.engine import validate_review
    from litresearch.workbench.schemas import Review

    with pytest.raises(ValueError, match="实质问题"):
        Review(approved=False, issues=["未见实质错误"], rejected_paragraphs=[])
    with pytest.raises(ValueError, match="必须为空"):
        Review(approved=True, issues=["unsupported"], rejected_paragraphs=[0])
    with pytest.raises(ValueError, match="段落下标"):
        validate_review(Review(approved=False, issues=["缺少支持"], rejected_paragraphs=[2]), 2)
    validate_review(Review(approved=True), 2)
