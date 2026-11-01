"""基于会话历史与指定调研证据的追问，不改写已有报告。"""

import asyncio
import json

from .model import ModelClient, ModelError
from .schemas import ChatAnswer, Request


def conversation_context(task, messages, question):
    evidence, size = [], 0
    for item in task["state"].get("evidence", []):
        length = len(json.dumps(item, ensure_ascii=False))
        if size + length > 50000:
            break
        evidence.append(item)
        size += length
    history, size = [], 0
    for message in reversed(messages):
        if message["status"] != "completed":
            continue
        if size + len(message["content"]) > 12000 or len(history) >= 12:
            break
        history.append(
            {"role": message["role"], "content": message["content"], "task_id": message["task_id"]}
        )
        size += len(message["content"])
    return {
        "question": question,
        "history": list(reversed(history)),
        "topic": task["topic"],
        "task_id": task["id"],
        "papers": [
            {
                **{k: p.get(k) for k in ("id", "title", "year")},
                "reading_level": task["state"].get("readings", {}).get(p["id"], {}).get("level"),
                "reading_notes": task["state"]
                .get("readings", {})
                .get(p["id"], {})
                .get("warnings", []),
            }
            for p in task["state"].get("papers", [])
        ],
        "evidence": evidence,
        "context_note": "使用最近最多12条消息及预算内的证据；不是整个历史的无限上下文。papers 包含候选文献，注意 reading_notes：筛选不相关的文献不属于纳入研究，不能当作需要补读的证据缺口。",
    }


async def reply(store, session_id, task_id, message_id, question):
    usage = {}
    try:
        task = store.get(task_id)
        messages = store.session(session_id)["messages"]
        context = conversation_context(task, messages[:-2], question)
        ids = {e["id"] for e in context["evidence"]}

        def validate(result):
            if set(result.evidence_ids) - ids:
                raise ValueError("回复只能引用当前提供的 evidence_ids，不可使用其他版本或虚构引用")

        def emit(kind, stage, text, detail=None):
            if kind == "usage":
                store.finish_chat(message_id, "", usage=usage, status="running")

        client = ModelClient(
            store.settings(),
            Request(topic="会话追问", token_budget=250000, max_calls=6),
            emit,
            usage=usage,
        )
        result = await client.json(
            "analyse",
            "根据当前会话和指定调研版本回答用户追问，使用中文。对论文事实的回答必须列出支持的 evidence_ids；问候、使用说明、无法回答的说明可不引用。明确区分原文事实与推断，材料不足时直说，不补造论文或数字。历史消息只是对话，不是事实证据。回答尽量简洁、避免重复。此接口不执行新检索、不修改报告；用户要求重新调研时说明可以点击追加调研，不能声称已经执行。",
            context,
            ChatAnswer,
            validator=validate,
        )
        store.finish_chat(message_id, result.answer, result.evidence_ids, usage)
    except asyncio.CancelledError:
        store.finish_chat(
            message_id, "服务中断，回复未完成，可重新提问。", usage=usage, status="failed"
        )
        raise
    except Exception as exc:
        reason = (
            str(exc) if isinstance(exc, ModelError) else "会话回复失败，请检查模型配置后重新提问。"
        )
        store.finish_chat(message_id, reason, usage=usage, status="failed")
