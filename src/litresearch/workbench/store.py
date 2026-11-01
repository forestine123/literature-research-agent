"""SQLite 事务保存检查点与事件；任务领取使用条件更新避免重复启动。"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .schemas import Settings


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "workbench.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, topic TEXT, request TEXT, state TEXT,
                    status TEXT, stage TEXT, error TEXT, created TEXT, updated TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, at TEXT,
                    kind TEXT, stage TEXT, message TEXT, detail TEXT);
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id);
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT, updated TEXT);
                CREATE TABLE IF NOT EXISTS task_sessions (
                    task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS task_session_idx ON task_sessions(session_id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                    evidence_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
                    usage TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS active_chat ON messages(session_id)
                    WHERE role='assistant' AND status='running';
                INSERT OR IGNORE INTO sessions
                    SELECT id,topic,created,updated FROM tasks
                    WHERE id NOT IN (SELECT task_id FROM task_sessions);
                INSERT OR IGNORE INTO task_sessions SELECT id,id FROM tasks;
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def settings(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, settings):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)", (settings.model_dump_json(),))

    def public_settings(self):
        data = self.settings().model_dump()
        for provider in data["providers"].values():
            provider["api_key"] = "********" if provider["api_key"] else ""
        for key in ("openalex_key", "semantic_scholar_key"):
            data[key] = "********" if data[key] else ""
        return data

    def create(self, request):
        task_id = uuid4().hex
        with self.connect() as db:
            session_id = request.session_id or task_id
            if request.session_id:
                if not db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                    raise KeyError(session_id)
            else:
                db.execute(
                    "INSERT INTO sessions VALUES(?,?,?,?)",
                    (session_id, request.topic[:160], now(), now()),
                )
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    request.topic,
                    request.model_dump_json(),
                    "{}",
                    "queued",
                    "search",
                    "",
                    now(),
                    now(),
                ),
            )
            db.execute("INSERT INTO task_sessions VALUES(?,?)", (task_id, session_id))
            db.execute("UPDATE sessions SET updated=? WHERE id=?", (now(), session_id))
        self.event(task_id, "created", "search", "调研任务已创建")
        return task_id

    def get(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        data = dict(row)
        data["request"] = json.loads(data["request"])
        data["state"] = json.loads(data["state"])
        with self.connect() as db:
            data["session_id"] = db.execute(
                "SELECT session_id FROM task_sessions WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        return data

    def sessions(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute("""
                SELECT s.*, (SELECT COUNT(*) FROM task_sessions x WHERE x.session_id=s.id) AS task_count,
                (SELECT t.id FROM tasks t JOIN task_sessions x ON x.task_id=t.id
                 WHERE x.session_id=s.id ORDER BY t.created DESC LIMIT 1) AS latest_task_id
                FROM sessions s ORDER BY s.updated DESC
            """)
            ]

    def session(self, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise KeyError(session_id)
            result = dict(row)
            result["tasks"] = [
                dict(r)
                for r in db.execute(
                    """
                SELECT t.id,t.topic,t.status,t.stage,t.created FROM tasks t JOIN task_sessions x
                ON t.id=x.task_id WHERE x.session_id=? ORDER BY t.created DESC
            """,
                    (session_id,),
                )
            ]
            result["messages"] = []
            for row in db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            ):
                item = dict(row)
                item["evidence_ids"] = json.loads(item["evidence_ids"])
                item["usage"] = json.loads(item["usage"])
                result["messages"].append(item)
            return result

    def rename_session(self, session_id, title):
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET title=?,updated=? WHERE id=?", (title, now(), session_id)
            )

    def begin_chat(self, session_id, task_id, content):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM task_sessions WHERE task_id=? AND session_id=?",
                (task_id, session_id),
            ).fetchone():
                raise KeyError(task_id)
            if db.execute(
                "SELECT 1 FROM messages WHERE session_id=? AND status='running'", (session_id,)
            ).fetchone():
                raise ValueError("当前会话正在回复，请等待完成")
            db.execute(
                "INSERT INTO messages(session_id,task_id,role,content,status,created) VALUES(?,?,'user',?,'completed',?)",
                (session_id, task_id, content, now()),
            )
            message_id = db.execute(
                "INSERT INTO messages(session_id,task_id,role,content,status,created) VALUES(?,?,'assistant','','running',?)",
                (session_id, task_id, now()),
            ).lastrowid
            db.execute("UPDATE sessions SET updated=? WHERE id=?", (now(), session_id))
            return message_id

    def finish_chat(self, message_id, content, evidence_ids=None, usage=None, status="completed"):
        with self.connect() as db:
            db.execute(
                "UPDATE messages SET content=?,evidence_ids=?,usage=?,status=? WHERE id=?",
                (content, encode(evidence_ids or []), encode(usage or {}), status, message_id),
            )
            db.execute(
                "UPDATE sessions SET updated=? WHERE id=(SELECT session_id FROM messages WHERE id=?)",
                (now(), message_id),
            )

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,topic,status,stage,error,created,updated FROM tasks ORDER BY created DESC LIMIT 100"
                )
            ]

    def claim(self, task_id):
        with self.connect() as db:
            return (
                db.execute(
                    "UPDATE tasks SET status='running',error='',updated=? WHERE id=? AND status IN ('queued','failed','interrupted','cancelled')",
                    (now(), task_id),
                ).rowcount
                == 1
            )

    def checkpoint(self, task_id, state, stage, message="阶段产物已保存"):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET state=?,stage=?,updated=? WHERE id=?",
                (encode(state), stage, now(), task_id),
            )
            db.execute(
                "INSERT INTO events(task_id,at,kind,stage,message,detail) VALUES(?,?,?,?,?,?)",
                (task_id, now(), "checkpoint", stage, message, "{}"),
            )

    def status(self, task_id, status, error=""):
        with self.connect() as db:
            db.execute(
                "UPDATE tasks SET status=?,error=?,updated=? WHERE id=?",
                (status, error, now(), task_id),
            )

    def event(self, task_id, kind, stage, message, detail=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(task_id,at,kind,stage,message,detail) VALUES(?,?,?,?,?,?)",
                (task_id, now(), kind, stage, message, encode(detail or {})),
            )

    def events(self, task_id, after=0):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT 300",
                (task_id, after),
            ).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]

    def reconcile(self):
        with self.connect() as db:
            db.execute(
                "UPDATE messages SET status='failed',content='服务中断，未完成此次回复；可以重新提问。' WHERE status='running'"
            )
            rows = db.execute(
                "SELECT id,stage FROM tasks WHERE status IN ('running','queued','cancelling')"
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE tasks SET status='interrupted',error=?,updated=? WHERE id=?",
                    ("服务中断；可从最近检查点恢复", now(), row["id"]),
                )
                db.execute(
                    "INSERT INTO events(task_id,at,kind,stage,message,detail) VALUES(?,?,?,?,?,?)",
                    (
                        row["id"],
                        now(),
                        "interrupted",
                        row["stage"],
                        "启动对账：已解除孤儿任务运行锁",
                        "{}",
                    ),
                )
        return len(rows)
