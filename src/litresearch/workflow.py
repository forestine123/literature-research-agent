"""带检索轮次上限的LangGraph基础流程。"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .evidence import evidence_error
from .models import Document, Finding, PaperRecord, ResearchReport, ResearchRequest, SearchPlan
from .ports import LiteraturePort, ModelPort


class State(TypedDict):
    request: ResearchRequest
    plan: SearchPlan
    papers: list[PaperRecord]
    documents: dict[str, Document]
    findings: list[Finding]
    warnings: list[str]
    events: list[str]
    search_rounds: int


def paper_key(paper: PaperRecord) -> str:
    doi = (paper.doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :].strip()
    return f"doi:{doi}" if doi else f"id:{paper.paper_id}"


def build_workflow(model: ModelPort, literature: LiteraturePort):
    def plan(state: State) -> dict:
        return {"plan": model.plan(state["request"]), "events": ["plan:completed"]}

    def search(state: State) -> dict:
        request = state["request"]
        round_index = state["search_rounds"]
        query = state["plan"].queries[round_index]
        papers = list(state["papers"])
        seen = {paper_key(paper) for paper in papers}
        seen_ids = {paper.paper_id for paper in papers}
        warnings = list(state["warnings"])
        try:
            candidates = literature.search(query, request.max_papers)
        except (TimeoutError, ConnectionError) as exc:
            candidates = []
            warnings.append(f"第{round_index + 1}轮检索失败：{type(exc).__name__}")
        for paper in candidates:
            if len(papers) >= request.max_papers:
                break
            key = paper_key(paper)
            if key not in seen and paper.paper_id not in seen_ids:
                papers.append(paper)
                seen.add(key)
                seen_ids.add(paper.paper_id)
        return {
            "papers": papers,
            "warnings": warnings,
            "search_rounds": round_index + 1,
            "events": state["events"] + [f"search:{round_index + 1}"],
        }

    def route(state: State) -> str:
        limit = min(state["request"].max_search_rounds, len(state["plan"].queries))
        if len(state["papers"]) < state["request"].max_papers and state["search_rounds"] < limit:
            return "search"
        return "read"

    def read(state: State) -> dict:
        documents: dict[str, Document] = {}
        warnings = list(state["warnings"])
        for paper in state["papers"]:
            try:
                document = literature.read(paper)
                if document.paper_id != paper.paper_id:
                    raise ValueError("文档与论文ID不一致")
                if not document.blocks:
                    warnings.append(f"{paper.paper_id}无可读文本")
                documents[paper.paper_id] = document
            except (OSError, ValueError) as exc:
                warnings.append(f"{paper.paper_id}阅读失败：{type(exc).__name__}")
        if len(state["papers"]) < state["request"].max_papers:
            warnings.append("检索结果不足，按实际取得的材料生成结果。")
        return {
            "documents": documents,
            "warnings": warnings,
            "events": state["events"] + ["read:completed"],
        }

    def extract(state: State) -> dict:
        findings: list[Finding] = []
        warnings = list(state["warnings"])
        for paper in state["papers"]:
            document = state["documents"].get(paper.paper_id)
            if document is None or not document.blocks:
                continue
            for finding in model.extract(paper, document):
                if finding.paper_id != paper.paper_id:
                    warnings.append(f"{paper.paper_id}提取结果错配论文，已排除。")
                else:
                    findings.append(finding)
        return {
            "findings": findings,
            "warnings": warnings,
            "events": state["events"] + ["extract:completed"],
        }

    def verify(state: State) -> dict:
        accepted: list[Finding] = []
        warnings = list(state["warnings"])
        for finding in state["findings"]:
            error = evidence_error(finding, state["documents"])
            if error:
                warnings.append(f"{finding.paper_id}/{finding.block_id}：{error}，已排除。")
            else:
                accepted.append(finding)
        return {
            "findings": accepted,
            "warnings": warnings,
            "events": state["events"] + ["verify:completed"],
        }

    graph = StateGraph(State)
    for name, node in [
        ("plan", plan),
        ("search", search),
        ("read", read),
        ("extract", extract),
        ("verify", verify),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "search")
    graph.add_conditional_edges("search", route, {"search": "search", "read": "read"})
    graph.add_edge("read", "extract")
    graph.add_edge("extract", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


def run_research(
    request: ResearchRequest,
    model: ModelPort,
    literature: LiteraturePort,
    *,
    mode: Literal["demo", "live"],
) -> ResearchReport:
    result = build_workflow(model, literature).invoke(
        {
            "request": request,
            "papers": [],
            "documents": {},
            "findings": [],
            "warnings": [],
            "events": [],
            "search_rounds": 0,
        }
    )
    return ResearchReport(
        topic=request.topic,
        mode=mode,
        papers=result["papers"],
        findings=result["findings"],
        warnings=result["warnings"],
        events=result["events"],
        search_rounds=result["search_rounds"],
    )
