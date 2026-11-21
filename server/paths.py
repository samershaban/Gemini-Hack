"""Folder locations used by the server. Everything under data/ is gitignored."""

import os
from pathlib import Path

REPO_ROOT_FOLDER = Path(__file__).resolve().parent.parent
DATA_FOLDER = REPO_ROOT_FOLDER / "data"
ROUNDS_FOLDER = DATA_FOLDER / "rounds"
# Set POKER_FACE_DB to test on a copy of the database without touching the real one.
DATABASE_FILE = Path(os.environ.get("POKER_FACE_DB", DATA_FOLDER / "poker_face.sqlite3"))


def get_round_folder(round_id: str) -> Path:
    """Return the folder that holds one round's clips, creating it if needed."""
    round_folder = ROUNDS_FOLDER / round_id
    round_folder.mkdir(parents=True, exist_ok=True)
    return round_folder
