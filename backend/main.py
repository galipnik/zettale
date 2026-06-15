"""
Personal Todo PWA — FastAPI backend.

Single-user, bearer-token auth, SQLite storage.
Last-write-wins per task (no file-sync conflicts).

Run locally:
    export TODO_TOKEN="dein-geheimes-token"
    uvicorn main:app --reload --port 8001
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- config -----------------------------------------------------------------

DB_PATH = os.environ.get("TODO_DB", "todo.db")
TOKEN = os.environ.get("TODO_TOKEN", "")  # MUST be set in production
import re

DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

if not TOKEN:
    # Fail loud rather than run unauthenticated.
    print("WARNING: TODO_TOKEN not set — all authed requests will 401.")

# --- db ----------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL,
    context    TEXT    NOT NULL DEFAULT 'privat',
    due        TEXT    NOT NULL DEFAULT '',
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS thoughts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL,
    context    TEXT    NOT NULL DEFAULT 'privat',
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- auth --------------------------------------------------------------------

def require_token(authorization: str = Header(default="")):
    expected = f"Bearer {TOKEN}"
    if not TOKEN or authorization != expected:
        raise HTTPException(status_code=401, detail="invalid or missing token")


# --- schemas -----------------------------------------------------------------

class TaskIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    context: str = "privat"
    due: str = ""


class TaskPatch(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    context: Optional[str] = None
    due: Optional[str] = None
    done: Optional[bool] = None


class Task(BaseModel):
    id: int
    text: str
    context: str
    due: str
    done: bool
    created_at: str
    updated_at: str


def validate_context(c: str) -> str:
    c = c.strip().lower()
    return c if c and len(c) <= 30 and c.replace("-", "").isalnum() else "privat"


def validate_due(d: str) -> str:
    """Empty string or an ISO date (YYYY-MM-DD)."""
    d = (d or "").strip()
    return d if d == "" or DUE_RE.match(d) else ""


class ThoughtIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    context: str = "privat"


class Thought(BaseModel):
    id: int
    text: str
    context: str
    archived: bool
    created_at: str


def row_to_thought(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "text": r["text"],
        "context": r["context"],
        "archived": bool(r["archived"]),
        "created_at": r["created_at"],
    }


def row_to_task(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "text": r["text"],
        "context": r["context"],
        "due": r["due"],
        "done": bool(r["done"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


# --- app ---------------------------------------------------------------------

app = FastAPI(title="Personal Todo PWA")

# In production, restrict to your own frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("TODO_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


init_db()  # ensure schema exists at import time (covers all run modes)


@app.get("/health")
def health():
    return {"status": "ok", "time": now()}


@app.get("/tasks", response_model=list[Task], dependencies=[Depends(require_token)])
def list_tasks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks "
            "ORDER BY done ASC, (due = '') ASC, due ASC, created_at ASC"
        ).fetchall()
    return [row_to_task(r) for r in rows]


@app.post("/tasks", response_model=Task, dependencies=[Depends(require_token)])
def create_task(t: TaskIn):
    ts = now()
    ctx = validate_context(t.context)
    due = validate_due(t.due)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (text, context, due, done, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (t.text.strip(), ctx, due, ts, ts),
        )
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return row_to_task(row)


@app.patch("/tasks/{task_id}", response_model=Task, dependencies=[Depends(require_token)])
def update_task(task_id: int, patch: TaskPatch):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="task not found")

        text = patch.text.strip() if patch.text is not None else row["text"]
        context = validate_context(patch.context) if patch.context is not None else row["context"]
        due = validate_due(patch.due) if patch.due is not None else row["due"]
        done = int(patch.done) if patch.done is not None else row["done"]

        cur = conn.execute(
            "UPDATE tasks SET text=?, context=?, due=?, done=?, updated_at=? WHERE id=?",
            (text, context, due, done, now(), task_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="task not found")
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_task(row)


@app.delete("/tasks/{task_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_task(task_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="task not found")
    return Response(status_code=204)


@app.get("/thoughts", response_model=list[Thought], dependencies=[Depends(require_token)])
def list_thoughts():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM thoughts ORDER BY created_at DESC"
        ).fetchall()
    return [row_to_thought(r) for r in rows]


@app.post("/thoughts", response_model=Thought, dependencies=[Depends(require_token)])
def create_thought(t: ThoughtIn):
    ts = now()
    ctx = validate_context(t.context)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO thoughts (text, context, archived, created_at) VALUES (?, ?, 0, ?)",
            (t.text.strip(), ctx, ts),
        )
        row = conn.execute("SELECT * FROM thoughts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_thought(row)


@app.patch("/thoughts/{thought_id}/archive", response_model=Thought, dependencies=[Depends(require_token)])
def archive_thought(thought_id: int):
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE thoughts SET archived=1 WHERE id=?", (thought_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="thought not found")
        row = conn.execute("SELECT * FROM thoughts WHERE id=?", (thought_id,)).fetchone()
    return row_to_thought(row)


@app.delete("/thoughts/{thought_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_thought(thought_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM thoughts WHERE id=?", (thought_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="thought not found")
    return Response(status_code=204)


@app.get("/export", dependencies=[Depends(require_token)])
def export_todotxt():
    """Plaintext export in todo.txt format — portability fallback."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks "
            "ORDER BY done ASC, (due = '') ASC, due ASC, created_at ASC"
        ).fetchall()
    lines = []
    for r in rows:
        parts = []
        if r["done"]:
            parts.append("x")
        parts.append(r["text"])
        parts.append(f"@{r['context']}")
        if r["due"]:
            parts.append(f"due:{r['due']}")
        lines.append(" ".join(parts))
    body = "\n".join(lines) + ("\n" if lines else "")
    return Response(content=body, media_type="text/plain")
