"""显式联网验收：使用本地已配置模型，会产生 API 用量。"""

import argparse
import asyncio
import json
from pathlib import Path

from litresearch.workbench.engine import Engine
from litresearch.workbench.schemas import Request
from litresearch.workbench.store import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="Retrieval augmented generation factuality evaluation")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--mode", choices=["live", "demo"], default="live")
    args = parser.parse_args()
    store = Store(Path("data"))
    request = Request(
        topic=args.topic, mode=args.mode, sources=["arxiv"], max_papers=args.count, max_rounds=1
    )
    task_id = store.create(request)
    store.claim(task_id)
    print("TASK", task_id, flush=True)
    engine = Engine(store, task_id)
    original = engine.emit

    def emit(kind, stage, message, detail=None):
        original(kind, stage, message, detail)
        if kind != "usage":
            print(stage, kind, message, flush=True)

    engine.emit = emit
    await engine.run()
    task = store.get(task_id)
    print(
        json.dumps(
            {
                "id": task_id,
                "status": task["status"],
                "error": task["error"],
                "papers": len(task["state"].get("papers", [])),
                "evidence": len(task["state"].get("evidence", [])),
                "usage": task["state"].get("usage", {}),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if task["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
