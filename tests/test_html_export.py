from litresearch.workbench.exporting import report_html


def test_offline_html_has_toc_table_and_escapes_untrusted_markup():
    result = report_html(
        "<script>alert(1)</script>",
        "# 标题\n\n## 摘要\n\n<script>alert(1)</script>\n\n| 文献 | 数据 |\n|---|---|\n| A | 12 |",
    )
    assert "<script>" not in result
    assert "<table>" in result
    assert 'href="#section-2"' in result
    assert 'id="section-2"' in result
    assert "@media print" in result
    assert "<script src=" not in result


def test_html_download_requires_completed_task(tmp_path):
    from fastapi.testclient import TestClient

    from litresearch.workbench.api import create_app
    from litresearch.workbench.schemas import Request
    from litresearch.workbench.store import Store

    store = Store(tmp_path)
    tid = store.create(Request(topic="导出测试"))
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f"/api/tasks/{tid}/export/html").status_code == 409
        store.checkpoint(tid, {"report": "# 报告\n\n## 摘要\n\n测试"}, "write")
        store.status(tid, "completed")
        response = client.get(f"/api/tasks/{tid}/export/html")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert "目录" in response.text
