import asyncio

import pytest

from litresearch.workbench.engine import Engine
from litresearch.workbench.schemas import Request
from litresearch.workbench.store import Store


def test_tool_trace_preserves_result_and_failure_without_secret(tmp_path):
    store = Store(tmp_path)
    tid = store.create(Request(topic="工具调用验收"))
    engine = Engine(store, tid)

    async def success():
        return ["paper1", "paper2"]

    result = asyncio.run(
        engine.tool("检索", "search", {"query": "test"}, success, lambda r: {"count": len(r)})
    )
    assert len(result) == 2
    records = [e["detail"] for e in store.events(tid) if e["kind"] == "tool"]
    assert [r["status"] for r in records] == ["running", "completed"]
    assert records[0]["call_id"] == records[1]["call_id"]
    assert records[1]["output"] == {"count": 2}
    assert records[1]["elapsed_ms"] >= 0

    async def failure():
        raise RuntimeError("private-provider-key")

    with pytest.raises(RuntimeError):
        asyncio.run(engine.tool("解析", "read", {}, failure, lambda r: r))
    records = store.events(tid)
    assert records[-1]["detail"]["status"] == "failed"
    assert "private-provider-key" not in str(records)
