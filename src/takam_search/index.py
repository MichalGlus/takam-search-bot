"""SQLite index: documents, chunks and an FTS5 table.

The index is built into a temporary file and swapped in atomically, and only if it
passes sanity checks, so a broken source (site/API/DOCX change) never replaces a
working index.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import hebrew
from .chunker import chunk_document
from .parser import ParseError, parse_docx
from .validity import parse_date

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE docs (
    code TEXT PRIMARY KEY,
    sfid TEXT,
    name TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    parent_code TEXT,
    chapter TEXT,
    valid_from TEXT,
    valid_to TEXT,
    version_number INTEGER,
    url TEXT,
    keywords TEXT,
    description TEXT,
    change_log TEXT,
    error TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    doc_code TEXT NOT NULL REFERENCES docs(code),
    ordinal INTEGER NOT NULL,
    section TEXT,
    section_end TEXT,
    heading_path TEXT,
    text TEXT NOT NULL
);
CREATE INDEX chunks_doc ON chunks(doc_code);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    title, body, variants,
    tokenize = 'unicode61'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


class IndexBuildError(RuntimeError):
    """The new index failed a sanity check; the previous index was kept."""


def _iso(value: str | None) -> str | None:
    d = parse_date(value)
    return d.isoformat() if d else None


def build_index(
    manifest: dict[str, Any],
    raw_dir: Path,
    db_path: Path,
    previous_stats: dict[str, Any] | None = None,
    min_chunks_ratio: float = 0.5,
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(db_path.suffix + ".tmp")
    tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp_path)
    parse_failures: list[str] = []
    try:
        conn.executescript(SCHEMA)
        n_docs = n_chunks = 0
        for doc in manifest["documents"]:
            code = doc["code"]
            error = doc.get("error")
            chunks = []
            change_log: list[dict[str, str]] = []
            if doc.get("file") and not error:
                try:
                    parsed = parse_docx(raw_dir / doc["file"])
                    chunks = chunk_document(parsed)
                    change_log = parsed.change_log
                    if not chunks:
                        error = "no text extracted"
                except (ParseError, OSError) as exc:
                    error = f"parse failed: {exc}"
            if error:
                parse_failures.append(code)
                log.warning("document %s not indexed: %s", code, error)

            conn.execute(
                "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    code, doc.get("sfid"), doc.get("name") or code, doc.get("documenttype") or "",
                    doc.get("parent_code"), doc.get("firstnamechapter"),
                    _iso(doc.get("datevalidfrom")), _iso(doc.get("datevalidto")),
                    doc.get("version_number"), doc.get("url"), doc.get("keywords"),
                    doc.get("description"), json.dumps(change_log, ensure_ascii=False), error,
                ),
            )
            n_docs += 1
            title = f"{code} {doc.get('name') or ''} {doc.get('keywords') or ''}"
            for chunk in chunks:
                cur = conn.execute(
                    "INSERT INTO chunks (doc_code, ordinal, section, section_end, heading_path, text)"
                    " VALUES (?,?,?,?,?,?)",
                    (code, chunk.ordinal, chunk.section, chunk.section_end, chunk.heading_path, chunk.text),
                )
                conn.execute(
                    "INSERT INTO chunks_fts (rowid, title, body, variants) VALUES (?,?,?,?)",
                    (
                        cur.lastrowid,
                        hebrew.normalize(title),
                        hebrew.normalize(chunk.text),
                        hebrew.variants_text(f"{title} {chunk.text}"),
                    ),
                )
                n_chunks += 1

        stats = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fetched_at": manifest.get("fetched_at"),
            "docs": n_docs,
            "chunks": n_chunks,
            "failed_docs": parse_failures,
        }
        conn.executemany(
            "INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in stats.items()]
        )
        conn.commit()
    finally:
        conn.close()

    # Sanity checks before swapping in the new index.
    problem = None
    if stats["chunks"] == 0:
        problem = "new index has 0 chunks"
    elif previous_stats and previous_stats.get("chunks"):
        if stats["chunks"] < previous_stats["chunks"] * min_chunks_ratio:
            problem = (f"chunk count dropped from {previous_stats['chunks']} to {stats['chunks']}"
                       f" (threshold {min_chunks_ratio:.0%})")
    if problem:
        tmp_path.unlink(missing_ok=True)
        raise IndexBuildError(f"{problem}; previous index kept")

    os.replace(tmp_path, db_path)
    return stats


def read_stats(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM meta")}
    finally:
        conn.close()
