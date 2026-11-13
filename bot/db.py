import asyncio
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS users_verification (
    user_id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    status TEXT NOT NULL,
    token_hash TEXT,
    token_expiry INTEGER,
    verified_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    reporter_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_tag TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    admin_message_id INTEGER,
    message_content TEXT,
    attachments_json TEXT,
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);

CREATE TABLE IF NOT EXISTS report_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,
    notes TEXT
);
"""


@dataclass
class ReportRecord:
    report_id: int
    message_id: int
    channel_id: int
    guild_id: int
    reporter_id: int
    author_id: int
    author_tag: str
    reason: str
    status: str
    hidden: int
    admin_message_id: Optional[int]
    message_content: Optional[str]
    attachments: Any
    created_at: int
    resolved_at: Optional[int]


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    async def execute(self, query: str, params: tuple = ()) -> int:
        return await asyncio.to_thread(self._execute_sync, query, params)

    def _execute_sync(self, query: str, params: tuple) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(query, params)
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._fetchone_sync, query, params)

    def _fetchone_sync(self, query: str, params: tuple) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    async def fetch_report(self, report_id: int) -> Optional[ReportRecord]:
        row = await self.fetchone(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        )
        if not row:
            return None
        attachments = []
        if row.get("attachments_json"):
            attachments = json.loads(row["attachments_json"])
        return ReportRecord(
            report_id=row["report_id"],
            message_id=row["message_id"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            reporter_id=row["reporter_id"],
            author_id=row["author_id"],
            author_tag=row["author_tag"],
            reason=row["reason"],
            status=row["status"],
            hidden=row["hidden"],
            admin_message_id=row.get("admin_message_id"),
            message_content=row.get("message_content"),
            attachments=attachments,
            created_at=row["created_at"],
            resolved_at=row.get("resolved_at"),
        )
