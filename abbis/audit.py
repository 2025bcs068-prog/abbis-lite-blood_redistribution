from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data_pipeline import ROOT

DB_PATH = ROOT / "data" / "local" / "review_audit.sqlite3"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS review_events (
            event_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            reviewer_name TEXT NOT NULL,
            reviewer_role TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            destination_facility_id TEXT NOT NULL,
            source_facility_id TEXT NOT NULL,
            component TEXT NOT NULL,
            blood_group TEXT NOT NULL,
            proposed_quantity INTEGER NOT NULL,
            decision_quantity INTEGER NOT NULL,
            selected_unit_ids TEXT NOT NULL
        )"""
    )
    connection.commit()
    return connection


def record_decision(
    *,
    reviewer_name: str,
    reviewer_role: str,
    decision: str,
    reason: str,
    destination_facility_id: str,
    source_facility_id: str,
    component: str,
    blood_group: str,
    proposed_quantity: int,
    decision_quantity: int,
    selected_unit_ids: list[str],
) -> None:
    event_id = str(uuid.uuid4())
    created_at = datetime.now(ZoneInfo("Africa/Kampala")).isoformat(timespec="seconds")
    with _connect() as connection:
        connection.execute(
            """INSERT INTO review_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                created_at,
                reviewer_name.strip(),
                reviewer_role,
                decision,
                reason.strip(),
                destination_facility_id,
                source_facility_id,
                component,
                blood_group,
                int(proposed_quantity),
                int(decision_quantity),
                json.dumps(selected_unit_ids),
            ),
        )


def recent_events(limit: int = 100) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with _connect() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM review_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]

