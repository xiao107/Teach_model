"""
Session persistence and lifecycle management.

Dialogue history is persisted to SQLite so conversations survive a server
restart. Heavy objects (DataFrames, fitted models) remain in memory only.
Idle sessions are evicted from the in-memory cache after a TTL.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from backend.state import ConversationManager

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, db_path: str = "backend/sessions.db", idle_ttl_seconds: int = 24 * 3600) -> None:
        self.db_path = db_path
        self.idle_ttl_seconds = idle_ttl_seconds
        self._cache: Dict[str, tuple[ConversationManager, float]] = {}
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                history TEXT NOT NULL,
                dataset_name TEXT,
                task_type TEXT,
                title TEXT DEFAULT '',
                updated_at REAL NOT NULL
            )
            """
        )
        # Migration: add title column for pre-existing databases
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "title" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN title TEXT DEFAULT ''")
        self._conn.commit()

    # ------------------------------------------------------------------ access

    def get(self, session_id: str) -> ConversationManager:
        """Return the manager for a session, restoring from DB if needed."""
        with self._lock:
            entry = self._cache.get(session_id)
            if entry is not None:
                manager, _ = entry
                self._cache[session_id] = (manager, time.time())
                return manager

            manager = ConversationManager(session_id=session_id)
            row = self._conn.execute(
                "SELECT history, dataset_name, task_type, title FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None:
                try:
                    state = {
                        "session_id": session_id,
                        "history": json.loads(row[0]),
                        "dataset_name": row[1],
                        "task_type": row[2],
                        "title": row[3] or "",
                    }
                    manager.restore(state)
                    logger.info(
                        "Session restored from DB session_id=%s messages=%d",
                        session_id, len(manager.history),
                    )
                except Exception:
                    logger.exception("Failed to restore session %s", session_id)

            self._cache[session_id] = (manager, time.time())
            return manager

    def save(self, manager: ConversationManager) -> None:
        """Persist the session snapshot to SQLite."""
        snapshot = manager.snapshot()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_id, history, dataset_name, task_type, title, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    history = excluded.history,
                    dataset_name = excluded.dataset_name,
                    task_type = excluded.task_type,
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot["session_id"],
                    json.dumps(snapshot["history"], ensure_ascii=False),
                    snapshot["dataset_name"],
                    snapshot["task_type"],
                    snapshot.get("title", ""),
                    time.time(),
                ),
            )
            self._conn.commit()
            self._cache[snapshot["session_id"]] = (manager, time.time())

    def delete(self, session_id: str) -> bool:
        with self._lock:
            self._cache.pop(session_id, None)
            cur = self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, updated_at, title FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        now = time.time()
        return [
            {
                "session_id": r[0],
                "updated_at": r[1],
                "idle_seconds": round(now - r[1]),
                "title": r[2] or "",
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ lifecycle

    def cleanup_idle(self) -> int:
        """Evict idle sessions from cache and DB. Returns number removed."""
        cutoff = time.time() - self.idle_ttl_seconds
        removed = 0
        with self._lock:
            for sid in [sid for sid, (_, ts) in self._cache.items() if ts < cutoff]:
                self._cache.pop(sid, None)
                removed += 1
            cur = self._conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
            self._conn.commit()
            removed += cur.rowcount
        if removed:
            logger.info("Cleaned up %d idle sessions", removed)
        return removed
