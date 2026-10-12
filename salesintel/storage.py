import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def connect():
    path = Path(os.getenv("SIGNALDESK_DB", str(ROOT / "var" / "signaldesk.sqlite")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS account_state (
                account_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                notes TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS traces (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, account_id TEXT NOT NULL,
                mode TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL, request TEXT NOT NULL, response TEXT,
                latency_ms REAL NOT NULL, input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL,
                decision TEXT, status TEXT NOT NULL, error TEXT
            );
            CREATE TABLE IF NOT EXISTS reservations (
                id TEXT PRIMARY KEY, day TEXT NOT NULL, amount REAL NOT NULL
            );
        """)
