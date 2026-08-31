"""SQLite connection + schema. The DB is disposable — `rm grimoire.db` anytime."""

import sqlite3

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id       INTEGER PRIMARY KEY,
  path     TEXT UNIQUE NOT NULL,
  sha256   TEXT NOT NULL,        -- skip re-index if unchanged
  title    TEXT,
  author   TEXT,
  format   TEXT,                 -- pdf | epub
  pages    INTEGER,
  added_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
  text,
  book_id  UNINDEXED,
  page     UNINDEXED,
  label    UNINDEXED,            -- chapter / section name
  tokenize = 'porter unicode61'
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
