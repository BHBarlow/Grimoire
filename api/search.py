"""Query building + result formatting over the FTS5 chunks table."""

import re
import sqlite3
from typing import Optional

# Pull out quoted "phrases" and bare words so we can rebuild a safe MATCH string.
_TOKEN = re.compile(r'"([^"]+)"|(\S+)')


def build_match(q: str) -> str:
    """Turn free user text into a valid FTS5 MATCH expression.

    Every term is quoted (doubling any inner quotes) so punctuation can't break
    the FTS5 grammar. Bare terms get a trailing `*` for prefix matching; explicit
    "quoted phrases" are kept as exact phrases. Terms are AND-ed together.
    """
    terms: list[str] = []
    for phrase, word in _TOKEN.findall(q):
        if phrase:
            terms.append('"' + phrase.replace('"', '""') + '"')
        elif word:
            terms.append('"' + word.replace('"', '""') + '"*')
    return " ".join(terms)


def search(
    conn: sqlite3.Connection,
    q: str,
    limit: int = 500,
    book_id: Optional[int] = None,
) -> dict:
    """Full-text search, grouped by book.

    Returns {"books": [...], "book_count": N, "total_hits": M}. Books are ordered
    by their single most relevant hit; within each book, hits are in page order.
    `limit` caps the total number of page-hits fetched (across all books).
    """
    match = build_match(q)
    if not match:
        return {"books": [], "book_count": 0, "total_hits": 0}

    sql = [
        "SELECT b.id AS book_id, b.title, b.author, b.format,",
        "       c.page, c.label,",
        # Control-char sentinels, not raw <mark>, so the client can HTML-escape
        # the surrounding book text before turning highlights back into markup.
        "       snippet(chunks, 0, char(2), char(3), '…', 20) AS excerpt,",
        "       bm25(chunks) AS rank",
        "FROM chunks c JOIN books b ON b.id = c.book_id",
        "WHERE chunks MATCH ?",
    ]
    params: list = [match]

    if book_id is not None:
        sql.append("AND b.id = ?")
        params.append(book_id)

    sql.append("ORDER BY rank LIMIT ?")
    params.append(limit)

    rows = conn.execute("\n".join(sql), params).fetchall()

    # Group into books. Rows arrive best-rank-first, so the first time we see a
    # book fixes both its position and its best rank.
    books: dict = {}
    order: list = []
    for r in rows:
        bid = r["book_id"]
        if bid not in books:
            books[bid] = {
                "book_id": bid,
                "title": r["title"],
                "author": r["author"],
                "format": r["format"],
                "best_rank": r["rank"],
                "hits": [],
            }
            order.append(bid)
        books[bid]["hits"].append(
            {"page": r["page"], "label": r["label"], "excerpt": r["excerpt"]}
        )

    result = []
    for bid in order:
        b = books[bid]
        b["hits"].sort(key=lambda h: h["page"])  # reading order within a book
        b["hit_count"] = len(b["hits"])
        result.append(b)

    return {
        "books": result,
        "book_count": len(result),
        "total_hits": sum(b["hit_count"] for b in result),
    }
