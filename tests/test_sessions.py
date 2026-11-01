import asyncio

import pytest
from fastapi.testclient import TestClient

from litresearch.workbench.api import create_app
from litresearch.workbench.conversation import conversation_context, reply
from litresearch.workbench.model import ModelClient
from litresearch.workbench.schemas import ChatAnswer, Request
from litresearch.workbench.store import Store


def test_migration_versions_and_recovery(tmp_path):
    store = Store(tmp_path)
    first = store.create(Request(topic="旧调研"))
    with store.connect() as db:
        db.execute("DELETE FROM task_sessions")
        db.execute("DELETE FROM sessions")
    store = Store(tmp_path)
    assert store.get(first)["session_id"] == first
    second = store.create(Request(topic="追加调研", session_id=first))
    store.rename_session(first, "持续研究")
    store = Store(tmp_path)
    assert len(store.sessions()) == 1
    assert len(store.session(first)["tasks"]) == 2
    message = store.begin_chat(first, second, "解释结论")
    with pytest.raises(ValueError):
        store.begin_chat(first, second, "重复提交")
    assert len(store.session(first)["messages"]) == 2
    store.reconcile()
    assert store.session(first)["messages"][-1]["status"] == "failed"
    store.finish_chat(message, "已恢复", ["e1"])
    assert Store(tmp_path).session(first)["messages"][-1]["evidence_ids"] == ["e1"]


def test_chat_context_and_citation_validation(tmp_path, monkeypatch):
    store = Store(tmp_path)
    tid = store.create(Request(topic="真实材料", mode="live"))
    store.checkpoint(tid, {"evidence": [{"id": "e1", "quote": "原文"}]}, "analyse")
    previous = store.begin_chat(tid, tid, "之前的问题")
    store.finish_chat(previous, "之前的回答", ["e1"])
    current = store.begin_chat(tid, tid, "继续解释")

    async def fake_json(self, stage, prompt, context, schema, validator=None):
        assert context["history"][-1]["content"] == "之前的回答"
        assert context["question"] == "继续解释"
        with pytest.raises(ValueError):
            validator(ChatAnswer(answer="虚构", evidence_ids=["missing"]))
        result = ChatAnswer(answer="基于原文解释", evidence_ids=["e1"])
        validator(result)
        return result

    monkeypatch.setattr(ModelClient, "json", fake_json)
    asyncio.run(reply(store, tid, tid, current, "继续解释"))
    assert store.session(tid)["messages"][-1]["content"] == "基于原文解释"
    messages = [{"status": "completed", "role": "user", "content": "问题", "task_id": tid}] * 20
    assert len(conversation_context(store.get(tid), messages, "追问")["history"]) == 12


def test_session_api_isolation_and_pdf(tmp_path):
    store = Store(tmp_path)
    first = store.create(Request(topic="第一会话"))
    second = store.create(Request(topic="第二会话"))
    paper = "a" * 16
    store.checkpoint(first, {"papers": [{"id": paper}]}, "read")
    folder = tmp_path / "tasks" / first / "papers"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{paper}.pdf").write_bytes(b"%PDF-1.4\n")
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get("/api/sessions").json()) == 2
        assert client.put(f"/api/sessions/{first}", json={"title": "新名称"}).status_code == 200
        assert (
            client.post(
                f"/api/sessions/{first}/messages", json={"task_id": second, "content": "跨会话"}
            ).status_code
            == 400
        )
        assert client.get(f"/api/tasks/{first}/papers/{paper}/pdf").content.startswith(b"%PDF")
        assert client.get(f"/api/tasks/{second}/papers/{paper}/pdf").status_code == 404
