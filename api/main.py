"""FastAPI app. Run: uvicorn api.main:app --reload"""

import mimetypes
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from api import search as search_mod
from config import BOOKS_DIR, SUPPORTED, WEB_DIR
from db import connect, init_db

# pdf.js ships ES modules; some setups don't map .mjs, which breaks the viewer.
mimetypes.add_type("text/javascript", ".mjs")

app = FastAPI(title="Grimoire", description="Full-text search inside your books.")

MEDIA_TYPES = {"pdf": "application/pdf", "epub": "application/epub+zip"}


@app.on_event("startup")
def _startup() -> None:
    conn = connect()
    init_db(conn)
    conn.close()


def _book_or_404(conn, book_id: int):
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Book not found")
    return row


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    # The single-page UI changes often; never let the browser serve a stale copy.
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(500, ge=1, le=2000),
    book: int | None = None,
):
    conn = connect()
    try:
        data = search_mod.search(conn, q, limit=limit, book_id=book)
    finally:
        conn.close()
    return {"query": q, **data}


@app.get("/books")
def books():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, title, author, format, pages, added_at FROM books "
            "ORDER BY title COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()
    return {"count": len(rows), "books": [dict(r) for r in rows]}


@app.get("/book/{book_id}")
def book_detail(book_id: int):
    conn = connect()
    try:
        row = _book_or_404(conn, book_id)
        pages_with_text = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE book_id = ?", (book_id,)
        ).fetchone()["n"]
    finally:
        conn.close()
    data = dict(row)
    data.pop("path", None)  # don't leak server filesystem paths
    data["indexed_pages"] = pages_with_text
    return data


@app.get("/download/{book_id}")
def download(book_id: int):
    conn = connect()
    try:
        row = _book_or_404(conn, book_id)
    finally:
        conn.close()

    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(410, "File missing on disk — re-run the indexer")

    media = MEDIA_TYPES.get(row["format"], "application/octet-stream")
    # FileResponse honors Range requests, so PDF viewers can seek/deep-link.
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/cover/{book_id}")
def cover(book_id: int):
    import covers as covers_mod

    conn = connect()
    try:
        row = _book_or_404(conn, book_id)
    finally:
        conn.close()

    path = covers_mod.get_or_make_cover(Path(row["path"]), row["format"], row["sha256"])
    if path is None or not path.exists():
        raise HTTPException(404, "No cover available")

    media = covers_mod.MEDIA_BY_EXT.get(path.suffix.lstrip(".").lower(), "image/png")
    # Covers are keyed by content hash, so they're safe to cache aggressively.
    return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@app.delete("/book/{book_id}")
def delete_book(book_id: int):
    """Remove a book from the index AND delete its file from disk (permanent)."""
    import covers as covers_mod

    conn = connect()
    try:
        row = _book_or_404(conn, book_id)
        path = Path(row["path"])
        sha = row["sha256"]
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
    finally:
        conn.close()

    # Remove the source file and any cached cover so it doesn't get re-indexed.
    path.unlink(missing_ok=True)
    cached = covers_mod.existing_cover(sha)
    if cached is not None:
        cached.unlink(missing_ok=True)

    return {"deleted": book_id, "title": row["title"]}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Save an uploaded PDF/EPUB into the books folder and index it."""
    name = Path(file.filename or "").name  # strip any directory components
    if not name:
        raise HTTPException(400, "No filename")
    if Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, "Only .pdf and .epub files are supported")

    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BOOKS_DIR / name
    if dest.exists():
        raise HTTPException(409, f"A file named '{name}' already exists")

    try:
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()

    from indexer.index import index_file

    try:
        index_file(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)  # don't leave a file we couldn't index
        raise HTTPException(422, f"Saved but could not index: {e}")

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, title, author, format, pages FROM books WHERE path = ?",
            (str(dest),),
        ).fetchone()
    finally:
        conn.close()
    return {"uploaded": name, "book": dict(row) if row else None}


@app.post("/reindex")
def reindex():
    from indexer.index import reindex as run  # imported lazily; heavy deps

    return run(verbose=False)


@app.get("/opds")
def opds() -> Response:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, title, author, format FROM books ORDER BY title COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for r in rows:
        media = MEDIA_TYPES.get(r["format"], "application/octet-stream")
        entries.append(
            "<entry>"
            f"<title>{escape(r['title'] or 'Untitled')}</title>"
            f"<id>urn:grimoire:book:{r['id']}</id>"
            f"<author><name>{escape(r['author'] or 'Unknown')}</name></author>"
            f'<link rel="http://opds-spec.org/acquisition" '
            f'href="/download/{r["id"]}" type="{media}"/>'
            "</entry>"
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opds="http://opds-spec.org/2010/catalog">'
        "<title>Grimoire</title>"
        "<id>urn:grimoire:catalog</id>"
        + "".join(entries)
        + "</feed>"
    )
    return Response(feed, media_type="application/atom+xml")


# Bundled pdf.js reader. Deep links open /pdfjs/web/viewer.html?file=/download/{id}#page=N.
# StaticFiles handles Range requests for its own assets; the PDF itself streams
# from /download, which already supports Range.
_PDFJS_DIR = WEB_DIR / "pdfjs"
if _PDFJS_DIR.is_dir():
    app.mount("/pdfjs", StaticFiles(directory=_PDFJS_DIR), name="pdfjs")
