"""Discover book files and hash them so unchanged books can be skipped."""

import hashlib
from pathlib import Path
from typing import Iterator

from config import BOOKS_DIR, SUPPORTED


def iter_books(books_dir: Path = BOOKS_DIR) -> Iterator[Path]:
    """Yield every supported book under books_dir, recursively, sorted."""
    if not books_dir.exists():
        return
    for path in sorted(books_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            yield path


def sha256(path: Path) -> str:
    """Content hash, read in chunks so large PDFs don't blow up memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
