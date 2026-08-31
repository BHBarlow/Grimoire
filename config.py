"""Shared configuration. Resolves paths once so the indexer and API agree."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent


def _path(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name)
    p = Path(raw).expanduser() if raw else default
    # Relative paths are resolved against the repo root, not the cwd, so
    # `python -m indexer.index` behaves the same from anywhere.
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


BOOKS_DIR = _path("BOOKS_DIR", ROOT / "books")
DB_PATH = _path("DB_PATH", ROOT / "grimoire.db")
WEB_DIR = ROOT / "web"

# Generated book-cover thumbnails, cached by content hash. Disposable like the DB.
COVERS_DIR = _path("COVERS_DIR", ROOT / "covers")

# File extensions that appear in the library. PDFs are full-text searched;
# EPUBs are catalogued for download only (see FULLTEXT below).
SUPPORTED = {".pdf", ".epub"}

# Only these formats get their text extracted into the search index.
FULLTEXT = {".pdf"}
