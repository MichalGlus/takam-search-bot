"""Retrieval quality regression gate on data/eval.jsonl."""

import json

from takam_search.evaluate import evaluate, load_eval, site_search


def test_recall_at_5_does_not_regress(settings, retriever):
    docs = json.loads(settings.manifest_path.read_text(encoding="utf-8"))["documents"]
    rows, summary = evaluate(retriever, load_eval(settings.eval_path), docs, k=5)
    misses = [r["query"] for r in rows if r["rank"] is None]
    assert summary["recall@5"] >= 0.9, misses


def test_site_baseline_matches_site_behaviour():
    docs = [{"code": "A", "name": "התחייבות בשם המדינה", "keywords": "חתימה, מורשי חתימה",
             "description": "1.3.1", "documentcodetext": "H.1.3.1"}]
    assert site_search("מורשי חתימה", docs) == ["A"]  # all words in one field
    assert site_search("חתימה דיגיטלית", docs) == []  # body text is not searched
    assert site_search("חתימה המדינה", docs) == []  # words split across fields: no match
