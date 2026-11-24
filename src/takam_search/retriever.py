"""Search over the SQLite FTS5 index (BM25) with validity filtering."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import hebrew

# Column weights for bm25(): title (code+name+keywords), body, prefix variants.
BM25_WEIGHTS = (3.0, 1.0, 0.4)
MAX_PER_DOC = 3
RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    doc_code: str
    doc_name: str
    doc_type: str
    parent_code: str | None
    section: str | None
    section_end: str | None
    heading_path: str
    text: str
    url: str | None
    valid_from: str | None
    valid_to: str | None
    in_force: bool
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Retriever:
    def __init__(self, db_path: Path, today: Callable[[], date] = date.today) -> None:
        self.db_path = db_path
        self._today = today

    def _connect(self) -> sqlite3.Connection:
        # One read-only connection per call: safe across threads, and the index file
        # can be swapped by a rebuild while the service is running.
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def search(self, query: str, k: int = 8, include_expired: bool = False) -> list[Hit]:
        """Word-level BM25 fused (RRF) with an exact-phrase query over adjacent terms.

        Pure word ranking let common words outrank the one section containing the
        user's phrase; pure phrase-first let a generic phrase ("חשבון בנק") crowd out
        the right section. Fusion rewards chunks that rank well in both.
        """
        match = hebrew.build_match_query(query)
        if match is None:
            return []
        word_rows = self._rows(match, k, include_expired)
        phrase = hebrew.build_phrase_query(query)
        phrase_rows = self._rows(phrase, k, include_expired) if phrase else []
        fused: dict[int, float] = {}
        by_id: dict[int, sqlite3.Row] = {}
        for ranked in (word_rows, phrase_rows):
            for rank, r in enumerate(ranked):
                fused[r["id"]] = fused.get(r["id"], 0.0) + 1.0 / (RRF_K + rank + 1)
                by_id.setdefault(r["id"], r)
        rows = [by_id[i] for i in sorted(fused, key=fused.get, reverse=True)]

        hits, per_doc = [], {}
        for r in rows:
            if per_doc.get(r["doc_code"], 0) >= MAX_PER_DOC:
                continue
            per_doc[r["doc_code"]] = per_doc.get(r["doc_code"], 0) + 1
            hits.append(
                Hit(
                    chunk_id=r["id"], doc_code=r["doc_code"], doc_name=r["name"], doc_type=r["doc_type"],
                    parent_code=r["parent_code"], section=r["section"], section_end=r["section_end"],
                    heading_path=r["heading_path"] or "", text=r["text"], url=r["url"],
                    valid_from=r["valid_from"], valid_to=r["valid_to"], in_force=bool(r["in_force"]),
                    score=-float(r["score"]),  # bm25() is lower-is-better; expose higher-is-better
                )
            )
            if len(hits) >= k:
                break
        return hits

    def _rows(self, match: str, k: int, include_expired: bool) -> list[sqlite3.Row]:
        today = self._today().isoformat()
        sql = f"""
            SELECT c.id, c.doc_code, c.section, c.section_end, c.heading_path, c.text,
                   d.name, d.doc_type, d.parent_code, d.url, d.valid_from, d.valid_to,
                   bm25(chunks_fts, {', '.join(map(str, BM25_WEIGHTS))}) AS score,
                   ((d.valid_from IS NULL OR d.valid_from <= :today)
                    AND (d.valid_to IS NULL OR d.valid_to >= :today)) AS in_force
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN docs d ON d.code = c.doc_code
            WHERE chunks_fts MATCH :match
              AND (:include_expired OR in_force)
            ORDER BY score
            LIMIT :limit
        """
        with self._connect() as conn:
            return conn.execute(
                sql, {"match": match, "today": today, "include_expired": int(include_expired), "limit": k * 4}
            ).fetchall()

    def search_many(self, queries: Iterable[str], k: int = 8, include_expired: bool = False,
                    keep_primary: int = 5) -> list[Hit]:
        """Run several phrasings: the user's own query first, LLM rewrites after.

        The top `keep_primary` hits of the first (original) query are always kept;
        rewrites only fill the remaining slots, merged with reciprocal rank fusion.
        Rewrites can add recall but must not push out precise matches: a rewrite
        using a term the instructions don't use ("חתימה אלקטרונית") once displaced
        the exact section on "חתימה דיגיטלית".
        """
        queries = list(queries)
        if not queries:
            return []
        primary = self.search(queries[0], k, include_expired)
        fused: dict[int, float] = {}
        by_id: dict[int, Hit] = {}
        for query_hits in [primary] + [self.search(q, k, include_expired) for q in queries[1:]]:
            for rank, hit in enumerate(query_hits):
                fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
                by_id.setdefault(hit.chunk_id, hit)
        result = primary[:keep_primary]
        chosen = {h.chunk_id for h in result}
        for chunk_id in sorted(fused, key=fused.get, reverse=True):
            if len(result) >= k:
                break
            if chunk_id not in chosen:
                result.append(by_id[chunk_id])
                chosen.add(chunk_id)
        return result

    def related(self, doc_codes: Iterable[str], include_expired: bool = False) -> dict[str, list[dict[str, Any]]]:
        """Messages / temporary instructions attached to the given documents (and to their parents)."""
        codes = list(dict.fromkeys(doc_codes))
        if not codes:
            return {}
        today = self._today().isoformat()
        with self._connect() as conn:
            parents = {
                r["code"]: r["parent_code"]
                for r in conn.execute(
                    f"SELECT code, parent_code FROM docs WHERE code IN ({','.join('?' * len(codes))})", codes
                )
            }
            roots = {c: (parents.get(c) or c) for c in codes}
            rows = conn.execute(
                f"""SELECT code, name, doc_type, parent_code, url, valid_to,
                           ((valid_from IS NULL OR valid_from <= ?) AND (valid_to IS NULL OR valid_to >= ?)) AS in_force
                    FROM docs WHERE parent_code IN ({','.join('?' * len(set(roots.values())))})
                    ORDER BY code""",
                [today, today, *set(roots.values())],
            ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {}
        for code, root in roots.items():
            items = [
                {"code": r["code"], "name": r["name"], "doc_type": r["doc_type"], "url": r["url"],
                 "valid_to": r["valid_to"], "in_force": bool(r["in_force"])}
                for r in rows
                if r["parent_code"] == root and r["code"] != code and (include_expired or r["in_force"])
            ]
            if items:
                out[code] = items
        return out

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        return {"docs": docs, "chunks": chunks, "built_at": meta.get("built_at", "").strip('"')}
