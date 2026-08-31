"""Book-cover thumbnails, cached on disk by content hash.

PDF  -> render the first page.
EPUB -> pull the cover image from the archive (or the first image as a fallback).

Every cover is normalized to a ~400px-wide JPEG so the library grid stays light
(raw EPUB covers can be multi-megabyte). Covers live in COVERS_DIR named
`<sha256>.jpg`; that dir is disposable and git-ignored. Returns a Path to the
cached image, or None if none could be produced.
"""

from pathlib import Path
from typing import Optional

try:  # PyMuPDF renamed its import; support both.
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

import ebooklib
from ebooklib import epub

from config import COVERS_DIR

# Target rendered width of a cover thumbnail, in pixels.
TARGET_WIDTH = 400
JPEG_QUALITY = 82

MEDIA_BY_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def existing_cover(sha: str) -> Optional[Path]:
    if not COVERS_DIR.exists():
        return None
    for p in COVERS_DIR.glob(f"{sha}.*"):
        return p
    return None


def get_or_make_cover(book_path: Path, fmt: str, sha: str) -> Optional[Path]:
    cached = existing_cover(sha)
    if cached is not None:
        return cached

    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if fmt == "pdf":
            pix = _pdf_first_page(book_path)
        elif fmt == "epub":
            data = _epub_cover_bytes(epub.read_epub(book_path))
            pix = _image_to_pixmap(data) if data else None
        else:
            return None
    except Exception:
        return None

    if pix is None:
        return None
    return _save_jpeg(pix, sha)


def _pdf_first_page(path: Path):
    doc = fitz.open(path)
    try:
        if doc.page_count == 0:
            return None
        page = doc[0]
        zoom = TARGET_WIDTH / (page.rect.width or TARGET_WIDTH)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    finally:
        doc.close()


def _image_to_pixmap(data: bytes):
    # Open the raw cover image as a one-page document and re-render it scaled down.
    doc = fitz.open(stream=data)
    try:
        page = doc[0]
        zoom = min(1.0, TARGET_WIDTH / (page.rect.width or TARGET_WIDTH))
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    finally:
        doc.close()


def _save_jpeg(pix, sha: str) -> Path:
    # JPEG can't carry alpha and doesn't do CMYK here; convert to plain RGB first.
    if pix.alpha or (pix.colorspace and pix.colorspace.n not in (1, 3)):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    out = COVERS_DIR / f"{sha}.jpg"
    out.write_bytes(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
    return out


def _epub_cover_bytes(book: epub.EpubBook) -> Optional[bytes]:
    # 1. Items explicitly flagged as the cover.
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        if item.get_content():
            return item.get_content()

    # 2. The <meta name="cover" content="..."> pointer, if present.
    for _value, attrs in book.get_metadata("OPF", "cover") or []:
        item_id = attrs.get("content")
        item = book.get_item_with_id(item_id) if item_id else None
        if item and item.get_content():
            return item.get_content()

    images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))

    # 3. Any image whose name mentions "cover".
    for item in images:
        if "cover" in item.get_name().lower() and item.get_content():
            return item.get_content()

    # 4. Last resort: the first image in the book.
    for item in images:
        if item.get_content():
            return item.get_content()

    return None
