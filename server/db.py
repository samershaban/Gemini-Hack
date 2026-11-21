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
    add_column_if_missing("clips", "words_json", "TEXT")
    add_column_if_missing("clips", "events_json", "TEXT")
    add_column_if_missing("rounds", "analysis_json", "TEXT")
    add_column_if_missing("rounds", "call_json", "TEXT")
    add_column_if_missing("rounds", "result_json", "TEXT")
    add_column_if_missing("rounds", "tried_to_trick", "INTEGER")
    add_column_if_missing("rounds", "tags_json", "TEXT")

    connection = open_connection()
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS votes (
                round_id TEXT NOT NULL REFERENCES rounds(round_id),
                voter_name TEXT NOT NULL,
                statement INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (round_id, voter_name)
            )
            """
        )
    connection.close()


def add_column_if_missing(table_name: str, column_name: str, column_type: str) -> None:
    """Small migration helper so an older local database keeps working."""
    connection = open_connection()
    existing_columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")]
    if column_name not in existing_columns:
        with connection:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
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
    return decode_round_row(row)


def decode_round_row(row: sqlite3.Row) -> dict:
    """Turn a rounds row into a dict and decode its JSON columns."""
    round_info = dict(row)
    round_info["prompts"] = json.loads(round_info["prompts_json"])
    for json_column in ["analysis_json", "call_json", "result_json"]:
        plain_name = json_column.replace("_json", "")
        column_text = round_info.get(json_column)
        round_info[plain_name] = json.loads(column_text) if column_text else None
    return round_info


def get_latest_round_in_room(room: str) -> dict | None:
    connection = open_connection()
    row = connection.execute(
        "SELECT * FROM rounds WHERE room = ? ORDER BY created_at DESC LIMIT 1", (room,)
    ).fetchone()
    connection.close()
    return decode_round_row(row) if row else None


def get_revealed_rounds_in_room(room: str) -> list[dict]:
    connection = open_connection()
    rows = connection.execute(
        "SELECT * FROM rounds WHERE room = ? AND result_json IS NOT NULL ORDER BY created_at", (room,)
    ).fetchall()
    connection.close()
    return [decode_round_row(row) for row in rows]


def get_all_revealed_rounds() -> list[dict]:
    """Every finished round, oldest first. The eval reads these."""
    connection = open_connection()
    rows = connection.execute(
        "SELECT * FROM rounds WHERE result_json IS NOT NULL ORDER BY created_at"
    ).fetchall()
    connection.close()
    return [decode_round_row(row) for row in rows]


def save_round_json(round_id: str, column_name: str, value: dict) -> None:
    """Save analysis, call, or result JSON on a round."""
    allowed_columns = ["analysis_json", "call_json", "result_json"]
    if column_name not in allowed_columns:
        raise ValueError(f"column_name must be one of {allowed_columns}")
    connection = open_connection()
    with connection:
        connection.execute(f"UPDATE rounds SET {column_name} = ? WHERE round_id = ?", (json.dumps(value), round_id))
    connection.close()


def save_tried_to_trick(round_id: str, tried_to_trick: bool) -> None:
    connection = open_connection()
    with connection:
        connection.execute("UPDATE rounds SET tried_to_trick = ? WHERE round_id = ?", (int(tried_to_trick), round_id))
    connection.close()


def save_vote(round_id: str, voter_name: str, statement: int) -> None:
    """One vote per voter per round; voting again changes the vote."""
    connection = open_connection()
    with connection:
        connection.execute(
            """
            INSERT INTO votes (round_id, voter_name, statement, created_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (round_id, voter_name) DO UPDATE SET statement = excluded.statement
            """,
            (round_id, voter_name, statement, get_current_time_text()),
        )
    connection.close()


def get_votes_for_round(round_id: str) -> list[dict]:
    connection = open_connection()
    rows = connection.execute("SELECT * FROM votes WHERE round_id = ?", (round_id,)).fetchall()
    connection.close()
    return [dict(row) for row in rows]


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


def save_clip_measurements(
    clip_id: str,
    transcript: str,
    words: list[dict],
    measures: dict,
    events: list[dict],
) -> None:
    connection = open_connection()
    with connection:
        connection.execute(
            """
            UPDATE clips SET transcript = ?, words_json = ?, measures_json = ?, events_json = ?
            WHERE clip_id = ?
            """,
            (transcript, json.dumps(words), json.dumps(measures), json.dumps(events), clip_id),
        )
    connection.close()


def save_clip_gemini_file_uri(clip_id: str, gemini_file_uri: str) -> None:
    connection = open_connection()
    with connection:
        connection.execute("UPDATE clips SET gemini_file_uri = ? WHERE clip_id = ?", (gemini_file_uri, clip_id))
    connection.close()


def get_clips_for_round(round_id: str) -> list[dict]:
    """All clips of a round, oldest first, with JSON columns decoded."""
    connection = open_connection()
    rows = connection.execute(
        "SELECT * FROM clips WHERE round_id = ? ORDER BY created_at", (round_id,)
    ).fetchall()
    connection.close()
    clips = []
    for row in rows:
        clip = dict(row)
        for json_column in ["measures_json", "words_json", "events_json"]:
            plain_name = json_column.replace("_json", "")
            clip[plain_name] = json.loads(clip[json_column]) if clip[json_column] else None
        clips.append(clip)
    return clips


def save_round_tags(round_id: str, tags: list[str]) -> None:
    connection = open_connection()
    with connection:
        connection.execute("UPDATE rounds SET tags_json = ? WHERE round_id = ?", (json.dumps(tags), round_id))
    connection.close()


def get_most_recent_round_id() -> str | None:
    connection = open_connection()
    row = connection.execute("SELECT round_id FROM rounds ORDER BY created_at DESC LIMIT 1").fetchone()
    connection.close()
    return row["round_id"] if row else None
