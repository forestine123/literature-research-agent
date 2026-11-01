"""五阶段 LangGraph 工作流与可检查的应用层断点。"""

import asyncio
import html
import json
import re
import time
import unicodedata
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from . import fixtures
from .model import ModelClient
from .reading import read_paper
from .schemas import (
    STAGES,
    Analysis,
    Claim,
    Evidence,
    EvidenceAudit,
    Extraction,
    Finding,
    Outline,
    Paper,
    Plan,
    Relevance,
    Request,
    Review,
    Section,
    SectionPlan,
)
from .sources import ScholarSearch, select
from .vectors import VectorIndex


class Interrupted(RuntimeError):
    pass


class GraphState(TypedDict):
    task_id: str


def validate_claims(claims, evidence_ids):
    for claim in claims:
        if not set(claim.evidence_ids) <= set(evidence_ids):
            missing = sorted(set(claim.evidence_ids) - set(evidence_ids))
            raise ValueError(f"出现未知证据 ID {missing}；只能使用提供的证据，不能编造或推测编号")
        if re.search(r"\[\s*E-[a-zA-Z0-9-]+\s*\]", claim.text):
            raise ValueError("正文不得自行插入证据 ID 引用，引用由 evidence_ids 统一生成")


def validate_review(review, paragraph_count):
    if any(i >= paragraph_count for i in review.rejected_paragraphs):
        raise ValueError(f"审查段落下标必须小于 {paragraph_count}，不能引用不存在的段落")


def canonical(text):
    """只规范化排版：空白、断行连字符及 Unicode 连字；保留字符到原文的映射。"""
    chars, positions = [], []
    skipped = set()
    for match in re.finditer(r"(?<=\w)-[ \t]*\n\s*(?=\w)", text):
        skipped.update(range(match.start(), match.end()))
    for offset, char in enumerate(text):
        if offset in skipped or char == "\u00ad":
            continue
        for value in unicodedata.normalize("NFKC", char):
            if value.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    positions.append(offset)
            else:
                chars.append(value)
                positions.append(offset)
    return "".join(chars), positions


def original_quote(text, quote):
    if quote in text:
        return quote
    content, positions = canonical(text)
    needle = canonical(quote)[0].strip()
    start = content.find(needle)
    if start < 0 or not needle:
        return None
    return text[positions[start] : positions[start + len(needle) - 1] + 1]


def verified_findings(paper_id, blocks, findings, start=0):
    lookup = {b.id: b for b in blocks}
    accepted, rejected = [], []
    for finding in findings:
        block = lookup.get(finding.block_id)
        located = original_quote(block.text, finding.quote) if block else None
        if not located:
            rejected.append(f"{paper_id}/{finding.block_id} 原文片段无法定位，已排除")
            continue
        accepted.append(
            Evidence(
                **finding.model_copy(update={"quote": located}).model_dump(),
                id=f"E-{paper_id}-{start + len(accepted) + 1}",
                paper_id=paper_id,
                page=block.page,
            )
        )
    return accepted, rejected


def balanced_evidence(items, per_dimension=4):
    counts, seen, result = {}, set(), []
    for item in items:
        key = (item["dimension"], canonical(item["quote"])[0])
        if key in seen or counts.get(item["dimension"], 0) >= per_dimension:
            continue
        seen.add(key)
        counts[item["dimension"]] = counts.get(item["dimension"], 0) + 1
        result.append(item)
    return result[:20]


def audit_material(title, evidence, blocks):
    """同一原文块只发送一次；证据保留 block_id，语义复核材料不截断。"""
    return {
        "title": title,
        "evidence": evidence,
        "source_blocks": {e["block_id"]: blocks[e["block_id"]] for e in evidence},
    }


class Engine:
    def __init__(self, store, task_id, cancel=None, model=None, search=None):
        self.store, self.task_id = store, task_id
        self.cancel = cancel or asyncio.Event()
        task = store.get(task_id)
        self.request = Request.model_validate(task["request"])
        self.state = task["state"]
        for key, default in {
            "done": [],
            "papers": [],
            "readings": {},
            "evidence": [],
            "warnings": [],
            "usage": {},
            "round": 0,
            "sections": [],
            "diagnostics": [],
        }.items():
            self.state.setdefault(key, default)
        # 调用用量比阶段检查点更细，恢复时取最新 usage 事件以避免预算归零。
        after = 0
        while events := store.events(task_id, after):
            for event in events:
                if event["kind"] == "usage":
                    self.state["usage"] = event["detail"]
            after = events[-1]["id"]
        self.settings = store.settings()
        self.model = model or ModelClient(
            self.settings, self.request, self.emit, self.state["usage"], audit=self.audit
        )
        self.searcher = search or ScholarSearch(self.settings)
        self.folder = store.root / "tasks" / task_id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.index = None

    def audit(self, stage, value):
        from uuid import uuid4

        folder = self.folder / "model_calls"
        folder.mkdir(exist_ok=True)
        (folder / f"{stage}-{uuid4().hex}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def emit(self, kind, stage, message, detail=None):
        self.store.event(self.task_id, kind, stage, message, detail)

    async def tool(self, name, stage, inputs, operation, summarize):
        """只保存可公开的工具参数和结果摘要，不记录凭据或原始网络响应。"""
        detail = {"call_id": uuid4().hex, "tool": name, "input": inputs, "status": "running"}
        started = time.monotonic()
        self.emit("tool", stage, f"正在执行 {name}", detail)
        try:
            result = await operation()
            output = summarize(result)
        except BaseException as exc:
            detail.update(
                status="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                elapsed_ms=round((time.monotonic() - started) * 1000),
                output={"error_type": type(exc).__name__},
            )
            self.emit("tool", stage, f"{name} 未完成，查看阶段错误与恢复入口", detail)
            raise
        detail.update(
            status="completed", elapsed_ms=round((time.monotonic() - started) * 1000), output=output
        )
        self.emit("tool", stage, f"{name} 已返回结果，详情见输出摘要", detail)
        return result

    def check(self):
        if self.cancel.is_set():
            raise Interrupted("用户已停止；可以从最近检查点继续")

    def save(self, stage, message):
        self.store.checkpoint(self.task_id, self.state, stage, message)

    async def run(self):
        graph = StateGraph(GraphState)
        for stage in STAGES:

            async def node(state, name=stage):
                self.check()
                if name not in self.state["done"]:
                    self.emit("stage", name, f"开始 {name} 阶段")
                    self.save(name, "阶段开始")
                    await getattr(self, name)()
                    self.check()
                    self.state["done"].append(name)
                    self.save(name, "阶段完成")
                return {"task_id": self.task_id}

            graph.add_node(stage, node)
        graph.add_edge(START, "search")
        graph.add_edge("search", "read")
        graph.add_edge("read", "analyse")

        def route(_):
            if self.state.pop("supplement", False):
                self.state["done"] = []
                self.save("search", "证据缺口触发下一轮检索")
                return "search"
            return "outline"

        graph.add_conditional_edges("analyse", route, {"search": "search", "outline": "outline"})
        graph.add_edge("outline", "write")
        graph.add_conditional_edges("write", route, {"search": "search", "outline": END})
        try:
            await graph.compile().ainvoke({"task_id": self.task_id}, {"recursion_limit": 30})
            self.store.status(self.task_id, "completed")
            self.emit("completed", "write", "报告已生成；语义支持仍需人工核验")
        except Interrupted as exc:
            self.save(self.store.get(self.task_id)["stage"], "已保存停止现场")
            self.store.status(self.task_id, "cancelled", str(exc))
            self.emit("cancelled", self.store.get(self.task_id)["stage"], str(exc))
        except Exception as exc:
            # 不记录 HTTP 请求/响应及密钥。已知业务错误才呈现具体信息。
            from .model import ModelError

            error = (
                str(exc)
                if isinstance(exc, (ValueError, ModelError))
                else f"{type(exc).__name__}：阶段执行失败，现场已保留"
            )
            self.save(self.store.get(self.task_id)["stage"], "已保存失败现场")
            self.store.status(self.task_id, "failed", error)
            self.emit("failed", self.store.get(self.task_id)["stage"], error)

    async def search(self):
        request = self.request
        if "plan" not in self.state:
            if request.mode == "demo":
                plan = Plan(
                    queries=[request.topic], subtopics=["证据定位", "多文献比较", "检索控制"]
                )
            else:
                plan = await self.model.json(
                    "search",
                    "制定可执行调研计划。queries 使用 2—5 个词的简洁英文查询，第一个查询只包含主题核心概念，另外两个细化方向；subtopics 中文且最多三个。",
                    request.model_dump(),
                    Plan,
                )
            self.state["plan"] = plan.model_dump()
            self.save("search", "检索计划已保存")
        queries = self.state.get("next_queries") or self.state["plan"]["queries"]
        if request.mode == "demo":
            found = fixtures.papers()[: request.max_papers]
            notes = [{"source": "synthetic", "status": "demo", "count": len(found)}]
        elif request.uploads:
            found, notes = [], []
            for upload_id in request.uploads:
                meta = json.loads(
                    (self.store.root / "uploads" / f"{upload_id}.json").read_text(encoding="utf-8")
                )
                found.append(
                    Paper(
                        id=upload_id,
                        title=meta["name"],
                        source="upload",
                        local_file=f"{upload_id}.pdf",
                    )
                )
        else:
            found, notes = await self.tool(
                "学术检索",
                "search",
                {
                    "queries": queries,
                    "sources": request.sources,
                    "years": [request.year_from, request.year_to],
                },
                lambda: self.searcher.search(queries, request),
                lambda value: {"candidates": len(value[0]), "sources": value[1]},
            )
        self.check()
        self.state["diagnostics"].extend(notes)
        for note in notes:
            self.emit(
                "source", "search", f"{note['source']}：{note['status']}，{note['count']} 篇", note
            )
        existing = [Paper.model_validate(p) for p in self.state["papers"]]
        # 补检索保留已读论文，新增候选只占剩余预算。
        merged = select(existing + found, request, queries)
        if existing:
            seen = {p.id for p in existing}
            merged = (existing + [p for p in merged if p.id not in seen])[: request.max_papers]
        self.state["papers"] = [p.model_dump() for p in merged]
        self.state["round"] += 1
        if not merged:
            raise ValueError("没有可用论文。请查看来源状态、调整检索词或上传 PDF 后创建任务。")

    async def read(self):
        if self.index is None:
            self.index = await asyncio.to_thread(
                VectorIndex, self.store.root, self.task_id, self.settings
            )
        self.state["vector_mode"] = (
            "semantic" if self.settings.embedding_provider else "lexical_hash"
        )
        for item in self.state["papers"]:
            self.check()
            paper = Paper.model_validate(item)
            if paper.id in self.state["readings"]:
                continue
            if self.request.mode != "demo" and paper.abstract:
                relevant = await self.model.json(
                    "read",
                    "判断摘要与主题和 focus 是否相关。用户明确限定的任务、模态和排除条件优先于宽泛主题相似性；主要研究对象落在排除范围时判为不相关，并说明违反的具体条件。没有明确排除条件时仅明确无关才排除。不能因为含有相同关键词就忽略用户范围。",
                    {
                        "topic": self.request.topic,
                        "focus": self.request.focus,
                        "paper": paper.model_dump(),
                    },
                    Relevance,
                )
                self.emit(
                    "relevance",
                    "read",
                    relevant.reason,
                    {"paper_id": paper.id, "relevant": relevant.relevant},
                )
                if not relevant.relevant:
                    self.state["readings"][paper.id] = {
                        "paper_id": paper.id,
                        "level": "unavailable",
                        "blocks": [],
                        "pages": 0,
                        "warnings": ["摘要筛选不相关"],
                        "analysed_blocks": [],
                    }
                    self.save("read", "摘要筛选结果已保存")
                    continue
            reading = (
                fixtures.reading(paper)
                if self.request.mode == "demo"
                else await self.tool(
                    "论文获取与 PDF 解析",
                    "read",
                    {"paper_id": paper.id, "title": paper.title},
                    lambda: read_paper(
                        paper,
                        self.folder / "papers",
                        self.store.root / "uploads",
                        self.request.fulltext_required,
                    ),
                    lambda value: {
                        "level": value.level,
                        "pages": value.pages,
                        "blocks": len(value.blocks),
                        "warnings": value.warnings,
                    },
                )
            )
            self.state["warnings"].extend(reading.warnings)
            if not reading.blocks:
                self.state["readings"][paper.id] = reading.model_dump()
                self.save("read", "材料不可读，已记录")
                continue
            await self.tool(
                "文献片段索引",
                "read",
                {
                    "paper_id": paper.id,
                    "blocks": len(reading.blocks),
                    "mode": self.state["vector_mode"],
                },
                lambda: self.index.add(paper.id, reading.blocks),
                lambda _: {"indexed_blocks": len(reading.blocks)},
            )
            # 小论文全读；大论文选首尾与检索相关块，覆盖情况显式保存。
            blocks = reading.blocks
            if sum(len(b.text) for b in blocks) > 24000:
                hits = await self.tool(
                    "相关片段检索",
                    "read",
                    {"paper_id": paper.id, "topic": self.request.topic, "limit": 18},
                    lambda: self.index.query(
                        self.request.topic
                        + " "
                        + self.request.focus
                        + " method dataset experiments results limitations",
                        18,
                        paper_id=paper.id,
                    ),
                    lambda value: {
                        "hits": len(value),
                        "block_ids": [item["block_id"] for item in value],
                    },
                )
                ranked = {h["block_id"] for h in hits if h["paper_id"] == paper.id}
                chosen = {b.id for b in blocks[:3] + blocks[-3:]} | ranked
                # 先覆盖首部和结论段，再按检索相关性补充；最后按原文顺序传给模型。
                priorities = blocks[:4] + blocks[-4:] + [b for b in blocks if b.id in chosen]
                candidates = list({b.id: b for b in priorities}.values())
                blocks, size = [], 0
                for block in candidates:
                    if size + len(block.text) > 24000:
                        break
                    blocks.append(block)
                    size += len(block.text)
                blocks.sort(key=lambda b: (b.page or 0, int(b.id.rsplit("b", 1)[-1])))
                reading.warnings.append(
                    f"全文共 {len(reading.blocks)} 块，本轮分析 {len(blocks)} 块；不代表逐段完整阅读"
                )
                self.state["warnings"].append(reading.warnings[-1])
            evidence = []
            batches, current, length = [], [], 0
            for block in blocks:
                if current and length + len(block.text) > 10000:
                    batches.append(current)
                    current, length = [], 0
                current.append(block)
                length += len(block.text)
            if current:
                batches.append(current)
            for batch in batches:
                self.check()
                if self.request.mode == "demo":
                    extracted = Extraction(
                        findings=[
                            Finding(
                                dimension="方法与局限", claim=b.text, block_id=b.id, quote=b.text
                            )
                            for b in batch
                        ]
                    )
                else:
                    extracted = await self.model.json(
                        "read",
                        "逐字段提取研究问题、方法、数据集、实验结果、局限。dimension 必须为这五个值之一，每批最多八条；claim 简明，quote 只摘取支持结论的必要原句（尽量不超过300字符）。仅有明确原文支持的字段才返回 finding；quote 应逐字匹配 block.text，可保留换行。",
                        {
                            "paper": paper.title,
                            "level": reading.level,
                            "blocks": [b.model_dump() for b in batch],
                        },
                        Extraction,
                    )
                accepted, rejected = verified_findings(
                    paper.id, batch, extracted.findings, len(evidence)
                )
                evidence.extend(accepted)
                self.state["warnings"].extend(rejected)
                reading.analysed_blocks.extend(b.id for b in batch)
            self.state["evidence"].extend(e.model_dump() for e in evidence)
            self.state["readings"][paper.id] = reading.model_dump()
            self.save("read", f"已保存《{paper.title}》：{len(evidence)} 条证据")
        if not self.state["evidence"]:
            raise ValueError("未取得通过原文匹配检查的证据，已停止生成报告")

    async def analyse(self):
        if self.request.mode == "live":
            audited = self.state.setdefault("audited_papers", [])
            for paper in self.state["papers"]:
                if paper["id"] in audited:
                    continue
                original_items = [e for e in self.state["evidence"] if e["paper_id"] == paper["id"]]
                selected = balanced_evidence(original_items)
                if not selected:
                    continue
                reading = self.state["readings"][paper["id"]]
                blocks = {b["id"]: b["text"] for b in reading["blocks"]}
                response = await self.model.json(
                    "analyse",
                    "逐条复核证据与结论。返回可支持证据的 corrections，保持 id 不变。claim 只能包含 quote 支持的内容；按 evidence.block_id 从 source_blocks 查找原文，可补全 quote 的必要上下文。无法支持的证据不返回。表格缺少明确行列对应关系时删除数字结论，不猜测。区分作者自述与客观事实，保留条件与不确定性。",
                    audit_material(paper["title"], selected, blocks),
                    EvidenceAudit,
                )
                originals = {e["id"]: e for e in selected}
                revised, seen = [], set()
                for correction in response.corrections:
                    if correction.id not in originals or correction.id in seen:
                        raise ValueError("证据复核返回未知或重复 ID")
                    seen.add(correction.id)
                    original = originals[correction.id]
                    quote = original_quote(blocks[original["block_id"]], correction.quote)
                    if quote:
                        revised.append({**original, "claim": correction.claim, "quote": quote})
                self.state["evidence"] = [
                    e for e in self.state["evidence"] if e["paper_id"] != paper["id"]
                ] + revised
                audited.append(paper["id"])
                self.emit(
                    "evidence_audit",
                    "analyse",
                    f"证据复核：保留 {len(revised)}/{len(selected)} 条",
                    {"paper_id": paper["id"]},
                )
                self.save("analyse", "逐篇证据复核已保存")
            if not self.state["evidence"]:
                raise ValueError("复核后没有足够原文支持的证据，已停止写作")
        evidence = self.state["evidence"]
        ids = {e["id"] for e in evidence}
        if self.request.mode == "demo":
            analysis = Analysis(
                claims=[Claim(text=e["claim"], evidence_ids=[e["id"]]) for e in evidence],
                gaps=["合成示例不能用于评价真实论文调研质量"],
            )
        else:
            subanalyses = []
            for topic in self.state["plan"]["subtopics"]:
                self.check()
                result = await self.model.json(
                    "analyse",
                    "围绕子主题分析研究现状、方法、共识与争议。最多八条简明结论，每条结论绑定证据；缺失信息写 gaps；提出至多两个补检索短语。",
                    {"subtopic": topic, "evidence": evidence},
                    Analysis,
                    validator=lambda result: validate_claims(result.claims, ids),
                )
                validate_claims(result.claims, ids)
                subanalyses.append({"subtopic": topic, **result.model_dump()})
            self.state["subanalyses"] = subanalyses
            analysis = await self.model.json(
                "analyse",
                "进行全局综合：研究现状、共识、争议、研究空白、时间演化与展望。不能从样本未提及推断领域不存在。不同实验设置禁止直接性能排名。",
                {"papers": self.state["papers"], "analyses": subanalyses, "evidence": evidence},
                Analysis,
                validator=lambda result: validate_claims(result.claims, ids),
            )
            validate_claims(analysis.claims, ids)
        self.state["analysis"] = analysis.model_dump()
        if (
            self.request.mode == "live"
            and analysis.followup_queries
            and self.state["round"] < self.request.max_rounds
            and not self.request.uploads
            and len(self.state["papers"]) < self.request.max_papers
        ):
            self.state["next_queries"] = analysis.followup_queries
            self.state["supplement"] = True
        elif analysis.gaps:
            self.state["warnings"].extend("证据局限：" + gap for gap in analysis.gaps)

    async def outline(self):
        ids = {e["id"] for e in self.state["evidence"]}
        if self.request.mode == "demo":
            outline = Outline(
                sections=[
                    SectionPlan(title="研究现状与代表性工作", evidence_ids=list(ids)),
                    SectionPlan(title="方法比较与研究局限", evidence_ids=list(ids)),
                ]
            )
        else:
            section_limit = min(6, max(2, len(self.state["papers"]) + 1))
            outline = await self.model.json(
                "outline",
                f"生成最多{section_limit}章的综述大纲，涵盖样本研究范围、方法比较、实验条件和局限。优先按比较问题组织，不为每篇论文各开一章；合并重复讨论的基准、方法和结论。每章绑定已有证据，缺乏证据时合并章节而非虚构。",
                {
                    "topic": self.request.topic,
                    "analysis": self.state["analysis"],
                    "evidence": self.state["evidence"],
                },
                Outline,
            )
        for section in outline.sections:
            if not set(section.evidence_ids) <= ids:
                raise ValueError("大纲引用了不存在的证据，已停止写作")
        self.state["outline"] = outline.model_dump()

    async def write(self):
        evidence = {e["id"]: e for e in self.state["evidence"]}
        for index, plan in enumerate(self.state["outline"]["sections"]):
            self.check()
            if index < len(self.state["sections"]):
                continue
            allowed = plan["evidence_ids"]
            material = [evidence[eid] for eid in allowed]
            if self.request.mode == "demo":
                section = Section(
                    paragraphs=[Claim(text=e["claim"], evidence_ids=[e["id"]]) for e in material]
                )
                reviewed = False
            else:
                data = {
                    "topic": self.request.topic,
                    "section": plan,
                    "evidence": material,
                    "papers": [
                        {k: p[k] for k in ("id", "title", "year")} for p in self.state["papers"]
                    ],
                    "corpus_coverage": [
                        {
                            "paper_id": p["id"],
                            "title": p["title"],
                            "reading_level": self.state["readings"].get(p["id"], {}).get("level"),
                            "reading_notes": self.state["readings"]
                            .get(p["id"], {})
                            .get("warnings", []),
                            "total_evidence": sum(
                                e["paper_id"] == p["id"] for e in evidence.values()
                            ),
                        }
                        for p in self.state["papers"]
                    ],
                }
                section = await self.model.json(
                    "write",
                    "按本节证据写中文综述，每节三至五段简明分析，逐段绑定 evidence_ids。正文不要手写引用编号。归纳方法与条件，不复述无法支持的数字。使用论文名称或简称标明归属；历史论文中的‘现有方法’是作者当年的判断，不能泛化为今天整个领域的现状。限定为本次样本，综合推断明确标注。避免重复复述‘所给证据未提供’，将缺口集中到局限段；不要将部分阅读未抽取到的信息写成论文没有报告。corpus_coverage 是全局阅读覆盖，evidence 仅为本节材料；某论文不在本节材料中不等于全局无证据。谈及材料不足必须限定为本节；全文第1页提取的证据不能称为仅获取摘要。被筛除的论文不是纳入研究，不应当作待补齐文献。不得把归纳解释声称为原论文提出的层级或结构。",
                    data,
                    Section,
                    validator=lambda result: validate_claims(result.paragraphs, allowed),
                )
                validate_claims(section.paragraphs, allowed)
                reviewed = False
                for revision in range(3):
                    review = await self.model.json(
                        "write",
                        "审查段落是否被所引原文支持。只报告实质性事实错误、缺少支持的断言、数值或实验设置误读、不当性能排名。允许忠实意译、明确限定的综合归纳和可直接从引文数字复算的算术事实（如比例合计）；不能仅因原文未逐字写出这些计算就判为无支持。但不能由比例合计擅自推断其统计口径。不要把措辞偏好或已限定在样本内的证据不足说明当作错误。无实质问题时 approved=true, issues=[], rejected_paragraphs=[]。有实质问题时 approved=false，issues 仅包含确实存在的问题，rejected_paragraphs 列出全部不受支持的段落下标（从0开始）；其余段落视为通过。不要在 issues 列出可接受、未见错误或不影响通过的评论。",
                        {
                            "section": section.model_dump(),
                            "evidence": material,
                            "corpus_coverage": data["corpus_coverage"],
                            "scope_rule": "检查正文范围声明：本节证据子集不得泛化为全局只有一篇论文/其他论文没有证据。全文第1页材料不等于摘要阅读。排除文献不属于纳入研究。",
                        },
                        Review,
                        validator=lambda result: validate_review(result, len(section.paragraphs)),
                    )
                    self.emit(
                        "review",
                        "write",
                        "章节审查通过" if review.approved else "章节需修改",
                        {
                            "section": index + 1,
                            "issues": review.issues,
                            "revision": revision,
                            "rejected_paragraphs": review.rejected_paragraphs,
                        },
                    )
                    if review.approved:
                        reviewed = True
                        break
                    if revision < 2:
                        section = await self.model.json(
                            "write",
                            "依据审查意见修订本节，仅保留证据支持的结论。",
                            {**data, "previous": section.model_dump(), "issues": review.issues},
                            Section,
                            validator=lambda result: validate_claims(result.paragraphs, allowed),
                        )
                        validate_claims(section.paragraphs, allowed)
                if not reviewed:
                    rejected = set(review.rejected_paragraphs)
                    if not rejected or any(i < 0 or i >= len(section.paragraphs) for i in rejected):
                        raise ValueError("章节审查未通过且无法定位问题段落，已保留此前章节")
                    kept = [p for i, p in enumerate(section.paragraphs) if i not in rejected]
                    if not kept:
                        if await self.supplement_writing(plan, review):
                            return
                        raise ValueError("本节全部段落未通过证据审查，已保留此前章节")
                    section = Section(paragraphs=kept)
                    reviewed = True
                    self.state["warnings"].append(
                        f"《{plan['title']}》两轮修订后移除 {len(rejected)} 个未通过支持性审查的段落"
                    )
            validate_claims(section.paragraphs, allowed)
            self.state["sections"].append(
                {"title": plan["title"], **section.model_dump(), "model_reviewed": reviewed}
            )
            self.save("write", f"第 {index + 1} 节写作完成")
        self.state["report"] = render_report(self.request, self.state)
        (self.folder / "report.md").write_text(self.state["report"], encoding="utf-8")
        (self.folder / "report.json").write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def supplement_writing(self, plan, review):
        if (
            self.request.uploads
            or self.state["round"] >= self.request.max_rounds
            or len(self.state["papers"]) >= self.request.max_papers
        ):
            return False
        search_plan = await self.model.json(
            "search",
            "本节因缺乏证据未能通过写作审查。给出最多两个简洁英文补检索词，针对具体证据缺口；不能只重复原主题。",
            {"topic": self.request.topic, "section": plan["title"], "issues": review.issues},
            Plan,
        )
        self.state["next_queries"] = search_plan.queries[:2]
        self.state["supplement"] = True
        self.state.setdefault("previous_drafts", []).append(self.state["sections"])
        self.state["sections"] = []
        self.emit("supplement", "write", "本节证据不足，在剩余预算内补检索后重建大纲与报告")
        return True


def safe(value):
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def render_report(request, state):
    lines = [
        f"# {safe(request.topic)}",
        "",
        "合成演示：不代表真实文献或模型质量。"
        if request.mode == "demo"
        else "基于实际获取材料的调研初稿；证据语义支持性尚待人工核验。",
        "",
    ]
    lines += [
        "## 摘要",
        "",
        f"本次围绕“{safe(request.topic)}”开展文献调研，检索得到 {len(state['papers'])} 篇候选文献，形成 {len(state['evidence'])} 条可追溯证据。下文按方法、实验条件和局限组织样本分析；阅读覆盖与来源状态另行列明。",
        "",
    ]
    for claim in state.get("analysis", {}).get("claims", [])[:2]:
        lines += [
            safe(claim["text"]) + " " + " ".join(f"[{eid}]" for eid in claim["evidence_ids"]),
            "",
        ]
    lines += [
        "关键词：" + "；".join(safe(t) for t in state.get("plan", {}).get("subtopics", [])[:5]),
        "",
    ]
    lines += [
        "## 调研范围与来源",
        "",
        f"- 调研要求：{safe(request.focus) or '按主题开展调研'}",
        f"- 年份范围：{request.year_from}—{request.year_to}；候选上限：{request.max_papers} 篇。",
        "- 文中实验数据来自论文原文，不代表本系统复现实验或下载了原始数据集。",
    ]
    for note in state.get("diagnostics", []):
        lines.append(
            f"- 检索来源 {safe(note.get('source', '未知'))}：{safe(note.get('status', '未知'))}，返回 {note.get('count', 0)} 条；查询：{safe(note.get('query', '未记录'))}。"
        )
    excluded = [
        p
        for p in state["papers"]
        if "摘要筛选不相关" in state["readings"].get(p["id"], {}).get("warnings", [])
    ]
    if excluded:
        lines += ["- 筛除文献（不参与方法比较）：" + "；".join(safe(p["title"]) for p in excluded)]
    lines.append("")
    for section in state["sections"]:
        lines += ["## " + safe(section["title"]), ""]
        for claim in section["paragraphs"]:
            lines += [
                safe(claim["text"]) + " " + " ".join(f"[{eid}]" for eid in claim["evidence_ids"]),
                "",
            ]
    lines += [
        "## 文献比较",
        "",
        "| 文献 | 年份 | 阅读层级 | 已分析块/全部块 |",
        "|---|---|---|---|",
    ]
    for paper in state["papers"]:
        reading = state["readings"].get(paper["id"], {})
        lines.append(
            f"| {safe(paper['title'])} | {paper['year'] or '未知'} | {reading.get('level', 'unavailable')} | {len(reading.get('analysed_blocks', []))}/{len(reading.get('blocks', []))} |"
        )
    lines += [
        "",
        "### 研究方法与实验条件",
        "",
        "| 文献 | 方法 | 数据集 | 实验结果 | 局限 |",
        "|---|---|---|---|---|",
    ]
    for paper in state["papers"]:
        items = [e for e in state["evidence"] if e["paper_id"] == paper["id"]]
        if not items:
            continue
        cells = []
        for dimension in ("方法", "数据集", "结果", "局限"):
            findings = [e for e in items if dimension in e["dimension"]][:2]
            cells.append(
                "；".join(safe(e["claim"]) + f" [{e['id']}]" for e in findings) or "当前证据未提取"
            )
        lines.append("| " + safe(paper["title"]) + " | " + " | ".join(cells) + " |")
    lines += ["", "不同数据集、指标与设置下的数字不作直接排名。", "", "## 证据索引", ""]
    for e in state["evidence"]:
        location = f"第 {e['page']} 页" if e.get("page") else "摘要/示例段落"
        lines += [
            f"- **[{e['id']}]** {e['paper_id']} · {location} · {safe(e['dimension'])}：{safe(e['quote'])}"
        ]
    lines += [
        "",
        "## 结论与展望",
        "",
        "以下归纳限于本次获取的材料，不代表对整个领域的穷尽检索。",
        "",
    ]
    for claim in state.get("analysis", {}).get("claims", [])[-3:]:
        lines += [
            safe(claim["text"]) + " " + " ".join(f"[{eid}]" for eid in claim["evidence_ids"]),
            "",
        ]
    for gap in state.get("analysis", {}).get("gaps", [])[:4]:
        lines += ["- 后续需核验或补充：" + safe(gap)]
    lines += ["", "## 参考文献", ""]
    for paper in state["papers"]:
        lines.append(
            f"- {safe(paper['title'])} ({paper['year'] or '年份未知'}). {safe(paper['url'])} DOI: {safe(paper['doi']) or '未提供'}"
        )
    lines += [
        "",
        "## 局限与运行说明",
        "",
        "- 原文匹配通过不等于语义正确；模型审查不替代人工评测。",
        "- 全文为文本提取结果，未解析图表或扫描件；跨论文实验条件须人工复核。",
    ]
    lines += ["- " + safe(w) for w in dict.fromkeys(state["warnings"])]
    return "\n".join(lines)
