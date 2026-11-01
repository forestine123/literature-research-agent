"""单用户本地 FastAPI 工作台。以单 worker 运行。"""

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi import Request as HTTPRequest
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .conversation import reply
from .engine import Engine
from .model import ModelClient, ModelError
from .reading import MAX_BYTES
from .schemas import STAGES, ChatInput, ConversationName, Probe, Request, Settings
from .store import Store
from .vectors import VectorIndex


def create_app(root=None):
    root = Path(root or os.environ.get("LITRESEARCH_DATA", "data"))
    store = Store(root)
    running, cancels = {}, {}
    chats = {}

    @asynccontextmanager
    async def lifespan(app):
        store.reconcile()
        yield
        for signal in cancels.values():
            signal.set()
        tasks = list(running.values()) + list(chats.values())
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    app = FastAPI(title="文献调研工作台", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_origin(request: HTTPRequest, call_next):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "仅允许本地同源工作台请求"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def task(task_id):
        if not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise HTTPException(404, "任务不存在")
        try:
            return store.get(task_id)
        except KeyError:
            raise HTTPException(404, "任务不存在") from None

    def launch(task_id):
        if task_id in running or not store.claim(task_id):
            raise HTTPException(409, "任务正在运行或已经完成")
        signal = asyncio.Event()
        cancels[task_id] = signal
        engine = Engine(store, task_id, signal)
        background = asyncio.create_task(engine.run())
        running[task_id] = background

        def finished(_):
            running.pop(task_id, None)
            cancels.pop(task_id, None)

        background.add_done_callback(finished)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.2.0", "stages": STAGES}

    @app.get("/api/settings")
    def settings():
        return store.public_settings()

    @app.put("/api/settings")
    def update_settings(value: Settings):
        old = store.settings()
        for name, provider in value.providers.items():
            if provider.api_key == "********":
                previous = old.providers.get(name)
                if (
                    not previous
                    or previous.base_url != provider.base_url
                    or previous.backend != provider.backend
                ):
                    raise HTTPException(400, "更改服务地址或协议后请重新输入密钥")
                provider.api_key = previous.api_key
        for key in ("openalex_key", "semantic_scholar_key"):
            if getattr(value, key) == "********":
                setattr(value, key, getattr(old, key))
        store.save_settings(value)
        return store.public_settings()

    @app.post("/api/settings/test/{provider_id}")
    async def test_provider(provider_id: str):
        config = store.settings()
        if provider_id not in config.providers:
            raise HTTPException(404, "Provider 不存在")
        config.agents["search"] = provider_id
        config.fallbacks = {}
        model = ModelClient(config, Request(topic="连通性测试"), lambda *args: None)
        try:
            result = await model.json("search", '仅返回 {"ok": true}。', {}, Probe)
            return {"ok": result.ok, "usage": model.usage}
        except ModelError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/tasks")
    def tasks():
        return store.list()

    def session(session_id):
        if not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise HTTPException(404, "会话不存在")
        try:
            return store.session(session_id)
        except KeyError:
            raise HTTPException(404, "会话不存在") from None

    @app.get("/api/sessions")
    def sessions():
        return store.sessions()

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        return session(session_id)

    @app.put("/api/sessions/{session_id}")
    def rename_session(session_id: str, value: ConversationName):
        session(session_id)
        store.rename_session(session_id, value.title)
        return session(session_id)

    @app.post("/api/sessions/{session_id}/messages", status_code=202)
    async def send_message(session_id: str, value: ChatInput):
        session(session_id)
        current = task(value.task_id)
        if current["session_id"] != session_id:
            raise HTTPException(400, "此调研不属于当前会话")
        if current["request"]["mode"] == "demo":
            raise HTTPException(400, "合成演示不调用模型，请在真实调研会话中追问")
        try:
            message_id = store.begin_chat(session_id, value.task_id, value.content)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        background = asyncio.create_task(
            reply(store, session_id, value.task_id, message_id, value.content)
        )
        chats[session_id] = background
        background.add_done_callback(lambda _: chats.pop(session_id, None))
        return {"id": message_id}

    @app.post("/api/tasks", status_code=201)
    async def create(request: Request):
        if request.session_id:
            session(request.session_id)
        for upload in request.uploads:
            if (
                not re.fullmatch(r"[a-f0-9]{32}", upload)
                or not (root / "uploads" / f"{upload}.pdf").exists()
            ):
                raise HTTPException(400, "上传文件不存在")
        if request.mode == "live":
            config = store.settings()
            missing = [s for s in STAGES if not config.providers[config.agents[s]].model]
            if missing:
                raise HTTPException(400, "请先在模型设置中填写各阶段模型并测试连通性")
        task_id = store.create(request)
        launch(task_id)
        return {"id": task_id}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        return task(task_id)

    @app.post("/api/tasks/{task_id}/resume")
    async def resume(task_id: str):
        task(task_id)
        launch(task_id)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel(task_id: str):
        current = task(task_id)
        signal = cancels.get(task_id)
        if not signal:
            raise HTTPException(409, "任务当前未运行")
        signal.set()
        store.status(task_id, "cancelling")
        store.event(task_id, "cancelling", current["stage"], "将在当前工具调用结束后停止")
        return {"ok": True}

    @app.get("/api/tasks/{task_id}/papers/{paper_id}/pdf")
    def paper_pdf(task_id: str, paper_id: str):
        current = task(task_id)
        paper = next((p for p in current["state"].get("papers", []) if p["id"] == paper_id), None)
        if not paper or not re.fullmatch(r"[a-f0-9]{16,32}", paper_id):
            raise HTTPException(404, "论文不存在")
        if paper.get("local_file"):
            filename = paper["local_file"]
            if not re.fullmatch(r"[a-f0-9]{32}\.pdf", filename):
                raise HTTPException(404, "论文文件无效")
            path = root / "uploads" / filename
        else:
            path = root / "tasks" / task_id / "papers" / f"{paper_id}.pdf"
        if not path.is_file():
            raise HTTPException(404, "没有本地全文，请打开原始来源")
        return FileResponse(
            path, media_type="application/pdf", headers={"Content-Disposition": "inline"}
        )

    @app.get("/api/tasks/{task_id}/events")
    async def events(task_id: str, request: HTTPRequest, after: int = 0):
        task(task_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "无效事件游标") from None

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                rows = store.events(task_id, cursor)
                for event in rows:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                status = store.get(task_id)["status"]
                if (
                    status in ("completed", "failed", "interrupted", "cancelled")
                    and len(rows) < 300
                ):
                    yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.get("/api/tasks/{task_id}/export/{format}")
    def export(task_id: str, format: str):
        current = task(task_id)
        if current["status"] != "completed":
            raise HTTPException(409, "报告尚未完成")
        if format == "md":
            return Response(
                current["state"]["report"],
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="report.md"'},
            )
        if format == "json":
            return Response(
                json.dumps(current, ensure_ascii=False, indent=2),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="report.json"'},
            )
        raise HTTPException(404, "不支持的格式")

    @app.get("/api/tasks/{task_id}/evidence/search")
    async def evidence_search(task_id: str, q: str):
        task(task_id)
        if not 1 <= len(q) <= 1000:
            raise HTTPException(400, "查询长度应为 1—1000 字符")
        index = await asyncio.to_thread(VectorIndex, root, task_id, store.settings())
        try:
            return await index.query(q)
        except Exception:
            raise HTTPException(400, "向量查询失败，请检查 Embedding 配置") from None

    @app.post("/api/uploads")
    async def upload(file: UploadFile):
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or not data.startswith(b"%PDF-"):
            raise HTTPException(400, "请上传不超过 30 MB 的 PDF")
        upload_id = uuid4().hex
        folder = root / "uploads"
        folder.mkdir(exist_ok=True)
        (folder / f"{upload_id}.pdf").write_bytes(data)
        name = Path(file.filename or "论文.pdf").name
        (folder / f"{upload_id}.json").write_text(
            json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8"
        )
        return {"id": upload_id, "name": name}

    frontend = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        path = frontend / "favicon.svg"
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
        raise HTTPException(404, "图标尚未构建")

    @app.get("/")
    def home():
        if (frontend / "index.html").exists():
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-store"})
        return JSONResponse({"message": "请先在 frontend 运行 npm ci 和 npm run build"})

    return app


def main():
    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("LITRESEARCH_PORT", "8765")),
        workers=1,
    )
