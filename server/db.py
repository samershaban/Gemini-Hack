"""SQLite storage for rounds and clips.

Every round played is saved here with its true answer, so the eval can read it later.
"""

import json
import sqlite3
from datetime import datetime, timezone

from server.paths import DATA_FOLDER, DATABASE_FILE


def open_connection() -> sqlite3.Connection:
    """Open a new connection. Rows come back as dict-like objects."""
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def get_current_time_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_tables() -> None:
    connection = open_connection()
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rounds (
                round_id TEXT PRIMARY KEY,
                room TEXT NOT NULL,
                prompts_json TEXT NOT NULL,
                lie_index INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clips (
                clip_id TEXT PRIMARY KEY,
                round_id TEXT NOT NULL REFERENCES rounds(round_id),
                kind TEXT NOT NULL,
                statement_index INTEGER NOT NULL,
                camera_id TEXT NOT NULL,
                original_path TEXT NOT NULL,
                mp4_path TEXT NOT NULL,
                gemini_file_uri TEXT,
                transcript TEXT,
                measures_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    connection.close()


def insert_round(round_id: str, room: str, prompts: list[str], lie_index: int) -> None:
    connection = open_connection()
    with connection:
        connection.execute(
            "INSERT INTO rounds (round_id, room, prompts_json, lie_index, created_at) VALUES (?, ?, ?, ?, ?)",
            (round_id, room, json.dumps(prompts), lie_index, get_current_time_text()),
        )
    connection.close()


def get_round(round_id: str) -> dict | None:
    """Return the round as a dict, or None if no round has this id."""
    connection = open_connection()
    row = connection.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    connection.close()
    if row is None:
        return None
    round_info = dict(row)
    round_info["prompts"] = json.loads(round_info["prompts_json"])
    return round_info


def insert_clip(
    clip_id: str,
    round_id: str,
    kind: str,
    statement_index: int,
    camera_id: str,
    original_path: str,
    mp4_path: str,
) -> None:
    connection = open_connection()
    with connection:
        connection.execute(
            """
            INSERT INTO clips (clip_id, round_id, kind, statement_index, camera_id,
                               original_path, mp4_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                round_id,
                kind,
                statement_index,
                camera_id,
                original_path,
                mp4_path,
                get_current_time_text(),
            ),
        )
    connection.close()
