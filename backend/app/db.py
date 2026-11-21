"""SQLite storage. Schema is created on startup; file path comes from DATABASE_URL."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def db_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    return url.replace("sqlite:///", "", 1)


@contextmanager
def conn():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    d = os.path.dirname(db_path())
    if d:
        os.makedirs(d, exist_ok=True)
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                system_prompt TEXT
            );
            """
        )


def ping() -> bool:
    with conn() as c:
        c.execute("SELECT 1")
    return True


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_system_prompt(session_id: str):
    with conn() as c:
        r = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return r["system_prompt"] if r else None


def set_system_prompt(session_id: str, prompt: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO sessions(session_id, system_prompt) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET system_prompt=excluded.system_prompt",
            (session_id, prompt),
        )


def history(session_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id", (session_id,)
        ).fetchall()
    out = []
    for r in rows:
        m = {"role": r["role"], "content": r["content"]}
        if r["metadata"]:
            m["metadata"] = json.loads(r["metadata"])
        out.append(m)
    return out


def save_turn(session_id: str, user_msg: str, reply: str, metadata: dict) -> None:
    """Persist user + assistant messages atomically (only called after a successful LLM reply)."""
    with conn() as c:
        c.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "user", user_msg, None, now()),
        )
        c.execute(
            "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
            (session_id, "assistant", reply, json.dumps(metadata), now()),
        )
