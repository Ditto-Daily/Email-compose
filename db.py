"""SQLite persistence for generated drafts and feedback processing."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from config import DATABASE_PATH


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    """Create the tracker table and indexes if they do not exist."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS draft_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incoming_message_id TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL,
                draft_id TEXT,
                sent_message_id TEXT,
                incoming_body TEXT NOT NULL,
                ai_draft TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFTED'
                    CHECK (status IN ('DRAFTED', 'PROCESSED')),
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_draft_logs_thread_status "
            "ON draft_logs(thread_id, status)"
        )


def log_draft(
    incoming_message_id: str,
    thread_id: str,
    draft_id: str,
    incoming_body: str,
    ai_draft: str,
) -> int:
    """Record a generated Gmail draft and return its local row ID."""
    initialize_db()
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO draft_logs (
                incoming_message_id, thread_id, draft_id, incoming_body,
                ai_draft, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'DRAFTED', ?)
            """,
            (
                incoming_message_id,
                thread_id,
                draft_id,
                incoming_body,
                ai_draft,
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def draft_exists(incoming_message_id: str) -> bool:
    """Return whether an incoming Gmail message has already been drafted."""
    initialize_db()
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM draft_logs WHERE incoming_message_id = ? LIMIT 1",
            (incoming_message_id,),
        ).fetchone()
    return row is not None


def get_drafted_records() -> list[dict[str, Any]]:
    """Return drafts that have not yet been matched to a sent response."""
    initialize_db()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM draft_logs WHERE status = 'DRAFTED' ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def mark_processed(record_id: int, sent_message_id: str) -> None:
    """Mark a draft comparison complete."""
    with _connect() as connection:
        connection.execute(
            """
            UPDATE draft_logs
            SET status = 'PROCESSED', sent_message_id = ?
            WHERE id = ?
            """,
            (sent_message_id, record_id),
        )
