"""Retrieval evaluation: recall@k on data/eval.jsonl, compared with the site's own search.

    takam-eval [--k 5] [--min-recall 0.8]

The site baseline reimplements the site's client-side filter (filterByFreeTxt ->
multiSearchAnd in main.*.js): every query word must be a substring of ONE of
name / description / keywords / documentcodetext. It is run on the same
documents as the POC. The site does not rank results, so for the site we count
"expected document appears in the results at all", which favours the site.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import get_settings
from .retriever import Retriever

SITE_FIELDS = ("name", "description", "keywords", "documentcodetext")


def load_eval(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def site_search(query: str, documents: list[dict[str, Any]]) -> list[str]:
    words = [w for w in query.split(" ") if w]
    out = []
    for doc in documents:
        if any(doc.get(f) is not None and all(w in doc[f] for w in words) for f in SITE_FIELDS):
            out.append(doc["code"])
    return out


def evaluate(retriever: Retriever, items: list[dict[str, Any]], documents: list[dict[str, Any]], k: int = 5):
    rows = []
    for item in items:
        hits = retriever.search(item["query"], k=k, include_expired=True)
        ranked_docs = list(dict.fromkeys(h.doc_code for h in hits))
        expected = set(item["expected"])
        rank = next((i + 1 for i, code in enumerate(ranked_docs) if code in expected), None)
        site = site_search(item["query"], documents)
        rows.append({
            "query": item["query"],
            "expected": item["expected"],
            "rank": rank,
            "top": ranked_docs[:3],
            "site_found": bool(expected & set(site)),
            "site_results": len(site),
        })
    n = len(rows) or 1
    summary = {
        "n": len(rows),
        "k": k,
        f"recall@{k}": sum(r["rank"] is not None for r in rows) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "site_found_any_rank": sum(r["site_found"] for r in rows) / n,
    }
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="takam-eval")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=None, help="exit 1 if recall@k is below this")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    rows, summary = evaluate(Retriever(settings.db_path), load_eval(settings.eval_path),
                             manifest["documents"], args.k)
    for r in rows:
        mark = f"#{r['rank']}" if r["rank"] else "MISS"
        site = "found" if r["site_found"] else f"miss ({r['site_results']} results)"
        print(f"{mark:>5}  site: {site:<18} {r['query']}  -> expected {r['expected']}, got {r['top']}")
    print(json.dumps(summary, ensure_ascii=False))
    if args.min_recall is not None and summary[f"recall@{args.k}"] < args.min_recall:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
