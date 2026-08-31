"""Turn a book file into (metadata, per-page chunks).

PDFs are extracted per physical page (one searchable chunk each) with section
labels from the outline. EPUBs are catalogued for the library — title/author
metadata only, with NO chunks, so they never enter the full-text search index.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:  # PyMuPDF renamed its import; support both.
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

import ebooklib
from ebooklib import epub


@dataclass
class Chunk:
    page: int
    label: Optional[str]
    text: str


@dataclass
class Extracted:
    title: Optional[str]
    author: Optional[str]
    fmt: str
    pages: int
    chunks: list[Chunk] = field(default_factory=list)


def extract(path: Path) -> Extracted:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".epub":
        return _extract_epub_meta(path)
    raise ValueError(f"Unsupported format: {suffix}")


def _pdf_labels(toc: list, num_pages: int) -> dict[int, Optional[str]]:
    """Map each 1-based page to the nearest preceding TOC heading."""
    # toc entries are [level, title, page] with 1-based page numbers.
    entries = sorted(
        ((p, t) for _lvl, t, p in toc if isinstance(p, int) and p >= 1),
        key=lambda e: e[0],
    )
    labels: dict[int, Optional[str]] = {}
    current: Optional[str] = None
    idx = 0
    for pg in range(1, num_pages + 1):
        while idx < len(entries) and entries[idx][0] <= pg:
            current = entries[idx][1]
            idx += 1
        labels[pg] = current
    return labels


def _extract_pdf(path: Path) -> Extracted:
    doc = fitz.open(path)
    try:
        meta = doc.metadata or {}
        num_pages = doc.page_count
        labels = _pdf_labels(doc.get_toc(), num_pages)

        chunks: list[Chunk] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:  # skip blank / image-only pages (candidates for OCR)
                chunks.append(Chunk(page=i, label=labels.get(i), text=text))

        return Extracted(
            title=(meta.get("title") or path.stem).strip() or path.stem,
            author=(meta.get("author") or "").strip() or None,
            fmt="pdf",
            pages=num_pages,
            chunks=chunks,
        )
    finally:
        doc.close()


def _epub_meta_field(book: epub.EpubBook, field_name: str) -> Optional[str]:
    data = book.get_metadata("DC", field_name)
    if data and data[0] and data[0][0]:
        return str(data[0][0]).strip() or None
    return None


def _extract_epub_meta(path: Path) -> Extracted:
    """Catalogue metadata only — no text chunks, so EPUBs stay out of search."""
    book = epub.read_epub(path)
    sections = sum(1 for _ in book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    return Extracted(
        title=_epub_meta_field(book, "title") or path.stem,
        author=_epub_meta_field(book, "creator"),
        fmt="epub",
        pages=sections,
        chunks=[],  # intentionally empty: downloadable, not full-text indexed
    )
