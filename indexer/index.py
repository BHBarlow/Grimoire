"""Idempotent indexer. Walk books, hash them, (re)index only what changed.

Run:  python -m indexer.index
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import BOOKS_DIR
from db import connect, init_db
from indexer.extract import extract
from indexer.walk import iter_books, sha256


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _existing(conn: sqlite3.Connection, path: str):
    return conn.execute(
        "SELECT id, sha256 FROM books WHERE path = ?", (path,)
    ).fetchone()


def _index_one(conn: sqlite3.Connection, path: Path, digest: str) -> None:
    data = extract(path)
    row = _existing(conn, str(path))

    if row is None:
        cur = conn.execute(
            "INSERT INTO books (path, sha256, title, author, format, pages, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(path), digest, data.title, data.author, data.fmt, data.pages, _now()),
        )
        book_id = cur.lastrowid
    else:
        book_id = row["id"]
        conn.execute(
            "UPDATE books SET sha256=?, title=?, author=?, format=?, pages=? WHERE id=?",
            (digest, data.title, data.author, data.fmt, data.pages, book_id),
        )
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))

    conn.executemany(
        "INSERT INTO chunks (text, book_id, page, label) VALUES (?, ?, ?, ?)",
        [(c.text, book_id, c.page, c.label) for c in data.chunks],
    )
    conn.commit()


def _prune_missing(conn: sqlite3.Connection, seen: set[str]) -> int:
    """Drop books whose files are gone from disk."""
    rows = conn.execute("SELECT id, path FROM books").fetchall()
    removed = 0
    for r in rows:
        if r["path"] not in seen:
            conn.execute("DELETE FROM chunks WHERE book_id = ?", (r["id"],))
            conn.execute("DELETE FROM books WHERE id = ?", (r["id"],))
            removed += 1
    if removed:
        conn.commit()
    return removed


def index_file(path: Path) -> None:
    """Index a single file (used by the upload endpoint). Skips if unchanged."""
    conn = connect()
    init_db(conn)
    try:
        digest = sha256(path)
        row = _existing(conn, str(path))
        if row is not None and row["sha256"] == digest:
            return
        _index_one(conn, path, digest)
    finally:
        conn.close()


def reindex(verbose: bool = True) -> dict:
    """Scan BOOKS_DIR and sync the index. Returns a small stats dict."""
    conn = connect()
    init_db(conn)

    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "failed": 0, "removed": 0}
    seen: set[str] = set()

    for path in iter_books(BOOKS_DIR):
        stats["scanned"] += 1
        seen.add(str(path))
        digest = sha256(path)
        row = _existing(conn, str(path))

        if row is not None and row["sha256"] == digest:
            stats["skipped"] += 1
            continue

        try:
            _index_one(conn, path, digest)
            stats["indexed"] += 1
            if verbose:
                print(f"  indexed  {path.relative_to(BOOKS_DIR)}")
        except Exception as e:  # keep going; one bad file shouldn't stop the run
            stats["failed"] += 1
            if verbose:
                print(f"  FAILED   {path.name}: {e}", file=sys.stderr)

    stats["removed"] = _prune_missing(conn, seen)
    conn.close()

    if verbose:
        print(
            f"\nDone. scanned={stats['scanned']} indexed={stats['indexed']} "
            f"skipped={stats['skipped']} failed={stats['failed']} "
            f"removed={stats['removed']}"
        )
    return stats


if __name__ == "__main__":
    if not BOOKS_DIR.exists():
        print(f"Books dir does not exist: {BOOKS_DIR}", file=sys.stderr)
        print("Set BOOKS_DIR in .env or create the folder and drop books in.")
        sys.exit(1)
    reindex()
