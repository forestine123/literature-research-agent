"""工作台领域契约。模型返回必须经过同样的校验。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

STAGES = ("search", "read", "analyse", "outline", "write")
Source = Literal["arxiv", "openalex", "semantic_scholar"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Request(Record):
    session_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    topic: str = Field(min_length=2, max_length=500)
    focus: str = Field(default="", max_length=2000)
    mode: Literal["demo", "live"] = "demo"
    sources: list[Source] = Field(
        default_factory=lambda: ["arxiv", "openalex", "semantic_scholar"], min_length=1
    )
    year_from: int = Field(default=2017, ge=1900, le=2100)
    year_to: int = Field(default=2026, ge=1900, le=2100)
    max_papers: int = Field(default=5, ge=1, le=10)
    exclude: list[str] = Field(default_factory=list, max_length=20)
    max_rounds: int = Field(default=2, ge=1, le=3)
    max_calls: int = Field(default=80, ge=5, le=200)
    token_budget: int = Field(default=300000, ge=1000, le=1000000)
    fulltext_required: bool = False
    uploads: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def years(self):
        if self.year_from > self.year_to:
            raise ValueError("起始年份不得晚于结束年份")
        return self


class Provider(Record):
    name: str = Field(default="默认服务", min_length=1, max_length=80)
    backend: Literal["openai", "openai_compat", "anthropic", "anthropic_compat"] = "openai_compat"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    json_mode: bool = True
    max_output_tokens: int = Field(default=4096, ge=256, le=16384)
    timeout: int = Field(default=90, ge=5, le=180)
    thinking: Literal["auto", "enabled", "disabled"] = "auto"


class Settings(Record):
    providers: dict[str, Provider] = Field(default_factory=lambda: {"default": Provider()})
    agents: dict[str, str] = Field(default_factory=lambda: dict.fromkeys(STAGES, "default"))
    fallbacks: dict[str, str] = Field(default_factory=dict)
    openalex_key: str = ""
    semantic_scholar_key: str = ""
    embedding_provider: str = ""
    embedding_model: str = ""

    @model_validator(mode="after")
    def references(self):
        for stage in STAGES:
            if self.agents.get(stage) not in self.providers:
                raise ValueError(f"{stage} 的 Provider 不存在")
        for stage, provider in self.fallbacks.items():
            if stage not in STAGES or provider not in self.providers:
                raise ValueError("回退配置无效")
        if self.embedding_provider and self.embedding_provider not in self.providers:
            raise ValueError("Embedding Provider 不存在")
        return self


class Plan(Record):
    queries: list[str] = Field(min_length=1, max_length=3)
    subtopics: list[str] = Field(min_length=1, max_length=5)
    dimensions: list[str] = Field(
        default_factory=lambda: ["研究问题", "方法", "数据集", "实验结果", "局限"]
    )


class Paper(Record):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str = ""
    source: str
    sources: list[str] = Field(default_factory=list)
    url: str = ""
    pdf_url: str = ""
    abstract: str = ""
    score: float = 0
    local_file: str = ""


class Block(Record):
    id: str
    text: str
    page: int | None = None


class Reading(Record):
    paper_id: str
    level: Literal["synthetic", "abstract", "fulltext", "unavailable"]
    blocks: list[Block]
    pages: int = 0
    warnings: list[str] = Field(default_factory=list)
    analysed_blocks: list[str] = Field(default_factory=list)


class Finding(Record):
    dimension: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    block_id: str
    quote: str = Field(min_length=8, max_length=1500)


class Extraction(Record):
    findings: list[Finding] = Field(max_length=20)


class Relevance(Record):
    relevant: bool
    reason: str


class Evidence(Finding):
    id: str
    paper_id: str
    page: int | None = None


class Claim(Record):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class Analysis(Record):
    claims: list[Claim] = Field(max_length=30)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    followup_queries: list[str] = Field(default_factory=list, max_length=2)


class SectionPlan(Record):
    title: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)


class Outline(Record):
    sections: list[SectionPlan] = Field(min_length=1, max_length=6)


class Section(Record):
    paragraphs: list[Claim] = Field(min_length=1, max_length=12)


class Review(Record):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    rejected_paragraphs: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent_verdict(self):
        if self.approved and (self.issues or self.rejected_paragraphs):
            raise ValueError("审查通过时 issues 和 rejected_paragraphs 必须为空")
        if not self.approved and (not self.issues or not self.rejected_paragraphs):
            raise ValueError(
                "审查不通过必须提供实质问题及对应段落下标；若无不受支持段落，应返回 approved=true 且清空 issues"
            )
        if any(i < 0 for i in self.rejected_paragraphs):
            raise ValueError("段落下标从 0 开始，不得为负数")
        return self


class EvidenceCorrection(Record):
    id: str
    claim: str = Field(min_length=1)
    quote: str = Field(min_length=8, max_length=2000)


class EvidenceAudit(Record):
    corrections: list[EvidenceCorrection]


class Probe(Record):
    ok: bool


class ConversationName(Record):
    title: str = Field(min_length=1, max_length=160)


class ChatInput(Record):
    content: str = Field(min_length=1, max_length=4000)
    task_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ChatAnswer(Record):
    answer: str = Field(min_length=1, max_length=12000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
