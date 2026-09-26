"""只验证证据属于原文；不将字符串匹配误称为语义核验。"""

from .models import Document, Finding


def evidence_error(finding: Finding, documents: dict[str, Document]) -> str | None:
    document = documents.get(finding.paper_id)
    if document is None or document.paper_id != finding.paper_id:
        return "未找到对应文档"
    block = next((item for item in document.blocks if item.block_id == finding.block_id), None)
    if block is None:
        return "未找到对应段落"
    if finding.quote not in block.text:
        return "证据片段不在原文段落中"
    return None
