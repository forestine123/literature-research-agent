"""自建合成材料与确定性适配器，不联网，不代表真实论文或模型效果。"""

from .models import Document, Finding, PaperRecord, ResearchRequest, SearchPlan, TextBlock


class DemoLiterature:
    def __init__(self) -> None:
        samples = [
            ("逐篇记录示例", "逐篇记录研究问题，再进行主题归类。", "本例未测试自动检索。"),
            ("证据定位示例", "为分析内容保留原文片段和段落编号。", "片段存在不能证明结论正确。"),
            ("条件比较示例", "先检查实验条件，再判断结果是否可以比较。", "本例没有真实实验数据。"),
        ]
        self.papers: list[PaperRecord] = []
        self.documents: dict[str, Document] = {}
        for index, (title, method, limitation) in enumerate(samples, 1):
            paper_id = f"demo-{index}"
            self.papers.append(
                PaperRecord(
                    paper_id=paper_id,
                    title=f"合成材料：{title}",
                    source="local-synthetic",
                    content_level="synthetic",
                )
            )
            self.documents[paper_id] = Document(
                paper_id=paper_id,
                blocks=[
                    TextBlock(block_id="method", text=method),
                    TextBlock(block_id="limitation", text=limitation),
                ],
            )

    def search(self, query: str, limit: int) -> list[PaperRecord]:
        # 固定返回用于验证编排，不能用于评价检索相关性。
        return self.papers[:limit]

    def read(self, paper: PaperRecord) -> Document:
        return self.documents[paper.paper_id]


class DemoModel:
    def plan(self, request: ResearchRequest) -> SearchPlan:
        return SearchPlan(queries=[request.topic, f"{request.topic} 方法", f"{request.topic} 局限"])

    def extract(self, paper: PaperRecord, document: Document) -> list[Finding]:
        names = {"method": "方法", "limitation": "局限"}
        return [
            Finding(
                paper_id=paper.paper_id,
                dimension=names.get(block.block_id, "内容"),
                claim=block.text,
                block_id=block.block_id,
                quote=block.text,
            )
            for block in document.blocks
        ]
