"""对已保存任务做确定性验收；不调用模型，不将引用存在性等同于语义准确性。"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from litresearch.workbench.store import Store


def audit(task, events):
    state = task["state"]
    evidence = state.get("evidence", [])
    ids = {e["id"] for e in evidence}
    errors = []
    if len(ids) != len(evidence):
        errors.append("证据 ID 重复")
    located = 0
    for item in evidence:
        reading = state.get("readings", {}).get(item["paper_id"], {})
        blocks = {b["id"]: b for b in reading.get("blocks", [])}
        block = blocks.get(item["block_id"])
        if block and item["quote"] and item["quote"] in block["text"]:
            located += 1
            if item.get("page") != block.get("page"):
                errors.append(f"{item['id']} 页码不一致")
        else:
            errors.append(f"{item['id']} 原文无法定位")
    paragraphs = [p for s in state.get("sections", []) for p in s["paragraphs"]]
    cited = set()
    for index, paragraph in enumerate(paragraphs):
        refs = set(paragraph["evidence_ids"])
        cited.update(refs)
        if not refs or refs - ids:
            errors.append(f"段落 {index + 1} 无引用或包含未知引用")
    if task["status"] != "completed" or not state.get("report") or not paragraphs:
        errors.append("任务未完成或没有报告正文")
    papers = []
    for paper in state.get("papers", []):
        reading = state.get("readings", {}).get(paper["id"], {})
        papers.append(
            {
                "title": paper["title"],
                "url": paper["url"],
                "level": reading.get("level"),
                "pages": reading.get("pages", 0),
                "blocks": len(reading.get("blocks", [])),
                "analysed_blocks": len(reading.get("analysed_blocks", [])),
                "evidence": sum(e["paper_id"] == paper["id"] for e in evidence),
            }
        )
    meters = state.get("usage", {})
    completed_at = state.get("editorial_review", {}).get("original_completed_at", task["updated"])
    return {
        "task_id": task["id"],
        "status": task["status"],
        "created": task["created"],
        "updated": task["updated"],
        "workflow_completed_at": completed_at,
        "elapsed_seconds": round(
            (
                datetime.fromisoformat(completed_at) - datetime.fromisoformat(task["created"])
            ).total_seconds(),
            1,
        ),
        "papers": papers,
        "sections": len(state.get("sections", [])),
        "paragraphs": len(paragraphs),
        "evidence": len(evidence),
        "source_present": located,
        "cited_evidence": len(cited),
        "calls": sum(m["calls"] for m in meters.values()),
        "tokens": sum(m["input_tokens"] + m["output_tokens"] for m in meters.values()),
        "usage_by_stage": meters,
        "retries": [e["message"] for e in events if e["kind"] == "retry"],
        "reviews": [e["detail"] for e in events if e["kind"] == "review"],
        "warnings": list(dict.fromkeys(state.get("warnings", []))),
        "errors": errors,
        "scope": "确定性引用与完整性检查；语义支持性需另行逐条核验。",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    store = Store(args.data)
    task = store.get(args.task_id)
    events, cursor = [], 0
    while batch := store.events(args.task_id, cursor):
        events.extend(batch)
        cursor = batch[-1]["id"]
    result = audit(task, events)
    path = args.data / "tasks" / args.task_id / "acceptance.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
