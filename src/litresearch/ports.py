"""成员一实现模型端口，成员二实现文献工具端口。"""

from typing import Protocol

from .models import Document, Finding, PaperRecord, ResearchRequest, SearchPlan


class ModelPort(Protocol):
    def plan(self, request: ResearchRequest) -> SearchPlan: ...

    def extract(self, paper: PaperRecord, document: Document) -> list[Finding]: ...


class LiteraturePort(Protocol):
    def search(self, query: str, limit: int) -> list[PaperRecord]: ...

    def read(self, paper: PaperRecord) -> Document: ...
