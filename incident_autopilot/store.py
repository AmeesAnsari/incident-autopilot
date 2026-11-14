"""SQLite persistence, so open incidents survive a restart. One JSON document per incident."""

from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from .models import Action, Incident, IncidentStatus


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS incidents ("
                " id INTEGER PRIMARY KEY, account TEXT, category TEXT, status TEXT, doc TEXT)"
            )
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_key ON incidents(account, category, status)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS actions (seq INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT)"
            )

    @property
    def lock(self) -> threading.Lock:
        """Held by the engine around read-modify-write, so two webhooks can't race on one incident."""
        return self._lock

    def next_id(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM incidents").fetchone()
        return int(row[0])

    def save(self, incident: Incident) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO incidents (id, account, category, status, doc) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status = excluded.status, doc = excluded.doc",
                (incident.id, incident.account, incident.category, incident.status.value, incident.model_dump_json()),
            )

    def _one(self, sql: str, args: tuple) -> Optional[Incident]:
        row = self._db.execute(sql, args).fetchone()
        return Incident.model_validate_json(row[0]) if row else None

    def open_for(self, account: str, category: str) -> Optional[Incident]:
        return self._one(
            "SELECT doc FROM incidents WHERE account = ? AND category = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (account, category, IncidentStatus.OPEN.value),
        )

    def last_resolved_for(self, account: str, category: str) -> Optional[Incident]:
        return self._one(
            "SELECT doc FROM incidents WHERE account = ? AND category = ? AND status = ? ORDER BY id DESC LIMIT 1",
            (account, category, IncidentStatus.RESOLVED.value),
        )

    def get(self, incident_id: int) -> Optional[Incident]:
        return self._one("SELECT doc FROM incidents WHERE id = ?", (incident_id,))

    def all(self, status: Optional[str] = None) -> list[Incident]:
        if status:
            rows = self._db.execute("SELECT doc FROM incidents WHERE status = ? ORDER BY id", (status,))
        else:
            rows = self._db.execute("SELECT doc FROM incidents ORDER BY id")
        return [Incident.model_validate_json(r[0]) for r in rows]

    def log(self, actions: list[Action]) -> None:
        with self._db:
            self._db.executemany("INSERT INTO actions (doc) VALUES (?)", [(a.model_dump_json(),) for a in actions])

    def recent_actions(self, limit: int = 50) -> list[Action]:
        rows = self._db.execute("SELECT doc FROM actions ORDER BY seq DESC LIMIT ?", (limit,))
        return [Action.model_validate_json(r[0]) for r in rows]
