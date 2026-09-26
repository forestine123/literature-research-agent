"""跨模块数据契约；证据存在性与语义支持性分开处理。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchRequest(Record):
    topic: str = Field(min_length=1, max_length=500)
    max_papers: int = Field(default=3, ge=1, le=10)
    max_search_rounds: int = Field(default=3, ge=1, le=3)


class SearchPlan(Record):
    queries: list[str] = Field(min_length=1, max_length=3)

    @field_validator("queries")
    @classmethod
    def nonempty_queries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("检索词不能为空")
        return [value.strip() for value in values]


class PaperRecord(Record):
    paper_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    doi: str | None = None
    content_level: Literal["synthetic", "abstract", "fulltext", "unavailable"]


class TextBlock(Record):
    block_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class Document(Record):
    paper_id: str
    blocks: list[TextBlock]

    @field_validator("blocks")
    @classmethod
    def unique_blocks(cls, blocks: list[TextBlock]) -> list[TextBlock]:
        ids = [block.block_id for block in blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("同一文档不能包含重复block_id")
        return blocks


class Finding(Record):
    paper_id: str
    dimension: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class ResearchReport(Record):
    topic: str
    mode: Literal["demo", "live"]
    papers: list[PaperRecord]
    findings: list[Finding]
    warnings: list[str]
    events: list[str]
    search_rounds: int
    semantic_verification: Literal["not_performed"] = "not_performed"
