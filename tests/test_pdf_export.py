import pymupdf
from fastapi.testclient import TestClient

from litresearch.workbench.api import create_app
from litresearch.workbench.schemas import Request
from litresearch.workbench.store import Store


def test_pdf_export_navigation_and_safe_text(tmp_path):
    store = Store(tmp_path)
    tid = store.create(Request(topic="论文导出测试"))
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/api/tasks/{tid}/export/pdf").status_code == 409
        store.checkpoint(
            tid,
            {
                "report": "# 标题\n\n## 摘要\n\n原文 <script> 不执行。\n\n## 结论\n\n有依据的结论。",
                "papers": [],
                "evidence": [],
            },
            "write",
        )
        store.status(tid, "completed")
        response = client.get(f"/api/tasks/{tid}/export/pdf")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        assert "attachment" in response.headers["content-disposition"]
        doc = pymupdf.open(stream=response.content, filetype="pdf")
        assert len(doc) >= 3
        assert len(doc.get_toc()) == 2
        assert all(
            page.rect.width == 595.2755737304688 or 595 < page.rect.width < 596 for page in doc
        )
